"""Logique pure de la molette / du pave tactile dans le lecteur (aucune
dependance Qt, testee isolement comme pairing.py).

Probleme resolu : autrefois chaque evenement de molette tournait une page.
* Une page zoomee ou ajustee a la largeur, plus haute que l'ecran, ne pouvait
  donc pas defiler a la molette (seulement au glisser).
* Un pave tactile envoie des dizaines d'evenements par glissement : chacun
  tournait une page, rendant la navigation incontrolable.
* Une souris haute resolution envoie des fractions de cran : meme effet.

Regles appliquees :
1. Si la page depasse de l'ecran, la molette la fait d'abord defiler.
2. Arrive au bord, il faut un nouveau cran (souris) ou un nouveau geste (pave
   tactile) pour tourner la page : l'elan qui amene au bord ne tourne jamais
   la page a lui seul.
3. Les fractions de cran s'accumulent jusqu'a un cran complet ; un glissement
   de pave tactile tourne au plus UNE page, inertie comprise.
"""

NOTCH = 120              # angleDelta d'un cran de molette classique
SCROLL_PX = 110          # defilement par cran dans une page qui depasse
TOUCHPAD_FLIP_PX = 140   # glissement cumule (pixels) pour tourner une page
RESET_S = 0.45           # pause qui remet a zero l'accumulation
GESTURE_GAP_S = 0.25     # pause marquant la fin d'un geste de pave tactile
MOUSE_EDGE_GAP_S = 0.15  # pause exigee au bord avant qu'un cran tourne la page


class WheelNavigator:
    def __init__(self):
        self._accum = 0.0
        self._last = float("-inf")
        self._edge_hold = float("-inf")
        self._gesture_used = False

    def feed(self, dy, touchpad, now, scroll):
        """Traite un evenement de molette.

        dy       : angleDelta().y() (souris) ou pixelDelta().y() (pave
                   tactile) ; negatif = vers le bas (vers la suite).
        touchpad : True si l'evenement porte un pixelDelta.
        now      : horodatage monotone en secondes.
        scroll   : fonction(px) -> bool qui fait defiler la page de `px`
                   pixels (negatif = vers le bas) et renvoie True si elle a
                   effectivement bouge (False : pas de depassement, ou deja au
                   bord dans ce sens).

        Renvoie "next", "prev" ou None (rien a faire de plus)."""
        if not dy:
            return None
        gap = now - self._last
        self._last = now
        if gap > RESET_S:
            self._accum = 0.0
        if self._accum and (self._accum > 0) != (dy > 0):
            self._accum = 0.0   # changement de sens

        if touchpad and self._gesture_used:
            if gap < GESTURE_GAP_S:
                return None     # fin du glissement ou inertie : deja utilise
            self._gesture_used = False

        px = dy if touchpad else dy / NOTCH * SCROLL_PX
        if scroll(px):
            self._accum = 0.0
            self._edge_hold = now
            return None

        # au bord (ou page entierement visible) : la rotation/le geste qui a
        # amene au bord ne doit pas tourner la page dans la foulee
        hold = GESTURE_GAP_S if touchpad else MOUSE_EDGE_GAP_S
        if now - self._edge_hold < hold:
            self._edge_hold = now
            return None

        self._accum += dy
        if abs(self._accum) >= (TOUCHPAD_FLIP_PX if touchpad else NOTCH):
            self._accum = 0.0
            if touchpad:
                self._gesture_used = True
            return "next" if dy < 0 else "prev"
        return None
