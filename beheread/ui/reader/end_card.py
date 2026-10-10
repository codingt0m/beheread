"""Fiche de fin de tome (recapitulatif, tome suivant).

Mixin de ReaderWidget : ces methodes partagent l'etat du lecteur
(self.page, self.cache, self.store...) ; elles sont regroupees ici par
responsabilite."""

from pathlib import Path

from PySide6.QtCore import (
    Qt,
    QUrl,
)
from PySide6.QtGui import QDesktopServices, QPixmap
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QVBoxLayout,
)

from beheread.core import babelio
from beheread.infra.storage import Store
from beheread.ui import theme


class EndCardMixin:
    # ------------------------------------------------------------ fiche de fin de tome
    def _build_end_card(self):
        self.end_card = QFrame(self)
        self.end_card.setObjectName("endCard")
        v = QVBoxLayout(self.end_card)
        v.setContentsMargins(28, 26, 28, 22)
        v.setSpacing(12)

        self.end_cover = QLabel(self.end_card)
        self.end_cover.setAlignment(Qt.AlignCenter)
        v.addWidget(self.end_cover, alignment=Qt.AlignCenter)

        self.end_title = QLabel(self.end_card)
        self.end_title.setObjectName("endTitle")
        self.end_title.setAlignment(Qt.AlignCenter)
        self.end_title.setWordWrap(True)
        v.addWidget(self.end_title)

        self.end_stats = QLabel(self.end_card)
        self.end_stats.setObjectName("endStats")
        self.end_stats.setAlignment(Qt.AlignCenter)
        v.addWidget(self.end_stats)

        row = QHBoxLayout()
        row.setSpacing(10)
        self.end_next_btn = QPushButton("Tome suivant", self.end_card)
        self.end_next_btn.setCursor(Qt.PointingHandCursor)
        self.end_next_btn.setFocusPolicy(Qt.NoFocus)
        self.end_next_btn.clicked.connect(self._on_end_next)
        self.end_lib_btn = QPushButton(
            "Quitter" if self.direct_mode else "Bibliothèque", self.end_card)
        self.end_lib_btn.setCursor(Qt.PointingHandCursor)
        self.end_lib_btn.setFocusPolicy(Qt.NoFocus)
        self.end_lib_btn.clicked.connect(self.close_reader)
        row.addWidget(self.end_next_btn)
        row.addWidget(self.end_lib_btn)
        v.addLayout(row)

        # Babelio n'a pas d'API : on ouvre sa recherche dans le navigateur, et
        # c'est l'utilisateur qui marque le tome « lu » (voir core/babelio.py)
        self.end_babelio_btn = QPushButton("Marquer comme lu sur Babelio", self.end_card)
        self.end_babelio_btn.setObjectName("endBabelio")
        self.end_babelio_btn.setCursor(Qt.PointingHandCursor)
        self.end_babelio_btn.setFocusPolicy(Qt.NoFocus)
        self.end_babelio_btn.setToolTip(
            "Ouvre la recherche de ce tome sur babelio.com dans votre navigateur")
        self.end_babelio_btn.clicked.connect(self._on_end_babelio)
        v.addWidget(self.end_babelio_btn, alignment=Qt.AlignCenter)

        self.end_card.hide()

    def _style_end_card(self, c):
        self.end_card.setStyleSheet(f"""
            #endCard {{
                background: {c['panel']};
                border: 1px solid {c['border']};
                border-radius: 16px;
            }}
            #endTitle {{ color: {c['text']}; font-size: 18px; font-weight: 700; }}
            #endStats {{ color: {c['text_dim']}; font-size: 13px; }}
            QPushButton {{
                color: {c['text']}; background: transparent;
                border: 1px solid {c['border']}; padding: 9px 18px;
                border-radius: 18px; font-size: 13px; font-weight: 600;
            }}
            QPushButton:hover {{ background: {c['button']}; border-color: {c['text_dim']}; }}
            #endCard QPushButton#endNext {{ background: {theme.ACCENT}; color: {theme.ON_ACCENT}; border: none; }}
            #endCard QPushButton#endNext:hover {{ background: {theme.ACCENT}; border: none; }}
        """)
        self.end_next_btn.setObjectName("endNext")

    def _show_end_card(self):
        name = Path(self.path).stem
        self.end_title.setText(name)

        cover = QPixmap(str(self.store.thumb_path(self.path)))
        if cover.isNull() and 0 in self.cache and not self.cache[0].isNull():
            cover = QPixmap.fromImage(self.cache[0])
        if not cover.isNull():
            self.end_cover.setPixmap(cover.scaled(
                150, 210, Qt.KeepAspectRatio, Qt.SmoothTransformation))
            self.end_cover.show()
        else:
            self.end_cover.hide()

        active = self._fmt_duration(self._active_seconds())
        parts = [f"{self.total} pages", "Tome terminé"]
        if self._active_seconds() > 5:
            parts.insert(1, f"lu en {active}")
        self.end_stats.setText("  ·  ".join(parts))

        if self._next_volume_path:
            self.end_next_btn.setText(f"Tome suivant : {Path(self._next_volume_path).stem}")
            self.end_next_btn.show()
        else:
            self.end_next_btn.hide()
        # option des preferences (lecteur), lue a chaque affichage de la fiche
        self.end_babelio_btn.setVisible(bool(self.store.reader_pref("babelio_button", False)))

        self.end_card.adjustSize()
        self._place_end_card()
        self._show_chrome()
        self.end_card.show()
        self.end_card.raise_()

    def _place_end_card(self):
        self.end_card.adjustSize()
        cw, ch = self.end_card.width(), self.end_card.height()
        self.end_card.move((self.width() - cw) // 2, (self.height() - ch) // 2)

    def _hide_end_card(self):
        if self.end_card.isVisible():
            self.end_card.hide()

    def _on_end_next(self):
        if self._next_volume_path:
            self.next_volume_requested.emit(self._next_volume_path)

    def _babelio_page(self) -> Path:
        """Ecrit la page locale qui lance la recherche Babelio de ce tome (nom
        de serie force par l'utilisateur pris en compte) et renvoie son
        chemin."""
        p = Path(self.path)
        override = self.store.series_override(self.path)
        name = None if override in (None, Store.SERIES_DETACHED) else override
        query = babelio.search_query(p.stem, p.parent.name, name)
        page = self.store.dir / "babelio_search.html"
        page.write_text(babelio.search_page(query), encoding="utf-8")
        return page

    def _on_end_babelio(self):
        try:
            page = self._babelio_page()
        except OSError:
            return
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(page)))
