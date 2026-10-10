# Vérifier une version macOS sur un vrai Mac

La CI construit l'application macOS, la lance et capture son interface à chaque push (voir [DEVELOPPEMENT.md](DEVELOPPEMENT.md#intégration-continue)). Ce qui suit ne se vérifie que sur un vrai Mac, avec une souris, un trackpad et le Finder. À dérouler avant de publier une version macOS, ou à confier à un testeur.

**Récupérer l'application à tester** : le `.dmg` d'une release, ou celui de la dernière exécution de la CI (onglet *Actions* du dépôt > *CI* > exécution > artefact *Beheread-macos*, à dézipper). Préparer quelques mangas : des CBZ, au moins un vrai CBR (RAR), un EPUB et un PDF.

Pour chaque point, noter ✅ ou ce qui se passe à la place. En cas de problème, joindre le fichier `~/Library/Application Support/Beheread/beheread.log`.

## Installation

- [ ] Le `.dmg` s'ouvre et montre Beheread et un raccourci Applications ; glisser Beheread dessus l'installe.
- [ ] Premier lancement : macOS bloque Beheread ; *Réglages Système > Confidentialité et sécurité > Ouvrir quand même* permet de le lancer, comme décrit dans [le guide](INSTALLATION-MACOS.md#3-autoriser-le-premier-lancement). Noter le texte exact des messages s'il diffère du guide.
- [ ] Les lancements suivants se font sans avertissement (Launchpad, Spotlight, Dock).
- [ ] L'icône de Beheread s'affiche dans le Dock, le Finder et le Launchpad.

## Bibliothèque

- [ ] Ajouter un dossier de mangas (y compris dans Documents ou Téléchargements : macOS demande l'autorisation, la bibliothèque se remplit ensuite).
- [ ] Les couvertures sont nettes sur un écran Retina.
- [ ] Recherche (`⌘F`), tris, filtres (Tous / Non lus / En cours / Terminés), regroupement par série.
- [ ] Sélection multiple avec `⌘` + clic et `⇧` + clic ; clic droit (ou clic à deux doigts) ouvre le menu.
- [ ] *Afficher dans le Finder* ouvre le Finder, le fichier sélectionné.
- [ ] Supprimer un tome (`⌘⌫` ou menu) : il part dans la Corbeille du Mac et peut en être restauré.
- [ ] `⌘R` rafraîchit ; glisser-déposer un dossier l'ajoute, un fichier l'ouvre.
- [ ] Menu **Beheread** : *À propos de Beheread*, *Réglages…* (`⌘,`), *Masquer*, *Quitter* (`⌘Q`) fonctionnent.
- [ ] **F1** (ou `fn F1`) affiche les raccourcis avec les touches du Mac (⌘F, ⌃⌘F…).
- [ ] Le défilement de la grille au trackpad est fluide.

## Lecteur

- [ ] Double-clic sur une couverture : le lecteur s'ouvre en plein écran (bureau à part, barre de menus et Dock masqués).
- [ ] Pages : flèches, Espace, molette, **trackpad** (défilement à deux doigts) ; `⌘` + molette zoome.
- [ ] Double page (`D`), sens manga (`M`), recadrage (`R`), ajustement (`F`), Ambilight (`A`).
- [ ] `⌃⌘F` et le bouton en haut à droite quittent et reprennent le plein écran.
- [ ] **Échap** ou *Bibliothèque* : on revient à la bibliothèque **sans écran noir** (la sortie du plein écran est animée, puis la bibliothèque s'affiche).
- [ ] Ouvrir un second tome après être revenu à la bibliothèque : même comportement.
- [ ] Fin de tome : la fiche s'affiche ; *Tome suivant* enchaîne dans le même plein écran.
- [ ] Touche **C** : Beheread disparaît ; un clic sur son icône du Dock le fait revenir, toujours en plein écran sur la bonne page.
- [ ] Un vrai CBR (RAR) s'ouvre sans rien installer ; un EPUB et un PDF aussi.

## Finder et fichiers

- [ ] Avec Beheread fermé : double-clic sur un `.cbz` (après l'avoir associé, voir [le guide](INSTALLATION-MACOS.md#ouvrir-vos-mangas-dun-double-clic)) ouvre **directement le lecteur**, sans la bibliothèque ; le fermer quitte Beheread.
- [ ] Avec Beheread ouvert : double-clic sur un autre fichier l'ouvre dans la fenêtre existante.
- [ ] *Clic droit > Ouvrir avec* propose Beheread pour CBZ, CBR, EPUB et PDF.
- [ ] Un fichier iCloud Drive non téléchargé (icône de nuage) est ignoré sans bloquer l'application.

## Données et réseau

- [ ] *Réglages > Données > Ouvrir le dossier des données* ouvre `~/Library/Application Support/Beheread`.
- [ ] Une sauvegarde exportée depuis Windows s'importe : la progression des mêmes tomes est reprise.
- [ ] Métadonnées en ligne : activées, les auteurs arrivent.
- [ ] AniList : la connexion passe par le navigateur et se termine seule ; dans *Trousseau d'accès*, un élément « Beheread » apparaît ; la déconnexion le retire.
- [ ] Quitter puis relancer : la progression et les réglages sont conservés.
