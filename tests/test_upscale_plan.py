"""Tests des decisions de l'upscaling (core/upscale_plan.py) : besoin selon
la taille d'affichage, taille gardee, ordre de preparation, lots, cache."""

from beheread.core import upscale_plan as plan


def test_low_resolution_pages_need_upscaling_large_ones_do_not():
    # Billy Bat : 984 x 1400 sur un ecran de 2880 x 1800 (hauteur)
    gain = plan.display_gain(984, 1400, 2880, 1800, fit_width=False)
    assert round(gain, 2) == 1.29 and plan.needs_upscale(gain)
    # page de 1920 x 2729 : deja reduite a l'affichage
    assert not plan.needs_upscale(plan.display_gain(1920, 2729, 2880, 1800, False))
    # a peine agrandie : difference invisible, pas de calcul
    assert not plan.needs_upscale(plan.display_gain(1000, 1700, 2880, 1800, False))
    # ajustement a la largeur : c'est la largeur qui compte
    assert plan.needs_upscale(plan.display_gain(1920, 2729, 2880, 1800, fit_width=True))
    assert plan.display_gain(0, 1400, 2880, 1800, False) == 0.0


def test_height_fit_is_limited_by_width_for_wide_pages():
    # planche double tres large : limitee par la largeur de l'ecran
    assert plan.display_gain(3000, 1400, 2880, 1800, False) == 2880 / 3000


def test_kept_at_display_size_never_beyond_the_model_output():
    assert plan.stored_size(984, 1400, 1800 / 1400) == (1265, 1800)
    assert plan.stored_size(500, 700, 5.0) == (1000, 1400)     # x2 au plus
    assert plan.stored_size(984, 1400, 0.5) == (984, 1400)     # jamais reduite


def test_preparation_order_shown_pages_then_next_then_previous():
    assert plan.preparation_order([10, 11], 100, ahead=3, behind=2) == [10, 11, 12, 13, 14, 9, 8]
    assert plan.preparation_order([0], 3, ahead=8, behind=2) == [0, 1, 2]
    assert plan.preparation_order([99], 100, ahead=3, behind=1) == [99, 98]
    assert plan.preparation_order([], 100) == []


def test_next_batch_waits_for_a_missing_page_then_prepares_far_ahead():
    ready = set(range(10, 19)) | {8, 9}   # 10 affichee, 11-18 deja pretes, 8-9 aussi
    assert plan.next_batch([10], 200, ready, ahead=8, extend=16, behind=2) == []
    # une page de plus : la 19 manque dans la fenetre, lot jusqu'a 26
    batch = plan.next_batch([11], 200, ready, ahead=8, extend=16, behind=2)
    assert batch == list(range(19, 28))
    # saut : la page affichee passe en tete
    assert plan.next_batch([150], 200, ready, ahead=2, extend=4, behind=1) == [150, 151, 152,
                                                                             153, 154, 149]


def test_cache_evicts_least_recently_used_files_first():
    files = [("a", 400, 3.0), ("b", 400, 1.0), ("c", 400, 2.0)]
    assert plan.files_to_evict(files, limit=1000) == ["b"]
    assert plan.files_to_evict(files, limit=400) == ["b", "c"]
    assert plan.files_to_evict(files, limit=2000) == []
