"""Empreinte de contenu d'un tome : logique pure (aucun acces disque, teste
isolement).

L'empreinte identifie un tome par son contenu et non par son chemin : la
taille du fichier et ses premiers Ko suffisent a distinguer deux tomes
differents, et restent stables quand on renomme ou deplace le fichier. La
progression, les metadonnees et le journal de lecture y sont rattaches ;
deux copies identiques (sur ce PC et sur un serveur) partagent donc tout.

Changer cette definition changerait l'identite de tous les tomes : le
prefixe « c1: » versionne le format.
"""

import hashlib

HEAD_BYTES = 65536        # octets de tete lus pour l'empreinte
PREFIX = "c1:"


def content_fingerprint(size: int, head: bytes) -> str:
    """Empreinte d'un fichier de `size` octets dont `head` est le debut
    (ses HEAD_BYTES premiers octets, ou le fichier entier s'il est plus court)."""
    h = hashlib.sha1()
    h.update(str(size).encode("ascii"))
    h.update(head[:HEAD_BYTES])
    return PREFIX + h.hexdigest()
