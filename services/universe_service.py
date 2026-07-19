from services.holdings_service import HoldingsService
from services.watchlist_service import WatchlistService


class UniverseService:
    def __init__(self) -> None:
        self.watchlist = WatchlistService()
        self.holdings = HoldingsService()

    def get_tickers(self) -> list[str]:
        watchlist = set(self.watchlist.tickers())
        holdings = set(self.holdings.current_tickers())
        universe = sorted(watchlist | holdings)
        return universe

    def get_universe_detail(self) -> dict:
        tickers = self.get_tickers()
        return {
            "tickers": tickers,
            "watchlist": self.watchlist.tickers(),
            "holdings": self.holdings.current_tickers(),
        }
