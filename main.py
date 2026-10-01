"""Point d'entree de PyInstaller (voir beheread.spec) et de `python main.py`.
Le code vit dans le package beheread/ ; voir beheread/app.py."""

from beheread.app import main

if __name__ == "__main__":
    main()
