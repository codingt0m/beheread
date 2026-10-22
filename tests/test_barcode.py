"""Tests du lecteur de code-barres EAN-13 (logique pure, lignes de pixels
synthetiques)."""

from beheread.core import barcode

ISBN = "9782505063520"


def _row(code=ISBN, module=3, dark=20, light=235, margin=12):
    """Ligne de pixels : marge claire, code, marge claire."""
    pixels = [255] * (margin * module)
    for m in barcode.encode(code):
        pixels += [dark if m else light] * module
    return bytes(pixels + [255] * (margin * module))


def test_check_digit():
    assert barcode.check_digit_ok([int(c) for c in ISBN])
    assert not barcode.check_digit_ok([int(c) for c in "9782505063521"])
    assert not barcode.check_digit_ok([9, 7, 8])


def test_encode_has_95_modules():
    assert len(barcode.encode(ISBN)) == 95


def test_row_is_decoded_in_both_directions():
    assert barcode.decode_row(_row()) == [ISBN]
    assert barcode.decode_row(_row()[::-1]) == [ISBN]   # code a l'envers


def test_thin_and_irregular_bars():
    assert barcode.decode_row(_row(module=1)) == [ISBN]
    # encre qui bave : chaque barre gagne un pixel, chaque espace le perd
    import itertools
    pixels = []
    for dark, run in itertools.groupby(barcode.encode(ISBN)):
        n = len(list(run))
        pixels += [20] * (3 * n + 1) if dark else [235] * (3 * n - 1)
    assert barcode.decode_row(bytes([255] * 40 + pixels + [255] * 40)) == [ISBN]


def test_decode_needs_repeated_reads_of_an_isbn():
    noise = bytes(range(256)) * 4
    assert barcode.decode([_row(), noise, _row(module=2)]) == ISBN
    assert barcode.decode([_row(), noise]) is None            # une seule lecture
    other = "4006381333931"                                     # EAN d'un produit, pas un livre
    assert barcode.decode([_row(other), _row(other)]) is None


def test_noise_is_not_a_barcode():
    import random
    rng = random.Random(1)
    rows = [bytes(rng.randrange(256) for _ in range(1200)) for _ in range(50)]
    assert barcode.decode(rows) is None
