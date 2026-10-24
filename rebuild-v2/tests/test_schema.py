from pathlib import Path
import sqlite3
import unittest

ROOT = Path(__file__).resolve().parents[1]
SCHEMA = ROOT / 'db' / 'schema.sql'

class CleanInstallSchemaTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.connection = sqlite3.connect(':memory:')
        cls.connection.execute('PRAGMA foreign_keys = ON')
        cls.connection.executescript(SCHEMA.read_text(encoding='utf-8'))

    @classmethod
    def tearDownClass(cls):
        cls.connection.close()

    def columns(self, table_name):
        rows = self.connection.execute(f'PRAGMA table_info({table_name})').fetchall()
        return {row[1] for row in rows}

    def test_schema_file_exists_and_is_nonempty(self):
        self.assertTrue(SCHEMA.is_file())
        self.assertGreater(SCHEMA.stat().st_size, 0)

    def test_required_core_tables_exist(self):
        rows = self.connection.execute("SELECT name FROM sqlite_master WHERE type = 'table'").fetchall()
        tables = {row[0] for row in rows}
        self.assertTrue({'device_registry', 'device_events', 'members', 'member_cards', 'accounts', 'transactions', 'ledger_entries', 'audit_events'}.issubset(tables))

    def test_device_registry_uses_canonical_identity_fields(self):
        columns = self.columns('device_registry')
        self.assertIn('registry_id', columns)
        self.assertIn('hardware_id', columns)
        self.assertIn('device_key_hash', columns)
        self.assertNotIn('device_id', columns)

    def test_transactions_use_hardware_identity_and_idempotency_key(self):
        columns = self.columns('transactions')
        self.assertIn('transaction_id', columns)
        self.assertIn('request_id', columns)
        self.assertIn('hardware_id', columns)
        self.assertNotIn('device_id', columns)

    def test_all_v2_tables_have_no_legacy_device_id_column(self):
        rows = self.connection.execute("SELECT name FROM sqlite_master WHERE type = 'table' AND name NOT LIKE 'sqlite_%'").fetchall()
        for (table_name,) in rows:
            with self.subTest(table=table_name):
                self.assertNotIn('device_id', self.columns(table_name))

    def test_foreign_keys_are_enabled(self):
        enabled = self.connection.execute('PRAGMA foreign_keys').fetchone()[0]
        self.assertEqual(enabled, 1)

if __name__ == '__main__':
    unittest.main()
