"""Detection heuristique de serie/tome a partir du nom de fichier, pour
regrouper les tomes d'un meme manga et enchainer automatiquement sur le
tome suivant a la fin de la lecture.

Purement base sur le nom de fichier (aucune metadonnee externe) : un fichier
sans numero de tome detectable est traite comme une serie a un seul tome.
"""

import re
import unicodedata
from pathlib import Path


def _remove_accents(text: str) -> str:
    """Normalise les accents pour la recherche (é->e, ç->c, etc.)."""
    return ''.join(c for c in unicodedata.normalize('NFD', text)
                   if unicodedata.category(c) != 'Mn')


# Marqueurs explicites de tome, du plus specifique au plus generique.
# Le separateur entre le marqueur et le numero peut etre un espace, un point,
# un tiret ou un underscore (ex. "Volume 12", "vol.45", "volume-11").
# Le numero accepte une partie decimale ("ch385.5", chapitres bonus) : sans
# elle, ".5" resterait dans le nom de serie et casserait le regroupement.
# Marqueurs couverts : francais (tome, chapitre, n°, cycle), anglais (volume,
# chapter, episode), espagnol (tomo) et abreviations scene (t, v, ch, ep, #).
# "v" et "t" n'exigent pas de separateur mais exigent un chiffre juste apres
# (modulo separateurs), donc "Vinland Saga" ou "Choujin X" ne matchent pas.
# "cycle" : integrales de BD decoupees par cycle ("Seuls - Intégrale du
# Cycle 1") ; le "du" qui le precede part avec lui, sans quoi il resterait
# dans le nom de serie une fois "Intégrale" retire.
_TRAILING_NUMBER = re.compile(r"(?:^|[\s\-_.])0*(\d+(?:\.\d+)?)\s*$")
_VOLUME_PATTERNS = [
    re.compile(r"(?i)\b(?:tome|tomo|vol(?:ume)?|chapitre|chapter|chap|ch|"
               r"ep(?:isode)?|(?:du\s+)?cycle|t|v|n[°º])[\s\-_.]*0*(\d+(?:\.\d+)?)\b"),
    re.compile(r"#[\s\-_]*0*(\d+(?:\.\d+)?)\b"),
    _TRAILING_NUMBER,   # numero final sans marqueur explicite
]
# numero suivi du titre de l'album, nommage BD le plus courant :
# "Astérix - 38 - La Fille de Vercingétorix", "Tintin 05 - Le Lotus bleu"
_TITLED_NUMBER = re.compile(r"(?:^|(?<=\s))0*(\d{1,3})\s+-\s+(?=\S)")
# plage de tomes en fin de nom ("Kingdom 01-05") : le premier numero sert au
# tri, la nature "range" evite de la confondre avec le tome seul
_RANGE = re.compile(r"(?:^|[\s_.])0*(\d{1,3})\s*-\s*0*(\d{1,3})\s*$")

# noms de serie qui n'en sont pas : un fichier nomme seulement « Tome 01 » ou
# « Volume 1 » tire son nom de serie de son dossier (voir parse_series_ex)
_GENERIC_NAMES = {"", "tome", "tomes", "tomo", "volume", "volumes", "vol", "t", "v",
                  "chapitre", "chapter", "chap", "ch", "episode", "ep", "cycle",
                  "integrale", "n", "no", "book", "livre", "manga", "bd", "scan", "scans"}


def is_generic_name(name: str) -> bool:
    """Vrai si `name` n'est pas un vrai nom de serie : vide, nombre seul ou
    simple marqueur de tome (« Tome », « Volume », « Chapitre »...)."""
    key = normalize_name(name or "")
    return key in _GENERIC_NAMES or key.isdigit()


def _to_number(text: str):
    """Numero extrait par les regex ci-dessus : int en regle generale, float
    pour les chapitres decimaux ("385.5")."""
    return float(text) if "." in text else int(text)

# Marqueurs de CHAPITRE (unite plus fine qu'un tome relie). Le regroupement et
# l'enchainement traitent volontairement un chapitre comme un "tome" (webtoons
# et scans numerotes par chapitre), mais la DEDUPLICATION doit les distinguer :
# "One Piece Chapitre 5" et "One Piece Tome 5" sont des contenus differents et
# ne doivent pas s'ecraser l'un l'autre (cf. LibraryWidget._dedupe_by_series_volume).
# "episode" (webtoons) est une unite de type chapitre, pas un tome relie.
_CHAPTER_MARKER = re.compile(r"(?i)^(?:chapitre|chapter|chap|ch|ep(?:isode)?)")
# un cycle (integrale de plusieurs tomes) n'est ni un tome ni un chapitre :
# "Seuls Cycle 1" et "Seuls Tome 1" sont des contenus differents
_CYCLE_MARKER = re.compile(r"(?i)^(?:du\s+)?cycle")


def _volume_kind(pattern, match) -> str:
    """Nature du numero extrait, pour la deduplication : "chapter" (marqueur de
    chapitre), "cycle" (integrale d'un cycle de BD), "bare" (numero final sans
    marqueur, identite fragile) ou "volume" (tome/vol/#, unite reliee
    habituelle)."""
    if pattern is _TRAILING_NUMBER:
        return "bare"
    if pattern is _VOLUME_PATTERNS[0] and _CHAPTER_MARKER.match(match.group(0)):
        return "chapter"
    if pattern is _VOLUME_PATTERNS[0] and _CYCLE_MARKER.match(match.group(0)):
        return "cycle"
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
# multi-langues, ex. "Chainsaw Man T01 French", "Berserk Chapitre 386 ENG") :
# ne font pas partie du titre et doivent disparaitre pour que les tomes d'une
# meme serie se regroupent quelle que soit la langue de l'edition.
# Couvre les noms complets ET les codes courts scene (ENG, FR, JAP...).
# Volontairement absents car ce sont des mots frequents de vrais titres :
# "en", "de", "it", "es", "us" (prepositions/pronoms francais ou anglais).
_LANGUAGE_TERMS = re.compile(
    r"(?i)\b(?:"
    r"french|francais|anglais|english|espagnol|spanish|italien|italian|"
    r"allemand|german|japonais|japanese|portugais|portuguese|russe|russian|"
    r"coreen|korean|chinois|chinese|"
    r"vf|vo|vostfr|vosta|multi|bilingue|bilingual|"
    r"fra|fre|fr|eng|jap|jpn|jp|esp|spa|ita|ger|deu|rus|kor|por|"
    r"scans?|scantrad"
    r")\b")
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


def parse_series(stem: str, folder=None):
    """Retourne (nom_de_serie, numero_de_tome). numero_de_tome vaut None si
    aucun numero n'a pu etre extrait (le fichier est alors sa propre serie)."""
    name, number, _ = parse_series_ex(stem, folder)
    return name, number


def parse_path(path):
    """parse_series_ex d'un chemin de fichier : nom, dossier compris."""
    p = Path(path)
    return parse_series_ex(p.stem, p.parent.name)


def _normalized_stem(stem: str) -> str:
    """Nom de fichier ramene a des mots separes par des espaces : suffixe de
    doublon retire, underscores et points « scene » convertis."""
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
    # nommage « scene » : des points a la place des espaces
    # ("Chainsaw.Man.T20.Fujimoto.FR.[CBZ]-NoTag"), seulement si le nom n'a
    # aucun espace ("Dr. Stone" garde son point) ; un nombre decimal
    # ("ch385.5") reste intact
    if " " not in work:
        work = re.sub(r"(?<!\d)\.|\.(?!\d)", " ", work).strip()
    return work


# mots introduisant une sous-serie numerotee, qui fait partie du nom :
# « Jojo's Bizarre Adventure - Part 07 - Steel Ball Run T01 »
_SUBSERIES_WORD = re.compile(r"(?i)\b(?:part|partie|arc|saison|season|book|livre|volet)\s*$")
_DASH_BEFORE = re.compile(r"-\s*$")


def _first_marker(text: str):
    """(pattern, match) du marqueur de tome : marqueur explicite (Tome, T,
    Vol, #...) ou numero suivi du titre de l'album (« Astérix - 38 - Titre »).

    Le numero d'album n'est retenu ni apres un mot de sous-serie (« Part 07 -
    Steel Ball Run »), ni quand un marqueur explicite le suit immediatement
    (« Area 51 - Tome 2 »). Face a un marqueur explicite plus loin, il ne
    l'emporte que s'il est encadre de tirets (« Blake et Mortimer - 01 - Le
    Secret de l'Espadon T1 », ou le « T1 » appartient au titre de l'album)."""
    explicit = [m and (m.start(), pattern, m)
                for pattern in _VOLUME_PATTERNS[:2]
                for m in [pattern.search(text)]]
    explicit = [e for e in explicit if e]
    first_explicit = min(explicit, key=lambda e: e[0]) if explicit else None

    titled = _TITLED_NUMBER.search(text)
    if titled and _SUBSERIES_WORD.search(text[:titled.start()]):
        titled = None
    if titled and any(start == titled.end() for start, _p, _m in explicit):
        titled = None
    if titled and first_explicit:
        framed = bool(_DASH_BEFORE.search(text[:titled.start()]))
        if not framed or first_explicit[0] < titled.start():
            titled = None
    if titled:
        return _TITLED_NUMBER, titled
    if first_explicit:
        return first_explicit[1], first_explicit[2]
    return None


def _folder_series(folder):
    """Nom de serie tire du dossier du fichier, ou None s'il n'en donne pas
    (« Berserk (Miura) [Manga FR] » -> « Berserk »)."""
    if not folder:
        return None
    name, _number, _kind = parse_series_ex(str(folder))
    return None if is_generic_name(name) else name


def parse_series_ex(stem: str, folder=None):
    """Comme parse_series, mais renvoie aussi la NATURE du numero
    (voir _volume_kind) : (nom_de_serie, numero, kind). `kind` vaut None quand
    aucun numero n'est trouve. Utilise par la deduplication, qui doit
    distinguer un chapitre d'un tome relie la ou le regroupement les confond.

    `folder` : nom du dossier du fichier. Il fournit le nom de serie quand le
    fichier n'en a pas (« Berserk/Tome 01.cbz ») ; sans lui, deux dossiers de
    fichiers « Tome 01 » se confondraient en une seule serie « Tome »."""
    work = _normalized_stem(stem)

    # on cherche le tome d'abord dans la version debarrassee du bruit de
    # release, puis dans la version brute en repli : un titre entierement
    # entre crochets (ex. "[Oshi no Ko] T03") ne doit pas etre vide apres
    # nettoyage, et un numero peut se cacher dans un groupe legitime.
    # Repli intermediaire : version aussi debarrassee des mentions d'edition/
    # langue NON parenthesees ("Berserk 386 ENG", "Bleach 07 VF") - sans
    # marqueur explicite, le numero n'est reconnu qu'en toute fin de nom, et
    # un code de langue final le masquait completement.
    bare = _strip_release_junk(work)
    plain = re.sub(r"\s{2,}", " ", _strip_edition_terms(bare)).strip(" -_.")
    candidates = [c for c in dict.fromkeys((bare, plain, work)) if c]

    for text in candidates:
        tries = []
        first = _first_marker(text)
        if first:
            tries.append(first)
        for pattern in (_RANGE, _TRAILING_NUMBER):
            m = pattern.search(text)
            if m:
                tries.append((pattern, m))
        for pattern, m in tries:
            number = _to_number(m.group(1))
            # un numero final a 4 chiffres et plus ressemble a une annee ou a
            # une resolution ("Edition 2020", "1920"), pas a un numero de tome
            if pattern is _TRAILING_NUMBER and number > 999:
                continue
            if pattern is _RANGE and int(m.group(2)) <= number:
                continue   # « 1-2 » dans « Ranma 1-2 » n'est pas une plage
            kind = ("range" if pattern is _RANGE else
                    "volume" if pattern is _TITLED_NUMBER else _volume_kind(pattern, m))
            # marqueur explicite (Tome, T, Vol, #...) : la serie est ce qui le
            # precede ; la suite est le titre de l'album, l'auteur ou le
            # groupe de release ("Seuls - Tome 4 - Les cairns rouges",
            # "Chainsaw Man T20 Fujimoto FR -NoTag"). Sans rien avant le
            # marqueur ("Tome 3 - Berserk"), la serie est ce qui le suit.
            before = _clean_name(text[:m.start()])
            if pattern is not _TRAILING_NUMBER and before:
                name = before
            else:
                name = _clean_name(text[:m.start()] + text[m.end():])
            # le numero peut apparaitre deux fois ("Choujin X T07 - Tome 7") :
            # purge les marqueurs explicites redondants portant le meme numero
            # (jamais les numeros nus : "Area 51" doit rester intact)
            while name:
                m2 = _VOLUME_PATTERNS[0].search(name) or _VOLUME_PATTERNS[1].search(name)
                if not m2 or _to_number(m2.group(1)) != number:
                    break
                name = _clean_name(name[:m2.start()] + name[m2.end():])
            if not name or is_generic_name(name):
                # fichier sans nom de serie (« Tome 01 ») : celui du dossier
                from_folder = _folder_series(folder)
                if from_folder:
                    return from_folder, number, kind
            if name:
                return name, number, kind
    name = (candidates[0] if candidates else stem).strip()
    if is_generic_name(name):
        name = _folder_series(folder) or name
    return name, None, None


def clean_title(stem: str) -> str:
    """Nom de fichier presentable (sans numero reconnu) : separateurs ramenes
    a des espaces, groupes de release entre crochets/parentheses retires
    (« Errance [Digital-1920] (Team) » -> « Errance »)."""
    work = _normalized_stem(stem)
    return _strip_release_junk(work) or work or stem


def volume_label(number, kind) -> str:
    """« Tome 3 », « Chapitre 385.5 », « Cycle 2 »."""
    unit = {"chapter": "Chapitre", "cycle": "Cycle"}.get(kind, "Tome")
    if isinstance(number, float) and number.is_integer():
        number = int(number)
    return f"{unit} {number}"


def matches_author(hints, names) -> bool:
    """Vrai si l'un des indices d'auteur (voir author_hint) designe l'une des
    personnes `names` : un mot d'au moins 3 lettres en commun, sans tenir
    compte des accents ni de l'ordre (« Urasawa » / « Naoki Urasawa »,
    « Oshimi Shuzo » / « Shuuzou Oshimi »)."""
    def words(texts):
        return {w for t in texts for w in normalize_name(t or "").split()
                if len(w) >= 3 and not w.isdigit()}
    return bool(hints) and bool(words(hints) & words(names))


def author_hint(stem: str) -> list:
    """Indices d'auteur glisses dans le nom de fichier, entre parentheses
    (« Monster T01 (Urasawa) (2010) », « Léviathan (Kuroi Shiro) ») : les
    groupes entre parentheses qui ne sont ni un nombre ni une annee. On y
    trouve aussi l'editeur ou le groupe de release : ces indices ne servent
    qu'a departager des oeuvres homonymes, jamais a en ecarter une."""
    groups = re.findall(r"\(([^()]+)\)", stem or "")
    return [g.strip() for g in groups if g.strip() and not re.fullmatch(r"[\d\s.-]+", g)]


def normalize_name(name: str) -> str:
    """Normalise un nom de serie pour la comparaison : insensible a la
    casse, aux accents ("Pokémon" vs "Pokemon"), aux tirets/underscores
    utilises comme espaces (frequents dans les noms de fichiers type
    "gloutons-dragons") et a la ponctuation (ex. "&")."""
    s = _remove_accents(name).casefold()
    s = re.sub(r"[\-_]+", " ", s)
    s = re.sub(r"[^\w\s]", " ", s, flags=re.UNICODE)
    s = re.sub(r"\s+", " ", s).strip()
    return s


def series_key(stem: str) -> str:
    """Cle de regroupement insensible a la casse/aux separateurs/ponctuation."""
    name, _ = parse_series(stem)
    return normalize_name(name)


def next_volume(path: str, siblings):
    """Parmi `siblings` (chemins des fichiers du meme dossier), le tome de
    numero immediatement superieur appartenant a la meme serie que `path`.
    Renvoie son chemin ou None. Logique pure : la liste des fichiers est
    fournie par l'appelant (voir infra.archive.find_next_volume)."""
    p = Path(path)
    name, volume = parse_series(p.stem, p.parent.name)
    if volume is None:
        return None
    key = normalize_name(name)

    candidates = []
    for sib in siblings:
        if sib == str(p):
            continue
        sname, svolume = parse_series(Path(sib).stem, Path(sib).parent.name)
        if svolume is not None and normalize_name(sname) == key:
            candidates.append((svolume, sib))

    better = [c for c in candidates if c[0] > volume]
    if not better:
        return None
    return min(better)[1]
