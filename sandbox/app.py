"""AcmeMail + AcmeERP sandbox. Run from project root: uvicorn sandbox.app:app --port 8000"""
import re
import secrets
import sqlite3
from datetime import date, datetime
from pathlib import Path
from typing import Optional

from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parent.parent / ".env")

import os  # noqa: E402
import sys  # noqa: E402

from fastapi import FastAPI, Form, Request  # noqa: E402
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, RedirectResponse  # noqa: E402
from fastapi.templating import Jinja2Templates  # noqa: E402

from sandbox.chaos import Chaos  # noqa: E402
from sandbox.seed import DB_PATH, PDF_DIR, seed_all  # noqa: E402

ERP_USER = os.getenv("ERP_USER", "ops@acme.test")
ERP_PASSWORD = os.getenv("ERP_PASSWORD") or sys.exit("Set ERP_PASSWORD in .env (any value; it is the sandbox ERP login password).")

app = FastAPI()
templates = Jinja2Templates(directory=str(Path(__file__).parent / "templates"))
chaos = Chaos()
sessions: set[str] = set()  # valid erp_session tokens (in memory)

if not DB_PATH.exists():
    seed_all()


def db() -> sqlite3.Connection:
    con = sqlite3.connect(DB_PATH)
    con.row_factory = sqlite3.Row
    return con


def fmt_date(iso: str) -> str:
    d = date.fromisoformat(iso)
    return f"{d.day} {d:%b} {d.year}"


def see_other(url: str) -> RedirectResponse:
    return RedirectResponse(url, status_code=303)


# ---------------------------------------------------------------- misc
@app.get("/health")
def health() -> dict:
    return {"ok": True, "chaos": chaos.enabled}


@app.post("/__reset")
def reset() -> dict:
    seed_all()
    chaos.reset()
    return {"ok": True}


@app.get("/")
def root() -> RedirectResponse:
    return see_other("/mail")


# ---------------------------------------------------------------- mail
def search_emails(q: str) -> list[sqlite3.Row]:
    sql, args = "SELECT * FROM emails", []
    if q:
        sql += " WHERE sender LIKE ? OR subject LIKE ? OR body LIKE ?"
        args = [f"%{q}%"] * 3
    with db() as con:
        return con.execute(sql + " ORDER BY date DESC, id DESC", args).fetchall()


@app.get("/mail")
def mail_inbox(request: Request, q: str = ""):
    rows = [dict(r, date_fmt=fmt_date(r["date"])) for r in search_emails(q.strip())]
    return templates.TemplateResponse(request, "mail_inbox.html", {"emails": rows, "q": q})


@app.get("/mail/api/emails")
def mail_api(q: str = "") -> list[dict]:
    return [{"id": r["id"], "date": r["date"], "from": r["sender"], "subject": r["subject"],
             "attachment": r["attachment"]} for r in search_emails(q.strip())]


@app.get("/mail/{email_id}")
def mail_detail(request: Request, email_id: int):
    with db() as con:
        r = con.execute("SELECT * FROM emails WHERE id=?", (email_id,)).fetchone()
    if not r:
        return templates.TemplateResponse(request, "mail_notfound.html", {}, status_code=404)
    return templates.TemplateResponse(request, "mail_detail.html", {"e": dict(r, date_fmt=fmt_date(r["date"]))})


@app.get("/mail/{email_id}/attachment/{filename}")
def mail_attachment(email_id: int, filename: str):
    with db() as con:
        r = con.execute("SELECT 1 FROM emails WHERE id=? AND attachment=?", (email_id, filename)).fetchone()
    path = PDF_DIR / filename
    if not r or not path.is_file():
        return HTMLResponse("Attachment not found", status_code=404)
    return FileResponse(path, media_type="application/pdf", filename=filename)


# ---------------------------------------------------------------- erp auth
def guard(request: Request, api: bool = False, page: bool = True):
    """Return None if authenticated, else a redirect/401 response. Applies chaos expiry on page views."""
    token = request.cookies.get("erp_session")
    if token not in sessions:
        if api:
            return JSONResponse({"error": "unauthorized"}, status_code=401)
        return see_other("/erp/login?next=" + request.url.path)
    if page and not api and request.method == "GET" and chaos.should_expire_session():
        sessions.discard(token)
        return see_other("/erp/login?next=" + request.url.path)
    return None


@app.get("/erp/login")
def login_page(request: Request, next: str = "/erp/bills"):
    return templates.TemplateResponse(request, "erp_login.html", {"next": next, "error": None, "nav": False})


@app.post("/erp/login")
def login_submit(request: Request, next: str = "/erp/bills", email: str = Form(""), password: str = Form("")):
    if email != ERP_USER or password != ERP_PASSWORD:
        return templates.TemplateResponse(request, "erp_login.html",
                                          {"next": next, "error": "Invalid email or password", "nav": False})
    token = secrets.token_hex(16)
    sessions.add(token)
    target = next if next.startswith("/erp") and not next.startswith("//") else "/erp/bills"
    resp = see_other(target)
    resp.set_cookie("erp_session", token, httponly=True)
    return resp


@app.get("/erp/logout")
def logout(request: Request):
    sessions.discard(request.cookies.get("erp_session", ""))
    resp = see_other("/erp/login")
    resp.delete_cookie("erp_session")
    return resp


# ---------------------------------------------------------------- erp pages
@app.get("/erp")
def erp_root(request: Request):
    return guard(request) or see_other("/erp/bills")


@app.get("/erp/vendors")
def erp_vendors(request: Request):
    if (g := guard(request)):
        return g
    with db() as con:
        rows = con.execute("SELECT * FROM vendors ORDER BY id").fetchall()
    return templates.TemplateResponse(request, "erp_vendors.html", {"vendors": rows, "nav": True})


def bill_dict(r: sqlite3.Row) -> dict:
    return {"id": f"BILL-{r['id']:03d}", "vendor_id": r["vendor_id"], "vendor_name": r["vendor_name"],
            "invoice_number": r["invoice_number"], "invoice_date": r["invoice_date"],
            "amount": float(r["amount"]), "due_date": r["due_date"], "status": r["status"],
            "notes": r["notes"], "created_at": r["created_at"]}


BILL_SQL = "SELECT b.*, v.name AS vendor_name FROM bills b JOIN vendors v ON v.id=b.vendor_id"


def query_bills(**f: Optional[str]) -> list[dict]:
    where, args = [], []
    for col, key, op in [("b.vendor_id", "vendor_id", "="), ("b.invoice_number", "invoice_number", "="),
                         ("b.status", "status", "="), ("b.due_date", "due_from", ">="),
                         ("b.due_date", "due_to", "<=")]:
        if f.get(key):
            where.append(f"{col} {op} ?")
            args.append(f[key])
    sql = BILL_SQL + (" WHERE " + " AND ".join(where) if where else "") + " ORDER BY b.id"
    with db() as con:
        return [bill_dict(r) for r in con.execute(sql, args).fetchall()]


@app.get("/erp/bills")
def erp_bills(request: Request, status: Optional[str] = None, created: Optional[str] = None):
    if (g := guard(request)):
        return g
    return templates.TemplateResponse(request, "erp_bills.html",
                                      {"bills": query_bills(status=status), "created": created, "nav": True})


def form_context(request: Request, values: dict, error: Optional[str] = None) -> HTMLResponse:
    with db() as con:
        vendors = con.execute("SELECT * FROM vendors ORDER BY id").fetchall()
    return templates.TemplateResponse(request, "erp_new_bill.html", {
        "vendors": vendors, "v": values, "error": error, "save_label": chaos.save_label, "nav": True})


@app.get("/erp/bills/new")
def erp_new_bill(request: Request):
    return guard(request) or form_context(request, {})


def validate(v: dict) -> Optional[str]:
    """Return first validation message or None."""
    if not v["vendor_id"]:
        return "Vendor is required"
    if not v["invoice_number"]:
        return "Invoice number is required"
    try:
        inv = date.fromisoformat(v["invoice_date"])
    except ValueError:
        return "Invoice date is required"
    if not re.fullmatch(r"\d+(\.\d{1,2})?", v["amount"]) or float(v["amount"]) <= 0:
        return "Amount must be a positive number"
    try:
        due = date.fromisoformat(v["due_date"])
    except ValueError:
        return "Due date is required"
    if due < inv:
        return "Due date cannot be before invoice date"
    return None


@app.post("/erp/bills")
def erp_create_bill(request: Request, vendor_id: str = Form(""), invoice_number: str = Form(""),
                    invoice_date: str = Form(""), amount: str = Form(""), due_date: str = Form(""),
                    notes: str = Form("")):
    if (g := guard(request, page=False)):
        return g
    if chaos.should_fail_post():
        return HTMLResponse("Internal Server Error", status_code=500)
    v = {"vendor_id": vendor_id.strip(), "invoice_number": invoice_number.strip(),
         "invoice_date": invoice_date.strip(), "amount": amount.strip().replace(",", ""),
         "due_date": due_date.strip(), "notes": notes}
    with db() as con:
        vendor = con.execute("SELECT * FROM vendors WHERE id=?", (v["vendor_id"],)).fetchone()
        err = validate(v)
        if not err and not vendor:
            err = "Vendor is required"
        if err:
            return form_context(request, v, err)
        dup = con.execute("SELECT id FROM bills WHERE vendor_id=? AND invoice_number=?",
                          (v["vendor_id"], v["invoice_number"])).fetchone()
        if dup:
            return form_context(request, v, f"Duplicate bill: {v['invoice_number']} already exists "
                                            f"for {vendor['name']} (bill BILL-{dup['id']:03d})")
        cur = con.execute(
            "INSERT INTO bills (vendor_id, invoice_number, invoice_date, amount, due_date, status, notes, created_at)"
            " VALUES (?,?,?,?,?,'unpaid',?,?)",
            (v["vendor_id"], v["invoice_number"], v["invoice_date"], round(float(v["amount"]), 2),
             v["due_date"], v["notes"], datetime.now().isoformat(timespec="seconds")))
        con.commit()
        bill_id = f"BILL-{cur.lastrowid:03d}"
    return see_other(f"/erp/bills?created={bill_id}")


# ---------------------------------------------------------------- erp json api
@app.get("/erp/api/vendors")
def api_vendors(request: Request):
    if (g := guard(request, api=True)):
        return g
    with db() as con:
        return [dict(r) for r in con.execute("SELECT * FROM vendors ORDER BY id").fetchall()]


@app.get("/erp/api/bills")
def api_bills(request: Request, vendor_id: Optional[str] = None, invoice_number: Optional[str] = None,
              status: Optional[str] = None, due_from: Optional[str] = None, due_to: Optional[str] = None):
    if (g := guard(request, api=True)):
        return g
    return query_bills(vendor_id=vendor_id, invoice_number=invoice_number, status=status,
                       due_from=due_from, due_to=due_to)


@app.get("/erp/api/bills/{bill_id}")
def api_bill(request: Request, bill_id: str):
    if (g := guard(request, api=True)):
        return g
    m = re.fullmatch(r"BILL-(\d+)", bill_id)
    with db() as con:
        r = con.execute(BILL_SQL + " WHERE b.id=?", (int(m.group(1)),)).fetchone() if m else None
    if not r:
        return JSONResponse({"error": "not_found"}, status_code=404)
    return bill_dict(r)
