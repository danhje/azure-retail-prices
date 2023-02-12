"""This module can fetch retail prices from the Azure API."""
import asyncio
from time import time

import aiohttp
import pandas as pd


class PriceCrawler:
    """Class for crawling the Azure Retail Price API."""

    def __init__(self, query: str | None = None, stop_after: int | None = None):
        """Initialize the crawler.

        Arguments:
            stop_after: Don't start new API calls after this many prices have been fetched.
                Calls that are already in progress will still complete, meaning that the
                total number of prices fetched might be slightly higher than this number.
        """
        self._session = None
        self._tasks = []
        self._reached_end = False
        self._url = "https://prices.azure.com/api/retail/prices?api-version=2021-10-01-preview"
        self._query = query or (
            "(location eq 'EU West' or location eq 'EU East') "
            "and "
            "(priceType eq 'Consumption' or priceType eq 'Reservation')"
        )
        self._per_page = 100
        self.prices = []
        self._concurrency = 9
        self._print_frequency = 1
        self._lastStatusPrintoutTime = time() - self._print_frequency
        self._stop_after = stop_after or float("inf")
        self._page = 0

    async def _fetch_page(self, page: int) -> list:
        skip = page * self._per_page
        await asyncio.sleep(0.3)  # Need to start new tasks slowly to avoid rate limiting
        async with self._session.get(
            self._url, params={"$filter": self._query, "$skip": skip}
        ) as resp:
            payload = await resp.json()
            try:
                items = payload["Items"]
            except KeyError:
                print(
                    "No data. Maybe you are being rate limited. Or the query is malformed."
                    f"Current skip: {skip}. Payload: {payload}"
                )
                return []
            if len(items) == 0:
                self._reached_end = True
            return items

    def _parse_and_discard_completed_tasks(self):
        for task in self._tasks:
            if task.done():
                self._tasks.remove(task)
                self.prices += task.result()

    def _start_additional_tasks(self):
        while (
            not self._reached_end
            and len(self._tasks) < self._concurrency
            and len(self.prices) < self._stop_after
        ):
            self._tasks.append(asyncio.create_task(self._fetch_page(self._page)))
            self._page += 1

    def _print_status(self, ignore_last_printout_time: bool = False) -> None:
        if (
            ignore_last_printout_time
            or time() - self._lastStatusPrintoutTime > self._print_frequency
        ):
            print(
                f"Running {len(self._tasks)} concurrent API calls, got {len(self.prices)} prices."
            )
            self._lastStatusPrintoutTime = time()

    def _done(self) -> bool:
        if len(self._tasks) == 0 and len(self.prices) > 0:
            return True

    async def _main(self):
        async with aiohttp.ClientSession() as self._session:
            while not self._done():
                self._parse_and_discard_completed_tasks()
                self._start_additional_tasks()
                self._print_status()
                await asyncio.sleep(0.01)
        self._print_status(ignore_last_printout_time=True)

    def fetch_prices(self) -> list[dict]:
        """Fetch prices from the Azure API."""
        asyncio.run(self._main())
        return self.prices


if __name__ == "__main__":
    pc = PriceCrawler(stop_after=None)
    prices = pc.fetch_prices()
    df = pd.DataFrame(prices)
    df.to_hdf("prices.h5", key="prices", format="table", mode="w")
    print("Results saved to 'prices.h5")
