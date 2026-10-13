import importlib.util
from pathlib import Path

SCRIPT = Path(__file__).resolve().parent.parent / "scripts" / "export_openapi.py"


def test_openapi_json_is_up_to_date() -> None:
    spec = importlib.util.spec_from_file_location("export_openapi", SCRIPT)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    current = module.TARGET.read_text(encoding="utf-8")
    assert current == module.render(), "run `uv run python scripts/export_openapi.py`"
