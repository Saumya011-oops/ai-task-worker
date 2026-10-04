# 03 — Design Decisions (ADR-style)

Each decision below gives the choice, the alternatives considered, and why. These are the "why did you build it this way" answers for the technical discussion.

### D1. A custom controller loop instead of LangChain/LangGraph/CrewAI
- **Choice:** A plain Python loop (~200 lines) with native LLM tool calling.
- **Alternatives:** LangGraph, LangChain AgentExecutor, CrewAI, browser-use.
- **Why:** The evaluation rewards *understanding* and *debuggability*. With my own loop, every retry, gate and replan is explicit code I can explain and change live in the interview. Frameworks hide the control flow and add abstraction that I would have to debug under time pressure.
- **Trade-off:** I re-implement small things (message history, tool schemas). That is acceptable at this size.

### D2. The LLM is the policy, the controller owns safety and retries
- **Choice:** The LLM only proposes the next action. Deterministic code enforces policies, retries transient errors, detects loops and decides when work is "done" (through the verifier).
- **Why:** LLMs are unreliable at counting retries, following hard limits and judging their own success. Putting this in code makes the system **predictable and auditable**, which an AI *employee* needs.

### D3. Observe the page through a tagged accessibility-style text snapshot, not screenshots
- **Choice:** JavaScript tags the interactive elements with IDs and returns a compact text list (see Architecture §3).
- **Alternatives:** Screenshot plus a vision model (pixel computer use), raw HTML.
- **Why:** It is around 10x fewer tokens than HTML, faster and cheaper than vision, deterministic element targeting, and resilient to CSS changes. A renamed button is still found by its label.
- **Trade-off:** It does not work on canvas or desktop apps. The tool interface is written so that a vision-based `computer` tool can be added later without changing the loop.

### D4. Independent verifier with fresh context
- **Choice:** After the agent calls `finish`, a separate verifier gets only the success criteria plus **read-only** tools and checks the real system state (the ERP API, files). Deterministic value checks run first.
- **Alternatives:** Trust the agent's own "done", or self-reflection in the same context.
- **Why:** An agent that grades itself in the same context tends to confirm its own beliefs. A fresh context reading ground truth catches false completions, which addresses the "Verification" criterion directly.

### D5. Understand step: convert the task into a TaskSpec with explicit success criteria
- **Why:** "Tell me once it's done" only becomes checkable once "done" is defined, for example *a bill exists in the ERP for vendor X with amount A, due date D and invoice number N, and no duplicate exists*. The same criteria drive the planner, the verifier and the final report, so there is one source of truth.

### D6. Typed error taxonomy plus layered recovery
- **Choice:** Each tool result is classified (`transient | auth | not_found | validation | policy | ambiguous | fatal`). Cheap mechanical recoveries (retry, re-login) happen in code. Semantic recoveries (a different element, fixing input, replanning) go to the LLM. Unresolvable cases go to the human.
- **Why:** This avoids wasting LLM calls on network blips and avoids endless loops. It is easy to explain and to test with chaos mode.

### D7. Company knowledge as files (SOP markdown plus policies.yaml)
- **Choice:** The agent loads `company/` into the Understand step. Hard rules (approval thresholds) are **also** enforced by `policy_gate` in code.
- **Why:** This matches CentrAlign's vision that agents are "personalized around each company's processes". It uses the LLM for soft guidance and code for hard rules, so the agent cannot talk itself past a limit.

### D8. Human-in-the-loop as a first-class tool
- **Choice:** `ask_human` is a normal tool the policy can call (for clarification), and the gate can force it (for approval). All answers are logged in the trace.
- **Why:** "Ask when it cannot safely proceed" is a required capability. Making it a tool means the same loop handles it, with no special cases.

### D9. Simulated company apps that I built (FastAPI + SQLite) with chaos mode
- **Alternatives:** Real SaaS sandboxes (Gmail, Zoho), public demo sites.
- **Why:** The brief forbids real credentials. My own sandbox gives deterministic, repeatable demos **and** lets me inject realistic failures on demand to prove reliability. The agent still interacts with it exactly like a real web app, through a real browser.

### D10. Provider-agnostic LLM adapter
- **Choice:** `llm/client.py` exposes `next_action(messages, tools)`. The default model is set in `.env`.
- **Why:** It avoids lock-in, lets the same tasks run on a cheaper or stronger model, and gives a simple way to compare models (a natural next step: an evaluation harness).

### D11. Evidence-first reporting
- **Choice:** Every action is written to `trace.jsonl` (thought, tool, args, observation, timing), with a screenshot after each browser action, plus a final `report.html`.
- **Why:** An AI employee must be **auditable**. A reviewer can see exactly what was done and why, and it makes debugging during the live interview trivial.

### D12. CLI plus an HTML report instead of a full web UI
- **Why:** With a 4-hour budget, time goes into autonomy and reliability, which are evaluated, not UI polish, which is not. The headed browser plus the live Rich trace make a clear demo video.

### D13. Value-grounding guard: typed data must come from something the worker actually observed
- **Choice:** before a `type`/`select` runs, any data-like value (contains a digit: amounts, dates, ids) must appear in the task text or in a real tool result or page snapshot (`agent/grounding.py`). Otherwise the action is blocked with "re-read the source and copy exactly". The worker's own `remember` echoes and the guard's own messages are excluded from the evidence, so a wrong value cannot ground itself. Dates and amounts match across notations (`2026-10-29` = `29 Oct 2026`, `48250.00` = `INR 48,250.00`).
- **Alternatives:** rely on the verifier alone; trust the model to copy values.
- **Why:** testing showed the small model sometimes typed invented dates/amounts. The verifier caught them, but only after the wrong record was saved. Blocking before the write prevents the damage.
- **Trade-off:** a wrong value that happens to occur elsewhere in observed text passes the guard (the verifier is the second line of defence). Plain words without digits are not checked.

### D14. A fail-closed policy gate
- **Choice:** the gate treats anything it cannot prove safe as unsafe: Enter-key submits and any button on a trigger page (including renamed buttons) are gated; a failed or unparseable duplicate lookup -> **block**; a missing/unreadable amount -> **needs approval**; approval needs the exact answer `approve`; and automatic form replays after a transient/auth failure go through the gate again (so a retry cannot double-submit a bill that was already saved).
- **Alternatives:** fail open (allow when the check errors); gate only on the exact button label.
- **Why:** a gate that disappears when the API hiccups, or when a button is renamed, is not a control. Chaos mode made these paths real: in a T2 run the retried save had already committed when the session expired, and only the re-gated replay prevented a duplicate.
- **Trade-off:** more blocks and more human questions when a lookup is flaky. That is the intended direction for money-moving actions.

### D15. Success is measured from ground truth, not from the agent's report
- **Choice:** the scenario runner (`scripts/run_scenarios.py`) resets the DB, scripts the human answers and then reads the ERP API / output files itself to decide pass or fail. The agent's `report.md` is data, not the verdict. The in-run verifier likewise judges against API snapshots and the re-read source documents, with a controller-written approval audit log.
- **Alternatives:** count "status: success" in the agent's report.
- **Why:** early batches showed reports that said success with wrong values, and correct runs reported as failed by an over-eager verifier. Only an independent check gives honest numbers (see the Results and "How I debugged it" sections in the README).
