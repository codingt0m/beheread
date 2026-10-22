"""Client minimal pour Wikidata (API publique MediaWiki, sans cle).

Arbitre de la nature d'une oeuvre quand la BnF ne la connait pas (comics non
traduit, BD absente du catalogue sous ce titre : « Lastman ») : chaque
element Wikidata dit ce qu'il est (P31 : serie de bande dessinee, serie de
manga...) et d'ou il vient (P495 : pays d'origine). AniList, interroge seul,
trouve toujours un manga homonyme ; Wikidata dit s'il existe une serie de BD
de ce nom, et si elle est japonaise, coreenne ou occidentale.

La recherche plein texte (CirrusSearch) est restreinte aux elements dont la
nature (P31) est une classe de BD (haswbstatement) : la recherche par
libelle seule classe par notoriete et ramene d'abord les films, jeux video
et series animees homonymes. Les donnees de Wikidata sont sous licence CC0.
"""

import json
import urllib.error
import urllib.parse
import urllib.request

from beheread.core.series import matches_author
from beheread.core.text import strip_accents
from beheread.infra import net
from beheread.infra.mangadex import title_score

API_URL = "https://www.wikidata.org/w/api.php"
TIMEOUT = 15
MIN_INTERVAL = 1.0
MAX_RESULTS = 10
# la charte de Wikimedia demande un User-Agent qui identifie l'application
USER_AGENT = net.APP_USER_AGENT

# natures (P31) retenues, par famille : le sens de lecture s'en deduit
MANGA_CLASSES = {"Q21198342", "Q8274", "Q3285662"}            # serie de manga, manga, manfra
MANHWA_CLASSES = {"Q74262765", "Q562214", "Q754669"}          # manhwa, manhua
COMIC_CLASSES = {"Q14406742", "Q1004", "Q2831984", "Q725377",  # serie de BD, BD, album,
                 "Q838795", "Q3297186", "Q1760610"}            # roman graphique, strip...
CLASSES = MANGA_CLASSES | MANHWA_CLASSES | COMIC_CLASSES

# pays d'origine (P495) -> code ISO, pour ceux qui comptent pour le sens de
# lecture et l'affichage
COUNTRIES = {"Q17": "JP", "Q884": "KR", "Q148": "CN", "Q865": "TW", "Q8646": "HK",
             "Q30": "US", "Q142": "FR", "Q31": "BE", "Q145": "GB", "Q39": "CH",
             "Q16": "CA", "Q29": "ES", "Q38": "IT", "Q183": "DE", "Q55": "NL",
             "Q155": "BR", "Q96": "MX", "Q414": "AR"}
ASIAN_RTL = ("JP",)
ASIAN_LTR = ("KR", "CN", "TW", "HK")

_LIMITER = net.RateLimiter(MIN_INTERVAL)


class WikidataError(Exception):
    """Erreur reseau/HTTP/format - a distinguer d'une recherche sans resultat."""


def _throttle():
    """Espace les requetes vers ce service (voir net.RateLimiter)."""
    _LIMITER.wait()


def _get(params):
    url = f"{API_URL}?{urllib.parse.urlencode(dict(params, format='json'))}"
    _throttle()
    try:
        req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
        with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        if e.code == 429:
            _LIMITER.back_off(net.retry_after(e))
        raise WikidataError(str(e)) from e
    except (urllib.error.URLError, OSError, ValueError, TimeoutError) as e:
        raise WikidataError(str(e)) from e


def _values(entity, prop):
    """Valeurs d'une propriete : identifiants d'element, annees, nombres."""
    out = []
    for claim in (entity.get("claims") or {}).get(prop) or ():
        value = ((claim.get("mainsnak") or {}).get("datavalue") or {}).get("value")
        if isinstance(value, dict) and "id" in value:
            out.append(value["id"])
        elif isinstance(value, dict) and "time" in value:
            out.append(value["time"].lstrip("+")[:4])
        elif isinstance(value, dict) and "amount" in value:
            out.append(value["amount"].lstrip("+"))
    return out


def _names(entity):
    """Libelles et alias en francais et en anglais."""
    names = [v.get("value") for v in (entity.get("labels") or {}).values()]
    for aliases in (entity.get("aliases") or {}).values():
        names += [a.get("value") for a in aliases]
    return [n for n in dict.fromkeys(names) if n]


def kind_of(classes, country) -> str:
    """"manga", "manhwa" ou "comics" (BD, comics : sens occidental)."""
    if set(classes) & MANGA_CLASSES or country in ASIAN_RTL:
        return "manga"
    if set(classes) & MANHWA_CLASSES or country in ASIAN_LTR:
        return "manhwa"
    return "comics"


def _candidate(entity, name):
    classes = _values(entity, "P31")
    countries = [COUNTRIES[q] for q in _values(entity, "P495") if q in COUNTRIES]
    country = countries[0] if countries else None
    labels = entity.get("labels") or {}
    title = ((labels.get("fr") or labels.get("en") or {}).get("value")) or name
    years = [int(y) for y in _values(entity, "P580") + _values(entity, "P577") if y.isdigit()]
    parts = _values(entity, "P2635")
    names = _names(entity)
    kind = kind_of(classes, country)
    return {"title": title, "titles": names,
            "kind": kind, "format": "manga" if kind == "manga" else "bd",
            "country": country,
            "published_year": min(years) if years else None,
            # nombre de tomes : seulement s'il est unique (Vinland Saga en a
            # deux, tomes et chapitres, sans qualificatif fiable)
            "volumes": int(parts[0]) if len(parts) == 1 and parts[0].isdigit() else None,
            "author_ids": _values(entity, "P50") or _values(entity, "P110"),
            "wikidata_id": entity.get("id"),
            "match_score": round(title_score(strip_accents(name),
                                             [strip_accents(n) for n in names]), 3)}


def _labels(ids):
    """{identifiant: libelle} d'elements (auteurs)."""
    if not ids:
        return {}
    data = _get({"action": "wbgetentities", "ids": "|".join(ids[:50]),
                 "props": "labels", "languages": "fr|en"})
    out = {}
    for qid, entity in (data.get("entities") or {}).items():
        labels = entity.get("labels") or {}
        label = (labels.get("fr") or labels.get("en") or {}).get("value")
        if label:
            out[qid] = label
    return out


def search_series(name: str, author_hint=None):
    """Cherche une serie de BD, de comics ou de manga par son nom. Renvoie
    {title, titles, authors, published_year, country, kind ("manga",
    "manhwa", "comics"), format ("manga"/"bd"), volumes, wikidata_id,
    match_score, kinds} ou None ; `kinds` : natures des elements dont le nom
    correspond exactement (un comics et un manga homonymes : les deux).
    Leve WikidataError en cas de probleme reseau/HTTP/format."""
    words = " ".join(strip_accents(name or "").replace('"', " ").split())
    if not words:
        return None
    statements = "|".join(f"P31={q}" for q in sorted(CLASSES))
    found = _get({"action": "query", "list": "search", "srnamespace": "0",
                  "srlimit": str(MAX_RESULTS),
                  "srsearch": f"{words} haswbstatement:{statements}"})
    ids = [hit.get("title") for hit in ((found.get("query") or {}).get("search") or ())
           if str(hit.get("title", "")).startswith("Q")]
    if not ids:
        return None
    data = _get({"action": "wbgetentities", "ids": "|".join(ids),
                 "props": "claims|labels|aliases", "languages": "fr|en"})
    entities = data.get("entities") or {}
    candidates = [_candidate(entities[q], name) for q in ids if q in entities]
    candidates = [c for c in candidates if c["match_score"] >= 0.7]
    if not candidates:
        return None
    authors = _labels(list(dict.fromkeys(a for c in candidates for a in c["author_ids"])))
    for c in candidates:
        c["authors"] = [authors[a] for a in c.pop("author_ids") if a in authors][:1]
    best_score = max(c["match_score"] for c in candidates)
    # a ressemblance egale, l'auteur indique par le nom de fichier, puis
    # l'ordre de pertinence de la recherche
    best = max(candidates, key=lambda c: (c["match_score"],
                                          matches_author(author_hint, c["authors"]),
                                          -candidates.index(c)))
    best["kinds"] = sorted({c["kind"] for c in candidates if c["match_score"] >= best_score})
    return best
