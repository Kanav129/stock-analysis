"""The drip script defaults to a live run only when --dry-run is omitted."""
import importlib.util
from pathlib import Path


def _load_script():
    path = Path(__file__).resolve().parents[2] / "scripts" / "av_backfill.py"
    spec = importlib.util.spec_from_file_location("av_backfill_cli", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_script_dry_run_does_not_refresh(monkeypatch, capsys):
    module = _load_script()
    seen: dict[str, bool] = {}

    class _Stub:
        def run(self, *, dry_run: bool = False):
            seen["dry_run"] = dry_run
            return {"dry_run": dry_run, "selected": ["AAPL"], "reason": None}

    monkeypatch.setattr(module, "AvBackfillService", _Stub)
    assert module.main(["--dry-run"]) == 0
    assert seen["dry_run"] is True
    assert "AAPL" in capsys.readouterr().out
