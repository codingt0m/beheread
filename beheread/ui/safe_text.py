"""Affichage sans interpretation HTML des textes venus de l'exterieur.

Qt affiche comme du HTML tout texte qui *ressemble* a du HTML (format
« AutoText » des QLabel, des infobulles et des boites de message). Or titres,
auteurs, noms de fichiers et messages d'erreur viennent de sources non
fiables : ComicInfo.xml d'une archive telechargee, reponses de MangaDex,
AniList ou de la BnF, sauvegarde importee, noms des entrees d'une archive.
Une balise <img src="file://serveur/partage/x.png"> y ferait lire un fichier
par Qt : sous Windows, une connexion SMB vers un serveur choisi par
l'attaquant (fuite du hash NTLM de la session, ou simple « pixel espion »).

* labels : `label.setTextFormat(Qt.PlainText)` ;
* infobulles et boites de message (les appels statiques de QMessageBox n'ont
  pas de reglage de format) : `plain(texte)`.
"""

import html


def plain(text) -> str:
    """`text` affiche litteralement par Qt. Sans « < », Qt ne le prend pas
    pour du HTML : il est renvoye tel quel. Sinon, il est echappe dans un
    document HTML qui conserve sauts de ligne et espaces."""
    text = "" if text is None else str(text)
    if "<" not in text:
        return text
    return ('<qt><span style="white-space:pre-wrap">'
            + html.escape(text, quote=False) + "</span></qt>")
