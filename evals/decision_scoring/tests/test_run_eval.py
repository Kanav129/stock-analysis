import json
from pathlib import Path
from unittest.mock import patch

import pytest

from evals.decision_scoring.invoke_decision import InvokeResult
from evals.decision_scoring.run_eval import run_evaluation
from evals.decision_scoring.structure import StructureResult


def _successful_invoke() -> InvokeResult:
    return InvokeResult(
        call_ok=True,
        schema_method="function_calling",
        structure=StructureResult(
            parsed_ok=True,
            rating_ok=True,
            score_ok=True,
            reasoning_ok=True,
            drivers_ok=True,
            levels_types_ok=True,
            normalized={"rating": "BUY", "score": 50, "target": 120.0},
        ),
        raw_error=None,
        latency_ms=10.0,
        model="test-model",
    )


@patch("evals.decision_scoring.run_eval.invoke_decision")
def test_run_evaluation_uses_fixtures_and_writes_scored_rows(
    mock_invoke, tmp_path: Path
):
    fixtures_dir = tmp_path / "fixtures"
    results_dir = tmp_path / "results"
    fixtures_dir.mkdir()
    (fixtures_dir / "AAPL.json").write_text(
        json.dumps(
            {
                "ticker": "AAPL",
                "live_price": 100.0,
                "factor_scores": {},
                "sections_markdown": {"fundamentals": "Strong cash flow."},
                "portfolio_markdown": "Not held.",
            }
        )
    )
    (fixtures_dir / "desk_scores.json").write_text(
        json.dumps({"rows": [{"ticker": "MSFT", "score": 11}]})
    )
    (fixtures_dir / "street_gold.json").write_text(
        json.dumps(
            {
                "as_of": "2026-08-10T00:00:00+00:00",
                "tickers": {
                    "AAPL": {
                        "recommendation_key": "buy",
                        "target_mean": 120.0,
                    }
                },
            }
        )
    )
    mock_invoke.return_value = _successful_invoke()

    output_path, payload = run_evaluation(
        variants=["tight_v1"],
        tickers=["AAPL"],
        fixtures_dir=fixtures_dir,
        results_dir=results_dir,
        allow_any_model=True,
    )

    assert output_path.parent == results_dir
    assert json.loads(output_path.read_text()) == payload
    assert payload["aggregates"]["tight_v1"]["structure_pass_rate"] == 1.0
    assert payload["rows"][0]["ticker"] == "AAPL"
    assert payload["rows"][0]["tag_hit"] is True
    assert payload["rows"][0]["target_hit"] is True
    mock_invoke.assert_called_once()
    assert "Strong cash flow." in mock_invoke.call_args.kwargs["context"]
    assert "MSFT +11 (HOLD)" in mock_invoke.call_args.kwargs["context"]


@patch("evals.decision_scoring.run_eval.resolve_analysis_model", return_value="qwen3.7-flash")
def test_run_evaluation_requires_qwen38_max(mock_model, tmp_path: Path):
    with pytest.raises(ValueError, match="qwen3.8-max"):
        run_evaluation(
            variants=["score_first"],
            tickers=["AAPL"],
            fixtures_dir=tmp_path,
            results_dir=tmp_path,
            allow_any_model=False,
        )
