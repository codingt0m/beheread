"""Constantes partagees par les modules de la bibliotheque (dimensions des
vignettes/cellules et roles de donnees des items). Regroupees ici pour que les
delegates (rendu) et le widget (construction des items) s'y referent sans se
dependre mutuellement."""

from PySide6.QtCore import Qt

THUMB_W, THUMB_H = 190, 268
# facteur de resolution du cache disque des vignettes par rapport a la taille
# logique affichee (THUMB_W x THUMB_H) : permet un rendu net sur les ecrans
# haute densite (Windows a 150%/175%/200%) sans agrandir la grille. Fait
# partie du nom de fichier en cache (voir Store.thumb_path) : le modifier
# invalide et regenere automatiquement les vignettes existantes.
THUMB_SCALE = 3
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
HEADER_H = 30

ROLE_PATH = Qt.UserRole
ROLE_FRACTION = Qt.UserRole + 1
ROLE_FINISHED = Qt.UserRole + 2
ROLE_PIXMAP = Qt.UserRole + 3
ROLE_PROG_TEXT = Qt.UserRole + 4
ROLE_IS_HEADER = Qt.UserRole + 5
ROLE_AUTHOR_TEXT = Qt.UserRole + 6
# dossiers de serie (regroupement) : un seul item represente plusieurs tomes,
# avec un empilement des premieres couvertures
ROLE_IS_SERIES = Qt.UserRole + 7
ROLE_SERIES_KEY = Qt.UserRole + 8
ROLE_SERIES_COUNT = Qt.UserRole + 9
ROLE_PIXMAP2 = Qt.UserRole + 10     # 2e couverture de la pile
ROLE_PIXMAP3 = Qt.UserRole + 11     # 3e couverture de la pile
ROLE_SERIES_PATHS = Qt.UserRole + 12   # chemins des tomes dont on empile la couverture

# decalage de l'empilement des couvertures d'un dossier de serie (pixels)
STACK_PEEK = 9
