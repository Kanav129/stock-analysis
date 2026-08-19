# Code for retrieval node
from typing import Any, Dict
from rag_graphs.news_rag_graph.graph.state import GraphState
from rag_graphs.news_rag_graph.ingestion import get_news_articles_retriever
from utils.logger import logger

def retrieve(state:GraphState)->Dict[str, Any]:
    logger.info("---RETRIEVE---")
    question    = state['question']
    documents   = get_news_articles_retriever().invoke(question)

    return {"documents": documents, "question": question}