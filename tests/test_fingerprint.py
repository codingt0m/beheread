"""Tests de l'empreinte de contenu (fingerprint.py). Purement algorithmique,
sans acces disque : la lecture du fichier reste dans storage.py."""

from beheread.core import fingerprint


def test_known_value_never_changes():
    # changer la definition changerait l'identite de tous les tomes (progression,
    # journal, metadonnees) : cette valeur, calculee avec l'ancien code de
    # storage.py (sha1 de la taille ecrite en decimal puis de la tete), est figee
    assert (fingerprint.content_fingerprint(5, b"hello")
            == "c1:6bd4d7c29aedc3e14dfbebc45a6df9b7118f7c5c")


def test_prefix_and_length():
    key = fingerprint.content_fingerprint(10, b"0123456789")
    assert key.startswith(fingerprint.PREFIX)
    assert len(key) == len(fingerprint.PREFIX) + 40


def test_size_is_part_of_identity():
    head = b"x" * 100
    assert fingerprint.content_fingerprint(100, head) != fingerprint.content_fingerprint(200, head)


def test_only_head_bytes_count():
    head = b"a" * fingerprint.HEAD_BYTES
    assert (fingerprint.content_fingerprint(1 << 20, head + b"b")
            == fingerprint.content_fingerprint(1 << 20, head + b"c"))
