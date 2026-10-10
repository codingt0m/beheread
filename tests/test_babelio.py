"""Tests du lien Babelio de la fiche de fin de tome (core/babelio.py)."""

from beheread.core import babelio


def test_a_numbered_volume_searches_series_and_number():
    assert babelio.search_query("Berserk T03") == "Berserk tome 3"
    assert babelio.search_query("Chainsaw Man - Tome 20") == "Chainsaw Man tome 20"


def test_a_volume_without_series_name_uses_its_folder():
    assert babelio.search_query("Tome 01", "Vagabond") == "Vagabond tome 1"


def test_a_chapter_or_cycle_searches_the_series_only():
    assert babelio.search_query("Berserk Chapitre 385") == "Berserk"
    assert babelio.search_query("Seuls - Intégrale du Cycle 1") == "Seuls"


def test_a_one_shot_searches_its_clean_title():
    assert babelio.search_query("Errance [Digital-1920] (Team)") == "Errance"


def test_a_forced_series_name_replaces_the_detected_one():
    assert babelio.search_query("Berserk T03", series_name="Berserk Deluxe") \
        == "Berserk Deluxe tome 3"


def test_page_posts_the_query_to_babelio_search():
    page = babelio.search_page("Lou ! tome 2 \"&\" Éclair")
    assert 'method="post" action="https://www.babelio.com/recherche.php"' in page
    # sans accents ni ponctuation, et rien qui puisse sortir de l'attribut
    assert 'name="Recherche" value="lou tome 2 eclair"' in page
    assert "&" not in page.split('value="')[1].split('"')[0]
