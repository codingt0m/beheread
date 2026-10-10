# Développement de Beheread

Ce document s'adresse à ceux qui veulent modifier Beheread ou le construire eux-mêmes. Il n'est pas nécessaire pour l'utiliser : voir plutôt le [README](../README.md).

## Lancer depuis les sources

Sous Windows, installer Python 3.10 ou plus récent (https://www.python.org/downloads/, case "Add Python to PATH" cochée) ; sous macOS, Python 3.10 ou plus récent de python.org ou de Homebrew (`python3` remplace alors `python` dans les commandes ci-dessous). Puis dans le dossier du projet :

```
pip install -r requirements.txt          # dépendances de l'application
pip install -r requirements-dev.txt      # + tests, vérification du code, construction de l'exe
python -m beheread                       # lancer l'application
```

`requirements.txt` installe PySide6 (interface graphique ; son module QtPdf assure la lecture des PDF), rarfile (lecture des RAR), send2trash (corbeille de Windows) et, sous macOS seulement, keyring (Trousseau). En développement, `UnRAR.exe` (ou `unrar` sous macOS) se dépose à la racine du projet. Si l'application ne se lance pas, vérifier `python --version` et réinstaller les dépendances.

## Construire l'application et l'installateur

La construction se fait sur le système visé : la version Windows sur un PC Windows, la version macOS sur un Mac (PyInstaller ne fait pas de compilation croisée). Sans Mac, la CI la construit à chaque push (voir [Intégration continue](#intégration-continue)).

### Windows

```
build.bat
```

enchaîne la vérification du code (ruff), les tests, la construction de l'exécutable par PyInstaller (`beheread.spec`) et la compilation de l'installateur par Inno Setup (`installer\beheread.iss`, à installer une fois : `winget install JRSoftware.InnoSetup`). Résultats, dans `dist\` :
* `Beheread\` : l'application en mode dossier (`Beheread.exe` + ses bibliothèques). Ce mode démarre immédiatement (rien à extraire à chaque lancement, contrairement à un exe unique) et déclenche beaucoup moins de faux positifs antivirus ;
* `Beheread-Setup-<version>.exe` : l'installateur ;
* `Beheread-<version>-windows-x64.zip` : le même dossier, pour un usage sans installation ;
* `SHA256SUMS.txt` : les sommes de contrôle des deux fichiers précédents.

`build_and_install.bat` fait la même chose puis installe et lance Beheread sur ce PC, sans demande d'élévation.

Limites : l'outil de décompression RAR n'est pas embarqué (voir [Lire les fichiers CBR](../README.md#lire-les-fichiers-cbr)). L'exe n'est pas signé numériquement : Windows SmartScreen peut afficher un avertissement au premier lancement de l'installateur.

### macOS

```
bash packaging/macos/build.sh
```

enchaîne la vérification du code, les tests, la construction de `dist/Beheread.app` par PyInstaller (le même `beheread.spec`, dont une branche produit l'application macOS), sa signature « ad hoc », une vérification de démarrage (l'application emballée est lancée avec `BEHEREAD_SMOKE_TEST=1`, dans un dossier personnel jetable, et doit se fermer d'elle-même après avoir créé sa base), puis l'image disque. Résultats, dans `dist/` :
* `Beheread.app` : l'application, pour Mac à puce Apple (arm64) ;
* `Beheread-<version>-macos.dmg` : l'image disque à publier (l'application et un raccourci vers Applications) ;
* `SHA256SUMS-macos.txt` : sa somme de contrôle.

`Info.plist` (dans `beheread.spec`) déclare les types CBZ et CBR, et les quatre formats ouverts par Beheread. L'icône est `packaging/macos/icon.icns`, générée depuis `beheread/resources/icon.ico`.

Limites : l'application n'est signée qu'« ad hoc », sans compte Apple Developer (payant) ni notarisation : Gatekeeper demande une autorisation au premier lancement (voir [le guide d'installation](INSTALLATION-MACOS.md#3-autoriser-le-premier-lancement)). Une signature Developer ID se brancherait dans `build.sh` (`codesign --sign "Developer ID Application: …" --options runtime`, puis `xcrun notarytool submit` et `xcrun stapler staple` sur le `.dmg`).

## Intégration continue

`.github/workflows/ci.yml` s'exécute à chaque push sur `main` :
* `ruff` et `pytest` sous **Windows et macOS** (runners GitHub) ;
* sous macOS, construction complète (`packaging/macos/build.sh`) et captures d'écran de l'interface (`tools/screenshots.py`, sur une fausse bibliothèque, avec les vraies polices du système). Le `.dmg` et les captures sont joints à l'exécution comme artefacts (onglet *Actions*, 14 jours) : de quoi vérifier le rendu, ou faire tester une version, sans Mac sous la main ni release.

`python tools/screenshots.py <dossier>` produit les mêmes captures en local, sur le système courant.

Ce que la CI ne peut pas vérifier (vrai plein écran, Finder, Gatekeeper, trackpad) est listé dans [TEST-MACOS.md](TEST-MACOS.md), à dérouler sur un vrai Mac avant de publier une version macOS.

## Publier une version

1. Mettre à jour le numéro dans `beheread/version.py` et ajouter la section correspondante en tête de `CHANGELOG.md`.
2. Commiter, puis poser et pousser le tag : `git tag vX.Y.Z`, puis `git push origin vX.Y.Z`.
3. Le workflow `.github/workflows/release.yml` lance `build.bat` sur un runner Windows et crée une release en **brouillon**, avec les trois fichiers à publier et les notes tirées de `CHANGELOG.md`. Il échoue si le tag ne correspond pas à `version.py` ou si la section du changelog manque. Un second job lance ensuite `packaging/macos/build.sh` sur un runner macOS et ajoute le `.dmg` et `SHA256SUMS-macos.txt` au brouillon ; son échec ne bloque pas la version Windows (vérifier que le `.dmg` est bien présent avant de publier).
4. Relire le brouillon dans l'onglet Releases, puis le publier.

Un lancement manuel du workflow (onglet Actions) fait un essai à blanc : les fichiers sont joints à l'exécution comme artefacts, sans créer de release.

## Enregistrer Beheread auprès d'AniList (une seule fois)

Sur https://anilist.co/settings/developer, créer une application (« Create New Application ») nommée Beheread, avec comme *Redirect URL* exactement `http://127.0.0.1:51789/anilist`. Recopier le **Client ID** obtenu dans `ANILIST_CLIENT_ID` de `beheread/config.py` (ou, pour tester, dans la variable d'environnement `BEHEREAD_ANILIST_CLIENT_ID`), puis reconstruire l'exe. Le Client ID n'est pas secret ; le **Client Secret n'est jamais utilisé** et ne doit figurer nulle part dans le code. Tant que le Client ID est vide, le bouton de connexion est désactivé. Si, après l'accord sur AniList, le navigateur affiche `{"error":{"status":404,"messages":["API route not found."]}}` sur une adresse `anilist.co/api/v2/oauth/…`, c'est que la *Redirect URL* a été enregistrée sans `http://` : le navigateur la traite alors comme un chemin du site AniList.

## Structure du projet

Le code vit dans le package `beheread/`, organisé en couches ; les dépendances vont toujours de `ui` vers `services`, `infra` puis `core` (jamais l'inverse).

```
main.py                  Point d'entrée de PyInstaller (et python main.py)
beheread/
  __main__.py            python -m beheread
  app.py                 Fenêtre principale, fenêtre du lecteur, démarrage (instance unique, thème)
  config.py              Configuration interne (Client ID AniList, facteur des vignettes, chemins)
  version.py             Numéro de version (SemVer)
  resources/             Icône
  core/                  Logique pure, sans Qt ni accès disque/réseau, testée isolément
    models.py            Modèles typés (LibraryEntry, VolumeInfo, SeriesInfo)
    series.py            Détection série/tome par nom de fichier, tome suivant
    babelio.py           Recherche Babelio d'un tome (page locale ouverte depuis la fiche de fin)
    library_model.py     Statuts de lecture, tris, sélection « Continuer la lecture »
    search.py            Recherche : normalisation, index inversé, tolérance aux fautes de frappe
    pairing.py           Appairage double page (parité, planches doubles, recul)
    wheel_nav.py         Molette / pavé tactile (défilement puis tour de page)
    stats.py             Statistiques (périodes, comparaison, jours d'affilée, classement)
    reading_session.py   Mesure d'une séance (pages lues, temps actif, rythme)
    backup.py            Sauvegarde (export, fusion à l'import)
    anilist_track.py     Règles du suivi AniList (uniquement des ajouts)
  platforms/             Tout ce qui dépend du système, derrière une seule interface (__init__.py)
    windows.py           DPAPI, raccourci global Ctrl+Alt+C, explorateur, outils RAR, fichiers cloud
    macos.py             Trousseau, Finder, Corbeille, bsdtar / 7-Zip, fichiers iCloud, masquage (touche C)
    generic.py           Repli pour les autres systèmes (non pris en charge)
  infra/                 Persistance, archives, réseau
    storage.py           Store : façade de persistance (identité par contenu, écritures différées)
    database.py          Base SQLite : schéma versionné, dépôts, écritures incrémentales
    reading_log.py       Journal de lecture : table SQL, agrégats par période des statistiques
    archive.py           Ouverture CBZ/CBR/EPUB en mémoire, rendu des PDF (QtPdf), scan des dossiers
    metadata.py          Cascade ComicInfo.xml -> Google Books -> AniList -> MangaDex -> BnF
    googlebooks.py, anilist.py, mangadex.py, bnf.py   Clients d'API
    anilist_auth.py      Connexion AniList (récepteur local du jeton)
    secret_store.py      Protection du jeton AniList (DPAPI, Trousseau : voir platforms)
    single_instance.py   Instance unique (verrou + canal local)
    applogging.py        Journal beheread.log
  services/
    anilist_tracker.py   Suivi AniList : file d'attente, envois en fin de séance
  ui/
    theme.py, icons.py, help_overlay.py, stats_view.py
    keys.py              Raccourcis propres au système et noms des touches affichés (⌘F sous macOS)
    appicon.py           Icône de l'application re-teintée dans la couleur d'accentuation
    library/             Bibliothèque
      widget.py          LibraryWidget : construction de la grille, navigation, bande « Continuer »
      controllers.py     Scan des dossiers, métadonnées, cache de couvertures (threads, signaux)
      chrome.py          En-tête, barre d'outils, bandeau de consentement, état vide, glisser-déposer
      detail_panel.py    Panneau d'informations
      actions.py         Actions sur les tomes et séries (marquer lu, renommer, supprimer, fusionner…)
      menus.py           Menus contextuels
      services.py        Préférences, statistiques, sauvegarde, AniList
      views.py, delegates.py, shelf.py, detail.py, dialogs.py, workers.py, constants.py
    reader/              Lecteur
      widget.py          ReaderWidget : navigation, rendu
      page_cache.py      Pages décodées : préchargement et éviction
      display.py         Recadrage, planches doubles, Ambilight, fondu, zoom, sens de lecture
      hud.py, end_card.py, input.py, session.py, imaging.py, components.py, constants.py
tests/                   Tests pytest (logique, persistance, réseau simulé)
  ui/                    Tests d'interface (pytest-qt) : bibliothèque et lecteur
  fixtures/              Fichiers de test (vrai RAR5)
installer/beheread.iss   Installateur Inno Setup (Windows)
build.bat                Windows : vérification du code, tests, exe (mode dossier), installateur, archive zip
build_and_install.bat    build.bat puis installation et lancement sur ce PC
packaging/macos/         macOS : build.sh (application, image disque), icon.icns
tools/screenshots.py     Captures d'écran de l'interface sur une fausse bibliothèque
beheread.spec            Configuration PyInstaller (Windows et macOS)
pyproject.toml           Configuration de ruff et de pytest
requirements.txt         Dépendances de l'application
requirements-dev.txt     + tests, vérification du code, construction de l'exe
CHANGELOG.md             Notes de version
.github/workflows/ci.yml        Tests Windows et macOS, build et captures macOS à chaque push
.github/workflows/release.yml   Publication d'une version (tag vX.Y.Z)
```

## Tests

```
pip install -r requirements-dev.txt
pytest
ruff check .
```

La suite couvre la logique pure (séries, appairage, molette, statistiques, règles AniList…), la persistance (SQLite, import des anciens JSON, sauvegarde), les clients réseau (réseau simulé, aucun appel réel) et l'interface avec **pytest-qt** (`tests/ui/` : état vide, glisser-déposer, filtres et tris, « Continuer la lecture », gestion des séries, suppression, lecteur, molette, PDF, instance unique). Les tests d'interface tournent sans fenêtre (plateforme « offscreen »), sans réseau et sans enregistrer de raccourci global. Les tests propres à un système (DPAPI, Trousseau, Corbeille du Finder, RAR par `bsdtar`) sont ignorés ailleurs ; la CI exécute la suite sous Windows et sous macOS. `ruff check .` vérifie le code avec les règles retenues dans `pyproject.toml` : noms indéfinis, imports inutiles, erreurs de syntaxe, ordre des imports.

## Performances

* Les archives sont lues à la volée, page par page, sans extraction sur le disque, même pour des tomes de plusieurs centaines de pages.
* Les pages voisines (3 avant, 3 après) sont préchargées dans un thread d'arrière-plan : la navigation reste fluide.
* Un cache mémoire limité (12 pages décodées) évite toute saturation de la RAM sur les gros fichiers.
* Les vignettes de la bibliothèque sont générées en parallèle et mises en cache sur disque.
