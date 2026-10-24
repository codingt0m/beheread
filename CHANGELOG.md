# Notes de version

Les numéros de version suivent [SemVer](https://semver.org/lang/fr/). Chaque section ci-dessous sert aussi de notes à la release GitHub du même numéro.

## [Non publié]

### Statistiques

* **Statistiques par série** : un clic sur une série du classement (ou « Statistiques de la série » dans son menu) ouvre sa page : temps passé, tomes lus, rythme comparé à votre moyenne, reste à lire avec une fin estimée, une étagère case par case (terminés, en cours, non lus, non possédés), la progression dans le temps, le temps de chaque tome et quelques repères.
* Le temps restant à lire d'un tome ou de la bibliothèque tient compte du rythme propre à chaque série, quand elle a assez été lue.
* Écran Statistiques : barres du classement à l'échelle de 100 %, « Jours de lecture préférés » à la place du calendrier sur 7 et 30 jours, dernier tome terminé à la place de la mini-tendance, carte Bibliothèque allégée (détail du calcul dans l'infobulle ⓘ). Sur un écran bas, la fenêtre défile au lieu de masquer des cartes.
* Bilan de l'année : tomes et chapitres comptés à part dans les séries, durées arrondies à l'heure la plus proche (1 h 59 s'affiche « 2 h »), couleur d'accent toujours lisible sur l'image sombre.

## [1.3.0] - 2026-10-23

### Tomes et chapitres

* Les séries qui mélangent tomes et chapitres sont mieux gérées : les chapitres complètent les tomes. La bibliothèque compte les tomes et les chapitres à part (« 22 tomes · 22 chapitres »), l'avancement suit l'ordre de lecture (« Tome 6/22 · puis ch. 211 à 232 », « Tomes lus · chapitre 213 en cours ») et la lecture enchaîne du dernier tome au premier chapitre qui le suit.
* Dans une série ouverte, les chapitres forment une section à part, « Suite en chapitres », en cases plus petites. Chaque chapitre indique le tome officiel qui le contient, quand on le connaît.
* Le découpage officiel en tomes (MangaDex) masque les chapitres déjà contenus dans un tome possédé, et signale les chapitres manquants à partir de la fin du dernier tome.
* **Tomes virtuels** : des chapitres peuvent être regroupés en un tome, lu d'une traite, sans modifier les fichiers (sélection de chapitres › « Regrouper en tome… »). Quand tous les chapitres d'un tome officiel sont là, le tome virtuel est créé tout seul, avec sa couverture officielle ; quand le tome officiel arrive, il prend sa place et la lecture est conservée.
* Clic droit sur une série › « Publiée en » : tomes, chapitres ou détection automatique.
* Les statistiques et le récapitulatif de l'année comptent les chapitres à part des tomes.
* Dans un tome virtuel, la barre de progression du lecteur marque d'un point le début de chaque chapitre, et le chapitre en cours s'affiche.
* Un fichier nommé « Vol.22 Ch.199 » est reconnu comme le chapitre 199 (et non plus comme le tome 22) ; le tome qu'il indique complète le découpage officiel quand celui-ci est incomplet.
* Les livres d'un serveur Komga ou Kavita dont le titre indique un chapitre sont traités comme des chapitres, et les tomes virtuels fonctionnent aussi pour eux.

### Métadonnées des BD, comics et mangas français

* Les comics ne sont plus confondus avec un manga homonyme : la BnF, interrogée en premier, dit de quelle langue l'œuvre est traduite. « Saga », « Batman », « Invincible » ou « Sandman » sont reconnus comme des comics (bon auteur, lecture de gauche à droite), les albums franco-belges comme des BD (« Largo Winch » n'est plus lu de droite à gauche), et les mangas restent confiés à AniList et MangaDex.
* Les BD ont désormais leur nombre de tomes parus (donc leurs tomes manquants), la date de chaque tome, l'éditeur d'origine et un résumé ; l'année affichée est celle du premier tome, plus celle d'une réédition.
* Wikidata départage les homonymes quand la BnF ne connaît pas la série, et sert de source à défaut (« Lastman »).
* L'ISBN imprimé en code-barres sur la quatrième de couverture d'un scan identifie le tome exact.
* `ComicInfo.xml` est mieux exploité (nombre de tomes, genres, résumé, ISBN), ainsi que les métadonnées des EPUB (série, numéro, sens de lecture) et le `series.json` de Mylar, comme dans Komga.
* Les œuvres pour adultes d'AniList ne sont plus associées à une série d'un autre genre portant le même nom.
* Les métadonnées déjà trouvées en ligne sont vérifiées à nouveau en arrière-plan.

### Bibliothèque

* Nouveau : déplacer des tomes, des chapitres ou une série vers un autre dossier de la bibliothèque (par exemple vers iCloud Drive), sous-dossier, lecture et réglages conservés.
* « Choisir la couverture… » propose la couverture officielle du tome (MangaDex).
* Les éditions au découpage différent (Perfect, Deluxe, Intégrale, tomes doubles…) ne sont plus comparées au nombre de tomes de l'édition courante : plus de faux tomes manquants. Le nombre de tomes parus de votre édition peut aussi être saisi dans « Modifier les informations… ».
* Séries en cours : les tomes parus au Japon après votre dernier tome, et les chapitres parus depuis votre dernier chapitre, apparaissent dans la grille.
* Le bandeau « Il vous manque… » est retiré : les manquants se voient dans la grille, et leur affichage se règle dans les préférences.
* **Corrigé** : l'auteur trouvé sur AniList pouvait être un assistant (Fire Punch attribué à Tatsuya Endo).
* **Corrigé** : la fenêtre des préférences pouvait dépasser de l'écran ; ses onglets défilent désormais.

## [1.2.0] - 2026-10-15

### Quel fichier télécharger

* `Beheread-Setup-1.2.0.exe` : l'installateur Windows, recommandé. Il remplace la version en place et conserve vos données.
* `Beheread-1.2.0-windows-x64.zip` : la version Windows sans installation, à dézipper où vous voulez.
* `SHA256SUMS.txt` : les sommes de contrôle des deux fichiers Windows.
* `Beheread-1.2.0-macos.dmg` : la version Mac (puce Apple, macOS 13 ou plus récent), avec ses sommes de contrôle dans `SHA256SUMS-macos.txt`.

### Sécurité

* **Corrigé** (Windows) : ouvrir un CBR téléchargé pouvait lancer un faux `unrar.exe` placé dans le même dossier. Beheread ne lance plus que les outils de décompression trouvés à leur emplacement connu, et jamais un programme du dossier du fichier ouvert.
* **Corrigé** : un titre ou un auteur piégé (ComicInfo.xml d'une archive, base de données en ligne) pouvait être interprété comme du HTML et faire charger une image distante, ce qui pouvait exposer des informations de connexion Windows. Ces textes sont désormais toujours affichés tels quels.
* **Corrigé** : à la connexion AniList, Beheread affiche le nom du compte et demande confirmation avant de l'enregistrer : un autre site ouvert dans le navigateur ne peut plus y substituer son propre compte.
* **Corrigé** : pendant la connexion à AniList, un autre site ouvert dans le navigateur pouvait faire afficher un message piégé par la fenêtre de connexion. Ce message est désormais toujours affiché tel quel.
* **Corrigé** : une sauvegarde abîmée ou modifiée ne peut plus rendre la bibliothèque inutilisable : les valeurs inattendues qu'elle contient sont ignorées à l'import.
* **Corrigé** (Windows) : sur un PC partagé, un autre compte ne peut plus intercepter les fichiers que vous ouvrez par double-clic quand Beheread est déjà lancé.
* Les métadonnées XML (ComicInfo.xml, BnF) sont contrôlées quel que soit leur encodage, et la publication des versions est mieux cloisonnée : les dépendances de l'application sont figées et vérifiées par empreinte.

### Fiabilité

* **Corrigé** : une modification faite juste avant de quitter Beheread (progression, réglage) pouvait ne pas être enregistrée, ou être remplacée par une valeur plus ancienne.
* **Corrigé** : double-cliquer un fichier pendant que Beheread était occupé pouvait lancer une seconde copie de l'application, qui écrasait une partie des réglages de la première. Beheread demande désormais de patienter.
* **Corrigé** : la vérification du compte AniList et l'association manuelle d'une série ne figent plus l'interface pendant la requête.
* **Corrigé** : une réponse inattendue d'une base en ligne pouvait suspendre le suivi AniList ou la recherche d'auteur jusqu'au redémarrage.
* **Corrigé** : un tome qui n'avait pas pu s'ouvrir restait verrouillé (impossible à renommer ou supprimer) jusqu'à la fermeture de Beheread.
* La recherche du tome suivant ne parcourt plus que le dossier du tome, et non ses sous-dossiers (lent depuis un dossier de téléchargements ou la racine d'un disque).

### Version macOS (nouveau)

* **Nouveau** : Beheread existe pour Mac (puce Apple, macOS 13 ou plus récent), avec les mêmes fonctions et la même interface que sous Windows. Téléchargez `Beheread-x.y.z-macos.dmg` et suivez le [guide d'installation macOS](https://github.com/codingt0m/beheread/blob/main/docs/INSTALLATION-MACOS.md) : l'application n'étant pas signée par Apple, macOS demande une autorisation au premier lancement.
* Les touches suivent les habitudes du Mac (⌘F, ⌘, pour les réglages, ⌃⌘F pour le plein écran, ⌘⌫ pour supprimer) ; la liste des raccourcis (F1) affiche celles de votre système.
* Les CBR s'ouvrent sans rien installer, avec l'outil de décompression fourni avec macOS.
* Une sauvegarde exportée sous Windows s'importe sur Mac, et inversement : la progression suit vos tomes d'un ordinateur à l'autre.
* Seule différence : le raccourci global `Ctrl+Alt+C` n'existe pas sur Mac ; la touche `C` du lecteur masque Beheread, un clic sur son icône du Dock le fait revenir.
* **Corrigé** : dans les statistiques, un ancien tome terminé venu d'une sauvegarde d'un autre système affichait son chemin complet au lieu de son titre.
* Les guides d'installation sont désormais séparés : [Windows](https://github.com/codingt0m/beheread/blob/main/docs/INSTALLATION-WINDOWS.md) et [macOS](https://github.com/codingt0m/beheread/blob/main/docs/INSTALLATION-MACOS.md).

### Serveurs de lecture (nouveau)

* **Nouveau** : Beheread lit les tomes d'un serveur Komga, Kavita ou OPDS, page par page, sans les copier sur l'ordinateur. L'option est désactivée par défaut (*Préférences > Serveurs*) ; une fois un serveur ajouté, l'en-tête de la bibliothèque permet de passer de « Sur cet ordinateur » à vos serveurs.
* Avec Komga et Kavita, la progression est synchronisée : la page atteinte est renvoyée au serveur à la fin de chaque séance, et une lecture plus avancée faite sur un autre appareil est reprise.
* Le mot de passe ou la clé d'API est protégé comme la connexion AniList, et n'est jamais envoyé ailleurs qu'à l'adresse du serveur.

### Interface en anglais (nouveau)

* **Nouveau** : Beheread existe en anglais. Le choix se fait dans *Préférences > Général > Langue* : « Celle du système » (par défaut : français si Windows ou macOS est en français, anglais sinon), Français ou English. Beheread redémarre de lui-même pour l'appliquer.
* Les dates, les nombres, les tailles de fichiers et le journal de lecture exporté en CSV suivent la langue choisie.
* En français, les boutons et fenêtres fournis par le système d'affichage (Oui / Non, choix d'un fichier) sont désormais eux aussi en français.

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

* Les réglages du lecteur (double page, ajustement, recadrage, décalage) sont retenus pour chaque série : un tome d'une série déjà réglée retrouve ses réglages, les autres séries reprennent le dernier choix fait.
* En double page, l'appairage se recale tout seul après une planche double : la page suivante commence une nouvelle paire, comme dans le livre imprimé.
* Un tome refermé sur sa page 1, 2 ou 3 n'est plus considéré comme commencé : sa progression est effacée à la sortie du lecteur, et il n'apparaît ni « en cours » ni dans « Continuer la lecture ». Un tome déjà terminé le reste.
* **Corrigé** : avec le recadrage automatique, une page simple aux grandes marges (haut et bas) passait pour une planche double une fois rognée : elle s'affichait seule et décalait l'appairage de toutes les pages suivantes. Une planche double est désormais reconnue sur l'image d'origine.
* **Corrigé** : appuyer plusieurs fois sur « Décalage » faisait reculer d'une page à chaque appui. Les appuis alternent maintenant entre deux vues, et la touche agit aussi après une planche double (le décalage ne vaut alors que pour cette partie du tome, pour la lecture en cours).
* **Corrigé** : le temps de lecture estimé était environ deux fois trop court. Le rythme est maintenant le temps total passé divisé par les pages lues, d'après le journal de lecture des six derniers mois (les coups d'œil de quelques pages n'y comptent pas) ; le temps restant du lecteur suit la même moyenne.
* **Corrigé** : un album nommé « Série - Tome 4 - Titre de l'album », ou un fichier au nommage « scène » (« Chainsaw.Man.T20.Fujimoto.FR.[CBZ]-NoTag »), formait sa propre série au lieu de rejoindre les autres tomes.

### Babelio

* **Nouveau** : la fiche de fin de tome peut proposer « Marquer comme lu sur Babelio » (option des préférences, désactivée par défaut), qui ouvre la recherche du tome dans le navigateur. Babelio n'ayant pas d'API, Beheread n'y publie rien.

### Suivi AniList

* **Nouveau** : les one-shots (« Errance ») sont publiés « 1 tome lu, terminée » une fois lus, quand l'œuvre AniList existe en un seul tome. Leur association automatique exige un titre quasi identique.

### Bibliothèque

* **Nouveau** : « Bilan de l'année » (fenêtre des statistiques) résume votre année de lecture en une image à partager : temps de lecture, tomes terminés, jour de lecture préféré, record de jours d'affilée, séries les plus lues, mois par mois.
* **Nouveau** : Beheread peut vérifier une fois par jour si une nouvelle version est publiée (Préférences > Général, désactivé par défaut) et l'annoncer par un bandeau. Rien n'est installé sans vous.
* **Nouveau** : « Choisir la couverture… » (clic droit sur un tome) remplace la couverture par une autre page du tome ou par une image de votre ordinateur, sans modifier le fichier.
* **Nouveau** : le panneau d'informations montre les genres et le résumé de l'œuvre (en français quand MangaDex en a un), ainsi que le nombre de tomes parus et possédés.
* **Nouveau** : une série ouverte indique les tomes que vous n'avez pas (« Il vous manque 3 tomes : 6, 12, 29 à 36 ») et peut les montrer à leur place dans la grille.
* **Nouveau** : le journal de lecture s'exporte en CSV (Préférences > Données), pour Excel, LibreOffice ou Google Sheets.
* **Nouveau** : les mots qui désignent les pages de crédits des équipes de traduction se règlent dans Préférences > Données.
* **Nouveau** : un tome illisible (fichier incomplet ou abîmé, outil RAR manquant) est signalé sur sa vignette ; « Voir l'erreur… » dans le menu contextuel explique le problème et permet de réessayer ou de montrer le fichier.
* **Nouveau** : quand la recherche de l'auteur et de l'année échoue, le panneau d'informations l'indique, avec l'heure du prochain essai automatique et un bouton « Réessayer maintenant ».
* **Nouveau** : le panneau « Dossiers de la bibliothèque » indique la place occupée par les mangas de chaque dossier (« 283 mangas · 12,4 Go »).

### Performances

* Le lecteur affiche ses pages sans attendre la fin de la génération des couvertures de la bibliothèque, et les tours de page restent fluides avec le recadrage des marges ou l'Ambilight.
* Le zoom (molette, `+` / `-`) suit le geste sans à-coups ; la page redevient nette dès la fin du geste.
* Les couvertures, l'aperçu de la barre de défilement et la préparation du tome suivant sont plus rapides à produire.
* Le retour du lecteur à la bibliothèque est instantané : seuls les tomes lus sont mis à jour, au lieu de toute la grille.
* Dans une grande bibliothèque, seules les couvertures à l'écran sont préparées, et la mémoire qu'elles occupent est plafonnée ; les auteurs des tomes affichés sont cherchés en premier.
* Les auteurs arrivent bien plus vite au premier remplissage d'une grande bibliothèque : chaque série n'est plus cherchée qu'une fois en ligne, au lieu d'une fois par tome.
* Une recherche d'auteur qui a échoué (réseau, service saturé) est retentée dans la session, après 5, 15 puis 60 minutes, au lieu d'attendre le prochain lancement. Beheread respecte les pauses demandées par les services en ligne.
* L'analyse des dossiers lit chaque dossier une seule fois, et un fichier ajouté ou retiré ne fait plus relire que son dossier, plus toute la bibliothèque : nettement plus rapide sur un disque réseau ou une grande bibliothèque.
* Le défilement de la bibliothèque est plus fluide : les cases et les couvertures sont préparées une seule fois, au lieu d'être redessinées à chaque pas.
* L'enregistrement de la progression ne dépend plus de la taille de la bibliothèque : seules les données modifiées sont écrites. La base de données est réorganisée au premier lancement (une copie de l'ancienne est gardée à côté), puis entretenue à la fermeture.

### Lecture des fichiers

* Les CBR compressés en mode « solide » se lisent aussi vite à la fin qu'au début : leurs pages sont extraites une fois, en arrière-plan, au lieu d'être décompressées à nouveau à chaque page.
* Les EPUB suivent l'ordre de lecture déclaré par le livre, même quand le nom de leurs images ne dit rien de cet ordre.
* Les pages ajoutées par les équipes de traduction en fin de scan (« zzz-credits », pages de recrutement) ne sont plus comptées comme des pages du tome.

### Corrections

* **Corrigé** : dans « Continuer la lecture », la ligne de progression sous le titre était coupée.
* **Corrigé** : dans les statistiques, les boutons de période (7 jours, 30 jours, 12 mois, Tout) n'avaient pas leurs extrémités arrondies.
* **Corrigé** : une série dont la fiche en ligne compte moins de tomes que vous n'en possédez (œuvre parue en un volume au Japon et en trois en France, comme *Léviathan*) affichait « 3 possédés sur 1 ». Ce nombre, faux pour votre édition, est désormais ignoré. « 1 tome paru » s'accorde aussi au singulier.

* **Corrigé** (Windows) : supprimer un tome juste après son apparition dans la bibliothèque pouvait échouer (« fichier utilisé par un autre processus ») pendant que Beheread préparait sa couverture.
* **Corrigé** : supprimer une copie d'un tome présent en double effaçait la progression de l'autre copie.
* **Corrigé** : la mémoire du lecteur grossissait sans limite en feuilletant un tome dans les deux sens.
* **Corrigé** : un tome terminé pendant un envoi à AniList pouvait ne jamais être publié.
* **Corrigé** : une requête refusée par AniList déconnectait le compte.
* **Corrigé** (Windows) : sur un écran à 200 %, les cases à cocher de l'installateur (tâches, « Lancer Beheread ») étaient rognées.

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
