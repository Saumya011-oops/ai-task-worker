"""Step 6: independent verification. FRESH context (no trace, no chat history), read-only tools only.
Order: (1) deterministic ground-truth snapshots + fact cross-check, (2) LLM judges each criterion with that evidence."""
from __future__ import annotations

import json
import re
import time
from difflib import SequenceMatcher
from datetime import datetime

from pydantic import BaseModel

from agent.grounding import variants as _variants
from agent.memory import Memory
from agent.prompts import VERIFIER_SYSTEM
from agent.types import TaskSpec, Verdict
from llm.client import LLMClient, LLMError
from tools import base
from tools.registry import READ_ONLY_TOOLS as READ_ONLY

MAX_VERIFY_STEPS = 8


class Verdicts(BaseModel):
    verdicts: list[Verdict]


REPORT_SPEC = {"name": "report_verdicts", "description": "Submit the final verdict for every success criterion.",
               "parameters": Verdicts.model_json_schema()}


def read_sources(mem: Memory) -> dict[str, str]:
    """Re-read (fresh, by the controller) every workspace file the worker cites as a fact source."""
    out: dict[str, str] = {}
    for f in mem.facts.values():
        for path in re.findall(r"[\w./-]+\.(?:pdf|txt|csv|md|json)", f.source):
            path = path.replace("workspace/", "", 1)
            if path not in out and (t := base.get("read_pdf" if path.endswith(".pdf") else "read_file")):
                obs = t.run(path=path)
                if obs.ok:
                    out[path] = obs.data
    return out


def ground_truth(mem: Memory) -> tuple[str, list[str]]:
    """Deterministic part: dump snapshot tools + source documents, then check each remembered fact against both."""
    chunks = []
    for name, t in base.REGISTRY.items():
        if getattr(t, "snapshot", False):
            obs = t.run()
            for i in range(3):   # transient failures (chaos) must not poison the ground truth
                if obs.ok or obs.error_class != "transient":
                    break
                time.sleep(1 + i)
                obs = t.run()
            chunks.append(f"## {name}()\n{obs.data if obs.ok else 'ERROR: ' + obs.data}")
    sources = read_sources(mem)
    chunks += [f"## SOURCE DOCUMENT {p}\n{txt}" for p, txt in sources.items()]
    blob = "\n".join(chunks)
    checks = []
    for f in mem.facts.values():
        v = f.value.strip()
        if not v:
            continue
        in_src = [any(c in txt.lower() for c in _variants(v)) for p, txt in sources.items() if p in f.source.replace("workspace/", "")]
        src = "n/a" if not in_src else ("FOUND" if any(in_src) else "NOT FOUND (possible wrong/invented value!)")
        sys_ = "FOUND" if any(c in blob.lower() for c in _variants(v)) else "not found"
        checks.append(f"fact {f.key}={v!r} (claimed source: {f.source}) -> in source document: {src}; anywhere in system data: {sys_}")
    return blob, checks


def _n(t: str) -> str:
    return re.sub(r"[^a-z0-9 ]", "", t.lower())


def align(criteria: list[str], got: list[Verdict]) -> list[Verdict]:
    """Match returned verdicts to the spec's criteria (the LLM may reword them slightly); a criterion with no matching
    verdict is FAILED (never an empty 'all passed'). Output uses the spec's wording, one verdict per criterion."""
    pool, out = list(got), []
    for c in criteria:
        best = max(pool, key=lambda v: SequenceMatcher(None, _n(c), _n(v.criterion)).ratio(), default=None)
        if best and SequenceMatcher(None, _n(c), _n(best.criterion)).ratio() >= 0.6:
            pool.remove(best)
            out.append(Verdict(criterion=c, passed=best.passed, evidence=best.evidence))
        else:
            out.append(Verdict(criterion=c, passed=False, evidence="verifier returned no verdict for this criterion"))
    return out


def verify(spec: TaskSpec, claims: dict, mem: Memory, llm: LLMClient) -> list[Verdict]:
    blob, checks = ground_truth(mem)
    ctx = ("SUCCESS CRITERIA:\n" + "\n".join(f"- {c}" for c in spec.success_criteria)
           + f"\n\nWORKER CLAIMS (unverified): {json.dumps(claims, default=str)}"
           + f"\n\nGROUND TRUTH (fetched just now by the controller):\n{blob[:20000]}"
           + "\n\nAPPROVAL AUDIT LOG (written by the controller, trustworthy; use it for criteria about approvals):\n"
           + ("\n".join(mem.approvals) or "(no approval was requested or granted)")
           + "\n\nDETERMINISTIC FACT CHECKS (facts the worker extracted, searched in the source documents and system data above):\n"
           + ("\n".join(checks) or "(none)"))
    tools = [t for t in base.schemas() if t["name"] in READ_ONLY] + [REPORT_SPEC]
    msgs = [{"role": "user", "content": ctx}]   # fresh: nothing from the worker's own context
    for i in range(MAX_VERIFY_STEPS):
        mem.llm_calls += 1
        last = i >= MAX_VERIFY_STEPS - 2   # last two turns: only report_verdicts is allowed, never run out of steps
        try:
            act = llm.next_action(msgs + ([{"role": "user", "content": "You have enough evidence. Submit report_verdicts NOW, "
                                            "one verdict per criterion."}] if last else []),
                                  [REPORT_SPEC] if last else tools, system=VERIFIER_SYSTEM)
        except LLMError as e:
            return [Verdict(criterion=c, passed=False, evidence=f"verifier error: {e}") for c in spec.success_criteria]
        if act.tool == "report_verdicts":
            try:
                return align(spec.success_criteria, Verdicts.model_validate(act.args).verdicts)
            except Exception as e:  # malformed -> ask again
                msgs.append({"role": "tool", "content": f"report_verdicts invalid: {e}"})
                continue
        obs = base.get(act.tool).run(**act.args)
        msgs += [{"role": "assistant", "content": f"{act.tool} {json.dumps(act.args)}"},
                 {"role": "tool", "content": obs.data[:4000]}]
    return [Verdict(criterion=c, passed=False, evidence="verifier ran out of steps") for c in spec.success_criteria]
