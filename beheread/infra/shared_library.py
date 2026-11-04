"""Donnees de bibliotheque partagees par un serveur Beheread.

Les corrections que l'administrateur apporte a la bibliotheque (series,
tomes virtuels, metadonnees, couvertures, sens de lecture) sont gardees par le
serveur dans sa LibraryStore et donnees a chaque client avec le catalogue.
Le serveur fait foi : chaque client les recopie dans sa propre LibraryStore,
qui sert de cache de la bibliotheque du serveur.

Une section par type de donnee, chacune un dictionnaire cle -> valeur au
format de LibraryStore (cle : empreinte de contenu d'un tome, cle de serie
normalisee ou identifiant de tome virtuel). export() les lit, apply() les
recopie ; apply() ne retire que ce que le serveur avait lui-meme donne et
qu'il ne donne plus (les corrections propres aux dossiers locaux du client
ne sont jamais touchees).

Les couvertures choisies parmi les images de l'ordinateur ne voyagent pas
ici (fichiers) : le serveur les sert par sa propre couverture.
"""

import json

# section -> ou elle vit dans LibraryStore : ("repo", depot) pour un depot a
# une ligne par cle, ("settings", nom) pour un dictionnaire des reglages,
# ("meta", "volume" | "series") pour le cache des metadonnees
SECTIONS = {
    "overrides": ("repo", "overrides"),               # empreinte -> serie forcee
    "directions": ("repo", "directions"),             # empreinte -> sens d'un tome seul
    "volume_meta": ("meta", "volume"),                # empreinte -> metadonnees
    "series_meta": ("meta", "series"),                # serie -> metadonnees
    "series_names": ("settings", "series_names"),     # serie -> nom affiche
    "series_published": ("settings", "series_published"),
    "series_nature": ("settings", "series_nature"),
    "series_direction": ("settings", "series_direction"),
    "virtual_volumes": ("settings", "virtual_volumes"),
    "virtual_dismissed": ("settings", "virtual_dismissed"),
    "chapter_ranges_manual": ("settings", "chapter_ranges_manual"),
    "covers": ("settings", "covers"),                 # empreinte -> {"page": n}
}
MAX_VALUE_BYTES = 64 * 1024
RECEIVED = "shared_received"   # reglage : {serveur: {section: [cles]}}


def _source(store, section) -> dict:
    where, name = SECTIONS[section]
    if where == "repo":
        return store._repos[name].data
    if where == "meta":
        return store.meta_cache.setdefault(name, {})
    value = store.settings.get(name)
    return value if isinstance(value, dict) else {}


def shareable(section, key, value) -> bool:
    """Ce qui peut partir vers le serveur (ou en revenir) : pas les
    metadonnees que le serveur a lui-meme donnees, pas les couvertures
    tirees d'une image de l'ordinateur, rien d'anormalement gros."""
    if section not in SECTIONS or not isinstance(key, str) or not key or len(key) > 300:
        return False
    if section == "volume_meta" and isinstance(value, dict) and value.get("source") == "server":
        return False
    if section == "covers" and not (isinstance(value, dict) and isinstance(value.get("page"), int)):
        return False
    try:
        return len(json.dumps(value, ensure_ascii=False)) <= MAX_VALUE_BYTES
    except (TypeError, ValueError):
        return False


def value(store, section, key):
    """Valeur actuelle de `key` dans la section, ou None (absente)."""
    return _source(store, section).get(key)


def export(store) -> dict:
    """Toutes les donnees partageables de la LibraryStore."""
    out = {}
    for section in SECTIONS:
        items = {k: v for k, v in _source(store, section).items() if shareable(section, k, v)}
        if items:
            out[section] = items
    return out


def _write(store, section, key, val):
    """Ecrit (ou retire, val None) une valeur ; True si elle a change."""
    where, name = SECTIONS[section]
    if where == "settings":
        data = store.settings.get(name)
        if not isinstance(data, dict):
            if val is None:
                return False
            data = store.settings[name] = {}
    else:
        data = _source(store, section)
    if val is None:
        if key not in data:
            return False
        del data[key]
    else:
        if data.get(key) == val:
            return False
        data[key] = val
    if where == "repo":
        store._schedule(name, key)
    elif where == "meta":
        store._schedule("meta")
    else:
        store._schedule("settings")
    if section == "overrides":
        store.invalidate_key_memo()
    if section == "covers":
        try:
            store.thumb_path(key).unlink(missing_ok=True)   # vignette regeneree
        except (OSError, TypeError, ValueError):
            pass
    return True


def apply(store, server_id, shared, skip=None) -> bool:
    """Recopie les donnees `shared` (format d'export) du serveur `server_id`
    dans la LibraryStore. Retire ce que ce serveur avait donne et ne donne
    plus. `skip(section, cle)` : vrai pour une cle a laisser telle quelle
    (correction locale pas encore envoyee). True si quelque chose a change."""
    if not isinstance(shared, dict):
        return False
    received_all = store.settings.get(RECEIVED)
    if not isinstance(received_all, dict):
        received_all = store.settings[RECEIVED] = {}
    before = received_all.get(server_id) if isinstance(received_all.get(server_id), dict) else {}
    now = {}
    changed = False
    for section in SECTIONS:
        items = shared.get(section)
        items = items if isinstance(items, dict) else {}
        kept = []
        for key, val in items.items():
            if not shareable(section, key, val):
                continue
            kept.append(key)
            if skip is not None and skip(section, key):
                continue
            changed |= _write(store, section, key, val)
        for key in set(before.get(section) or ()) - set(kept):
            if skip is not None and skip(section, key):
                continue
            changed |= _write(store, section, key, None)
        if kept:
            now[section] = sorted(kept)
    if now != before:
        received_all[server_id] = now
        store._schedule("settings")
    return changed
