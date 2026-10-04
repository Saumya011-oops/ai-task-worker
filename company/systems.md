# Company systems (Acme Retail Pvt Ltd) — where things live
All internal apps run on the company server at http://localhost:8000 (no other ports are used).
- **AcmeMail** (email inbox, no login): http://localhost:8000/mail . It has a search box and each email page lists attachments. To save an attachment use the `download` tool on the attachment link (element id or its URL, e.g. /mail/<id>/attachment/<file>) into workspace/downloads/, then open it with `read_pdf` using the path relative to workspace/ (e.g. downloads/<file>.pdf).
- **AcmeERP** (system of record): http://localhost:8000/erp . Pages: Vendors, Bills, New Bill (form). Login is handled automatically by the controller if the session is missing or expires; do not type credentials yourself.
- **Read-only ERP API tools** (`erp_list_bills`, `erp_list_vendors`) are for lookups and duplicate checks. Create/change records only through the browser UI.
- Local files: the `workspace/` folder (downloads/ and outputs/). Today's date in the company is 4 Oct 2026.
