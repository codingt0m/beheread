"""Tests de la logique molette / pave tactile du lecteur (wheel_nav.py)."""

from beheread.core.wheel_nav import NOTCH, WheelNavigator


class FakePage:
    """Page de hauteur `overflow` pixels au-dela de l'ecran ; position 0 =
    haut de la page, `overflow` = bas."""

    def __init__(self, overflow=0.0):
        self.overflow = overflow
        self.pos = 0.0

    def scroll(self, px):
        new = min(self.overflow, max(0.0, self.pos - px))
        moved = abs(new - self.pos) > 0.5
        self.pos = new
        return moved


def test_mouse_notch_turns_page_when_page_fits():
    nav, page = WheelNavigator(), FakePage()
    assert nav.feed(-NOTCH, False, 0.0, page.scroll) == "next"
    assert nav.feed(NOTCH, False, 1.0, page.scroll) == "prev"


def test_high_resolution_wheel_accumulates_to_one_notch():
    nav, page = WheelNavigator(), FakePage()
    results = [nav.feed(-30, False, i * 0.2, page.scroll) for i in range(4)]
    assert results == [None, None, None, "next"]


def test_overflowing_page_scrolls_before_turning():
    nav, page = WheelNavigator(), FakePage(overflow=200)
    t = 0.0
    assert nav.feed(-NOTCH, False, t, page.scroll) is None   # 110 px
    t += 0.3
    assert nav.feed(-NOTCH, False, t, page.scroll) is None   # bas atteint
    assert page.pos == 200
    t += 0.3
    assert nav.feed(-NOTCH, False, t, page.scroll) == "next"  # cran de plus au bord


def test_fast_spin_stops_at_edge_without_turning():
    """Une rotation rapide et continue bute contre le bas sans tourner : il
    faut une pause puis un nouveau cran."""
    nav, page = WheelNavigator(), FakePage(overflow=200)
    results = [nav.feed(-NOTCH, False, i * 0.03, page.scroll) for i in range(10)]
    assert "next" not in results
    assert nav.feed(-NOTCH, False, 0.03 * 9 + 0.3, page.scroll) == "next"


def test_touchpad_swipe_turns_at_most_one_page():
    nav, page = WheelNavigator(), FakePage()
    results = [nav.feed(-40, True, i * 0.016, page.scroll) for i in range(60)]
    assert results.count("next") == 1
    # nouveau geste apres une pause : une page de plus
    later = [nav.feed(-40, True, 2.0 + i * 0.016, page.scroll) for i in range(10)]
    assert later.count("next") == 1


def test_touchpad_scrolls_overflowing_page_smoothly():
    nav, page = WheelNavigator(), FakePage(overflow=500)
    for i in range(5):
        assert nav.feed(-20, True, i * 0.016, page.scroll) is None
    assert page.pos == 100


def test_direction_change_resets_accumulation():
    nav, page = WheelNavigator(), FakePage()
    assert nav.feed(-60, False, 0.0, page.scroll) is None
    assert nav.feed(60, False, 0.1, page.scroll) is None   # ne complete pas le cran
    assert nav.feed(60, False, 0.2, page.scroll) == "prev"
