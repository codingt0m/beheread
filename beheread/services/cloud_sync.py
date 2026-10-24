"""Synchronisation de la lecture entre appareils par un dossier cloud (partie
Qt ; regles dans core/sync.py et core/backup.py).

Branchee comme un service de suivi (voir tracking.py) : apres chaque seance
de lecture ou tome marque « lu », au demarrage, toutes les 5 minutes et a la
fermeture, cet appareil ecrit sa sauvegarde dans le dossier et fusionne celles
des autres. Les lectures et ecritures de fichiers se font dans un thread
dedie (un fichier cloud pas encore telecharge peut bloquer le temps de son
telechargement) ; la fusion se fait sur le thread UI, comme un import manuel.
Hors ligne ou dossier injoignable, rien n'est perdu : la base locale reste la
reference et le prochain essai renverra tout.

Etat (Store.cloud_sync()) : folder, enabled, signature (contenu du dernier
fichier ecrit), seen ({fichier: empreinte de version fusionnee}), peers
({appareil: {"name", "exported", "merged"}}), last_ok.
"""

import json
import logging
import os
import threading
import time
from pathlib import Path

from PySide6.QtCore import QObject, QRunnable, QThreadPool, QTimer, Signal

from beheread.core import sync
from beheread.i18n import tr, trn
from beheread.infra.storage import Store
from beheread.services.tracking import Tracker

INTERVAL_MS = 5 * 60 * 1000
DEBOUNCE_MS = 2000


def write_text_atomic(path: Path, text: str):
    # nom temporaire propre au thread : l'envoi de fermeture peut croiser un
    # envoi encore en cours dans le thread de synchronisation
    tmp = path.with_name(f"{path.name}.{os.getpid()}-{threading.get_ident()}.tmp")
    try:
        tmp.write_text(text, encoding="utf-8")
        os.replace(tmp, path)
    finally:
        tmp.unlink(missing_ok=True)


def run_sync(folder, device_id, text, seen) -> dict:
    """Ecrit le fichier de cet appareil (si `text`) et lit ceux des autres
    appareils qui ont change depuis `seen`. Sans etat partage : appelee dans
    le thread de synchronisation."""
    folder = Path(folder)
    if not folder.is_dir():
        return {"ok": False, "missing": True}
    try:
        if text is not None:
            write_text_atomic(folder / sync.file_name(device_id), text)
        names = os.listdir(folder)
    except OSError as e:
        return {"ok": False, "error": str(e)}
    peers = []
    for name in sync.peer_files(names, device_id):
        path = folder / name
        try:
            version = sync.stamp(path.stat())
            if seen.get(name) == version:
                continue
            peers.append((name, version, Store.read_backup(path)))
        except (OSError, ValueError) as e:
            # fichier en cours d'ecriture par le client cloud, ou abime :
            # relu au prochain essai
            logging.warning("Synchronisation : %s illisible (%s)", name, e)
    return {"ok": True, "wrote": text is not None, "peers": peers}


class _Signals(QObject):
    done = Signal(object)


class _SyncWorker(QRunnable):
    def __init__(self, *args):
        super().__init__()
        self.args = args
        self.signals = _Signals()

    def run(self):
        try:
            result = run_sync(*self.args)
        except Exception as e:   # sans signal `done`, la synchro resterait bloquee
            logging.exception("Synchronisation en echec")
            result = {"ok": False, "error": str(e)}
        self.signals.done.emit(result)


class CloudSync(Tracker):
    NAME = "Synchronisation"

    # lecture d'un autre appareil fusionnee : {"progress": n, "extras": m,
    # "devices": [noms]} (la bibliotheque se rafraichit)
    synced = Signal(object)

    def __init__(self, store, parent=None):
        super().__init__(parent)
        self.store = store
        self.status = ""
        self.failed = False   # dernier essai en echec : status est un avertissement
        self._pool = QThreadPool(self)
        self._pool.setMaxThreadCount(1)
        self._worker = None
        self._pending_signature = None
        self._again = False
        self._debounce = QTimer(self)
        self._debounce.setSingleShot(True)
        self._debounce.setInterval(DEBOUNCE_MS)
        self._debounce.timeout.connect(self.sync_now)
        self._timer = QTimer(self)
        self._timer.setInterval(INTERVAL_MS)
        self._timer.timeout.connect(self.sync_now)
        self._timer.start()

    # ----- etat -----
    def state(self) -> dict:
        return self.store.cloud_sync()

    def folder(self):
        return self.state().get("folder") or None

    def connected(self) -> bool:
        return bool(self.folder())

    def enabled(self) -> bool:
        return self.connected() and bool(self.state().get("enabled", True))

    def peers(self) -> dict:
        """{appareil: {"name", "exported", "merged"}} des autres appareils deja fusionnes."""
        return dict(self.state().get("peers") or {})

    def _set_status(self, text):
        self.status = text
        self.statusChanged.emit(text)

    # ----- reglages -----
    def set_folder(self, folder):
        """Nouveau dossier (ou None) : tout y sera ecrit et relu."""
        state = self.state()
        state["folder"] = str(folder) if folder else None
        state["enabled"] = bool(folder)
        for key in ("signature", "seen", "peers", "pushed", "last_ok"):
            state.pop(key, None)
        self.failed = False
        self._set_status("")
        self.store.touch_cloud_sync()
        if folder:
            self.sync_now()

    def set_enabled(self, on: bool):
        self.state()["enabled"] = bool(on)
        self.store.touch_cloud_sync()
        if on:
            self.sync_now()

    # ----- evenements de lecture (Tracker) -----
    def on_volumes_finished(self, paths):
        if self.enabled():
            self._debounce.start()

    def on_session_end(self, path):
        if self.enabled():
            self._debounce.start()

    def flush_pending(self):
        self.sync_now()

    # ----- envoi -----
    def _payload(self):
        """(signature, texte a ecrire ou None si le fichier est a jour).
        Construit sur le thread UI : la sauvegarde lit des dictionnaires
        vivants du Store."""
        data = self.store.backup_data()
        signature = sync.signature(data)
        if signature == self.state().get("signature"):
            return signature, None
        return signature, json.dumps(data, ensure_ascii=False)

    def sync_now(self):
        if not self.enabled():
            return
        if self._worker is not None:
            self._again = True
            return
        signature, text = self._payload()
        self._pending_signature = signature
        self._worker = _SyncWorker(self.folder(), self.store.device_id(), text,
                                   dict(self.state().get("seen") or {}))
        self._worker.signals.done.connect(self._on_done)
        self._pool.start(self._worker)

    def push_on_close(self):
        """Fermeture de l'application : ecrit tout de suite le fichier de cet
        appareil (sans rien relire), pour que les autres reprennent la
        derniere seance. Un echec est seulement consigne."""
        if not self.enabled():
            return
        try:
            signature, text = self._payload()
            if text is not None:
                write_text_atomic(Path(self.folder()) / sync.file_name(self.store.device_id()),
                                  text)
                self.state().update(signature=signature, pushed=time.time())
                self.store.touch_cloud_sync()
        except OSError as e:
            logging.warning("Synchronisation a la fermeture impossible : %s", e)

    def _on_done(self, result):
        self._worker = None
        state = self.state()
        self.failed = not result.get("ok")
        if self.failed:
            if result.get("missing"):
                self._set_status(tr("Dossier introuvable (disque débranché ou application cloud "
                                    "fermée ?). Votre lecture reste enregistrée sur cet appareil "
                                    "et partira dès que le dossier sera de nouveau accessible."))
            else:
                self._set_status(tr("Synchronisation impossible : {error}",
                                    error=result.get("error", "")))
        else:
            if result.get("wrote"):
                state["signature"] = self._pending_signature
                state["pushed"] = time.time()
            seen = state.setdefault("seen", {})
            peers = state.setdefault("peers", {})
            progress = extras = 0
            devices = []
            for name, version, data in result["peers"]:
                try:
                    counts = self.store.merge_backup(data)
                except Exception:
                    # contenu valide en surface mais inattendu : ce fichier
                    # seulement est ignore (relu s'il change)
                    logging.exception("Synchronisation : fusion de %s impossible", name)
                    seen[name] = version
                    continue
                seen[name] = version
                device = data.get("device") or name
                peers[device] = {"name": data.get("device_name") or device,
                                 "exported": data.get("exported"), "merged": time.time()}
                progress += counts["progress"]
                extras += counts["extras"]
                if counts["progress"] or counts["extras"]:
                    devices.append(peers[device]["name"])
            state["last_ok"] = time.time()
            if progress or extras:
                self.synced.emit({"progress": progress, "extras": extras, "devices": devices})
                self._again = True   # le fichier de cet appareil inclut desormais leur lecture
            if progress:
                self._set_status(trn(progress, "Synchronisé · {n} tome repris de {devices}",
                                     "Synchronisé · {n} tomes repris de {devices}",
                                     devices=", ".join(devices)))
            else:
                self._set_status(tr("Synchronisé"))
        self.store.touch_cloud_sync()
        if self._again:
            self._again = False
            self._debounce.start()
