"""Write the API's OpenAPI document to backend/openapi.json (the frontend generates types from it).

`uv run python scripts/export_openapi.py` writes the file; `--check` exits 1 if it is stale.
"""

import argparse
import json
import sys
from pathlib import Path

from ajs.main import app

TARGET = Path(__file__).resolve().parent.parent / "openapi.json"


def render() -> str:
    return json.dumps(app.openapi(), indent=2, sort_keys=True, ensure_ascii=False) + "\n"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--check", action="store_true", help="fail if openapi.json is out of date")
    args = parser.parse_args()
    text = render()
    if args.check:
        current = TARGET.read_text(encoding="utf-8") if TARGET.exists() else ""
        if current != text:
            print("openapi.json is out of date: run `uv run python scripts/export_openapi.py`")
            return 1
        return 0
    TARGET.write_text(text, encoding="utf-8", newline="\n")
    print(f"wrote {TARGET}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
