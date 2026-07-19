from typing import Any

from db.mongo_db import MongoDBClient


class NewsService:
    def __init__(self) -> None:
        self.mongo_client = MongoDBClient()

    def get_recent_articles(self, ticker: str, limit: int = 10) -> list[dict[str, Any]]:
        ticker = ticker.upper()
        collection = self.mongo_client.get_collection()
        cursor = (
            collection.find(
                {"ticker": ticker},
                {
                    "_id": 0,
                    "headline": 1,
                    "description": 1,
                    "posted": 1,
                    "source": 1,
                    "link": 1,
                },
            )
            .sort("posted", -1)
            .limit(limit)
        )
        return list(cursor)
