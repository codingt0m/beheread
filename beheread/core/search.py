"""Recherche dans la bibliotheque (logique pure, sans Qt, testee isolement).

Index inverse : chaque document (un tome) est decoupe en mots normalises
(voir fold) et l'index associe chaque mot aux documents qui le contiennent.
La requete est decoupee de la meme facon et TOUS ses mots doivent etre
trouves, dans n'importe quel champ du document (titre, serie, auteur...) :

* un mot alphabetique correspond a tout mot indexe qui le CONTIENT ("saw"
  trouve "chainsaw"), comme l'ancienne recherche par sous-chaine ;
* un nombre ne correspond qu'au meme nombre entier : "1" trouve "T01" mais
  ni "T10" ni "T100" ;
* sans aucun resultat exact, un mot introuvable est rapproche des mots
  indexes a une ou deux fautes de frappe pres (resultats « approchants »).

Une recherche parcourt le VOCABULAIRE (les mots distincts, quelques milliers
meme pour une grosse bibliotheque : les mots d'une serie sont partages par
tous ses tomes), pas les documents un par un : son cout depend peu du nombre
de tomes.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from functools import lru_cache
from typing import Dict, FrozenSet, Iterable, List, Mapping, Optional, Set

from beheread.core.anilist_track import AUTO_MATCH_MIN_SCORE

# lettres que la decomposition Unicode (NFKD) ne ramene pas a une lettre de
# base suivie d'un accent : ligatures et lettres barrees
_TRANSLIT = str.maketrans({"œ": "oe", "æ": "ae", "ø": "o", "ł": "l", "đ": "d",
                           "ħ": "h", "ı": "i", "þ": "th"})
_NON_WORD = re.compile(r"[\W_]+")
# frontiere lettre/chiffre : "T01" -> "T 01", "20th" -> "20 th"
_LETTER_DIGIT = re.compile(r"(?<=\d)(?=[^\W\d_])|(?<=[^\W\d_])(?=\d)")
_LEADING_ZEROS = re.compile(r"\b0+(?=\d)")

# en dessous de 4 lettres, une faute de frappe rapprocherait des mots sans
# rapport ("one" -> "ono", "man" -> "mao") : pas de recherche approchante
FUZZY_MIN_LEN = 4

# au-dela, le cache des sous-chaines deja resolues est vide (une session de
# frappe en remplit quelques dizaines tout au plus)
_TOKEN_CACHE_MAX = 512


@lru_cache(maxsize=65536)
def fold(text: str) -> str:
    """Forme normalisee d'un texte, pour l'indexation comme pour la requete :
    minuscules, sans accents ("Kōhei" -> "kohei", "Pokémon" -> "pokemon"),
    ponctuation et separateurs ramenes a des espaces ("Gloutons & Dragons",
    "One_Piece", "Dr. Stone"), lettres et chiffres separes et zeros de tete
    retires ("T01" -> "t 1"). Memorise : les memes noms de serie et d'auteur
    reviennent pour chaque tome et a chaque reconstruction de l'index."""
    s = unicodedata.normalize("NFKD", text.casefold().translate(_TRANSLIT))
    s = "".join(c for c in s if not unicodedata.combining(c))
    s = _NON_WORD.sub(" ", s)
    s = _LETTER_DIGIT.sub(" ", s)
    s = _LEADING_ZEROS.sub("", s)
    return s.strip()


def tokenize(text: str) -> List[str]:
    """Mots normalises d'un texte (voir fold), dans l'ordre, doublons retires."""
    return list(dict.fromkeys(fold(text).split()))


def known_titles(meta: Optional[Mapping]) -> List[str]:
    """Titres d'une oeuvre connus par ses metadonnees en cache (titre affiche
    et titres alternatifs : romaji, original, traductions), a indexer avec le
    nom du fichier - "Attack on Titan" trouve alors "L'Attaque des Titans".

    AniList renvoie toujours un resultat, meme pour une serie qu'il ne connait
    pas : ses titres ne sont retenus que si la correspondance avec le nom du
    fichier est fiable (meme seuil que le suivi AniList), sans quoi la
    recherche ferait apparaitre une serie sous le nom d'une autre."""
    if not meta or meta.get("not_found"):
        return []
    if meta.get("source") == "anilist" and \
            (meta.get("match_score") or 0) < AUTO_MATCH_MIN_SCORE:
        return []
    titles = [meta.get("title"), *(meta.get("titles") or ())]
    return [t for t in dict.fromkeys(titles) if isinstance(t, str) and t]


def _fuzzy_budget(token: str) -> int:
    """Nombre de fautes de frappe tolerees pour ce mot (0 : aucune)."""
    if len(token) < FUZZY_MIN_LEN or token.isdigit():
        return 0
    return 1 if len(token) < 8 else 2


def near_prefix(token: str, word: str, k: int) -> bool:
    """Vrai si `token` est a au plus `k` fautes de frappe (insertion,
    suppression, substitution ou inversion de deux lettres voisines) du mot
    `word` ou de l'un de ses debuts : un mot en cours de frappe ("fujimot")
    est rapproche du mot complet ("fujimoto").

    Distance d'edition (Damerau restreinte) calculee ligne par ligne : la
    derniere ligne donne la distance a chaque prefixe de `word`, et le calcul
    s'arrete des qu'une ligne depasse `k` (la plupart des mots du vocabulaire
    sont ecartes en deux ou trois lignes)."""
    n = len(token)
    m = min(len(word), n + k)   # un prefixe plus long coute plus de k insertions
    if m < n - k:
        return False
    prev2 = None
    prev = list(range(m + 1))
    for i in range(1, n + 1):
        a = token[i - 1]
        cur = [i] + [0] * m
        for j in range(1, m + 1):
            b = word[j - 1]
            v = min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + (a != b))
            if prev2 is not None and j > 1 and a == word[j - 2] and token[i - 2] == b:
                v = min(v, prev2[j - 2] + 1)
            cur[j] = v
        if min(cur) > k:
            return False
        prev2, prev = prev, cur
    return min(prev) <= k


@dataclass(frozen=True)
class SearchResult:
    ids: FrozenSet[str]          # documents correspondant a la requete
    approximate: bool = False    # obtenus en tolerant des fautes de frappe


class SearchIndex:
    """Index inverse mot -> documents. Les documents sont identifies par une
    chaine (le chemin du tome) et decrits par une liste de textes (champs)."""

    def __init__(self):
        self._texts: Dict[str, tuple] = {}            # id -> textes indexes
        self._docs: Dict[str, FrozenSet[str]] = {}    # id -> mots
        self._postings: Dict[str, Set[str]] = {}      # mot -> ids
        self._strict: Dict[str, Set[str]] = {}        # mot de requete -> mots indexes
        self._fuzzy: Dict[str, Set[str]] = {}

    def __len__(self):
        return len(self._docs)

    def __contains__(self, doc_id):
        return doc_id in self._docs

    def set(self, doc_id: str, texts: Iterable[Optional[str]]):
        """Ajoute ou met a jour un document (sans effet s'il n'a pas change :
        la comparaison des textes bruts suffit alors, sans renormaliser)."""
        texts = tuple(t for t in texts if isinstance(t, str) and t)
        if self._texts.get(doc_id) == texts:
            return
        self._texts[doc_id] = texts
        words = frozenset(w for t in texts for w in fold(t).split())
        old = self._docs.get(doc_id)
        if old == words:
            return
        old = old or frozenset()
        for w in old - words:
            ids = self._postings[w]
            ids.discard(doc_id)
            if not ids:
                del self._postings[w]
        for w in words - old:
            self._postings.setdefault(w, set()).add(doc_id)
        self._docs[doc_id] = words
        self._invalidate()

    def discard(self, doc_id: str):
        self._texts.pop(doc_id, None)
        words = self._docs.pop(doc_id, None)
        if words is None:
            return
        for w in words:
            ids = self._postings[w]
            ids.discard(doc_id)
            if not ids:
                del self._postings[w]
        self._invalidate()

    def replace_all(self, docs: Mapping[str, Iterable[Optional[str]]]):
        """Aligne l'index sur `docs` (id -> textes) : retire les documents
        absents, met a jour les autres. Les documents inchanges ne coutent
        qu'une comparaison - l'index survit donc aux reconstructions."""
        for doc_id in [d for d in self._docs if d not in docs]:
            self.discard(doc_id)
        for doc_id, texts in docs.items():
            self.set(doc_id, texts)

    def _invalidate(self):
        self._strict.clear()
        self._fuzzy.clear()

    # ----- recherche -----
    def search(self, query: str) -> Optional[SearchResult]:
        """Documents contenant tous les mots de la requete, ou None si la
        requete n'a aucun mot cherchable (vide, ponctuation seule) - auquel
        cas il n'y a rien a filtrer."""
        tokens = tokenize(query)
        if not tokens:
            return None
        per_token = [self._ids(self._strict_words(t)) for t in tokens]
        result = _intersect(per_token)
        if result or all(per_token):
            # resultat exact ; ou chaque mot existe mais jamais ensemble
            # ("berserk chainsaw") - une faute de frappe n'y est pour rien
            return SearchResult(frozenset(result))
        fuzzy = []
        for t, ids in zip(tokens, per_token):
            if not ids:
                ids = self._ids(self._fuzzy_words(t))
                if not ids:
                    return SearchResult(frozenset())
            fuzzy.append(ids)
        result = _intersect(fuzzy)
        return SearchResult(frozenset(result), approximate=bool(result))

    def _ids(self, words: Iterable[str]) -> Set[str]:
        postings = self._postings
        return set().union(*(postings[w] for w in words))

    def _strict_words(self, token: str) -> Set[str]:
        """Mots indexes correspondant exactement a `token` : le meme nombre,
        ou tout mot contenant ces lettres. Pendant la frappe, chaque mot de
        requete prolonge le precedent ("fu" -> "fuj") : on ne reparcourt
        alors que les mots qui contenaient deja le debut."""
        cached = self._strict.get(token)
        if cached is not None:
            return cached
        if token.isdigit():
            words = {token} if token in self._postings else set()
        else:
            base = self._postings.keys()
            best = 0
            for prev, prev_words in self._strict.items():
                if len(prev) > best and not prev.isdigit() and prev in token:
                    base, best = prev_words, len(prev)
            words = {w for w in base if token in w}
        if len(self._strict) >= _TOKEN_CACHE_MAX:
            self._strict.clear()
        self._strict[token] = words
        return words

    def _fuzzy_words(self, token: str) -> Set[str]:
        cached = self._fuzzy.get(token)
        if cached is not None:
            return cached
        k = _fuzzy_budget(token)
        words = set()
        if k:
            shortest = len(token) - k
            words = {w for w in self._postings
                     if len(w) >= shortest and not w.isdigit() and near_prefix(token, w, k)}
        if len(self._fuzzy) >= _TOKEN_CACHE_MAX:
            self._fuzzy.clear()
        self._fuzzy[token] = words
        return words


def _intersect(sets: List[Set[str]]) -> Set[str]:
    if not sets:
        return set()
    ordered = sorted(sets, key=len)
    result = set(ordered[0])
    for s in ordered[1:]:
        result &= s
        if not result:
            break
    return result
