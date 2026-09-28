"""Configuration interne de l'application (renseignee par le developpeur,
jamais montree a l'utilisateur) et chemins de l'application.

AniList : Beheread est enregistre UNE fois comme application sur le compte
AniList du developpeur (https://anilist.co/settings/developer), avec comme
adresse de redirection exactement :

    http://127.0.0.1:51789/anilist

Le Client ID obtenu se colle ci-dessous. Il n'est pas secret : le flux utilise
(« implicit grant », recommande par AniList pour les applications qui ne
peuvent pas proteger un secret, comme une application de bureau distribuee)
n'emploie que lui. Le Client Secret n'est JAMAIS necessaire et ne doit pas
figurer ici.

Pour tester sans modifier ce fichier : variable d'environnement
BEHEREAD_ANILIST_CLIENT_ID.
"""

import os
import sys
from pathlib import Path

# facteur de resolution du cache disque des vignettes par rapport a la taille
# logique affichee : rendu net sur les ecrans haute densite. Fait partie du
# nom de fichier en cache (voir Store.thumb_path) : le modifier regenere les
# vignettes existantes.
THUMB_SCALE = 3


def app_root() -> Path:
    """Dossier de l'application : celui de Beheread.exe une fois installe,
    la racine du depot en developpement (la ou l'on peut deposer UnRAR.exe)."""
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent.parent


def resource_path(name: str) -> Path:
    """Fichier embarque (icone...) : beheread/resources/, en developpement
    comme dans l'exe (PyInstaller y recopie ce dossier)."""
    return Path(__file__).resolve().parent / "resources" / name

ANILIST_CLIENT_ID = "52145"

# port local ou le navigateur revient apres l'autorisation ; doit
# correspondre a l'adresse de redirection enregistree sur AniList
ANILIST_REDIRECT_PORT = 51789
ANILIST_REDIRECT_PATH = "/anilist"


def anilist_client_id() -> str:
    return (os.environ.get("BEHEREAD_ANILIST_CLIENT_ID") or ANILIST_CLIENT_ID).strip()


def anilist_redirect_uri() -> str:
    return f"http://127.0.0.1:{ANILIST_REDIRECT_PORT}{ANILIST_REDIRECT_PATH}"
