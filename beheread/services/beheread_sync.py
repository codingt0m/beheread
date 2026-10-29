"""Synchronisation d'un profil avec un serveur Beheread (cross-progression).

Dans les deux sens, avec les regles de core/profile_sync.py (celles du
serveur et de Beheread Web) :

* vers le serveur : chaque action de ce lecteur sur un tome identifie par
  son empreinte (page tournee, tome termine ou remis a zero, seance du
  journal, masquage de « Continuer la lecture ») devient un evenement, range
  dans une file gardee en base (rien n'est perdu hors ligne ni a la
  fermeture). La file part toutes les 5 s pendant une lecture, tout de suite
  en fin de seance, et des le retour de la connexion. Les tomes des dossiers
  locaux en font partie : le serveur accepte les empreintes qu'il ne connait
  pas (copies presentes seulement sur ce PC) ;
* depuis le serveur : le flux SSE du profil signale chaque changement ; le
  desktop lit alors les changements depuis son curseur (progression et
  masquages des autres appareils, nouveau journal d'un appareil, bibliotheque
  modifiee). Sans flux (coupure, proxy), les changements sont demandes
  toutes les minutes.

Conflits : la plus recente action l'emporte. Une progression venue d'un autre
appareil garde la page lue ici auparavant (« before ») : a l'ouverture du
tome, le lecteur y saute et propose d'y revenir (bandeau de reprise).

Un serveur qui exige une version plus recente de Beheread suspend tout
(etat « update ») : la file attend la mise a jour.
"""

import logging
import threading
import time

from PySide6.QtCore import QObject, QThreadPool, QTimer, Signal

from beheread.core import fingerprint
from beheread.core.profile_sync import MAX_BATCH, new_event_id
from beheread.infra.servers import ServerError, UpdateRequired
from beheread.services.jobs import JobRunner

CONNECTING, ONLINE, OFFLINE, UPDATE = "connecting", "online", "offline", "update"

FLUSH_MS = 5000             # envoi regroupe pendant une lecture
RETRY_MS = 30 * 1000        # nouvel essai apres un echec d'envoi
POLL_MS = 60 * 1000         # sans flux SSE : changements demandes regulierement
PULL_DELAY_MS = 300         # changements signales en rafale : une seule lecture
BATCH = 200                 # evenements par envoi (le serveur en accepte MAX_BATCH)
MAX_QUEUE = 5000            # au-dela, les plus anciens sont oublies (jamais atteint en pratique)
STREAM_BACKOFF = (5, 10, 20, 40, 60)   # secondes avant de rouvrir le flux

assert BATCH <= MAX_BATCH


def is_fingerprint(key) -> bool:
    return isinstance(key, str) and key.startswith(fingerprint.PREFIX)


class BeheReadSync(QObject):
    """Synchronisation d'un serveur Beheread (un par serveur configure).
    Methodes et signaux sur le thread UI ; le reseau dans ses taches."""

    stateChanged = Signal()          # connexion, profil, version exigee
    progressChanged = Signal(str)    # empreinte dont la progression vient d'ailleurs
    libraryChanged = Signal()        # bibliotheque du serveur modifiee
    journalChanged = Signal()        # journal d'un autre appareil recu
    pending = Signal(int)            # evenements en attente d'envoi
    _streamEvent = Signal(str, str)  # flux SSE (thread du flux -> thread UI)
    _streamDown = Signal()

    def __init__(self, store, client, parent=None):
        super().__init__(parent)
        self.store = store
        self.client = client
        self.server_id = client.config.id
        self.state = CONNECTING
        self.error = ""
        self.update = None           # UpdateRequired du serveur, ou None
        self.profile = {}            # profil de cet appareil (nom, couleur, avatar)
        self._jobs = JobRunner(QThreadPool(self))
        self._jobs.pool.setMaxThreadCount(2)
        self._sending = None         # identifiants de l'envoi en cours
        self._pulling = False
        self._pull_again = False
        self._started = False
        self._stop = threading.Event()
        self._stream_thread = None
        self._stream_up = False

        self._flush_timer = QTimer(self, singleShot=True, interval=FLUSH_MS)
        self._flush_timer.timeout.connect(self.flush)
        self._retry_timer = QTimer(self, singleShot=True, interval=RETRY_MS)
        self._retry_timer.timeout.connect(self._reconnect)
        self._poll_timer = QTimer(self, interval=POLL_MS)
        self._poll_timer.timeout.connect(self._poll)
        self._pull_timer = QTimer(self, singleShot=True, interval=PULL_DELAY_MS)
        self._pull_timer.timeout.connect(self.pull)
        self._streamEvent.connect(self._on_stream_event)
        self._streamDown.connect(self._on_stream_down)
        store.sync_listeners.append(self._on_store)

    # ----- etat garde en base
    @property
    def _state(self) -> dict:
        return self.store.sync_state(self.server_id)

    @property
    def queue(self) -> list:
        return self._state.setdefault("queue", [])

    @property
    def device_id(self) -> str:
        """Identifiant de cet ordinateur sur le serveur ("" avant la connexion)."""
        return self._state.get("device", "")

    def device_name(self, device_id) -> str:
        return (self._state.get("devices") or {}).get(device_id, "")

    def _save(self):
        self.store.save_sync_state()
        self.pending.emit(len(self.queue))

    # ----- cycle de vie
    def start(self):
        """Connexion : version, profil, rattrapage des changements, puis
        flux en temps reel et envoi de la file."""
        if self._started:
            return
        self._started = True
        self._catch_up()
        self._connect()

    def stop(self):
        """Arret (serveur retire ou desactive, fermeture). La file reste en base."""
        self._started = False
        self._stop.set()
        for timer in (self._flush_timer, self._retry_timer, self._poll_timer, self._pull_timer):
            timer.stop()
        if self._on_store in self.store.sync_listeners:
            self.store.sync_listeners.remove(self._on_store)
        self.store.save_sync_state()

    def _set_state(self, state, error=""):
        if (state, error) != (self.state, self.error):
            self.state, self.error = state, error
            self.stateChanged.emit()

    def _connect(self):
        client = self.client

        def work():
            client.version()
            return client.me()
        self._jobs.run(work, self._on_connected)

    def _on_connected(self, me, err):
        if not self._started:
            return
        if err is not None:
            self._failed(err)
            return
        self.update = None
        state = self._state
        device = me.get("device") if isinstance(me.get("device"), str) else ""
        if device and device != state.get("device"):
            state["device"] = device
        state["devices"] = {d.get("id"): d.get("name") or "" for d in me.get("devices") or []
                            if isinstance(d, dict) and isinstance(d.get("id"), str)}
        self.profile = me.get("profile") if isinstance(me.get("profile"), dict) else {}
        state["profile"] = self.profile
        self._save()
        self._set_state(ONLINE)
        if state.get("cursor"):
            self.pull()
        else:
            self._load_snapshot()
        self._load_journal()
        self._start_stream()
        self.flush()

    def _failed(self, err):
        """Echec d'une requete : hors ligne (nouvel essai plus tard) ou
        mise a jour exigee (tout attend)."""
        if isinstance(err, UpdateRequired):
            self.update = err
            self._set_state(UPDATE, str(err))
            return
        if not isinstance(err, ServerError):
            logging.warning("Synchronisation avec %s en echec", self.server_id, exc_info=err)
        self._set_state(OFFLINE, str(err) if isinstance(err, ServerError) else "")
        if self._started and not self._retry_timer.isActive():
            self._retry_timer.start()

    def _reconnect(self):
        if not self._started or self.state == UPDATE:
            return
        if self.state != ONLINE:
            self._connect()
        else:
            self.flush()

    def retry(self):
        """Nouvel essai demande (mise a jour faite, bouton « Actualiser »)."""
        if not self._started:
            return
        self.update = None
        if self.state != ONLINE:
            self._set_state(CONNECTING)
            self._connect()
        else:
            self.pull()
            self.flush()

    # ----- envoi
    def _catch_up(self):
        """Progression de ce lecteur modifiee sans synchronisation en marche
        (premiere connexion de cet ordinateur, serveurs desactives un temps) :
        elle rejoint la file. La plus recente l'emporte sur le serveur, rien
        n'y est donc ecrase a tort. Ensuite, chaque action passe par _on_store."""
        state = self._state
        since = float(state.get("watched_since") or 0)
        for key, entry in list(self.store.progress.items()):
            if (is_fingerprint(key) and isinstance(entry, dict) and "device" not in entry
                    and float(entry.get("ts") or 0) > since):
                self._enqueue_progress(key, entry)
        state["watched_since"] = time.time()
        self._save()

    def _enqueue_progress(self, key, entry):
        queue = self.queue
        sending = self._sending or set()
        # une seule progression en attente par tome : la plus recente
        queue[:] = [e for e in queue
                    if not (e.get("type") == "progress" and e.get("fp") == key
                            and e.get("id") not in sending)]
        if entry is None:   # progression effacee : retour au debut
            event = {"type": "progress", "fp": key, "page": 0, "total": 0,
                     "finished": False, "ts": time.time()}
        else:
            event = {"type": "progress", "fp": key, "page": int(entry.get("page", 0)),
                     "total": int(entry.get("total", 0)), "finished": bool(entry.get("finished")),
                     "ts": float(entry.get("ts") or time.time())}
        self._push(event)

    def _push(self, event):
        # l'appareil est celui du jeton : le serveur remplace ce champ
        event.update(id=new_event_id(), device="desktop")
        queue = self.queue
        queue.append(event)
        if len(queue) > MAX_QUEUE:
            del queue[:len(queue) - MAX_QUEUE]

    def _on_store(self, kind, key, data):
        """Action de ce lecteur (voir ProfileStore.sync_listeners)."""
        if not is_fingerprint(key):
            return
        if kind == "progress":
            self._enqueue_progress(key, data)
        elif kind == "journal":
            row = dict(data, fp=key)
            self._push({"type": "journal", "rows": [row], "ts": time.time()})
        elif kind == "dismiss":
            self._push({"type": "dismiss", "target": key, "ts": float(data)})
        else:
            return
        self._save()
        if self._started and not self._flush_timer.isActive():
            self._flush_timer.start()

    def flush(self):
        """Envoie la file (par paquets) si la connexion le permet."""
        if not self._started:
            return   # arretee (et peut-etre deja detruite cote Qt)
        self._flush_timer.stop()
        if self.state != ONLINE or self._sending is not None:
            return
        batch = [dict(e) for e in self.queue[:BATCH]]
        if not batch:
            return
        self._sending = {e["id"] for e in batch}
        client = self.client
        self._jobs.run(lambda: client.send_events(batch), self._on_sent)

    def flush_now(self):
        """Fin de seance : envoi immediat (sans attendre les 5 s)."""
        self.flush()

    def _on_sent(self, result, err):
        sent, self._sending = self._sending or set(), None
        if err is not None:
            self._failed(err)
            return
        done = set(result.get("accepted") or ()) | set(result.get("rejected") or ())
        for reason in (result.get("rejected") or {}).values():
            logging.warning("Evenement refuse par le serveur : %s", reason)
        # ce que le serveur n'a ni accepte ni refuse repartira au prochain envoi
        self.queue[:] = [e for e in self.queue if e.get("id") not in (done & sent)]
        self._save()
        if self.queue and done & sent:
            self.flush()

    # ----- reception
    def _load_snapshot(self):
        client = self.client
        self._jobs.run(client.profile, self._on_snapshot)

    def _on_snapshot(self, snap, err):
        if err is not None:
            self._failed(err)
            return
        for key, value in (snap.get("progress") or {}).items():
            self._apply_progress(key, value, snapshot=True)
        for key, value in (snap.get("dismissed") or {}).items():
            if is_fingerprint(key) and isinstance(value, dict):
                self.store.apply_remote_dismiss(key, float(value.get("ts") or 0))
        cursor = snap.get("cursor")
        if isinstance(cursor, int):
            self._state["cursor"] = cursor
        self._save()
        self.pull()   # ce qui est arrive entre-temps, et la bibliotheque

    def pull(self):
        """Lit les changements depuis le curseur (signales par le flux)."""
        if not self._started:
            return
        self._pull_timer.stop()
        if self.state != ONLINE:
            return
        if self._pulling:
            self._pull_again = True
            return
        self._pulling = True
        since = int(self._state.get("cursor") or 0)
        library = int(self._state.get("library", -1))
        client = self.client
        self._jobs.run(lambda: client.changes(since, library), self._on_changes)

    def _on_changes(self, result, err):
        self._pulling = False
        if err is not None:
            self._failed(err)
            return
        state = self._state
        if result.get("reload"):
            state["cursor"] = 0
            self._save()
            self._load_snapshot()
            return
        journal = set()
        for change in result.get("changes") or ():
            if not isinstance(change, dict):
                continue
            repo, key, value = change.get("repo"), change.get("key"), change.get("value")
            if change.get("feed") == "library":
                self.libraryChanged.emit()
            elif repo == "progress":
                self._apply_progress(key, value)
            elif repo == "dismissed" and is_fingerprint(key) and isinstance(value, dict):
                self.store.apply_remote_dismiss(key, float(value.get("ts") or 0))
            elif repo == "journal" and isinstance(key, str) and key != self.device_id:
                journal.add(key)
        cursor = result.get("cursor") or {}
        more = isinstance(cursor.get("profile"), int) and \
            cursor["profile"] > int(state.get("cursor") or 0) and \
            len(result.get("changes") or ()) >= 1000
        if isinstance(cursor.get("profile"), int):
            state["cursor"] = cursor["profile"]
        if isinstance(cursor.get("library"), int):
            if state.get("library", -1) < 0 and cursor["library"] >= 0:
                self.libraryChanged.emit()   # premiere lecture : liste a jour
            state["library"] = cursor["library"]
        self._save()
        for device in journal:
            self._load_journal(device)
        if more or self._pull_again:
            self._pull_again = False
            self.pull()

    def _apply_progress(self, key, value, snapshot=False):
        """Progression du serveur pour ce tome, si elle est plus recente."""
        if not is_fingerprint(key) or not isinstance(value, dict):
            return
        try:
            page, total = int(value.get("page", 0)), int(value.get("total", 0))
            ts = float(value.get("ts") or 0)
        except (TypeError, ValueError):
            return
        device = value.get("device") if isinstance(value.get("device"), str) else ""
        mine = bool(device) and device == self.device_id
        if mine and not snapshot:
            return   # notre propre action, deja connue ici
        local = self.store.progress.get(key)
        if isinstance(local, dict) and float(local.get("ts") or 0) >= ts:
            return
        finished = bool(value.get("finished"))
        if page == 0 and total == 0 and not finished:
            self.store.apply_remote_removal(key)
        elif mine:
            self.store.apply_remote_progress(key, page, total, finished, ts)
        else:
            # page lue ici avant cette reprise : celle d'une reprise
            # precedente pas encore vue, sinon la derniere lue sur ce PC
            if isinstance(local, dict):
                before = local.get("before") if "device" in local else local.get("page", 0)
            else:
                before = 0
            self.store.apply_remote_progress(key, page, total, finished, ts, device, before)
        self.progressChanged.emit(key)

    def _load_journal(self, device=""):
        client = self.client
        self._jobs.run(lambda: client.journal(device), self._on_journal)

    def _on_journal(self, devices, err):
        if err is not None:
            if not isinstance(err, ServerError) or err.status != 404:
                self._failed(err)
            return   # serveur sans journal partage : statistiques locales seulement
        mine = {self.store.device_id(), self.device_id}
        sections = {d: s for d, s in devices.items()
                    if isinstance(d, str) and d not in mine and isinstance(s, dict)}
        if sections:
            self.store.reading_log.replace_devices(sections)
            self.journalChanged.emit()

    # ----- flux en temps reel
    def _start_stream(self):
        if self._stream_thread is not None and self._stream_thread.is_alive():
            return
        self._stop = threading.Event()
        stop, client = self._stop, self.client

        def loop():
            failures = 0
            while not stop.is_set():
                try:
                    client.listen(self._stream_event_from_thread, stop)
                    failures = 0
                except Exception as e:   # coupure, serveur arrete, jeton revoque
                    if stop.is_set():
                        return
                    logging.info("Flux du serveur Beheread interrompu : %s", e)
                    self._streamDown.emit()
                    if isinstance(e, ServerError) and e.status in (401, 403):
                        return   # appareil retire : plus la peine d'insister
                stop.wait(STREAM_BACKOFF[min(failures, len(STREAM_BACKOFF) - 1)])
                failures += 1

        self._stream_thread = threading.Thread(target=loop, name="beheread-sync-stream",
                                               daemon=True)
        self._stream_thread.start()

    def _stream_event_from_thread(self, name, data):
        self._streamEvent.emit(name, data)

    def _on_stream_event(self, name, _data):
        if not self._started:
            return
        self._stream_up = True
        self._poll_timer.stop()
        if name == "hello":
            # (re)connexion : ce qui a pu etre manque, et la file en attente
            if self.state != ONLINE:
                self._retry_timer.stop()
                self._connect()
                return
            self.pull()
            self.flush()
        elif name == "change":
            self._pull_timer.start()

    def _on_stream_down(self):
        self._stream_up = False
        if self._started and not self._poll_timer.isActive():
            self._poll_timer.start()

    def _poll(self):
        if self.state == ONLINE:
            self.pull()
            self.flush()
        else:
            self._reconnect()

    @property
    def live(self) -> bool:
        """Flux en temps reel ouvert."""
        return self._stream_up
