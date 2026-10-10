# Notes de version

Les numéros de version suivent [SemVer](https://semver.org/lang/fr/). Chaque section ci-dessous sert aussi de notes à la release GitHub du même numéro.

## [Non publié]

### Version macOS (nouveau)

* **Nouveau** : Beheread existe pour Mac (puce Apple, macOS 13 ou plus récent), avec les mêmes fonctions et la même interface que sous Windows. Téléchargez `Beheread-x.y.z-macos.dmg` et suivez le [guide d'installation macOS](https://github.com/codingt0m/beheread/blob/main/docs/INSTALLATION-MACOS.md) : l'application n'étant pas signée par Apple, macOS demande une autorisation au premier lancement.
* Les touches suivent les habitudes du Mac (⌘F, ⌘, pour les réglages, ⌃⌘F pour le plein écran, ⌘⌫ pour supprimer) ; la liste des raccourcis (F1) affiche celles de votre système.
* Les CBR s'ouvrent sans rien installer, avec l'outil de décompression fourni avec macOS.
* Une sauvegarde exportée sous Windows s'importe sur Mac, et inversement : la progression suit vos tomes d'un ordinateur à l'autre.
* Seule différence : le raccourci global `Ctrl+Alt+C` n'existe pas sur Mac ; la touche `C` du lecteur masque Beheread, un clic sur son icône du Dock le fait revenir.
* **Corrigé** : dans les statistiques, un ancien tome terminé venu d'une sauvegarde d'un autre système affichait son chemin complet au lieu de son titre.
* Les guides d'installation sont désormais séparés : [Windows](https://github.com/codingt0m/beheread/blob/main/docs/INSTALLATION-WINDOWS.md) et [macOS](https://github.com/codingt0m/beheread/blob/main/docs/INSTALLATION-MACOS.md).

### BD franco-belge et sens de lecture

* **Nouveau** : les BD (Lou !, Seuls, Blacksad…) trouvent leur auteur et leur année dans le catalogue de la BnF, quand les bases manga ne les connaissent pas.
* **Nouveau** : une BD s'ouvre de gauche à droite, un manga traduit de droite à gauche, d'après le format du livre indiqué par la BnF.
* **Corrigé** : des mangas recevaient l'auteur d'une autre œuvre (Monster, Ping Pong…) : un résultat AniList n'est retenu que si son titre ressemble au nom cherché. Les anciens résultats sont revérifiés automatiquement.
* **Corrigé** : quand AniList limitait les requêtes, des mangas recevaient un homonyme venu d'une autre source (Vagabond, Parasite…) et parfois le mauvais sens de lecture. Les requêtes AniList sont espacées, et un résultat obtenu sans AniList est revérifié à la session suivante.
* **Corrigé** : la touche `M` ne change plus le sens par défaut des préférences, qui ne sert plus qu'aux séries que rien ne permet de reconnaître.
* Les intégrales par cycle (« Seuls - Intégrale du Cycle 1 ») sont rangées dans leur série.

### Reconnaissance des noms de fichiers

* **Corrigé** : dans une bibliothèque rangée par dossiers (« Berserk/Tome 01.cbz », « Vagabond/Tome 01.cbz »), toutes les séries se confondaient en une série « Tome » et des tomes disparaissaient de la bibliothèque. Un fichier sans nom de série prend désormais celui de son dossier.
* **Nouveau** : le nommage BD « Astérix - 38 - La Fille de Vercingétorix » ou « Tintin 05 - Le Lotus bleu » est reconnu : les albums se regroupent par série, dans l'ordre.
* **Nouveau** : les tomes s'affichent sous un titre propre (« Berserk · Tome 1 ») au lieu du nom de fichier brut, qui reste dans l'info-bulle ; le tri par titre range le tome 2 avant le tome 10.
* **Nouveau** : un auteur entre parenthèses dans le nom de fichier (« Monster T01 (Urasawa) ») départage les œuvres homonymes.
* Les plages de tomes (« Kingdom 01-05 ») sont rangées dans leur série.

### Lecture

* Un tome refermé sur sa page 1, 2 ou 3 n'est plus considéré comme commencé : sa progression est effacée à la sortie du lecteur, et il n'apparaît ni « en cours » ni dans « Continuer la lecture ». Un tome déjà terminé le reste.
* **Corrigé** : un album nommé « Série - Tome 4 - Titre de l'album », ou un fichier au nommage « scène » (« Chainsaw.Man.T20.Fujimoto.FR.[CBZ]-NoTag »), formait sa propre série au lieu de rejoindre les autres tomes.

### Babelio

* **Nouveau** : la fiche de fin de tome peut proposer « Marquer comme lu sur Babelio » (option des préférences, désactivée par défaut), qui ouvre la recherche du tome dans le navigateur. Babelio n'ayant pas d'API, Beheread n'y publie rien.

### Suivi AniList

* **Nouveau** : les one-shots (« Errance ») sont publiés « 1 tome lu, terminée » une fois lus, quand l'œuvre AniList existe en un seul tome. Leur association automatique exige un titre quasi identique.

### Corrections

* **Corrigé** : supprimer une copie d'un tome présent en double effaçait la progression de l'autre copie.
* **Corrigé** : la mémoire du lecteur grossissait sans limite en feuilletant un tome dans les deux sens.
* **Corrigé** : un tome terminé pendant un envoi à AniList pouvait ne jamais être publié.
* **Corrigé** : une requête refusée par AniList déconnectait le compte.

## [1.1.0] - 2026-10-03

### Quel fichier télécharger

* `Beheread-Setup-1.1.0.exe` : l'installateur, recommandé. Il remplace la version en place et conserve vos données.
* `Beheread-1.1.0-windows-x64.zip` : la version sans installation, à dézipper où vous voulez.
* `SHA256SUMS.txt` : les sommes de contrôle des deux fichiers.

### Recherche refaite

* **Corrigé** : en mode regroupé par série, taper rapidement (un nom d'auteur par exemple) pouvait afficher « Aucun résultat » alors que des mangas correspondaient.
* Les résultats suivent le regroupement : on voit les dossiers de série concernés plutôt que tous leurs tomes à plat ; un dossier ouvert pendant une recherche ne montre que ses tomes correspondants, et effacer la recherche ramène à l'endroit quitté.
* Plusieurs mots, dans n'importe quel ordre et dans n'importe quel champ : `fujimoto fire`, `berserk 12`.
* Accents, majuscules et ponctuation ignorés : `pokemon` trouve « Pokémon », `gloutons dragons` trouve « Gloutons & Dragons ».
* Les numéros sont exacts : `berserk 1` trouve le tome 1, pas les tomes 10 à 19.
* Fautes de frappe tolérées quand rien ne correspond exactement (`fujimotto`, `berzerk`), signalées par « résultats approchants ».
* La recherche trouve aussi les séries renommées à la main et les titres connus de l'œuvre (anglais, romaji, original) : « Attack on Titan » trouve « L'Attaque des Titans ».
* Les résultats se complètent quand un auteur arrive en arrière-plan.
* Plus rapide et plus économe : chaque frappe prend moins de quelques millisecondes, même sur des milliers de tomes, et une recherche ne charge plus en mémoire les couvertures de toute la bibliothèque.

### Autres changements

* Licence : Beheread passe sous PolyForm Noncommercial 1.0.0 (usage commercial interdit).
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
