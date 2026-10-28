import sqlite3
import hashlib
import os
import secrets
import fcntl
from contextlib import contextmanager
from pathlib import Path
from importlib.resources import files as resource_files

class ClosingConnection(sqlite3.Connection):
    """SQLite connection that releases its process-wide shared DB lock on close."""

    _lock_fd = None

    def close(self):
        lock_fd = self._lock_fd
        self._lock_fd = None
        try:
            return super().close()
        finally:
            if lock_fd is not None:
                try:
                    fcntl.flock(lock_fd, fcntl.LOCK_UN)
                finally:
                    os.close(lock_fd)

    def __exit__(self, exc_type, exc_value, traceback):
        try:
            return super().__exit__(exc_type, exc_value, traceback)
        finally:
            self.close()


class Database:
    def __init__(self, path: Path):
        self.path = Path(path)

    def _acquire_lock(self, exclusive=False):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        lock_path = Path(str(self.path) + ".lock")
        os.umask(0o077)
        fd = os.open(lock_path, os.O_CREAT | os.O_RDWR, 0o600)
        try:
            os.fchmod(fd, 0o600)
            fcntl.flock(fd, fcntl.LOCK_EX if exclusive else fcntl.LOCK_SH)
            return fd
        except Exception:
            os.close(fd)
            raise

    @contextmanager
    def exclusive_lock(self):
        """Block new DB users and wait for active managed connections to finish."""
        fd = self._acquire_lock(exclusive=True)
        try:
            yield
        finally:
            try:
                fcntl.flock(fd, fcntl.LOCK_UN)
            finally:
                os.close(fd)

    def connect(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        # Every app connection holds a shared OS-level lock for its entire
        # lifetime. Restore/maintenance can then obtain an exclusive lock that
        # coordinates requests across server worker processes, not just threads.
        lock_fd = self._acquire_lock(exclusive=False)
        c = None
        try:
            os.umask(0o077)
            c = sqlite3.connect(self.path, factory=ClosingConnection)
            c._lock_fd = lock_fd
            self.path.chmod(0o600)
            c.row_factory = sqlite3.Row
            c.execute("PRAGMA foreign_keys=ON")
            return c
        except Exception:
            if c is not None:
                c.close()
            else:
                try:
                    fcntl.flock(lock_fd, fcntl.LOCK_UN)
                finally:
                    os.close(lock_fd)
            raise

    def migrate(self, migrations_dir: Path | None = None):
        if migrations_dir is not None:
            paths = sorted(migrations_dir.glob("*.sql"))
        else:
            root = resource_files("app").joinpath("migrations")
            paths = sorted(Path(root).glob("*.sql"))

        with self.connect() as c:
            for path in paths:
                if path.name == "014_vending_promo_hardening.sql":
                    columns = {row[1] for row in c.execute("PRAGMA table_info(vending_transactions)")}
                    if "promo_id" not in columns:
                        c.execute("ALTER TABLE vending_transactions ADD COLUMN promo_id TEXT")
                        columns.add("promo_id")
                    table_sql = c.execute(
                        "SELECT sql FROM sqlite_master WHERE type='table' AND name='vending_transactions'"
                    ).fetchone()
                    sql_text = (table_sql[0] if table_sql and table_sql[0] else "").lower()
                    if "amount integer not null check(amount>0)" in sql_text:
                        c.execute("PRAGMA foreign_keys=OFF")
                        c.execute("""
                            CREATE TABLE vending_transactions_new(
                                transaction_id TEXT PRIMARY KEY,
                                machine_id TEXT NOT NULL REFERENCES vending_machines(machine_id),
                                product_id TEXT NOT NULL REFERENCES vending_products(product_id),
                                credential_id TEXT NOT NULL,
                                account_id TEXT NOT NULL,
                                amount INTEGER NOT NULL CHECK(amount>=0),
                                status TEXT NOT NULL,
                                dispense_status TEXT NOT NULL DEFAULT 'pending',
                                idempotency_key TEXT UNIQUE,
                                payment_transaction_id TEXT,
                                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                                completed_at TEXT,
                                base_amount INTEGER,
                                discount_amount INTEGER NOT NULL DEFAULT 0,
                                payment_method TEXT NOT NULL DEFAULT 'NFC',
                                payment_provider TEXT NOT NULL DEFAULT 'local',
                                payment_status TEXT NOT NULL DEFAULT 'pending',
                                transaction_source TEXT NOT NULL DEFAULT 'VENDING',
                                promo_id TEXT
                            )
                        """)
                        c.execute("""
                            INSERT INTO vending_transactions_new(
                                transaction_id,machine_id,product_id,credential_id,account_id,
                                amount,status,dispense_status,idempotency_key,payment_transaction_id,
                                created_at,completed_at,base_amount,discount_amount,
                                payment_method,payment_provider,payment_status,transaction_source,promo_id
                            )
                            SELECT transaction_id,machine_id,product_id,credential_id,account_id,
                                   amount,status,dispense_status,idempotency_key,payment_transaction_id,
                                   created_at,completed_at,base_amount,discount_amount,
                                   payment_method,payment_provider,payment_status,transaction_source,promo_id
                            FROM vending_transactions
                        """)
                        c.execute("DROP TABLE vending_transactions")
                        c.execute("ALTER TABLE vending_transactions_new RENAME TO vending_transactions")
                        c.execute(
                            "CREATE INDEX IF NOT EXISTS ix_vending_tx_machine_created "
                            "ON vending_transactions(machine_id,created_at)"
                        )
                        c.execute("PRAGMA foreign_keys=ON")
                    c.execute(
                        "INSERT OR IGNORE INTO system_meta(key,value) "
                        "VALUES('vending_promo_architecture_version','001')"
                    )
                    continue

                if path.name == "017_member_ktp.sql":
                    columns = {row[1] for row in c.execute("PRAGMA table_info(identity_members)")}
                    additions = {
                        "birth_place": "TEXT", "birth_date": "TEXT", "sex": "TEXT",
                        "rt": "TEXT", "rw": "TEXT", "village": "TEXT", "district": "TEXT",
                        "city_regency": "TEXT", "province": "TEXT", "religion": "TEXT",
                        "marital_status": "TEXT", "occupation": "TEXT", "citizenship": "TEXT",
                        "phone": "TEXT", "email": "TEXT", "registration_date": "TEXT",
                    }
                    for name, definition in additions.items():
                        if name not in columns:
                            c.execute(f"ALTER TABLE identity_members ADD COLUMN {name} {definition}")
                    c.execute("CREATE INDEX IF NOT EXISTS ix_member_nik ON identity_members(nik)")
                    c.execute("INSERT OR IGNORE INTO system_meta(key,value) VALUES('member_ktp_schema_version','001')")
                    continue

                if path.name == "024_canonical_hardware_registry.sql":
                    # Forward-migrate the legacy device_id table without retaining
                    # device_id in the canonical schema. Keep the old row identifier
                    # only as registry_id and preserve hardware/auth/status metadata.
                    tables = {
                        row[0] for row in c.execute(
                            "SELECT name FROM sqlite_master WHERE type='table'"
                        )
                    }
                    if "device_registry" in tables:
                        existing = {row[1] for row in c.execute("PRAGMA table_info(device_registry)")}
                        if "registry_id" not in existing:
                            c.execute("ALTER TABLE device_registry RENAME TO device_registry_legacy_024")
                            c.execute("""
                                CREATE TABLE device_registry (
                                    registry_id TEXT PRIMARY KEY,
                                    hardware_id TEXT UNIQUE,
                                    device_type TEXT NOT NULL,
                                    mac_address TEXT,
                                    display_name TEXT,
                                    status TEXT NOT NULL DEFAULT 'awaiting_device_registration'
                                        CHECK(status IN ('active','pending','awaiting_device_registration','offline','disabled','maintenance','unassigned')),
                                    last_seen TEXT,
                                    auth_key_hash TEXT,
                                    auth_key_hint TEXT,
                                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                                    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                                    deleted_at TEXT
                                )
                            """)
                            old = {row[1] for row in c.execute("PRAGMA table_info(device_registry_legacy_024)")}
                            def old_col(name, fallback="NULL"):
                                return name if name in old else fallback
                            legacy_id = old_col("device_id", old_col("hardware_id", "lower(hex(randomblob(16)))"))
                            hardware = old_col("hardware_id", legacy_id)
                            c.execute(f"""
                                INSERT INTO device_registry(
                                    registry_id,hardware_id,device_type,mac_address,display_name,status,
                                    last_seen,auth_key_hash,auth_key_hint,created_at,updated_at,deleted_at
                                )
                                SELECT CAST({legacy_id} AS TEXT),
                                       COALESCE(NULLIF({hardware},''),CAST({legacy_id} AS TEXT)),
                                       {old_col("device_type", "'cashier'")},
                                       {old_col("mac_address")},
                                       COALESCE(NULLIF({old_col("display_name")},''),NULLIF({hardware},''),CAST({legacy_id} AS TEXT)),
                                       COALESCE(NULLIF({old_col("status")},''),'active'),
                                       {old_col("last_seen")},{old_col("auth_key_hash")},{old_col("auth_key_hint")},
                                       COALESCE(NULLIF({old_col("created_at")},''),CURRENT_TIMESTAMP),
                                       COALESCE(NULLIF({old_col("updated_at")},''),CURRENT_TIMESTAMP),
                                       {old_col("deleted_at")}
                                FROM device_registry_legacy_024
                            """)
                            c.execute("DROP TABLE device_registry_legacy_024")
                    # The SQL migration creates the table for clean installations
                    # and adds canonical indexes in both fresh and upgraded databases.

                if path.name == "016_hardware_registry.sql":
                    # The rebuilt schema no longer creates device_registry.
                    # Skip this legacy device-registry migration when that table
                    # is absent; never recreate removed device identity state.
                    tables = {
                        row[0] for row in c.execute(
                            "SELECT name FROM sqlite_master WHERE type='table'"
                        )
                    }
                    if "device_registry" not in tables:
                        continue

                    device_columns = {row[1] for row in c.execute("PRAGMA table_info(device_registry)")}
                    additions = {
                        "mac_address": "TEXT",
                        "display_name": "TEXT",
                        "created_at": "TEXT",
                        "updated_at": "TEXT",
                    }
                    for name, definition in additions.items():
                        if name not in device_columns:
                            c.execute(f"ALTER TABLE device_registry ADD COLUMN {name} {definition}")
                    c.execute(
                        "UPDATE device_registry SET hardware_id=hardware_id "
                        "WHERE hardware_id IS NULL OR hardware_id=''"
                    )
                    c.execute(
                        "UPDATE device_registry SET display_name=hardware_id "
                        "WHERE display_name IS NULL OR display_name=''"
                    )
                    c.execute(
                        "UPDATE device_registry SET created_at=CURRENT_TIMESTAMP "
                        "WHERE created_at IS NULL OR created_at=''"
                    )
                    c.execute(
                        "UPDATE device_registry SET updated_at=CURRENT_TIMESTAMP "
                        "WHERE updated_at IS NULL OR updated_at=''"
                    )
                    marker = c.execute(
                        "SELECT value FROM system_meta WHERE key='hardware_registry_schema_version'"
                    ).fetchone()
                    if marker and marker[0] == "001":
                        continue

                if path.name == "013_feature_foundation.sql":
                    marker = c.execute(
                        "SELECT value FROM system_meta WHERE key='f01_schema_extension_version'"
                    ).fetchone()
                    if marker and marker[0] == "001":
                        continue

                    member_columns = {row[1] for row in c.execute("PRAGMA table_info(identity_members)")}
                    for name, definition in {
                        "nik": "TEXT",
                        "address": "TEXT",
                        "deleted_at": "TEXT",
                    }.items():
                        if name not in member_columns:
                            c.execute(f"ALTER TABLE identity_members ADD COLUMN {name} {definition}")

                    c.execute(
                        "CREATE UNIQUE INDEX IF NOT EXISTS ux_member_nik_active "
                        "ON identity_members(nik) "
                        "WHERE nik IS NOT NULL AND deleted_at IS NULL"
                    )
                    c.execute(
                        "CREATE INDEX IF NOT EXISTS ix_member_status "
                        "ON identity_members(status)"
                    )

                    # Device registry lifecycle columns/indexes were removed
                    # from the rebuilt schema. Keep this migration focused on
                    # member/NFC/promotion tables only.

                if path.name == "011_nfc_payment_hardening.sql":
                    marker = c.execute(
                        "SELECT value FROM system_meta WHERE key='nfc_payment_architecture_version'"
                    ).fetchone()
                    if marker and marker[0] == "002":
                        continue
                    for table in ("identity_credentials", "credential_registry"):
                        columns = {row[1] for row in c.execute(f"PRAGMA table_info({table})")}
                        additions = {
                            "pin_failed_attempts": "INTEGER NOT NULL DEFAULT 0",
                            "pin_blocked": "INTEGER NOT NULL DEFAULT 0",
                        }
                        if table == "identity_credentials":
                            additions["enabled"] = "INTEGER NOT NULL DEFAULT 1"
                        for name, definition in additions.items():
                            if name not in columns:
                                c.execute(f"ALTER TABLE {table} ADD COLUMN {name} {definition}")

                    columns = {row[1] for row in c.execute("PRAGMA table_info(payment_transactions)")}
                    target = {
                        "transaction_id": "TEXT PRIMARY KEY",
                        "credential_id": "TEXT NOT NULL",
                        "account_id": "TEXT NOT NULL",
                        "amount": "INTEGER NOT NULL CHECK(amount>=0)",
                        "status": "TEXT NOT NULL",
                        "created_at": "TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP",
                        "method": "TEXT NOT NULL DEFAULT 'NFC'",
                        "provider": "TEXT NOT NULL DEFAULT 'local'",
                        "idempotency_key": "TEXT",
                        "provider_transaction_id": "TEXT",
                        "provider_reference": "TEXT",
                        "failure_reason": "TEXT",
                                "original_amount": "INTEGER",
                        "discount_amount": "INTEGER NOT NULL DEFAULT 0",
                        "final_amount": "INTEGER",
                        "promo_id": "TEXT",
                        "balance_before": "INTEGER",
                        "balance_after": "INTEGER",
                    }
                    select_defaults = {
                        "method": "'NFC'",
                        "provider": "'local'",
                        "idempotency_key": "NULL",
                        "provider_transaction_id": "NULL",
                        "provider_reference": "NULL",
                        "failure_reason": "NULL",
                        "original_amount": "amount",
                        "discount_amount": "0",
                        "final_amount": "amount",
                        "promo_id": "NULL",
                        "balance_before": "NULL",
                        "balance_after": "NULL",
                    }
                    select_parts = [
                        name if name in columns else select_defaults.get(name, "NULL")
                        for name in target
                    ]
                    c.execute("CREATE TABLE payment_transactions_new(" +
                              ",".join(f"{name} {definition}" for name, definition in target.items()) +
                              ")")
                    c.execute(
                        "INSERT INTO payment_transactions_new(" +
                        ",".join(target.keys()) + ") SELECT " +
                        ",".join(select_parts) + " FROM payment_transactions"
                    )
                    c.execute("DROP TABLE payment_transactions")
                    c.execute("ALTER TABLE payment_transactions_new RENAME TO payment_transactions")
                    c.execute(
                        "CREATE UNIQUE INDEX IF NOT EXISTS ux_payment_idempotency "
                        "ON payment_transactions(idempotency_key) WHERE idempotency_key IS NOT NULL"
                    )
                    c.execute(
                        "CREATE INDEX IF NOT EXISTS ix_payment_provider_tx "
                        "ON payment_transactions(provider,provider_transaction_id)"
                    )
                    c.execute(
                        "CREATE INDEX IF NOT EXISTS ix_payment_device "
                        "ON payment_transactions(hardware_id,created_at)"
                    )
                    c.execute(
                        "CREATE INDEX IF NOT EXISTS ix_payment_account_created "
                        "ON payment_transactions(account_id,created_at)"
                    )
                    c.execute(
                        "INSERT OR IGNORE INTO system_meta(key,value) "
                        "VALUES('nfc_payment_architecture_version','002')"
                    )
                    continue

                if path.name == "008_member_pin.sql":
                    columns = {row[1] for row in c.execute("PRAGMA table_info(identity_members)")}
                    if "pin_salt" not in columns: c.execute("ALTER TABLE identity_members ADD COLUMN pin_salt TEXT")
                    if "pin_hash" not in columns: c.execute("ALTER TABLE identity_members ADD COLUMN pin_hash TEXT")
                    continue

                if path.name == "006_vending.sql":
                    product_columns = {
                        row[1] for row in c.execute("PRAGMA table_info(vending_products)")
                    }
                    product_additions = {
                        "machine_id": "TEXT",
                        "stock": "INTEGER NOT NULL DEFAULT 0",
                        "enabled": "INTEGER NOT NULL DEFAULT 1",
                    }
                    for name, definition in product_additions.items():
                        if name not in product_columns:
                            c.execute(f"ALTER TABLE vending_products ADD COLUMN {name} {definition}")

                    transaction_columns = {
                        row[1] for row in c.execute("PRAGMA table_info(vending_transactions)")
                    }
                    transaction_additions = {
                        "credential_id": "TEXT",
                        "account_id": "TEXT",
                        "dispense_status": "TEXT NOT NULL DEFAULT 'pending'",
                        "idempotency_key": "TEXT",
                        "payment_transaction_id": "TEXT",
                        "completed_at": "TEXT",
                    }
                    for name, definition in transaction_additions.items():
                        if name not in transaction_columns:
                            c.execute(f"ALTER TABLE vending_transactions ADD COLUMN {name} {definition}")

                if path.name == "009_vending_registry.sql":
                    machine_columns = {row[1] for row in c.execute("PRAGMA table_info(vending_machines)")}
                    machine_additions = {
                        "location": "TEXT NOT NULL DEFAULT ''",
                        "hardware_id": "TEXT",
                        "updated_at": "TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP",
                    }
                    for name, definition in machine_additions.items():
                        if name not in machine_columns:
                            c.execute(f"ALTER TABLE vending_machines ADD COLUMN {name} {definition}")

                    product_columns = {row[1] for row in c.execute("PRAGMA table_info(vending_products)")}
                    product_additions = {
                        "slot": "INTEGER",
                        "capacity": "INTEGER NOT NULL DEFAULT 0",
                        "servo_channel": "INTEGER",
                        "created_at": "TEXT",
                    }
                    for name, definition in product_additions.items():
                        if name not in product_columns:
                            c.execute(f"ALTER TABLE vending_products ADD COLUMN {name} {definition}")
                    c.execute(
                        "UPDATE vending_products SET created_at=CURRENT_TIMESTAMP "
                        "WHERE created_at IS NULL OR created_at=''"
                    )

                    machines = [row[0] for row in c.execute("SELECT machine_id FROM vending_machines ORDER BY machine_id")]
                    for machine_id in machines:
                        rows = c.execute(
                            "SELECT product_id,stock,slot FROM vending_products "
                            "WHERE machine_id=? ORDER BY created_at,product_id",
                            (machine_id,),
                        ).fetchall()
                        used = {row["slot"] for row in rows if row["slot"] is not None}
                        next_slot = 1
                        for row in rows:
                            slot = row["slot"]
                            if slot is None:
                                while next_slot in used:
                                    next_slot += 1
                                if next_slot <= 5:
                                    slot = next_slot
                                    used.add(slot)
                                else:
                                    continue
                            c.execute(
                                "UPDATE vending_products SET slot=?, capacity=CASE WHEN capacity=0 THEN stock ELSE capacity END, "
                                "servo_channel=CASE WHEN servo_channel IS NULL THEN ? ELSE servo_channel END "
                                "WHERE product_id=?",
                                (slot, slot, row["product_id"]),
                            )
                            next_slot += 1

                c.executescript(path.read_text(encoding="utf-8"))

            vending_tx_columns = {row[1] for row in c.execute("PRAGMA table_info(vending_transactions)")}
            vending_tx_additions = {
                "base_amount": "INTEGER",
                "discount_amount": "INTEGER NOT NULL DEFAULT 0",
                "payment_method": "TEXT NOT NULL DEFAULT 'NFC'",
                "payment_provider": "TEXT NOT NULL DEFAULT 'local'",
                "payment_status": "TEXT NOT NULL DEFAULT 'pending'",
            }
            for name, definition in vending_tx_additions.items():
                if name not in vending_tx_columns:
                    c.execute(f"ALTER TABLE vending_transactions ADD COLUMN {name} {definition}")
            c.execute("UPDATE vending_transactions SET base_amount=amount WHERE base_amount IS NULL")

            vending_columns = {row[1] for row in c.execute("PRAGMA table_info(vending_machines)")}
            if vending_columns and "machine_id" not in vending_columns:
                c.execute("ALTER TABLE vending_machines ADD COLUMN machine_id TEXT")
                c.execute("UPDATE vending_machines SET machine_id='legacy-' || rowid WHERE machine_id IS NULL")
                c.execute("CREATE UNIQUE INDEX IF NOT EXISTS ux_vending_machines_machine_id ON vending_machines(machine_id)")

            columns = {row[1] for row in c.execute("PRAGMA table_info(payment_transactions)")}
            if "transaction_source" not in columns:
                c.execute("ALTER TABLE payment_transactions ADD COLUMN transaction_source TEXT NOT NULL DEFAULT 'WEBUI'")
            vending_cols = {row[1] for row in c.execute("PRAGMA table_info(vending_transactions)")}
            if "transaction_source" not in vending_cols:
                c.execute("ALTER TABLE vending_transactions ADD COLUMN transaction_source TEXT NOT NULL DEFAULT 'VENDING'")
            c.execute("CREATE INDEX IF NOT EXISTS ix_payment_source_created ON payment_transactions(transaction_source,created_at)")
            c.execute("CREATE INDEX IF NOT EXISTS ix_vending_source_created ON vending_transactions(transaction_source,created_at)")
            c.execute("INSERT OR IGNORE INTO system_meta(key,value) VALUES('transaction_retention_months','12')")
            operator_pin = os.getenv("M_GROUP_CASHIER_OPERATOR_PIN", "")
            if operator_pin and (not operator_pin.isdigit() or not 4 <= len(operator_pin) <= 6):
                raise ValueError("cashier_operator_pin_must_be_4_to_6_digits")

            pin_marker = c.execute(
                "SELECT value FROM system_meta WHERE key='cashier_operator_pin_security_version'"
            ).fetchone()
            pin_row = c.execute(
                "SELECT value FROM system_meta WHERE key='cashier_operator_pin_hash'"
            ).fetchone()
            if not pin_marker:
                # Remove the publicly documented legacy default only when the
                # stored salted hash actually matches 9992. Preserve custom PINs.
                if pin_row and pin_row["value"] and ":" in pin_row["value"]:
                    salt, stored_digest = pin_row["value"].split(":", 1)
                    legacy_digest = hashlib.pbkdf2_hmac("sha256", b"9992", salt.encode(), 120000).hex()
                    if secrets.compare_digest(stored_digest, legacy_digest):
                        c.execute("DELETE FROM system_meta WHERE key='cashier_operator_pin_hash'")
                c.execute(
                    "INSERT OR REPLACE INTO system_meta(key,value) VALUES('cashier_operator_pin_security_version','001')"
                )
                pin_row = c.execute(
                    "SELECT value FROM system_meta WHERE key='cashier_operator_pin_hash'"
                ).fetchone()

            # A new install has no shared/default operator PIN. The installer may
            # provide a one-time PIN for first boot; otherwise it is configured
            # explicitly by an administrator in the WebUI.
            if (not pin_row or not pin_row["value"]) and operator_pin:
                salt = secrets.token_hex(16)
                digest = hashlib.pbkdf2_hmac("sha256", operator_pin.encode(), salt.encode(), 120000).hex()
                c.execute(
                    "INSERT OR REPLACE INTO system_meta(key,value) VALUES('cashier_operator_pin_hash',?)",
                    (salt + ":" + digest,),
                )
            additions = {
                "method": "TEXT NOT NULL DEFAULT 'NFC'",
                "provider": "TEXT NOT NULL DEFAULT 'local'",
                "idempotency_key": "TEXT",
                "provider_transaction_id": "TEXT",
                "provider_reference": "TEXT",
                "failure_reason": "TEXT",
                "hardware_id": "TEXT",
            }
            for name, definition in additions.items():
                if name not in columns:
                    c.execute(f"ALTER TABLE payment_transactions ADD COLUMN {name} {definition}")
            # Remove the obsolete payment-level device identity while preserving
            # every transaction and its financial/audit fields. Older installs may
            # still have hardware_id; new schemas and application contracts do not.
            payment_columns = {row[1] for row in c.execute("PRAGMA table_info(payment_transactions)")}
            if "hardware_id" in payment_columns:
                payment_fields = [
                    "transaction_id", "credential_id", "account_id", "amount", "status",
                    "created_at", "method", "provider", "idempotency_key",
                    "provider_transaction_id", "provider_reference", "failure_reason",
                    "original_amount", "discount_amount", "final_amount", "promo_id",
                    "balance_before", "balance_after", "transaction_source",
                ]
                c.execute("""
                    CREATE TABLE payment_transactions_new(
                        transaction_id TEXT PRIMARY KEY,
                        credential_id TEXT NOT NULL,
                        account_id TEXT NOT NULL,
                        amount INTEGER NOT NULL CHECK(amount>=0),
                        status TEXT NOT NULL,
                        created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                        method TEXT NOT NULL DEFAULT 'NFC',
                        provider TEXT NOT NULL DEFAULT 'local',
                        idempotency_key TEXT,
                        provider_transaction_id TEXT,
                        provider_reference TEXT,
                        failure_reason TEXT,
                        original_amount INTEGER,
                        discount_amount INTEGER NOT NULL DEFAULT 0,
                        final_amount INTEGER,
                        promo_id TEXT,
                        balance_before INTEGER,
                        balance_after INTEGER,
                        transaction_source TEXT NOT NULL DEFAULT 'WEBUI'
                    )
                """)
                field_list = ",".join(payment_fields)
                c.execute(
                    f"INSERT INTO payment_transactions_new({field_list}) "
                    f"SELECT {field_list} FROM payment_transactions"
                )
                c.execute("DROP TABLE payment_transactions")
                c.execute("ALTER TABLE payment_transactions_new RENAME TO payment_transactions")
            c.execute(
                "CREATE UNIQUE INDEX IF NOT EXISTS ux_payment_idempotency "
                "ON payment_transactions(idempotency_key) WHERE idempotency_key IS NOT NULL"
            )
            c.execute(
                "CREATE INDEX IF NOT EXISTS ix_payment_provider_tx "
                "ON payment_transactions(provider,provider_transaction_id)"
            )
            # Authentication is no longer stored on a device_registry table.
            # Keep payment transaction schema upgrades independent of legacy device state.
            c.commit()
