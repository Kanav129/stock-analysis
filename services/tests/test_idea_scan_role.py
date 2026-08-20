from pathlib import Path


def test_idea_scan_rank_and_brief_use_research_role():
    src = (
        Path(__file__).resolve().parents[2] / "services" / "idea_scan_service.py"
    ).read_text(encoding="utf-8")
    assert src.count('role="research"') >= 2
    assert 'role="analysis"' not in src
