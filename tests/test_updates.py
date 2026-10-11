"""Verification des mises a jour (infra/updates.py) : reseau simule."""

import io
import json

import pytest

from beheread.infra import updates


def _fake(payload):
    class _Resp(io.BytesIO):
        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False
    return lambda req, timeout=None: _Resp(json.dumps(payload).encode("utf-8"))


def test_versions_compare_numerically():
    assert updates.version_tuple("v1.10.0") == (1, 10, 0)
    assert updates.version_tuple("1.1.0-dev") == (1, 1, 0)
    assert updates.version_tuple("nightly") is None
    assert updates.is_newer("1.10.0", "1.9.3") and not updates.is_newer("1.1.0", "1.1.0")


def test_latest_release_is_read_from_github(monkeypatch):
    monkeypatch.setattr(updates.urllib.request, "urlopen", _fake(
        {"tag_name": "v1.2.0",
         "html_url": "https://github.com/codingt0m/beheread/releases/tag/v1.2.0"}))
    assert updates.latest_release() == {
        "version": "1.2.0", "url": "https://github.com/codingt0m/beheread/releases/tag/v1.2.0"}


@pytest.mark.parametrize("payload", [
    {"tag_name": "v1.2.0", "html_url": "https://exemple.com/piege"},     # autre site
    {"tag_name": "<b>9.9</b>", "html_url": updates.RELEASES_PREFIX + "x"},
    {},
])
def test_unexpected_answers_are_refused(monkeypatch, payload):
    monkeypatch.setattr(updates.urllib.request, "urlopen", _fake(payload))
    with pytest.raises(updates.UpdateError):
        updates.latest_release()
