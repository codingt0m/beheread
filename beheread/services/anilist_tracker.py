"""Suivi AniList (partie Qt) : a la fin de chaque seance de lecture (et quand
un tome est marque « lu » dans la bibliotheque), la progression de sa serie
est publiee sur la liste AniList de l'utilisateur - seulement si elle a
augmente depuis le dernier envoi.

Les regles de decision sont dans anilist_track.py (pures, testees) ; ici, on
orchestre : file d'attente persistante par serie (settings["anilist"]
["pending"]), appels reseau dans un thread dedie, resultats appliques au Store
sur le thread UI. Une mise a jour qui echoue (reseau, limite de requetes)
reste en file et sera retentee ; un jeton refuse suspend tout jusqu'a une
reconnexion.

Association serie <-> oeuvre AniList (settings["anilist"]["map"]) :
{"id": 30002, "title": "Berserk", "auto": True} (trouvee automatiquement),
{"id": ..., "auto": False} (choisie par l'utilisateur), {"ignored": True}
(ne pas suivre) ou {"unmatched": True} (recherche non concluante : a associer
a la main depuis le panneau d'informations).
"""

import logging
import time

from PySide6.QtCore import QObject, QRunnable, QThreadPool, QTimer, Signal

from beheread.core import anilist_track
from beheread.infra import anilist

RETRY_MS = 10 * 60 * 1000


class _Signals(QObject):
    done = Signal(object)


def _min_score(desired):
    """Ressemblance de titre exigee pour associer automatiquement : plus
    stricte pour un one-shot, qui serait publie « termine »."""
    if desired and desired.get("oneshot"):
        return anilist_track.ONESHOT_MIN_SCORE
    return anilist_track.AUTO_MATCH_MIN_SCORE


class _TrackWorker(QRunnable):
    """Traite une liste de travaux {series_key, name, desired, media_id}."""

    def __init__(self, token, jobs):
        super().__init__()
        self.token, self.jobs = token, jobs
        self.signals = _Signals()

    def run(self):
        results = []
        for job in self.jobs:
            res = {"series_key": job["series_key"], "status": "error",
                   "desired": job["desired"]}
            try:
                media_id = job.get("media_id")
                if media_id is None:
                    found = anilist.search_series(job["name"])
                    media_id = anilist_track.auto_match(found, _min_score(job["desired"]))
                    if media_id is None:
                        res["status"] = "unmatched"
                        results.append(res)
                        continue
                    res["mapped"] = {"id": media_id, "title": found.get("title"), "auto": True}
                media = anilist.media_entry(self.token, media_id)
                if media is None:
                    res["status"] = "missing"
                    results.append(res)
                    continue
                res["title"] = media.get("title")
                res["url"] = media.get("url")
                if anilist_track.oneshot_mismatch(job["desired"], media):
                    res["status"] = "skipped"
                    res["summary"] = "œuvre en plusieurs tomes : rien publié"
                    results.append(res)
                    continue
                changes = anilist_track.plan_update(job["desired"], media)
                if changes and not anilist_track.is_additive(changes, media.get("entry")):
                    logging.error("Mise a jour AniList non additive ignoree : %s", changes)
                    changes = None
                if changes:
                    anilist.save_entry(self.token, media_id, changes, media.get("entry"))
                    res["status"] = "updated"
                    res["summary"] = anilist_track.describe(changes)
                else:
                    res["status"] = "uptodate"
            except anilist.AniListAuthError:
                res["status"] = "auth"
                results.append(res)
                break   # jeton refuse : inutile de continuer
            except anilist.AniListError as e:
                res["error"] = str(e)
                logging.warning("Suivi AniList en echec pour %s : %s", job["series_key"], e)
            results.append(res)
        self.signals.done.emit(results)


class AniListTracker(QObject):
    statusChanged = Signal(str)
    seriesUpdated = Signal(str)    # cle de serie dont l'etat de suivi a change

    def __init__(self, store, series_resolver, parent=None):
        """series_resolver(path) -> (cle de serie, nom, [(numero, nature,
        termine)]) ou None : fourni par la bibliotheque."""
        super().__init__(parent)
        self.store = store
        self.series_resolver = series_resolver
        self.status = ""
        self._pool = QThreadPool(self)
        self._pool.setMaxThreadCount(1)
        self._worker = None
        self._debounce = QTimer(self)
        self._debounce.setSingleShot(True)
        self._debounce.setInterval(800)
        self._debounce.timeout.connect(self.flush_pending)
        self._retry = QTimer(self)
        self._retry.setInterval(RETRY_MS)
        self._retry.timeout.connect(self.flush_pending)
        self._retry.start()

    # ----- etat -----
    def user(self):
        return self.store.anilist().get("user")

    def connected(self) -> bool:
        return bool(self.store.anilist().get("token_enc"))

    def enabled(self) -> bool:
        return self.connected() and bool(self.store.anilist().get("tracking", True))

    def series_state(self, series_key):
        """(texte, association) pour le panneau d'informations."""
        mapping = self.store.anilist_series("map").get(series_key) or {}
        last = self.store.anilist_series("last").get(series_key) or {}
        pending = series_key in self.store.anilist_series("pending")
        if mapping.get("ignored"):
            return "Non suivie", mapping
        if mapping.get("unmatched") and not mapping.get("id"):
            return "Œuvre non trouvée : à associer", mapping
        title = mapping.get("title") or last.get("title")
        text = title or "Association automatique au prochain tome terminé"
        if pending:
            text += " · mise à jour en attente"
        elif last.get("summary"):
            text += f" · {last['summary']}"
        return text, mapping

    def _set_status(self, text):
        self.status = text
        self.statusChanged.emit(text)

    # ----- evenements -----
    def on_volumes_finished(self, paths):
        """Un ou plusieurs tomes viennent d'etre termines (lecteur ou « marquer
        comme lu ») : met a jour la file de leur serie, envoi groupe."""
        if not self.enabled():
            return
        pending = self.store.anilist_series("pending")
        for path in paths:
            info = self.series_resolver(path)
            if not info:
                continue
            key, name, volumes = info
            desired = anilist_track.desired_progress(volumes)
            pushed = (self.store.anilist_series("last").get(key) or {}).get("pushed")
            if anilist_track.is_new_progress(desired, pushed):
                pending[key] = {"name": name, "desired": desired}
        self.store.touch_anilist()
        self._debounce.start()

    def on_session_end(self, path):
        """Fin d'une seance de lecture : publie la progression de la serie."""
        self.on_volumes_finished([path])

    def associate(self, series_key, media_id=None, title=None, ignore=False):
        """Association manuelle (ou « ne pas suivre ») d'une serie."""
        amap = self.store.anilist_series("map")
        if ignore:
            amap[series_key] = {"ignored": True}
            self.store.anilist_series("pending").pop(series_key, None)
        elif media_id:
            amap[series_key] = {"id": int(media_id), "title": title, "auto": False}
            # nouvelle oeuvre associee : tout est a republier
            self.store.anilist_series("last").pop(series_key, None)
        else:
            amap.pop(series_key, None)
        self.store.touch_anilist()
        self.seriesUpdated.emit(series_key)

    def resync_series(self, series_key, path):
        """Publie maintenant l'etat d'une serie (apres une association)."""
        if path:
            self.on_volumes_finished([path])

    # ----- envoi -----
    def flush_pending(self):
        if self._worker is not None or not self.enabled():
            return
        pending = self.store.anilist_series("pending")
        if not pending:
            return
        token = self.store.anilist_token()
        if not token:
            self._set_status("Reconnectez votre compte AniList dans les préférences.")
            return
        amap = self.store.anilist_series("map")
        jobs = []
        for key, job in list(pending.items()):
            mapping = amap.get(key) or {}
            if mapping.get("ignored"):
                pending.pop(key, None)
                continue
            media_id = mapping.get("id")
            if media_id is None and mapping.get("unmatched"):
                continue   # en attente d'une association manuelle
            if media_id is None:
                media_id = anilist_track.auto_match(self.store.series_meta(key),
                                                    _min_score(job.get("desired")))
            jobs.append({"series_key": key, "name": job.get("name", key),
                         "desired": job.get("desired"), "media_id": media_id})
        if not jobs:
            return
        self._worker = _TrackWorker(token, jobs)
        self._worker.signals.done.connect(self._on_done)
        self._pool.start(self._worker)
        self._set_status("Mise à jour d'AniList…")

    def _on_done(self, results):
        self._worker = None
        pending = self.store.anilist_series("pending")
        amap = self.store.anilist_series("map")
        last = self.store.anilist_series("last")
        updated, errors = [], 0
        requeued = False
        for res in results:
            key = res["series_key"]
            if res.get("mapped"):
                amap[key] = res["mapped"]
            status = res["status"]
            if status in ("updated", "uptodate", "skipped"):
                # un tome termine pendant l'envoi a pu remplacer l'attente de
                # cette serie : elle n'est retiree que si c'est bien ce qui
                # vient d'etre publie, sinon elle repart au prochain envoi
                if (pending.get(key) or {}).get("desired") == res.get("desired"):
                    pending.pop(key, None)
                elif key in pending:
                    requeued = True
                last[key] = {"ts": time.time(), "title": res.get("title"),
                             "url": res.get("url"), "pushed": res.get("desired"),
                             "summary": res.get("summary") or last.get(key, {}).get("summary")}
                if status == "updated":
                    updated.append(f"{res.get('title')} ({res.get('summary')})")
            elif status in ("unmatched", "missing"):
                amap[key] = {"unmatched": True}
            elif status == "auth":
                self.store.set_anilist_login(None, None)
                self._set_status("AniList a refusé le jeton : reconnectez votre compte "
                                 "dans les préférences.")
                self.store.touch_anilist()
                return
            else:
                errors += 1
            self.seriesUpdated.emit(key)
        self.store.touch_anilist()
        if requeued:
            self._debounce.start()
        if updated:
            self._set_status("AniList mis à jour : " + " ; ".join(updated))
        elif errors:
            self._set_status("AniList injoignable : nouvel essai dans quelques minutes.")
        else:
            self._set_status("Liste AniList déjà à jour.")
