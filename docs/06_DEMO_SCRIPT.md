# 06 — Demo Video Script (target 4–5 min) + Interview Prep

## Recording layout
Left: the terminal with the live Rich trace. Right: the headed Chromium window (`--headed`). At the end, open `runs/<id>/report.html`.

## Script
1. **0:00–0:30 Intro.** "I'm Saumya. This is an autonomous AI task worker. It takes a plain-English task, operates real web apps in a browser, recovers from failures, asks me when it must, and verifies the result before saying it's done. Everything runs against a sandbox company I built, Acme Retail, with a mail app and an ERP."
2. **0:30–1:00 Architecture.** Show the mermaid diagram from the README. Say one line: "Deterministic controller, LLM as policy, independent verifier."
3. **1:00–2:00 T1.** Run it. Point at: the TaskSpec success criteria, the plan, it picking the *latest* invoice, the PDF extraction, the duplicate check and the form fill.
4. **2:00–2:45 T2 chaos.** Run with `--chaos`. Pause on the 500 retry, the session-expired re-login and the renamed button.
5. **2:45–3:30 T3 approval + T4 clarification.** Show the gate pausing for ₹2,40,000. Approve. Show the "Which Northwind?" question.
6. **3:30–4:00 T5 generalization.** A different task with the same code, producing the CSV.
7. **4:00–4:30 Verification and evidence.** Open `report.html`: the criteria table, the screenshots, the trace.
8. **4:30–4:50 Limitations and next steps** (one sentence each).

## Likely interview questions (prepare 2-line answers)
- Why no LangGraph? (D1: control, debuggability, explainability.)
- How do you stop the agent from looping forever? (Max steps, `is_stuck` detection, forced replan, then human.)
- How do you know it's actually done? (TaskSpec criteria, fresh-context verifier, deterministic API checks.)
- What if the ERP UI changes? (Label-based element tagging, `not_found` leads to re-read and re-pick, demonstrated in chaos mode.)
- What if the PDF is a scanned image? (Next step: an OCR fallback tool. The verifier would flag low-confidence extraction for human review.)
- How would this generalize to desktop apps? (Add a vision-based `computer` tool behind the same tool interface. The loop is unchanged.)
- How would you make it production-grade? (A durable task queue, per-tool permissions, secrets vault, eval harness with regression tasks, and memory learned from human corrections.)
- **Be ready to modify live.** For example: "add a new policy", "add a tool", "change the approval threshold". Know where each lives.
