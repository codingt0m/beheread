"""Instance unique de l'application.

Sans elle, double-cliquer un second fichier dans l'explorateur lancait un
second processus : les deux gardaient progress.json en memoire et le
reecrivaient en entier, le dernier ecrivain effacant la progression de
l'autre. Desormais :

* la premiere instance prend un verrou (QLockFile, dans le dossier de
  donnees) et ouvre un canal local (QLocalServer) ;
* une instance suivante ne prend pas le verrou : elle transmet sa demande
  (ouvrir tel fichier, ou simplement « se montrer ») a la premiere par ce
  canal, puis se termine sans jamais charger les donnees.

Le verrou, et non `QLocalServer.listen`, decide qui est l'instance principale :
sous Windows, deux serveurs peuvent ecouter sur le meme nom de pipe. Un
verrou laisse par un processus plante est detecte (PID mort) et repris.
"""

import getpass
import hashlib
import json
import logging
import re
import secrets
import time
from pathlib import Path

from PySide6.QtCore import QLockFile, QObject, Signal
from PySide6.QtNetwork import QLocalServer, QLocalSocket

from beheread import platforms

NAME_FILE = "instance.name"
_NAME = re.compile(r"beheread-[0-9a-f]{24}")
CONNECT_TIMEOUT_MS = 500
CONNECT_ATTEMPTS = 6        # ~3 s : l'instance principale peut etre en plein demarrage
ACK_TIMEOUT_MS = 3000
ACK = b"ok\n"              # accuse de reception renvoye par l'instance principale


def default_server_name(folder=None) -> str:
    """Nom du canal : aleatoire, tire au premier lancement et range dans le
    dossier de donnees de l'utilisateur (`folder`), lisible de lui seul. Un
    nom calculable (empreinte du nom d'utilisateur) permettait a un autre
    compte de la machine de creer le canal avant Beheread : les pipes nommes
    de Windows sont globaux, et il aurait recu les chemins des fichiers ouverts
    (et pu repondre « ok » a leur place)."""
    if folder is None:
        from beheread.infra.storage import data_dir
        folder = data_dir()
    path = Path(folder) / NAME_FILE
    for _attempt in range(2):
        try:
            name = path.read_text(encoding="ascii").strip()
        except (OSError, ValueError):
            name = ""
        if _NAME.fullmatch(name):
            return name
        name = "beheread-" + secrets.token_hex(12)
        try:
            # creation exclusive : deux premiers lancements simultanes
            # finissent par lire le meme nom
            with open(path, "x", encoding="ascii") as f:
                f.write(name)
            return name
        except FileExistsError:
            continue   # ecrit entre-temps par l'autre lancement : on le relit
        except OSError:
            break
    logging.warning("Nom du canal d'instance non enregistre, repli sur un nom derive")
    try:
        user = getpass.getuser()
    except Exception:
        user = "user"
    return "beheread-" + hashlib.sha1(user.encode("utf-8", "replace")).hexdigest()[:24]


def encode(message: dict) -> bytes:
    return json.dumps(message, ensure_ascii=False).encode("utf-8") + b"\n"


def decode(data: bytes):
    """Message decode, ou None s'il est illisible (le canal est local, mais
    rien n'empeche un autre programme de s'y connecter : on valide)."""
    try:
        msg = json.loads(data.decode("utf-8"))
    except (ValueError, UnicodeDecodeError):
        return None
    if not isinstance(msg, dict):
        return None
    path = msg.get("open")
    if path is not None and not isinstance(path, str):
        return None
    return msg


def _allow_foreground():
    """Cede le premier plan a l'instance principale (voir
    beheread.platforms.allow_foreground)."""
    platforms.allow_foreground()


def send_to_primary(message: dict, name: str = None) -> bool:
    """Transmet `message` a l'instance principale. True seulement si celle-ci
    en a accuse reception : sans accuse, l'appelant se lance normalement
    plutot que de disparaitre sans rien ouvrir.

    (waitForBytesWritten ne suffit pas comme preuve : sous Windows, une
    ecriture dans le pipe peut se terminer immediatement, et la fonction
    repond alors False alors que le message est bien parti.)"""
    name = name or default_server_name()
    _allow_foreground()
    for _attempt in range(CONNECT_ATTEMPTS):
        sock = QLocalSocket()
        sock.connectToServer(name)
        if not sock.waitForConnected(CONNECT_TIMEOUT_MS):
            time.sleep(0.25)
            continue
        sock.write(encode(message))
        sock.flush()
        reply = bytearray()
        deadline = time.monotonic() + ACK_TIMEOUT_MS / 1000
        while ACK not in reply and time.monotonic() < deadline:
            if sock.bytesAvailable() or sock.waitForReadyRead(100):
                reply.extend(bytes(sock.readAll()))
            elif sock.state() == QLocalSocket.UnconnectedState:
                break   # connexion fermee sans accuse
        sock.abort()
        return ACK in reply
    return False


class SingleInstance(QObject):
    """Verrou + canal de l'instance principale. `messageReceived` porte les
    demandes des instances lancees ensuite ({"open": chemin} ou
    {"activate": True})."""

    messageReceived = Signal(dict)

    def __init__(self, lock_path, name: str = None, parent=None):
        super().__init__(parent)
        # nom range a cote du verrou (dossier de donnees de l'utilisateur)
        self.name = name or default_server_name(Path(lock_path).parent)
        self._lock = QLockFile(str(lock_path))
        # 0 : un verrou n'est jamais perime par son age (l'application reste
        # ouverte des heures), seulement si son processus n'existe plus
        self._lock.setStaleLockTime(0)
        self._server = None
        self._buffers = {}

    def acquire(self) -> bool:
        """True si ce processus devient l'instance principale."""
        if not self._lock.tryLock(0):
            return False
        self._server = QLocalServer(self)
        self._server.setSocketOptions(QLocalServer.UserAccessOption)
        QLocalServer.removeServer(self.name)   # socket orphelin d'un plantage (hors Windows)
        if not self._server.listen(self.name):
            logging.warning("Canal d'instance unique indisponible : %s",
                            self._server.errorString())
        self._server.newConnection.connect(self._on_new_connection)
        return True

    def release(self):
        if self._server is not None:
            self._server.close()
        self._lock.unlock()

    def _on_new_connection(self):
        while self._server.hasPendingConnections():
            sock = self._server.nextPendingConnection()
            self._buffers[sock] = bytearray()
            sock.readyRead.connect(lambda s=sock: self._on_ready(s))
            sock.disconnected.connect(lambda s=sock: self._on_disconnected(s))
            self._on_ready(sock)   # donnees peut-etre deja arrivees

    def _on_ready(self, sock):
        buf = self._buffers.get(sock)
        if buf is None:
            return
        buf.extend(bytes(sock.readAll()))
        if b"\n" not in buf:
            if len(buf) > 64 * 1024:   # message anormal : on coupe
                self._drop(sock)
            return
        line = bytes(buf).split(b"\n", 1)[0]
        msg = decode(line)
        if msg is None:
            self._drop(sock)
            logging.warning("Message d'instance illisible ignore")
            return
        sock.write(ACK)          # accuse reception avant de traiter la demande
        sock.flush()
        self._drop(sock)
        self.messageReceived.emit(msg)

    def _on_disconnected(self, sock):
        self._on_ready(sock)   # dernier morceau eventuel
        self._drop(sock)

    def _drop(self, sock):
        if self._buffers.pop(sock, None) is not None:
            sock.disconnectFromServer()
            sock.deleteLater()
