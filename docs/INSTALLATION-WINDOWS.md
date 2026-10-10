# Installer Beheread sous Windows

Pour Windows 10 et 11 (64 bits). Rien d'autre à installer : tout ce dont Beheread a besoin est inclus dans le téléchargement.

Vous êtes sur Mac ? Voir [Installer Beheread sous macOS](INSTALLATION-MACOS.md).

## 1. Télécharger

Ouvrez la page de la [dernière version](https://github.com/codingt0m/beheread/releases/latest) et, dans la liste **Assets** en bas de page, téléchargez l'un de ces deux fichiers :

| Fichier | Quand le choisir |
|---|---|
| `Beheread-Setup-x.y.z.exe` | **Recommandé.** Installe Beheread, crée son raccourci dans le menu Démarrer et permet d'ouvrir vos mangas d'un double-clic. |
| `Beheread-x.y.z-windows-x64.zip` | Version sans installation, à dézipper où vous voulez (voir [plus bas](#version-sans-installation)). |

Les archives « Source code » de la même liste contiennent le code du projet : elles ne servent pas à utiliser l'application.

## 2. Installer

1. Double-cliquez sur `Beheread-Setup-x.y.z.exe`.
2. Si Windows affiche « Windows a protégé votre ordinateur » (éditeur inconnu), cliquez sur **Informations complémentaires**, puis sur **Exécuter quand même**. Cet avertissement apparaît parce que Beheread n'est pas signé numériquement : un certificat de signature est payant, et Windows se méfie par défaut de tout programme non signé et encore peu téléchargé. Ce n'est pas le signe d'un problème. Pour vous assurer que le fichier est bien celui publié ici, voir [Vérifier le téléchargement](#vérifier-le-téléchargement-facultatif).
3. Choisissez **Installer seulement pour moi (recommandé)** : aucun droit administrateur n'est demandé.
4. Sur la page des tâches supplémentaires, laissez cochée l'option **Ouvrir les fichiers CBZ, CBR et EPUB avec Beheread** pour ouvrir vos mangas d'un double-clic. Cochez **Créer une icône sur le Bureau** si vous en voulez une.
5. Cliquez sur **Installer**, puis sur **Terminer** : Beheread se lance.

Beheread s'installe dans `%LOCALAPPDATA%\Programs\Beheread`. Pour les PDF, il est proposé dans « Ouvrir avec » sans remplacer votre lecteur PDF habituel.

## 3. Premier lancement

1. Sur l'écran d'accueil, cliquez sur **Ajouter un dossier** et choisissez le dossier qui contient vos mangas. Ses sous-dossiers sont parcourus aussi, et vos fichiers ne sont ni déplacés ni modifiés.
2. Un bandeau propose de rechercher en ligne l'auteur et la date de sortie de vos tomes : répondez **Activer** ou **Non merci**. Ce choix se modifie ensuite dans les préférences.
3. Double-cliquez sur une couverture pour lire. **F1** affiche la liste des raccourcis.

Par la suite, Beheread s'ouvre depuis le menu Démarrer ou d'un double-clic sur un fichier CBZ, CBR ou EPUB.

## Version sans installation

1. Dézippez `Beheread-x.y.z-windows-x64.zip` où vous voulez.
2. Ouvrez le dossier `Beheread` et lancez `Beheread.exe`. Le dossier `_internal` doit rester à côté de lui.
3. Au premier lancement, Windows peut afficher le même avertissement que pour l'installateur : cliquez sur **Informations complémentaires**, puis sur **Exécuter quand même** (voir l'étape 2 de [Installer](#2-installer)).

Cette version ne crée ni raccourci ni association de fichiers. Elle enregistre ses données au même endroit que la version installée (`%APPDATA%\MangaReaderPy`).

## Mettre à jour

Beheread ne se met pas à jour tout seul. Téléchargez le nouvel installateur et lancez-le : il remplace la version en place, en fermant Beheread s'il est ouvert. Votre bibliothèque, votre progression et vos réglages sont conservés.

## Désinstaller

Ouvrez *Paramètres Windows > Applications > Applications installées*, puis choisissez **Désinstaller** sur la ligne Beheread. L'application et ses associations de fichiers sont retirées ; vos données de lecture sont conservées dans `%APPDATA%\MangaReaderPy`. Supprimez ce dossier pour tout effacer.

## Lire les fichiers CBR

Les CBZ, EPUB et PDF fonctionnent sans rien d'autre. Beaucoup de fichiers `.cbr` sont en réalité des ZIP renommés : Beheread reconnaît le format réel du fichier, donc ceux-là s'ouvrent aussi sans rien installer.

Les vrais fichiers RAR ont besoin d'un outil de décompression, qui n'est pas fourni avec Beheread. Une seule de ces options suffit :

* **WinRAR est installé** : rien à faire, il est détecté automatiquement.
* **7-Zip est installé** : rien à faire non plus, il est détecté automatiquement à son emplacement habituel (`C:\Program Files\7-Zip`). Installé ailleurs, ajoutez son dossier à la variable d'environnement PATH.
* **Ni l'un ni l'autre** : téléchargez « UnRAR for Windows » sur [rarlab.com](https://www.rarlab.com/rar_add.htm) et copiez `UnRAR.exe` dans le dossier de Beheread, à côté de `Beheread.exe`. Avec l'installateur, ce dossier est `%LOCALAPPDATA%\Programs\Beheread` (collez ce chemin dans la barre d'adresse de l'Explorateur pour l'ouvrir).

## Vérifier le téléchargement (facultatif)

Chaque version publie un fichier `SHA256SUMS.txt`. Dans PowerShell, depuis le dossier du téléchargement :

```
Get-FileHash .\Beheread-Setup-x.y.z.exe -Algorithm SHA256
```

(ou `.\Beheread-x.y.z-windows-x64.zip` pour la version sans installation). L'empreinte affichée doit être celle de la ligne correspondante de `SHA256SUMS.txt`.

## Passer d'un PC à un autre, ou à un Mac

Dans *Préférences > Données*, **Exporter…** enregistre votre progression, vos statistiques et vos réglages de séries dans un fichier ; sur l'autre ordinateur, **Importer…** le fusionne. Les tomes sont reconnus par leur contenu : peu importe où se trouvent les fichiers sur le nouvel ordinateur, Windows ou Mac.

## Dépannage

* **« Windows a protégé votre ordinateur »** au lancement de l'installateur ou de `Beheread.exe` (version sans installation) : voir l'étape 2 de [Installer](#2-installer).
* **« Aucun outil de décompression RAR n'a été trouvé »** : voir [Lire les fichiers CBR](#lire-les-fichiers-cbr).
* **Une vignette reste grise** : l'archive est probablement corrompue ou vide ; ouvrez-la pour voir le message d'erreur détaillé.
* **Autre comportement anormal** (Beheread qui ne se lance pas, métadonnées qui n'arrivent jamais, dossier qui ne se rafraîchit plus) : consultez `beheread.log` dans `%APPDATA%\MangaReaderPy`, toutes les erreurs y sont consignées.
* **Signaler un problème** : ouvrez une [issue](https://github.com/codingt0m/beheread/issues), en joignant si possible les lignes concernées de `beheread.log`.
