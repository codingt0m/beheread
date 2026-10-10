"""Tests de beheread.platforms : chaque implementation (Windows, macOS,
repli) expose la meme interface, et la facade secret_store relit les valeurs
de toutes les plateformes."""

import importlib
import os
from pathlib import Path

import pytest

from beheread import platforms
from beheread.infra import secret_store

IMPLEMENTATIONS = ["windows", "macos", "generic"]


@pytest.mark.parametrize("name", IMPLEMENTATIONS)
def test_every_implementation_exposes_the_whole_api(name):
    # importable sur tous les systemes : les appels natifs sont faits a l'usage
    module = importlib.import_module(f"beheread.platforms.{name}")
    missing = [n for n in platforms.API if not hasattr(module, n)]
    assert missing == []
    assert module.NAME == name


@pytest.mark.parametrize("name", IMPLEMENTATIONS)
def test_rar_tools_lists_paths_by_kind(name, tmp_path):
    module = importlib.import_module(f"beheread.platforms.{name}")
    tools = module.rar_tools(tmp_path)
    assert set(tools) == {"unrar", "sevenzip", "bsdtar"}
    assert all(isinstance(p, Path) for paths in tools.values() for p in paths)


def test_facade_matches_the_current_system():
    assert platforms.NAME in IMPLEMENTATIONS
    assert platforms.IS_WINDOWS == (platforms.NAME == "windows")
    assert platforms.IS_MACOS == (platforms.NAME == "macos")
    assert isinstance(platforms.data_dir(), Path)
    assert platforms.GLOBAL_HOTKEY == (platforms.GlobalHotkey is not None)


def test_regular_file_is_not_a_cloud_placeholder(tmp_path):
    f = tmp_path / "a.cbz"
    f.write_bytes(b"PK")
    assert platforms.is_cloud_placeholder(os.stat(f)) is False


def test_plain_secrets_are_readable_on_every_system():
    # valeurs ecrites par le repli "plain:" (systemes sans coffre)
    assert secret_store.unprotect("plain:" + "am9rZXI=") == "joker"


@pytest.mark.parametrize("value", [None, "", "inconnu:xyz", "plain:/w=="])   # /w== : octet 0xFF, pas de l'UTF-8
def test_unreadable_secrets_give_none(value):
    assert secret_store.unprotect(value) is None


@pytest.mark.skipif(not platforms.IS_WINDOWS, reason="DPAPI : Windows seulement")
def test_dpapi_roundtrip():
    enc = secret_store.protect("jeton-secret")
    assert enc.startswith("dpapi:") and "jeton-secret" not in enc
    assert secret_store.unprotect(enc) == "jeton-secret"


def test_cloud_placeholders_are_recognized_by_their_flags():
    from types import SimpleNamespace

    from beheread.platforms import macos, windows
    assert windows.is_cloud_placeholder(SimpleNamespace(st_file_attributes=0x00400000))
    assert not windows.is_cloud_placeholder(SimpleNamespace(st_file_attributes=0x20))
    assert macos.is_cloud_placeholder(SimpleNamespace(st_flags=0x40000000))   # SF_DATALESS
    assert not macos.is_cloud_placeholder(SimpleNamespace(st_flags=0))


@pytest.mark.skipif(not platforms.IS_MACOS, reason="macOS seulement")
def test_mac_data_lives_in_application_support():
    assert platforms.data_dir() == Path.home() / "Library" / "Application Support" / "Beheread"


@pytest.mark.skipif(not platforms.IS_MACOS, reason="Trousseau : macOS seulement")
def test_keychain_roundtrip():
    import uuid
    name = f"test-{uuid.uuid4().hex[:8]}"
    enc = secret_store.protect("jeton-secret", name=name)
    try:
        assert enc == f"keychain:{name}"
        assert secret_store.unprotect(enc) == "jeton-secret"
    finally:
        secret_store.discard(enc)
    assert secret_store.unprotect(enc) is None


@pytest.mark.skipif(not platforms.IS_MACOS, reason="Corbeille du Finder : macOS seulement")
def test_mac_trash_moves_the_file_to_the_trash(tmp_path):
    f = tmp_path / "a-jeter.cbz"
    f.write_bytes(b"PK")
    platforms.trash_function()(str(f))
    assert not f.exists()
    trashed = list((Path.home() / ".Trash").glob("a-jeter*.cbz"))
    assert trashed
    for t in trashed:
        t.unlink()


def test_trash_function_is_available_on_supported_systems():
    if platforms.IS_WINDOWS or platforms.IS_MACOS:
        assert callable(platforms.trash_function())
