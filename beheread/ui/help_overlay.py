"""Panneau d'aide des raccourcis clavier (touche F1, ou ? dans le lecteur),
affiche par-dessus le lecteur ou la bibliotheque. Les memes listes sont
reprises dans l'onglet « Raccourcis » des preferences."""

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QFrame, QGridLayout, QHBoxLayout, QLabel, QVBoxLayout

from beheread import platforms
from beheread.i18n import N_, tr
from beheread.ui import keys, style, theme

# (titre de section, [(touches, description)]) ; plusieurs touches separees
# par " / " sont affichees comme des pastilles distinctes. Les touches sont
# ecrites a la maniere de Windows et traduites a l'affichage (voir keys.py).

# raccourci global de la touche boss, la ou le systeme le permet
_GLOBAL_BOSS = ([("Ctrl + Alt + C", N_("Masquer / réafficher depuis n'importe où"))]
                if platforms.GLOBAL_HOTKEY else [])

READER_SHORTCUTS = [
    (N_("Navigation"), [
        ("↓ / Espace / Molette", N_("Page suivante (fait d'abord défiler une page plus haute que l'écran)")),
        ("↑ / Retour arrière", N_("Page précédente")),
        ("→ / ←", N_("Page suivante / précédente (inversé en mode manga)")),
        ("Clic gauche / droit", N_("Zones gauche et droite de l'écran : tourner la page")),
        ("Pg suiv / Pg préc", N_("Avancer / reculer d'une seule page")),
        ("Début / Fin", N_("Première / dernière page")),
        ("Entrée", N_("Tome suivant (en fin de tome)")),
        ("Barre du bas", N_("Clic ou glisser : aller à une page")),
    ]),
    (N_("Affichage"), [
        ("D", N_("Simple page / double page")),
        ("M", N_("Sens de lecture manga (droite à gauche)")),
        ("S", N_("Décaler l'appairage des pages doubles")),
        ("F", N_("Ajustement : hauteur / largeur")),
        ("R", N_("Recadrage automatique des marges")),
        ("A", N_("Ambilight")),
        ("+ / − / 0", N_("Zoom avant / arrière / réinitialiser")),
        ("Ctrl + Molette", N_("Zoom")),
        ("Glisser", N_("Déplacer une image plus grande que l'écran")),
        ("F11", N_("Plein écran")),
    ]),
    (N_("Général"), [
        ("Échap", N_("Retour à la bibliothèque")),
        ("C", N_("Masquer la fenêtre")),
        *_GLOBAL_BOSS,
        ("F1 / ?", N_("Afficher / masquer cette aide")),
    ]),
]

LIBRARY_SHORTCUTS = [
    (N_("Bibliothèque"), [
        ("Ctrl + F", N_("Rechercher")),
        ("Entrée / Double-clic", N_("Ouvrir le manga ou le dossier de série")),
        ("Échap / Retour arrière", N_("Sortir du dossier de série")),
        ("Suppr", N_("Supprimer la sélection (avec confirmation)")),
        ("Ctrl + Clic / Maj + Clic", N_("Sélection multiple")),
        ("Clic droit", N_("Actions sur la sélection")),
        ("I", N_("Afficher / masquer le panneau d'informations")),
        ("F5", N_("Rafraîchir")),
        ("Glisser-déposer", N_("Un dossier pour l'ajouter, un fichier pour l'ouvrir")),
    ]),
    (N_("Général"), [
        ("Tab", N_("Passer d'un bouton à l'autre dans l'en-tête")),
        ("Ctrl + ,", N_("Préférences")),
        ("F11", N_("Plein écran")),
        *_GLOBAL_BOSS,
        ("F1", N_("Afficher / masquer cette aide")),
    ]),
]


def sections_layout(sections, parent, vertical=False):
    """Sections de raccourcis cote a cote (carte flottante) ou empilees
    (vertical=True : onglet des preferences, plus etroit)."""
    box = QVBoxLayout() if vertical else QHBoxLayout()
    box.setSpacing(18 if vertical else 36)
    for name, rows in sections:
        col = QVBoxLayout()
        col.setSpacing(8)
        head = QLabel(tr(name).upper(), parent)
        head.setObjectName("helpSection")
        col.addWidget(head)
        grid = QGridLayout()
        grid.setHorizontalSpacing(14)
        grid.setVerticalSpacing(6)
        if vertical:
            # descriptions alignees d'une section a l'autre, sur toute la largeur restante
            grid.setColumnMinimumWidth(0, 200)
            grid.setColumnStretch(1, 1)
        for r, (shortcut, desc) in enumerate(rows):
            keys_row = QHBoxLayout()
            keys_row.setSpacing(4)
            for k in shortcut.split(" / "):
                kl = QLabel(keys.label(k), parent)
                kl.setObjectName("kbd")
                keys_row.addWidget(kl)
            keys_row.addStretch(1)
            grid.addLayout(keys_row, r, 0)
            dl = QLabel(tr(desc), parent)
            dl.setObjectName("helpDesc")
            dl.setWordWrap(True)
            dl.setMinimumWidth(220)
            grid.addWidget(dl, r, 1)
        col.addLayout(grid)
        col.addStretch(1)
        box.addLayout(col)
    return box


def sections_css(c) -> str:
    """Style des sections construites par sections_layout."""
    return f"""
        #helpSection {{
            color: {theme.ACCENT}; font-size: 12px; font-weight: 700;
            letter-spacing: 1px;
        }}
        #helpDesc {{ color: {c['text']}; font-size: 13px; }}
        #kbd {{
            color: {c['text']}; background: {c['button']};
            border: 1px solid {c['border']}; border-bottom-width: 2px;
            border-radius: {style.RADIUS_SM}px; padding: 1px 7px;
            font-size: 12px; font-weight: 600;
        }}
    """


class ShortcutOverlay(QFrame):
    """Carte flottante listant les raccourcis par section. Un clic la ferme.

    take_focus=False (lecteur) : le parent garde le focus et gere lui-meme la
    fermeture au clavier. take_focus=True (bibliotheque) : la carte prend le
    focus a l'affichage, n'importe quelle touche la ferme et le focus revient
    au widget precedent."""

    def __init__(self, sections, parent, take_focus=False):
        super().__init__(parent)
        self._take_focus = take_focus
        self._prev_focus = None
        if take_focus:
            self.setFocusPolicy(Qt.StrongFocus)
        self.setObjectName("helpCard")
        self.setAccessibleName(tr("Raccourcis clavier"))
        root = QVBoxLayout(self)
        root.setContentsMargins(28, 22, 28, 22)
        root.setSpacing(14)

        title = QLabel(tr("Raccourcis clavier"), self)
        title.setObjectName("helpTitle")
        root.addWidget(title)

        root.addLayout(sections_layout(sections, self))

        foot = QLabel(tr("Échap, F1 ou un clic pour fermer"), self)
        foot.setObjectName("helpFoot")
        foot.setAlignment(Qt.AlignRight)
        root.addWidget(foot)
        self.hide()

    def apply_colors(self, c):
        self.setStyleSheet(f"""
            #helpCard {{
                background: {c['panel']};
                border: 1px solid {c['border']};
                border-radius: 16px;
            }}
            #helpTitle {{ color: {c['text']}; font-size: 18px; font-weight: 700; }}
            #helpFoot {{ color: {c['text_dim']}; font-size: 12px; }}
        """ + sections_css(c))

    def toggle(self):
        if self.isVisible():
            self.hide()
        else:
            self.show_centered()

    def show_centered(self):
        self.adjustSize()
        parent = self.parentWidget()
        w = min(self.width(), parent.width() - 32)
        h = min(self.height(), parent.height() - 32)
        self.resize(w, h)
        self.move((parent.width() - w) // 2, (parent.height() - h) // 2)
        self.show()
        self.raise_()
        if self._take_focus:
            self._prev_focus = self.window().focusWidget()
            self.setFocus()

    def hideEvent(self, event):
        prev, self._prev_focus = self._prev_focus, None
        if self._take_focus and prev is not None and self.hasFocus():
            prev.setFocus()
        super().hideEvent(event)

    def mousePressEvent(self, event):
        self.hide()
        event.accept()

    def keyPressEvent(self, event):
        if self._take_focus:
            self.hide()
            event.accept()
            return
        super().keyPressEvent(event)
