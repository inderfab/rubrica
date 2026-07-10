import textwrap
import pytest
from db import connection
from config import settings


@pytest.fixture
def tmp_db(tmp_path, monkeypatch):
    data_dir = tmp_path / "_data"
    data_dir.mkdir()
    cfg = data_dir / "config.yaml"
    cfg.write_text(textwrap.dedent("""\
        database:
          path: rubrica.db
    """), encoding="utf-8")

    monkeypatch.setenv("RUBRICA_DATA_DIR", str(data_dir))
    monkeypatch.setattr(settings, "_CONFIG_PATH", cfg)
    monkeypatch.setattr(settings, "_settings", {})
    monkeypatch.setattr(connection, "_DB_PATH", None)

    connection.init_schema()
    conn = connection.get_connection()
    yield conn
    conn.close()
