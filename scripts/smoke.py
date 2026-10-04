"""Smoke test: drive login -> New Bill page using ONLY tools. Run from project root."""
import sys; sys.path.insert(0, ".")
import os
from dotenv import load_dotenv
from tools import browser
from tools.registry import build_registry
from tools.base import get

load_dotenv(); build_registry(); browser.set_run_dir("runs/smoke")
base = os.getenv("SANDBOX_URL", "http://localhost:8000")

def call(name, **a):
    o = get(name).run(**a); print(f"--- {name}({a}) ok={o.ok} err={o.error_class}\n{o.data[:1500]}"); return o

call("goto", url=f"{base}/erp/bills/new")            # expect redirect to login
page = call("read_page").data
def eid(label):                                       # find element id by its label
    return next(l.split("]")[0][1:] for l in page.splitlines() if f'"{label}"' in l)
call("type", id=eid("Email"), text=os.getenv("ERP_USER"))
call("type", id=eid("Password"), text=os.getenv("ERP_PASSWORD"), submit=True)
call("read_page")                                     # should be the New Bill form after next= redirect
browser.close_browser()
