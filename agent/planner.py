"""Step 2: TaskSpec -> ordered, revisable plan. Also defines the generic `update_plan` control tool."""
from __future__ import annotations

from pydantic import BaseModel

from agent.memory import Memory
from agent.prompts import PLAN_SYSTEM
from agent.types import PlanStep, TaskSpec
from llm.client import LLMClient
from tools import base


class Plan(BaseModel):
    steps: list[PlanStep]


# Control tool handled by the loop itself (not in the tool registry): lets the policy revise the plan.
UPDATE_PLAN_SPEC = {
    "name": "update_plan",
    "description": "Replace the plan with an updated list of steps (mark finished steps 'done', failed ones 'failed', add/remove steps).",
    "parameters": {"type": "object", "properties": {"steps": {"type": "array", "items": {
        "type": "object", "properties": {"id": {"type": "integer"}, "description": {"type": "string"},
                                         "status": {"type": "string", "enum": ["todo", "doing", "done", "failed", "skipped"]}},
        "required": ["id", "description", "status"]}}}, "required": ["steps"]}}


def make_plan(spec: TaskSpec, llm: LLMClient, mem: Memory) -> list[PlanStep]:
    tools = ", ".join(t["name"] for t in base.schemas())
    mem.llm_calls += 1
    plan = llm.structured([{"role": "user", "content": spec.model_dump_json(indent=2)}], Plan,
                          system=PLAN_SYSTEM.format(tools=tools))
    return plan.steps


def apply_update(mem: Memory, steps: list[dict]) -> str:
    mem.plan = [PlanStep(**s) for s in steps]
    return "Plan updated."


def render(plan: list[PlanStep]) -> str:
    mark = {"todo": " ", "doing": ">", "done": "x", "failed": "!", "skipped": "-"}
    return "\n".join(f"[{mark[s.status]}] {s.id}. {s.description}" for s in plan) or "(no plan)"
