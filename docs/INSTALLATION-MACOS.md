# Installer Beheread sous macOS

Pour les Mac à puce Apple (M1 et plus récents), sous macOS 13 Ventura ou plus récent. Les Mac à processeur Intel ne sont pas pris en charge. Rien d'autre à installer : tout ce dont Beheread a besoin est inclus dans le téléchargement.

Vous êtes sur PC ? Voir [Installer Beheread sous Windows](INSTALLATION-WINDOWS.md).

> **Version macOS récente.** Elle offre les mêmes fonctions et la même interface que sous Windows, à une exception près : le raccourci global `Ctrl+Alt+C`, qui masque Beheread depuis n'importe quelle application, n'existe pas sur Mac (la touche `C` du lecteur, elle, fonctionne). Si quelque chose ne marche pas comme prévu, [signalez-le](https://github.com/codingt0m/beheread/issues) : c'est très utile.

## 1. Télécharger

Ouvrez la page de la [dernière version](https://github.com/codingt0m/beheread/releases/latest) et, dans la liste **Assets** en bas de page, téléchargez `Beheread-x.y.z-macos.dmg`.

Les archives « Source code » de la même liste contiennent le code du projet : elles ne servent pas à utiliser l'application.

## 2. Installer

1. Double-cliquez sur `Beheread-x.y.z-macos.dmg` (dans le dossier Téléchargements) : une fenêtre s'ouvre avec l'icône de Beheread et un raccourci vers le dossier **Applications**.
2. Faites glisser **Beheread** sur **Applications**.
3. Fermez la fenêtre, puis éjectez l'image disque « Beheread » (bouton ⏏ à côté de son nom dans la barre latérale du Finder). Vous pouvez ensuite supprimer le fichier `.dmg`.

## 3. Autoriser le premier lancement

Beheread n'est pas signé par Apple : la signature demande un abonnement payant au programme développeur d'Apple. macOS bloque donc son premier lancement, une seule fois. Ce n'est pas le signe d'un problème ; pour vous assurer que le fichier est bien celui publié ici, voir [Vérifier le téléchargement](#vérifier-le-téléchargement-facultatif).

1. Ouvrez le dossier **Applications** et double-cliquez sur **Beheread**. Un message indique qu'Apple ne peut pas vérifier que Beheread ne contient pas de logiciel malveillant : cliquez sur **Terminé** (ou **OK**).
2. Ouvrez **Réglages Système** (menu  > Réglages Système), puis **Confidentialité et sécurité**.
3. Faites défiler jusqu'à la section **Sécurité** : une ligne indique que « Beheread » a été bloqué. Cliquez sur **Ouvrir quand même**, puis confirmez avec votre mot de passe ou Touch ID.
4. Dans la fenêtre qui suit, cliquez sur **Ouvrir** : Beheread se lance.

Les lancements suivants se font normalement, depuis le Launchpad, Spotlight (`⌘ Espace`, puis « Beheread ») ou le dossier Applications. Pour garder Beheread dans le Dock : clic droit sur son icône dans le Dock > *Options* > *Garder dans le Dock*.

## 4. Premier lancement

1. Sur l'écran d'accueil, cliquez sur **Ajouter un dossier** et choisissez le dossier qui contient vos mangas. Ses sous-dossiers sont parcourus aussi, et vos fichiers ne sont ni déplacés ni modifiés. macOS peut demander l'autorisation d'accéder à ce dossier (Documents, Téléchargements, disque externe…) : cliquez sur **Autoriser**.
2. Un bandeau propose de rechercher en ligne l'auteur et la date de sortie de vos tomes : répondez **Activer** ou **Non merci**. Ce choix se modifie ensuite dans les réglages.
3. Double-cliquez sur une couverture pour lire : le lecteur s'ouvre en plein écran. **F1** (ou `fn F1` sur un clavier de portable) affiche la liste des raccourcis.

Les réglages s'ouvrent par le menu **Beheread > Réglages…** ou `⌘,`.

## Ouvrir vos mangas d'un double-clic

Beheread est proposé dans « Ouvrir avec » pour les fichiers CBZ, CBR, EPUB et PDF. Pour qu'il ouvre toujours un format d'un double-clic :

1. Dans le Finder, sélectionnez un fichier de ce format (par exemple un `.cbz`), puis *Fichier > Lire les informations* (`⌘I`).
2. Dans la section **Ouvrir avec**, choisissez **Beheread**.
3. Cliquez sur **Tout modifier…**, puis sur **Continuer**.

Recommencez pour chaque format voulu (`.cbr`, `.epub`). Pour les PDF, mieux vaut garder Aperçu par défaut et passer par *clic droit > Ouvrir avec > Beheread*.

## Différences avec Windows

L'interface est la même ; seules les touches suivent les habitudes du Mac (la liste des raccourcis, **F1**, les affiche telles qu'elles sont sur votre Mac) :

| Action | Windows | Mac |
|---|---|---|
| Rechercher | Ctrl+F | ⌘F |
| Préférences | Ctrl+, | ⌘, (menu Beheread > Réglages…) |
| Plein écran | F11 | ⌃⌘F |
| Rafraîchir la bibliothèque | F5 | ⌘R |
| Supprimer la sélection | Suppr | ⌘⌫ |
| Zoom à la molette | Ctrl + molette | ⌘ + molette |
| Sélection multiple | Ctrl + clic | ⌘ + clic |
| Masquer la fenêtre (touche « boss ») | C, puis Ctrl+Alt+C pour la réafficher | C masque Beheread ; un clic sur son icône dans le Dock le réaffiche |

Les fichiers supprimés depuis Beheread vont dans la Corbeille du Mac.

## Mettre à jour

Beheread ne se met pas à jour tout seul. Quittez Beheread (`⌘Q`), téléchargez le nouveau `.dmg` et faites glisser Beheread sur **Applications** comme la première fois, en choisissant **Remplacer**. Votre bibliothèque, votre progression et vos réglages sont conservés. macOS peut redemander l'autorisation du premier lancement (étape 3).

## Désinstaller

Faites glisser **Beheread** du dossier Applications vers la Corbeille. Vos données de lecture sont conservées dans le dossier `~/Library/Application Support/Beheread` : pour tout effacer, ouvrez-le depuis le Finder (*Aller > Aller au dossier…*, `⇧⌘G`, collez ce chemin) et supprimez-le. Si vous étiez connecté à AniList, déconnectez-vous d'abord dans les réglages : l'accès, rangé dans le Trousseau de macOS, est alors effacé.

## Lire les fichiers CBR

Les CBZ, EPUB et PDF fonctionnent sans rien d'autre, ainsi que la plupart des CBR : Beheread utilise l'outil de décompression fourni avec macOS.

Si un fichier `.cbr` particulier refuse de s'ouvrir (« Aucun outil de décompression RAR n'a été trouvé » ou erreur de lecture), installez 7-Zip, que Beheread utilise alors en priorité. Avec [Homebrew](https://brew.sh/), dans le Terminal :

```
brew install sevenzip
```

## Vérifier le téléchargement (facultatif)

Chaque version publie un fichier `SHA256SUMS-macos.txt`. Dans le Terminal :

```
shasum -a 256 ~/Downloads/Beheread-x.y.z-macos.dmg
```

L'empreinte affichée doit être celle de `SHA256SUMS-macos.txt`.

## Passer d'un PC Windows à un Mac

Sur le PC, dans *Préférences > Données*, cliquez sur **Exporter…** : un fichier de sauvegarde est créé avec votre progression, vos statistiques et vos réglages de séries. Copiez-le sur le Mac, puis dans *Réglages > Données*, cliquez sur **Importer…**. Les tomes sont reconnus par leur contenu : peu importe où se trouvent les fichiers sur le Mac. Ajoutez ensuite vos dossiers de mangas ; les dossiers et les préférences d'affichage ne sont pas repris d'un ordinateur à l'autre.

## Dépannage

* **Beheread est bloqué au premier lancement** : voir [Autoriser le premier lancement](#3-autoriser-le-premier-lancement).
* **« Beheread est endommagé et ne peut pas être ouvert »** : le téléchargement a peut-être été modifié en route ; téléchargez-le de nouveau depuis la page des versions et [vérifiez-le](#vérifier-le-téléchargement-facultatif). Si le message persiste avec un fichier vérifié, ouvrez le Terminal et tapez `xattr -dr com.apple.quarantine /Applications/Beheread.app`, puis relancez Beheread.
* **Un dossier de mangas reste vide** : vérifiez dans *Réglages Système > Confidentialité et sécurité > Fichiers et dossiers* que Beheread a accès à ce dossier.
* **Un fichier iCloud Drive n'apparaît pas** : s'il n'est pas téléchargé sur le Mac (icône de nuage dans le Finder), Beheread l'ignore pour ne pas bloquer en le téléchargeant ; cliquez sur le nuage dans le Finder pour le télécharger.
* **Autre comportement anormal** : consultez `beheread.log` dans `~/Library/Application Support/Beheread`, toutes les erreurs y sont consignées.
* **Signaler un problème** : ouvrez une [issue](https://github.com/codingt0m/beheread/issues), en précisant que vous êtes sur Mac et en joignant si possible les lignes concernées de `beheread.log`.
