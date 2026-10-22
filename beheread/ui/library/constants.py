"""Constantes partagees par les modules de la bibliotheque (dimensions des
vignettes/cellules et roles de donnees des items). Regroupees ici pour que les
delegates (rendu) et le widget (construction des items) s'y referent sans se
dependre mutuellement."""

from PySide6.QtCore import Qt

THUMB_W, THUMB_H = 190, 268
# facteur de resolution du cache de vignettes : voir beheread.config.THUMB_SCALE
# dimensions de reference (echelle 1.0) ; le curseur de taille de la barre
# d'outils les multiplie par un facteur (cf. MangaDelegate.set_scale). Seule
# la couverture (THUMB_*) grandit/retrecit ; le bloc de legende sous la
# couverture (CELL_* - THUMB_*) garde une hauteur fixe pour rester lisible.
CELL_W, CELL_H = 214, 348
# jeu entre deux cases de la grille : baked dans QListView.setGridSize (avec
# setSpacing(0)) pour que le nombre de colonnes soit exactement
# viewport_width // gridWidth - condition d'un centrage stable (cf.
# SmoothListWidget._center_grid).
GRID_GAP = 12
LIST_ROW_H = 64
LIST_THUMB_W, LIST_THUMB_H = 42, 58

ROLE_PATH = Qt.UserRole
ROLE_FRACTION = Qt.UserRole + 1
ROLE_FINISHED = Qt.UserRole + 2
# Qt.UserRole + 3 : ancien role de couverture (les delegates lisent CoverCache)
ROLE_PROG_TEXT = Qt.UserRole + 4
# Qt.UserRole + 5 : ancien role d'en-tete de serie (vue liste), retire
ROLE_AUTHOR_TEXT = Qt.UserRole + 6
# dossiers de serie (regroupement) : un seul item represente plusieurs tomes,
# avec un empilement des premieres couvertures
ROLE_IS_SERIES = Qt.UserRole + 7
ROLE_SERIES_KEY = Qt.UserRole + 8
ROLE_SERIES_COUNT = Qt.UserRole + 9
# Qt.UserRole + 10, + 11 : anciennes 2e et 3e couvertures de la pile
ROLE_SERIES_PATHS = Qt.UserRole + 12   # chemins des tomes dont on empile la couverture
# case « non possede » d'un dossier de serie ouvert : (premier, dernier, unite)
ROLE_MISSING = Qt.UserRole + 13
# en-tete de section d'un dossier de serie ouvert (« Tomes », « Suite en
# chapitres ») : (titre, sous-titre), sur toute la largeur de la grille
ROLE_SECTION = Qt.UserRole + 14
# chapitre affiche en petite case (dossier de serie ouvert, vue grille)
ROLE_SMALL = Qt.UserRole + 15
# tome virtuel (chapitres regroupes, voir infra/virtual.py) : mention « virtuel »
ROLE_VIRTUAL = Qt.UserRole + 16
# chapitre : tome officiel qui le contient (« Tome 43 »), quand on le sait
ROLE_IN_VOLUME = Qt.UserRole + 17
SECTION_H = 56
# taille des couvertures des chapitres par rapport a celle des tomes
CHAPTER_SCALE = 0.62
# marges laterales d'une petite case de chapitre, et jeu entre deux d'entre
# elles (les cases de tome : CELL_W - THUMB_W et GRID_GAP)
CHAPTER_SIDE = 6
CHAPTER_GAP = 6

# decalage de l'empilement des couvertures d'un dossier de serie (pixels)
STACK_PEEK = 9
