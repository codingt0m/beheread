"""Saisie d'un texte ou choix d'un element, aux couleurs de l'application.

Remplace QInputDialog (qui ignorait le theme et ne validait rien) : une
saisie invalide est expliquee sous le champ et bloque le bouton principal, au
lieu d'ouvrir une boite d'erreur apres coup. `validate(texte)` renvoie le
message d'erreur, ou "" / None si la saisie est valable."""

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QVBoxLayout,
)

from beheread.i18n import tr
from beheread.ui import theme
from beheread.ui.library.dialogs import _dialog_css


class PromptDialog(QDialog):
    def __init__(self, title, label, colors, text="", choices=None, editable=True,
                 validate=None, ok_label=None, parent=None):
        super().__init__(parent)
        self.setWindowTitle(title)
        self.setMinimumWidth(460)
        self._validate = validate
        self.setStyleSheet(_dialog_css(colors) + f"""
            QLabel#promptError {{ color: {colors['warning']}; font-size: 12px; }}
            QLineEdit, QComboBox {{ padding: 5px 8px; }}
        """)
        root = QVBoxLayout(self)
        root.setContentsMargins(22, 18, 22, 16)
        root.setSpacing(10)
        heading = QLabel(title)
        heading.setObjectName("promptTitle")
        heading.setStyleSheet("font-size: 15px; font-weight: 700;")
        root.addWidget(heading)
        prompt = QLabel(label)
        prompt.setTextFormat(Qt.PlainText)   # nom de serie ou de fichier : non fiable
        prompt.setWordWrap(True)
        root.addWidget(prompt)

        if choices is not None:
            self.field = QComboBox()
            self.field.setEditable(editable)
            self.field.addItems(list(choices))
            self.field.setCurrentIndex(0 if self.field.count() else -1)
            if editable:
                if text:
                    self.field.setCurrentText(text)
                self._edit = self.field.lineEdit()
            else:
                self._edit = None
            self.field.currentTextChanged.connect(self._check)
        else:
            self.field = QLineEdit(text)
            self._edit = self.field
            self.field.textChanged.connect(self._check)
        self.field.setAccessibleName(label)
        root.addWidget(self.field)
        if self._edit is not None:
            self._edit.returnPressed.connect(self._accept_if_valid)

        self.error = QLabel()
        self.error.setObjectName("promptError")
        self.error.setWordWrap(True)
        self.error.setTextFormat(Qt.PlainText)
        self.error.hide()
        root.addWidget(self.error)

        row = QHBoxLayout()
        row.addStretch(1)
        cancel = QPushButton(tr("Annuler"))
        cancel.clicked.connect(self.reject)
        self.ok = QPushButton(ok_label or tr("OK"))
        self.ok.setObjectName("primary")
        self.ok.setDefault(True)
        self.ok.clicked.connect(self._accept_if_valid)
        row.addWidget(cancel)
        row.addWidget(self.ok)
        root.addLayout(row)
        self.field.setFocus()
        if self._edit is not None:
            self._edit.selectAll()
        self._check()

    def value(self) -> str:
        return (self.field.currentText() if isinstance(self.field, QComboBox)
                else self.field.text())

    def _check(self, *_args):
        """Message d'erreur sous le champ ; le bouton principal est bloque
        tant que la saisie est invalide."""
        message = (self._validate(self.value()) if self._validate else "") or ""
        self.error.setText(message)
        self.error.setVisible(bool(message))
        self.ok.setEnabled(not message)
        return not message

    def _accept_if_valid(self):
        if self._check():
            self.accept()


def _colors(parent):
    store = getattr(parent, "store", None)
    return theme.colors(store.ui_pref("theme", "dark") if store is not None else "dark")


def ask_text(parent, title, label, text="", validate=None, ok_label=None):
    """Texte saisi, ou None si la saisie est annulee."""
    dlg = PromptDialog(title, label, _colors(parent), text=text, validate=validate,
                       ok_label=ok_label, parent=parent)
    return dlg.value() if dlg.exec() == QDialog.Accepted else None


def ask_choice(parent, title, label, choices, editable=True, validate=None, ok_label=None):
    """Element choisi (ou, si `editable`, saisi), ou None si annule."""
    dlg = PromptDialog(title, label, _colors(parent), choices=choices, editable=editable,
                       validate=validate, ok_label=ok_label, parent=parent)
    return dlg.value() if dlg.exec() == QDialog.Accepted else None
