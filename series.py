"""Detection heuristique de serie/tome a partir du nom de fichier, pour
regrouper les tomes d'un meme manga et enchainer automatiquement sur le
tome suivant a la fin de la lecture.

Purement base sur le nom de fichier (aucune metadonnee externe) : un fichier
sans numero de tome detectable est traite comme une serie a un seul tome.
"""

import re
import unicodedata
from pathlib import Path

from archive_handler import scan_folder

def _remove_accents(text: str) -> str:
    """Normalise les accents pour la recherche (é->e, ç->c, etc.)."""
    return ''.join(c for c in unicodedata.normalize('NFD', text)
                   if unicodedata.category(c) != 'Mn')


# Marqueurs explicites de tome, du plus specifique au plus generique.
# Le separateur entre le marqueur et le numero peut etre un espace, un point,
# un tiret ou un underscore (ex. "Volume 12", "vol.45", "volume-11").
_TRAILING_NUMBER = re.compile(r"(?:^|[\s\-_])0*(\d+)\s*$")
_VOLUME_PATTERNS = [
    re.compile(r"(?i)\b(?:tome|vol(?:ume)?|chapitre|chap|ch|t)[\s\-_.]*0*(\d+)\b"),
    re.compile(r"#[\s\-_]*0*(\d+)\b"),
    _TRAILING_NUMBER,   # numero final sans marqueur explicite
]

# Marqueurs de CHAPITRE (unite plus fine qu'un tome relie). Le regroupement et
# l'enchainement traitent volontairement un chapitre comme un "tome" (webtoons
# et scans numerotes par chapitre), mais la DEDUPLICATION doit les distinguer :
# "One Piece Chapitre 5" et "One Piece Tome 5" sont des contenus differents et
# ne doivent pas s'ecraser l'un l'autre (cf. LibraryWidget._dedupe_by_series_volume).
_CHAPTER_MARKER = re.compile(r"(?i)^(?:chapitre|chapter|chap|ch)")


def _volume_kind(pattern, match) -> str:
    """Nature du numero extrait, pour la deduplication : "chapter" (marqueur de
    chapitre), "bare" (numero final sans marqueur, identite fragile) ou
    "volume" (tome/vol/#, unite reliee habituelle)."""
    if pattern is _TRAILING_NUMBER:
        return "bare"
    if pattern is _VOLUME_PATTERNS[0] and _CHAPTER_MARKER.match(match.group(0)):
        return "chapter"
    return "volume"

# Mentions d'edition/format qui ne font pas partie du titre ("Intégrale
# Deluxe", "Édition originale", "Perfect Edition", etc.) - retirees pour eviter
# des cles de serie fragmentees et pour ne pas polluer la recherche de
# metadonnees (une recherche "Parasite - originale tome 1" echoue la ou
# "Parasite tome 1" aboutit). Recherche faite sur le texte sans accents pour
# matcher aussi "intégrale", "spéciale", "édition".
#
# Deux familles, car le risque de faux positif differe :
#
# * _EDITION_PHRASE : mots ambigus (anglais surtout) qui ne doivent etre
#   retires QUE colles au mot "edition" - seuls, ce sont de vrais titres
#   ("Perfect World", "Master Keaton", "Blue Period"). Ex. "Perfect Edition",
#   "Édition originale", "Master Edition".
# * _EDITION_TERMS : mentions autonomes qui ne sont, en pratique, jamais un mot
#   de titre de manga isole ("Intégrale", "Deluxe", "Kanzenban", "Coffret"...).
_ED_PHRASE_SIDE = (r"perfect|master|ultimate|ultime|final|double|new|grand.format|"
                   r"originale?|couleurs?|prestige|anniversaire|definitive|"
                   r"nouvelle|reedition|hardcover")
_EDITION_PHRASE = re.compile(
    r"(?i)(?:\b(?:" + _ED_PHRASE_SIDE + r")\s+)*"
    r"\b(?:edition|edt)\b"
    r"(?:\s+\b(?:" + _ED_PHRASE_SIDE + r")\b)*")
_EDITION_TERMS = re.compile(
    r"(?i)\b(?:integrale|deluxe|luxe|premium|complet|complete|coffret|"
    r"speciale|special|directors?.cut|extended|limitee|collector|originale|"
    r"couleurs?|kanzenban|kanzembam|bunko|wideban|tankou?bon|omnibus|"
    r"anniversaire|prestige|definitive|reedition)\b")

# Mentions de langue accolees au titre (frequentes sur les EPUB/scans
# multi-langues, ex. "Chainsaw Man T01 French") : ne font pas partie du titre
# et doivent disparaitre pour que les tomes d'une meme serie se regroupent
# quelle que soit la langue de l'edition qui les a fournis.
_LANGUAGE_TERMS = re.compile(
    r"(?i)\b(?:french|francais|anglais|english|vf|vo|vostfr)\b")
_EDITION_PATTERNS = (_EDITION_PHRASE, _EDITION_TERMS, _LANGUAGE_TERMS)


def _strip_edition_terms(name: str) -> str:
    """Retire les mentions d'edition/format du nom. La recherche se fait sur la
    version sans accents (pour matcher "Édition", "Spéciale"...) et les memes
    positions sont decoupees dans l'original, qui garde ses accents. NFD ne
    modifie pas le nombre de code points d'une lettre accentuee (base +
    diacritique retire = 1), donc les positions restent alignees."""
    for pattern in _EDITION_PATTERNS:
        folded = _remove_accents(name)
        parts = []
        last_end = 0
        for m in pattern.finditer(folded):
            parts.append(name[last_end:m.start()])
            parts.append(" ")
            last_end = m.end()
        parts.append(name[last_end:])
        name = "".join(parts)
    return name

# Groupes de "bruit de release" : tags de team, d'edition ou de qualite entre
# parentheses/crochets/accolades (ex. "(Miura)", "(PapriKa+)", "[Digital-1920]",
# "[NEO RIP-Club]"). Ils varient d'une release a l'autre pour une meme serie :
# laisses en place, chaque variante produirait sa propre "serie" et le
# regroupement eclaterait (et ils masquent parfois le numero de tome, ex.
# "Erased 01 (Kei SANBE) [Digital-1920]" dont le numero n'est plus final).
_JUNK_GROUP = re.compile(r"[\[({][^\[\](){}]*[\])}]")


def _strip_release_junk(text: str) -> str:
    """Retire tous les groupes entre parentheses/crochets/accolades (boucle
    pour gerer l'imbrication), puis compacte les espaces residuels."""
    while True:
        cleaned = _JUNK_GROUP.sub(" ", text)
        if cleaned == text:
            break
        text = cleaned
    return re.sub(r"\s{2,}", " ", text).strip(" -_.")


def _clean_name(name: str) -> str:
    """Nettoie un nom de serie apres extraction du numero de tome : tiret
    laisse pendant, paire de parentheses/crochets videe, espaces multiples,
    et termes d'edition comme "Integrale", "Deluxe", "Premium"."""
    name = re.sub(r"-\s*(?=\(|$)", " ", name)
    name = re.sub(r"[\[({]\s*[\])}]", " ", name)
    name = _strip_edition_terms(name)
    # apres retrait d'une mention d'edition, le tiret separateur peut se
    # retrouver pendant en bout de chaine ("Parasite - Édition originale" ->
    # "Parasite - ") : on le retire aussi la (le strip final ne couvre que les
    # extremites immediates, pas un tiret suivi d'espaces deja compactes).
    name = re.sub(r"\s*-\s*$", "", name)
    return re.sub(r"\s{2,}", " ", name).strip(" -_.")


def parse_series(stem: str):
    """Retourne (nom_de_serie, numero_de_tome). numero_de_tome vaut None si
    aucun numero n'a pu etre extrait (le fichier est alors sa propre serie)."""
    name, number, _ = parse_series_ex(stem)
    return name, number


def parse_series_ex(stem: str):
    """Comme parse_series, mais renvoie aussi la NATURE du numero
    (voir _volume_kind) : (nom_de_serie, numero, kind). `kind` vaut None quand
    aucun numero n'est trouve. Utilise par la deduplication, qui doit
    distinguer un chapitre d'un tome relie la ou le regroupement les confond."""
    # supprime un suffixe de doublon ajoute par l'OS/le navigateur lors d'un
    # second telechargement (ex. "fichier(1).cbz", "fichier (2).cbz") : ce
    # n'est jamais une partie du vrai titre, mais laisse tel quel il pollue
    # le nom de serie extrait et casse la recherche de metadonnees.
    cleaned = re.sub(r"\s*\(\d+\)\s*$", "", stem).strip()
    if cleaned:
        stem = cleaned

    # les underscores servent souvent d'espaces ("Berserk_T41") : sans cette
    # normalisation, le marqueur de tome colle au nom et n'est pas reconnu
    work = stem.replace("_", " ").strip()

    # on cherche le tome d'abord dans la version debarrassee du bruit de
    # release, puis dans la version brute en repli : un titre entierement
    # entre crochets (ex. "[Oshi no Ko] T03") ne doit pas etre vide apres
    # nettoyage, et un numero peut se cacher dans un groupe legitime.
    bare = _strip_release_junk(work)
    candidates = [c for c in dict.fromkeys((bare, work)) if c]

    for text in candidates:
        for pattern in _VOLUME_PATTERNS:
            m = pattern.search(text)
            if not m:
                continue
            number = int(m.group(1))
            # un numero final a 4 chiffres et plus ressemble a une annee ou a
            # une resolution ("Edition 2020", "1920"), pas a un numero de tome
            if pattern is _TRAILING_NUMBER and number > 999:
                continue
            kind = _volume_kind(pattern, m)
            name = _clean_name(text[:m.start()] + text[m.end():])
            # le numero peut apparaitre deux fois ("Choujin X T07 - Tome 7") :
            # purge les marqueurs explicites redondants portant le meme numero
            # (jamais les numeros nus : "Area 51" doit rester intact)
            while name:
                m2 = _VOLUME_PATTERNS[0].search(name) or _VOLUME_PATTERNS[1].search(name)
                if not m2 or int(m2.group(1)) != number:
                    break
                name = _clean_name(name[:m2.start()] + name[m2.end():])
            if name:
                return name, number, kind
    return (candidates[0] if candidates else stem).strip(), None, None


def normalize_name(name: str) -> str:
    """Normalise un nom de serie pour la comparaison : insensible a la
    casse, aux tirets/underscores utilises comme espaces (frequents dans les
    noms de fichiers type "gloutons-dragons") et a la ponctuation (ex. "&")."""
    s = name.casefold()
    s = re.sub(r"[\-_]+", " ", s)
    s = re.sub(r"[^\w\s]", " ", s, flags=re.UNICODE)
    s = re.sub(r"\s+", " ", s).strip()
    return s


def series_key(stem: str) -> str:
    """Cle de regroupement insensible a la casse/aux separateurs/ponctuation."""
    name, _ = parse_series(stem)
    return normalize_name(name)


def find_next_volume(path: str):
    """Cherche, dans le meme dossier, le tome de numero immediatement
    superieur appartenant a la meme serie. Renvoie son chemin ou None."""
    p = Path(path)
    name, volume = parse_series(p.stem)
    if volume is None:
        return None
    key = normalize_name(name)

    candidates = []
    for sib in scan_folder(str(p.parent)):
        if sib == str(p):
            continue
        sname, svolume = parse_series(Path(sib).stem)
        if svolume is not None and normalize_name(sname) == key:
            candidates.append((svolume, sib))

    better = [c for c in candidates if c[0] > volume]
    if not better:
        return None
    return min(better)[1]
