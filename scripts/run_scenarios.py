"""Scenario runner: python scripts/run_scenarios.py T1 T2 T3a T3b T4 T5 T6 [--runs N]
Resets the DB before every run, scripts the human answers, checks GROUND TRUTH via the ERP API (not the agent's report)
and appends metrics to runs/metrics.json."""
from __future__ import annotations

import argparse
import csv
import json
import os
import re
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
os.chdir(ROOT)

import httpx
from dotenv import load_dotenv

load_dotenv(ROOT / ".env")
import main as cli
from agent import loop
from llm.client import LLMClient
from tools import browser, human
from tools.registry import build_registry

T1 = "Find the latest invoice from Northwind Supplies, extract the amount and due date, enter it into our ERP, and tell me once it's done."
TASKS = {
    "T1": (T1, False), "T2": (T1, True), "T6": (T1, False),
    "T3a": ("Enter the latest invoice from Globex Industrial into the ERP.", False),
    "T3b": ("Enter the latest invoice from Globex Industrial into the ERP.", False),
    "T4": ("Enter the latest invoice from Northwind into the ERP.", False),
    "T5": ("Make a CSV of all unpaid ERP bills due in October 2026 and save it to workspace/outputs/", False),
}
BASE = os.getenv("SANDBOX_URL", "http://localhost:8000")


def reset_state() -> None:
    subprocess.run([sys.executable, "sandbox/seed.py"], cwd=ROOT, capture_output=True, check=True)
    for d in ("downloads", "outputs"):
        for f in (ROOT / "workspace" / d).glob("*"):
            f.unlink()


def bills() -> list[dict]:
    c = httpx.Client(base_url=BASE, follow_redirects=False)
    c.post("/erp/login", data={"email": os.getenv("ERP_USER"), "password": os.getenv("ERP_PASSWORD")})
    return c.get("/erp/api/bills").json()


def check(sid: str, status: str, summary: str, recov: int, asked: list[str]) -> tuple[bool, str]:
    """Ground-truth verdict per docs/04_TEST_SCENARIOS.md 'Verifier checks'."""
    b = bills()
    ns = [x for x in b if x["invoice_number"] == "INV-NS-1043"]
    gx = [x for x in b if x["invoice_number"] == "GX-7781"]
    if sid in ("T1", "T2", "T6"):
        good = len(ns) == 1 and ns[0]["vendor_id"] == "V001" and ns[0]["amount"] == 48250.0 and ns[0]["due_date"] == "2026-10-29"
        if sid == "T2":
            good = good and recov >= 2
        if sid == "T6":
            good = good and bool(re.search(r"BILL-\d+", summary))
        return good, f"INV-NS-1043 bills={len(ns)} {[(x['id'], x['amount'], x['due_date']) for x in ns]}"
    if sid == "T3a":
        ok = len(gx) == 1 and gx[0]["amount"] == 240000.0 and gx[0]["due_date"] == "2026-10-30" and gx[0]["invoice_date"] == "2026-09-30"
        return ok, f"GX-7781 bills={[(x['id'], x['amount'], x['invoice_date'], x['due_date']) for x in gx]}"
    if sid == "T3b":
        return len(gx) == 0 and status == "denied", f"GX-7781 bills={len(gx)} status={status}"
    if sid == "T4":
        new = [x for x in b if x["id"] not in ("BILL-001", "BILL-002", "BILL-003")]
        ok = bool(asked) and len(new) == 1 and new[0]["vendor_id"] == "V001" and new[0]["invoice_number"] == "INV-NS-1043" \
            and new[0]["amount"] == 48250.0 and new[0]["due_date"] == "2026-10-29" and new[0]["invoice_date"] == "2026-09-29"
        return ok, f"asked_human={len(asked)} new bills={[(x['vendor_id'], x['invoice_number'], x['amount'], x['due_date']) for x in new]}"
    if sid == "T5":
        files = list((ROOT / "workspace" / "outputs").glob("*.csv"))
        if not files:
            return False, "no CSV in workspace/outputs"
        rows = list(csv.DictReader(files[0].open()))
        want = {x["id"] for x in b if x["status"] == "unpaid" and x["due_date"].startswith("2026-10")}
        got = {r.get("id") or r.get("Bill ID") or r.get("bill_id") for r in rows}
        return got == want and len(rows) == len(want), f"csv={files[0].name} rows={sorted(got, key=str)} expected={sorted(want)} header={list(rows[0]) if rows else []}"
    return False, "unknown scenario"


def run_one(sid: str) -> dict:
    task, chaos = TASKS[sid]
    asked: list[str] = []

    def answers(question: str, options: list[str] | None) -> str:
        asked.append(question)
        if question.startswith("APPROVAL REQUIRED"):
            return "reject" if sid == "T3b" else "approve"
        opts = options or []
        pick = next((o for o in opts if "supplies" in o.lower()), opts[0] if opts else "Northwind Supplies")
        return pick

    human.set_answer_provider(answers)
    proc = cli.ensure_sandbox(BASE, chaos, reset=False)
    run_dir = ROOT / "runs" / time.strftime("%Y%m%d-%H%M%S")
    build_registry(); browser.SESSION.headed = False; browser.set_run_dir(run_dir)
    t0 = time.time()
    try:
        status, summary = loop.run(task, LLMClient(), run_dir)
        stats = dict(re.findall(r"(\w+)=(\d+)", (run_dir / "report.md").read_text().split("**Stats:**")[1].splitlines()[0]))
        recov = int(stats.get("recoveries", 0))
        approvals = [q for q in asked if q.startswith("APPROVAL REQUIRED")]
        clar = [q for q in asked if not q.startswith("APPROVAL REQUIRED")]
        ok, evidence = check(sid, status, summary, recov, clar)
    finally:
        browser.close_browser()
        if proc:
            proc.terminate(); proc.wait()
    return {"scenario": sid, "pass": ok, "status": status, "steps": int(stats["steps"]), "llm_calls": int(stats["llm_calls"]),
            "recoveries": recov, "clarifications": len(clar), "approvals": len(approvals), "secs": round(time.time() - t0),
            "run": run_dir.name, "evidence": evidence, "summary": summary[:200]}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("scenarios", nargs="+")
    ap.add_argument("--runs", type=int, default=1)
    a = ap.parse_args()
    out = ROOT / "runs" / "metrics.json"
    results = json.loads(out.read_text()) if out.exists() else []
    for sid in a.scenarios:
        for i in range(a.runs):
            if sid == "T6":   # T6 = T1 then the same task again WITHOUT a reset
                reset_state(); first = run_one("T1"); first["scenario"] = "T6-setup"; results.append(first)
            else:
                reset_state()
            r = run_one(sid)
            results.append(r)
            print(f"[{'PASS' if r['pass'] else 'FAIL'}] {sid} run {i+1}: status={r['status']} steps={r['steps']} llm={r['llm_calls']} "
                  f"recov={r['recoveries']} {r['secs']}s | {r['evidence']} | {r['run']}", flush=True)
            out.write_text(json.dumps(results, indent=1))


if __name__ == "__main__":
    main()
