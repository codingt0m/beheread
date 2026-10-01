# Notes de version

Les numéros de version suivent [SemVer](https://semver.org/lang/fr/). Chaque section ci-dessous sert aussi de notes à la release GitHub du même numéro.

## [Non publié]

* CBR : 7-Zip est détecté automatiquement à son emplacement habituel (`C:\Program Files\7-Zip`), sans avoir à modifier le PATH.
* Message d'erreur RAR plus clair, qui renvoie vers la bonne section du README.

## [1.0.0] - 2026-10-01

Première version publiée de Beheread, lecteur de mangas pour Windows 10 et 11 (CBZ, CBR, EPUB, PDF).

### Quel fichier télécharger

* `Beheread-Setup-1.0.0.exe` : l'installateur, recommandé. Il installe Beheread pour votre compte, sans droits administrateur.
* `Beheread-1.0.0-windows-x64.zip` : la version sans installation, à dézipper où vous voulez.
* `SHA256SUMS.txt` : les sommes de contrôle des deux fichiers.

L'installateur n'est pas signé numériquement : si Windows affiche « Windows a protégé votre ordinateur », cliquez sur **Informations complémentaires**, puis sur **Exécuter quand même**. Le [guide d'installation](https://github.com/codingt0m/beheread#installation) détaille chaque étape.

### Ce que fait Beheread

* **Bibliothèque** : vos dossiers de mangas sont parcourus et surveillés, les tomes regroupés par série, avec recherche, tris, filtres et une bande « Continuer la lecture ».
* **Lecteur** : plein écran, double page, sens de lecture manga, recadrage des marges, zoom, Ambilight, enchaînement sur le tome suivant.
* **Progression** : chaque tome reprend à la dernière page lue, même après avoir renommé ou déplacé le fichier.
* **Statistiques** : temps de lecture, pages lues, tomes terminés et régularité, par période.
* **Métadonnées** (optionnel) : auteur et date de sortie, depuis ComicInfo.xml puis Google Books, AniList et MangaDex.
* **Suivi AniList** (optionnel) : votre liste est mise à jour à la fin de chaque séance, uniquement par ajouts.
* **Sauvegarde** : export et import de la progression, pour changer de PC.

Toutes les données restent sur votre PC. Seules les deux fonctions optionnelles utilisent le réseau, et uniquement après votre accord.

### Nouveautés depuis la version de test 0.2.0

* Statistiques refaites : une période au choix (7 jours, 30 jours, 12 mois, tout) gouverne tous les chiffres, chacun comparé à la période précédente ; calendrier de régularité, séries les plus lues, derniers tomes terminés.
* Mesure de la lecture plus juste : une page compte après 1 s d'affichage, et les pauses de plus de 90 s sont ignorées.
* Le lecteur s'ouvre toujours en plein écran, et ses réglages (double page, recadrage, ajustement, Ambilight) sont communs à tous les mangas.
* Couleur d'accentuation personnalisable, en-tête allégé, recherche centrée.
* La bande « Continuer la lecture » défile avec la grille ; les couvertures ne clignotent plus dans un dossier de série.
* Téléchargement et installation plus légers : l'installateur passe de 35 à 25 Mo.

### Vous utilisiez la version de test 0.2.0 ?

Lancez le nouvel installateur : il remplace la version en place et conserve vos données. Au premier lancement, la base est convertie automatiquement ; une copie de l'ancienne est gardée dans `%APPDATA%\MangaReaderPy\beheread-v1.bak`.
