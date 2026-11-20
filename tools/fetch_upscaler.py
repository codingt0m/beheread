"""Recupere le moteur d'upscaling (Real-ESRGAN ncnn-vulkan, licence BSD-3)
dans beheread/resources/upscaler/, d'ou PyInstaller l'embarque avec les
autres ressources (voir beheread.spec). Le dossier n'est pas versionne.

    python tools/fetch_upscaler.py            # systeme courant
    python tools/fetch_upscaler.py macos      # windows | macos | linux

Seuls l'executable, sa bibliotheque OpenMP (Windows) et le modele utilise
(AnimeVideo v3 x2) sont gardes, avec les licences de Real-ESRGAN et de ncnn.
Chaque fichier telecharge est verifie par sa somme SHA-256 : une archive
modifiee en ligne fait echouer le build au lieu d'etre embarquee.

Lance par build.bat et packaging/macos/build.sh ; sans lui, Beheread
fonctionne mais l'upscaling est indique comme indisponible."""

import hashlib
import io
import shutil
import sys
import urllib.request
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DEST = ROOT / "beheread" / "resources" / "upscaler"

_RELEASE = "https://github.com/xinntao/Real-ESRGAN/releases/download/v0.2.5.0/"
ARCHIVES = {
    "windows": ("realesrgan-ncnn-vulkan-20220424-windows.zip",
                "abc02804e17982a3be33675e4d471e91ea374e65b70167abc09e31acb412802d",
                ["realesrgan-ncnn-vulkan.exe", "vcomp140.dll"]),
    "macos": ("realesrgan-ncnn-vulkan-20220424-macos.zip",
              "e0ad05580abfeb25f8d8fb55aaf7bedf552c375b5b4d9bd3c8d59764d2cc333a",
              ["realesrgan-ncnn-vulkan"]),
    "linux": ("realesrgan-ncnn-vulkan-20220424-ubuntu.zip",
              "e5aa6eb131234b87c0c51f82b89390f5e3e642b7b70f2b9bbe95b6a285a40c96",
              ["realesrgan-ncnn-vulkan"]),
}
MODEL_FILES = ["models/realesr-animevideov3-x2.param", "models/realesr-animevideov3-x2.bin"]
LICENSES = {
    "LICENSE-Real-ESRGAN.txt": (
        "https://raw.githubusercontent.com/xinntao/Real-ESRGAN/v0.2.5.0/LICENSE",
        "4a699ec4863d96a91fc265948a0c90033f7e8735d515524dcf3444736406e0c2"),
    "LICENSE-ncnn.txt": (
        "https://raw.githubusercontent.com/Tencent/ncnn/20220420/LICENSE.txt",
        "6495f972a09ad7f64ccd953e79adba91a93d862edc7135e6d95210bbf4002a01"),
}


def _download(url, sha256):
    with urllib.request.urlopen(url, timeout=120) as resp:   # URL fixe (https), contenu verifie ci-dessous
        data = resp.read()
    digest = hashlib.sha256(data).hexdigest()
    if digest != sha256:
        raise SystemExit(f"Somme SHA-256 inattendue pour {url} :\n  {digest}\n  attendue {sha256}")
    return data


def current_platform():
    if sys.platform == "win32":
        return "windows"
    return "macos" if sys.platform == "darwin" else "linux"


def fetch(platform):
    name, sha256, binaries = ARCHIVES[platform]
    data = _download(_RELEASE + name, sha256)
    if DEST.exists():
        shutil.rmtree(DEST)
    (DEST / "models").mkdir(parents=True)
    with zipfile.ZipFile(io.BytesIO(data)) as z:
        for member in binaries + MODEL_FILES:
            target = DEST / member
            target.write_bytes(z.read(member))
            if member in binaries:
                target.chmod(0o755)
    for filename, (url, sha) in LICENSES.items():
        (DEST / filename).write_bytes(_download(url, sha))
    print(f"Moteur d'upscaling ({platform}) dans {DEST}")


if __name__ == "__main__":
    fetch(sys.argv[1] if len(sys.argv) > 1 else current_platform())
