# Project: Autonomous AI Task Worker (CentrAlign AI intern submission)
Deadline: today 5:30 PM IST. Speed > polish. Working > broad.

## Source of truth
Read docs/01_PRD.md, docs/02_ARCHITECTURE.md, docs/03_DESIGN_DECISIONS.md, docs/04_TEST_SCENARIOS.md before coding. Follow the repo layout in Architecture §8 exactly.

## Hard rules
- Python 3.11. No LangChain / LangGraph / CrewAI / browser-use. Custom loop only.
- NEVER put task-specific logic (e.g. "invoice") in agent/ or tools/. Task specifics come only from the prompt or company/.
- Every tool returns agent.types.Observation(ok, data, error_class, screenshot).
- LLM provider comes from .env (LLM_PROVIDER, LLM_MODEL). I am using: <gemini/openai/anthropic>.
- Keep files small, typed, commented. No over-engineering.
- After each phase: run it, show me the output, then stop.
- Sandbox runs on http://localhost:8000. Creds in .env.