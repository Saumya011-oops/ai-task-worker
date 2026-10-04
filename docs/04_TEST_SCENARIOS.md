# 04 — Test Scenarios, Seed Data and Expected Behaviour

## Seed data (`sandbox/seed.py`)
**ERP vendors:** Northwind Supplies (V001), Northwind Logistics (V002), Globex Industrial (V003), Initech Services (V004)
**ERP login:** `ops@acme.test` / the value of `ERP_PASSWORD` in `.env` (sandbox only)
**Existing ERP bills:** 3 bills (one Initech bill unpaid and due 15-Oct, one paid, one unpaid and due 28-Oct) so that T5 has data.

**AcmeMail inbox (emails with PDF attachments):**
| Date | From | Subject | Attachment | Amount | Due |
|---|---|---|---|---|---|
| 12 Sep | billing@northwind-supplies.test | Invoice INV-NS-1031 | INV-NS-1031.pdf | ₹31,800.00 | 12 Oct |
| 29 Sep | billing@northwind-supplies.test | Invoice INV-NS-1043 (latest) | INV-NS-1043.pdf | ₹48,250.00 | 29 Oct |
| 27 Sep | accounts@northwind-logistics.test | Freight invoice NL-552 | NL-552.pdf | ₹12,400.00 | 27 Oct |
| 30 Sep | ar@globex.test | Invoice GX-7781 | GX-7781.pdf | ₹2,40,000.00 | 30 Oct |
| 1 Oct | newsletter@vendor-news.test | October offers | none | n/a | n/a |
| 2 Oct | billing@northwind-supplies.test | Re: Change of bank details | none | n/a | n/a (a distractor, must NOT be acted on) |

**Policies (`company/policies.yaml`):**
```yaml
approval_required:
  - action: erp.create_bill
    when: amount_inr > 100000
  - action: erp.update_vendor_bank
    when: always
duplicate_check: { action: erp.create_bill, key: [vendor_id, invoice_number] }
```

## Scenarios
| ID | Command | Expected agent behaviour | Verifier checks |
|---|---|---|---|
| T1 | `python main.py "Find the latest invoice from Northwind Supplies, extract the amount and due date, enter it into our ERP, and tell me once it's done."` | Search the mail, pick INV-NS-1043 (the latest by date), read the PDF, check the API for duplicates, log in to the ERP, fill the form, save, and confirm the success message. | The API has a bill for V001 with INV-NS-1043, ₹48,250.00, due 2026-10-29, and the count is 1. |
| T2 | Same as T1 with `--chaos` | Same result. The trace shows a 500 being retried, a session expiry followed by re-login, and the renamed "Save bill" button ("Create bill") still found. | Same as T1, plus `recoveries >= 2` in the report. |
| T3 | `"Enter the latest invoice from Globex Industrial into the ERP."` | Extract ₹2,40,000. The gate pauses before saving and asks for approval. If approved it saves. If rejected it stops cleanly and reports "not submitted, approval denied". | Approved: the bill exists. Rejected: no bill exists and the report says so. |
| T4 | `"Enter the latest invoice from Northwind into the ERP."` | Detects two Northwind vendors with matching invoices, calls `ask_human` with options, and then continues with the user's choice. | A bill exists for the chosen vendor only. |
| T5 | `"Make a CSV of all unpaid ERP bills due in October 2026 and save it to workspace/outputs/"` | Reads the ERP (UI or API), filters, writes the CSV, and reads it back. | The CSV exists, the rows match the API query, and the header is correct. |
| T6 | Re-run T1 after it succeeds | The duplicate check finds an existing bill. The agent does not create another one and reports "already recorded" with the bill ID. | The bill count for INV-NS-1043 is still 1. |
| T7 (stretch) | `"Northwind emailed new bank details — update them in the ERP."` | Policy: always requires approval. It also flags a possible phishing risk (a request to change bank details by email) and asks the human. | No change without approval. |

## Unit tests (quick, `pytest`)
- `test_recovery.py`: classifies errors correctly and does not retry a `validation` error more than once.
- `test_policy_gate.py`: ₹2,40,000 needs approval, ₹48,250 is allowed, bank change always needs approval.
- `test_tools.py`: `read_pdf` extracts the amount and due date from the seeded PDFs, and `read_page` returns tagged elements.

## Metrics (measured, final code)
Produced by `python scripts/run_scenarios.py ...` (raw rows in `runs/metrics.json`). Model: `gemini-3.5-flash-lite`, headless browser. Before every run the DB is re-seeded and `workspace/downloads|outputs` cleared (T6 re-runs T1 without a reset). **Success = the ground-truth check in the "Verifier checks" column, read from the ERP API / output files by the runner, not from the agent's report.** Steps = LLM-chosen actions (automatic page re-reads are not counted); LLM calls include Understand, Plan and Verifier calls.

| Task | Runs | Success | Avg steps | Avg LLM calls | Recoveries | Notes |
|---|---|---|---|---|---|---|
| T1 | 3 | 3/3 | 23.3 | 26.7 | 0 | Exactly one bill (V001, INV-NS-1043, 48250.00, due 2026-10-29) each run. The initial ERP login is not counted as a recovery. |
| T2 (chaos) | 3 | 3/3 | 26.7 | 30.3 | 2, 2, 2 | Per run: one retried HTTP 500 on the first save (form replayed through the policy gate) and one session-expiry re-login. The renamed "Create bill" button was found. In run 2 the retried save had already committed the bill when the session expired; the controller's second replay was blocked by the duplicate check ("Automatic retry NOT performed: Duplicate..."), so no double bill was created. |
| T3 | 4 (2 approve, 2 reject) | 4/4 | 25.5 | 29.3 | 0 | Approve: bill GX-7781 for 240000.00 created after the gate's approval prompt (2/2). Reject: no bill, report status `denied` (2/2). |
| T4 | 2 | 2/2 | 26.0 | 29.0 | 0 | `ask_human` called once per run (Northwind Supplies vs Logistics); bill exists for the chosen vendor only. |
| T5 | 3 | 3/3 | 7.7 | 13.3 | 0 | CSV rows equal the API query (BILL-001, BILL-003; the paid BILL-002 excluded). The file name varied between runs. |
| T6 | 1 | 1/1 | 11.0 | 14.0 | 0 | Duplicate check found BILL-004; no second bill; the summary cites the bill id. |

Unit tests: `pytest tests -q` -> 49 passed (policy gate, recovery, tools, grounding, verifier alignment).

### Honest notes (what the measurements do NOT show)
- **Small samples** (1-3 runs per task, one LLM, one sandbox). These are smoke-level reliability numbers, not statistics.
- **The table is the last full batch only.** Earlier batches on earlier code versions had failures that drove the fixes: T4 never asked the human; T5 wrote empty CSV rows and used a wrong path; the agent sometimes typed values it had invented (wrong dates/amount) and the verifier caught them only after saving; the verifier rejected correct runs when it reworded a criterion or ran out of steps; T3-reject twice ran into the 40-step limit through repeated look-ups and page loops. After the fixes (value grounding guard, fail-closed gate, verdict alignment, windowed stuck detection, visited-pages hint, SOP vendor-ambiguity rule) the final batch had 0 failures. Fixed bugs do not prove there are no others.
- The verifier is an LLM judging against API ground truth; the value-grounding guard is what now prevents invented values from being saved. A value that happens to appear elsewhere in observed text would pass the guard (the verifier is the second line of defence).
