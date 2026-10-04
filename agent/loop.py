"""Main controller loop (docs/02 §5). The LLM only proposes; this code gates, executes, retries, records, verifies."""
from __future__ import annotations

import json
import time
from pathlib import Path

from rich.console import Console

from agent import grounding, planner, policy_gate, recovery, report, understand, verifier
from agent.memory import Memory
from agent.prompts import POLICY_SYSTEM
from agent.types import Action, Observation, TaskSpec, Verdict
from llm.client import LLMClient, LLMError
from tools import base

con = Console()
SHOW = 300             # chars of a tool result echoed in the live trace
MAX_LLM_CALLS = 150    # budget guards: a run always stops with a (partial) report
MAX_SECONDS = 1200


def build_context(spec: TaskSpec, mem: Memory, hints: list[str]) -> str:
    """One self-contained prompt per step: spec + plan + facts + current page + recent steps + controller hints."""
    page = mem.page_text or "(no page read yet)"
    if mem.page_stale and mem.page_text:
        page = "(STALE: page may have changed since this snapshot; call read_page before using ids)\n" + page
    facts = "\n".join(f"- {f.key} = {f.value}  (source: {f.source})" for f in mem.facts.values()) or "(none yet)"
    return (f"TASK: {mem.task}\n\nTASKSPEC:\n{spec.model_dump_json(indent=1)}\n\nPLAN:\n{planner.render(mem.plan)}\n\n"
            f"FACTS:\n{facts}\n\nPAGES ALREADY VISITED:\n{mem.visited_summary()}\n\nCURRENT PAGE:\n{page[:4500]}\n\nRECENT STEPS:\n{mem.compact_history()}\n\n"
            + ("CONTROLLER HINTS:\n" + "\n".join(f"- {h}" for h in hints) + "\n\n" if hints else "")
            + f"Step {mem.step + 1}. Choose the next tool call.")


def approve(reason: str, action: Action) -> bool:
    """Approval gate: a normal ask_human call, answered approve/reject (logged in the trace like any step)."""
    q = f"APPROVAL REQUIRED: {reason}\nProposed action: {action.tool} {json.dumps(action.args)}"
    obs = base.get("ask_human").run(question=q, options=["approve", "reject"])
    return obs.ok and obs.data.lower().split("answered:")[-1].strip() == "approve"


def ungrounded(action: Action, mem: Memory) -> str | None:
    """Anti-hallucination guard: data-like values typed/selected into a form must appear in something observed."""
    val = str(action.args.get("text", action.args.get("option", "")))
    el = mem.elements.get(str(action.args.get("id", "")), {})
    if action.tool not in ("type", "select") or "password" in el.get("label", "").lower() or not grounding.needs_grounding(val):
        return None
    # corpus = only what was really observed. Facts and remember/update_plan echoes are the worker's OWN claims, so
    # they must not ground themselves.
    corpus = "\n".join([mem.task, mem.page_text, *(h["data"] for h in mem.history
                                                 if h["tool"] not in ("remember", "update_plan") and not h["data"].startswith("BLOCKED:"))])
    if grounding.is_grounded(val, corpus):
        return None
    return (f"BLOCKED: the value {val!r} does not appear in the task, any tool result, or your facts. Do not invent or "
            "recompute values: re-read the source (file/page) and copy the value exactly, then `remember` it.")


def execute(action: Action, mem: Memory, pol: dict, extra: dict) -> Observation:
    """Gate -> (approval) -> run with retries. Hard company rules are enforced here in code, not by the prompt."""
    if action.tool == "update_plan":
        try:
            return Observation(ok=True, data=planner.apply_update(mem, action.args.get("steps", [])))
        except Exception as e:
            return Observation(ok=False, error_class="validation", data=f"Invalid plan: {e}")
    if base.get(action.tool) is None:
        return Observation(ok=False, error_class="validation", data=f"Unknown tool {action.tool!r}")
    if bad := ungrounded(action, mem):
        extra["gate"] = "ungrounded"
        return Observation(ok=False, error_class="validation", data=bad)
    decision = policy_gate.check(action, mem, pol)
    extra["gate"] = decision.verdict
    if decision.verdict == "block":
        return Observation(ok=False, error_class="policy", data=decision.reason)
    if decision.verdict == "needs_approval":
        if not approve(decision.reason, action):
            mem.approvals.append(f"step {mem.step}: human DENIED approval for {action.tool} ({decision.reason[:150]})")
            extra["approval"] = "denied"
            mem.denied.append(decision.reason)
            return Observation(ok=False, error_class="policy", data="Approval DENIED by the human. Do NOT submit and do NOT "
                               "ask again. Call finish now and report: not submitted, approval denied.")
        mem.approvals.append(f"step {mem.step}: human GRANTED approval for {action.tool} ({decision.reason[:150]}) BEFORE it ran")
        extra["approval"] = "granted"
    if action.tool == "finish":
        return Observation(ok=True, data="finish requested")
    try:   # tools never raise by contract, but an LLM can pass bad args: classify instead of crashing
        return recovery.run_with_retries(action, mem, lambda m: con.print(f"   [yellow]↻ {m}[/]"))
    except TypeError as e:
        return Observation(ok=False, error_class="validation", data=f"Bad arguments for {action.tool}: {e}")


def _loop(task: str, llm: LLMClient, mem: Memory, st: dict, max_steps: int | None) -> None:
    pol = policy_gate.load_policies()
    max_steps = max_steps or pol.get("limits", {}).get("max_steps", 40)
    max_verify = pol.get("limits", {}).get("max_verify_rounds", 2)
    stuck, hints, t0 = recovery.Stuck(), [], time.time()

    # 1-2) Understand -> Plan
    spec = st["spec"] = understand.understand(task, llm, mem)
    con.print(f"[bold]Goal:[/] {spec.goal}\n[bold]Success criteria:[/] {spec.success_criteria}")
    mem.plan = planner.make_plan(spec, llm, mem)
    con.print("[bold]Plan:[/]\n" + planner.render(mem.plan))
    tools = base.schemas() + [planner.UPDATE_PLAN_SPEC]
    system = POLICY_SYSTEM + "\n\nCOMPANY KNOWLEDGE (SOPs, policies, where systems live):\n" + understand.company_knowledge()

    # 3-5) Execute <-> Observe <-> Adapt
    while mem.step < max_steps:
        if mem.llm_calls >= MAX_LLM_CALLS or time.time() - t0 > MAX_SECONDS:
            st["summary"] = "Stopped: LLM-call/time budget exhausted. Partial progress is in the trace."
            return
        # a) policy (LLM) proposes ONE action from a fresh, compact context
        mem.llm_calls += 1
        try:
            action = llm.next_action([{"role": "user", "content": build_context(spec, mem, hints)}], tools, system=system)
        except LLMError as e:
            con.print(f"[red]LLM error: {e}[/]")
            hints, mem.step = [f"Your last reply was invalid ({str(e)[:150]}). Call exactly one valid tool."], mem.step + 1
            continue
        hints, mem.step = [], mem.step + 1
        con.print(f"[dim]#{mem.step}[/] [italic]{action.thought[:160]}[/]\n   [cyan]{action.tool}[/] {json.dumps(action.args)[:200]}")

        # b+c) gate and execute (retries / re-login happen inside, no LLM involved)
        extra: dict = {}
        obs = execute(action, mem, pol, extra)

        # d) observe: record to trace.jsonl + memory, echo to the live trace
        mem.record(action, obs, **extra)
        con.print(f"   [{'green' if obs.ok else 'red'}]{'ok' if obs.ok else 'FAIL ' + str(obs.error_class)}[/] "
                  f"{obs.data[:SHOW].replace(chr(10), ' ')}")

        # d2) after navigation the controller refreshes the page snapshot itself (cheaper, no 'forgot read_page')
        if action.tool in ("goto", "click") and obs.ok:
            snap = Action(thought="(auto) refresh page snapshot after navigation", tool="read_page")
            mem.record(snap, recovery.run_with_retries(snap, mem, lambda m: con.print(f"   [yellow]↻ {m}[/]")), auto=True)

        # e) finish -> independent verification (max rounds); failures are fed back as hints
        if action.tool == "finish" and obs.ok and "gate" in extra:
            st["rounds"] += 1
            st["summary"] = action.args.get("summary", "")
            vspec = spec
            if mem.denied:   # human refused an action: the correct outcome is "nothing was submitted"
                vspec = TaskSpec(goal=spec.goal, success_criteria=[
                    f"The action the human denied was NOT performed and no record for it exists in the system ({mem.denied[-1][:200]})",
                    "The final summary states that it was not submitted because approval was denied"])
            con.print("[bold magenta]Verifying (fresh context, read-only)...[/]")
            st["verdicts"] = verdicts = verifier.verify(vspec, action.args, mem, llm)
            for v in verdicts:
                con.print(f"   {'[green]PASS' if v.passed else '[red]FAIL'}[/] {v.criterion} — {v.evidence[:150]}")
            if verdicts and all(v.passed for v in verdicts):
                st["status"] = "denied" if mem.denied else "success"
                return
            if st["rounds"] >= max_verify or mem.denied:
                st["status"], st["summary"] = "failed", st["summary"] + " | Verifier did not confirm all criteria."
                return
            hints = ["VERIFIER FAILED these criteria; fix them then finish again: "
                     + "; ".join(f"{v.criterion} ({v.evidence[:120]})" for v in verdicts if not v.passed)]
            continue

        # f) stuck detection: replan hint first, then escalate to the human
        s = stuck.check(action, obs)
        if s == "replan":
            hints = ["You keep repeating the same call with the same result: the data has not changed. Stop re-checking, use what you already have and do the next unfinished plan step."]
        elif s == "ask_human":
            ans = base.get("ask_human").run(question="The agent is stuck repeating an action. How should it proceed?")
            hints = [f"Human guidance after being stuck: {ans.data}"]
    st["summary"] = st["summary"] or f"Stopped: reached max_steps={max_steps}. Partial progress is in the trace."


def run(task: str, llm: LLMClient, run_dir: Path, max_steps: int | None = None) -> tuple[str, str]:
    """Exception boundary: whatever happens, a report.md/report.html is written and the status is honest."""
    mem = Memory(run_dir, task)
    st: dict = {"spec": None, "verdicts": [], "status": "failed", "summary": "", "rounds": 0}
    try:
        _loop(task, llm, mem, st, max_steps)
    except KeyboardInterrupt:
        st["status"], st["summary"] = "failed", "Interrupted by the user."
    except Exception as e:   # LLMError during understand/plan, bugs, ...: record instead of crashing silently
        st["status"], st["summary"] = "error", f"Run aborted: {type(e).__name__}: {str(e)[:300]}"
        con.print(f"[red]{st['summary']}[/]")
    report.write(st["spec"], mem, st["verdicts"], st["status"], st["summary"] or "No summary.", st["rounds"])
    con.print(f"\n[bold]{st['status'].upper()}[/] — report: {run_dir / 'report.md'}")
    return st["status"], st["summary"]
