"""Pivot control: depth, budget, junk filter, canonical selectors."""

import pytest
from factories import pivots, result_cache


@pytest.fixture(autouse=True)
def _mem(monkeypatch):
    monkeypatch.setenv("VEILED_CACHE", "memory")
    monkeypatch.setenv("VEILED_PIVOT_DEPTH", "2")
    monkeypatch.setenv("VEILED_PIVOT_BUDGET", "40")
    result_cache.clear_memory()


def res(param, tasks):
    return [{"module": "x"}, {"param": param}, {"tasks": tasks}]


def params(result):
    return [t["param"] for t in result[2]["tasks"]]


def test_depth_is_enforced_and_same_selector_is_free():
    pivots.mark_root("johndoe")
    r1 = pivots.limit(
        res(
            "johndoe",
            [
                {"module": "github", "param": "johndoe"},
                {"module": "github", "param": "tailmon"},
            ],
        )
    )
    assert params(r1) == ["johndoe", "tailmon"]
    assert pivots.depth_of("tailmon") == 1
    r2 = pivots.limit(
        res("tailmon", [{"module": "emailreg", "param": "t@tailmon.dev"}])
    )
    assert r2[2]["tasks"][0]["depth"] == 2
    r3 = pivots.limit(
        res(
            "t@tailmon.dev",
            [
                {"module": "maigret", "param": "deeperone"},
                {"module": "gravatar", "param": "T@tailmon.dev"},
            ],
        )
    )
    assert params(r3) == ["T@tailmon.dev"]  # same selector, any case


def test_root_resets_previous_depth():
    pivots.mark_root("alpha1")
    pivots.limit(res("alpha1", [{"module": "m", "param": "bravo2"}]))
    pivots.limit(res("bravo2", [{"module": "m", "param": "charlie3"}]))
    assert pivots.depth_of("charlie3") == 2
    pivots.mark_root("charlie3")
    assert pivots.depth_of("charlie3") == 0


def test_shortest_path_wins():
    pivots.mark_root("alpha1")
    pivots.limit(res("alpha1", [{"module": "m", "param": "bravo2"}]))
    pivots.limit(res("bravo2", [{"module": "m", "param": "charlie3"}]))
    pivots.limit(res("alpha1", [{"module": "m", "param": "charlie3"}]))
    assert pivots.depth_of("charlie3") == 1


@pytest.mark.parametrize(
    ("value", "ok"),
    [
        ("john.doe@acme.com", True),
        ("noreply@acme.com", False),
        ("info@acme.com", False),
        ("x@example.com", False),
        ("42+tailmon@users.noreply.github.com", False),
        ("+90 532 123 45 67", True),
        ("+90 123", False),
        ("tailmon", True),
        ("ab", False),
        ("admin", False),
        ("github", False),
        ("123", False),
        ("1234567890", True),  # numeric account id
        ("0x52908400098527886E0F7030069857D2E4169EE7", True),
    ],
)
def test_worth_following(value, ok):
    assert pivots.worth_following(value) is ok


def test_canonical_forms():
    assert (
        pivots.canonical("+90 532 123 45 67")
        == pivots.canonical("05321234567")
        == "+905321234567"
    )
    assert pivots.canonical("John@ACME.com") == "john@acme.com"
    assert pivots.canonical("@TailMon") == "tailmon"


def test_budget_caps_new_selectors_per_root(monkeypatch):
    monkeypatch.setenv("VEILED_PIVOT_BUDGET", "3")
    pivots.mark_root("rootuser")
    tasks = [{"module": "maigret", "param": f"handle{i}"} for i in range(6)]
    out = pivots.limit(res("rootuser", tasks))
    assert params(out) == ["handle0", "handle1", "handle2"]
    # already-known selectors are free
    again = pivots.limit(res("rootuser", [{"module": "github", "param": "handle1"}]))
    assert params(again) == ["handle1"]


def test_duplicate_tasks_written_two_ways_collapse():
    pivots.mark_root("rootuser")
    out = pivots.limit(
        res(
            "rootuser",
            [
                {"module": "phone", "param": "+90 532 123 45 67"},
                {"module": "phone", "param": "05321234567"},
            ],
        )
    )
    assert len(out[2]["tasks"]) == 1
