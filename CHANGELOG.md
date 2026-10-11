# Notes de version

Les numéros de version suivent [SemVer](https://semver.org/lang/fr/). Chaque section ci-dessous sert aussi de notes à la release GitHub du même numéro.

## [Non publié]

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
* **Corrigé** : un album nommé « Série - Tome 4 - Titre de l'album », ou un fichier au nommage « scène » (« Chainsaw.Man.T20.Fujimoto.FR.[CBZ]-NoTag »), formait sa propre série au lieu de rejoindre les autres tomes.

### Babelio

* **Nouveau** : la fiche de fin de tome peut proposer « Marquer comme lu sur Babelio » (option des préférences, désactivée par défaut), qui ouvre la recherche du tome dans le navigateur. Babelio n'ayant pas d'API, Beheread n'y publie rien.

### Suivi AniList

* **Nouveau** : les one-shots (« Errance ») sont publiés « 1 tome lu, terminée » une fois lus, quand l'œuvre AniList existe en un seul tome. Leur association automatique exige un titre quasi identique.

### Bibliothèque

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
* L'enregistrement de la progression ne dépend plus de la taille de la bibliothèque : seules les données modifiées sont écrites. La base de données est réorganisée au premier lancement (une copie de l'ancienne est gardée à côté), puis entretenue à la fermeture.

### Lecture des fichiers

* Les CBR compressés en mode « solide » se lisent aussi vite à la fin qu'au début : leurs pages sont extraites une fois, en arrière-plan, au lieu d'être décompressées à nouveau à chaque page.
* Les EPUB suivent l'ordre de lecture déclaré par le livre, même quand le nom de leurs images ne dit rien de cet ordre.
* Les pages ajoutées par les équipes de traduction en fin de scan (« zzz-credits », pages de recrutement) ne sont plus comptées comme des pages du tome.

### Corrections

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
