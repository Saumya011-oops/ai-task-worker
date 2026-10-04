# 07 — Prompt to paste into Claude Code / Cursor to build fast

> Build the project described in `docs/01_PRD.md`, `docs/02_ARCHITECTURE.md`, `docs/03_DESIGN_DECISIONS.md` and `docs/04_TEST_SCENARIOS.md` in this repo. Follow the repo layout in Architecture §8 exactly. Python 3.11.
>
> Build order, and stop after each phase so I can test:
> 1. `sandbox/`: a FastAPI app on port 8000. `/mail` has an inbox list, an email detail page and attachment download. `/erp` has a login page, vendors, a bills list, a "New Bill" form (vendor select, invoice number, invoice date, amount, due date, notes) with server-side validation and a success message, plus a JSON API `/erp/api/bills` and `/erp/api/vendors` (read-only, same session or an API token). `seed.py` creates SQLite data and generates the invoice PDFs with reportlab exactly as in the seed-data table. `chaos.py` middleware is enabled by `CHAOS=1`: the first POST to `/erp/bills` returns 500, the session expires after the 3rd ERP page view, and the save button label changes to "Create bill".
> 2. `tools/`: browser tools on Playwright with `read_page` doing the JS element tagging described in Architecture §3, plus files, erp_api and human (Rich prompt). `registry.py` exports JSON tool schemas. Every tool returns an `Observation` with an `error_class`.
> 3. `llm/client.py`: a provider adapter (gemini | openai | anthropic from `.env`) with native tool calling, returning an `Action`.
> 4. `agent/`: understand, planner, loop, policy_gate (reads `company/policies.yaml`), recovery (retries, relogin skill, is_stuck), memory (facts plus `trace.jsonl` plus screenshots), verifier (fresh context, read-only tools, deterministic checks first), report (md plus html).
> 5. `main.py` CLI: `python main.py "<task>" [--chaos] [--headed] [--max-steps N]` with a live Rich trace.
> 6. `tests/` as listed in `04_TEST_SCENARIOS.md`.
>
> Keep the code simple, typed and commented. No LangChain/LangGraph. Never hard-code task-specific logic (no "invoice" logic in the agent or tools). Everything task-specific must come from the prompt or `company/`.
