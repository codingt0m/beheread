"""Constantes du lecteur (reglages d'ajustement, cache, animations, HUD)."""

FIT_WINDOW, FIT_WIDTH, FIT_HEIGHT = 0, 1, 2
FIT_NAMES = {FIT_WINDOW: "Ajuster à la fenêtre",
             FIT_WIDTH: "Ajuster à la largeur",
             FIT_HEIGHT: "Ajuster à la hauteur"}

PRELOAD_RADIUS = 3   # pages prechargees de chaque cote
CACHE_LIMIT = 12     # pages decodees conservees en memoire
SCALED_CACHE_LIMIT = 8   # pixmaps mis a l'echelle conserves (evite le rescale/frame)

SLIDER_H = 8
SLIDER_SIDE_MARGIN = 20
SLIDER_BOTTOM_MARGIN = 14
HUD_GAP = 8

TRANSITION_MS = 130     # duree totale du fondu entre deux pages
TRANSITION_STEP_MS = 15  # ~60 fps

CHROME_HIDE_MS = 2600   # inactivite souris avant d'effacer l'interface
PAGE_PAUSE_CAP = 90     # secondes : au-dela, on considere une pause (temps ignore)
TIME_MIN_SAMPLES = 4    # tours de page avant d'estimer le temps restant

AMBIENT_DARKEN = 0.35    # facteur d'assombrissement de la couleur moyenne de la page
AMBIENT_MS = 260         # duree du fondu du fond vers la nouvelle teinte
AMBIENT_STEP_MS = 15     # ~60 fps
