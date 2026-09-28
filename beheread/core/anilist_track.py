"""Suivi AniList : logique pure de decision (aucune dependance Qt ni reseau,
testee isolement). Elle ecrit sur le compte de l'utilisateur, d'ou des regles
volontairement prudentes :

* Beheread ne fait qu'AJOUTER : il ne supprime jamais une entree, ne fait
  jamais reculer une progression et ne touche a aucun autre champ (note,
  commentaires, dates, relectures...). Toute mise a jour passe par
  is_additive, verifiee une seconde fois par anilist.save_entry ;
* une entree « terminee », « abandonnee », « en pause » ou « en relecture »
  n'est jamais modifiee : c'est un choix de l'utilisateur ;
* une serie n'est associee automatiquement a une oeuvre AniList que si le
  titre trouve ressemble vraiment au nom cherche (sinon, association
  manuelle depuis le panneau d'informations).
"""

AUTO_MATCH_MIN_SCORE = 0.6
UNTOUCHABLE = {"COMPLETED", "DROPPED", "PAUSED", "REPEATING"}

# seuls champs que Beheread ecrit, et seules transitions de statut permises
# (depuis « absente de la liste » (None) ou « a lire » vers « en cours »,
# puis vers « terminee » quand le dernier tome connu d'AniList est lu)
WRITABLE_FIELDS = {"status", "progress", "progressVolumes"}
ALLOWED_STATUS = {
    None: {"CURRENT", "COMPLETED"},
    "PLANNING": {"CURRENT", "COMPLETED"},
    "CURRENT": {"COMPLETED"},
}


def desired_progress(volumes):
    """Progression a publier pour une serie, d'apres ses tomes :
    `volumes` = [(numero, nature, termine)] (nature : "volume", "bare" ou
    "chapter", cf. series.parse_series_ex). Renvoie {"volumes": n,
    "chapters": m} (cles absentes si rien de termine), ou None.

    On publie le plus grand numero TERMINE : lire le tome 5 apres le 3 compte
    comme « 5 tomes lus », comme sur AniList."""
    best_vol, best_ch = 0, 0
    for number, kind, finished in volumes:
        if not finished or number is None:
            continue
        n = int(number)
        if kind == "chapter":
            best_ch = max(best_ch, n)
        else:
            best_vol = max(best_vol, n)
    out = {}
    if best_vol:
        out["volumes"] = best_vol
    if best_ch:
        out["chapters"] = best_ch
    return out or None


def is_new_progress(desired, pushed) -> bool:
    """Vrai si `desired` depasse ce qui a deja ete publie pour la serie
    (`pushed`, meme forme, ou None) : sinon, inutile d'interroger AniList."""
    if not desired:
        return False
    pushed = pushed or {}
    return any(desired.get(k, 0) > pushed.get(k, 0) for k in ("volumes", "chapters"))


def plan_update(desired, media):
    """Changements a envoyer (dict pour save_entry) ou None si rien a faire.
    `media` : resultat de anilist.media_entry (avec `entry` eventuellement None)."""
    if not desired or not media:
        return None
    entry = media.get("entry") or {}
    status = entry.get("status")
    if status in UNTOUCHABLE:
        return None
    changes = {}
    vols = desired.get("volumes")
    if vols and vols > (entry.get("progressVolumes") or 0):
        changes["progressVolumes"] = vols
    chs = desired.get("chapters")
    if chs and chs > (entry.get("progress") or 0):
        changes["progress"] = chs
    if not changes:
        return None
    total_vols = media.get("volumes")
    total_chs = media.get("chapters")
    done = ((total_vols and changes.get("progressVolumes", 0) >= total_vols)
            or (total_chs and changes.get("progress", 0) >= total_chs))
    if done:
        changes["status"] = "COMPLETED"
    elif status in (None, "PLANNING"):
        changes["status"] = "CURRENT"
    return changes


def is_additive(changes, entry) -> bool:
    """Garde-fou final : vrai seulement si `changes` ne fait qu'ajouter par
    rapport a l'entree AniList actuelle `entry` (None si la serie n'est pas
    dans la liste) - champs autorises uniquement, progression jamais en
    baisse, transition de statut permise, entree protegee jamais touchee."""
    if not changes or not set(changes) <= WRITABLE_FIELDS:
        return False
    entry = entry or {}
    status = entry.get("status")
    if status in UNTOUCHABLE:
        return False
    for field in ("progress", "progressVolumes"):
        if field in changes:
            value = changes[field]
            if not isinstance(value, int) or value < (entry.get(field) or 0):
                return False
    if "status" in changes and changes["status"] != status:
        if changes["status"] not in ALLOWED_STATUS.get(status, set()):
            return False
    return True


def auto_match(search_result):
    """Identifiant AniList a retenir automatiquement pour une serie, ou None
    si le resultat de recherche n'est pas assez sur."""
    if not search_result or not search_result.get("anilist_id"):
        return None
    if (search_result.get("match_score") or 0) < AUTO_MATCH_MIN_SCORE:
        return None
    return int(search_result["anilist_id"])


def describe(changes) -> str:
    """Resume lisible d'une mise a jour, pour l'interface."""
    parts = []
    if "progressVolumes" in changes:
        parts.append(f"{changes['progressVolumes']} tome(s) lu(s)")
    if "progress" in changes:
        parts.append(f"{changes['progress']} chapitre(s) lu(s)")
    if changes.get("status") == "COMPLETED":
        parts.append("série terminée")
    return ", ".join(parts)
