"""CLI: python main.py "<task>" [--chaos] [--headed] [--max-steps N] [--reset]"""
from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

import httpx
from dotenv import load_dotenv
from rich.console import Console

ROOT = Path(__file__).resolve().parent
load_dotenv(ROOT / ".env")
con = Console()


def health(base: str) -> dict | None:
    try:
        return httpx.get(f"{base}/health", timeout=2).json()
    except Exception:
        return None


def ensure_sandbox(base: str, chaos: bool, reset: bool) -> subprocess.Popen | None:
    """Use the running sandbox if it matches the chaos setting; otherwise start our own (and stop it at exit)."""
    h, proc = health(base), None
    if h is None:
        env = {**os.environ, "CHAOS": "1" if chaos else "0"}
        port = base.rsplit(":", 1)[-1]
        proc = subprocess.Popen([sys.executable, "-m", "uvicorn", "sandbox.app:app", "--port", port, "--log-level", "warning"],
                                cwd=ROOT, env=env)
        for _ in range(40):
            if (h := health(base)):
                break
            time.sleep(0.5)
        else:
            sys.exit("Could not start the sandbox.")
        con.print(f"[dim]Started sandbox on {base} (chaos={'on' if chaos else 'off'})[/]")
    elif h.get("chaos") != chaos:
        sys.exit(f"Sandbox at {base} has chaos={h.get('chaos')} but you asked chaos={chaos}. Restart it with CHAOS={int(chaos)}.")
    try:
        if reset:
            httpx.post(f"{base}/__reset", timeout=5)
    except Exception:
        if proc:
            proc.terminate()
        raise
    return proc


def to_mp4(run_dir: Path) -> None:
    """webm -> demo.mp4 with ffmpeg; silently skipped if ffmpeg is missing or fails. Re-writes report.html to link it."""
    webms = sorted((run_dir / "video").glob("*.webm"))
    if not webms or not shutil.which("ffmpeg"):
        return
    r = subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", str(webms[-1]), "-c:v", "libx264", "-pix_fmt", "yuv420p",
                        str(run_dir / "demo.mp4")], capture_output=True)
    if r.returncode == 0:
        con.print(f"[dim]Recording: {run_dir / 'demo.mp4'}[/]")
        html = run_dir / "report.html"   # report was written before the video existed: add the link now
        if html.exists() and "demo.mp4" not in html.read_text():
            html.write_text(html.read_text().replace("<h2>Evidence</h2>", '<h2>Evidence</h2><p>Demo recording: <video src="demo.mp4" controls width="640"></video> <a href="demo.mp4">demo.mp4</a></p>', 1))


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("task")
    ap.add_argument("--chaos", action="store_true", help="expect/start the sandbox with failure injection")
    ap.add_argument("--headed", action="store_true", help="show the browser")
    ap.add_argument("--max-steps", type=int, default=None)
    ap.add_argument("--record", action="store_true", help="record the browser session to runs/<id>/demo.mp4")
    ap.add_argument("--reset", action="store_true", help="re-seed the sandbox DB before the run")
    a = ap.parse_args()

    base = os.getenv("SANDBOX_URL", "http://localhost:8000")
    proc = ensure_sandbox(base, a.chaos, a.reset)
    # imports after .env is loaded so tools/llm see the environment
    from agent import loop
    from llm.client import LLMClient
    from tools import browser
    from tools.registry import build_registry

    run_dir = ROOT / "runs" / datetime.now().strftime("%Y%m%d-%H%M%S")
    build_registry()
    browser.SESSION.headed = a.headed
    browser.set_run_dir(run_dir)
    if a.record:
        browser.SESSION.record_dir = run_dir / "video"
    try:
        status, _ = loop.run(a.task, LLMClient(), run_dir, a.max_steps)
    finally:
        browser.close_browser()   # also flushes the video
        if a.record:
            to_mp4(run_dir)
        if proc:
            proc.terminate()
    sys.exit(0 if status in ("success", "denied") else 1)


if __name__ == "__main__":
    main()
