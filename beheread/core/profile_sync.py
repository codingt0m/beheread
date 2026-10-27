"""Synchronisation d'un profil avec un serveur Beheread : logique pure
(aucune dependance Qt, aucun acces disque ni reseau, testee isolement),
partagee par le serveur et par ses clients (desktop, web).

Les clients envoient des evenements ; le serveur les applique a l'etat du
profil (ProfileState) puis diffuse ce qui a change. Les regles (cahier des
charges, P1 a P6) :

* une progression = (profil, empreinte) -> page, total, termine, heure de
  l'action (P1). Une empreinte inconnue de la bibliotheque est acceptee :
  c'est un tome present seulement sur un PC (P3) ;
* conflit : la plus recente action l'emporte (P2), qu'elle avance ou recule
  - relire depuis le debut sur un autre appareil est donc respecte, et un
  appareil reste hors ligne n'ecrase pas une lecture plus recente ;
* l'heure est celle de l'appareil (lectures hors ligne), bornee : une heure
  dans le futur est ramenee a l'heure de reception, et l'ordre propre a
  chaque appareil est garde (un evenement n'est jamais date avant le
  precedent du meme appareil) ;
* chaque evenement porte un identifiant unique (UUIDv7, cree par le client) :
  renvoyer un paquet apres une coupure ne compte rien deux fois (P5, P6) ;
* le web envoie des vues de page brutes ; les seances en sont deduites ici,
  avec les memes seuils que le lecteur du desktop (reading_session.py), pour
  des statistiques identiques.

Format d'un evenement (dictionnaire JSON) : {"id", "type", "device", "ts"}
plus les champs de son type (voir EVENT_FIELDS). `ts` : heure de l'appareil,
en secondes depuis l'epoque.
"""

from __future__ import annotations

import datetime as dt
import os
import time
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Set, Tuple

from beheread.core.reading_session import MIN_DWELL, PAUSE_CAP

PROGRESS, PAGE_VIEWS, JOURNAL, DISMISS, READER_OVERRIDE = (
    "progress", "page_views", "journal", "dismiss", "reader_override")
# champs propres a chaque type (en plus de id, type, device, ts)
EVENT_FIELDS = {
    PROGRESS: ("fp", "page", "total", "finished"),
    PAGE_VIEWS: ("fp", "views"),        # views : [[pages affichees, debut, duree], ...]
    JOURNAL: ("rows",),                 # seances calculees par le desktop
    DISMISS: ("target",),               # empreinte, ou « series:<cle> »
    READER_OVERRIDE: ("target", "setting", "value"),
}
# deux vues separees de plus que cela n'appartiennent pas a la meme seance
SESSION_GAP = 30 * 60
MAX_BATCH = 500           # evenements par envoi au plus


class EventError(ValueError):
    """Evenement mal forme : refuse, sans empecher les autres du paquet."""


# ------------------------------------------------------------------ identifiants

def new_event_id(now: Optional[float] = None, rand: Optional[bytes] = None) -> str:
    """Identifiant UUIDv7 (RFC 9562) : l'heure en millisecondes en tete, donc
    croissant dans le temps, puis 74 bits aleatoires."""
    ms = int((time.time() if now is None else now) * 1000) & ((1 << 48) - 1)
    r = int.from_bytes(rand if rand is not None else os.urandom(10), "big")
    rand_a = (r >> 62) & 0xFFF
    rand_b = r & ((1 << 62) - 1)
    value = (ms << 80) | (0x7 << 76) | (rand_a << 64) | (0b10 << 62) | rand_b
    h = f"{value:032x}"
    return f"{h[:8]}-{h[8:12]}-{h[12:16]}-{h[16:20]}-{h[20:]}"


# ------------------------------------------------------------------ validation

def _number(value, name, minimum=0):
    if isinstance(value, bool) or not isinstance(value, (int, float)) or value < minimum:
        raise EventError(f"{name} invalide")
    return value


def _text(value, name, max_len=200):
    if not isinstance(value, str) or not value or len(value) > max_len:
        raise EventError(f"{name} invalide")
    return value


def validate(event) -> dict:
    """Evenement verifie (copie ne gardant que les champs connus), ou
    EventError. Un client est suppose honnete mais peut etre bogue : rien
    d'inattendu n'entre dans la base d'un profil."""
    if not isinstance(event, dict):
        raise EventError("evenement invalide")
    kind = event.get("type")
    if kind not in EVENT_FIELDS:
        raise EventError("type inconnu")
    clean = {"id": _text(event.get("id"), "id", 64), "type": kind,
             "device": _text(event.get("device"), "device", 64),
             "ts": float(_number(event.get("ts"), "ts"))}
    for name in EVENT_FIELDS[kind]:
        if name not in event:
            raise EventError(f"{name} manquant")
        clean[name] = event[name]
    if kind in (PROGRESS, PAGE_VIEWS):
        _text(clean["fp"], "fp")
    if kind == PROGRESS:
        page, total = _number(clean["page"], "page"), _number(clean["total"], "total")
        if not isinstance(page, int) or not isinstance(total, int):
            raise EventError("page invalide")
        clean["finished"] = bool(clean["finished"])
    elif kind == PAGE_VIEWS:
        clean["views"] = [_view(v) for v in _list(clean["views"], "views")]
        if "tz" in event:   # decalage horaire de l'appareil (minutes), pour dater les seances
            clean["tz"] = int(_number(event["tz"], "tz", minimum=-14 * 60))
            if clean["tz"] > 14 * 60:
                raise EventError("tz invalide")
    elif kind == JOURNAL:
        clean["rows"] = [_journal_row(r) for r in _list(clean["rows"], "rows")]
    elif kind == DISMISS:
        _text(clean["target"], "target")
    elif kind == READER_OVERRIDE:
        _text(clean["target"], "target")
        _text(clean["setting"], "setting", 64)
    return clean


def _list(value, name, max_len=10000):
    if not isinstance(value, list) or len(value) > max_len:
        raise EventError(f"{name} invalide")
    return value


def _view(view) -> Tuple[Tuple[int, ...], float, float]:
    """[pages, debut, duree] : pages = un indice ou une liste (double page)."""
    if not isinstance(view, (list, tuple)) or len(view) != 3:
        raise EventError("vue invalide")
    pages, start, duration = view
    pages = [pages] if isinstance(pages, int) and not isinstance(pages, bool) else pages
    if not isinstance(pages, list) or not 1 <= len(pages) <= 2 or \
            not all(isinstance(p, int) and not isinstance(p, bool) and p >= 0 for p in pages):
        raise EventError("pages invalides")
    return tuple(pages), float(_number(start, "debut")), float(_number(duration, "duree"))


def _journal_row(row) -> dict:
    if not isinstance(row, dict):
        raise EventError("ligne de journal invalide")
    try:
        day = dt.date.fromisoformat(str(row.get("day"))).isoformat()
    except (TypeError, ValueError):
        raise EventError("jour invalide") from None
    return {"day": day, "fp": _text(row.get("fp"), "fp"),
            "pages": int(_number(row.get("pages", 0), "pages")),
            "seconds": float(_number(row.get("seconds", 0), "seconds")),
            "finished": bool(row.get("finished"))}


# ------------------------------------------------------------------ horloge

def effective_time(device_ts: float, received: float, previous: Optional[float]) -> float:
    """Heure retenue pour un evenement : celle de l'appareil, ramenee a
    l'heure de reception si elle est dans le futur, et jamais avant celle
    du precedent evenement du meme appareil."""
    ts = min(device_ts, received)
    return ts if previous is None else max(ts, previous)


# ------------------------------------------------------------------ seances (vues de page du web)

def sessions_from_views(views, tz_minutes: int = 0) -> List[dict]:
    """Seances deduites de vues de page brutes [(pages, debut, duree)], avec
    les regles du lecteur du desktop : une vue de moins de MIN_DWELL secondes
    ne compte pas ; au-dela de PAUSE_CAP, son temps est ignore (pause) ; ses
    pages ne sont lues que si l'on avance ensuite. La derniere vue d'une
    seance n'est donc pas comptee comme lue, comme a la fermeture du lecteur
    (une fin de tome arrive, elle, par la progression).

    Renvoie une ligne par seance : {"day", "pages", "seconds", "start"}."""
    ordered = sorted(views, key=lambda v: v[1])
    sessions: List[List[tuple]] = []
    last_end = None
    for view in ordered:
        if last_end is None or view[1] - last_end > SESSION_GAP:
            sessions.append([])
        sessions[-1].append(view)
        last_end = max(last_end or 0.0, view[1] + view[2])
    rows = []
    for group in sessions:
        pages: Set[int] = set()
        seconds = 0.0
        for i, (shown, _start, duration) in enumerate(group):
            if duration < MIN_DWELL:
                continue
            if duration <= PAUSE_CAP:
                seconds += duration
            nxt = group[i + 1][0] if i + 1 < len(group) else None
            if nxt is not None and min(nxt) > max(shown):
                pages.update(shown)
        if not pages and seconds <= 0:
            continue
        start = group[0][1]
        day = dt.datetime.fromtimestamp(start + tz_minutes * 60, dt.timezone.utc).date()
        rows.append({"day": day.isoformat(), "pages": len(pages), "seconds": seconds,
                     "start": start})
    return rows


# ------------------------------------------------------------------ etat d'un profil

@dataclass
class ProfileState:
    """Etat synchronise d'un profil, tel que le tient le serveur.

    `progress` a la forme de la progression du desktop (Store.progress) :
    {empreinte: {"page", "total", "finished", "ts"}}, plus "device" (l'appareil
    de l'action). Les autres dictionnaires sont indexes de meme ; `journal`
    recoit les lignes a ajouter au journal de lecture (une par seance)."""

    progress: Dict[str, dict] = field(default_factory=dict)
    dismissed: Dict[str, dict] = field(default_factory=dict)
    overrides: Dict[str, dict] = field(default_factory=dict)
    journal: List[dict] = field(default_factory=list)
    seen: Set[str] = field(default_factory=set)              # evenements deja appliques
    device_clock: Dict[str, float] = field(default_factory=dict)


def _newer(event_key: tuple, current: Optional[dict]) -> bool:
    """La plus recente action l'emporte ; a heure egale, l'ordre (appareil,
    identifiant) departage de facon identique partout."""
    if current is None:
        return True
    return event_key > (current.get("ts", 0.0), current.get("device", ""), current.get("id", ""))


def apply(state: ProfileState, event: dict, received: float) -> List[tuple]:
    """Applique un evenement deja valide (validate) ; renvoie les changements
    a diffuser : [(depot, cle)] - vide si l'evenement etait deja connu ou
    plus ancien que l'etat."""
    if event["id"] in state.seen:
        return []
    state.seen.add(event["id"])
    device = event["device"]
    ts = effective_time(event["ts"], received, state.device_clock.get(device))
    state.device_clock[device] = ts
    stamp = {"ts": ts, "device": device, "id": event["id"]}
    order = (ts, device, event["id"])
    kind = event["type"]

    if kind == PROGRESS:
        fp = event["fp"]
        if not _newer(order, state.progress.get(fp)):
            return []
        state.progress[fp] = dict(stamp, page=event["page"], total=event["total"],
                                  finished=event["finished"])
        return [("progress", fp)]
    if kind == DISMISS:
        target = event["target"]
        if not _newer(order, state.dismissed.get(target)):
            return []
        state.dismissed[target] = stamp
        return [("dismissed", target)]
    if kind == READER_OVERRIDE:
        key = f"{event['target']}\x1f{event['setting']}"
        if not _newer(order, state.overrides.get(key)):
            return []
        state.overrides[key] = dict(stamp, target=event["target"], setting=event["setting"],
                                    value=event["value"])
        return [("overrides", key)]
    if kind == JOURNAL:
        rows = [dict(r, device=device, sessions=1 if r["pages"] or r["seconds"] else 0)
                for r in event["rows"]]
    else:   # PAGE_VIEWS
        rows = [dict(r, fp=event["fp"], device=device, sessions=1, finished=False)
                for r in sessions_from_views(event["views"], event.get("tz", 0))]
    state.journal.extend(rows)
    return [("journal", None)] if rows else []


def apply_batch(state: ProfileState, events, received: float) -> dict:
    """Applique un envoi d'evenements (POST /api/v1/events). Les evenements
    mal formes sont refuses un par un, sans bloquer les autres ; ceux du meme
    appareil sont appliques dans l'ordre de leurs identifiants (UUIDv7 :
    l'ordre de creation). Renvoie {"accepted": [id], "rejected": {id: motif},
    "changes": [(depot, cle)]} ; un evenement deja connu est « accepte » (le
    client peut l'oublier)."""
    if not isinstance(events, list) or len(events) > MAX_BATCH:
        raise EventError("paquet invalide")
    valid, rejected = [], {}
    for i, raw in enumerate(events):
        try:
            valid.append(validate(raw))
        except EventError as exc:
            ident = raw.get("id") if isinstance(raw, dict) and isinstance(raw.get("id"), str) \
                else f"#{i}"
            rejected[ident] = str(exc)
    valid.sort(key=lambda e: (e["device"], e["id"]))
    changes: List[tuple] = []
    for event in valid:
        for change in apply(state, event, received):
            if change not in changes:
                changes.append(change)
    return {"accepted": [e["id"] for e in valid], "rejected": rejected, "changes": changes}


# ------------------------------------------------------------------ reprise (P4)

@dataclass(frozen=True)
class Resume:
    """Reprise a l'ouverture d'un tome : aller a `page`, en proposant de
    revenir a `back_to` (bandeau « Repris a la page 87, lue sur l'iPad ·
    Revenir page 40 »)."""

    page: int
    back_to: int
    device: str
    ts: float


def resume(local: Optional[dict], remote: Optional[dict], this_device: str) -> Optional[Resume]:
    """Reprise a proposer, ou None : seulement si la progression du serveur
    est plus recente que la locale, vient d'un autre appareil et mene a une
    autre page. `local`, `remote` : entrees de progression ({"page", "ts",
    "device"...})."""
    if not remote or remote.get("device") == this_device:
        return None
    if local and float(local.get("ts", 0)) >= float(remote.get("ts", 0)):
        return None
    page = int(remote.get("page", 0))
    back = int(local.get("page", 0)) if local else 0
    if page == back:
        return None
    return Resume(page=page, back_to=back, device=str(remote.get("device")),
                  ts=float(remote.get("ts", 0)))
