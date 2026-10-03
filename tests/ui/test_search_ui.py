"""Recherche dans la bibliotheque (pytest-qt) : filtrage en place a chaque
niveau, dossiers de serie, retour a la position initiale, metadonnees
arrivant en cours de recherche."""

from beheread.core.series import normalize_name
from tests.ui.conftest import make_cbz, scanned, visible_titles

CSM = "Chainsaw Man"


def _library(window, qtbot, mangas, store, grouped=True):
    paths = {}
    for i in range(1, 4):
        paths[f"csm{i}"] = make_cbz(mangas, f"{CSM} - Tome {i}", seed=i)
    paths["fp"] = make_cbz(mangas, "Fire Punch T01", seed=4)
    paths["poke1"] = make_cbz(mangas, "Pokémon - Tome 1", seed=5)
    paths["poke2"] = make_cbz(mangas, "Pokémon - Tome 2", seed=6)
    store.set_folders([str(mangas)])
    store.set_series_meta(normalize_name(CSM), {"authors": ["Tatsuki Fujimoto"],
                                                "source": "anilist", "match_score": 1.0})
    lib = window.library
    lib._set_group_series(grouped)
    lib.refresh()
    scanned(qtbot, lib, len(paths))
    return lib, paths


def _type(lib, text):
    """Frappe caractere par caractere, sans laisser tourner la boucle
    d'evenements entre deux touches (frappe rapide)."""
    for k in range(1, len(text) + 1):
        lib.search_edit.setText(text[:k])


def test_fast_typing_in_grouped_mode_finds_the_series(window, qtbot, mangas, store):
    """Regression : en mode regroupe, une frappe rapide masquait tous les
    dossiers de serie (« Aucun resultat » pour un auteur bien connu)."""
    lib, _ = _library(window, qtbot, mangas, store)
    _type(lib, "fujimoto")
    assert visible_titles(lib) == [CSM]          # le dossier, pas trois tomes
    assert lib.count_label.text() == "3 tomes"
    assert not lib.empty_panel.isVisible()


def test_search_is_structural_noop_and_loads_no_extra_cover(window, qtbot, mangas, store):
    lib, _ = _library(window, qtbot, mangas, store)
    rows = lib.list.count()
    requested = []
    lib.covers._request = requested.append
    _type(lib, "chainsaw")
    lib.search_edit.clear()
    assert lib.list.count() == rows and not requested


def test_drill_in_shows_matching_volumes_and_back_returns_to_results(window, qtbot, mangas, store):
    lib, _ = _library(window, qtbot, mangas, store)
    _type(lib, "chainsaw 2")
    assert visible_titles(lib) == [CSM] and lib.count_label.text() == "1 tome"
    lib._enter_series(normalize_name(CSM))
    assert visible_titles(lib) == [f"{CSM} - Tome 2"]
    lib._exit_series()
    assert visible_titles(lib) == [CSM]
    lib.search_edit.clear()
    assert set(visible_titles(lib)) == {CSM, "Fire Punch T01", "Pokémon"}


def test_typing_inside_a_series_searches_the_whole_library(window, qtbot, mangas, store):
    lib, _ = _library(window, qtbot, mangas, store)
    lib._enter_series(normalize_name(CSM))
    _type(lib, "fire")
    assert lib._current_series is None
    assert visible_titles(lib) == ["Fire Punch T01"]


def test_flat_view_accents_numbers_and_several_words(window, qtbot, mangas, store):
    lib, _ = _library(window, qtbot, mangas, store, grouped=False)
    _type(lib, "pokemon")
    assert visible_titles(lib) == ["Pokémon - Tome 1", "Pokémon - Tome 2"]
    lib.search_edit.setText("chainsaw 1")
    assert visible_titles(lib) == [f"{CSM} - Tome 1"]
    lib.search_edit.setText("fujimoto tome 3")
    assert visible_titles(lib) == [f"{CSM} - Tome 3"]
    lib.search_edit.setText("dragon ball")
    assert visible_titles(lib) == [] and lib.empty_panel.isVisible()
    assert lib.empty_title.text() == "Aucun résultat"


def test_search_combines_with_status_filter(window, qtbot, mangas, store):
    lib, paths = _library(window, qtbot, mangas, store, grouped=False)
    store.set_progress(paths["csm2"], 3, 4, True)
    lib._set_status_filter("finished")
    _type(lib, "chainsaw")
    assert visible_titles(lib) == [f"{CSM} - Tome 2"]
    lib.search_edit.setText("pokemon")
    assert visible_titles(lib) == []
    assert "Terminés" in lib.empty_label.text()


def test_typos_give_approximate_results(window, qtbot, mangas, store):
    lib, _ = _library(window, qtbot, mangas, store, grouped=False)
    _type(lib, "fujimotto")
    assert len(visible_titles(lib)) == 3
    assert "approchants" in lib.count_label.text()
    lib.search_edit.setText("fujimoto")
    assert "approchants" not in lib.count_label.text()


def test_author_arriving_during_a_search_updates_results(window, qtbot, mangas, store):
    lib, _ = _library(window, qtbot, mangas, store)
    _type(lib, "kentaro")
    assert visible_titles(lib) == []
    store.set_series_meta("pokemon", {"authors": ["Kentaro Pokéauteur"], "source": "mangadex"})
    lib._on_series_meta_updated("pokemon")
    assert visible_titles(lib) == ["Pokémon"]


def test_alternative_titles_are_searchable_when_reliable(window, qtbot, mangas, store):
    lib, _ = _library(window, qtbot, mangas, store)
    store.set_series_meta("pokemon", {"title": "Pokemon Adventures", "titles": ["Pocket Monster SPECIAL"],
                                      "source": "anilist", "match_score": 0.9})
    lib._on_series_meta_updated("pokemon")
    _type(lib, "pocket monster")
    assert visible_titles(lib) == ["Pokémon"]


def test_continue_shelf_hides_while_searching_and_position_comes_back(window, qtbot, mangas, store):
    lib, paths = _library(window, qtbot, mangas, store, grouped=False)
    store.set_progress(paths["fp"], 2, 4, False)
    lib._rebuild_list()
    assert lib.shelf.isVisible()
    current = lib.list.item(3)
    lib.list.setCurrentItem(current)
    _type(lib, "poke")
    assert not lib.shelf.isVisible()
    lib.search_edit.clear()
    assert lib.shelf.isVisible()
    assert lib.list.currentItem() is current
    assert len(visible_titles(lib)) == len(paths)


def test_logo_click_clears_the_search(window, qtbot, mangas, store):
    lib, paths = _library(window, qtbot, mangas, store)
    _type(lib, "fire")
    lib._go_home()
    assert lib.search_edit.text() == "" and lib._search_hits is None
    assert len(visible_titles(lib)) == 3
