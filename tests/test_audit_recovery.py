from pathlib import Path
from tempfile import TemporaryDirectory
import sqlite3

from app.core.db import Database

def test_audit_and_device_indexes_exist():
    with TemporaryDirectory() as d:
        db=Database(Path(d)/"m-group.db")
        db.migrate()
        with db.connect() as c:
            indexes={r[1] for r in c.execute("PRAGMA index_list(audit_events)").fetchall()}
            assert "ix_audit_events_created" in indexes
            assert "ix_audit_events_entity" in indexes
            indexes={r[1] for r in c.execute("PRAGMA index_list(device_events)").fetchall()}
            assert "ix_device_events_device_created" in indexes

def test_sqlite_backup_restore_roundtrip():
    with TemporaryDirectory() as d:
        root=Path(d)
        src=root/"source.db"; backup=root/"backup.db"; restored=root/"restored.db"
        c=sqlite3.connect(src)
        c.execute("CREATE TABLE t(v TEXT)")
        c.execute("INSERT INTO t VALUES('m_group-audit')")
        c.commit(); c.close()

        a=sqlite3.connect(src); b=sqlite3.connect(backup)
        a.backup(b); b.close(); a.close()

        b=sqlite3.connect(backup); r=sqlite3.connect(restored)
        b.backup(r); r.close(); b.close()

        r=sqlite3.connect(restored)
        assert r.execute("SELECT v FROM t").fetchone()[0]=="m_group-audit"
        r.close()
