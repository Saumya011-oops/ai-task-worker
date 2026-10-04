"""Recovery tests: retry runner + stuck detection, with fake tools and no real sleeping."""
from __future__ import annotations

from types import SimpleNamespace

import pytest

from agent import recovery
from agent.memory import Memory
from agent.types import Action, Observation
from tools import base


class Scripted:
    """Fake tool: returns the scripted observations in order (last one repeats) and counts calls."""
    description = "fake"
    json_schema = {"type": "object", "properties": {}}

    def __init__(self, name: str, results: list[Observation]):
        self.name, self.results, self.calls = name, results, 0

    def run(self, **args):
        r = self.results[min(self.calls, len(self.results) - 1)]
        self.calls += 1
        return r


def bad(cls: str) -> Observation:
    return Observation(ok=False, data=f"{cls} problem", error_class=cls)


GOOD = Observation(ok=True, data="fine")


@pytest.fixture
def env(tmp_path, monkeypatch):
    saved = dict(base.REGISTRY)
    sleeps: list[float] = []
    monkeypatch.setattr(recovery.time, "sleep", lambda s: sleeps.append(s))
    logs: list[str] = []
    mem = Memory(tmp_path, "task")

    def run(tool: Scripted):
        base.register(tool)
        return recovery.run_with_retries(Action(tool=tool.name), mem, logs.append)
    yield SimpleNamespace(run=run, mem=mem, logs=logs, sleeps=sleeps)
    base.REGISTRY.clear()
    base.REGISTRY.update(saved)


def test_transient_retried_three_times_then_returned(env):
    t = Scripted("fake_t", [bad("transient")])
    obs = env.run(t)
    assert not obs.ok and obs.error_class == "transient"
    assert t.calls == 4
    assert len(env.mem.recoveries) == 3 and all("transient" in r for r in env.mem.recoveries)
    assert env.sleeps == [1, 2, 4]


def test_transient_then_success(env):
    t = Scripted("fake_t2", [bad("transient"), GOOD])
    obs = env.run(t)
    assert obs.ok and obs.data.endswith("fine") and "automatic retry" in obs.data and t.calls == 2
    assert len(env.mem.recoveries) == 1


@pytest.mark.parametrize("cls", ["validation", "not_found", "ambiguous", "fatal"])
def test_semantic_errors_not_retried(env, cls):
    t = Scripted("fake_s", [bad(cls)])
    obs = env.run(t)
    assert obs.error_class == cls and t.calls == 1 and env.mem.recoveries == []


def test_auth_relogin_success_then_retry(env, monkeypatch):
    calls = []
    monkeypatch.setattr(recovery, "relogin", lambda: calls.append(1) or True)
    env.mem.logged_in = True    # an expired session (we were logged in before) counts as a recovery
    t = Scripted("fake_a", [bad("auth"), GOOD])
    obs = env.run(t)
    assert obs.ok and t.calls == 2 and len(calls) == 1
    assert any("re-login" in r for r in env.mem.recoveries)


def test_auth_relogin_failure_returns_auth(env, monkeypatch):
    monkeypatch.setattr(recovery, "relogin", lambda: False)
    t = Scripted("fake_a2", [bad("auth"), GOOD])
    obs = env.run(t)
    assert not obs.ok and obs.error_class == "auth" and "Re-login failed" in obs.data
    assert t.calls == 1


# ---- stuck detection ----
def A(tool="click", **args):
    return Action(tool=tool, args=args)


def test_stuck_replan_then_ask_human():
    s = recovery.Stuck()
    a, o = A(id="e1"), Observation(ok=False, data="same", error_class="validation")
    assert [s.check(a, o), s.check(a, o), s.check(a, o)] == [None, None, "replan"]
    assert [s.check(a, o), s.check(a, o), s.check(a, o)] == [None, None, "ask_human"]


def test_stuck_distinct_calls_never_trigger():
    s = recovery.Stuck()
    for i in range(20):      # every call differs -> never stuck
        assert s.check(A(id=f"e{i}"), Observation(ok=True, data="x")) is None


def test_stuck_catches_alternating_repeats_within_window():
    """Regression (T3b): A,B,A,B,A dodged a consecutive-only detector and burned 15 steps."""
    s = recovery.Stuck()
    a, b = A(id="e1"), A(id="e2")
    o = Observation(ok=True, data="same")
    assert [s.check(a, o), s.check(b, o), s.check(a, o), s.check(b, o)] == [None] * 4
    assert s.check(a, o) == "replan"          # 3rd identical call (a) inside the 8-step window


def test_stuck_changed_result_is_not_a_repeat():
    s = recovery.Stuck()
    a = A(id="e1")
    assert [s.check(a, Observation(ok=True, data=str(i))) for i in range(6)] == [None] * 6


def test_first_login_is_not_counted_as_recovery(env, monkeypatch):
    monkeypatch.setattr(recovery, "relogin", lambda: True)
    t = Scripted("fake_first", [bad("auth"), GOOD])
    obs = env.run(t)
    assert obs.ok and env.mem.logged_in and env.mem.recoveries == []
