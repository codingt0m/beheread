# Audit du projet Beheread

*Date : 27/09/2026. Périmètre : tout le dépôt (`main` @ 687a416), soit ~5 000 lignes de code applicatif et ~1 400 lignes de tests.*

*Les liens des sections 0 à 2 renvoient au code tel qu'il était lors de l'audit (commit 687a416, modules à la racine). Depuis le lot 4, le code vit dans le package `beheread/` ; les liens du plan d'action (section 3) pointent vers les emplacements actuels.*

---

## 0. Synthèse

Beheread est un lecteur de mangas (CBZ/CBR/EPUB) pour Windows, en Python 3 et PySide6. Pour un projet personnel, la base est **solide et soignée**. Le code est très commenté, avec les raisons des choix. Il gère déjà des cas difficiles : identité des fichiers par empreinte de contenu, fichiers iCloud/OneDrive non téléchargés, bombes de décompression, XXE, écritures différées, démarrage hors ligne. Il y a 150 tests, qui passent tous (1,7 s).

Les limites viennent surtout de la **croissance organique** du projet :

| Axe | État | Risque principal |
|---|---|---|
| Robustesse des données | 🟠 | Perte de progression possible (suppression, concurrence des sauvegardes, deux instances ouvertes en même temps) |
| Performance | 🟠 | RAM des vignettes (~1,8 Mo par couverture), nombreux `os.stat` sur le thread UI, lent sur un dossier réseau |
| Architecture | 🟠 | Deux « god classes » : `LibraryWidget` (1 650 lignes) et `ReaderWidget` (1 420 lignes) ; aucun package, aucun outillage |
| UI/UX | 🟡 | Molette inutilisable pour faire défiler une page zoomée, peu d'accessibilité clavier, textes sans accents |
| Produit | 🟡 | Des fonctions documentées ou préparées mais absentes : « Reprendre la lecture », tri, filtres de statut, rattachement manuel à une série |
| Sécurité | 🟢 | Bonne hygiène. Deux réserves : User-Agent de navigateur usurpé pour AniList, métadonnées en ligne activées sans consentement |

---

## 1. Analyse de l'existant et points faibles

### 1.1 Architecture et dette technique

**Structure**
- Tous les modules sont à la racine, sans package ni `pyproject.toml`. Les imports (`from library import ...`) dépendent du dossier courant, et `conftest.py` sert seulement à contourner ce problème pour pytest.
- **God classes** :
  - [library.py](library.py) (`LibraryWidget`, 1 650 lignes) mélange la vue Qt, la logique métier (dédoublonnage, regroupement en séries, sélection du tome mis en avant), les E/S disque (renommage, suppression, surveillance des dossiers) et l'orchestration réseau (quatre pools de threads).
  - [reader.py](reader.py) (`ReaderWidget`, 1 420 lignes) mélange le rendu, le cache, le HUD, la détection des marges, l'Ambilight, la fiche de fin et la détection du sens de lecture.
- Les entrées de la bibliothèque sont des **`dict` non typés** (`{"path", "title", "series", "volume", "kind", "added", "detached"}`) qui circulent partout. Une faute de frappe sur une clé ne se voit qu'à l'exécution.
- **`settings.json` sert de fourre-tout**. On y trouve des préférences, mais aussi des données par tome qui grossissent avec la bibliothèque : `added`, `pages`, `series_overrides`, `volume_direction`, `series_direction` ([storage.py:390-483](storage.py#L390-L483)). Il n'y a aucune version de schéma : les migrations sont codées au cas par cas (`_migrate_meta_cache_out_of_settings`, migration par chemin dans `_progress_entry`...).
- **Trois clients HTTP dupliqués** ([googlebooks.py](googlebooks.py), [anilist.py](anilist.py), [mangadex.py](mangadex.py)) : `_throttle`, `_norm_tokens`, gestion d'erreurs, User-Agent. Aucun ne gère `429 Retry-After` ni ne réessaie après une erreur.
- **Style dispersé** : les feuilles de style QSS sont des f-strings réparties dans cinq fichiers. Certaines couleurs sont écrites en dur hors de `theme.py` (`#d14433`, `white`, `#d06060`, `rgba(192, 57, 43, 55)`).

**Code mort ou dérive de la documentation**
- `ROLE_IS_HEADER` et `HEADER_H` : aucun item n'est plus jamais créé avec ce rôle, mais on le teste encore à six endroits ([lib_delegates.py:259](lib_delegates.py#L259), [library.py:1343](library.py#L1343)...).
- `Store.set_series_override(path, <nom>)` (rattachement manuel à une série, « glisser-déposer » d'après [storage.py:319](storage.py#L319)) n'est appelé qu'avec la sentinelle `SERIES_DETACHED`. La fonction de rattachement n'a pas d'interface.
- Imports inutilisés : `QScrollArea`, `QSizePolicy`, `parse_series` dans [library.py](library.py#L16-L24).
- Le README décrit une **bande « Reprendre la lecture »** ([README.md:69](README.md#L69)) qui n'existe plus dans le code (seul l'horodatage `ts` est encore écrit, cf. [storage.py:439](storage.py#L439)). Il décrit aussi des boutons « Ajouter/Retirer un dossier » et des en-têtes de série en vue liste, qui ont été remplacés.
- La docstring de [library.py:1](library.py#L1) annonce « tri, filtres de statut », qui n'existent pas.
- [main.py:2](main.py#L2) dit « 100% local, hors-ligne », ce qui est inexact depuis l'arrivée des métadonnées en ligne.

**Outillage**
- Pas de linter ni de formateur (ruff/black), pas de vérification de types (mypy/pyright), pas de CI, pas de pre-commit.
- Les dépendances sont en `>=` et non figées : un build PyInstaller n'est pas reproductible.
- `version.py` est resté à `0.1.0` depuis le début. Il n'y a pas de CHANGELOG.
- Les tests ne couvrent que la logique pure. Rien ne teste les widgets (pas de `pytest-qt`), alors que la plupart des bugs trouvés ci-dessous sont dans la couche UI.

### 1.2 Bugs et risques de perte de données

| # | Gravité | Problème | Emplacement |
|---|---|---|---|
| B1 | 🔴 | **Suppression : la progression est effacée avant la suppression du fichier.** Si `send2trash` échoue (fichier verrouillé, droits, dossier réseau), le fichier reste mais sa progression, sa date d'ajout et ses métadonnées sont perdues. | [library.py:1621-1632](library.py#L1621-L1632) |
| B2 | 🔴 | **Sauvegardes concurrentes non protégées.** `_flush` sérialise sous verrou dans un thread `Timer`, mais les setters (`set_progress`, `key_for` appelé depuis `ScanWorker`...) modifient les dicts **sans verrou**. Un ajout de clé pendant le `json.dumps` lève `RuntimeError`. L'exception est journalisée, mais le fichier est **retiré de `_dirty`**, donc cette sauvegarde est perdue jusqu'à la modification suivante. | [storage.py:152-178](storage.py#L152-L178), [storage.py:228](storage.py#L228) |
| B3 | 🔴 ✅ | **Pas d'instance unique** *(corrigé au lot 2)*. Double-cliquer un second `.cbz` lance un second processus. Les deux gardent `progress.json` en mémoire et le réécrivent en entier, donc le dernier qui écrit efface la progression de l'autre. | [main.py:243](main.py#L243) |
| B4 | 🟠 | **Enchaînement au tome suivant** : l'ancien lecteur est détruit sans `_persist_reading_pace()`. Le rythme de lecture mesuré sur ce tome est perdu, et ses chargeurs de pages en cours lisent une archive fermée. | [main.py:126-130](main.py#L126-L130) |
| B5 | 🟠 | `Archive.close()` ne prend pas le verrou utilisé par `read_page()`. Fermer le lecteur pendant un préchargement ferme le fichier pendant qu'un autre thread le lit, ce qui provoque des exceptions dans le journal. | [archive_handler.py:254](archive_handler.py#L254) |
| B6 | 🟡 | Après une suppression, `_entries` est réassigné sans `_set_entries()`, donc `_entry_by_path` reste périmé. L'index persistant n'est pas mis à jour non plus. | [library.py:1642](library.py#L1642) |
| B7 | 🟡 | Aucune référence n'est gardée sur `_FolderCountWorker`, contrairement aux autres workers. Le signal peut être perdu (GC), ou arriver sur un dialogue déjà détruit. | [lib_dialogs.py:131-133](lib_dialogs.py#L131-L133) |
| B8 | 🟡 | `build_and_install.bat` fait un `taskkill /f` sur l'application en cours, sans passer par `flush()` : jusqu'à 0,6 s de progression peut être perdue. | [build_and_install.bat](build_and_install.bat) |

### 1.3 Performance

| # | Impact | Constat |
|---|---|---|
| P1 | 🔴 RAM | **Vignettes en mémoire à 3×** (570×804 px en ARGB, soit ~1,8 Mo chacune), jamais libérées. 500 tomes font ~900 Mo de RAM. Le facteur ×3 ne sert que pour un zoom de 150 % sur un écran à 200 %. Sur un écran à 100 %, 1,5× suffit : **4× moins de mémoire**. [library.py:1307](library.py#L1307) |
| P2 | 🔴 UI | **`key_for()` fait un `os.stat()` à chaque appel.** Il est appelé plusieurs fois par item dans `_rebuild_list` (`get_progress`, `volume_meta`, `series_override`, `_series_progress`...) et **à chaque frappe dans la recherche** (`_authors_text` → `volume_meta` → `key_for`, [library.py:1060](library.py#L1060)). Sur un NAS ou OneDrive, cela représente des milliers d'accès réseau sur le thread UI, donc des blocages. |
| P3 | 🟠 UI | La liste est reconstruite entièrement (`clear()` + recréation) à chaque retour du lecteur et à chaque action du menu contextuel, alors qu'un seul item a changé. |
| P4 | 🟠 UI | Après chaque scan, `_update_watches` (un `os.walk` pouvant parcourir 2 000 dossiers) et `purge_orphan_caches` (glob + `key_for` par fichier) tournent sur le thread UI. [library.py:784](library.py#L784) |
| P5 | 🟡 UI | La détection des marges (`_compute_content_rect`) fait une boucle Python pixel par pixel (~20 000 appels `pixel()`) sur le thread UI, à chaque nouvelle page. [reader.py:414](reader.py#L414) |
| P6 | 🟡 | `_schedule()` crée **un nouveau thread `threading.Timer` à chaque modification**, donc à chaque tour de page. [storage.py:148](storage.py#L148) |
| P7 | 🟡 | Métadonnées : une requête Google Books par tome (1 req/s) et une ouverture d'archive par tome pour lire ComicInfo.xml. Pour un RAR, cela lance un processus `unrar` à chaque fois. Premier scan de 1 000 tomes : plus de 20 minutes. |
| P8 | 🟡 | `_throttle()` repose sur une variable globale sans verrou, alors que deux pools (`meta_pool`, `series_meta_pool`) peuvent appeler AniList et MangaDex en parallèle. La limite de débit n'est donc pas garantie. |

### 1.4 Sécurité et vie privée

Points positifs : garde anti-bombe de décompression, refus des DOCTYPE dans ComicInfo.xml, aucune extraction sur disque (donc pas de path traversal), `subprocess` en liste, HTTPS avec vérification de certificat, validation des noms de fichiers au renommage (noms réservés Windows compris).

Réserves :
- **User-Agent Chrome usurpé** pour contourner la protection Cloudflare d'AniList ([anilist.py:22](anilist.py#L22)). C'est fragile (peut être bloqué du jour au lendemain) et discutable vis-à-vis des conditions d'utilisation. Le UA MangaDex pointe vers une URL GitHub qui n'existe pas ([mangadex.py:30](mangadex.py#L30)).
- **Métadonnées en ligne activées par défaut, sans consentement ni réglage.** Les noms des séries de l'utilisateur partent vers Google, AniList et MangaDex dès l'ajout d'un dossier.
- AniList ne vérifie pas la similarité du titre renvoyé, contrairement à Google Books et MangaDex. Une recherche floue peut attribuer un **mauvais auteur**.
- L'exe onefile n'est pas signé et l'installation nécessite des droits admin (HKLM). Les faux positifs antivirus restent possibles malgré la désactivation d'UPX.

### 1.5 UI/UX

**Lecteur**
- 🔴 **La molette tourne toujours la page**, même zoomé ou en « ajuster à la largeur » avec une page plus haute que l'écran. On ne peut alors faire défiler la page qu'en la glissant à la souris ([reader.py:1365](reader.py#L1365)). Sur un **pavé tactile**, chaque événement `pixelDelta` tourne une page, ce qui rend la navigation incontrôlable.
- 🟠 La touche « boss » `C`, sans modificateur, minimise la fenêtre sur une simple faute de frappe.
- 🟠 Les raccourcis ne se découvrent que par les info-bulles ou le README. Il n'y a pas d'aide intégrée (touche `?`).
- 🟡 On ne peut pas aller directement à une page par son numéro. Pas de rotation, pas de mode de lecture verticale continue (webtoon), alors que la détection manhwa/manhua existe déjà.

**Bibliothèque**
- 🟠 **État vide trompeur** : il invite à cliquer sur « Ajouter un dossier », un bouton qui n'existe plus (c'est désormais l'icône engrenage « Gérer les dossiers sources »). Aucun bouton d'action n'est proposé dans cet état ([library.py:1069](library.py#L1069)).
- 🟠 Tri alphabétique uniquement. La date d'ajout et la date de dernière lecture sont calculées et stockées, mais l'interface ne les exploite pas.
- 🟠 Auteur, date de sortie et temps de lecture estimé ne sont visibles **qu'au survol**.
- 🟡 Le menu contextuel d'une série ne propose que « Supprimer » : pas de « Marquer la série comme lue », pas de renommage de série, pas de choix du sens de lecture.
- 🟡 La largeur fixe de la recherche (300 px) et du curseur rend l'en-tête trop large sous ~900 px.

**Cohérence et accessibilité**
- 🟠 **Textes français sans accents** dans la plupart des écrans (« Bibliotheque », « Reinitialiser », « Serie terminee », « Rafraichir ») mais accentués dans d'autres (« Gérer les dossiers sources », dialogue des dossiers). L'application paraît inachevée. Les textes ne passent pas non plus par `tr()`, ce qui empêche toute traduction.
- 🟠 **Clavier** : tous les boutons de l'en-tête, les pastilles du HUD et les boutons du lecteur ont `Qt.NoFocus`, donc impossible de les atteindre avec Tab.
- 🟠 **Lecteurs d'écran** : les boutons ne contenant qu'une icône n'ont pas de `setAccessibleName`.
- 🟡 L'état « terminé » ou « en cours » passe surtout par la couleur (barre verte ou rouge), ce qui pose problème aux daltoniens (heureusement, un badge ✓ existe pour « terminé »). Les pastilles désactivées ont un contraste quasi nul (couleur = `border`).
- 🟡 Les messages d'erreur affichent l'exception brute (`f"{path}\n\n{e}"`).

### 1.6 Fonctionnalités : limites et cas mal couverts

- **Tome suivant** : il n'est cherché que dans le **même dossier**, sans tenir compte des rattachements manuels de série ([series.py:244](series.py#L244)). Une série répartie sur plusieurs dossiers n'enchaîne pas.
- **Formats** : pas de PDF (pourtant QtPdf est déjà fourni avec PySide6), pas de CB7 ni de dossier d'images, pas d'AVIF/JXL.
- **Pas de page de préférences** : les réglages se changent uniquement par raccourcis ou en éditant le JSON.
- **Pas de sauvegarde ni d'export** de la progression : supprimer `%APPDATA%\MangaReaderPy` efface tout. Pas de synchronisation entre plusieurs PC.
- **Pas d'édition manuelle** des métadonnées ni de fusion de séries mal détectées (sauf en renommant le fichier).
- Aucun suivi AniList/MyAnimeList, alors que c'est un usage central chez les lecteurs de mangas.

---

## 2. Propositions d'amélioration

### 2.1 Technique : bonnes pratiques à mettre en place

1. **Structuration en package** `beheread/` en couches :
   - `core/` : pur, sans Qt, testable (`series`, `pairing`, `metadata`, modèles `@dataclass` `Entry`/`Progress`).
   - `infra/` : `storage`, `archive`, `http` commun, clients d'API.
   - `ui/` : `library/` découpé en `view`, `controller`, `model`, et `reader/` découpé en `canvas`, `hud`, `end_card`, `page_cache`.
   - Un point d'entrée `python -m beheread`, et un `pyproject.toml` (métadonnées, dépendances, configuration des outils).
2. **Modèle de données typé** : `@dataclass(frozen=True) class LibraryEntry`. `Store` devient une façade sur des *repositories* : `ProgressRepo`, `MetaRepo`, `LibraryIndexRepo`, `PrefsRepo`, chacun dans son fichier JSON avec un champ `schema_version`, plus une chaîne de migrations.
   - À moyen terme : **SQLite** (`sqlite3`, dans la bibliothèque standard) pour la progression et les caches. On y gagne des écritures transactionnelles, la concurrence entre processus (WAL) et des requêtes de tri.
3. **Store thread-safe** : toute écriture passe par un verrou, ou mieux, toutes les écritures passent par le thread UI et un `QTimer` unique fait le debounce. Seule l'E/S disque part sur un thread.
4. **Module `http.py` commun** : limiteur de débit thread-safe par hôte, prise en compte de `Retry-After`, réessais avec backoff exponentiel, User-Agent honnête (`Beheread/x.y (+URL du dépôt)`).
5. **Qualité** :
   - `ruff` pour le lint et le formatage (règles `E,F,I,B,UP,SIM`).
   - `mypy` en mode progressif (strict sur `core/`).
   - `pre-commit`.
   - Dépendances figées (`uv lock` ou `pip-tools`).
6. **Tests** :
   - Ajouter `pytest-qt` pour les widgets (navigation du lecteur, menu contextuel, suppression).
   - Mesurer la couverture avec `pytest-cov`.
   - Écrire des tests de non-régression pour B1 à B6.
7. **CI GitHub Actions** (`windows-latest`) : `ruff check`, `mypy`, `pytest`, puis sur une étiquette `v*` un build PyInstaller publié en *release*.
8. **Distribution** : PyInstaller en **onedir** (démarrage instantané, moins de faux positifs) avec un installateur **Inno Setup** qui déclare les associations par utilisateur (HKCU, sans droits admin), et une signature du code si possible.

### 2.2 UI/UX

| Priorité | Modification |
|---|---|
| P0 | **Molette intelligente** dans le lecteur : si la page dépasse l'écran, la molette la fait défiler, et elle ne tourne la page qu'une fois arrivée en bas ou en haut. Accumuler le `pixelDelta` du pavé tactile jusqu'à un seuil avant de tourner. |
| P0 | **Harmoniser les textes** : accents partout, un seul ton (vouvoiement), passage par `QCoreApplication.translate` pour pouvoir traduire (EN) plus tard. |
| P0 | **État vide actionnable** : illustration, texte juste et un gros bouton « Ajouter un dossier ». On peut aussi déposer un dossier sur la fenêtre. |
| P1 | **Aide des raccourcis** (touche `?` ou `F1`) affichée par-dessus le lecteur, groupée par thème. |
| P1 | **Accessibilité** : focus clavier sur l'en-tête et le HUD (`Qt.TabFocus`), anneau de focus visible, `setAccessibleName` sur chaque bouton à icône, contraste AA sur les éléments désactivés. |
| P1 | **Barre d'outils de la bibliothèque** : liste déroulante de tri (Titre / Ajout récent / Lu récemment / Auteur / Année) et pastilles de filtre (Tous / Non lus / En cours / Terminés). |
| P1 | **Panneau de détail** (volet latéral ou fenêtre) sur un tome ou une série : grande couverture, auteur, année, source, progression, temps estimé et actions. Remplace les info-bulles comme source principale d'information. |
| P2 | **Design system** : centraliser les jetons (espacements, rayons, tailles de police, couleurs d'état) dans `theme.py`, générer un QSS global unique et supprimer les couleurs en dur. |
| P2 | **En-tête responsive** : la recherche s'étire (`QSizePolicy.Expanding` avec un maximum), et les actions secondaires passent dans un menu « ⋯ » sous 900 px. |
| P2 | **Touche boss** : `C` seule devient désactivable, ou passe à `Ctrl+Shift+C`. |
| P2 | Erreurs lisibles : message humain + bouton « Détails » + lien vers `beheread.log`. |

### 2.3 Produit : nouvelles fonctionnalités à forte valeur

Classées par rapport valeur/effort :

1. **« Continuer la lecture » (à rétablir)** : bande des tomes en cours et du **prochain tome à lire** de chaque série suivie. Les données existent déjà (`ts`, `_series_featured_index`). *Valeur très haute, effort faible.*
2. **Tri et filtres de statut** (cf. 2.2). *Haute, faible.*
3. **Page de préférences** : sens de lecture par défaut, double page, **métadonnées en ligne (activer/désactiver, avec consentement au premier lancement)**, touche boss, vider les caches, emplacement des données. *Haute, moyen.*
4. **Mode webtoon (défilement vertical continu)**, activé automatiquement pour les manhwa/manhua déjà détectés. *Haute, moyen.*
5. **Édition des métadonnées et gestion des séries** : renommer une série, rattacher un tome à une série par glisser-déposer (l'API `set_series_override` existe déjà), corriger l'auteur ou l'année. *Haute, moyen.*
6. **Instance unique + ouverture transmise** (`QLocalServer`) : corrige B3, et un double-clic dans l'explorateur ouvre le tome dans la fenêtre existante. *Haute, faible.*
7. **Sauvegarde, export et synchronisation** : export/import JSON de la progression, et option « dossier de données » placé dans OneDrive ou iCloud pour synchroniser plusieurs PC (fusion par `ts`). *Moyenne-haute, moyen.*
8. **Statistiques de lecture** : pages et tomes lus, temps total, séries terminées, série de jours consécutifs. Le rythme est déjà mesuré. *Moyenne, faible.*
9. **Support PDF** via `QtPdf` (déjà inclus dans PySide6-Addons), ainsi que CB7 et dossiers d'images. *Moyenne, moyen.*
10. **Suivi AniList** (OAuth) : marquer un tome comme lu met à jour la progression sur AniList. *Haute pour les utilisateurs d'AniList, effort élevé.*
11. **Marque-pages et notes** par page, **filtres d'image** (netteté, mode nuit/sépia), **rotation**. *Moyenne, faible à moyen.*

---

## 3. Plan d'action

### Lot 1 : corrections techniques rapides *(à valider, voir fin de document)*

Petites corrections ciblées, sans changement visible de l'interface, chacune couverte par un test quand c'est possible :

| # | Correction | Fichiers | Risque |
|---|---|---|---|
| Q1 | **B1** : ne purger progression, métadonnées et date d'ajout qu'**après** la réussite de la suppression. L'empreinte est calculée avant, et de nouvelles méthodes `Store.forget_by_key(...)` s'en servent. | `library.py`, `storage.py`, test | Faible |
| Q2 | **B2** : protéger les écritures de `Store` par le verrou, et en cas d'échec de sérialisation remettre le fichier dans `_dirty` puis reprogrammer la sauvegarde (plus aucune perte silencieuse). | `storage.py`, test | Faible |
| Q3 | **P6** : un seul minuteur réarmable au lieu d'un nouveau thread par tour de page. | `storage.py` | Faible |
| Q4 | **B4 + B5** : enregistrer le rythme de lecture de l'ancien lecteur lors de l'enchaînement, et fermer l'archive sous verrou. | `main.py`, `reader.py`, `archive_handler.py` | Faible |
| Q5 | **P1** : vignettes en mémoire dimensionnées selon le DPI réel de l'écran et le zoom maximal, au lieu d'un ×3 fixe (**RAM divisée par 2 à 4**). Le cache disque ne change pas. | `library.py` | Faible |
| Q6 | **P2** : mémoriser l'empreinte par chemin pour la session (invalidée à chaque scan), ce qui supprime les `os.stat` répétés sur le thread UI. | `storage.py`, `lib_workers.py`, test | Moyen |
| Q7 | **B6 + B7** : `_set_entries` et mise à jour de l'index après suppression, et référence gardée sur `_FolderCountWorker`. | `library.py`, `lib_dialogs.py` | Faible |
| Q8 | **P8** : limiteur de débit thread-safe (verrou) dans les trois clients d'API. | `googlebooks.py`, `anilist.py`, `mangadex.py` | Faible |
| Q9 | Nettoyage : imports inutilisés, code mort `ROLE_IS_HEADER`/`HEADER_H`, texte de l'état vide corrigé, docstrings (« 100% local », « filtres de statut ») et README mis à jour (bande « Reprendre » retirée ou marquée à venir). | divers | Nul |
| Q10 | **Outillage** : `pyproject.toml` (configuration ruff + pytest + mypy progressif), `requirements` avec bornes supérieures, workflow GitHub Actions (`ruff` + `pytest` sous Windows), `.pre-commit-config.yaml`. | nouveaux fichiers | Nul |

Estimation : ~1 journée. Tests existants maintenus au vert, nouveaux tests pour Q1, Q2 et Q6.

**État au 27/09/2026 : Q1 à Q9 appliqués, Q10 (outillage) non retenu pour l'instant.**
- Tests : 150 → **157 tests**, tous au vert. Nouveaux tests : suppression et copie partagée, empreintes mémorisées et invalidation, nouvel essai après modification concurrente, sauvegarde différée sans `flush`, lecture sur une archive fermée.
- Test de fumée de l'interface (Qt offscreen) : scan, vignettes, lecteur, enchaînement au tome suivant, fermeture, suppression en échec puis réussie. Couverture en mémoire à 285×402 px au lieu de 570×804 sur un écran à 100 %.
- Écarts par rapport au plan :
  - Pour Q2, les setters restent sans verrou. La sécurité vient d'un **nouvel essai automatique** en cas de `RuntimeError` pendant la sérialisation, et d'un verrou sur l'écriture de `_fp` depuis le `ScanWorker`. Tout faire passer par le thread UI reste prévu au lot 4.
  - Pour Q5, le recadrage et la mise à l'échelle se font désormais dans `ThumbWorker`, hors du thread UI.
  - `Store.remove_added` et la clé de palette `header_bg`, devenus inutilisés, ont été supprimés.

### Lot 2 : UX essentielle (≈ 2 à 3 jours)
Molette intelligente et pavé tactile, harmonisation des textes, état vide actionnable, aide des raccourcis, focus clavier et noms accessibles, instance unique.

**État au 27/09/2026 : fait.** 157 → **172 tests** au vert. Nouveaux fichiers : `tests/test_wheel_nav.py` et `tests/test_single_instance.py`, ce dernier avec un échange réel par pipe local.
- **Molette et pavé tactile** ([core/wheel_nav.py](beheread/core/wheel_nav.py), logique pure testée sans Qt) :
  - une page plus haute que l'écran défile d'abord ;
  - au bord, il faut un cran de plus pour tourner la page (l'élan ne suffit pas) ;
  - la page suivante s'affiche depuis son haut, la précédente depuis son bas ;
  - un glissement de pavé tactile tourne au plus une page ;
  - les molettes haute résolution sont regroupées par crans.

  Flèche bas et Espace font de même ; la flèche haut remonte.
- **Textes** : accents et typographie (« … », guillemets français, « Échap ») sur tous les textes affichés, messages d'erreur d'archive compris. Les journaux techniques restent sans accents. `tr()` n'a **pas** été ajouté : l'intérêt viendra avec une vraie traduction.
- **État vide** : accueil avec bouton « Ajouter un dossier » au premier lancement, « Analyse en cours… », « Aucun manga trouvé » (bouton vers la gestion des dossiers), « Aucun résultat » (bouton « Effacer la recherche »). Correction au passage d'un bug : au premier lancement, **la fenêtre restait vide sans aucun message** (un scan vide ne reconstruisait pas la liste). Glisser-déposer : un dossier est ajouté, un fichier est ouvert.
- **Aide des raccourcis** ([ui/help_overlay.py](beheread/ui/help_overlay.py)) : F1 ou « ? » dans le lecteur (plus une pastille « ? » dans le HUD), F1 ou icône « ? » dans la bibliothèque.
- **Accessibilité** :
  - boutons de l'en-tête et curseur atteignables avec Tab, avec un contour de focus visible (au clavier seulement) ;
  - noms accessibles sur tous les boutons à icône et sur la barre de pages ;
  - anneau de focus clavier sur l'item courant de la grille ou de la liste ;
  - contraste des pastilles désactivées relevé (nouvelle couleur `text_disabled`) ;
  - touche **Suppr** pour supprimer la sélection.

  Les pastilles du HUD du lecteur restent hors du Tab : le lecteur capte toutes les touches, et chaque pastille a déjà son raccourci.
- **Instance unique** ([infra/single_instance.py](beheread/infra/single_instance.py)) : verrou `QLockFile` + canal `QLocalServer`. Une seconde ouverture transmet le fichier (ou une demande d'activation) puis se ferme **avant de charger les données**. Vérifié avec deux vrais processus. Au passage :
  - si l'application a été lancée sur un fichier et qu'on la relance normalement, le lecteur repasse en mode bibliothèque ;
  - un fichier transmis qui ne s'ouvre pas ne ferme plus toute l'application.

### Lot 3 : produit à forte valeur (≈ 1 semaine)
« Continuer la lecture », tri et filtres, page de préférences (avec consentement aux métadonnées en ligne), panneau de détail, gestion manuelle des séries.

**État au 27/09/2026 : fait.** 172 → **192 tests** au vert. La nouvelle logique pure (statuts, tris, sélection « Continuer ») est dans [core/library_model.py](beheread/core/library_model.py), testée sans Qt. Les nouveaux widgets sont dans [ui/library/shelf.py](beheread/ui/library/shelf.py) et [ui/library/detail.py](beheread/ui/library/detail.py), et les dialogues dans [ui/library/dialogs.py](beheread/ui/library/dialogs.py). `LibraryWidget` ne fait que les orchestrer.
- **Continuer la lecture** : tomes en cours et « À suivre » (tome suivant d'une série dont le dernier tome lu est terminé), triés par date de lecture. Un tome masqué y revient s'il est relu.
- **Tri** (titre, ajout, lecture, auteur, année) et **filtres** (Tous / Non lus / En cours / Terminés), mémorisés. Ils s'appliquent aussi aux dossiers de série ; un compteur de tomes est affiché. La position de défilement et l'élément courant sont maintenant **conservés** au retour du lecteur et après une action (avant, la grille revenait en haut). En sortant d'une série, on retrouve sa position à la racine.
- **Panneau d'informations** repliable, avec les actions de l'élément sélectionné.
- **Séries** : déplacer, fusionner, renommer (affichage seul), marquer comme lue, saisie manuelle de l'auteur et de l'année (source « manuelle », prioritaire). Correctif : le dédoublonnage automatique masquait un tome après une fusion manuelle (deux « Tome 1 ») ; les regroupements manuels en sont désormais exclus.
- **Préférences** (Ctrl+,) : thème, panneaux, réglages par défaut du lecteur, fondu désactivable (réduction des animations), touche C et raccourci global Ctrl+Alt+C désactivables (le raccourci est alors rendu aux autres applications), dossier des données, vidage des caches (les saisies manuelles et ComicInfo sont conservées).
- **Consentement aux métadonnées en ligne** : plus aucune requête réseau sans accord. Un bandeau le demande au premier scan. Sans accord, seul ComicInfo.xml est lu, et aucun « introuvable » n'est mis en cache, pour qu'une activation ultérieure relance les recherches.
- **Corrections trouvées au passage** :
  - les couleurs `rgba(...)` de la palette étaient invalides pour `QPainter` : sélection, contour des couvertures et fond des barres étaient peints **en noir opaque**, très visible en thème clair. Corrigé par `theme.qcolor` et un test ;
  - protocole de l'instance unique fiabilisé par un **accusé de réception**. Sous Windows, `waitForBytesWritten` répondait parfois « échec » alors que le message était parti, et une seconde instance aurait pu se lancer ;
  - dans le panneau, un chemin de fichier long élargissait le contenu et coupait les boutons.

### Lot 4 : refonte structurelle (≈ 1 à 2 semaines, en continu)
Package `beheread/`, dataclasses, découpage de `LibraryWidget` et `ReaderWidget`, repositories avec version de schéma, puis SQLite, `pytest-qt`, onedir + Inno Setup.

**État au 27/09/2026 : fait (version 0.2.0).** 256 → **294 tests** au vert (dont 17 tests d'interface pytest-qt), stables sur des exécutions répétées. `ruff` ne signale ni nom indéfini ni import inutile.
- **Package en couches** : `beheread/core` (pur : modèles, séries, statistiques, règles AniList…), `infra` (persistance, archives, réseau, Windows), `services` (suivi AniList), `ui` (bibliothèque, lecteur). Deux dépendances à l'envers ont été supprimées : la persistance dépendait d'une constante d'interface, et la détection de série appelait le scan des dossiers. Points d'entrée : `python -m beheread`, `main.py` conservé.
- **Dataclasses** ([core/models.py](beheread/core/models.py)) : `LibraryEntry` (immuable, relue de façon tolérante depuis l'instantané persisté), `VolumeInfo`, `SeriesInfo`, à la place des dictionnaires non typés. La conversion a révélé des accès oubliés dans des f-strings, corrigés.
- **Découpage** :
  - `LibraryWidget` passe de 2 593 à 923 lignes. Trois contrôleurs sont extraits par composition (scan et surveillance des dossiers, métadonnées, cache de couvertures) et cinq mixins par responsabilité (en-tête et barre d'outils, panneau d'informations, actions, menus, services).
  - `ReaderWidget` passe de 1 554 à 521 lignes : cache de pages en composant autonome, traitements d'image sans état dans `imaging.py`, mixins HUD, fiche de fin, affichage, entrées, séance.
- **SQLite** ([infra/database.py](beheread/infra/database.py)) :
  - une table par dépôt, schéma versionné (`PRAGMA user_version`, migrations) ;
  - écritures transactionnelles et incrémentales (seules les lignes modifiées sont réécrites) ;
  - refus clair d'une base créée par une version plus récente ;
  - import automatique des anciens JSON, ensuite rangés dans `legacy-json/`. **Répétition à blanc sur une copie des vraies données** (35 progressions, 349 et 117 entrées de métadonnées, 326 empreintes, 324 entrées d'instantané) : tout est identique, avant comme après réouverture, et les originaux ne sont pas modifiés.
- **pytest-qt** : état vide, glisser-déposer, couvertures, filtres et tris, « Continuer la lecture », séries (renommage, fusion), suppression en échec, aide, lecteur (progression et statistiques de séance), molette, pavé tactile, PDF, message d'instance unique.
- **Mode dossier + Inno Setup** ([installer/beheread.iss](installer/beheread.iss), `build.bat`) :
  - installation **par utilisateur, sans UAC** ;
  - associations dans le registre de l'utilisateur (CBZ, CBR et EPUB en option, PDF seulement dans « Ouvrir avec ») ;
  - fermeture automatique d'une instance ouverte, désinstallation propre.

  Vérifié réellement : l'installation dans un dossier de test, le lancement de l'app installée et la désinstallation ramènent le registre exactement à son état initial. La seconde instance démarre en 0,5 s contre 2,9 s en exe unique.
- **Défauts corrigés au passage** :
  - le récepteur de connexion AniList pouvait couper la connexion avant sa réponse (corps de requête non lu) ;
  - une page haute n'était plus calée en haut si la fenêtre du lecteur changeait de taille juste après l'ouverture ;
  - le message d'erreur RAR indiquait de placer UnRAR.exe « à côté de main.py », ce qui est faux pour une app installée.
- **Vérification complète (27/09/2026)** : relecture de l'ensemble des lots.
  - Contrôles :
    - fidélité des découpages, vérifiée méthode par méthode sur l'arbre syntaxique ;
    - aucun attribut ni nom indéfini ;
    - tests répétés ;
    - migration à blanc sur une copie des vraies données ;
    - exe reconstruit : ouverture d'un PDF, instance unique ;
    - installation et désinstallation réelles dans un dossier de test : le raccourci du Bureau a été sauvegardé puis restauré à l'identique, et le registre est revenu à son état initial.

    Les données réelles (`%APPDATA%\MangaReaderPy`) n'ont jamais été modifiées.
  - Trois défauts trouvés et corrigés :
    - un **import des anciens JSON** interrompu (erreur disque) n'était jamais retenté : les anciennes données auraient semblé perdues. Un marqueur (table `app_meta`) n'est désormais posé que dans la même transaction que les données ; tant qu'il manque, l'import est retenté au lancement suivant ;
    - une erreur à l'ouverture des données faisait **planter l'app sans message** : un message clair renvoie maintenant vers `beheread.log` ;
    - l'**ancienne installation** (`C:\Program Files\Beheread`, copiée par l'ancien script) reste en place avec son raccourci du Bureau, et elle ne sait pas lire la base SQLite. L'installateur redirige maintenant ce raccourci vers la nouvelle version et signale le dossier à supprimer. Premier essai en échec : l'installateur, programme 32 bits, voit la cible sous la forme « Program Files (x86) ». Les deux formes sont maintenant reconnues, ce qui est vérifié par un test réel.
  - Documentation remise à jour : liens vers les nouveaux emplacements, PDF dans le glisser-déposer et le scan, commande `ruff` explicite. `qt_api = pyside6` est épinglé dans `pytest.ini`.

### Lot 5 : fonctionnalités avancées
Mode webtoon, PDF, statistiques, export et synchronisation, suivi AniList, marque-pages.

**État au 27/09/2026 : PDF, statistiques, export/import et suivi AniList faits.** La synchronisation automatique entre PC, d'abord développée, a été **retirée** à la demande (jugée pas assez fiable) ; seul l'export/import manuel est conservé. Le mode webtoon et les marque-pages restent à faire.
- **PDF** : `PdfArchive` ([infra/archive.py](beheread/infra/archive.py)), choisie automatiquement par `Archive(chemin)`. Pages rendues par QtPdf (déjà fourni avec PySide6) à environ 200 dpi, bornées entre 1 400 et 3 200 px, composées sur fond blanc (PDFium rend un fond transparent). Rendu possible depuis les threads de préchargement. Beheread est ajouté au menu « Ouvrir avec » des PDF sans en devenir le lecteur par défaut.
- **Statistiques** : journal des séances par appareil ([core/stats.py](beheread/core/stats.py), pur ; `stats.json`, puis base SQLite depuis le lot 4). Il compte les pages quittées en avançant, le temps actif hors pauses de plus de 90 s et les tomes terminés pendant la séance. La fenêtre [ui/stats_view.py](beheread/ui/stats_view.py) suit la méthode dataviz : chiffres clés, histogrammes à une teinte, seul le maximum étiqueté, infobulles à la souris et au clavier, bascule en tableau, palette de la répartition validée (daltonisme et contraste) sur les fonds clair et sombre. Les tomes terminés par mois sont calculés à partir de la progression existante, donc remplis dès l'installation.
- **Export / import manuel** ([core/backup.py](beheread/core/backup.py), pur) : pour un tome présent des deux côtés, la progression la plus récente l'emporte, un tome absent est repris (ce qui permet de restaurer une progression effacée). Les statistiques sont regroupées par appareil, donc un import ne compte rien en double. Les réglages locaux ne sont jamais écrasés.
- **Suivi AniList** ([core/anilist_track.py](beheread/core/anilist_track.py), règles pures ; [services/anilist_tracker.py](beheread/services/anilist_tracker.py)) :
  - flux « PIN » officiel avec le client API de l'utilisateur (il n'existe pas de client Beheread enregistré) ;
  - jeton chiffré par DPAPI ([infra/secret_store.py](beheread/infra/secret_store.py)), jamais écrit en clair ni dans le journal ;
  - règles prudentes : jamais de recul de la progression, statuts terminé, en pause et abandonné jamais modifiés, association automatique seulement si le titre correspond clairement (score ≥ 0,6), sinon association manuelle par l'adresse AniList ;
  - file d'attente persistante et nouvel essai en cas d'erreur réseau.

  La recherche AniList renvoie désormais l'identifiant de l'œuvre et un score de ressemblance du titre ; cela répond au point de l'audit sur l'absence de vérification de la correspondance.

  **Révision** : l'utilisateur n'a plus rien à configurer. Le Client ID de l'application est dans la configuration interne ([config.py](beheread/config.py)), renseigné une fois par le développeur. La connexion se fait en un clic : le navigateur revient sur une page locale ([infra/anilist_auth.py](beheread/infra/anilist_auth.py)), limitée à 127.0.0.1, active seulement pendant la connexion et n'acceptant le jeton que depuis sa propre page. L'envoi a lieu à la fin de chaque séance de lecture, seulement si la progression de la série a augmenté. **Uniquement des ajouts** : chaque écriture passe par `anilist_track.is_additive` (champs statut / chapitres / tomes seulement, jamais de recul, transitions de statut limitées à « absente ou à lire → en cours → terminée », statuts terminé / en pause / abandonné / relecture intouchables), revérifiée par `anilist.save_entry`, et le client réseau refuse toute requête de suppression.
- Les préférences sont passées en **onglets** (Général, Lecteur, Données, AniList).
