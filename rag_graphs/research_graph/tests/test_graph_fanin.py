from rag_graphs.research_graph.graph import JOIN_CORE, should_run_deep
from rag_graphs.research_graph.state import merge_dicts


def test_merge_dicts_unions_section_keys():
    left = {"market": "m", "fundamentals": "f"}
    right = {"news": "n", "market": "m2"}
    out = merge_dicts(left, right)
    assert out["fundamentals"] == "f"
    assert out["news"] == "n"
    assert out["market"] == "m2"


def test_should_run_deep_routes_from_join():
    assert should_run_deep({"report_type": "core"}) == "synthesize_decision"
    assert should_run_deep({"report_type": "deep"}) == "gather_flows"
    assert JOIN_CORE == "join_core_gathers"
