"""Fingerprint diff: new / persisting / fixed across runs (drives status + the CI gate)."""

from __future__ import annotations

from tarnish.baseline import diff


def test_diff_classifies_fingerprints():
    previous = {"a", "b", "c"}
    current = {"b", "c", "d"}  # d is new, b/c persist, a is fixed
    new, persisting, fixed = diff(current, previous)
    assert new == {"d"}
    assert persisting == {"b", "c"}
    assert fixed == {"a"}


def test_first_run_is_all_new():
    new, persisting, fixed = diff({"a", "b"}, set())
    assert new == {"a", "b"}
    assert not persisting and not fixed
