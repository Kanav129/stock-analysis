import os

from dotenv import load_dotenv
from pymongo import ASCENDING, DESCENDING, MongoClient

from utils.logger import logger

# Load environment variables from .env file
load_dotenv()

class MongoDBClient:
    _instance = None

    def __new__(cls, *args, **kwargs):
        if not cls._instance:
            cls._instance = super(MongoDBClient, cls).__new__(cls, *args, **kwargs)
        return cls._instance

    def __init__(self, uri=None, database_name=None):
        if not hasattr(self, '_initialized'):  # Prevent reinitialization in the singleton
            # Load default values from environment variables if not provided
            self.uri = uri or os.getenv('MONGO_URI', 'mongodb://localhost:27017/')
            self.database_name = database_name or os.getenv('DATABASE_NAME', 'default_db')
            # Lazy connect: do not force a handshake here (Render needs PORT bound first).
            self.client = MongoClient(self.uri)
            self.db = self.client[self.database_name]
            self._indexes_ensured = False
            self._indexes_attempted = False
            self._initialized = True

    def get_collection(self, collection_name=None):
        """Retrieve a collection."""
        # Load default collection name from environment variables if not provided
        collection_name = collection_name or os.getenv('COLLECTION_NAME', 'default_collection')
        self.ensure_indexes(collection_name)
        return self.db[collection_name]

    def ensure_indexes(self, collection_name=None) -> None:
        """Create indexes used by news load and RAG sync paths (best-effort)."""
        if self._indexes_ensured or self._indexes_attempted:
            return
        self._indexes_attempted = True
        try:
            collection = self.db[
                collection_name or os.getenv("COLLECTION_NAME", "default_collection")
            ]
            collection.create_index(
                [("ticker", ASCENDING), ("posted", DESCENDING)],
                name="ticker_posted",
            )
            collection.create_index([("synced", ASCENDING)], name="synced")
            self._indexes_ensured = True
        except Exception as exc:
            # Never fail process startup if Atlas is slow/unreachable; queries still work.
            logger.warning(f"Mongo index ensure skipped: {exc}")

    def insert_one(self, collection_name, document):
        """Insert a single document into a collection."""
        collection = self.get_collection(collection_name)
        result = collection.insert_one(document)
        return result.inserted_id

    def insert_many(self, collection_name, documents):
        """Insert multiple documents into a collection."""
        collection = self.get_collection(collection_name)
        result = collection.insert_many(documents)
        return result.inserted_ids

    def find(self, collection_name, query={}, projection=None):
        """Retrieve documents from a collection."""
        collection = self.get_collection(collection_name)
        return list(collection.find(query, projection))

    def update_one(self, collection_name, query, update, upsert=False):
        """Update a single document in a collection."""
        collection = self.get_collection(collection_name)
        result = collection.update_one(query, update, upsert=upsert)
        return result.modified_count

    def update_many(self, collection_name, query, update, upsert=False):
        """Update multiple documents in a collection."""
        collection = self.get_collection(collection_name)
        result = collection.update_many(query, update, upsert=upsert)
        return result.modified_count

    def delete_one(self, collection_name, query):
        """Delete a single document from a collection."""
        collection = self.get_collection(collection_name)
        result = collection.delete_one(query)
        return result.deleted_count

    def delete_many(self, collection_name, query):
        """Delete multiple documents from a collection."""
        collection = self.get_collection(collection_name)
        result = collection.delete_many(query)
        return result.deleted_count
