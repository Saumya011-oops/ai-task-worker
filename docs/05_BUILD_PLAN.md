# 05 — Build Plan (today, deadline 5:30 PM IST)

**Rule for today:** a narrow system that genuinely works is worth more than a broad one. Lock scope at T1 to T6 and do not add features after 4:15 PM.

## Timeline
| Time (IST) | Block | Done when |
|---|---|---|
| 1:15 – 1:30 | Setup: GitHub repo, venv, `pip install -r requirements.txt`, `playwright install chromium`, `.env` with an LLM key | `python -c "import playwright, fastapi"` works and the key is tested |
| 1:30 – 2:15 | **Sandbox**: `sandbox/app.py` (AcmeMail + AcmeERP + JSON API), `seed.py` (SQLite + PDFs via reportlab), `chaos.py` middleware | You can log in, see the inbox, open a PDF, create a bill manually, and `GET /erp/api/bills` shows it |
| 2:15 – 2:45 | **Tools**: browser (`read_page` with element tagging), files, `erp_api`, human, registry plus JSON schemas | A manual script can drive the ERP form using only the tools |
| 2:45 – 3:45 | **Agent core**: llm client, understand, planner, loop, memory, policy gate, recovery | **T1 passes end to end** (top priority) |
| 3:45 – 4:15 | **Verifier + report**, then T2 (chaos), T3 (approval), T4 (clarify), T6 (duplicate) | All pass at least once |
| 4:15 – 4:35 | T5 (CSV generalization), 3 unit tests, fill in the metrics table | `pytest` is green |
| 4:35 – 4:55 | **README**: finalize from `README.md` (most of it is already written), add a screenshot | All submission sections are complete |
| 4:55 – 5:15 | **Demo video** (see `06_DEMO_SCRIPT.md`), upload to YouTube (unlisted) or Drive with "anyone with link" | The link opens in an incognito window |
| 5:15 – 5:25 | Push the final commit, then **submit the Google Form** | The form is submitted by **5:25 at the latest** |

## Cut list (if you are behind, cut in this order)
1. T7 (bank details), already marked as a stretch goal.
2. The HTML report (keep `report.md` only).
3. Unit tests (keep only `test_policy_gate.py`).
4. T5 (CSV). Keep it only if T1 to T4 work.
5. The Understand step as a separate LLM call (merge it into the first planner call).

**Never cut:** the T1 end-to-end run, the verifier, chaos-mode recovery, the approval gate, the README or the video.

## Checkpoints
- **2:45 PM:** the sandbox works by hand. If not, simplify it to plain HTML forms with no CSS.
- **3:45 PM:** T1 passes. If not, stop adding features and debug only T1.
- **4:55 PM:** start recording no matter what. A partial but honest demo beats a missed deadline.

## Pre-build checklist
- [ ] LLM API key works (one test call).
- [ ] GitHub repo created (public).
- [ ] Screen recorder ready (QuickTime / OBS) with the mic tested.
- [ ] The Google Form opened once to see which fields it asks for: https://forms.gle/CeaiXnsQ5oqx4dFx6
- [ ] Resume PDF ready to upload if the form asks for it.
