"""Step 1: task text + company knowledge -> TaskSpec (one structured LLM call)."""
from __future__ import annotations

from datetime import date
from pathlib import Path

from agent.memory import Memory
from agent.prompts import UNDERSTAND_SYSTEM
from agent.types import TaskSpec
from llm.client import LLMClient

COMPANY = Path(__file__).resolve().parent.parent / "company"


def company_knowledge() -> str:
    """Concatenate every file in company/ (SOPs + policies) as plain text."""
    return "\n\n".join(f"### {p.name}\n{p.read_text()}" for p in sorted(COMPANY.iterdir()) if p.is_file())


def understand(task: str, llm: LLMClient, mem: Memory) -> TaskSpec:
    msg = f"Today: {date.today().isoformat()}\n\nCOMPANY KNOWLEDGE:\n{company_knowledge()}\n\nTASK:\n{task}"
    mem.llm_calls += 1
    return llm.structured([{"role": "user", "content": msg}], TaskSpec, system=UNDERSTAND_SYSTEM)
