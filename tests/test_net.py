"""Acces reseau commun (infra/net.py) et normalisation partagee (core/text.py)."""

import threading

from beheread.core import series
from beheread.core.text import GENERIC_NAMES, strip_accents
from beheread.infra import metadata, net


def test_rate_limiter_spaces_requests():
    # horloge propre au limiteur : jamais le module time, partage par tous
    # les threads (un thread d'un autre test aurait calcule une attente folle)
    clock, slept = [100.0], []
    limiter = net.RateLimiter(2.0, clock=lambda: clock[0],
                              sleep=lambda s: slept.append(round(s, 3)))
    limiter.wait()
    limiter.wait()          # meme instant : attend un intervalle
    limiter.wait()          # creneau suivant deja reserve : deux intervalles
    assert slept == [2.0, 4.0]


def test_rate_limiter_honours_a_requested_pause():
    clock, slept = [100.0], []
    limiter = net.RateLimiter(1.0, clock=lambda: clock[0],
                              sleep=lambda s: slept.append(round(s, 3)))
    limiter.back_off(30)
    limiter.wait()
    assert slept == [30.0]


class _Error:
    def __init__(self, value):
        self.headers = {} if value is None else {"Retry-After": value}


def test_retry_after_reads_the_header_and_is_bounded():
    assert net.retry_after(_Error("12")) == 12.0
    assert net.retry_after(_Error(None)) == net.DEFAULT_BACK_OFF
    assert net.retry_after(_Error("bientot")) == net.DEFAULT_BACK_OFF
    assert net.retry_after(_Error("99999")) == net.MAX_BACK_OFF


def test_app_user_agent_names_the_project():
    assert "codingt0m/beheread" in net.APP_USER_AGENT


def test_strip_accents_keeps_series_keys_unchanged():
    assert strip_accents("Pokémon Lumière") == "Pokemon Lumiere"
    assert strip_accents("ｆｕｌｌ") == "full"                 # pleine chasse ramenee
    assert strip_accents("ｆｕｌｌ", compat=False) == "ｆｕｌｌ"   # cles de serie : NFD seul
    assert series.normalize_name("Gloutons & Dragons") == "gloutons dragons"


def test_generic_names_are_never_searched_online():
    assert "volumes" in GENERIC_NAMES and "scans" in GENERIC_NAMES
    for name in ("Volumes", "Tome", "Scans", "  "):
        assert not metadata._searchable(name)
    assert metadata._searchable("Akira")


def test_series_search_is_shared_by_the_volumes_of_a_series(monkeypatch):
    """Tous les tomes d'une serie (et le worker serie) partagent une seule
    recherche, meme lancee en parallele."""
    calls, release = [], threading.Event()

    def search(query, author_hint=None):
        calls.append(query)
        release.wait(5)
        return {"authors": ["Kentaro Miura"], "source": "anilist"}, True

    monkeypatch.setattr(metadata, "_search_series_sources", search)
    results = []
    threads = [threading.Thread(target=lambda: results.append(
        metadata._search_series_once("Berserk"))) for _ in range(4)]
    for t in threads:
        t.start()
    release.set()
    for t in threads:
        t.join(5)
    results.append(metadata._search_series_once("Berserk"))
    assert calls == ["Berserk"]
    assert all(r[0]["authors"] == ["Kentaro Miura"] for r in results) and len(results) == 5


def test_series_search_failure_is_not_remembered(monkeypatch):
    calls = []

    def search(query, author_hint=None):
        calls.append(query)
        return None, False

    monkeypatch.setattr(metadata, "_search_series_sources", search)
    assert metadata._search_series_once("Berserk") == (None, False)
    assert metadata._search_series_once("Berserk") == (None, False)
    assert len(calls) == 2
    metadata.clear_series_memo()
