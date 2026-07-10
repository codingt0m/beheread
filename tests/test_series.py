"""Tests de la detection heuristique serie/tome (series.py).

Ce module est un candidat naturel a la regression : ce sont des regex sur des
noms de fichiers reels, avec des cas limites deja documentes en commentaires
dans le code (suffixes de doublon "(1)", tirets pendants, separateurs varies).
"""

import pytest

from series import find_next_volume, normalize_name, parse_series


@pytest.mark.parametrize("stem, expected_name, expected_vol", [
    ("One Piece - Tome 12", "One Piece", 12),
    ("One Piece Tome 108", "One Piece", 108),
    ("Naruto vol.45", "Naruto", 45),
    ("Naruto volume-11", "Naruto", 11),
    ("Berserk #38", "Berserk", 38),
    ("Berserk T3", "Berserk", 3),
    ("Bleach 07", "Bleach", 7),          # numero final sans marqueur
    ("Vinland Saga 12", "Vinland Saga", 12),
    ("Gloutons & Dragons", "Gloutons & Dragons", None),  # aucun numero
    ("Akira", "Akira", None),
    ("One Piece - Tome 12 (1)", "One Piece", 12),   # suffixe de doublon OS
    ("One Piece Tome 5 (2)", "One Piece", 5),
])
def test_parse_series(stem, expected_name, expected_vol):
    name, vol = parse_series(stem)
    assert vol == expected_vol
    if expected_name is not None:
        assert name == expected_name


def test_parse_series_strips_leading_zeros():
    assert parse_series("Naruto Tome 007")[1] == 7


@pytest.mark.parametrize("stem, expected_name, expected_vol", [
    # tags de release (team, edition, qualite) : varient d'une release a
    # l'autre et doivent disparaitre du nom de serie extrait
    ("Berserk T37 (Miura) (2019-2023) [Manga FR] (PapriKa+)", "Berserk", 37),
    ("Choujin X T06 (Glenat) [NEO RIP-Club]", "Choujin X", 6),
    ("20th Century Boys - Tome 1 [Manga FR] (CrossRead+)", "20th Century Boys", 1),
    # underscore utilise comme espace : le marqueur T41 doit etre reconnu
    ("Berserk_T41", "Berserk", 41),
    ("Berserk Volume 42", "Berserk", 42),
    # numero au milieu, masque par les tags : redevables au nettoyage
    ("Erased 01 (Kei SANBE) [Digital-1920]", "Erased", 1),
    ("Erased 07 (Kei SANBE) [Digital-1920]", "Erased", 7),
    # titre legitimement entre crochets : pas vide apres nettoyage
    ("[Oshi no Ko] T03", "[Oshi no Ko]", 3),
    # un numero final a 4 chiffres est une annee/resolution, pas un tome
    ("Blame Master Edition 2020", None, None),
    # numero repete via deux marqueurs : le second ne doit pas rester dans le nom
    ("Choujin X T07 - Tome 7 [1920px] [NEO RIP-Club]", "Choujin X", 7),
    # numero faisant partie du titre : jamais purge (seuls les marqueurs
    # explicites redondants du meme numero le sont)
    ("Area 51 - Tome 3", "Area 51", 3),
    # Termes d'edition courants (avec/sans accents) : "Integrale", "Deluxe",
    # "Premium", etc. doivent etre retires du nom extrait
    ("Monster - Intégrale Deluxe T06 (Urasawa) (2011) [Digital-2000] [Manga FR] (TONER-PapriKa+)", "Monster", 6),
    ("Blade Runner Deluxe Edition T01", "Blade Runner", 1),
    # Marqueurs de chapitre ("Chapitre", "chap", "ch") comme alternatives a "Tome"
    ("Berserk Chapitre 383", "Berserk", 383),
    ("Berserk_ch0364[FR][FM][TEAM]", "Berserk", 364),
    ("One Piece chap 1001", "One Piece", 1001),
    # "Édition originale" et autres mentions d'edition francaises : la mention
    # entiere doit disparaitre du nom (sinon la recherche de metadonnees echoue
    # sur "Parasite - originale tome 1" la ou "Parasite tome 1" aboutit).
    ("Parasite - Édition originale T01 (Iwaaki) (2020) [Digital-1699] [Manga FR] (PapriKa+)",
     "Parasite", 1),
    ("One Piece Édition originale T105", "One Piece", 105),
    ("Naruto Édition Collector T12", "Naruto", 12),
    ("Fruits Basket Edition Couleur T03", "Fruits Basket", 3),
    # editions/formats anglais et japonais autonomes
    ("Slam Dunk Perfect Edition T01", "Slam Dunk", 1),
    ("Blade Runner Deluxe Edition T01", "Blade Runner", 1),
    ("Berserk Kanzenban T01", "Berserk", 1),
    # mots ambigus (Perfect, Master) NON colles a "Edition" : vrais titres,
    # jamais retires
    ("Perfect World T01", "Perfect World", 1),
    ("Master Keaton T05", "Master Keaton", 5),
    # sous-titre legitime separe par un tiret : conserve (pas confondu avec un
    # tiret pendant apres retrait d'edition)
    ("Cardcaptor Sakura - Clear Card T01", "Cardcaptor Sakura - Clear Card", 1),
    # mentions de langue (frequentes sur les EPUB multi-langues) : retirees
    # pour que les tomes se regroupent avec les autres editions de la serie
    ("Chainsaw_Man_T01_French", "Chainsaw Man", 1),
    ("One Piece Tome 5 VF", "One Piece", 5),
    ("Naruto T02 VOSTFR", "Naruto", 2),
])
def test_parse_series_release_junk(stem, expected_name, expected_vol):
    name, vol = parse_series(stem)
    assert vol == expected_vol
    if expected_name is not None:
        assert name == expected_name


def test_release_variants_share_series_key():
    """Le coeur du regroupement : toutes les variantes de nommage d'une meme
    serie (releases differentes) doivent partager la meme cle."""
    from series import series_key
    variants = [
        "Berserk T37 (Miura) (2019-2023) [Manga FR] (PapriKa+)",
        "Berserk_T41",
        "Berserk Volume 42",
        "Berserk #38",
        "berserk-t39",
    ]
    keys = {series_key(v) for v in variants}
    assert keys == {"berserk"}


def test_language_tag_does_not_split_series():
    """Cas reel : un tome French epub ne doit pas creer une serie distincte
    de la version deja presente dans la bibliotheque."""
    from series import series_key
    assert series_key("Chainsaw_Man_T01_French") == series_key("Chainsaw Man 12")


@pytest.mark.parametrize("a, b", [
    ("Gloutons & Dragons", "gloutons-dragons"),
    ("One_Piece", "one piece"),
    ("  Naruto  ", "naruto"),
    ("L'Attaque des Titans", "l attaque des titans"),
])
def test_normalize_name_equivalence(a, b):
    assert normalize_name(a) == normalize_name(b)


def test_find_next_volume(tmp_path):
    for n in (1, 2, 3):
        (tmp_path / f"One Piece - Tome {n}.cbz").write_bytes(b"PK\x03\x04dummy")
    current = str(tmp_path / "One Piece - Tome 1.cbz")
    nxt = find_next_volume(current)
    assert nxt is not None
    assert nxt.endswith("Tome 2.cbz")


def test_find_next_volume_none_at_last(tmp_path):
    for n in (1, 2):
        (tmp_path / f"Naruto Tome {n}.cbz").write_bytes(b"PK\x03\x04dummy")
    last = str(tmp_path / "Naruto Tome 2.cbz")
    assert find_next_volume(last) is None


def test_find_next_volume_ignores_other_series(tmp_path):
    (tmp_path / "Naruto Tome 1.cbz").write_bytes(b"PK\x03\x04dummy")
    (tmp_path / "Bleach Tome 2.cbz").write_bytes(b"PK\x03\x04dummy")
    assert find_next_volume(str(tmp_path / "Naruto Tome 1.cbz")) is None
