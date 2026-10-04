"""Tiny shared helpers for tools: Observation builders, schema builder, workspace root."""
from __future__ import annotations

from pathlib import Path
from typing import Any

from agent.types import ErrorClass, Observation

ROOT = Path(__file__).resolve().parent.parent
WORKSPACE = ROOT / "workspace"


def ok(data: str = "", screenshot: str | None = None) -> Observation:
    return Observation(ok=True, data=data, screenshot=screenshot)


def fail(error_class: ErrorClass, msg: str, screenshot: str | None = None) -> Observation:
    return Observation(ok=False, data=msg, error_class=error_class, screenshot=screenshot)


def schema(props: dict[str, Any], required: list[str] | None = None) -> dict[str, Any]:
    """Build a JSON-Schema object for tool args."""
    return {"type": "object", "properties": props, "required": required or []}


def clip(s: str, n: int = 4000) -> str:
    return s if len(s) <= n else s[:n] + f"... [truncated {len(s) - n} chars]"
