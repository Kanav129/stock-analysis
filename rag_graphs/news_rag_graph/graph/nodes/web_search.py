import os
from typing import Any, Dict, Optional

from dotenv import load_dotenv
from langchain_core.documents import Document
from langchain_community.tools import TavilySearchResults

from rag_graphs.news_rag_graph.graph.state import GraphState
from utils.logger import logger

load_dotenv()

_web_search_tool: Optional[TavilySearchResults] = None


def _get_web_search_tool() -> Optional[TavilySearchResults]:
    global _web_search_tool
    if _web_search_tool is not None:
        return _web_search_tool
    if not os.getenv("TAVILY_API_KEY"):
        return None
    _web_search_tool = TavilySearchResults(max_results=3)
    return _web_search_tool


def web_search(state: GraphState) -> Dict[str, Any]:
    logger.info("---WEB SEARCH---")
    question = state["question"]
    documents = state["documents"]

    tool = _get_web_search_tool()
    if tool is None:
        logger.warning("TAVILY_API_KEY not set — skipping web search fallback.")
        return {"documents": documents or [], "question": question}

    try:
        tavily_results = tool.invoke({"query": question})
        joined_tavily_result = "\n".join(
            [tavily_result["content"] for tavily_result in tavily_results]
        )
        web_results = Document(page_content=joined_tavily_result)
        if documents is not None:
            documents.append(web_results)
        else:
            documents = [web_results]
    except Exception as exc:
        logger.error(f"Web search failed: {exc}")

    return {"documents": documents or [], "question": question}
