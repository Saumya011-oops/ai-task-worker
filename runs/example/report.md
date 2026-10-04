# Run report — SUCCESS
**Task:** Find the latest invoice from Northwind Supplies, extract the amount and due date, enter it into our ERP, and tell me once it's done.
**Summary:** Successfully found the latest invoice from Northwind Supplies (INV-NS-1043), recorded it as bill BILL-004 in AcmeERP, and confirmed it appears in the ERP bills list.
**Stats:** steps=24, llm_calls=27, recoveries=0, verify_rounds=1

## Success criteria
| Criterion | Result | Evidence |
|---|---|---|
| Every copied field (vendor, invoice number, invoice date, amount (INR, 2 decimals), due date, and PDF filename in notes) in AcmeERP equals the value in the source PDF document, exactly. | PASS | Bill BILL-004 in AcmeERP has vendor_id V001 (Northwind Supplies), invoice_number INV-NS-1043, invoice_date 2026-09-29, amount 48250.0, due_date 2026-10-29, and notes 'INV-NS-1043.pdf', which match the source PDF (Invoice Number: INV-NS-1043, Vendor: Northwind Supplies, Invoice Date: 29 Sep 2026 -> 2026-09-29, Amount Due: INR 48,250.00 -> 48250.00, Due Date: 29 Oct 2026 -> 2026-10-29, PDF filename INV-NS-1043.pdf in notes). |
| No duplicate record with the same vendor_id and invoice_number exists in AcmeERP before creation. | PASS | Checking the initial bills list (BILL-001 to BILL-003), none had vendor_id 'V001' and invoice_number 'INV-NS-1043'. |
| The bill is confirmed to appear in the AcmeERP bills list after saving. | PASS | Bill BILL-004 appears in the erp_list_bills() output with all correct details. |

## Key facts
- `vendor_id` = V001  _(source: ERP vendors list V001, step 7)_
- `invoice_number` = INV-NS-1043  _(source: downloads/INV-NS-1043.pdf, step 8)_
- `invoice_date` = 2026-09-29  _(source: downloads/INV-NS-1043.pdf, step 9)_
- `amount_inr` = 48250.00  _(source: downloads/INV-NS-1043.pdf, step 10)_
- `due_date` = 2026-10-29  _(source: downloads/INV-NS-1043.pdf, step 11)_

## Recoveries
- none

## Evidence
- trace: `trace.jsonl`
- `screenshots/001_goto.png`
- `screenshots/002_read_page.png`
- `screenshots/003_click.png`
- `screenshots/004_read_page.png`
- `screenshots/005_download.png`
- `screenshots/012_goto.png`
- `screenshots/013_read_page.png`
- `screenshots/014_select.png`
- `screenshots/015_type.png`
- `screenshots/016_type.png`
- `screenshots/017_type.png`
- `screenshots/018_type.png`
- `screenshots/019_type.png`
- `screenshots/020_click.png`
- `screenshots/021_read_page.png`