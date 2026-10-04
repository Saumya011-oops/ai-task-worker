# 01 — Product Requirements: Autonomous AI Task Worker

**Role applied:** AI Engineering Intern, CentrAlign AI
**Author:** Saumya Thacker
**Deadline:** 4 Oct 2026, 5:30 PM IST

---

## 1. Problem (in my words)

In a company, a "simple" request like *"enter the latest invoice from Northwind into the ERP"* hides many unstated steps: find the right email, open the attachment, pull out the right numbers, log into another system, fill a form, follow company rules (approval limits, duplicate checks), and then check that it actually saved. Today a person does all of this by hand and moves between tools.

An LLM that only *answers* doesn't help here. We need a worker that **does the work, checks it, and proves it**.

## 2. Product goal

Give the worker one plain-English task. It should:

1. Work out the **end goal** and what "done" means, without being told every step.
2. **Plan** the steps, then **act** in real (sandboxed) apps: a browser, files and an API.
3. **Observe** every result and choose the next step based on what actually happened.
4. **Recover** from failures (retry, re-login, find an alternative path, replan).
5. **Ask the human** when it is unsure or when company policy needs approval.
6. **Verify** independently that the outcome happened.
7. Return a **short summary plus evidence** (screenshots, record IDs, a step trace).

## 3. Users
- **Primary:** an operations or finance employee who hands over a repetitive multi-tool task.
- **Secondary:** a reviewer or manager who approves risky actions and audits what the worker did.

## 4. Environment (sandbox, no real company systems)
A simulated company, **Acme Retail Pvt Ltd**, runs locally:

| App | What it is | Why it exists |
|---|---|---|
| **AcmeMail** (`/mail`) | Web inbox with vendor emails and PDF invoice attachments | A source of information the agent must search and read |
| **AcmeERP** (`/erp`) | Web ERP with login, a vendor list, a "New Bill" form, a bills list and a JSON API | The system of record the agent must update |
| **Company knowledge** (`company/`) | Markdown SOPs and policies (approval limits, duplicate rule, vendor rules) | Company context the agent must follow |
| **Files** (`workspace/`) | A local folder for downloads and outputs | File tools and report outputs |

The ERP has a **chaos mode** that injects realistic failures: a random HTTP 500, an expired session, a renamed button, and slow loads.

## 5. In scope (MVP for today)
- A natural-language task in, autonomous execution, and a verified result out.
- Tools: browser (Playwright), files (list/read/PDF text/write), ERP read API (used for verification), `ask_human`, `remember`, `finish`.
- A policy-aware approval gate (amount above ₹1,00,000, any change to bank details).
- Clarification when the input is ambiguous (two matching vendors or invoices).
- An independent verifier step before completion.
- A run report: a summary, a success-criteria table, screenshots, `trace.jsonl`.
- **At least 3 different tasks run with zero code changes** (to show generalization).

## 6. Out of scope (stated honestly)
- Real websites, real email or real credentials.
- Desktop (non-browser) app control and pixel-based computer use.
- Multi-user auth, production deployment, or a rich web UI (a CLI plus an HTML report is enough).
- Long-term learning across runs (it is designed for, but not built; see the README "Next steps").

## 7. Demo tasks (each must work)
| # | Task given to the agent | What it shows |
|---|---|---|
| T1 | "Find the latest invoice from Northwind Supplies, extract the amount and due date, enter it into our ERP, and tell me once it's done." | The core loop, multi-tool use, extraction and verification |
| T2 | T1 with `CHAOS=1` (500 on first submit, session expiry, renamed button) | Failure detection, retry, re-login and adaptation |
| T3 | "Enter the latest invoice from Globex Industrial into the ERP." (amount ₹2,40,000) | A policy-driven **human approval** gate |
| T4 | "Enter the latest invoice from Northwind into the ERP." (Northwind Supplies and Northwind Logistics both exist) | **Clarification** instead of guessing |
| T5 | "Make a CSV of all unpaid ERP bills due in October and save it to workspace/outputs." | **Generalization**: a different task with the same code |
| T6 | Re-run T1 | **Duplicate detection**: the agent finds the bill already exists and does not create a second one |

## 8. Success criteria (mapped to CentrAlign's evaluation)
| CentrAlign criterion | How this prototype shows it |
|---|---|
| Autonomy | The task gives only the goal. The agent builds its own plan and finds the inbox, attachment, ERP form and vendor. |
| Execution | Real clicks and typing in a real browser against running apps. Nothing is mocked inside the agent. |
| Reliability | A typed error taxonomy, controller-level retries, a re-login skill, loop detection, replanning, and tested chaos mode. |
| Verification | A separate verifier with fresh context and read-only tools checks each success criterion. Values are cross-checked against the PDF. |
| Generalization | T1 to T6 share the same agent code. Tasks differ only in the prompt. |
| Engineering quality | A small typed codebase, a custom loop with no framework magic, tests for the tools, a structured trace. |
| Product thinking | It follows company SOPs, avoids duplicates, asks before risky actions, and returns evidence rather than chat. |
| Technical understanding | Design decisions are documented with the alternatives that were rejected (`03_DESIGN_DECISIONS.md`). |

## 9. Key metrics I will report in the README
- Task success rate across T1 to T6 (for example, over 3 runs each).
- Average number of steps and LLM calls per task.
- Number of recoveries performed in chaos mode.
- Whether the verifier caught any false "done" claims.
