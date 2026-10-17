"""Worker tests reuse the engine fixtures (fake connector and factories)."""

import importlib.util
from pathlib import Path

_path = Path(__file__).parent.parent / "engine" / "conftest.py"
_spec = importlib.util.spec_from_file_location("_engine_fixtures", _path)
_module = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_module)

fake = _module.fake
ws = _module.ws
make_connection = _module.make_connection
make_action = _module.make_action
make_operator = _module.make_operator
