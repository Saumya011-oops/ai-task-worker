"""Shared data contracts (docs/02_ARCHITECTURE.md §4). Every module imports from here."""
from __future__ import annotations

from typing import Any, Literal, Optional

from pydantic import BaseModel, Field

# Typed error taxonomy: drives retry / re-login / replan / escalate decisions.
ErrorClass = Optional[
    Literal["transient", "auth", "not_found", "validation", "policy", "ambiguous", "fatal"]
]


class TaskSpec(BaseModel):
    """What the user wants and what 'done' means. Single source of truth for plan + verify."""
    goal: str
    inputs_needed: list[str] = Field(default_factory=list)
    success_criteria: list[str] = Field(default_factory=list)
    risky_actions: list[str] = Field(default_factory=list)
    assumptions: list[str] = Field(default_factory=list)
    open_questions: list[str] = Field(default_factory=list)


class PlanStep(BaseModel):
    id: int
    description: str
    status: Literal["todo", "doing", "done", "failed", "skipped"] = "todo"


class Action(BaseModel):
    """One LLM-proposed tool call."""
    thought: str = ""
    tool: str
    args: dict[str, Any] = Field(default_factory=dict)
    plan_update: Optional[list[PlanStep]] = None


class Observation(BaseModel):
    """Uniform result of every tool call."""
    ok: bool
    data: str = ""
    error_class: ErrorClass = None
    screenshot: Optional[str] = None  # path to a PNG, if the tool took one


class Fact(BaseModel):
    """A remembered piece of working-memory, with provenance."""
    key: str
    value: str
    source: str = ""
    step: int = 0


class Verdict(BaseModel):
    """Verifier result for one success criterion."""
    criterion: str
    passed: bool
    evidence: str = ""
