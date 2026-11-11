#!/usr/bin/env bash
# Reproduce the 3-claude pipeline end to end. Stops on the first failure.
set -euo pipefail
cd "$(dirname "$0")"
python code/00_extract_public_data.py "$@"
python code/01_clean_data.py
python code/02_audit_original.py          # optional arg: local path to a 1-gemini folder
python code/03_build_exposure.py
python code/04_analyze.py
python code/05_verify_pipeline.py
if command -v node >/dev/null 2>&1; then
  node code/docs/build_manuscript.js
  node code/docs/build_brief.js
  node code/docs/build_review.js
  if command -v soffice >/dev/null 2>&1; then
    (cd documents && soffice --headless --convert-to pdf *.docx >/dev/null)
  fi
fi
python - <<'PY'
import hashlib, json, pathlib
root = pathlib.Path(".")
files = [p for p in sorted(root.rglob("*")) if p.is_file() and not any(s in p.parts for s in ("cache", "__pycache__", "original_snapshot"))
         and p.name != "manifest_sha256.json"]
json.dump({str(p): hashlib.sha256(p.read_bytes()).hexdigest() for p in files}, open("manifest_sha256.json", "w"), indent=1)
print(f"manifest: {len(files)} files")
PY
