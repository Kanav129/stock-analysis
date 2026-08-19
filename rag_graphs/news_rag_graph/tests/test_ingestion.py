from unittest.mock import MagicMock, patch

from langchain_core.documents import Document

from rag_graphs.news_rag_graph.ingestion import DocumentSyncManager


def _manager(tmp_path=None):
    manager = DocumentSyncManager.__new__(DocumentSyncManager)
    manager.mongo_client = MagicMock()
    manager.news_collection = MagicMock()
    manager.vector_db_collection = "news_embeddings"
    manager.vector_db_directory = str(tmp_path / "chroma_db") if tmp_path else "./chroma_db"
    return manager


def test_rebuild_vector_store_resets_mongo_wipes_chroma_and_resyncs(tmp_path):
    chroma_dir = tmp_path / "chroma_db"
    chroma_dir.mkdir()
    (chroma_dir / "chroma.sqlite3").write_text("stale-1536")

    manager = _manager(tmp_path)
    manager.news_collection.update_many.return_value = MagicMock(modified_count=12)

    with patch.object(manager, "sync_documents") as sync:
        manager.rebuild_vector_store()

    manager.news_collection.update_many.assert_called_once_with(
        {},
        {"$set": {"synced": False}},
    )
    assert not chroma_dir.exists()
    sync.assert_called_once()


def test_sync_documents_indexes_in_batches_and_marks_each_batch():
    manager = _manager()
    batch_one = [
        {"_id": 1, "description": "first article"},
        {"_id": 2, "description": "second article"},
    ]
    batch_two = [{"_id": 3, "description": "third article"}]
    manager.fetch_unsynced_documents = MagicMock(
        side_effect=[batch_one, batch_two, []],
    )

    with (
        patch.object(
            manager,
            "process_content",
            side_effect=lambda texts: [Document(page_content=text) for text in texts],
        ),
        patch.object(manager, "store_documents_in_chroma") as store,
        patch.object(manager, "mark_documents_as_synced") as mark,
        patch(
            "rag_graphs.news_rag_graph.ingestion.VECTOR_SYNC_BATCH_SIZE",
            2,
        ),
    ):
        manager.sync_documents()

    assert store.call_count == 2
    assert mark.call_count == 2
    mark.assert_any_call([1, 2])
    mark.assert_any_call([3])
    assert manager.fetch_unsynced_documents.call_args_list[0].kwargs["limit"] == 2
