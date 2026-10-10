# Beheread

[![Dernière version](https://img.shields.io/github/v/release/codingt0m/beheread?label=version)](https://github.com/codingt0m/beheread/releases/latest)
[![Windows 10 et 11](https://img.shields.io/badge/Windows-10%20%7C%2011%20(64%20bits)-0078D6)](docs/INSTALLATION-WINDOWS.md)
[![macOS 13+](https://img.shields.io/badge/macOS-13%2B%20(puce%20Apple)-555555)](docs/INSTALLATION-MACOS.md)
[![Téléchargements](https://img.shields.io/github/downloads/codingt0m/beheread/total?label=t%C3%A9l%C3%A9chargements)](https://github.com/codingt0m/beheread/releases)
[![Licence PolyForm Noncommercial](https://img.shields.io/badge/licence-PolyForm%20Noncommercial-orange)](LICENSE)

**Un lecteur de mangas pour Windows et macOS, simple et hors ligne.** Beheread lit les fichiers CBZ, CBR, EPUB et PDF, range vos tomes par série et reprend chaque lecture à la page où vous l'avez laissée.

### [⬇ Télécharger Beheread](https://github.com/codingt0m/beheread/releases/latest)

<!--
Captures d'écran : déposer les images dans docs/images/ puis retirer ce commentaire.
![La bibliothèque](docs/images/bibliotheque.png)
![Le lecteur en double page](docs/images/lecteur.png)
-->

## Fonctionnalités

* **Bibliothèque par séries** : vos dossiers sont parcourus et surveillés, les tomes regroupés par série, avec recherche, tris, filtres et une bande « Continuer la lecture ».
* **Lecteur confortable** : plein écran, double page, sens de lecture manga, recadrage automatique des marges, zoom, enchaînement sur le tome suivant.
* **Progression conservée** : chaque tome reprend à la dernière page lue, même après avoir renommé ou déplacé le fichier.
* **Statistiques de lecture** : temps de lecture, pages lues, tomes terminés et régularité, par période.
* **Métadonnées** (optionnel) : auteur et date de sortie de vos tomes.
* **Suivi AniList** (optionnel) : votre liste AniList se met à jour toute seule pendant que vous lisez.
* **Sauvegarde** : export et import de la progression, pour changer d'ordinateur, y compris entre Windows et Mac.

Toutes vos données restent **sur votre ordinateur**. Seules les deux fonctions optionnelles utilisent le réseau, et uniquement si vous les activez. L'application fonctionne normalement sans connexion.

## Installation

Rien d'autre à installer : tout ce dont Beheread a besoin est inclus dans le téléchargement. Sur la page de la [dernière version](https://github.com/codingt0m/beheread/releases/latest), dans la liste **Assets** en bas de page, téléchargez le fichier de votre système :

| Système | Fichier | Guide pas à pas |
|---|---|---|
| **Windows** 10 et 11 (64 bits) | `Beheread-Setup-x.y.z.exe` (installateur, recommandé) ou `Beheread-x.y.z-windows-x64.zip` (sans installation) | [Installer sous Windows](docs/INSTALLATION-WINDOWS.md) |
| **macOS** 13 ou plus récent, Mac à puce Apple (M1 et suivants) | `Beheread-x.y.z-macos.dmg` | [Installer sous macOS](docs/INSTALLATION-MACOS.md) |

Les archives « Source code » de la même liste contiennent le code du projet : elles ne servent pas à utiliser l'application.

En bref :

* **Windows** : lancez l'installateur. Si Windows affiche « Windows a protégé votre ordinateur », cliquez sur **Informations complémentaires**, puis sur **Exécuter quand même** : Beheread n'est pas signé numériquement (un certificat est payant), ce n'est pas le signe d'un problème.
* **macOS** : ouvrez le `.dmg` et faites glisser Beheread dans **Applications**. Au premier lancement, macOS le bloque car il n'est pas signé par Apple : autorisez-le une fois dans *Réglages Système > Confidentialité et sécurité > Ouvrir quand même* ([détails](docs/INSTALLATION-MACOS.md#3-autoriser-le-premier-lancement)).

Ensuite, sur l'écran d'accueil, cliquez sur **Ajouter un dossier** et choisissez le dossier qui contient vos mangas. Ses sous-dossiers sont parcourus aussi, et vos fichiers ne sont ni déplacés ni modifiés. Double-cliquez sur une couverture pour lire ; **F1** affiche la liste des raccourcis.

L'application est la même sur les deux systèmes, et une sauvegarde (*Préférences > Données > Exporter…*) se réimporte de l'un à l'autre : la progression suit vos tomes d'un PC à un Mac.

## Lire les fichiers CBR

Les CBZ, EPUB et PDF fonctionnent sans rien d'autre. Beaucoup de fichiers `.cbr` sont en réalité des ZIP renommés : Beheread reconnaît le format réel du fichier, donc ceux-là s'ouvrent aussi sans rien installer.

Les vrais fichiers RAR ont besoin d'un outil de décompression :

* **Windows** : WinRAR ou 7-Zip, s'ils sont installés, sont détectés automatiquement ; sinon, déposez `UnRAR.exe` dans le dossier de Beheread ([détails](docs/INSTALLATION-WINDOWS.md#lire-les-fichiers-cbr)).
* **macOS** : rien à installer, l'outil fourni avec macOS suffit pour la plupart des fichiers ; pour un fichier qui résiste, installez 7-Zip ([détails](docs/INSTALLATION-MACOS.md#lire-les-fichiers-cbr)).

## Raccourcis essentiels du lecteur

| Action | Touche |
|---|---|
| Page suivante / précédente | Flèches, Espace, molette |
| Simple page / double page | D |
| Sens manga (droite à gauche) / normal | M |
| Couverture seule en double page | S |
| Recadrer les marges | R |
| Ajuster à la hauteur / à la largeur | F |
| Zoom | + / -, 0 pour réinitialiser |
| Plein écran | F11 (Mac : ⌃⌘F) |
| Retour à la bibliothèque | Échap |
| Liste de tous les raccourcis | F1 |

Sur Mac, les raccourcis avec Ctrl utilisent ⌘ (⌘F pour rechercher, ⌘, pour les réglages) ; la liste affichée par F1 montre toujours les touches de votre système. Toutes les fonctions sont détaillées dans le [guide d'utilisation](docs/GUIDE.md).

## Vérifier le téléchargement (facultatif)

Chaque version publie les sommes de contrôle de ses fichiers (`SHA256SUMS.txt` pour Windows, `SHA256SUMS-macos.txt` pour macOS). La marche à suivre est dans chaque guide : [Windows](docs/INSTALLATION-WINDOWS.md#vérifier-le-téléchargement-facultatif), [macOS](docs/INSTALLATION-MACOS.md#vérifier-le-téléchargement-facultatif).

## Dépannage

* **Avertissement de sécurité à l'installation ou au premier lancement** : voir le guide de votre système ([Windows](docs/INSTALLATION-WINDOWS.md#2-installer), [macOS](docs/INSTALLATION-MACOS.md#3-autoriser-le-premier-lancement)).
* **« Aucun outil de décompression RAR n'a été trouvé »** : voir [Lire les fichiers CBR](#lire-les-fichiers-cbr).
* **Une vignette reste grise** : l'archive est probablement corrompue ou vide ; ouvrez-la pour voir le message d'erreur détaillé.
* **Autre comportement anormal** (Beheread qui ne se lance pas, métadonnées qui n'arrivent jamais, dossier qui ne se rafraîchit plus) : consultez le journal `beheread.log`, toutes les erreurs y sont consignées. Il se trouve dans `%APPDATA%\MangaReaderPy` sous Windows, dans `~/Library/Application Support/Beheread` sous macOS.
* **Signaler un problème** : ouvrez une [issue](https://github.com/codingt0m/beheread/issues), en précisant votre système et en joignant si possible les lignes concernées de `beheread.log`.

## Documentation

* Installation pas à pas : [Windows](docs/INSTALLATION-WINDOWS.md), [macOS](docs/INSTALLATION-MACOS.md).
* [Guide d'utilisation](docs/GUIDE.md) : bibliothèque, lecteur, statistiques, métadonnées, AniList, données.
* [Notes de version](CHANGELOG.md)
* [Développement](docs/DEVELOPPEMENT.md) : lancer depuis les sources, construire, publier, structure du code, tests.

## Licence

Beheread est distribué sous [licence PolyForm Noncommercial 1.0.0](LICENSE).

* **Autorisé** : utiliser Beheread, le modifier et le partager gratuitement, pour un usage personnel ou non commercial (y compris dans une association, une école ou un organisme public).
* **Interdit** : tout usage commercial, par exemple vendre Beheread ou une version modifiée, ou l'intégrer à un produit ou service payant.

Pour un usage commercial, contactez l'auteur en ouvrant une [issue](https://github.com/codingt0m/beheread/issues).
