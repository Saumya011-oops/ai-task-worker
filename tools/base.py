"""Tool protocol + registry. Tools are generic (browser/files/api), never task-specific."""
from __future__ import annotations

from typing import Any, Protocol, runtime_checkable

from agent.types import Observation


@runtime_checkable
class Tool(Protocol):
    name: str
    description: str
    json_schema: dict[str, Any]  # JSON-Schema for the args object: {"type":"object","properties":{...},"required":[...]}

    def run(self, **args: Any) -> Observation: ...


# name -> Tool. Populated by tools/registry.py (kept empty here on purpose).
REGISTRY: dict[str, Tool] = {}


def register(tool: Tool) -> Tool:
    REGISTRY[tool.name] = tool
    return tool


def get(name: str) -> Tool | None:
    return REGISTRY.get(name)


def schemas() -> list[dict[str, Any]]:
    """Provider-neutral tool specs: [{name, description, parameters}]. llm/client.py adapts these."""
    return [{"name": t.name, "description": t.description, "parameters": t.json_schema}
            for t in REGISTRY.values()]
