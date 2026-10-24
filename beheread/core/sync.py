"""Synchronisation par dossier cloud (logique pure, aucune dependance Qt).

L'utilisateur choisit un dossier synchronise par iCloud Drive, OneDrive,
Dropbox... le meme sur chacun de ses appareils. Chaque appareil y ecrit SA
sauvegarde (voir backup.py) dans un fichier a son nom, et fusionne celles des
autres comme un import manuel. Personne n'ecrit dans le fichier d'un autre :
les clients cloud n'ont jamais deux versions d'un meme fichier a reconcilier
(pas de « copie en conflit »), et la fusion de backup.py est idempotente
(relire un fichier deja fusionne ne change rien).
"""

import hashlib
import json
import re
import time

from beheread.i18n import tr, trn

PREFIX = "beheread-sync-"
# identifiant d'appareil : uuid4().hex (voir Store.device_id). Les copies en
# conflit ou temporaires d'un client cloud (« ... (1).json », « .tmp ») ne
# correspondent pas et sont ignorees.
_FILE_RE = re.compile(r"^beheread-sync-([0-9a-f]{32})\.json$")


def file_name(device_id: str) -> str:
    return f"{PREFIX}{device_id}.json"


def peer_files(names, device_id: str) -> list:
    """Fichiers de synchronisation des AUTRES appareils parmi `names`."""
    return sorted(n for n in names
                  if (m := _FILE_RE.match(n)) and m.group(1) != device_id)


def stamp(st) -> list:
    """Empreinte de version d'un fichier (date de modification, taille) :
    un fichier inchange depuis la derniere fusion n'est pas relu."""
    return [st.st_mtime_ns, st.st_size]


def signature(data: dict) -> str:
    """Empreinte du contenu d'une sauvegarde, hors date d'export : rien n'est
    reecrit dans le dossier (ni renvoye par le client cloud) tant que la
    lecture n'a pas change."""
    body = {k: v for k, v in data.items() if k != "exported"}
    text = json.dumps(body, sort_keys=True, ensure_ascii=False, default=str)
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def ago(ts, now=None) -> str:
    """Moment d'une synchronisation, relatif a maintenant (preferences)."""
    if not ts:
        return tr("jamais")
    elapsed = max(0.0, (now if now is not None else time.time()) - float(ts))
    if elapsed < 60:
        return tr("à l'instant")
    if elapsed < 3600:
        return trn(int(elapsed // 60), "il y a {n} min", "il y a {n} min")
    if elapsed < 86400:
        return trn(int(elapsed // 3600), "il y a {n} h", "il y a {n} h")
    return tr("le {date}", date=time.strftime("%d/%m/%Y", time.localtime(float(ts))))
