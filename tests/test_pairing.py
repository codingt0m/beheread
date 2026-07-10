"""Tests de la logique d'appairage double page (pairing.py) : parite,
planches doubles, recul. Purement algorithmique, sans Qt."""

import pairing


def no_spread(_i):
    return False


def spreads(*indices):
    s = set(indices)
    return lambda i: i in s


# ----- pairs_with_next -----

def test_no_pairing_in_single_page_mode():
    assert pairing.pairs_with_next(0, 10, 0, double_page=False, is_spread=no_spread) is False


def test_pairs_on_even_page_with_zero_offset():
    # offset 0 : (0,1), (2,3), (4,5)... s'appairent
    assert pairing.pairs_with_next(0, 10, 0, True, no_spread) is True
    assert pairing.pairs_with_next(2, 10, 0, True, no_spread) is True


def test_odd_page_does_not_start_a_pair_with_zero_offset():
    assert pairing.pairs_with_next(1, 10, 0, True, no_spread) is False


def test_offset_shifts_parity():
    # offset 1 : la page 0 (couverture) est seule, l'appairage commence a (1,2)
    assert pairing.pairs_with_next(0, 10, 1, True, no_spread) is False
    assert pairing.pairs_with_next(1, 10, 1, True, no_spread) is True


def test_last_page_has_no_successor():
    assert pairing.pairs_with_next(9, 10, 0, True, no_spread) is False


def test_spread_never_pairs():
    # une planche double (page 2) ne s'appaire ni comme gauche ni comme droite
    assert pairing.pairs_with_next(2, 10, 0, True, spreads(2)) is False
    assert pairing.pairs_with_next(2, 10, 0, True, spreads(3)) is False


# ----- current_indices -----

def test_current_indices_returns_pair():
    assert pairing.current_indices(0, 10, 0, True, no_spread) == [0, 1]


def test_current_indices_single_when_not_paired():
    assert pairing.current_indices(1, 10, 0, True, no_spread) == [1]
    assert pairing.current_indices(0, 10, 0, False, no_spread) == [0]


def test_current_indices_single_on_spread():
    assert pairing.current_indices(4, 10, 0, True, spreads(4)) == [4]


# ----- step_back -----

def test_step_back_single_page_mode():
    assert pairing.step_back(5, 10, 0, False, no_spread) == 1


def test_step_back_from_first_pages():
    assert pairing.step_back(0, 10, 0, True, no_spread) == 1
    assert pairing.step_back(1, 10, 0, True, no_spread) == 1


def test_step_back_two_when_previous_is_a_pair():
    # a la page 4 (debut de la paire 4-5), reculer doit sauter la paire 2-3
    assert pairing.step_back(4, 10, 0, True, no_spread) == 2


def test_step_back_one_when_previous_page_is_spread():
    # page 3 precedee d'une planche double (page 2) : recul d'une seule page
    assert pairing.step_back(3, 10, 0, True, spreads(2)) == 1
