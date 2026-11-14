"""Günlük güncelleme: bir ülkenin hatası diğerlerini durdurmaz, istisnalar yakalanır."""

import httpx

from app import update


def _fake(monkeypatch, failing: dict[str, object]):
    calls: list[list[str]] = []

    def ingest(args: list[str]) -> int:
        calls.append(["ingest", *args])
        cc = args[args.index("--country") + 1]
        result = failing.get(cc, 0)
        if isinstance(result, Exception):
            raise result
        return int(result)

    def harmonize(args: list[str]) -> int:
        calls.append(["harmonize", *args])
        return 0

    monkeypatch.setattr(update, "ingest_main", ingest)
    monkeypatch.setattr(update, "harmonize_main", harmonize)
    return calls


def test_failed_country_does_not_block_the_others(monkeypatch):
    calls = _fake(monkeypatch, {"TR": httpx.ConnectError("offline"), "US": 1})
    failures = update._run(["AZ", "TR", "US", "GR"], bootstrap=False, optimize=False)
    assert failures == ["ingest TR: ConnectError", "ingest US: çıkış kodu 1"]
    harm = [c for c in calls if c[0] == "harmonize"]
    assert len(harm) == 1 and harm[0][harm[0].index("--country") + 1] == "AZ,GR"


def test_nothing_is_harmonized_when_every_ingest_fails(monkeypatch):
    calls = _fake(monkeypatch, {"AZ": 3})
    assert update._run(["AZ"], bootstrap=False, optimize=False) == ["ingest AZ: çıkış kodu 3"]
    assert not [c for c in calls if c[0] == "harmonize"]


def test_bootstrap_skips_optimize_unless_asked(monkeypatch):
    _fake(monkeypatch, {})
    ran = []
    monkeypatch.setattr(update, "optimize_main", lambda: ran.append(1) or 0)
    assert update._run(["AZ"], bootstrap=True, optimize=False) == [] and ran == []
    assert update._run(["AZ"], bootstrap=True, optimize=True) == [] and ran == [1]
