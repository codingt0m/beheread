# Beheread

Application de bureau pour Windows 10/11, 100% locale et hors-ligne, pour lire des mangas au format CBZ (archives ZIP), CBR (archives RAR) et EPUB (les EPUB étant eux-mêmes des archives ZIP, leurs images sont lues comme des pages de manga).

Stack : Python 3 + PySide6 (Qt). Choix motivé par la simplicité d'installation (un seul `pip install`), de bonnes performances d'affichage d'images (rendu natif Qt) et un support Windows solide.

## Installation

1. Installer Python 3.10 ou plus récent depuis https://www.python.org/downloads/
   Pendant l'installation, cocher la case "Add Python to PATH".

2. Ouvrir un terminal (touche Windows, taper "cmd", Entrée), se placer dans le dossier de l'application, puis installer les dépendances :

```
cd chemin\vers\manga-reader
pip install -r requirements.txt
```

Cela installe PySide6 (interface graphique) et rarfile (lecture des RAR).

## Support CBR (obligatoire uniquement pour les vrais fichiers RAR)

Les CBZ fonctionnent sans rien d'autre. Pour les CBR, la bibliothèque `rarfile` a besoin d'un outil de décompression externe. Trois options, une seule suffit :

* Option A (recommandée) : télécharger "UnRAR for Windows" sur https://www.rarlab.com/rar_add.htm et copier le fichier `UnRAR.exe` dans le même dossier que `main.py`. L'application le détecte automatiquement.
* Option B : si WinRAR est déjà installé, rien à faire dans la plupart des cas. L'application cherche `UnRAR.exe` dans `C:\Program Files\WinRAR`.
* Option C : installer 7-Zip (https://www.7-zip.org) et ajouter son dossier (`C:\Program Files\7-Zip`) à la variable d'environnement PATH. `rarfile` sait utiliser `7z.exe` comme moteur de décompression.

Note : beaucoup de fichiers `.cbr` du commerce sont en réalité des ZIP renommés. L'application détecte le format réel par la signature du fichier, donc ces fichiers s'ouvrent même sans outil RAR.

## Lancement

**Sans taper de commande** : double-cliquer sur `Lancer le lecteur.vbs` dans le dossier de l'application. Ça lance l'appli directement, sans fenêtre de console. Pour un accès encore plus rapide, clic droit sur ce fichier > "Envoyer vers" > "Bureau (créer un raccourci)" - le raccourci obtenu peut ensuite être épinglé à la barre des tâches ou au menu Démarrer.

En ligne de commande, ça reste possible avec :

```
python main.py
```

Astuce : pour lancer sans fenêtre de console, utiliser `pythonw main.py`.

### Construire un .exe autonome

Pour distribuer Beheread sans que la personne qui l'utilise ait besoin d'installer Python :

```
pip install -r requirements-dev.txt
pyinstaller beheread.spec
```

L'exécutable est généré dans `dist\Beheread.exe` (~45 Mo, un seul fichier, icône incluse, sans fenêtre de console). Il peut être copié/partagé tel quel — aucune installation de Python n'est requise sur la machine cible.

Pour reconstruire depuis zéro (ex. après avoir modifié `beheread.spec`), supprimer les dossiers `build\` et `dist\` avant de relancer la commande.

Limites : le support CBR nécessite toujours un outil de décompression RAR sur la machine cible (voir "Support CBR" ci-dessus) — ce n'est pas embarqué dans l'exe. Ce format "un seul fichier" s'extrait dans un dossier temporaire à *chaque* lancement, donc le démarrage est un peu plus lent qu'avec `python main.py` (quelques secondes) ; c'est le compromis du mode "onefile".

## Utilisation

En haut de la bibliothèque, un en-tête unique regroupe tout : logo et titre à gauche, barre de recherche au centre, puis à droite les boutons à icônes (regrouper par série, vue grille/liste, ajouter/retirer un dossier, rafraîchir) et la bascule de thème clair/sombre (icône soleil/lune, choix mémorisé entre les sessions). Chaque bouton affiche son rôle au survol.

Bibliothèque :
* **Ajouter un dossier** (icône dossier +) : choisir un répertoire contenant vos CBZ/CBR/EPUB. Le scan est récursif (sous-dossiers inclus). Plusieurs dossiers sources possibles.
* **Retirer un dossier** (icône dossier −) : enlève un répertoire de la bibliothèque (les fichiers ne sont pas touchés).
* **Rafraîchir** (icône flèche circulaire, ou F5) : rescanne les dossiers après ajout de nouveaux fichiers. La bibliothèque se rafraîchit désormais **automatiquement** quand un fichier CBZ/CBR/EPUB est ajouté, déplacé ou supprimé dans un dossier source (ou l'un de ses sous-dossiers) ; le bouton reste utile en secours.
* **Recherche** (raccourci Ctrl+F pour y placer le curseur) : le champ de recherche filtre instantanément par titre, nom de série, ou auteur (une fois l'auteur récupéré en arrière-plan — voir section métadonnées ci-dessous ; juste après l'ajout d'un dossier, la recherche par auteur peut donc mettre quelques instants à devenir disponible pour les entrées tout juste découvertes).
* **Reprendre la lecture** : une bande horizontale en haut de la bibliothèque rassemble les tomes en cours de lecture, du plus récemment lu au plus ancien ; un clic reprend directement à la dernière page. Elle n'apparaît qu'à la racine (masquée pendant une recherche ou dans un dossier de série).
* **Démarrage immédiat (hors-ligne)** : la bibliothèque s'affiche instantanément au lancement à partir du dernier instantané connu, pendant que le scan réel des dossiers se fait en arrière-plan (l'interface ne fige plus, même sur un dossier réseau).
* **Regrouper par série** (icône pile de couches, s'allume en rouge quand actif) : détecte les tomes d'un même manga d'après leur nom de fichier (ex. "One Piece - Tome 12.cbz") et les place les uns à la suite des autres (avec un en-tête de série en vue liste), triés par (série, numéro de tome). Sans regroupement, la bibliothèque reste triée par ordre alphabétique.
* **Vue Grille / Liste** (icône grille ou liste) : bascule entre la grille de vignettes et une liste compacte plus dense.
* **Sélection multiple** (Ctrl/Maj + clic) pour appliquer une action à plusieurs mangas d'un coup.
* Les vignettes utilisent la première image de chaque archive et sont mises en cache pour un affichage instantané aux lancements suivants.
* Sous chaque couverture : la page en cours et le total. Barre rouge = lecture en cours, barre verte + badge = terminé. Une couverture legèrement grisée indique un manga marqué comme lu.
* L'auteur, une fois récupéré (voir ci-dessous), s'affiche sous la vignette (grille) ou sur la ligne de sous-titre (vue liste), et apparaît aussi au survol dans l'info-bulle avec la date de sortie et la source.
* Double-clic sur une vignette pour ouvrir le manga (il reprend exactement à la dernière page lue). Le lecteur s'ouvre dans sa **propre fenêtre**, maximisée, distincte de la bibliothèque (qui repasse en arrière-plan pendant la lecture et réapparaît à la fermeture du lecteur).
* Clic droit sur une ou plusieurs vignettes sélectionnées pour :
  * **Réinitialiser la progression** : remet le suivi de lecture à zéro.
  * **Marquer comme lu** : déclare le(s) manga(s) terminé(s) (couverture grisée, badge vert).
  * **Marquer comme non lu** : annule un marquage « terminé » (accidentel ou non) sans perdre la page en cours — proposé uniquement sur des tomes actuellement marqués terminés.
  * **Recharger les métadonnées** : oublie l'auteur/la date en cache (et le résultat AniList associé à la série) pour relancer la recherche à zéro — utile si une recherche précédente n'a rien trouvé, s'est trompée, ou a échoué faute de réseau.
  * **Mettre à la corbeille...** : envoie le(s) fichier(s) dans la corbeille de Windows (récupérables), après confirmation obligatoire. Si le module `send2trash` n'est pas disponible, l'application se rabat sur une suppression définitive (le libellé de la confirmation le précise alors clairement).

### Métadonnées (auteur, date de sortie)

Dès qu'un dossier est ajouté ou rafraîchi, l'auteur et la date de sortie de chaque manga sont récupérés automatiquement en arrière-plan. L'auteur s'affiche sous la vignette (grille) ou en sous-titre (liste), apparaît au survol dans l'info-bulle (avec la date de sortie et la source), et devient exploitable par la recherche (le champ en haut filtre aussi par auteur). La récupération utilise une stratégie en cascade, du plus fiable/local au plus incertain :

1. **ComicInfo.xml** (priorité 1, 100% hors ligne) : si l'archive contient un fichier `ComicInfo.xml` (standard ComicRack/ComicTagger) à sa racine, ses champs `Writer`/`Penciller`/`Author`, `Year`/`Month`/`Day` sont utilisés directement — aucune requête réseau n'est faite si ces informations suffisent.
2. **Google Books** (priorité 2) : à défaut, recherche combinant le nom de série (déduit du nom de fichier) et le numéro de tome, pour retrouver la date de sortie de l'édition physique précise (la couverture affichée reste toujours la première page de l'archive, aucune image externe n'est utilisée).
3. **AniList** (priorité 3, repli) : si Google Books ne trouve rien, recherche sur le seul nom de série via l'API AniList (GraphQL, gratuite), qui gère bien les titres traduits/synonymes (y compris français). Le résultat, propre à la série, est alors partagé par tous ses tomes.

Chaque couche n'est interrogée que si la précédente n'a rien donné d'exploitable. Le résultat (avec sa source) est mis en cache localement dans `meta_cache.json` : un tome/une série n'est interrogé qu'une seule fois.

Limites à connaître :
* Google Books et AniList ne documentent pas forcément un tome précis dans une édition française — la date obtenue via AniList (repli série) est celle de la première publication de la série entière, pas du tome lu.
* La recherche se base sur le nom de fichier ; un titre traduit qui ne correspond à rien d'indexé peut ne rien trouver, ou (rarement) trouver la mauvaise œuvre.
* Nécessite une connexion internet pour les couches 2 et 3. Sans connexion (ou en cas d'erreur), l'application continue de fonctionner normalement : l'auteur reste simplement vide pour les mangas concernés, et la recherche sera retentée à la prochaine session (les échecs réseau ne sont pas mis en cache, contrairement aux recherches sans résultat).
* L'API Google Books sans clé a un quota anonyme assez bas et partagé par adresse IP (des erreurs "trop de requêtes" sont possibles sur certains réseaux) ; l'application se rabat alors automatiquement sur AniList.
* Les requêtes sont volontairement espacées pour rester polies envers ces API publiques ; l'auteur affiché se remplit progressivement au fur et à mesure que les réponses arrivent.

Détection de série : basée uniquement sur le nom de fichier (marqueurs "Tome", "Vol", "#", ou numéro final). Un fichier sans numéro détecté reste affiché individuellement. À la fin d'un tome, si un tome suivant est détecté dans le même dossier, le lecteur propose d'enchaîner directement dessus (touche Entrée) sans repasser par la bibliothèque.

Lecteur :

| Action | Commande |
|---|---|
| Page suivante | Flèche bas, Espace, molette bas, flèche droite*, clic zone droite* |
| Page précédente | Flèche haut, retour arrière, molette haut, flèche gauche*, clic zone gauche* |
| Avancer/reculer d'une seule page (utile en double page) | PgDown / PgUp |
| Première / dernière page | Début / Fin |
| Basculer simple page / double page | D |
| Basculer mode manga (droite → gauche) / mode normal (gauche → droite) | M |
| Décaler la parité en double page (couverture seule ↔ couplée) | S |
| Changer l'ajustement (fenêtre, largeur, hauteur) | F |
| Recadrage automatique des marges (rogne les bords vides du scan) | R |
| Ambilight : fond teinté par la couleur de la page (désactivé par défaut) | A |
| Zoom | + / - ou Ctrl + molette, 0 pour réinitialiser |
| Déplacer l'image quand elle dépasse (zoom, ajustement largeur) | glisser avec la souris |
| Plein écran | F11, ou bouton "⛶ Plein écran" en haut à droite |
| Masquer instantanément la fenêtre (touche « boss »), puis la réafficher | C pour masquer ; Ctrl+Alt+C pour masquer/réafficher depuis n'importe où |
| Tome suivant (si detecte, en fin de tome) | Entree, ou bouton de la fiche de fin |
| Retour à la bibliothèque | Echap, ou bouton "← Bibliothèque" en haut à gauche |
| Sauter directement à une page | clic ou glisser sur la barre de défilement en bas de l'écran (le survol affiche un aperçu de la page visée) |

\* Flèche/clic gauche et droite sont inversés en mode manga, puisque la lecture s'y fait de droite à gauche.

Par défaut, le lecteur démarre en **mode manga** et en **double page** : la page 1 s'affiche à droite, la page 2 à sa gauche, et "page suivante" fait progresser vers la gauche. Le mode d'affichage (double page, mode manga, ajustement) est mémorisé entre les sessions.

En double page, une image déjà plus large que haute (planche double scannée en une seule image) est détectée automatiquement et affichée seule, sans être couplée à sa voisine.

Chaque changement de page est adouci par un fondu enchaîné rapide (~130ms).

**Décalage de parité (touche S).** Beaucoup de scans placent une couverture en première page, ce qui décale toutes les doubles pages : les planches qui se répondent ne se retrouvent jamais côte à côte. La touche `S` bascule la parité de l'appairage — la couverture s'affiche alors seule et les paires suivantes se recalent correctement. Le choix est mémorisé pour chaque tome.

**Recadrage automatique des marges (touche R).** Les scans embarquent souvent des marges blanches (ou noires) inégales qui gâchent l'ajustement et désalignent les deux planches en double page. La touche `R` détecte et rogne ces bords vides pour agrandir la surface utile. En double page, les deux planches partagent le **même niveau de recadrage** (la marge la plus faible des deux sur chaque bord, c'est-à-dire le recadrage le moins agressif), afin de rester alignées et à la même échelle. Le préréglage est mémorisé entre les sessions.

**Ambilight (touche A).** Teinte le fond du lecteur avec la couleur moyenne (assombrie) de la page affichée, avec un fondu doux à chaque changement de page — un effet d'ambiance proche des téléviseurs Ambilight. **Désactivé par défaut**, activable à tout moment d'un appui sur `A` ; le choix est mémorisé entre les sessions.

**Interface auto-masquable.** Le HUD, les boutons et la barre de défilement s'effacent après quelques secondes d'inactivité de la souris, pour une lecture sans distraction. Ils réapparaissent au moindre mouvement de souris — mais jamais lors d'un simple changement de page au clavier, afin de ne pas interrompre la lecture.

**Estimation du temps restant.** Après quelques tours de page, le HUD affiche une estimation du temps de lecture restant dans le tome (« ~18 min restantes »), calculée sur votre rythme de la session (les longues pauses sont ignorées).

**Fiche de fin de tome.** À la dernière page, une fiche récapitulative s'affiche : couverture, nombre de pages, temps de lecture de la session, et un bouton pour enchaîner sur le tome suivant (s'il est détecté) ou revenir à la bibliothèque.

**Touche « boss » (C).** Un appui sur `C` masque instantanément la fenêtre de lecture (elle reste dans la barre des tâches). Le raccourci global `Ctrl+Alt+C` la masque et la réaffiche depuis n'importe quelle application — pratique pour dissimuler sa lecture d'une seule touche.

## Sauvegarde de la progression

La dernière page lue de chaque manga est enregistrée automatiquement à chaque changement de page et à la fermeture. Un manga est marqué "Terminé" quand la dernière page est atteinte.

Données stockées localement dans `%APPDATA%\MangaReaderPy` (nom technique historique, inchangé pour ne pas perdre les données des installations existantes) :
* `settings.json` : dossiers sources, préférences du lecteur/bibliothèque, thème
* `progress.json` : progression de lecture (page, décalage de parité et date de dernière lecture par tome)
* `meta_cache.json` : cache des métadonnées (auteur/date) par tome et par série
* `fingerprints.json` : empreintes de contenu des fichiers (voir ci-dessous)
* `library_index.json` : dernier instantané de la bibliothèque, pour l'affichage immédiat au démarrage (hors-ligne)
* `thumbnails\` : cache des couvertures (JPEG)

**Identité par contenu.** La progression, les métadonnées et les vignettes sont rattachées à une **empreinte du contenu** de chaque fichier (sa taille et ses premiers kilo-octets), et non à son chemin sur le disque. Concrètement : renommer ou déplacer un tome **conserve sa progression**, et deux copies identiques la partagent. Les anciennes données indexées par chemin sont migrées automatiquement au premier lancement (les vignettes se régénèrent une fois à cette occasion). Les empreintes sont mises en cache dans `fingerprints.json` pour rester instantanées aux lancements suivants.

Les sauvegardes sont regroupées puis écrites en arrière-plan (elles ne bloquent pas la lecture, même en tournant les pages rapidement) et garanties à la fermeture de l'application.

Supprimer ce dossier réinitialise l'application. Aucune donnée ne quitte votre machine, à l'exception des requêtes envoyées à Google Books et/ou AniList lors de la récupération automatique des métadonnées (auteur, date de sortie) après l'ajout ou le rafraîchissement d'un dossier — le nom de série déduit du fichier, et éventuellement le numéro de tome, leur sont alors envoyés.

## Performances

* Les archives sont lues à la volée, page par page, sans extraction sur le disque, même pour des tomes de plusieurs centaines de pages.
* Les pages voisines (3 avant, 3 après) sont préchargées dans un thread d'arrière-plan : la navigation reste fluide.
* Un cache mémoire limité (12 pages décodées) évite toute saturation de la RAM sur les gros fichiers.
* Les vignettes de la bibliothèque sont générées en parallèle et mises en cache sur disque.

## Structure du projet

```
manga-reader/
  Lancer le lecteur.vbs  Lancement en un double-clic, sans console
  main.py              Point d'entrée, fenêtre principale, bascule de theme
  theme.py             Palettes clair/sombre partagees par l'interface
  icons.py             Icones vectorielles du header, dessinees avec QPainter
  icon.ico             Icone de l'application
  library.py           Bibliothèque : widget principal (grille/liste, recherche, rangée "reprendre", actions, surveillance des dossiers, scan en arrière-plan)
  lib_constants.py     Dimensions et rôles de données partagés par les modules de la bibliothèque
  lib_delegates.py     Rendu des items (grille avec pile de couvertures pour les séries, liste compacte)
  lib_dialogs.py       Panneau de gestion des dossiers sources (façon Plex)
  lib_workers.py       Tâches d'arrière-plan (vignettes, métadonnées par tome et par série, scan)
  reader.py            Lecteur : navigation, double page, zoom, recadrage, préchargement, aperçu au survol, fiche de fin
  pairing.py           Logique pure d'appairage double page (parité, planches doubles, recul) — testée sans Qt
  hotkey.py            Raccourci clavier global Windows (touche « boss » Ctrl+Alt+C)
  archive_handler.py   Ouverture CBZ/CBR/EPUB en mémoire, détection de format
  series.py            Detection serie/tome par nom de fichier, tome suivant
  metadata.py          Cascade ComicInfo.xml -> Google Books -> AniList (+ recherche au niveau série)
  googlebooks.py       Client API Google Books (date de sortie par tome)
  anilist.py           Client API AniList (repli metadonnees serie)
  storage.py           Persistance (identité par contenu, écritures différées)
  tests/               Tests unitaires (pytest) de la logique pure
  requirements.txt     Dépendances Python (utilisation normale)
  requirements-dev.txt Dépendances de build/test (+ PyInstaller, pytest)
  beheread.spec        Config PyInstaller pour generer Beheread.exe
```

## Tests

La logique pure (détection série/tome, cascade de métadonnées, persistance) est couverte par une suite de tests `pytest`, sans interface graphique :

```
pip install -r requirements-dev.txt
pytest
```

## Dépannage

* "Aucun outil de decompression RAR n'a ete trouve" : voir la section "Support CBR" ci-dessus.
* Une vignette reste grise : l'archive est probablement corrompue ou vide ; ouvrez-la pour voir le message d'erreur détaillé.
* L'application ne se lance pas : vérifier `python --version` (3.10 minimum) et réinstaller les dépendances avec `pip install -r requirements.txt`.
#   b e h e r e a d  
 