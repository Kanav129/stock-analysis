#!/usr/bin/env bash
# Fetch upstream Kronos model code (MIT) into forecast/kronos_model/.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
DEST="$ROOT/forecast/kronos_model"
TMP="$(mktemp -d)"

cleanup() { rm -rf "$TMP"; }
trap cleanup EXIT

if [[ -f "$DEST/kronos.py" && -f "$DEST/module.py" ]]; then
  echo "Kronos model code already present at forecast/kronos_model/"
  exit 0
fi

mkdir -p "$DEST"
git clone --depth 1 https://github.com/shiyu-coder/Kronos.git "$TMP"
cp "$TMP/model/__init__.py" "$TMP/model/kronos.py" "$TMP/model/module.py" "$DEST/"

python3 - "$DEST/kronos.py" <<'PY'
import pathlib
import sys

path = pathlib.Path(sys.argv[1])
text = path.read_text()
text = text.replace("from model.module import *", "from forecast.kronos_model.module import *")
lines = [ln for ln in text.splitlines() if "sys.path.append" not in ln]
path.write_text("\n".join(lines) + "\n")
PY

cat > "$DEST/__init__.py" <<'PY'
from forecast.kronos_model.kronos import Kronos, KronosPredictor, KronosTokenizer

__all__ = ["Kronos", "KronosPredictor", "KronosTokenizer"]
PY

echo "Installed Kronos model code to forecast/kronos_model/"
