"""Langue de l'interface (francais, langue des sources, ou anglais).

    tr("Il vous manque {n} tomes", n=3)       -> texte traduit puis complete
    trn(n, "{n} tome", "{n} tomes")           -> forme du singulier ou du pluriel
    N_("Non lu")                              -> marque un texte d'une constante,
                                                 traduit plus tard par tr()

Le texte francais sert de cle : sans traduction connue, il s'affiche tel
quel. Les traductions anglaises sont dans beheread/locale/en.py (un test
verifie qu'aucun texte marque n'y manque). La langue est choisie une fois,
au lancement (preference « language » : « system », « fr » ou « en »).

Logique pure, sans Qt : utilisable aussi par core/ et infra/.
"""

LANGUAGES = {"fr": "Français", "en": "English"}
DEFAULT = "fr"

_language = DEFAULT
_catalog: dict = {}


def resolve(preference, system_language) -> str:
    """Langue a utiliser : celle choisie dans les preferences, ou pour
    « system », le francais si le systeme est en francais, l'anglais sinon."""
    if preference in LANGUAGES:
        return preference
    return "fr" if (system_language or "").lower().startswith("fr") else "en"


def set_language(code):
    """Langue de l'interface pour la suite de la session."""
    global _language, _catalog
    _language = code if code in LANGUAGES else DEFAULT
    if _language == "en":
        from beheread.locale import en
        _catalog = en.CATALOG
    else:
        _catalog = {}


def language() -> str:
    return _language


def tr(text, **values) -> str:
    """Texte dans la langue de l'interface, complete par `values` ({nom})."""
    translated = _catalog.get(text, text) if _catalog else text
    return translated.format(**values) if values else translated


def trn(n, singular, plural, **values) -> str:
    """Forme du singulier ou du pluriel selon `n` (en francais, 0 et 1 sont
    au singulier ; en anglais, seul 1 l'est), avec {n} disponible (mis en
    forme par fmt_int pour un entier)."""
    one = n in (0, 1) if _language == "fr" else n == 1
    shown = fmt_int(n) if isinstance(n, int) else n
    return tr(singular if one else plural, n=shown, **values)


def fmt_int(n) -> str:
    """Entier avec separateur de milliers : 12 345 (espace fine insecable)
    en francais, 12,345 en anglais."""
    text = f"{int(n):,}"
    return text.replace(",", " ") if _language == "fr" else text


def fmt_decimal(x, digits=1) -> str:
    """Nombre a virgule : 2,5 en francais, 2.5 en anglais."""
    text = f"{x:.{digits}f}"
    return text.replace(".", ",") if _language == "fr" else text


def N_(text):
    """Marque un texte a traduire sans le traduire (constantes evaluees au
    chargement des modules) : c'est tr() qui le traduit a l'affichage."""
    return text
