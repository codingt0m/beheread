"""Recherche de la bibliotheque : normalisation, index inverse, tolerance aux
fautes de frappe (logique pure, voir core/search.py)."""

import pytest

from beheread.core.search import SearchIndex, fold, known_titles, near_prefix, tokenize


@pytest.mark.parametrize("raw, folded", [
    ("Pokémon", "pokemon"),
    ("Kōhei Horikoshi", "kohei horikoshi"),
    ("Gloutons & Dragons", "gloutons dragons"),
    ("gloutons-dragons", "gloutons dragons"),
    ("One_Piece_T01", "one piece t 1"),
    ("Dr. Stone", "dr stone"),
    ("L'Attaque des Titans", "l attaque des titans"),
    ("Cœur", "coeur"),
    ("Berserk Vol.007", "berserk vol 7"),
    ("20th Century Boys", "20 th century boys"),
    ("Area 0", "area 0"),
    ("Mob Psycho 100", "mob psycho 100"),
    ("ＦＵＬＬＷＩＤＴＨ １２", "fullwidth 12"),
])
def test_fold(raw, folded):
    assert fold(raw) == folded


def test_tokenize_dedupes_and_ignores_punctuation():
    assert tokenize("  Chainsaw -- chainsaw MAN! ") == ["chainsaw", "man"]
    assert tokenize("?!  ...") == []


def _library():
    idx = SearchIndex()
    for v in range(1, 20):
        idx.set(f"csm{v}", [f"Chainsaw Man - Tome {v:02}", "Chainsaw Man", "Tatsuki Fujimoto"])
    idx.set("fp1", ["Fire Punch T01", "Fire Punch", "Tatsuki Fujimoto"])
    idx.set("bsk12", ["Berserk_T12", "Berserk", "Kentarou Miura"])
    idx.set("bsk120", ["Berserk_T120", "Berserk", "Kentarou Miura"])
    idx.set("poke", ["Pokémon La grande aventure 3", "Pokémon La grande aventure", ""])
    idx.set("gd", ["gloutons-dragons 1", "Gloutons & Dragons", None])
    return idx


def ids(idx, q):
    res = idx.search(q)
    return None if res is None else set(res.ids)


def test_empty_query_means_no_filter():
    idx = _library()
    assert idx.search("") is None
    assert idx.search("  - ") is None


def test_author_and_partial_words_match():
    idx = _library()
    assert ids(idx, "fujimoto") == {f"csm{v}" for v in range(1, 20)} | {"fp1"}
    assert ids(idx, "saw") == {f"csm{v}" for v in range(1, 20)}   # milieu de mot
    assert ids(idx, "FUJI") == ids(idx, "fujimoto")


def test_all_words_must_match_across_fields():
    idx = _library()
    assert ids(idx, "fujimoto fire") == {"fp1"}
    assert ids(idx, "chainsaw berserk") == set()


def test_numbers_match_whole_numbers_only():
    idx = _library()
    assert ids(idx, "berserk 12") == {"bsk12"}
    assert ids(idx, "berserk 120") == {"bsk120"}
    assert ids(idx, "chainsaw 1") == {"csm1"}           # pas 10..19
    assert ids(idx, "chainsaw t01") == {"csm1"}         # zeros de tete ignores


def test_accents_and_punctuation_are_ignored():
    idx = _library()
    assert ids(idx, "pokemon") == {"poke"}
    assert ids(idx, "POKÉMON aventure") == {"poke"}
    assert ids(idx, "gloutons & dragons") == {"gd"}
    assert ids(idx, "gloutons_dragons") == {"gd"}


def test_typos_fall_back_to_approximate_results():
    idx = _library()
    res = idx.search("fujimotto")
    assert res.approximate and set(res.ids) == ids(idx, "fujimoto")
    assert set(idx.search("berzerk").ids) == {"bsk12", "bsk120"}
    assert set(idx.search("chainsow 3").ids) == {"csm3"}
    assert set(idx.search("fujimot").ids) == ids(idx, "fujimoto")   # exact (sous-chaine)
    assert not idx.search("fujimot").approximate


def test_no_fuzzy_for_short_words_numbers_or_unrelated_words():
    idx = _library()
    assert ids(idx, "mam") == set()        # trop court pour tolerer une faute
    assert ids(idx, "chainsaw 99") == set()
    assert ids(idx, "zzzzzz") == set()


def test_update_and_discard_keep_postings_consistent():
    idx = _library()
    idx.set("fp1", ["Fire Punch T01", "Fire Punch", ""])   # auteur retire
    assert "fp1" not in ids(idx, "fujimoto")
    idx.set("fp1", ["Fire Punch T01", "Fire Punch", "Tatsuki Fujimoto"])
    assert "fp1" in ids(idx, "fujimoto")
    idx.discard("fp1")
    assert ids(idx, "punch") == set() and "fp1" not in idx


def test_replace_all_drops_missing_documents():
    idx = _library()
    idx.replace_all({"x": ["Solo Leveling 1", "Solo Leveling"]})
    assert len(idx) == 1
    assert ids(idx, "fujimoto") == set()
    assert ids(idx, "solo") == {"x"}


def test_cached_tokens_follow_index_changes():
    idx = _library()
    assert ids(idx, "lev") == set()
    idx.set("x", ["Solo Leveling 1"])
    assert ids(idx, "lev") == {"x"}       # le cache du mot "lev" a ete invalide
    assert ids(idx, "leve") == {"x"}      # affine a partir du mot precedent


@pytest.mark.parametrize("token, word, k, ok", [
    ("fujimotto", "fujimoto", 2, True),     # lettre en trop
    ("berzerk", "berserk", 1, True),        # substitution
    ("chainsow", "chainsaw", 2, True),
    ("fujimto", "fujimoto", 1, True),       # lettre manquante
    ("fuijmoto", "fujimoto", 2, True),      # inversion de deux lettres voisines
    ("fujimat", "fujimoto", 1, True),       # debut de mot avec une faute
    ("fujm", "fujimoto", 1, True),
    ("berserk", "chainsaw", 2, False),
    ("abcd", "ab", 1, False),               # mot trop court
])
def test_near_prefix(token, word, k, ok):
    assert near_prefix(token, word, k) is ok


def test_known_titles_only_trusts_reliable_matches():
    good = {"source": "anilist", "match_score": 0.9, "title": "Attack on Titan",
            "titles": ["Shingeki no Kyojin", "Attack on Titan", "進撃の巨人"]}
    assert known_titles(good) == ["Attack on Titan", "Shingeki no Kyojin", "進撃の巨人"]
    assert known_titles({**good, "match_score": 0.3}) == []
    assert known_titles({"source": "anilist", "title": "Old cache"}) == []   # sans score
    assert known_titles({"source": "mangadex", "title": "Run to Heaven"}) == ["Run to Heaven"]
    assert known_titles({"not_found": True}) == []
    assert known_titles(None) == []
