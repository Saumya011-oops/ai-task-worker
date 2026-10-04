"""Step 7: write report.md + report.html (summary, criteria table, facts, recoveries, screenshots, trace link)."""
from __future__ import annotations

import html
import json
from pathlib import Path

from agent.memory import Memory
from agent.types import TaskSpec, Verdict


def write(spec: TaskSpec | None, mem: Memory, verdicts: list[Verdict], status: str, summary: str, rounds: int) -> None:
    shots = [json.loads(l).get("screenshot") for l in (mem.trace.read_text().splitlines() if mem.trace.exists() else []) if l.strip()]
    shots = [str(Path(s).relative_to(mem.run_dir)) if Path(s).is_absolute() and str(s).startswith(str(mem.run_dir)) else s for s in shots if s]
    steps = mem.step
    stats = (f"steps={steps}, llm_calls={mem.llm_calls}, recoveries={len(mem.recoveries)}, verify_rounds={rounds}")
    # ---- markdown
    md = [f"# Run report — {status.upper()}", f"**Task:** {mem.task}", f"**Summary:** {summary}", f"**Stats:** {stats}", "",
          "## Success criteria", "| Criterion | Result | Evidence |", "|---|---|---|"]
    md += [f"| {v.criterion} | {'PASS' if v.passed else 'FAIL'} | {v.evidence.replace('|', '/')} |" for v in verdicts] or ["| (none verified) | - | - |"]
    md += ["", "## Key facts"] + [f"- `{f.key}` = {f.value}  _(source: {f.source}, step {f.step})_" for f in mem.facts.values()]
    md += ["", "## Recoveries"] + ([f"- {r}" for r in mem.recoveries] or ["- none"])
    md += ["", "## Evidence", "- trace: `trace.jsonl`"] + [f"- `{s}`" for s in shots]
    (mem.run_dir / "report.md").write_text("\n".join(md))
    # ---- html
    e = html.escape
    rows = "".join(f"<tr><td>{e(v.criterion)}</td><td class={'p' if v.passed else 'f'}>{'PASS' if v.passed else 'FAIL'}</td>"
                   f"<td>{e(v.evidence)}</td></tr>" for v in verdicts)
    facts = "".join(f"<li><code>{e(f.key)}</code> = {e(f.value)} <small>({e(f.source)}, step {f.step})</small></li>" for f in mem.facts.values())
    video = ('<h3>Demo recording</h3><video src="demo.mp4" controls width="640"></video> <a href="demo.mp4">demo.mp4</a>'
             if (mem.run_dir / "demo.mp4").exists() else "")
    imgs = "".join(f'<a href="{e(s)}"><img src="{e(s)}" width="240"></a> ' for s in shots)
    (mem.run_dir / "report.html").write_text(f"""<!doctype html><meta charset=utf-8><title>Run report</title>
<style>body{{font-family:system-ui;max-width:960px;margin:2em auto}}td,th{{border:1px solid #ccc;padding:4px 8px}}table{{border-collapse:collapse}}
.p{{color:#0a7d2c;font-weight:bold}}.f{{color:#c00;font-weight:bold}}.s{{font-size:1.4em}}</style>
<h1>Run report — <span class={'p' if status == 'success' else 'f'}>{e(status.upper())}</span></h1>
<p><b>Task:</b> {e(mem.task)}</p><p><b>Summary:</b> {e(summary)}</p><p><small>{e(stats)}</small></p>
<h2>Success criteria</h2><table><tr><th>Criterion</th><th>Result</th><th>Evidence</th></tr>{rows}</table>
<h2>Key facts</h2><ul>{facts}</ul><h2>Recoveries</h2><ul>{''.join(f'<li>{e(r)}</li>' for r in mem.recoveries) or '<li>none</li>'}</ul>
<h2>Evidence</h2><p><a href="trace.jsonl">trace.jsonl</a></p>{video}{imgs}""")
