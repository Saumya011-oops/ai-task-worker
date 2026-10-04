"""Error taxonomy handling (docs/02 §6): mechanical recoveries happen here WITHOUT calling the LLM.
  transient -> backoff retry (replaying a form submit if the action was a click)
  auth      -> relogin skill, then retry / replay
  stuck     -> is_stuck(): same action+result 3x -> replan hint, again -> ask_human
Semantic errors (not_found, validation, ambiguous) are returned to the LLM unchanged."""
from __future__ import annotations

import json
import os
import re
import time
from collections import deque
from typing import Callable

from agent import policy_gate
from agent.memory import Memory, parse_elements
from agent.types import Action, Observation
from tools import base

BACKOFF = (1, 2, 4)  # seconds; length == transient_retries


def _run(tool: str, **args) -> Observation:
    return base.get(tool).run(**args)


def _find(elements: dict, label: str, kinds: tuple[str, ...] | None = None) -> str | None:
    for eid, e in elements.items():
        if e["label"] == label and (kinds is None or e["kind"] in kinds):
            return eid
    return None


# ---- skills ----------------------------------------------------------------------------------
def relogin() -> bool:
    """Generic login skill: on a login page, fill the email/user + password fields from .env and submit."""
    page = _run("read_page")
    els = parse_elements(page.data)
    pw = next((ln.split("]")[0][1:] for ln in page.data.splitlines() if "type=password" in ln), None)
    user = next((i for i, e in els.items() if e["kind"] == "input" and i != pw
                 and re.search(r"email|user|login", e["label"], re.I)), None)
    btn = next((i for i, e in els.items() if e["kind"] == "button" and re.search(r"sign in|log ?in", e["label"], re.I)), None)
    if not (pw and user and btn):
        return False
    env = policy_gate.load_policies().get("login", {})   # env var names come from company/policies.yaml
    _run("type", id=user, text=os.getenv(env.get("user_env", "LOGIN_USER"), ""))
    _run("type", id=pw, text=os.getenv(env.get("password_env", "LOGIN_PASSWORD"), ""))
    _run("click", id=btn)
    return "/login" not in (_run("read_page").data.split("\n")[0])


def replay_submit(mem: Memory, url: str, button_label: str) -> Observation:
    """Re-open the form page, refill every field typed so far (by label), and press the same button again.
    The replay goes through the policy gate again (the first attempt may have committed before failing)."""
    form = dict(mem.form)
    obs = _run("goto", url=url)
    if not obs.ok:
        return obs
    page = _run("read_page")
    els = parse_elements(page.data)
    for label, f in form.items():
        eid = _find(els, label)
        if not eid:
            return Observation(ok=False, error_class="not_found", data=f"replay: field {label!r} missing")
        _run("select" if f["kind"] == "select" else "type", id=eid,
             **({"option": f["value"]} if f["kind"] == "select" else {"text": f["value"]}))
    pol = policy_gate.load_policies()
    alt = {l for t in (pol.get("triggers") or {}).values() for l in t.get("button_labels", [])}  # e.g. renamed button
    btn = _find(els, button_label, ("button",)) or next((i for i, e in els.items() if e["kind"] == "button" and e["label"] in alt), None)
    if not btn:
        return Observation(ok=False, error_class="not_found", data="replay: submit button not found")
    mem.page_text, mem.page_url, mem.elements, mem.form = page.data, url, els, form
    d = policy_gate.check(Action(tool="click", args={"id": btn}), mem, pol)
    if d.verdict != "allow":
        return Observation(ok=False, error_class="policy",
                           data=f"Automatic retry NOT performed: {d.reason or d.verdict}. The first attempt may have been saved; check the system before retrying.")
    return _run("click", id=btn)


# ---- retry runner ----------------------------------------------------------------------------
def run_with_retries(action: Action, mem: Memory, log: Callable[[str], None]) -> Observation:
    """Execute a tool; handle transient/auth failures mechanically. Returns the final Observation."""
    tool = base.get(action.tool)
    pre_url, pre_btn = mem.page_url, mem.label_of(action.args.get("id", ""))  # for form replay
    pre_kind = mem.elements.get(action.args.get("id", ""), {}).get("kind")
    form_before = dict(mem.form)
    obs = tool.run(**action.args)
    retries = 0
    while not obs.ok and obs.error_class in ("transient", "auth") and retries < len(BACKOFF):
        retries += 1
        if obs.error_class == "transient":
            log(f"transient error ({obs.data[:80]}) -> retry {retries} in {BACKOFF[retries-1]}s")
            mem.recoveries.append(f"step {mem.step}: transient error on {action.tool}, retry {retries}")
            time.sleep(BACKOFF[retries - 1])
        else:
            first = not mem.logged_in
            log("not logged in -> logging in" if first else "session expired -> running re-login skill")
            if not first:   # the very first login of a run is normal operation, not a recovery
                mem.recoveries.append(f"step {mem.step}: session expired on {action.tool}, re-login")
            if not relogin():
                return Observation(ok=False, error_class="auth", data="Re-login failed; credentials may be wrong.")
            mem.logged_in = True
        if action.tool == "click" and pre_kind == "button" and form_before:       # a form submit: can't just re-click
            mem.form = form_before
            obs = replay_submit(mem, pre_url, pre_btn)
        elif action.tool in ("click", "type", "select"):             # page changed under us: tell the LLM
            if obs.error_class == "auth":
                return Observation(ok=True, data="Session had expired; re-logged in automatically. "
                                   "Page state was reset: call read_page and redo this action if needed.")
            obs = tool.run(**action.args)
        else:
            obs = tool.run(**action.args)
    if obs.ok and retries:   # tell the LLM what happened so its report is accurate
        obs = obs.model_copy(update={"data": f"[controller: this succeeded only after {retries} automatic retry/recovery attempt(s); "
                                              f"the earlier attempt(s) failed] " + obs.data})
    return obs


# ---- stuck detection -------------------------------------------------------------------------
class Stuck:
    """Same action + same result 3 times within the last 8 steps (consecutive or alternating) -> 'replan';
    the next time -> 'ask_human'. Windowed so A,B,A,B,A cannot dodge a consecutive-only check."""
    def __init__(self) -> None:
        self.recent: deque[str] = deque(maxlen=8)
        self.triggers = 0

    def check(self, action: Action, obs: Observation) -> str | None:
        self.recent.append(json.dumps([action.tool, action.args, obs.ok, obs.data[:300]], sort_keys=True, default=str))
        if self.recent.count(self.recent[-1]) >= 3:
            self.recent.clear()
            self.triggers += 1
            return "replan" if self.triggers == 1 else "ask_human"
        return None
