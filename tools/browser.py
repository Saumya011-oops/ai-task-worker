"""Playwright (sync) browser tools. One shared BrowserSession; the LLM acts by element id from read_page."""
from __future__ import annotations

import os
import re
from urllib.parse import urljoin
from pathlib import Path
from typing import Any, Callable

from playwright.sync_api import Error as PWError
from playwright.sync_api import TimeoutError as PWTimeout
from playwright.sync_api import sync_playwright

from agent.types import Observation
from tools._util import ROOT, WORKSPACE, clip, fail, ok, schema

TIMEOUT_MS = 15000


class ToolFail(Exception):
    """Raised inside a browser action to return a classified failure."""
    def __init__(self, error_class: str, msg: str):
        super().__init__(msg)
        self.error_class, self.msg = error_class, msg


# JS injected by read_page: tags visible interactive elements and returns {elements:[...], text:"..."}.
_READ_JS = r"""
() => {
  document.querySelectorAll('[data-agent-id]').forEach(e => e.removeAttribute('data-agent-id'));
  const vis = (e) => {
    const s = getComputedStyle(e);
    if (s.display === 'none' || s.visibility === 'hidden') return false;
    const r = e.getBoundingClientRect();
    return r.width > 0 && r.height > 0;
  };
  const clean = (t) => (t || '').replace(/\s+/g, ' ').trim();
  const nameOf = (e) => {
    if (e.id) { const l = document.querySelector('label[for="' + CSS.escape(e.id) + '"]'); if (l) return clean(l.innerText); }
    const al = e.getAttribute('aria-label'); if (al) return clean(al);
    const wl = e.closest('label'); if (wl) { const t = clean(wl.innerText); if (t) return t; }
    if (e.placeholder) return clean(e.placeholder);
    const tag = e.tagName.toLowerCase();
    if (tag === 'input' && ['submit', 'button', 'reset'].includes(e.type)) return clean(e.value);
    const t = clean(e.innerText || e.textContent); if (t) return t.slice(0, 80);
    return clean(e.getAttribute('title') || e.getAttribute('name') || '');
  };
  const els = [...document.querySelectorAll('a[href], button, input, select, textarea, [role=button]')]
    .filter(e => e.type !== 'hidden' && vis(e));
  const lines = [];
  els.forEach((e, i) => {
    const id = 'e' + (i + 1);
    e.setAttribute('data-agent-id', id);
    const tag = e.tagName.toLowerCase(), name = nameOf(e).replace(/"/g, "'");
    if (tag === 'a') lines.push(`[${id}] link "${name}" href=${e.getAttribute('href')}`);
    else if (tag === 'select') {
      const opts = [...e.options].filter(o => o.value !== '').map(o => clean(o.text));
      const cur = e.selectedOptions[0] && e.value !== '' ? clean(e.selectedOptions[0].text) : '';
      lines.push(`[${id}] select "${name}" options=[${opts.join(', ')}]` + (cur ? ` selected="${cur}"` : ''));
    }
    else if (tag === 'button' || tag === 'input' && ['submit', 'button', 'reset'].includes(e.type) || e.getAttribute('role') === 'button')
      lines.push(`[${id}] button "${name}"`);
    else if (tag === 'input' && ['checkbox', 'radio'].includes(e.type))
      lines.push(`[${id}] input  "${name}" type=${e.type} checked=${e.checked}`);
    else {
      const t = tag === 'textarea' ? 'textarea' : 'input ';
      const ty = tag === 'input' && e.type && e.type !== 'text' ? ` type=${e.type}` : '';
      const val = e.type === 'password' ? (e.value ? '***' : '') : e.value;
      lines.push(`[${id}] ${t} "${name}"${ty} value="${val.replace(/"/g, "'")}"`);
    }
  });
  // TEXT: walk visible DOM, skipping controls; render tables as `| a | b |` rows.
  const out = [];
  const SKIP = new Set(['SCRIPT', 'STYLE', 'NOSCRIPT', 'SELECT', 'BUTTON', 'INPUT', 'TEXTAREA', 'OPTION']);
  const BLOCK = new Set(['P', 'DIV', 'H1', 'H2', 'H3', 'H4', 'LI', 'UL', 'SECTION', 'FORM', 'BR', 'TR', 'TABLE', 'LABEL']);
  const walk = (n) => {
    if (n.nodeType === 3) { const t = clean(n.textContent); if (t) out.push(t + ' '); return; }
    if (n.nodeType !== 1 || SKIP.has(n.tagName) || !vis(n)) return;
    if (n.tagName === 'TABLE') {
      out.push('\n');
      n.querySelectorAll('tr').forEach(tr => {
        const cells = [...tr.children].map(c => clean(c.innerText));
        if (cells.length) out.push('| ' + cells.join(' | ') + ' |\n');
      });
      return;
    }
    const b = BLOCK.has(n.tagName);
    if (b) out.push('\n');
    n.childNodes.forEach(walk);
    if (b) out.push('\n');
  };
  walk(document.body);
  const text = out.join('').replace(/[ \t]+\n/g, '\n').replace(/\n{2,}/g, '\n').trim();
  return {lines, text, title: document.title, url: location.href};
}
"""


class BrowserSession:
    """Lazily-started single Playwright page + per-run screenshot numbering."""

    def __init__(self) -> None:
        self._pw = None
        self._browser = None
        self._ctx = None
        self.page = None
        self.headed = os.getenv("BROWSER_HEADED", "0") == "1"
        self.run_dir: Path | None = None
        self._n = 0
        self.record_dir: Path | None = None  # set (e.g. runs/<id>/video) to record the session as .webm
        self.last_status: int | None = None  # status of last main-frame navigation response

    def set_run_dir(self, path: str | Path) -> None:
        self.run_dir = Path(path)
        (self.run_dir / "screenshots").mkdir(parents=True, exist_ok=True)
        self._n = len(list((self.run_dir / "screenshots").glob("*.png")))

    def start(self) -> Any:
        if self.page is None:
            self._pw = sync_playwright().start()
            self._browser = self._pw.chromium.launch(headless=not self.headed)
            opts: dict[str, Any] = {"accept_downloads": True}
            if self.record_dir:   # screen recording for the demo: 1280x800 .webm written when the context closes
                opts.update(viewport={"width": 1280, "height": 800}, record_video_dir=str(self.record_dir),
                            record_video_size={"width": 1280, "height": 800})
            self._ctx = self._browser.new_context(**opts)
            self.page = self._ctx.new_page()
            self.page.set_default_timeout(TIMEOUT_MS)
            self.page.on("response", self._on_response)
        return self.page

    def _on_response(self, resp: Any) -> None:
        try:
            if resp.request.is_navigation_request() and resp.frame == self.page.main_frame:
                self.last_status = resp.status
        except Exception:
            pass

    def close(self) -> None:
        try:
            if self._ctx:   # closing the context first flushes the video file
                self._ctx.close()
            if self._browser:
                self._browser.close()
            if self._pw:
                self._pw.stop()
        finally:
            self._pw = self._browser = self._ctx = self.page = None

    def shot(self, label: str) -> str | None:
        """Save a screenshot as <run_dir>/screenshots/NNN_<label>.png; never raises."""
        try:
            if self.page is None:
                return None
            base = (self.run_dir or ROOT / "runs" / "_adhoc") / "screenshots"
            base.mkdir(parents=True, exist_ok=True)
            self._n += 1
            p = base / f"{self._n:03d}_{re.sub(r'[^A-Za-z0-9_-]', '_', label)}.png"
            self.page.screenshot(path=str(p))
            return str(p)
        except Exception:
            return None

    def check_nav(self, before_url: str, requested: str | None = None) -> None:
        """Raise ToolFail for login redirects / 5xx after a navigating action."""
        url = self.page.url
        if "/login" in url and "/login" not in (requested or before_url):
            raise ToolFail("auth", f"Redirected to login page ({url}). Session expired; re-authentication needed.")
        if self.last_status is not None and self.last_status >= 500:
            raise ToolFail("transient", f"HTTP {self.last_status} from server at {url}")

    def settle(self) -> None:
        try:
            self.page.wait_for_timeout(150)
            self.page.wait_for_load_state("load", timeout=TIMEOUT_MS)
        except PWError:
            pass

    def locate(self, eid: str) -> Any:
        loc = self.page.locator(f'[data-agent-id="{eid}"]')
        if not re.fullmatch(r"e\d+", str(eid)) or loc.count() == 0:
            raise ToolFail("not_found", f"No element with id '{eid}' on the current page. Call read_page again to get fresh ids.")
        return loc.first

    def info(self) -> str:
        return f"url={self.page.url} title={self.page.title()!r}"

    def run(self, tool: str, fn: Callable[[Any], str]) -> Observation:
        """Run an action with uniform error classification + screenshot after every action."""
        try:
            page = self.start()
            self.last_status = None
            data = fn(page)
            return ok(data, self.shot(tool))
        except ToolFail as e:
            return fail(e.error_class, e.msg, self.shot(tool))  # type: ignore[arg-type]
        except PWTimeout as e:
            return fail("transient", f"Timeout: {str(e).splitlines()[0]}", self.shot(tool))
        except PWError as e:
            msg = str(e).splitlines()[0] if str(e) else repr(e)
            if "net::" in str(e) or "Timeout" in msg:
                return fail("transient", f"Network error: {msg}", self.shot(tool))
            if "not visible" in str(e) or "waiting for locator" in str(e) or "not an <input>" in str(e) or "No option" in str(e) or "did not find some options" in str(e):
                return fail("not_found", f"Element problem: {msg}. Call read_page again to re-check ids/options.", self.shot(tool))
            return fail("fatal", f"Browser error: {msg}", self.shot(tool))
        except Exception as e:  # never raise
            return fail("fatal", f"{type(e).__name__}: {e}", self.shot(tool))


SESSION = BrowserSession()


def set_run_dir(path: str | Path) -> None:
    SESSION.set_run_dir(path)


def close_browser() -> None:
    SESSION.close()


class _Tool:
    name = ""
    description = ""
    json_schema: dict[str, Any] = {}

    def run(self, **args: Any) -> Observation:  # pragma: no cover
        raise NotImplementedError


class Goto(_Tool):
    name = "goto"
    description = "Navigate the browser to a URL. Returns final URL and title (call read_page afterwards to see the page)."
    json_schema = schema({"url": {"type": "string", "description": "Absolute URL"}}, ["url"])

    def run(self, url: str = "", **_: Any) -> Observation:
        def go(page: Any) -> str:
            before = page.url
            page.goto(url, wait_until="load")
            SESSION.check_nav(before, requested=url)
            return SESSION.info() + (f" status={SESSION.last_status}" if SESSION.last_status else "")
        return SESSION.run(self.name, go)


class ReadPage(_Tool):
    name = "read_page"
    description = ("Return a compact text view of the current page: URL, TITLE, one line per visible interactive element "
                   "with an id like [e3], then TEXT with visible headings/messages/errors/tables. Ids regenerate on every call.")
    json_schema = schema({})

    def run(self, **_: Any) -> Observation:
        def read(page: Any) -> str:
            r = page.evaluate(_READ_JS)
            head = f"URL: {r['url']}   TITLE: {r['title']}"
            text = clip(r["text"], 4000).replace('"', "'")
            return "\n".join([head, *r["lines"], f'TEXT: "{text}"'])
        return SESSION.run(self.name, read)


class Click(_Tool):
    name = "click"
    description = "Click the element with the given id from the latest read_page. Waits for navigation/load."
    json_schema = schema({"id": {"type": "string", "description": "Element id such as e5"}}, ["id"])

    def run(self, id: str = "", **_: Any) -> Observation:
        def do(page: Any) -> str:
            loc = SESSION.locate(id)
            before = page.url
            loc.click()
            SESSION.settle()
            SESSION.check_nav(before)
            return "clicked " + SESSION.info() + ". Call read_page to see the result."
        return SESSION.run(self.name, do)


class Type(_Tool):
    name = "type"
    description = "Type text into an input/textarea by id (clears first by default). Optionally press Enter to submit."
    json_schema = schema({
        "id": {"type": "string"}, "text": {"type": "string"},
        "clear": {"type": "boolean", "description": "Clear existing value first (default true)"},
        "submit": {"type": "boolean", "description": "Press Enter afterwards (default false)"},
    }, ["id", "text"])

    def run(self, id: str = "", text: str = "", clear: bool = True, submit: bool = False, **_: Any) -> Observation:
        def do(page: Any) -> str:
            loc = SESSION.locate(id)
            before = page.url
            if clear:
                loc.fill(text)
            else:
                loc.press_sequentially(text)
            if submit:
                loc.press("Enter")
                SESSION.settle()
                SESSION.check_nav(before)
            return f"typed into {id}; " + SESSION.info()
        return SESSION.run(self.name, do)


class Select(_Tool):
    name = "select"
    description = "Choose an option (by visible text, or value) in a <select> by id."
    json_schema = schema({"id": {"type": "string"}, "option": {"type": "string"}}, ["id", "option"])

    def run(self, id: str = "", option: str = "", **_: Any) -> Observation:
        def do(page: Any) -> str:
            loc = SESSION.locate(id)
            try:
                loc.select_option(label=option, timeout=3000)
            except PWError:
                loc.select_option(value=option, timeout=3000)
            return f"selected {option!r} in {id}; " + SESSION.info()
        return SESSION.run(self.name, do)


class Screenshot(_Tool):
    name = "screenshot"
    description = "Take a labelled screenshot of the current page as evidence."
    json_schema = schema({"label": {"type": "string"}}, ["label"])

    def run(self, label: str = "screenshot", **_: Any) -> Observation:
        def do(page: Any) -> str:
            return "screenshot saved: " + SESSION.info()
        return SESSION.run(f"screenshot_{label}", do)


class Download(_Tool):
    name = "download"
    description = ("Download a file into workspace/downloads/. id_or_url is an element id (e.g. e7) of a link/button, "
                   "or a URL/path starting with http or /. filename is the saved name.")
    json_schema = schema({"id_or_url": {"type": "string"}, "filename": {"type": "string"}}, ["id_or_url", "filename"])

    def run(self, id_or_url: str = "", filename: str = "", **_: Any) -> Observation:
        def do(page: Any) -> str:
            name = re.sub(r"[^A-Za-z0-9._-]", "_", Path(filename or "download").name) or "download"
            dest = WORKSPACE / "downloads" / name
            dest.parent.mkdir(parents=True, exist_ok=True)
            if id_or_url.startswith(("http://", "https://", "/")):
                base = page.url if page.url.startswith("http") else os.getenv("SANDBOX_URL", "http://localhost:8000")
                url = urljoin(base, id_or_url)  # resolves "/path" against the current (or default) origin
                r = page.context.request.get(url)
                if r.status >= 500:
                    raise ToolFail("transient", f"HTTP {r.status} downloading {url}")
                if r.status == 404:
                    raise ToolFail("not_found", f"404 downloading {url}")
                if "/login" in r.url:
                    raise ToolFail("auth", "Redirected to login while downloading")
                dest.write_bytes(r.body())
            else:
                loc = SESSION.locate(id_or_url)
                with page.expect_download(timeout=TIMEOUT_MS) as dl:
                    loc.click()
                dl.value.save_as(str(dest))
            return f"saved {dest.relative_to(ROOT)} ({dest.stat().st_size} bytes)"
        return SESSION.run(self.name, do)


BROWSER_TOOLS: list[_Tool] = [Goto(), ReadPage(), Click(), Type(), Select(), Screenshot(), Download()]
