"""Lecture d'un code-barres EAN-13 (ISBN) dans une image en niveaux de gris
(logique pure, sans Qt ni dependance externe).

La quatrieme de couverture d'un album porte presque toujours l'ISBN en
code-barres : quand un scan l'inclut, le tome est identifie sans ambiguite
(voir metadata._isbn_meta), comme le fait Komga.

Chaque ligne de l'image est binarisee, decoupee en plages claires/sombres
(par expression reguliere, en C : une page se parcourt en quelques
millisecondes), puis chaque suite de 59 plages qui commence par le motif de
garde (barre, espace, barre de meme largeur) est decodee. La somme de
controle de l'EAN-13 ecarte presque tous les faux positifs, et un code n'est
retenu que s'il est lu a l'identique sur plusieurs lignes.
"""

import re
from collections import Counter

THRESHOLD = 128   # en dessous : sombre
ROW_STEP = 4      # une ligne sur ROW_STEP est lue
MIN_READS = 2     # lectures identiques exigees

# largeurs (en modules) des quatre plages de chaque chiffre : codage L
# (espace, barre, espace, barre) ; le codage G est son miroir ; le codage R
# (partie droite : barre, espace, barre, espace) a les memes largeurs que L
_L = {(3, 2, 1, 1): 0, (2, 2, 2, 1): 1, (2, 1, 2, 2): 2, (1, 4, 1, 1): 3, (1, 1, 3, 2): 4,
      (1, 2, 3, 1): 5, (1, 1, 1, 4): 6, (1, 3, 1, 2): 7, (1, 2, 1, 3): 8, (3, 1, 1, 2): 9}
_G = {tuple(reversed(k)): v for k, v in _L.items()}
# parite (L/G) des six chiffres de gauche -> premier chiffre
_FIRST = {"LLLLLL": 0, "LLGLGG": 1, "LLGGLG": 2, "LLGGGL": 3, "LGLLGG": 4,
          "LGGLLG": 5, "LGGGLL": 6, "LGLGLG": 7, "LGLGGL": 8, "LGGLGL": 9}
_RUNS = 59        # 3 (garde) + 24 + 5 (garde centrale) + 24 + 3 (garde)
_RUN = re.compile(rb"0+|1+")
_BINARY = bytes(0x31 if v < THRESHOLD else 0x30 for v in range(256))   # b"1" : sombre


def check_digit_ok(digits) -> bool:
    """Somme de controle d'un EAN-13 (13 chiffres)."""
    if len(digits) != 13:
        return False
    total = sum(d * (3 if i % 2 else 1) for i, d in enumerate(digits[:12]))
    return (10 - total % 10) % 10 == digits[12]


def _digit(widths, table):
    """Chiffre code par 4 largeurs de plages (pixels), ou None."""
    total = sum(widths)
    modules = tuple(max(1, round(w * 7 / total)) for w in widths)
    if sum(modules) != 7:
        return None
    return table.get(modules)


def _decode_runs(runs):
    """Code EAN-13 (chaine de 13 chiffres) lu dans 59 plages commencant par
    une barre, ou None."""
    module = sum(runs) / 95
    # gardes : barre, espace, barre d'un module chacune ; garde centrale
    for i in (0, 1, 2, 56, 57, 58, 27, 28, 29, 30, 31):
        if not 0.4 * module <= runs[i] <= 1.8 * module:
            return None
    digits, parity = [], ""
    for k in range(6):
        widths = runs[3 + 4 * k: 7 + 4 * k]
        d = _digit(widths, _L)
        if d is not None:
            parity += "L"
        else:
            d = _digit(widths, _G)
            if d is None:
                return None
            parity += "G"
        digits.append(d)
    for k in range(6):
        d = _digit(runs[32 + 4 * k: 36 + 4 * k], _L)
        if d is None:
            return None
        digits.append(d)
    first = _FIRST.get(parity)
    if first is None:
        return None
    digits.insert(0, first)
    return "".join(map(str, digits)) if check_digit_ok(digits) else None


def decode_row(row: bytes):
    """Codes EAN-13 lus dans une ligne de pixels (niveaux de gris, un octet
    par pixel), dans les deux sens."""
    runs = [(m.group()[0] == 0x31, m.end() - m.start())
            for m in _RUN.finditer(row.translate(_BINARY))]
    found = []
    for seq in (runs, runs[::-1]):
        for i in range(len(seq) - _RUNS + 1):
            dark, _width = seq[i]
            # debut : une barre precedee d'une zone claire (marge du code)
            if not dark or (i > 0 and seq[i - 1][1] < 3 * seq[i][1]):
                continue
            code = _decode_runs([w for _d, w in seq[i:i + _RUNS]])
            if code:
                found.append(code)
    return found


def decode(rows):
    """ISBN (EAN-13 commencant par 978 ou 979) lu sur au moins MIN_READS des
    lignes fournies, ou None."""
    reads = Counter()
    for row in rows:
        for code in decode_row(row):
            if code.startswith(("978", "979")):
                reads[code] += 1
    if not reads:
        return None
    code, count = reads.most_common(1)[0]
    return code if count >= MIN_READS else None


def encode(code: str):
    """Modules (1 : barre) d'un EAN-13 - pour les tests."""
    digits = [int(c) for c in code]
    parity = next(p for p, d in _FIRST.items() if d == digits[0])
    out = [1, 0, 1]
    for d, p in zip(digits[1:7], parity, strict=True):
        widths = next(k for k, v in (_L if p == "L" else _G).items() if v == d)
        for j, w in enumerate(widths):
            out += [j % 2] * w   # L/G : espace d'abord
    out += [0, 1, 0, 1, 0]
    for d in digits[7:]:
        widths = next(k for k, v in _L.items() if v == d)
        for j, w in enumerate(widths):
            out += [1 - j % 2] * w   # R : barre d'abord
    return out + [1, 0, 1]
