"""Working memory + persistence: facts, plan, history, last page snapshot, run trace (trace.jsonl, state.json)."""
from __future__ import annotations

import json
import re
import time
from pathlib import Path
from typing import Any

from agent.types import Action, Fact, Observation, PlanStep

# One tagged line from read_page: [e5] input  "Amount (INR)" type=date value="12"
_EL = re.compile(r'^\[(e\d+)\]\s+(\w+)\s+"(.*?)"(.*)$')
BROWSER_TOOLS = {"goto", "click", "type", "select", "screenshot", "download", "read_page", "update_plan"}  # results squeezed when old
NAV_TOOLS = {"goto", "click", "download"}  # actions after which element ids may be invalid


def parse_elements(page_text: str) -> dict[str, dict[str, str]]:
    """read_page text -> {id: {kind, label, value}} (value = typed value, or selected option)."""
    out: dict[str, dict[str, str]] = {}
    for line in page_text.splitlines():
        m = _EL.match(line.strip())
        if m:
            rest = m.group(4)
            v = re.search(r'(?:value|selected)="(.*?)"', rest)
            out[m.group(1)] = {"kind": m.group(2), "label": m.group(3), "value": v.group(1) if v else ""}
    return out


class Memory:
    def __init__(self, run_dir: Path, task: str):
        self.run_dir, self.task = run_dir, task
        run_dir.mkdir(parents=True, exist_ok=True)
        self.facts: dict[str, Fact] = {}
        self.plan: list[PlanStep] = []
        self.history: list[dict[str, Any]] = []   # compact per-step records for the LLM context
        self.step = 0
        self.llm_calls = 0
        self.recoveries: list[str] = []            # human-readable recovery events (for the report)
        self.page_text = ""                        # latest read_page output
        self.page_url = ""
        self.page_stale = True                     # True after nav-ish actions until next read_page
        self.elements: dict[str, dict[str, str]] = {}
        self.form: dict[str, dict[str, str]] = {}  # label -> {kind, value} typed since last page load
        self.approvals: list[str] = []             # controller audit log of approval decisions (verifier evidence)
        self.denied: list[str] = []                # reasons of actions the human refused
        self.visits: dict[str, list] = {}           # url -> [title, times seen]
        self.logged_in = False                     # set once the re-login skill has succeeded in this run
        self.trace = run_dir / "trace.jsonl"

    # ---- page / form tracking -------------------------------------------------------------
    def label_of(self, eid: str) -> str:
        return self.elements.get(str(eid), {}).get("label", "")

    def field_value(self, label: str) -> str:
        """Typed value if we typed one, else whatever the snapshot shows."""
        if label in self.form:
            return self.form[label]["value"]
        return next((e["value"] for e in self.elements.values() if e["label"] == label), "")

    def _track(self, action: Action, obs: Observation) -> None:
        t, a = action.tool, action.args
        if t == "read_page" and obs.ok:
            m = re.search(r"URL:\s*(\S+)", obs.data)
            url = m.group(1) if m else ""
            if url != self.page_url:
                self.form = {}
            t = re.search(r"TITLE:\s*(.*?)(?:\s{2,}|\n|$)", obs.data)
            v = self.visits.setdefault(url, [t.group(1).strip() if t else "", 0])
            v[1] += 1
            self.page_text, self.page_url, self.page_stale = obs.data, url, False
            self.elements = parse_elements(obs.data)
        elif t in ("type", "select") and obs.ok:
            e = self.elements.get(a.get("id", ""), {})
            if e:
                self.form[e["label"]] = {"kind": e["kind"], "value": a.get("text", a.get("option", ""))}
        elif t in NAV_TOOLS:
            self.page_stale = True
            if t == "goto":
                self.form = {}

    # ---- recording ------------------------------------------------------------------------
    def remember(self, key: str, value: str, source: str = "") -> None:
        self.facts[key] = Fact(key=key, value=value, source=source, step=self.step)

    def record(self, action: Action, obs: Observation, **extra: Any) -> None:
        """Append to trace.jsonl, update memory, persist state.json."""
        if action.tool == "remember" and obs.ok:
            self.remember(action.args.get("key", ""), str(action.args.get("value", "")), action.args.get("source", ""))
        if action.tool != "update_plan":
            self._track(action, obs)
        self.history.append({"step": self.step, "tool": action.tool, "args": action.args, "ok": obs.ok,
                             "error_class": obs.error_class, "data": obs.data})
        args = dict(action.args)
        if action.tool == "type" and "password" in self.elements.get(args.get("id", ""), {}).get("label", "").lower():
            args["text"] = "***"  # never persist credentials
        row = {"step": self.step, "ts": round(time.time(), 2), "thought": action.thought, "tool": action.tool,
               "args": args, "ok": obs.ok, "error_class": obs.error_class, "data": obs.data[:2000],
               "screenshot": obs.screenshot, **extra}
        with self.trace.open("a") as f:
            f.write(json.dumps(row, default=str) + "\n")
        (self.run_dir / "state.json").write_text(json.dumps({
            "task": self.task, "step": self.step, "llm_calls": self.llm_calls, "recoveries": self.recoveries,
            "facts": [f.model_dump() for f in self.facts.values()],
            "plan": [p.model_dump() for p in self.plan]}, indent=2))

    def visited_summary(self, limit: int = 8) -> str:
        """Pages already opened + counts, so the LLM notices when it is going in circles."""
        rows = []
        for url, (title, n) in list(self.visits.items())[-limit:]:
            warn = "  <- seen several times, nothing new: use what you already learned/remembered" if n >= 3 else ""
            rows.append(f"- {url} '{title}' x{n}{warn}")
        return "\n".join(rows) or "(none)"

    # ---- context for the LLM --------------------------------------------------------------
    def compact_history(self, k: int = 8) -> str:
        """Last k steps; only the very last result is shown in full (older ones are squeezed)."""
        rows = []
        for i, h in enumerate(self.history[-k:]):
            last = i == len(self.history[-k:]) - 1
            keep = 160 if h["tool"] in BROWSER_TOOLS else 1500  # file/API/data results stay readable for later steps
            data = h["data"] if last else re.sub(r"\s+", " ", h["data"])[:keep]
            if h["tool"] == "read_page" and not last:
                data = "(page snapshot, see CURRENT PAGE)"
            err = "" if h["ok"] else f" [ERROR {h['error_class']}]"
            rows.append(f"#{h['step']} {h['tool']} {json.dumps(h['args'], default=str)[:200]} -> "
                        f"{'ok' if h['ok'] else 'FAILED'}{err}: {data[:4000 if last else keep]}")
        return "\n".join(rows) or "(no steps yet)"
