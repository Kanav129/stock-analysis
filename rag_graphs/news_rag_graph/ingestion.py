import os
import shutil
import sys
from typing import List, Optional

from dotenv import load_dotenv
from langchain_chroma import Chroma
from langchain_core.documents import Document
from langchain_text_splitters import RecursiveCharacterTextSplitter

from config.llm_config import get_embeddings
from db.mongo_db import MongoDBClient
from utils.logger import logger

load_dotenv()

VECTOR_SYNC_BATCH_SIZE = int(os.getenv("VECTOR_SYNC_BATCH_SIZE", "200"))

_news_articles_retriever = None


def get_news_articles_retriever():
    """Lazy Chroma retriever so rebuilds can drop the on-disk collection."""
    global _news_articles_retriever
    if _news_articles_retriever is None:
        _news_articles_retriever = Chroma(
            collection_name=os.getenv("VECTOR_DB_COLLECTION"),
            persist_directory=os.getenv("VECTOR_DB_DIRECTORY"),
            embedding_function=get_embeddings(),
        ).as_retriever()
    return _news_articles_retriever


def reset_news_articles_retriever() -> None:
    global _news_articles_retriever
    _news_articles_retriever = None


class DocumentSyncManager:
    def __init__(self):
        self.mongo_client = MongoDBClient()
        self.news_collection = self.mongo_client.get_collection()
        self.vector_db_collection = os.getenv("VECTOR_DB_COLLECTION")
        self.vector_db_directory = os.getenv("VECTOR_DB_DIRECTORY")

    def fetch_unsynced_documents(self, limit: Optional[int] = None):
        """
        Fetches documents from the database where 'synced' is set to False.
        """
        cursor = self.news_collection.find(
            {"synced": False},
            {"_id": 1, "description": 1},
        )
        if limit is not None:
            cursor = cursor.limit(limit)
        return cursor

    def mark_documents_as_synced(self, document_ids: List):
        """
        Marks the provided document IDs as synced in the database.
        """
        result = self.news_collection.update_many(
            {"_id": {"$in": document_ids}},
            {"$set": {"synced": True}},
        )
        logger.info(f"Marked {result.modified_count} documents as synced.")

    def process_content(self, contents: List[str]):
        """
        Processes content into chunks using a text splitter.
        """
        text_splitter = RecursiveCharacterTextSplitter.from_tiktoken_encoder(
            chunk_size=250, chunk_overlap=0
        )
        documents = [Document(page_content=content) for content in contents]
        return text_splitter.split_documents(documents)

    def store_documents_in_chroma(self, doc_splits: List[Document]):
        """
        Stores processed document chunks as embeddings in Chroma.
        """
        Chroma.from_documents(
            documents=doc_splits,
            collection_name=self.vector_db_collection,
            embedding=get_embeddings(),
            persist_directory=self.vector_db_directory,
        )
        logger.info("Documents stored in Chroma.")

    def _clear_persisted_chroma(self) -> None:
        directory = self.vector_db_directory
        if directory and os.path.isdir(directory):
            shutil.rmtree(directory)
            logger.info(f"Removed Chroma persist directory {directory}")
        reset_news_articles_retriever()

    def rebuild_vector_store(self) -> None:
        """Drop the persisted collection and reindex every news article."""
        result = self.news_collection.update_many({}, {"$set": {"synced": False}})
        logger.info(
            "Marked %s documents as unsynced for vector rebuild.",
            result.modified_count,
        )
        self._clear_persisted_chroma()
        self.sync_documents()

    def sync_documents(self):
        """
        Orchestrates the process of syncing unsynced documents:
        - Fetches unsynced documents
        - Processes their content
        - Stores them in Chroma
        - Marks them as synced in the database
        """
        total = 0
        while True:
            unsynced_articles = list(
                self.fetch_unsynced_documents(limit=VECTOR_SYNC_BATCH_SIZE)
            )
            if not unsynced_articles:
                if total == 0:
                    logger.info("No unsynced documents found in MongoDB!")
                else:
                    logger.info("Indexed %s news documents into Chroma.", total)
                return

            document_ids = [article["_id"] for article in unsynced_articles]
            descriptions = []
            for article in unsynced_articles:
                text = (article.get("description") or "").strip()
                if text:
                    descriptions.append(text)

            if descriptions:
                doc_splits = [
                    doc
                    for doc in self.process_content(descriptions)
                    if (doc.page_content or "").strip()
                ]
                if doc_splits:
                    self.store_documents_in_chroma(doc_splits)
            self.mark_documents_as_synced(document_ids)
            total += len(document_ids)
            logger.info(
                "Documents processed, stored, and marked as synced (%s this run).",
                total,
            )


if __name__ == "__main__":
    manager = DocumentSyncManager()
    if "--rebuild" in sys.argv:
        manager.rebuild_vector_store()
    else:
        manager.sync_documents()
