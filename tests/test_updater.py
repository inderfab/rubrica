import subprocess

import httpx

from menubar import updater


class _FakeResponse:
    def __init__(self, status_code=200, json_daten=None):
        self.status_code = status_code
        self._json = json_daten or {}

    def json(self):
        return self._json

    def raise_for_status(self):
        if self.status_code >= 400:
            raise httpx.HTTPStatusError("Fehler", request=None, response=self)


def _release(tag_name, asset_name="rubrica-server-1.2.3.pkg"):
    return {
        "tag_name": tag_name,
        "assets": [{"name": asset_name, "browser_download_url": f"https://example.com/{asset_name}"}],
    }


def test_pruefe_update_findet_neuere_version(monkeypatch):
    monkeypatch.setattr(httpx, "get", lambda *a, **kw: _FakeResponse(200, _release("v1.2.3")))
    info = updater.pruefe_update("1.0.0")
    assert info is not None
    assert info.version == "1.2.3"
    assert info.asset_name == "rubrica-server-1.2.3.pkg"


def test_pruefe_update_ohne_neuere_version_gibt_none(monkeypatch):
    monkeypatch.setattr(httpx, "get", lambda *a, **kw: _FakeResponse(200, _release("v1.0.0")))
    assert updater.pruefe_update("1.0.0") is None


def test_pruefe_update_ohne_passendes_asset_gibt_none(monkeypatch):
    monkeypatch.setattr(httpx, "get", lambda *a, **kw: _FakeResponse(200, _release("v2.0.0", asset_name="irgendwas.dmg")))
    assert updater.pruefe_update("1.0.0") is None


def test_pruefe_update_bei_netzwerkfehler_gibt_none(monkeypatch):
    def _wirft(*a, **kw):
        raise httpx.ConnectError("kein Netz")
    monkeypatch.setattr(httpx, "get", _wirft)
    assert updater.pruefe_update("1.0.0") is None


def test_pruefe_update_bei_ungueltiger_remote_version_gibt_none(monkeypatch):
    monkeypatch.setattr(httpx, "get", lambda *a, **kw: _FakeResponse(200, _release("v-nicht-semver")))
    assert updater.pruefe_update("1.0.0") is None


def test_pruefe_update_bei_http_fehlerstatus_gibt_none(monkeypatch):
    monkeypatch.setattr(httpx, "get", lambda *a, **kw: _FakeResponse(404))
    assert updater.pruefe_update("1.0.0") is None


def test_verify_pkg_akzeptiert_korrekte_signatur(monkeypatch, tmp_path):
    pkg = tmp_path / "rubrica-server-1.2.3.pkg"
    pkg.write_bytes(b"fake")
    monkeypatch.setattr(updater, "EXPECTED_TEAM_ID", "ABCDE12345")

    def _fake_run(cmd, **kwargs):
        if cmd[0] == "pkgutil":
            return subprocess.CompletedProcess(cmd, 0, stdout="Developer ID Installer: Firma (ABCDE12345)\n")
        if cmd[0] == "spctl":
            return subprocess.CompletedProcess(cmd, 0, stdout="", stderr="")
        raise AssertionError(f"unerwarteter Aufruf: {cmd}")

    monkeypatch.setattr(subprocess, "run", _fake_run)
    assert updater._verify_pkg(pkg) is True


def test_verify_pkg_lehnt_falsche_team_id_ab(monkeypatch, tmp_path):
    pkg = tmp_path / "rubrica-server-1.2.3.pkg"
    pkg.write_bytes(b"fake")
    monkeypatch.setattr(updater, "EXPECTED_TEAM_ID", "ABCDE12345")

    def _fake_run(cmd, **kwargs):
        return subprocess.CompletedProcess(cmd, 0, stdout="Developer ID Installer: Fremd (ANDERSTEAMID)\n")

    monkeypatch.setattr(subprocess, "run", _fake_run)
    assert updater._verify_pkg(pkg) is False


def test_verify_pkg_lehnt_fehlende_signatur_ab(monkeypatch, tmp_path):
    pkg = tmp_path / "rubrica-server-1.2.3.pkg"
    pkg.write_bytes(b"fake")

    def _fake_run(cmd, **kwargs):
        return subprocess.CompletedProcess(cmd, 1, stdout="nicht signiert")

    monkeypatch.setattr(subprocess, "run", _fake_run)
    assert updater._verify_pkg(pkg) is False


def test_lade_und_pruefe_loescht_datei_bei_fehlgeschlagener_verifikation(monkeypatch, tmp_path):
    monkeypatch.setattr(updater, "_DOWNLOAD_DIR", tmp_path)

    class _FakeStream:
        status_code = 200
        def raise_for_status(self):
            pass
        def iter_bytes(self, chunk_size=1):
            yield b"fake-pkg-inhalt"
        def __enter__(self):
            return self
        def __exit__(self, *a):
            return False

    monkeypatch.setattr(httpx, "stream", lambda *a, **kw: _FakeStream())
    monkeypatch.setattr(updater, "_verify_pkg", lambda pkg, log=None: False)

    info = updater.UpdateInfo(version="1.2.3", download_url="https://example.com/x.pkg", asset_name="x.pkg")
    ergebnis = updater.lade_und_pruefe(info)
    assert ergebnis is None
    assert not (tmp_path / "x.pkg").exists()


def test_lade_und_pruefe_gibt_pfad_bei_erfolgreicher_verifikation(monkeypatch, tmp_path):
    monkeypatch.setattr(updater, "_DOWNLOAD_DIR", tmp_path)

    class _FakeStream:
        status_code = 200
        def raise_for_status(self):
            pass
        def iter_bytes(self, chunk_size=1):
            yield b"fake-pkg-inhalt"
        def __enter__(self):
            return self
        def __exit__(self, *a):
            return False

    monkeypatch.setattr(httpx, "stream", lambda *a, **kw: _FakeStream())
    monkeypatch.setattr(updater, "_verify_pkg", lambda pkg, log=None: True)

    info = updater.UpdateInfo(version="1.2.3", download_url="https://example.com/x.pkg", asset_name="x.pkg")
    ergebnis = updater.lade_und_pruefe(info)
    assert ergebnis == tmp_path / "x.pkg"
    assert ergebnis.read_bytes() == b"fake-pkg-inhalt"


def test_installiere_oeffnet_pkg_per_open(monkeypatch, tmp_path):
    aufrufe = []
    monkeypatch.setattr(subprocess, "run", lambda cmd, **kw: aufrufe.append(cmd))
    pkg = tmp_path / "rubrica-server-1.2.3.pkg"
    updater.installiere(pkg)
    assert aufrufe == [["open", str(pkg)]]
