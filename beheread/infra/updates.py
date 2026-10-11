"""Verification des mises a jour (facultative, desactivee par defaut) : la
derniere version publiee sur GitHub est comparee a celle-ci. Rien n'est
envoye d'autre que la requete elle-meme, et rien n'est installe : un bandeau
propose simplement de telecharger la nouvelle version."""

import json
import re
import urllib.error
import urllib.request

from beheread.infra import net
from beheread.version import __version__

LATEST_URL = "https://api.github.com/repos/codingt0m/beheread/releases/latest"
RELEASES_PREFIX = "https://github.com/codingt0m/beheread/releases/"
TIMEOUT = 10
CHECK_INTERVAL = 24 * 3600   # une verification par jour au plus

_TAG = re.compile(r"^v?(\d{1,4})\.(\d{1,4})\.(\d{1,4})$")


class UpdateError(Exception):
    """Reseau, HTTP ou reponse inattendue."""


def version_tuple(text):
    """(majeur, mineur, correctif) d'un numero « 1.2.0 » ou d'un tag « v1.2.0 »
    (suffixe eventuel ignore pour la version courante : « 1.1.0-dev »), ou None."""
    match = _TAG.match((text or "").strip().split("-")[0])
    return tuple(int(x) for x in match.groups()) if match else None


def latest_release():
    """{"version": "1.2.0", "url": page de la release} de la derniere version
    publiee. Leve UpdateError (reseau, ou reponse inattendue : version ou
    adresse qui ne ressemble pas a une release de Beheread)."""
    req = urllib.request.Request(LATEST_URL, headers={
        "User-Agent": net.APP_USER_AGENT, "Accept": "application/vnd.github+json"})
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
            data = json.loads(resp.read(1_000_000).decode("utf-8"))
    except (urllib.error.URLError, OSError, ValueError) as e:
        raise UpdateError(str(e)) from e
    tag, url = (data or {}).get("tag_name"), (data or {}).get("html_url")
    if version_tuple(tag) is None or not isinstance(url, str) or not url.startswith(RELEASES_PREFIX):
        raise UpdateError("réponse inattendue de GitHub")
    return {"version": ".".join(str(x) for x in version_tuple(tag)), "url": url}


def is_newer(version, current=__version__) -> bool:
    new, cur = version_tuple(version), version_tuple(current)
    return bool(new and cur and new > cur)
