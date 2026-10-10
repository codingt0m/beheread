# Guide d'utilisation de Beheread

Ce guide détaille toutes les fonctions de Beheread. Pour l'installation et la prise en main, voir le [README](../README.md).

* [La bibliothèque](#la-bibliothèque)
* [Métadonnées (auteur, date de sortie)](#métadonnées-auteur-date-de-sortie)
* [Le lecteur](#le-lecteur)
* [Sauvegarde et suivi AniList](#sauvegarde-et-suivi-anilist)
* [Progression et données](#progression-et-données)

## La bibliothèque

En haut de la bibliothèque, un en-tête unique regroupe tout : logo et titre à gauche (un clic ramène à la racine de la bibliothèque), barre de recherche exactement au centre de la fenêtre, puis à droite le curseur de taille des couvertures et les boutons à icônes (gérer les dossiers sources, rafraîchir, statistiques, préférences). Chaque bouton affiche son rôle au survol. Le thème clair/sombre, la vue grille/liste, le regroupement par série, le panneau d'informations et la liste des raccourcis se règlent dans les préférences.

Fonctions de la bibliothèque :

* **Gérer les dossiers sources** (icône dossier + engrenage) : ouvre un panneau listant les dossiers de la bibliothèque avec leur nombre de mangas. On y ajoute un répertoire contenant vos CBZ/CBR/EPUB/PDF (scan récursif, sous-dossiers inclus) ou on en retire un (les fichiers ne sont pas touchés). Les changements s'appliquent à la validation.
* **Rafraîchir** (icône flèche circulaire, ou F5) : rescanne les dossiers après ajout de nouveaux fichiers. La bibliothèque se rafraîchit aussi **automatiquement** quand un fichier CBZ/CBR/EPUB/PDF est ajouté, déplacé ou supprimé dans un dossier source (ou l'un de ses sous-dossiers) ; le bouton reste utile en secours.
* **Recherche** (raccourci Ctrl+F pour y placer le curseur) : le champ de recherche filtre instantanément, à chaque frappe, par nom de fichier, nom de série (y compris un nom renommé à la main), auteur et titres connus de l'œuvre (titre anglais, romaji ou original trouvé par AniList ou MangaDex : « Attack on Titan » trouve « L'Attaque des Titans »). L'auteur et les titres viennent des [métadonnées](#métadonnées-auteur-date-de-sortie) récupérées en arrière-plan : juste après l'ajout d'un dossier, ils peuvent mettre quelques instants à arriver, et les résultats se complètent alors d'eux-mêmes.
  * Tous les mots tapés doivent être trouvés, dans n'importe quel champ et dans n'importe quel ordre : `fujimoto fire`, `berserk 12`.
  * Les accents, majuscules et la ponctuation sont ignorés : `pokemon` trouve « Pokémon », `gloutons dragons` trouve « Gloutons & Dragons ».
  * Un mot peut n'être qu'un morceau de mot (`saw` trouve « Chainsaw Man ») ; un nombre, lui, désigne un numéro exact : `berserk 1` trouve le tome 1 (« Berserk T01 »), pas les tomes 10 à 19.
  * Faute de frappe : si rien ne correspond exactement, les mots proches sont acceptés (`fujimotto`, `berzerk`) et le compteur indique « résultats approchants ».
  * En mode regroupé, les résultats sont les **dossiers de série** concernés (le compteur donne le nombre de tomes correspondants) ; un dossier ouvert pendant une recherche ne montre que ses tomes correspondants. Taper une recherche depuis un dossier ouvert cherche dans toute la bibliothèque ; effacer la recherche ramène à l'endroit quitté.
* **Continuer la lecture** : une bande en haut de la bibliothèque propose les tomes en cours et, pour chaque série entamée dont le dernier tome lu est terminé, le **tome suivant** (« À suivre »), du plus récent au plus ancien. Un clic reprend la lecture. Clic droit : masquer un tome de la bande (il y revient s'il est relu), réinitialiser sa progression ou le marquer comme lu. Masquable dans les préférences.
* **Trier et filtrer** : sous l'en-tête, « Trier par » (titre, ajout récent, lu récemment, auteur, année de sortie) et des filtres de statut **Tous / Non lus / En cours / Terminés** ; le nombre de tomes affichés s'affiche à droite. Un tome refermé sur l'une de ses trois premières pages (couverture, page de garde) n'est pas considéré comme commencé : il reste « non lu » et sa progression est effacée à la sortie du lecteur. En mode regroupé, les dossiers de série suivent le même tri et le même filtre ; à l'intérieur d'une série, les tomes restent dans l'ordre de lecture.
* **Panneau d'informations** (à activer dans *Préférences > Général*, masqué par défaut) : couverture, auteur, année, source, statut, nombre de pages, temps de lecture estimé, dates d'ajout et de lecture, taille et emplacement du fichier de l'élément sélectionné, avec ses actions (Lire / Reprendre / Relire, marquer lu, modifier…). Pour une série : « Continuer : Tome N », ouvrir, marquer comme lue, renommer, fusionner.
* **Gestion manuelle des séries** (clic droit ou panneau d'informations) : **Déplacer vers une série…** (choisir une série existante ou en créer une), **Fusionner avec une autre série…**, **Renommer la série…** (nom affiché uniquement, les fichiers ne sont pas touchés) et **Modifier les informations…** (auteur, année ; une saisie manuelle est prioritaire et conservée). Un tome placé à la main dans une série n'est jamais masqué comme doublon.
* **Préférences** (icône engrenage, ou Ctrl+,), en onglets : *Général* (thème, vue grille ou liste, couleur d'accentuation, regroupement par série, bande « Continuer la lecture », panneau d'informations, touche C et raccourci global Ctrl+Alt+C, métadonnées en ligne), *Lecteur* (sens de lecture, ajustement, double page, Ambilight, fondu entre les pages), *Données* (export/import, dossier des données, vidage des caches), *AniList* (connexion et suivi), *Raccourcis* (tous les raccourcis clavier de la bibliothèque et du lecteur).
* **Couleur d'accentuation** (*Préférences > Général*) : le rouge d'origine peut être remplacé par une des couleurs proposées ou par une couleur libre (« Personnalisée… ») ; « Réinitialiser » revient au rouge. Elle s'applique au logo, au titre, aux boutons, aux barres de progression, aux icônes actives et aux graphiques. Une couleur trop claire (thème clair) ou trop sombre (thème sombre) est ajustée juste assez pour rester lisible ; si elle est verte, « terminé » passe au bleu pour rester distinct de « en cours ». L'icône de l'exécutable, des raccourcis et des fichiers associés, lue par Windows dans Beheread.exe, garde sa couleur d'origine.
* **Statistiques** (icône histogramme) : une période au choix en tête de fenêtre (**7 jours / 30 jours / 12 mois / Tout**) gouverne tous les chiffres, et la ligne sous le titre rappelle ses dates et ce à quoi elle est comparée. Pour cette période : le temps de lecture en chiffre principal, puis pages lues, tomes terminés et jours de lecture, chacun avec son écart à la période précédente de même durée et une mini-tendance ; le temps de lecture par jour (ou par mois) ; les séries les plus lues, regroupées et nommées comme dans la bibliothèque actuelle ; un calendrier de régularité (une case par jour, d'autant plus soutenue que la lecture a été longue) avec la série de jours en cours et le record ; la liste des derniers tomes terminés. À part, l'état de la bibliothèque (non lus / en cours / terminés) et le temps qu'il reste à lire à votre rythme. Chaque graphique affiche la valeur au survol (ou aux flèches du clavier) et l'histogramme peut basculer en tableau. L'écran s'ouvre en plein écran (« Fermer » ou Échap pour revenir à la bibliothèque) et tout y tient sans défilement : les cartes occupent la hauteur disponible, leurs listes n'affichent que les lignes qui y tiennent, et sur un écran trop bas la rangée du bas (régularité, tomes terminés, bibliothèque) est retirée. Règles de mesure (rappelées en infobulle par « Méthode de mesure ») : une page compte comme lue après 1 s d'affichage (feuilleter ou faire glisser la barre de défilement ne compte pas), le temps de lecture ignore les pauses de plus de 90 s, et un tome est terminé quand sa dernière page est atteinte dans le lecteur (« Marquer comme lu » n'est pas une lecture). Les tomes terminés avant l'existence du journal de lecture y sont repris à la date de leur dernière lecture.
* **PDF** : les PDF des dossiers sources apparaissent dans la bibliothèque comme les autres tomes (vignette, progression, séries). Les pages sont rendues à la demande en haute résolution, sur fond blanc. Un PDF protégé par mot de passe n'est pas pris en charge.
* **Démarrage immédiat (hors-ligne)** : la bibliothèque s'affiche instantanément au lancement à partir du dernier instantané connu, pendant que le scan réel des dossiers se fait en arrière-plan (l'interface reste réactive, même sur un dossier réseau).
* **Regrouper par série** (*Préférences > Général*) : détecte les tomes d'un même manga d'après leur nom de fichier (ex. "One Piece - Tome 12.cbz") et les rassemble dans un **dossier de série** (pile de couvertures, le tome en cours ou le prochain à lire au-dessus). Double-clic pour entrer dans le dossier (tomes triés par numéro), Échap / Retour arrière ou le bouton de retour pour en sortir. Une recherche montre les dossiers de série dont un tome correspond (voir **Recherche**). Sans regroupement, la bibliothèque est triée par ordre alphabétique.
* **Vue Grille / Liste** (*Préférences > Général > Affichage*) : grille de vignettes ou liste compacte plus dense.
* **Sélection multiple** (Ctrl/Maj + clic) pour appliquer une action à plusieurs mangas d'un coup. La touche **Suppr** supprime la sélection (après confirmation).
* **Glisser-déposer** : déposer un dossier sur la fenêtre l'ajoute à la bibliothèque ; déposer un fichier CBZ/CBR/EPUB/PDF l'ouvre directement.
* **Premier lancement** : tant qu'aucun dossier n'est configuré, un écran d'accueil propose un bouton « Ajouter un dossier ».
* **Aide** (F1, ou *Préférences > Raccourcis*) : liste de tous les raccourcis clavier. Les boutons de l'en-tête sont accessibles au clavier (Tab), avec un contour de focus visible, et nommés pour les lecteurs d'écran.
* Les vignettes utilisent la première image de chaque archive et sont mises en cache pour un affichage instantané aux lancements suivants.
* Sous chaque couverture : la page en cours et le total. Barre de la couleur d'accentuation (rouge par défaut) = lecture en cours, barre verte + badge = terminé. Une couverture légèrement grisée indique un manga marqué comme lu.
* L'auteur, une fois récupéré (voir ci-dessous), s'affiche sous la vignette (grille) ou sur la ligne de sous-titre (vue liste), et apparaît aussi au survol dans l'info-bulle avec la date de sortie et la source.
* Double-clic sur une vignette pour ouvrir le manga (il reprend exactement à la dernière page lue). Le lecteur s'ouvre dans sa **propre fenêtre**, toujours en plein écran, distincte de la bibliothèque (qui repasse en arrière-plan pendant la lecture et réapparaît à la fermeture du lecteur).
* Clic droit sur une ou plusieurs vignettes sélectionnées pour :
  * **Réinitialiser la progression** : remet le suivi de lecture à zéro.
  * **Marquer comme lu** : déclare le(s) manga(s) terminé(s) (couverture grisée, badge vert).
  * **Marquer comme non lu** : annule un marquage « terminé » (accidentel ou non) sans perdre la page en cours. Proposé uniquement sur des tomes actuellement marqués terminés.
  * **Recharger les métadonnées** : oublie l'auteur/la date en cache (et le résultat AniList associé à la série) pour relancer la recherche à zéro. Utile si une recherche précédente n'a rien trouvé, s'est trompée, ou a échoué faute de réseau.
  * **Renommer le fichier...** / **Afficher dans l'explorateur** (sélection simple) : la progression, les métadonnées et la vignette suivent le fichier renommé.
  * **Sortir de la série** / **Rétablir le regroupement automatique** : isole un tome mal regroupé, ou annule ce choix.
  * **Supprimer le manga...** : envoie le(s) fichier(s) dans la corbeille de Windows (récupérables), après confirmation obligatoire. Si la corbeille n'est pas utilisable, la suppression est définitive et la fenêtre de confirmation le précise clairement. Si la suppression échoue (fichier ouvert ailleurs, droits), la progression du tome est conservée.
* Clic droit sur un dossier de série : **Supprimer la série** (tous ses tomes, après confirmation listant les fichiers).

## Métadonnées (auteur, date de sortie)

**Consentement.** La recherche en ligne n'est faite qu'avec votre accord : au premier scan, un bandeau propose de l'activer (« Activer » / « Non merci ») ; le choix se modifie ensuite dans les Préférences. Tant qu'elle n'est pas activée, seules les informations ComicInfo.xml contenues dans les fichiers sont utilisées, et aucune donnée ne quitte l'ordinateur.

Une fois la recherche en ligne activée, dès qu'un dossier est ajouté ou rafraîchi, l'auteur et la date de sortie de chaque manga sont récupérés automatiquement en arrière-plan. L'auteur s'affiche sous la vignette (grille) ou en sous-titre (liste), apparaît au survol dans l'info-bulle (avec la date de sortie et la source), et devient exploitable par la recherche (le champ en haut filtre aussi par auteur). La récupération utilise une stratégie en cascade, du plus fiable/local au plus incertain :

1. **ComicInfo.xml** (priorité 1, 100% hors ligne) : si l'archive contient un fichier `ComicInfo.xml` (standard ComicRack/ComicTagger) à sa racine, ses champs `Writer`/`Penciller`/`Author`, `Year`/`Month`/`Day` sont utilisés directement : aucune requête réseau n'est faite si ces informations suffisent.
2. **Google Books** (priorité 2) : à défaut, recherche combinant le nom de série (déduit du nom de fichier) et le numéro de tome, pour retrouver la date de sortie de l'édition physique précise (la couverture affichée reste toujours la première page de l'archive, aucune image externe n'est utilisée).
3. **AniList** (priorité 3) : si Google Books ne trouve rien, recherche sur le seul nom de série via l'API AniList (GraphQL, gratuite), qui gère bien les titres traduits/synonymes (y compris français). Le résultat, propre à la série, est alors partagé par tous ses tomes. AniList renvoyant toujours une œuvre, même sans rapport, son résultat n'est retenu que si son titre ressemble vraiment au nom cherché.
4. **MangaDex** (priorité 4) : si AniList ne trouve rien non plus, recherche sur le seul nom de série via l'API MangaDex (catalogue plus large : œuvres de niche, séries indépendantes/françaises, webtoons...). Comme AniList, le résultat est propre à la série et partagé par tous ses tomes ; MangaDex expose aussi la langue d'origine, utilisée pour affiner la détection automatique du sens de lecture (manga/manhwa/manhua).
5. **BnF** (priorité 5, dernier recours) : pour ce qui n'est pas un manga (bande dessinée franco-belge, comics), recherche du nom de série dans le catalogue de la Bibliothèque nationale de France (API publique, gratuite). Sa notice indique aussi le format du livre (album de BD ou manga), utilisé pour le sens de lecture.

Chaque couche n'est interrogée que si la précédente n'a rien donné d'exploitable. Le résultat (avec sa source) est mis en cache localement (base `beheread.db`) : un tome/une série n'est interrogé qu'une seule fois.

Limites à connaître :
* Google Books, AniList et MangaDex ne documentent pas forcément un tome précis dans une édition française : la date obtenue via un repli série (AniList/MangaDex) est celle de la première publication de la série entière, pas du tome lu.
* La recherche se base sur le nom de fichier ; un titre traduit qui ne correspond à rien d'indexé peut ne rien trouver, ou (rarement) trouver la mauvaise œuvre.
* Nécessite une connexion internet pour les couches 2 à 5. Sans connexion (ou en cas d'erreur), l'application continue de fonctionner normalement : l'auteur reste simplement vide pour les mangas concernés, et la recherche sera retentée à la prochaine session (les échecs réseau ne sont pas mis en cache, contrairement aux recherches sans résultat).
* L'API Google Books sans clé a un quota anonyme assez bas et partagé par adresse IP (des erreurs "trop de requêtes" sont possibles sur certains réseaux) ; l'application se rabat alors automatiquement sur AniList, MangaDex puis la BnF.
* Les requêtes sont volontairement espacées pour rester polies envers ces API publiques ; l'auteur affiché se remplit progressivement au fur et à mesure que les réponses arrivent.

**Détection de série.** basée sur le nom de fichier : marqueurs "Tome", "T", "Vol", "#", "Chapitre", "Cycle" (intégrales de BD), numéro suivi du titre de l'album ("Astérix - 38 - La Fille de Vercingétorix"), ou numéro final. Ce qui suit le numéro (titre de l'album, auteur, langue, groupe de release) ne fait pas partie du nom de série. Un fichier sans nom de série ("Tome 01.cbz", "Volume 1.cbz") prend celui de son dossier ("Berserk/Tome 01.cbz"). Les tomes s'affichent sous un titre propre ("Berserk · Tome 1"), le nom de fichier complet restant visible dans l'info-bulle et le panneau d'informations. Un auteur entre parenthèses dans le nom ("Monster T01 (Urasawa)") aide à reconnaître la bonne œuvre quand plusieurs portent le même titre. Un fichier sans numéro détecté reste affiché individuellement. À la fin d'un tome, si un tome suivant est détecté dans le même dossier, le lecteur propose d'enchaîner directement dessus (touche Entrée) sans repasser par la bibliothèque.

## Le lecteur

| Action | Commande |
|---|---|
| Page suivante | Flèche bas, Espace, molette bas, flèche droite*, clic zone droite* (voir « Molette » ci-dessous) |
| Page précédente | Flèche haut, retour arrière, molette haut, flèche gauche*, clic zone gauche* |
| Avancer/reculer d'une seule page (utile en double page) | PgDown / PgUp |
| Première / dernière page | Début / Fin |
| Basculer simple page / double page | D |
| Basculer mode manga (droite → gauche) / mode normal (gauche → droite) | M |
| Décaler la parité en double page (couverture seule ↔ couplée) | S |
| Changer l'ajustement (hauteur ↕ / largeur ↔) | F, ou bouton à double flèche de la barre de réglages |
| Recadrage automatique des marges (rogne les bords vides du scan) | R |
| Ambilight : fond teinté par la couleur de la page (désactivé par défaut) | A, ou *Préférences > Lecteur* |
| Zoom | + / - ou Ctrl + molette, 0 pour réinitialiser |
| Déplacer l'image quand elle dépasse (zoom, ajustement largeur) | glisser avec la souris |
| Quitter / reprendre le plein écran (actif à l'ouverture) | F11, ou bouton en haut à droite |
| Masquer instantanément la fenêtre (touche « boss »), puis la réafficher | C pour masquer ; Ctrl+Alt+C pour masquer/réafficher depuis n'importe où |
| Tome suivant (si détecté, en fin de tome) | Entrée, ou bouton de la fiche de fin |
| Retour à la bibliothèque | Échap, ou bouton "← Bibliothèque" en haut à gauche |
| Aide : liste des raccourcis | F1 ou ? (aussi dans *Préférences > Raccourcis*) |
| Sauter directement à une page | clic ou glisser sur la barre de défilement en bas de l'écran (le survol affiche un aperçu de la page visée) |

\* Flèche/clic gauche et droite sont inversés en mode manga, puisque la lecture s'y fait de droite à gauche.

**Molette, pavé tactile et flèches haut/bas.** Quand la page est plus haute que l'écran (zoom, ajustement à la largeur, webtoon), la molette, la flèche bas et Espace la font d'abord **défiler** ; arrivé en bas, un cran de plus tourne la page, et la page suivante s'affiche depuis son haut (en remontant, la page précédente s'affiche depuis son bas). L'élan qui amène au bord ne tourne jamais la page à lui seul. Sur un **pavé tactile**, un glissement tourne au plus une page (l'inertie est ignorée) ; les molettes haute résolution sont regroupées par crans entiers.

Par défaut, le lecteur démarre en **mode manga** et en **double page** : la page 1 s'affiche à droite, la page 2 à sa gauche, et "page suivante" fait progresser vers la gauche. Les réglages du lecteur (double page, recadrage, ajustement, décalage, Ambilight) sont **communs à tous les mangas** : un choix fait dans un tome se retrouve à l'ouverture de n'importe quel autre, et d'une session à l'autre. Seul le **sens de lecture** fait exception : il est détecté automatiquement (pays d'origine connu d'AniList ou de MangaDex, format BD ou manga indiqué par la BnF, sinon champ `Manga` de ComicInfo.xml, sinon sens par défaut des préférences), et celui que vous choisissez avec `M` est mémorisé pour la série (ou pour le tome s'il est isolé), sans changer le sens par défaut. L'ajustement « hauteur » montre toujours la page entière (elle est réduite si elle dépasserait en largeur) ; l'ajustement « largeur » occupe toute la largeur de l'écran.

En double page, une image déjà plus large que haute (planche double scannée en une seule image) est détectée automatiquement et affichée seule, sans être couplée à sa voisine.

Chaque changement de page est adouci par un fondu enchaîné rapide (~130ms).

**Décalage de parité (touche S).** Beaucoup de scans placent une couverture en première page, ce qui décale toutes les doubles pages : les planches qui se répondent ne se retrouvent jamais côte à côte. La touche `S` bascule la parité de l'appairage : la couverture s'affiche alors seule et les paires suivantes se recalent correctement. Le choix vaut pour tous les mangas, comme les autres réglages du lecteur.

**Recadrage automatique des marges (touche R).** Les scans embarquent souvent des marges blanches (ou noires) inégales qui gâchent l'ajustement et désalignent les deux planches en double page. La touche `R` détecte et rogne ces bords vides pour agrandir la surface utile. En double page, les deux planches partagent le **même niveau de recadrage** (la marge la plus faible des deux sur chaque bord, c'est-à-dire le recadrage le moins agressif), afin de rester alignées et à la même échelle. Le préréglage est mémorisé entre les sessions.

**Ambilight (touche A).** Teinte le fond du lecteur avec la couleur moyenne (assombrie) de la page affichée, avec un fondu doux à chaque changement de page, un effet d'ambiance proche des téléviseurs Ambilight. **Désactivé par défaut**, activable dans *Préférences > Lecteur* ou d'un appui sur `A` pendant la lecture ; le choix est mémorisé entre les sessions.

**Interface auto-masquable.** Le HUD, les boutons et la barre de défilement s'effacent après quelques secondes d'inactivité de la souris, pour une lecture sans distraction. Ils réapparaissent au moindre mouvement de souris, mais jamais lors d'un simple changement de page au clavier, afin de ne pas interrompre la lecture.

**Estimation du temps restant.** Après quelques tours de page, le HUD affiche une estimation du temps de lecture restant dans le tome (« ~18 min restantes »), calculée sur votre rythme de la session (les longues pauses sont ignorées).

**Fiche de fin de tome.** À la dernière page, une fiche récapitulative s'affiche : couverture, nombre de pages, temps de lecture de la session, et un bouton pour enchaîner sur le tome suivant (s'il est détecté) ou revenir à la bibliothèque. Le bouton **Marquer comme lu sur Babelio** ouvre la recherche de ce tome sur babelio.com dans votre navigateur : Beheread ne s'y connecte pas et n'y publie rien (Babelio n'offre pas d'API), c'est vous qui le marquez « lu » sur votre compte.

**Touche « boss » (C).** Un appui sur `C` masque instantanément la fenêtre de lecture (elle reste dans la barre des tâches). Le raccourci global `Ctrl+Alt+C` la masque et la réaffiche depuis n'importe quelle application, pratique pour dissimuler sa lecture d'une seule touche.

## Sauvegarde et suivi AniList

**Sauvegarde** (*Préférences > Données*). *Exporter…* écrit un fichier JSON avec la progression, les statistiques, les regroupements et renommages de séries, les sens de lecture et les informations saisies à la main. *Importer…* fusionne ce fichier, par exemple pour passer à un autre PC ou restaurer une progression effacée : pour un tome présent des deux côtés, la progression la plus récente l'emporte, un tome absent est repris, et vos réglages actuels ne sont jamais écrasés (seuls les éléments absents sont ajoutés). Les mêmes fichiers de mangas sont reconnus d'un PC à l'autre par leur contenu, quel que soit leur emplacement ; les dossiers sources et les préférences ne sont pas repris.

**Suivi AniList.** Dans *Préférences > AniList*, un clic sur **Se connecter à AniList…** ouvre le navigateur sur la page d'autorisation d'AniList ; une fois Beheread autorisé, la connexion se termine toute seule (aucun code à copier). L'accès est chiffré sur ce PC (protection Windows DPAPI, liée à votre session), reste valable un an et peut être révoqué à tout moment depuis les réglages du compte AniList.

Ensuite, **à la fin de chaque séance de lecture** (fermeture du lecteur ou passage au tome suivant) et quand un tome est marqué « lu » dans la bibliothèque, Beheread met à jour la série sur votre liste : nombre de tomes lus (ou de chapitres pour les fichiers numérotés par chapitre), série ajoutée « en cours » si elle n'y était pas, « terminée » quand le dernier tome connu d'AniList est lu. Rien n'est envoyé si la progression de la série n'a pas augmenté depuis le dernier envoi. **Beheread ne fait qu'ajouter** : il ne supprime jamais une entrée de votre liste, ne fait jamais reculer une progression et ne touche à aucun autre champ (note, commentaires, dates, relectures…). Une série que vous avez marquée terminée, en pause, abandonnée ou en relecture n'est **jamais modifiée**. Chaque envoi est vérifié juste avant de partir, et aucune requête de suppression ne peut être émise.

Chaque série est associée automatiquement à son œuvre AniList quand le titre trouvé correspond clairement au nom de la série ; sinon, le panneau d'informations indique « à associer » : *Associer à AniList…* accepte l'adresse de la page AniList de la série (ex. `https://anilist.co/manga/30002/Berserk`). *Ne pas suivre sur AniList* exclut une série. Sans réseau, les mises à jour restent en attente et sont renvoyées plus tard.

**One-shots.** Un tome sans numéro qui n'appartient à aucune série (« Errance.cbz ») est publié « 1 tome lu, terminée » une fois lu, à condition que l'œuvre AniList associée existe en **un seul tome** : sinon, impossible de savoir quel tome a été lu, et le panneau d'informations indique « œuvre en plusieurs tomes : rien publié ». Une erreur publiant « terminée » sur une œuvre sans rapport, l'association automatique d'un one-shot exige un titre quasi identique ; à défaut, *Associer à AniList…* le fait à la main. Un tome détaché de sa série, ou placé à la main dans une série sans numéro, n'est jamais publié.

## Progression et données

La dernière page lue de chaque manga est enregistrée automatiquement à chaque changement de page et à la fermeture. Un manga est marqué "Terminé" quand la dernière page est atteinte.

Données stockées localement dans `%APPDATA%\MangaReaderPy` (nom historique du projet, conservé pour ne pas perdre les données existantes) :
* `beheread.db` : base SQLite (réglages, progression, métadonnées, empreintes, statistiques, instantané de la bibliothèque), au schéma versionné. Les écritures sont transactionnelles (une coupure de courant ne peut pas laisser un fichier à moitié écrit) et incrémentales (seules les données modifiées sont réécrites) ;
* `beheread-v1.bak` : copie de la base faite automatiquement avant la migration vers le schéma 2 (journal de lecture en table SQL) ; elle permet de revenir à une version antérieure de Beheread et peut être supprimée ensuite ;
* `legacy-json\` : les anciens fichiers JSON des versions 0.1, importés automatiquement dans la base au premier lancement de la version 0.2 puis rangés ici par sécurité (ils ne sont plus relus ; ce dossier peut être supprimé) ;
* `instance.lock` : présent tant que Beheread est ouvert (instance unique)
* `beheread.log` : journal de diagnostic
* `thumbnails\` : cache des couvertures (JPEG)

**Identité par contenu.** La progression, les métadonnées et les vignettes sont rattachées à une **empreinte du contenu** de chaque fichier (sa taille et ses premiers kilo-octets), et non à son chemin sur le disque. Concrètement : renommer ou déplacer un tome **conserve sa progression**, et deux copies identiques la partagent. Les anciennes données indexées par chemin sont migrées automatiquement au premier lancement (les vignettes se régénèrent une fois à cette occasion). Les empreintes sont mises en cache dans la base pour rester instantanées aux lancements suivants.

Les sauvegardes sont regroupées puis écrites en arrière-plan (elles ne bloquent pas la lecture, même en tournant les pages rapidement) et garanties à la fermeture de l'application.

**Instance unique.** Beheread ne s'exécute qu'une fois : double-cliquer un autre fichier dans l'explorateur (ou relancer l'application) l'ouvre dans la fenêtre existante au lieu de lancer un second processus, qui écraserait la progression de l'autre. Le fichier `instance.lock` de ce dossier matérialise l'instance en cours (un verrou laissé par un plantage est repris automatiquement).

Supprimer ce dossier réinitialise l'application. Aucune donnée ne quitte votre machine sans votre accord : seulement, si vous les activez, les requêtes de métadonnées (nom de série et numéro de tome envoyés à Google Books, AniList, MangaDex et la BnF) et les mises à jour de votre liste AniList (nombre de tomes/chapitres lus par série).
