"""Tests de la deduplication de la bibliotheque par empreinte de contenu
(deux fichiers identiques ne doivent apparaitre qu'une fois - voir
LibraryWidget._dedupe_by_content). N'instancie aucun widget Qt : la methode
ne touche qu'a self.store, donc un objet factice suffit."""

import pytest

import storage
from library import LibraryWidget
from storage import Store


@pytest.fixture
def store(tmp_path, monkeypatch):
    monkeypatch.setenv("APPDATA", str(tmp_path))
    monkeypatch.setattr(storage, "data_dir", lambda: tmp_path / "MangaReaderPy")
    (tmp_path / "MangaReaderPy").mkdir(parents=True, exist_ok=True)
    return Store()


class _FakeLibrary:
    """Duck-type minimal : _dedupe_by_content n'utilise que self.store."""
    def __init__(self, store):
        self.store = store


def _make_manga(dir_path, name, content=b"chapitre un, contenu unique"):
    p = dir_path / name
    p.write_bytes(b"PK\x03\x04" + content + b"\x00" * 200)
    return str(p)


def _dedupe(store, paths):
    return LibraryWidget._dedupe_by_content(_FakeLibrary(store), paths)


def test_identical_files_collapse_to_one(store, tmp_path):
    a = _make_manga(tmp_path, "a.cbz", b"meme-contenu")
    b = _make_manga(tmp_path, "b.cbz", b"meme-contenu")
    assert _dedupe(store, [a, b]) == [a]   # "a" < "b" : representant stable


def test_distinct_files_are_both_kept(store, tmp_path):
    a = _make_manga(tmp_path, "a.cbz", b"contenu-A")
    b = _make_manga(tmp_path, "b.cbz", b"contenu-B")
    result = _dedupe(store, [a, b])
    assert set(result) == {a, b}


def test_duplicate_across_two_source_folders(store, tmp_path):
    """Le cas vise : le meme tome present dans deux dossiers sources
    differents (copie, sauvegarde, lien...) ne doit apparaitre qu'une fois."""
    folder1 = tmp_path / "source1"
    folder2 = tmp_path / "source2"
    folder1.mkdir()
    folder2.mkdir()
    a = _make_manga(folder1, "One Piece T01.cbz", b"contenu-identique")
    b = _make_manga(folder2, "One Piece T01 (copie).cbz", b"contenu-identique")
    assert len(_dedupe(store, [a, b])) == 1


def test_representative_choice_is_stable_across_refreshes(store, tmp_path):
    """Le meme fichier doit rester le representant affiche d'un
    rafraichissement a l'autre (pas de "saut" arbitraire dans la liste)."""
    a = _make_manga(tmp_path, "a.cbz", b"meme-contenu")
    b = _make_manga(tmp_path, "b.cbz", b"meme-contenu")
    first = _dedupe(store, [a, b])
    second = _dedupe(store, [b, a])   # ordre de scan different
    assert first == second == [a]


def test_dedupe_preserves_shared_progress(store, tmp_path):
    """Comportement transparent pour l'utilisateur : la progression est deja
    partagee par empreinte de contenu, donc peu importe quel chemin reste
    affiche apres deduplication, sa progression est correcte."""
    a = _make_manga(tmp_path, "a.cbz", b"meme-contenu")
    b = _make_manga(tmp_path, "b.cbz", b"meme-contenu")
    store.set_progress(a, 4, 10, False)
    kept = _dedupe(store, [a, b])[0]
    assert store.get_progress(kept) == (4, 10, False)


# ----- regroupement en dossiers de serie -----

def _entry(title, series, volume):
    return {"path": f"/x/{title}.cbz", "title": title,
            "series": series, "volume": volume, "added": 0}


def _group(store, entries):
    return LibraryWidget._group_entries(_FakeLibrary(store), entries)


def test_group_entries_by_normalized_series(store):
    entries = [
        _entry("Berserk T01", "Berserk", 1),
        _entry("berserk-02", "berserk", 2),      # variante de casse/separateur
        _entry("One Piece T01", "One Piece", 1),
    ]
    groups = _group(store, entries)
    assert set(groups) == {"berserk", "one piece"}
    assert len(groups["berserk"]) == 2      # les deux variantes fusionnent
    assert len(groups["one piece"]) == 1


def test_single_volume_series_is_its_own_group(store):
    entries = [_entry("Akira integrale", "Akira integrale", None)]
    groups = _group(store, entries)
    assert len(groups) == 1
    assert len(next(iter(groups.values()))) == 1


def test_series_paths_gathers_all_volumes(store):
    """Le menu contextuel d'un dossier de serie supprime TOUS ses tomes :
    _series_paths doit rassembler tous les membres de la serie (regroupement
    automatique), en excluant les tomes detaches et les autres series."""
    lib = _FakeLibrary(store)
    lib._entries = [
        _entry("Berserk T01", "Berserk", 1),
        _entry("berserk-02", "berserk", 2),
        _entry("Berserk T03", "Berserk", 3),
        _entry("One Piece T01", "One Piece", 1),
    ]
    lib._entries[2]["detached"] = True   # tome sorti de la serie : exclu
    lib._group_entries = LibraryWidget._group_entries.__get__(lib)

    paths = LibraryWidget._series_paths(lib, "berserk")

    assert set(paths) == {"/x/Berserk T01.cbz", "/x/berserk-02.cbz"}


def _progress(store, group):
    return LibraryWidget._series_progress(_FakeLibrary(store), group)


def test_series_progress_none_read(store, tmp_path):
    group = [_entry("T01", "S", 1), _entry("T02", "S", 2), _entry("T03", "S", 3)]
    read, count, frac, finished = _progress(store, group)
    assert (read, count, frac, finished) == (0, 3, 0.0, False)


def test_series_progress_partial(store, tmp_path):
    a = _make_manga(tmp_path, "a.cbz", b"A")
    b = _make_manga(tmp_path, "b.cbz", b"B")
    c = _make_manga(tmp_path, "c.cbz", b"C")
    store.set_progress(a, 9, 10, True)   # termine
    store.set_progress(b, 3, 10, False)  # en cours, pas termine
    group = [{"path": a}, {"path": b}, {"path": c}]
    read, count, frac, finished = _progress(store, group)
    assert read == 1 and count == 3 and finished is False
    assert abs(frac - 1 / 3) < 1e-9


def test_series_progress_all_read(store, tmp_path):
    a = _make_manga(tmp_path, "a.cbz", b"A")
    b = _make_manga(tmp_path, "b.cbz", b"B")
    store.set_progress(a, 9, 10, True)
    store.set_progress(b, 9, 10, True)
    read, count, frac, finished = _progress(store, [{"path": a}, {"path": b}])
    assert (read, count, frac, finished) == (2, 2, 1.0, True)


# ----- tome en tete de pile d'un dossier de serie -----

def _featured(store, vols):
    return LibraryWidget._series_featured_index(_FakeLibrary(store), vols)


def _make_volumes(store, tmp_path, n):
    return [{"path": _make_manga(tmp_path, f"t{i:02d}.cbz",
                                 f"tome-{i}".encode())} for i in range(1, n + 1)]


def test_featured_defaults_to_first_volume(store, tmp_path):
    vols = _make_volumes(store, tmp_path, 4)
    assert _featured(store, vols) == 0


def test_featured_is_next_after_last_finished(store, tmp_path):
    """Tome 2 (indice 1) termine -> la pile montre le tome 3 (indice 2)."""
    vols = _make_volumes(store, tmp_path, 4)
    store.set_progress(vols[1]["path"], 9, 10, True)
    assert _featured(store, vols) == 2


def test_featured_stays_on_final_volume_when_series_done(store, tmp_path):
    """Dernier tome termine et rien apres : la pile reste sur ce tome."""
    vols = _make_volumes(store, tmp_path, 3)
    store.set_progress(vols[2]["path"], 9, 10, True)
    assert _featured(store, vols) == 2


def test_featured_prefers_volume_in_progress(store, tmp_path):
    """Un tome en cours de lecture passe devant le "prochain a lire"."""
    vols = _make_volumes(store, tmp_path, 4)
    store.set_progress(vols[0]["path"], 9, 10, True)    # T1 termine
    store.set_progress(vols[2]["path"], 4, 10, False)   # T3 en cours
    assert _featured(store, vols) == 2


def test_featured_next_to_read_skips_gap(store, tmp_path):
    """T1 et T2 termines -> prochain a lire = T3, meme sans progression."""
    vols = _make_volumes(store, tmp_path, 5)
    store.set_progress(vols[0]["path"], 9, 10, True)
    store.set_progress(vols[1]["path"], 9, 10, True)
    assert _featured(store, vols) == 2


# ----- doublons "meme tome, releases differentes" (series.py + progression) -----

def _entry_p(path, title, series, volume, kind="volume"):
    return {"path": path, "title": title, "series": series, "volume": volume,
            "kind": kind, "added": 0}


def _dedupe_sv(store, entries):
    return LibraryWidget._dedupe_by_series_volume(_FakeLibrary(store), entries)


def test_chapter_and_volume_same_number_do_not_collapse(store, tmp_path):
    """Un chapitre et un tome relie de meme numero sont des contenus distincts :
    la deduplication ne doit pas en masquer un (regression : ils partageaient la
    meme cle (serie, numero) et l'un disparaissait de la bibliotheque)."""
    a = _make_manga(tmp_path, "One Piece Chapitre 5.cbz", b"chapitre-scan")
    b = _make_manga(tmp_path, "One Piece Tome 5.cbz", b"tome-relie")
    entries = [_entry_p(a, "One Piece Chapitre 5", "One Piece", 5, kind="chapter"),
              _entry_p(b, "One Piece Tome 5", "One Piece", 5, kind="volume")]
    result = _dedupe_sv(store, entries)
    assert len(result) == 2


def test_same_series_volume_different_files_collapse(store, tmp_path):
    """Deux fichiers DIFFERENTS (releases distinctes) representant le meme
    tome de la meme serie ne doivent apparaitre qu'une fois - meme si leur
    contenu differe (donc invisibles a _dedupe_by_content)."""
    a = _make_manga(tmp_path, "Berserk Volume 42.cbz", b"scan-edition-A")
    b = _make_manga(tmp_path, "Berserk_T42.cbz", b"scan-edition-B-differente")
    entries = [_entry_p(a, "Berserk Volume 42", "Berserk", 42),
              _entry_p(b, "Berserk_T42", "Berserk", 42)]
    result = _dedupe_sv(store, entries)
    assert len(result) == 1


def test_dedupe_prefers_the_read_copy(store, tmp_path):
    """Si l'une des deux releases a ete lue (termine ou entamee), c'est elle
    qui doit rester affichee - pas une copie au hasard sans progression."""
    a = _make_manga(tmp_path, "Berserk Volume 42.cbz", b"scan-A")
    b = _make_manga(tmp_path, "Berserk_T42.cbz", b"scan-B")
    store.set_progress(a, 9, 10, True)   # "a" est celle que l'utilisateur a lue
    entries = [_entry_p(b, "Berserk_T42", "Berserk", 42),   # ordre delibere : b avant a
              _entry_p(a, "Berserk Volume 42", "Berserk", 42)]
    result = _dedupe_sv(store, entries)
    assert len(result) == 1
    assert result[0]["path"] == a


def test_dedupe_in_progress_beats_untouched(store, tmp_path):
    a = _make_manga(tmp_path, "a.cbz", b"scan-A")
    b = _make_manga(tmp_path, "b.cbz", b"scan-B")
    store.set_progress(b, 3, 10, False)   # entame, pas termine
    entries = [_entry_p(a, "a", "Naruto", 5), _entry_p(b, "b", "Naruto", 5)]
    result = _dedupe_sv(store, entries)
    assert len(result) == 1 and result[0]["path"] == b


def test_dedupe_does_not_merge_volumeless_entries(store, tmp_path):
    """Les titres sans numero de tome detectable (one-shots) ne sont jamais
    fusionnes entre eux : rien ne garantit qu'ils soient le meme contenu."""
    a = _make_manga(tmp_path, "Akira.cbz", b"akira-scan")
    b = _make_manga(tmp_path, "Solo Leveling.cbz", b"solo-leveling-scan")
    entries = [_entry_p(a, "Akira", "Akira", None),
              _entry_p(b, "Solo Leveling", "Solo Leveling", None)]
    result = _dedupe_sv(store, entries)
    assert len(result) == 2


def test_dedupe_does_not_merge_different_volumes(store, tmp_path):
    a = _make_manga(tmp_path, "T01.cbz", b"vol1")
    b = _make_manga(tmp_path, "T02.cbz", b"vol2")
    entries = [_entry_p(a, "T01", "Naruto", 1), _entry_p(b, "T02", "Naruto", 2)]
    result = _dedupe_sv(store, entries)
    assert len(result) == 2
