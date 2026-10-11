"""Constantes du lecteur (reglages d'ajustement, cache, animations, HUD)."""

from beheread.i18n import N_

FIT_WIDTH, FIT_HEIGHT = 1, 2
# textes a traduire a l'affichage : tr(FIT_NAMES[...])
FIT_NAMES = {FIT_HEIGHT: N_("Ajuster à la hauteur"),
             FIT_WIDTH: N_("Ajuster à la largeur")}


def normalize_fit(value) -> int:
    """Ajustement enregistre -> FIT_WIDTH ou FIT_HEIGHT. L'ancien mode
    « fenetre » (0), fusionne avec la hauteur, et toute valeur inconnue
    retombent sur la hauteur (reglage par defaut)."""
    return FIT_WIDTH if value == FIT_WIDTH else FIT_HEIGHT


PRELOAD_RADIUS = 3   # pages prechargees de chaque cote
CACHE_LIMIT = 12     # pages decodees conservees en memoire
SCALED_CACHE_LIMIT = 8   # pixmaps mis a l'echelle conserves (evite le rescale/frame)
ZOOM_SETTLE_MS = 150    # fin d'un geste de zoom : rendu net apres ce delai

SLIDER_H = 8
SLIDER_SIDE_MARGIN = 20
SLIDER_BOTTOM_MARGIN = 14
HUD_GAP = 8

TRANSITION_MS = 130     # duree totale du fondu entre deux pages
TRANSITION_STEP_MS = 15  # ~60 fps

CHROME_HIDE_MS = 2600   # inactivite souris avant d'effacer l'interface
TIME_MIN_SAMPLES = 4    # tours de page avant d'estimer le temps restant

AMBIENT_DARKEN = 0.35    # facteur d'assombrissement de la couleur moyenne de la page
AMBIENT_MS = 260         # duree du fondu du fond vers la nouvelle teinte
AMBIENT_STEP_MS = 15     # ~60 fps
