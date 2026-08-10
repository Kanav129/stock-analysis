from __future__ import annotations

import argparse
import json
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from evals.decision_scoring import build_fixtures
from evals.decision_scoring.invoke_decision import invoke_decision
from evals.decision_scoring.prompts import VARIANTS, get_variant
from evals.decision_scoring.score import aggregate_variant, score_call
from rag_graphs.research_graph.nodes.synthesize_decision import build_decision_context

FIXTURES_DIR = Path(__file__).with_name("fixtures")
RESULTS_DIR = Path(__file__).with_name("results")


def _load_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"Expected a JSON object in {path}")
    return value


def _normalize_csv(value: str | None, defaults: list[str]) -> list[str]:
    if value is None:
        return list(defaults)
    items = [item.strip() for item in value.split(",") if item.strip()]
    if not items:
        raise ValueError("comma-separated selection must not be empty")
    return items


def run_evaluation(
    *,
    variants: list[str],
    tickers: list[str],
    fixtures_dir: Path = FIXTURES_DIR,
    results_dir: Path = RESULTS_DIR,
) -> tuple[Path, dict[str, Any]]:
    """Run every selected prompt variant against every selected frozen fixture."""
    selected_variants = [name.strip() for name in variants]
    selected_tickers = [ticker.strip().upper() for ticker in tickers]
    configs = {name: get_variant(name) for name in selected_variants}
    street_gold = _load_json(fixtures_dir / "street_gold.json")
    gold_by_ticker = street_gold.get("tickers") or {}
    rows: list[dict[str, Any]] = []

    for variant_name, config in configs.items():
        for ticker in selected_tickers:
            fixture = _load_json(fixtures_dir / f"{ticker}.json")
            context = build_decision_context(
                ticker=ticker,
                live_price=fixture["live_price"],
                factor_scores=fixture.get("factor_scores") or {},
                sections=fixture.get("sections_markdown") or {},
                portfolio_markdown=fixture.get("portfolio_markdown") or "",
            )
            invoke = invoke_decision(
                system_prompt=config.system_prompt,
                temperature=config.temperature,
                enable_thinking=config.enable_thinking,
                ticker=ticker,
                context=context,
            )
            row = score_call(invoke, gold_by_ticker.get(ticker) or {})
            rows.append({"variant": variant_name, "ticker": ticker, **row})

    aggregates = {
        name: aggregate_variant(
            [row for row in rows if row["variant"] == name]
        )
        for name in selected_variants
    }
    created_at = datetime.now(timezone.utc)
    payload: dict[str, Any] = {
        "created_at": created_at.isoformat(),
        "street_gold_as_of": street_gold.get("as_of"),
        "variants": selected_variants,
        "tickers": selected_tickers,
        "rows": rows,
        "aggregates": aggregates,
    }
    results_dir.mkdir(parents=True, exist_ok=True)
    output_path = results_dir / created_at.strftime("%Y%m%dT%H%M%S%fZ.json")
    output_path.write_text(
        json.dumps(payload, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    return output_path, payload


def _percent(value: float | None) -> str:
    return "n/a" if value is None else f"{value:.1%}"


def summarize_payload(payload: dict[str, Any]) -> str:
    rows = payload.get("rows") or []
    variants = payload.get("variants") or list(
        dict.fromkeys(row["variant"] for row in rows)
    )
    lines = [
        "| variant | structure_pass_rate | tag_accuracy | target_accuracy | distinct_scores | bullish_skew | notes |",
        "|---|---:|---:|---:|---:|---:|---|",
    ]
    for variant in variants:
        variant_rows = [row for row in rows if row.get("variant") == variant]
        aggregate = aggregate_variant(variant_rows)
        methods = Counter(row.get("schema_method", "unknown") for row in variant_rows)
        notes = ", ".join(
            f"{method}: {count}" for method, count in sorted(methods.items())
        )
        lines.append(
            "| {variant} | {structure} | {tag} | {target} | {scores} | {bullish} | {notes} |".format(
                variant=variant,
                structure=_percent(aggregate["structure_pass_rate"]),
                tag=_percent(aggregate["tag_accuracy"]),
                target=_percent(aggregate["target_accuracy"]),
                scores=aggregate["distinct_scores"],
                bullish=_percent(aggregate["bullish_skew"]),
                notes=notes or "no calls",
            )
        )
    return "\n".join(lines)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Decision-scoring evaluation CLI")
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("build-fixtures", help="refresh frozen evaluation fixtures")
    run_parser = commands.add_parser("run", help="run model evaluations")
    run_parser.add_argument("--variants", help="comma-separated prompt variants")
    run_parser.add_argument("--tickers", help="comma-separated fixture tickers")
    summarize_parser = commands.add_parser("summarize", help="summarize a result JSON")
    summarize_parser.add_argument("path", type=Path)
    return parser


def main() -> None:
    args = _parser().parse_args()
    if args.command == "build-fixtures":
        build_fixtures.write_fixtures(
            build_fixtures.DEFAULT_TICKERS,
            build_fixtures.FIXTURES_DIR,
        )
        return
    if args.command == "summarize":
        print(summarize_payload(_load_json(args.path)))
        return

    variants = _normalize_csv(args.variants, list(VARIANTS))
    tickers = _normalize_csv(args.tickers, build_fixtures.DEFAULT_TICKERS)
    output_path, payload = run_evaluation(variants=variants, tickers=tickers)
    print(summarize_payload(payload))
    print(f"\nResults: {output_path}")


if __name__ == "__main__":
    main()
