"""Policy gate tests against the real company/policies.yaml (offline; fake read-only lookup tool)."""
from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

from agent import policy_gate as pg
from agent.memory import Memory, parse_elements
from agent.types import Action, Observation
from tools import base

NEW_BILL_URL = "http://localhost:8000/erp/bills/new"


def page_text(button: str = "Save bill") -> str:
    return (f"URL: {NEW_BILL_URL}   TITLE: New Bill\n"
            '[e1] select "Vendor" options=[Alpha, Beta]\n'
            '[e2] input  "Invoice number" value=""\n'
            '[e3] input  "Amount (INR)" value=""\n'
            f'[e4] button "{button}"\n[e5] link "Cancel" href=/erp/bills\n'
            'TEXT: "New bill"')


def make_mem(tmp_path, amount: str, button: str = "Save bill", vendor: str = "V1", inv: str = "INV-NS-1043",
             url: str = NEW_BILL_URL) -> Memory:
    mem = Memory(tmp_path, "task")
    mem.page_url = url
    mem.page_text = page_text(button).replace(NEW_BILL_URL, url)
    mem.elements = parse_elements(mem.page_text)
    mem.form = {"Vendor": {"kind": "select", "value": vendor},
                "Invoice number": {"kind": "input", "value": inv},
                "Amount (INR)": {"kind": "input", "value": amount}}
    return mem


@pytest.fixture(scope="module")
def policies():
    return pg.load_policies()


@pytest.fixture
def fake_bills():
    """Register a fake erp_list_bills; yields a setter for the records it returns."""
    saved = base.REGISTRY.get("erp_list_bills")
    state = {"records": []}

    class FakeBills:
        name = "erp_list_bills"
        description = "fake"
        json_schema = {"type": "object", "properties": {}}

        def run(self, **args):
            state["args"] = args
            return Observation(ok=True, data=json.dumps(state["records"]))

    base.register(FakeBills())
    yield state
    if saved is None:
        base.REGISTRY.pop("erp_list_bills", None)
    else:
        base.REGISTRY["erp_list_bills"] = saved


@pytest.mark.parametrize("button", ["Save bill", "Create bill"])
def test_large_amount_needs_approval(tmp_path, policies, button, fake_bills):
    mem = make_mem(tmp_path, "240000", button)
    d = pg.check(Action(tool="click", args={"id": "e4"}), mem, policies)
    assert d.verdict == "needs_approval" and d.trigger == "erp.create_bill"


def test_indian_formatted_large_amount(tmp_path, policies, fake_bills):
    d = pg.check(Action(tool="click", args={"id": "e4"}), make_mem(tmp_path, "2,40,000.00"), policies)
    assert d.verdict == "needs_approval"


def test_small_amount_allowed(tmp_path, policies, fake_bills):
    d = pg.check(Action(tool="click", args={"id": "e4"}), make_mem(tmp_path, "48,250.00"), policies)
    assert d.verdict == "allow"


def test_threshold_boundary(tmp_path, policies, fake_bills):
    act = Action(tool="click", args={"id": "e4"})
    assert pg.check(act, make_mem(tmp_path, "100000"), policies).verdict == "allow"
    assert pg.check(act, make_mem(tmp_path, "100000.01"), policies).verdict == "needs_approval"


def test_unrelated_actions_allowed(tmp_path, policies):
    mem = make_mem(tmp_path, "240000")
    assert pg.check(Action(tool="goto", args={"url": "http://x/"}), mem, policies).verdict == "allow"
    assert pg.check(Action(tool="click", args={"id": "e5"}), mem, policies).verdict == "allow"   # Cancel link
    assert pg.check(Action(tool="click", args={"id": "e99"}), mem, policies).verdict == "allow"  # unknown id
    other = make_mem(tmp_path, "240000", url="http://localhost:8000/erp/vendors")
    assert pg.check(Action(tool="click", args={"id": "e4"}), other, policies).verdict == "allow"


def test_duplicate_blocks(tmp_path, policies, fake_bills):
    fake_bills["records"] = [{"id": 7, "vendor_id": "V1", "invoice_number": "INV-NS-1043", "amount_inr": 48250}]
    d = pg.check(Action(tool="click", args={"id": "e4"}), make_mem(tmp_path, "48,250.00"), policies)
    assert d.verdict == "block" and "Duplicate" in d.reason
    assert fake_bills["args"] == {"invoice_number": "INV-NS-1043"}  # lookup arg built from the form field


def test_duplicate_blocks_even_when_large(tmp_path, policies, fake_bills):
    fake_bills["records"] = [{"id": 8, "vendor_id": "V1", "invoice_number": "INV-NS-1043"}]
    d = pg.check(Action(tool="click", args={"id": "e4"}), make_mem(tmp_path, "240000"), policies)
    assert d.verdict == "block"


def test_no_matching_record_allows(tmp_path, policies, fake_bills):
    fake_bills["records"] = [{"id": 9, "vendor_id": "V2", "invoice_number": "INV-NS-1043"},   # other vendor
                             {"id": 10, "vendor_id": "V1", "invoice_number": "OTHER"}]       # other invoice
    assert pg.check(Action(tool="click", args={"id": "e4"}), make_mem(tmp_path, "48,250.00"), policies).verdict == "allow"
    fake_bills["records"] = []
    assert pg.check(Action(tool="click", args={"id": "e4"}), make_mem(tmp_path, "48,250.00"), policies).verdict == "allow"


def test_always_condition_and_bad_conditions():
    assert pg._holds("always", {}) is True
    assert pg._holds("amount_inr > 5", {}) is None            # missing field -> cannot evaluate (fail closed upstream)
    assert pg._holds("garbage", {"x": "1"}) is None
    assert pg._holds("amount_inr >= 10", {"amount_inr": "INR 10.00"}) is True


def test_always_approval_trigger(tmp_path):
    synth = {
        "triggers": {"erp.update_vendor_bank": {
            "tool": "click", "url_contains": "/erp/vendors/", "button_labels": ["Update bank details"],
            "fields": {"account": "Account number"}}},
        "approval_required": [{"action": "erp.update_vendor_bank", "when": "always", "reason": "fraud vector"}],
    }
    mem = Memory(tmp_path, "task")
    mem.page_url = "http://localhost:8000/erp/vendors/V1/bank"
    mem.page_text = f'URL: {mem.page_url}\n[e1] input  "Account number" value="123"\n[e2] button "Update bank details"'
    mem.elements = parse_elements(mem.page_text)
    d = pg.check(Action(tool="click", args={"id": "e2"}), mem, synth)
    assert d.verdict == "needs_approval" and d.trigger == "erp.update_vendor_bank" and "fraud" in d.reason


# ---- fail-closed + bypass coverage (added after code review) -------------------------------------
def test_unreadable_amount_requires_approval(tmp_path, policies, fake_bills):
    d = pg.check(Action(tool="click", args={"id": "e4"}), make_mem(tmp_path, ""), policies)
    assert d.verdict == "needs_approval" and "Cannot evaluate" in d.reason


def test_enter_key_submit_is_gated(tmp_path, policies, fake_bills):
    act = Action(tool="type", args={"id": "e3", "text": "240000", "submit": True})
    assert pg.check(act, make_mem(tmp_path, "240000"), policies).verdict == "needs_approval"


def test_renamed_unknown_button_is_still_gated(tmp_path, policies, fake_bills):
    assert pg.check(Action(tool="click", args={"id": "e4"}), make_mem(tmp_path, "240000", button="Submit now"),
                    policies).verdict == "needs_approval"


def test_duplicate_lookup_failure_blocks(tmp_path, policies, fake_bills, monkeypatch):
    monkeypatch.setattr(pg.time, "sleep", lambda *_: None)
    base.REGISTRY["erp_list_bills"].run = lambda **a: Observation(ok=False, error_class="transient", data="500")
    d = pg.check(Action(tool="click", args={"id": "e4"}), make_mem(tmp_path, "100"), policies)
    assert d.verdict == "block" and "Cannot verify" in d.reason


def test_duplicate_lookup_garbage_blocks(tmp_path, policies, fake_bills):
    base.REGISTRY["erp_list_bills"].run = lambda **a: Observation(ok=True, data='[{"id": 1, "x" ... [truncated')
    assert pg.check(Action(tool="click", args={"id": "e4"}), make_mem(tmp_path, "100"), policies).verdict == "block"
