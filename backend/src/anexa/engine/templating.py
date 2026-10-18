"""`{{ expression }}` substitution for action params (rules in docs/api.md).

An expression is a dotted path into the run context; nothing is evaluated.
"""

from __future__ import annotations

import json
import re
from typing import Any

_EXPR = re.compile(r"\{\{(.*?)\}\}", re.DOTALL)


class TemplateError(Exception):
    pass


def resolve(expr: str, context: dict[str, Any]) -> Any:
    expr = expr.strip()
    current: Any = context
    for part in expr.split("."):
        if isinstance(current, dict) and part in current:
            current = current[part]
        elif isinstance(current, list) and part.isdigit() and int(part) < len(current):
            current = current[int(part)]
        else:
            raise TemplateError(f"cannot resolve {{{{ {expr} }}}}")
    return current


def _as_text(value: Any) -> str:
    return value if isinstance(value, str) else json.dumps(value, default=str)


def render(value: Any, context: dict[str, Any]) -> Any:
    """Return a copy of `value` with every template in its strings resolved
    against `context`. Dict keys are left alone."""
    if isinstance(value, str):
        whole = _EXPR.fullmatch(value)
        if whole and "{{" not in whole.group(1):
            return resolve(whole.group(1), context)
        return _EXPR.sub(lambda m: _as_text(resolve(m.group(1), context)), value)
    if isinstance(value, dict):
        return {k: render(v, context) for k, v in value.items()}
    if isinstance(value, list):
        return [render(v, context) for v in value]
    return value
