# SOP — Accounts Payable: Recording Vendor Invoices (Acme Retail Pvt Ltd)

1. Vendor invoices arrive by email in AcmeMail as PDF attachments.
2. "Latest invoice" means the most recent invoice by **invoice date** from that exact vendor.
3. Before creating a bill, check the ERP for an existing bill with the same vendor and invoice number. Never create duplicates.
4. Record: vendor, invoice number, invoice date, amount (INR, 2 decimals), due date. Attach the PDF filename in the notes.
5. Bills above ₹1,00,000 require approval from the finance lead before saving.
6. Never change vendor bank details based on an email alone. This always requires human approval (possible fraud).
7. If the vendor name is ambiguous, or the invoice data is unclear, ask a human instead of guessing.
8. After saving, confirm the bill appears in the ERP bills list.
9. Requesters often give a partial vendor name. BEFORE opening any email or entering data, list the ERP vendors (`erp_list_vendors`) and compare the requested name against the FULL vendor names:
   - If the requested text equals one vendor's full name (e.g. "Northwind Supplies"), that vendor is unambiguous: do NOT ask, even if other vendors share a first word.
   - If the requested text is only part of the name and matches MORE THAN ONE vendor (e.g. "Northwind" matches Northwind Supplies and Northwind Logistics), you must `ask_human` which vendor is meant, with the full vendor names as options.
