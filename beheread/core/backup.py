"""Sauvegarde manuelle : export et import de la progression (logique pure,
aucune dependance Qt, testee isolement).

L'export ecrit un fichier JSON avec la progression, les statistiques, les
reglages par tome/serie et les metadonnees saisies a la main. L'import le
fusionne, toutes les donnees etant indexees par empreinte de contenu (donc
valables d'un PC a l'autre pour un meme fichier, quel que soit son chemin) :
* progression : pour un tome present des deux cotes, la plus recente
  l'emporte (horodatage `ts`) ; un tome absent localement est repris ;
* statistiques : chaque appareil a sa propre section, reprise si elle est
  plus recente - importer deux fois le meme fichier ne compte rien en double ;
* tomes masques de « Continuer la lecture » : date de masquage la plus recente ;
* reglages par tome/serie et saisies manuelles : ajoutes seulement s'ils
  manquent localement (jamais d'ecrasement).
"""

import json
import os
import time
from pathlib import Path

BACKUP_FORMAT = "beheread-backup"
VERSION = 1

# reglages indexes par empreinte ou par serie, repris par une sauvegarde
# (ajoutes a l'import seulement s'ils manquent localement). Les dossiers
# sources, propres a chaque PC, n'en font pas partie.
BACKUP_SETTINGS = ("series_overrides", "series_names", "volume_direction",
                   "series_direction", "added", "pages")


def _content_keys(d):
    return {k: v for k, v in (d or {}).items()
            if isinstance(k, str) and k.startswith("c1:") and isinstance(v, dict)}


def build_backup(store_settings, progress, stats, meta_cache, dismissed, device_id,
                 device_name, now=None):
    """Contenu complet d'une sauvegarde (export manuel)."""
    return {
        "format": BACKUP_FORMAT, "version": VERSION,
        "device": device_id, "device_name": device_name,
        "exported": now if now is not None else time.time(),
        "progress": _content_keys(progress),
        "stats": {"devices": dict((stats or {}).get("devices", {}))},
        "continue_dismissed": dict(dismissed or {}),
        "settings": {k: store_settings.get(k, {}) for k in BACKUP_SETTINGS
                     if store_settings.get(k)},
        "meta_manual": {
            section: {k: v for k, v in (meta_cache or {}).get(section, {}).items()
                      if isinstance(v, dict) and v.get("source") == "manual"}
            for section in ("volume", "series")},
    }


def is_valid(data) -> bool:
    return (isinstance(data, dict) and data.get("format") == BACKUP_FORMAT
            and isinstance(data.get("version"), int) and data["version"] <= VERSION
            and isinstance(data.get("progress", {}), dict))


def merge_progress(local: dict, remote: dict) -> list:
    """Integre la progression importee (en place). Renvoie les empreintes
    modifiees."""
    changed = []
    for key, rv in _content_keys(remote).items():
        lv = local.get(key)
        if lv is None or float(rv.get("ts", 0) or 0) > float(lv.get("ts", 0) or 0):
            local[key] = dict(rv)
            changed.append(key)
    return changed


def merge_stats(local: dict, remote: dict, local_device: str) -> bool:
    """Reprend la section de chaque AUTRE appareil si elle est plus recente.
    La section de cet appareil n'est jamais ecrasee par un import."""
    changed = False
    devices = local.setdefault("devices", {})
    for dev_id, dev in (remote or {}).get("devices", {}).items():
        if dev_id == local_device or not isinstance(dev, dict):
            continue
        cur = devices.get(dev_id)
        if cur is None or float(dev.get("updated", 0)) > float(cur.get("updated", 0)):
            devices[dev_id] = dev
            changed = True
    return changed


def merge_dismissed(local: dict, remote: dict) -> bool:
    changed = False
    for key, ts in (remote or {}).items():
        if isinstance(ts, (int, float)) and ts > local.get(key, 0):
            local[key] = ts
            changed = True
    return changed


def merge_extras(settings: dict, meta_cache: dict, data: dict) -> int:
    """Reprend les reglages par tome/serie absents localement et les
    metadonnees manuelles (sans ecraser une saisie locale). Renvoie le nombre
    d'elements ajoutes."""
    added = 0
    for name, values in (data.get("settings") or {}).items():
        if name not in BACKUP_SETTINGS or not isinstance(values, dict):
            continue
        target = settings.setdefault(name, {})
        for k, v in values.items():
            if k not in target:
                target[k] = v
                added += 1
    for section, values in (data.get("meta_manual") or {}).items():
        if section not in ("volume", "series") or not isinstance(values, dict):
            continue
        target = meta_cache.setdefault(section, {})
        for k, v in values.items():
            cur = target.get(k)
            if not (isinstance(cur, dict) and cur.get("source") == "manual"):
                target[k] = v
                added += 1
    return added


def write_json_atomic(path, data):
    path = Path(path)
    tmp = path.with_name(path.name + ".tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False)
    os.replace(tmp, path)
