"""Tests de la mesure d'une seance de lecture (reading_session.py)."""

from beheread.core.reading_session import PACE_WINDOW, SessionMeter


def test_a_page_counts_once_it_stayed_on_screen():
    m = SessionMeter(0.0)
    m.leave(10.0, [0])           # 10 s sur la page 0
    m.leave(10.3, [1])           # feuilletee : ni page ni temps
    m.leave(22.3, [2])
    assert m.pages == {0, 2}
    assert m.active_seconds == 22.0


def test_flipping_through_a_volume_reads_nothing():
    m = SessionMeter(0.0)
    for i in range(150):         # fleche maintenue, barre de defilement
        m.leave((i + 1) * 0.05, [i])
    assert m.pages == set() and m.active_seconds == 0 and m.pace() is None


def test_a_long_session_is_not_truncated():
    m = SessionMeter(0.0)
    for i in range(200):
        m.leave((i + 1) * 10.0, [i])
    assert len(m.pages) == 200
    assert m.active_seconds == 2000.0          # et non les 60 derniers tours de page
    assert len(m.samples) == PACE_WINDOW       # seul le rythme est sur une fenetre


def test_a_pause_is_not_reading_time_but_the_page_was_read():
    m = SessionMeter(0.0)
    m.leave(600.0, [0])          # dix minutes : une pause
    m.leave(620.0, [1])
    assert m.pages == {0, 1} and m.active_seconds == 20.0
    assert list(m.samples) == [20.0]


def test_going_back_is_reading_time_but_adds_no_page():
    m = SessionMeter(0.0)
    m.leave(10.0, [0])
    m.leave(30.0, [1], forward=False)      # retour a la page precedente
    assert m.pages == {0} and m.active_seconds == 30.0
    assert list(m.samples) == [10.0]       # le rythme ne retient que l'avancee


def test_pace_is_per_page_not_per_turn():
    m = SessionMeter(0.0)
    for i in range(4):
        m.leave((i + 1) * 30.0, [2 * i, 2 * i + 1])   # double page : 30 s pour deux pages
    assert m.pace(4) == 15.0
    assert m.pace(5) is None                           # pas assez de vues pour estimer


def test_clock_stops_on_the_end_card_and_resumes():
    m = SessionMeter(0.0)
    m.leave(10.0, [0], resume=False)   # derniere page lue, fiche de fin affichee
    m.leave(200.0, [0], resume=False)  # fermeture bien plus tard : rien a compter
    assert m.active_seconds == 10.0 and m.pages == {0}
    m.leave(300.0, [0], forward=False)  # retour en arriere : l'horloge repart
    m.leave(320.0, [1])
    assert m.active_seconds == 30.0 and m.pages == {0, 1}
