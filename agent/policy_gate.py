"""Policy gate: checks a proposed action against company/policies.yaml BEFORE it runs.
Returns allow | needs_approval | block. Hard rules live here (code), not in the prompt."""
from __future__ import annotations

import json
import re
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

from agent.memory import Memory
from agent.types import Action
from tools import base

POLICY_FILE = Path(__file__).resolve().parent.parent / "company" / "policies.yaml"


@dataclass
class Decision:
    verdict: str            # "allow" | "needs_approval" | "block"
    reason: str = ""
    trigger: str = ""       # which company action matched (e.g. erp.create_bill)


def load_policies(path: Path = POLICY_FILE) -> dict[str, Any]:
    return yaml.safe_load(path.read_text()) or {}


def _num(s: str) -> float | None:
    s = re.sub(r"[^\d.]", "", s or "")
    return float(s) if s.count(".") <= 1 and s else None


def _holds(cond: str, values: dict[str, str]) -> bool | None:
    """Evaluate 'always' or '<field> <op> <number>' against form values. None = cannot evaluate (fail closed upstream)."""
    if cond.strip() == "always":
        return True
    m = re.match(r"\s*(\w+)\s*(>=|<=|>|<|==)\s*([\d.]+)\s*$", cond)
    if not m:
        return None
    v = _num(values.get(m.group(1), ""))
    if v is None:
        return None
    lim = float(m.group(3))
    return {">": v > lim, "<": v < lim, ">=": v >= lim, "<=": v <= lim, "==": v == lim}[m.group(2)]


def match_trigger(action: Action, mem: Memory, policies: dict) -> tuple[str, dict, dict[str, str]] | None:
    """Map a raw browser step to a company action using the `triggers` section of policies.yaml."""
    for name, t in (policies.get("triggers") or {}).items():
        if t.get("url_contains", "") not in mem.page_url:
            continue
        el = mem.elements.get(action.args.get("id", ""), {})
        is_click = action.tool == "click" and (el.get("label") in t.get("button_labels", []) or el.get("kind") == "button")
        is_enter = action.tool == "type" and bool(action.args.get("submit"))   # Enter in a field submits the form too
        if is_click or is_enter:
            return name, t, {f: mem.field_value(label) for f, label in t.get("fields", {}).items()}
    return None


def check(action: Action, mem: Memory, policies: dict) -> Decision:
    hit = match_trigger(action, mem, policies)
    if not hit:
        return Decision("allow")
    name, trig, values = hit
    # 1) duplicate check (hard block). Fails CLOSED: if the lookup cannot be completed, do not proceed silently.
    dup = policies.get("duplicate_check") or {}
    lk = trig.get("lookup")
    if dup.get("action") == name and lk and (tool := base.get(lk["tool"])):
        args = {k: values.get(v, "") for k, v in lk.get("args", {}).items()}
        obs = tool.run(**args)
        for i in range(3):                       # transient lookup errors are retried here, no LLM involved
            if obs.ok or obs.error_class != "transient":
                break
            time.sleep(1 + i)
            obs = tool.run(**args)
        try:
            if not obs.ok:
                raise ValueError(obs.data[:120])
            recs = json.loads(obs.data or "[]")
            for rec in (r for r in recs if isinstance(r, dict)):
                if all(values.get(k, "").strip().lower() in
                       {str(rec.get(k, "")).lower(), str(rec.get(k.replace("_id", "_name"), "")).lower()}
                       for k in dup.get("key", [])):
                    return Decision("block", f"Duplicate: a record with {dup['key']} = "
                                    f"{[values.get(k) for k in dup['key']]} already exists (id {rec.get('id')}). "
                                    "Do not create it again; finish and report it as already recorded.", name)
        except Exception as e:
            return Decision("block", f"Cannot verify duplicates ({e}). Do not submit; retry later or ask the human.", name)
    # 2) approval rules; a rule that cannot be evaluated (missing/garbled amount) also requires approval
    for rule in policies.get("approval_required", []):
        if rule.get("action") == name:
            held = _holds(rule.get("when", ""), values)
            if held is None:
                return Decision("needs_approval", f"Cannot evaluate rule '{rule.get('when')}' ({name}: {values}); approval required.", name)
            if held:
                return Decision("needs_approval", f"{rule.get('reason', 'Approval required')} ({name}: {values})", name)
    return Decision("allow", trigger=name)
