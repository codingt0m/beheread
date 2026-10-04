# Beheread

[![Dernière version](https://img.shields.io/github/v/release/codingt0m/beheread?label=version)](https://github.com/codingt0m/beheread/releases/latest)
[![Windows 10 et 11](https://img.shields.io/badge/Windows-10%20%7C%2011%20(64%20bits)-0078D6)](https://github.com/codingt0m/beheread/releases/latest)
[![Téléchargements](https://img.shields.io/github/downloads/codingt0m/beheread/total?label=t%C3%A9l%C3%A9chargements)](https://github.com/codingt0m/beheread/releases)
[![Licence PolyForm Noncommercial](https://img.shields.io/badge/licence-PolyForm%20Noncommercial-orange)](LICENSE)

**Un lecteur de mangas pour Windows, simple et hors ligne.** Beheread lit les fichiers CBZ, CBR, EPUB et PDF, range vos tomes par série et reprend chaque lecture à la page où vous l'avez laissée.

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
* **Sauvegarde** : export et import de la progression, pour changer de PC.

Toutes vos données restent **sur votre PC**. Seules les deux fonctions optionnelles utilisent le réseau, et uniquement si vous les activez. L'application fonctionne normalement sans connexion.

## Installation

Rien d'autre à installer : tout ce dont Beheread a besoin est inclus dans le téléchargement.

### 1. Télécharger

Ouvrez la page de la [dernière version](https://github.com/codingt0m/beheread/releases/latest) et, dans la liste **Assets** en bas de page, téléchargez l'un de ces deux fichiers :

| Fichier | Quand le choisir |
|---|---|
| `Beheread-Setup-x.y.z.exe` | **Recommandé.** Installe Beheread, crée son raccourci dans le menu Démarrer et permet d'ouvrir vos mangas d'un double-clic. |
| `Beheread-x.y.z-windows-x64.zip` | Version sans installation, à dézipper où vous voulez (voir [plus bas](#version-sans-installation)). |

Les archives « Source code » de la même liste contiennent le code du projet : elles ne servent pas à utiliser l'application.

### 2. Installer

1. Double-cliquez sur `Beheread-Setup-x.y.z.exe`.
2. Si Windows affiche « Windows a protégé votre ordinateur » (éditeur inconnu), cliquez sur **Informations complémentaires**, puis sur **Exécuter quand même**. Cet avertissement apparaît parce que Beheread n'est pas signé numériquement : un certificat de signature est payant, et Windows se méfie par défaut de tout programme non signé et encore peu téléchargé. Ce n'est pas le signe d'un problème. Pour vous assurer que le fichier est bien celui publié ici, voir [Vérifier le téléchargement](#vérifier-le-téléchargement-facultatif).
3. Choisissez **Installer seulement pour moi (recommandé)** : aucun droit administrateur n'est demandé.
4. Sur la page des tâches supplémentaires, laissez cochée l'option **Ouvrir les fichiers CBZ, CBR et EPUB avec Beheread** pour ouvrir vos mangas d'un double-clic. Cochez **Créer une icône sur le Bureau** si vous en voulez une.
5. Cliquez sur **Installer**, puis sur **Terminer** : Beheread se lance.

Beheread s'installe dans `%LOCALAPPDATA%\Programs\Beheread`. Pour les PDF, il est proposé dans « Ouvrir avec » sans remplacer votre lecteur PDF habituel.

### 3. Premier lancement

1. Sur l'écran d'accueil, cliquez sur **Ajouter un dossier** et choisissez le dossier qui contient vos mangas. Ses sous-dossiers sont parcourus aussi, et vos fichiers ne sont ni déplacés ni modifiés.
2. Un bandeau propose de rechercher en ligne l'auteur et la date de sortie de vos tomes : répondez **Activer** ou **Non merci**. Ce choix se modifie ensuite dans les préférences.
3. Double-cliquez sur une couverture pour lire. **F1** affiche la liste des raccourcis.

Par la suite, Beheread s'ouvre depuis le menu Démarrer ou d'un double-clic sur un fichier CBZ, CBR ou EPUB.

### Version sans installation

1. Dézippez `Beheread-x.y.z-windows-x64.zip` où vous voulez.
2. Ouvrez le dossier `Beheread` et lancez `Beheread.exe`. Le dossier `_internal` doit rester à côté de lui.
3. Au premier lancement, Windows peut afficher le même avertissement que pour l'installateur : cliquez sur **Informations complémentaires**, puis sur **Exécuter quand même** (voir l'étape 2 de [Installer](#2-installer)).

Cette version ne crée ni raccourci ni association de fichiers. Elle enregistre ses données au même endroit que la version installée (`%APPDATA%\MangaReaderPy`).

### Mettre à jour

Beheread ne se met pas à jour tout seul. Téléchargez le nouvel installateur et lancez-le : il remplace la version en place, en fermant Beheread s'il est ouvert. Votre bibliothèque, votre progression et vos réglages sont conservés.

### Désinstaller

Ouvrez *Paramètres Windows > Applications > Applications installées*, puis choisissez **Désinstaller** sur la ligne Beheread. L'application et ses associations de fichiers sont retirées ; vos données de lecture sont conservées dans `%APPDATA%\MangaReaderPy`. Supprimez ce dossier pour tout effacer.

## Lire les fichiers CBR

Les CBZ, EPUB et PDF fonctionnent sans rien d'autre. Beaucoup de fichiers `.cbr` sont en réalité des ZIP renommés : Beheread reconnaît le format réel du fichier, donc ceux-là s'ouvrent aussi sans rien installer.

Les vrais fichiers RAR ont besoin d'un outil de décompression, qui n'est pas fourni avec Beheread. Une seule de ces options suffit :

* **WinRAR est installé** : rien à faire, il est détecté automatiquement.
* **7-Zip est installé** : rien à faire non plus, il est détecté automatiquement à son emplacement habituel (`C:\Program Files\7-Zip`) depuis la version 1.1.0. Installé ailleurs, ajoutez son dossier à la variable d'environnement PATH.
* **Ni l'un ni l'autre** : téléchargez « UnRAR for Windows » sur [rarlab.com](https://www.rarlab.com/rar_add.htm) et copiez `UnRAR.exe` dans le dossier de Beheread, à côté de `Beheread.exe`. Avec l'installateur, ce dossier est `%LOCALAPPDATA%\Programs\Beheread` (collez ce chemin dans la barre d'adresse de l'Explorateur pour l'ouvrir).

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
| Retour à la bibliothèque | Échap |
| Liste de tous les raccourcis | F1 |

Toutes les fonctions sont détaillées dans le [guide d'utilisation](docs/GUIDE.md).

## Vérifier le téléchargement (facultatif)

Chaque version publie un fichier `SHA256SUMS.txt`. Dans PowerShell, depuis le dossier du téléchargement :

```
Get-FileHash .\Beheread-Setup-x.y.z.exe -Algorithm SHA256
```

(ou `.\Beheread-x.y.z-windows-x64.zip` pour la version sans installation). L'empreinte affichée doit être celle de la ligne correspondante de `SHA256SUMS.txt`.

## Dépannage

* **« Windows a protégé votre ordinateur »** au lancement de l'installateur ou de `Beheread.exe` (version sans installation) : voir l'étape 2 de [Installer](#2-installer).
* **« Aucun outil de décompression RAR n'a été trouvé »** : voir [Lire les fichiers CBR](#lire-les-fichiers-cbr).
* **Une vignette reste grise** : l'archive est probablement corrompue ou vide ; ouvrez-la pour voir le message d'erreur détaillé.
* **Autre comportement anormal** (Beheread qui ne se lance pas, métadonnées qui n'arrivent jamais, dossier qui ne se rafraîchit plus) : consultez `beheread.log` dans `%APPDATA%\MangaReaderPy`, toutes les erreurs y sont consignées.
* **Signaler un problème** : ouvrez une [issue](https://github.com/codingt0m/beheread/issues), en joignant si possible les lignes concernées de `beheread.log`.

## Documentation

* [Guide d'utilisation](docs/GUIDE.md) : bibliothèque, lecteur, statistiques, métadonnées, AniList, données.
* [Notes de version](CHANGELOG.md)
* [Développement](docs/DEVELOPPEMENT.md) : lancer depuis les sources, construire, publier, structure du code, tests.

## Licence

Beheread est distribué sous [licence PolyForm Noncommercial 1.0.0](LICENSE).

* **Autorisé** : utiliser Beheread, le modifier et le partager gratuitement, pour un usage personnel ou non commercial (y compris dans une association, une école ou un organisme public).
* **Interdit** : tout usage commercial, par exemple vendre Beheread ou une version modifiée, ou l'intégrer à un produit ou service payant.

Pour un usage commercial, contactez l'auteur en ouvrant une [issue](https://github.com/codingt0m/beheread/issues).
