"""Anti-hallucination guard: typed data values must appear in observed text."""
from pathlib import Path

from agent import grounding
from agent.loop import ungrounded
from agent.memory import Memory, parse_elements
from agent.types import Action, Observation

PDF = "INVOICE Invoice Number: INV-NS-1043 Invoice Date: 29 Sep 2026 Amount Due: INR 48,250.00 Due Date: 29 Oct 2026"


def mem_with_pdf(tmp_path: Path) -> Memory:
    m = Memory(tmp_path, "enter the invoice")
    m.record(Action(tool="read_pdf", args={"path": "x.pdf"}), Observation(ok=True, data=PDF))
    m.page_text = '[e1] input  "Amount (INR)" value=""\n[e2] input  "Password" type=password value=""'
    m.elements = parse_elements(m.page_text)
    return m


def test_variants_cover_formats():
    assert grounding.is_grounded("48250.00", PDF) and grounding.is_grounded("2026-10-29", PDF)
    assert not grounding.is_grounded("48500.00", PDF) and not grounding.is_grounded("2026-10-14", PDF)


def test_typed_values_are_checked(tmp_path):
    m = mem_with_pdf(tmp_path)
    ok = Action(tool="type", args={"id": "e1", "text": "48250.00"})
    bad = Action(tool="type", args={"id": "e1", "text": "125000.00"})
    assert ungrounded(ok, m) is None and "BLOCKED" in (ungrounded(bad, m) or "")


def test_own_facts_and_plain_words_do_not_count(tmp_path):
    m = mem_with_pdf(tmp_path)
    m.record(Action(tool="remember", args={"key": "amount", "value": "99999.00"}), Observation(ok=True, data='{"value": "99999.00"}'))
    assert ungrounded(Action(tool="type", args={"id": "e1", "text": "99999.00"}), m)   # hallucinated fact can't ground itself
    assert ungrounded(Action(tool="type", args={"id": "e1", "text": "northwind"}), m) is None  # no digits -> not checked
    assert ungrounded(Action(tool="type", args={"id": "e2", "text": "s3cr3t"}), m) is None     # passwords never checked


def test_blocked_message_does_not_ground_a_retry(tmp_path):
    """Regression (T4 run 2): the guard's own 'BLOCKED: the value X ...' message must not make X grounded."""
    m = mem_with_pdf(tmp_path)
    act = Action(tool="type", args={"id": "e1", "text": "2026-10-28"})
    msg = ungrounded(act, m)
    assert msg
    m.record(act, Observation(ok=False, error_class="validation", data=msg))
    assert ungrounded(act, m)          # still blocked on the retry


def test_visited_pages_are_counted_for_the_prompt(tmp_path):
    m = Memory(tmp_path, "t")
    page = "URL: http://x/mail   TITLE: Inbox\n[e1] link \"A\" href=/a"
    for _ in range(3):
        m.record(Action(tool="read_page"), Observation(ok=True, data=page))
    s = m.visited_summary()
    assert "http://x/mail" in s and "x3" in s and "nothing new" in s
