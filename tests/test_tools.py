"""Offline tests for tools/ and llm/client.py (local http.server only; no LLM calls)."""
from __future__ import annotations

import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from types import SimpleNamespace as NS

import pytest
from pydantic import BaseModel

from llm import client as llmc
from tools import base
from tools.browser import SESSION, Click, Download, Goto, ReadPage, Select, Type, close_browser, set_run_dir
from tools.files import ListDir, ReadFile, ReadPdf, WriteCsv, WriteFile
from tools.registry import build_registry, tool_schemas

FORM = """<html><head><title>Test Form</title></head><body><nav><a href="/other">Other</a></nav>
<h1>New Thing</h1><div class="error">Amount is bad</div>
<form action="/submit" method="get">
<label for="v">Vendor</label><select id="v" name="v"><option value="">-- select --</option><option value="V1">Alpha</option><option value="V2">Beta</option></select>
<label for="n">Invoice number</label><input id="n" name="n">
<label>Due <input type="date" name="d"></label>
<textarea aria-label="Notes" name="notes"></textarea>
<button type="submit">Save bill</button></form>
<table><tr><th>ID</th><th>Name</th></tr><tr><td>1</td><td>Zed</td></tr></table>
<input type="hidden" name="h"><div style="display:none"><button>Ghost</button></div></body></html>"""


TAGGED = """<html><head><title>Tagged</title></head><body>
<label for="amt">Amount (INR)</label><input id="amt" name="amt">
<button id="vis">Visible</button><button hidden>Hidden btn</button>
<div style="visibility:hidden"><input aria-label="Invisible field"></div>
<input type="hidden" name="h"><a href="/x">Go</a></body></html>"""


class H(BaseHTTPRequestHandler):
    def log_message(self, *a): pass

    def do_GET(self):
        p = self.path
        if p.startswith("/form"):
            self._send(200, FORM)
        elif p.startswith("/tagged"):
            self._send(200, TAGGED)
        elif p.startswith("/submit"):
            self._send(200, "<title>Done</title><h1>Submitted</h1>")
        elif p.startswith("/boom"):
            self._send(500, "Internal Server Error")
        elif p.startswith("/secret"):
            self.send_response(303); self.send_header("Location", "/erp/login?next=/secret"); self.end_headers()
        elif p.startswith("/erp/login"):
            self._send(200, "<title>Login</title><h1>Sign in</h1>")
        elif p.startswith("/file.txt"):
            self._send(200, "hello", "text/plain")
        else:
            self._send(404, "nope")

    def _send(self, code, body, ct="text/html"):
        b = body.encode()
        self.send_response(code); self.send_header("Content-Type", ct)
        self.send_header("Content-Length", str(len(b))); self.end_headers(); self.wfile.write(b)


@pytest.fixture(scope="module")
def server(tmp_path_factory):
    srv = HTTPServer(("127.0.0.1", 0), H)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    set_run_dir(tmp_path_factory.mktemp("run"))
    yield f"http://127.0.0.1:{srv.server_port}"
    srv.shutdown(); close_browser()


def ids(txt: str) -> dict[str, str]:
    """Map element name -> id from read_page output."""
    out = {}
    for line in txt.splitlines():
        if line.startswith("[e"):
            out[line.split('"')[1]] = line[1:line.index("]")]
    return out


def test_read_page_format_and_actions(server):
    assert Goto().run(url=server + "/form").ok
    obs = ReadPage().run()
    assert obs.ok and obs.screenshot
    t = obs.data
    assert t.startswith(f"URL: {server}/form   TITLE: Test Form")
    assert 'select "Vendor" options=[Alpha, Beta]' in t
    assert 'input  "Invoice number" value=""' in t
    assert 'input  "Due" type=date value=""' in t
    assert 'textarea "Notes" value=""' in t
    assert 'button "Save bill"' in t and "Ghost" not in t
    assert 'link "Other" href=/other' in t
    assert "| ID | Name |" in t and "| 1 | Zed |" in t and "Amount is bad" in t
    m = ids(t)
    assert Select().run(id=m["Vendor"], option="Beta").ok
    assert Type().run(id=m["Invoice number"], text="INV-1").ok
    assert Type().run(id=m["Due"], text="2026-10-29").ok
    r = Click().run(id=m["Save bill"])
    assert r.ok and "v=V2" in r.data and "n=INV-1" in r.data and "d=2026-10-29" in r.data
    assert "Submitted" in ReadPage().run().data


def test_not_found_and_errors(server):
    Goto().run(url=server + "/form"); ReadPage().run()
    r = Click().run(id="e99")
    assert not r.ok and r.error_class == "not_found" and "read_page" in r.data
    assert Click().run(id="bogus").error_class == "not_found"
    assert Goto().run(url=server + "/boom").error_class == "transient"
    assert Goto().run(url=server + "/secret").error_class == "auth"
    assert Goto().run(url=server + "/erp/login").ok  # intended login -> fine
    assert Goto().run(url="http://127.0.0.1:1/").error_class == "transient"


def test_download(server):
    Goto().run(url=server + "/form")
    r = Download().run(id_or_url=server + "/file.txt", filename="t_dl.txt")
    assert r.ok
    from tools._util import WORKSPACE
    p = WORKSPACE / "downloads" / "t_dl.txt"
    assert p.read_text() == "hello"; p.unlink()


def test_files_sandbox():
    assert WriteFile().run(path="outputs/_t.txt", content="hi").ok
    assert ReadFile().run(path="outputs/_t.txt").data == "hi"
    assert "_t.txt" in ListDir().run(path="outputs").data
    assert WriteCsv().run(path="outputs/_t.csv", rows=[{"a": 1, "b": 2}, {"a": 3, "b": 4}]).ok
    assert ReadFile().run(path="outputs/_t.csv").data.splitlines()[0] == "a,b"
    assert ReadFile().run(path="../CLAUDE.md").error_class == "validation"
    assert WriteFile().run(path="/etc/x", content="x").error_class == "validation"
    assert ReadFile().run(path="nope.txt").error_class == "not_found"
    assert ReadPdf().run(path="nope.pdf").error_class == "not_found"
    from tools._util import WORKSPACE
    (WORKSPACE / "outputs/_t.txt").unlink(); (WORKSPACE / "outputs/_t.csv").unlink()


def test_registry():
    build_registry(); build_registry()
    names = {s["name"] for s in tool_schemas()}
    assert names == {"goto", "read_page", "click", "type", "select", "screenshot", "download", "list_dir", "read_file",
                     "read_pdf", "write_file", "write_csv", "erp_list_bills", "erp_list_vendors", "ask_human",
                     "finish", "remember"}
    assert len(base.REGISTRY) == len(names)


def test_human_hooks():
    from tools import human
    human.set_answer_provider(lambda q, o: "yes")
    assert human.AskHuman().run(question="ok?").data == "Human answered: yes"
    human.set_answer_provider(None)
    assert human.Finish().run(summary="s", claims=["c"]).ok


# ---- llm client (offline) ---------------------------------------------------------------------
def mk(provider="anthropic"):
    return llmc.LLMClient(provider=provider, model="m", api_key="k")


def test_client_config_errors(monkeypatch):
    with pytest.raises(llmc.LLMError):
        llmc.LLMClient(provider="bogus", model="m", api_key="k")
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    with pytest.raises(llmc.LLMError):
        llmc.LLMClient(provider="openai", model="m", api_key="")


def test_schema_and_messages():
    tools = [{"name": "goto", "description": "d", "parameters": {"type": "object", "properties": {"url": {"type": "string"}}}}]
    t2 = llmc.with_thought(tools)
    assert "thought" in t2[0]["parameters"]["properties"] and "thought" not in tools[0]["parameters"]["properties"]
    msgs = llmc.normalize_messages([{"role": "user", "content": "a"}, {"role": "assistant", "content": "b"},
                                    {"role": "tool", "content": "r1"}, {"role": "user", "content": "hint"}])
    assert [m["role"] for m in msgs] == ["user", "assistant", "user"]
    assert msgs[2]["content"].startswith("Observation: r1")


def test_parsers():
    a = NS(content=[NS(type="text", text="thinking"), NS(type="tool_use", name="goto", input={"url": "x"})])
    assert llmc.parse_anthropic(a) == ("thinking", "goto", {"url": "x"})
    o = NS(choices=[NS(message=NS(content=None, tool_calls=[NS(function=NS(name="click", arguments='{"id":"e1"}'))]))])
    assert llmc.parse_openai(o) == ("", "click", {"id": "e1"})
    g = NS(candidates=[NS(content=NS(parts=[NS(text="hm", function_call=None),
                                            NS(text=None, function_call=NS(name="read_page", args={}))]))])
    assert llmc.parse_gemini(g) == ("hm", "read_page", {})
    bad = NS(choices=[NS(message=NS(content=None, tool_calls=[NS(function=NS(name="x", arguments="{bad"))]))])
    with pytest.raises(llmc.LLMError):
        llmc.parse_openai(bad)


def test_next_action_and_structured(monkeypatch):
    c = mk()
    tools = [{"name": "goto", "description": "d", "parameters": {"type": "object", "properties": {}}}]
    monkeypatch.setattr(c, "_raw", lambda m, t, s: ("", "goto", {"thought": "why", "url": "u"}))
    act = c.next_action([{"role": "user", "content": "x"}], tools)
    assert (act.tool, act.thought, act.args) == ("goto", "why", {"url": "u"})
    monkeypatch.setattr(c, "_raw", lambda m, t, s: ("just text", None, {}))
    with pytest.raises(llmc.LLMError):
        c.next_action([{"role": "user", "content": "x"}], tools)
    monkeypatch.setattr(c, "_raw", lambda m, t, s: ("", "nope", {}))
    with pytest.raises(llmc.LLMError):
        c.next_action([{"role": "user", "content": "x"}], tools)

    class S(BaseModel):
        a: int
    monkeypatch.setattr(c, "_raw", lambda m, t, s: ("", "respond", {"a": 3}))
    assert c.structured([{"role": "user", "content": "x"}], S).a == 3
    monkeypatch.setattr(c, "_raw", lambda m, t, s: ("", "respond", {"a": "zz"}))
    with pytest.raises(llmc.LLMError):
        c.structured([{"role": "user", "content": "x"}], S)


# ---- additional tests: tagged elements + seeded PDFs ------------------------------------------
def test_read_page_tags_elements(server):
    assert Goto().run(url=server + "/tagged").ok
    t = ReadPage().run().data
    lines = [ln for ln in t.splitlines() if ln.startswith("[e")]
    assert [ln.split("]")[0] for ln in lines] == ["[e1", "[e2", "[e3"]       # sequential [eN] ids
    assert 'input  "Amount (INR)" value=""' in t                              # label-for gives the name
    assert 'button "Visible"' in t and 'link "Go" href=/x' in t
    assert "Hidden btn" not in t and "Invisible field" not in t               # hidden elements get no id
    assert ids(t)["Amount (INR)"] == "e1"


@pytest.fixture
def pdf_dir():
    import shutil
    import uuid
    from tools._util import ROOT, WORKSPACE
    src = ROOT / "sandbox" / "data" / "invoices"
    d = WORKSPACE / f"_test_tmp_{uuid.uuid4().hex[:8]}"
    d.mkdir(parents=True)
    for f in src.glob("*.pdf"):
        shutil.copy(f, d / f.name)
    yield d
    shutil.rmtree(d, ignore_errors=True)


@pytest.mark.parametrize("name,inv,amount,due", [
    ("INV-NS-1043", "INV-NS-1043", "INR 48,250.00", "29 Oct 2026"),
    ("GX-7781", "GX-7781", "INR 240,000.00", "30 Oct 2026"),
])
def test_read_pdf_seeded_invoices(pdf_dir, name, inv, amount, due):
    from tools._util import WORKSPACE
    f = pdf_dir / f"{name}.pdf"
    if not f.exists():
        pytest.skip(f"seeded PDF {name}.pdf not generated yet")
    r = ReadPdf().run(path=str(f.relative_to(WORKSPACE)))
    assert r.ok, r.data
    assert inv in r.data and amount in r.data and due in r.data
