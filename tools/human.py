"""Human-in-the-loop + control tools (finish / remember are handled semantically by the controller)."""
from __future__ import annotations

import json
from typing import Any, Callable, Optional

from rich.console import Console
from rich.prompt import Prompt

from agent.types import Observation
from tools._util import fail, ok, schema

_console = Console()
# fn(question, options) -> answer. Inject for tests / non-interactive runs.
_answer_provider: Optional[Callable[[str, Optional[list[str]]], str]] = None


def set_answer_provider(fn: Optional[Callable[[str, Optional[list[str]]], str]]) -> None:
    global _answer_provider
    _answer_provider = fn


class AskHuman:
    name = "ask_human"
    description = ("Ask the human operator a question (clarification, ambiguity, or approval). "
                   "Optionally give a list of options. Blocks until answered.")
    json_schema = schema({
        "question": {"type": "string"},
        "options": {"type": "array", "items": {"type": "string"}, "description": "Optional choices"},
    }, ["question"])

    def run(self, question: str = "", options: list[str] | None = None, **_: Any) -> Observation:
        try:
            if _answer_provider is not None:
                ans = _answer_provider(question, options)
            else:
                _console.print(f"\n[bold yellow]Agent asks:[/] {question}")
                if options:
                    ans = Prompt.ask("Your answer", choices=[str(o) for o in options])
                else:
                    ans = Prompt.ask("Your answer")
            return ok(f"Human answered: {ans}")
        except (EOFError, KeyboardInterrupt):
            return fail("fatal", "No human input available")
        except Exception as e:
            return fail("fatal", f"{type(e).__name__}: {e}")


class Finish:
    name = "finish"
    description = ("Declare the task complete (or impossible). summary: what was done / outcome. "
                   "claims: concrete verifiable claims, e.g. ['Bill BILL-004 created for INV-NS-1043'].")
    json_schema = schema({
        "summary": {"type": "string"},
        "claims": {"type": "array", "items": {"type": "string"}},
    }, ["summary"])

    def run(self, summary: str = "", claims: list[str] | None = None, **_: Any) -> Observation:
        return ok(json.dumps({"summary": summary, "claims": claims or []}))


class Remember:
    name = "remember"
    description = "Store a fact in working memory (key, value, optional source such as a file or URL)."
    json_schema = schema({"key": {"type": "string"}, "value": {"type": "string"}, "source": {"type": "string"}},
                         ["key", "value"])

    def run(self, key: str = "", value: str = "", source: str = "", **_: Any) -> Observation:
        return ok(json.dumps({"key": key, "value": value, "source": source}))


HUMAN_TOOLS = [AskHuman(), Finish(), Remember()]
