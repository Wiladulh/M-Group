import tempfile
import unittest
from pathlib import Path

from mgroup_backend.db import connect, initialize


class InitializationSafetyTests(unittest.TestCase):
    def test_reinitialization_does_not_rewrite_existing_v2_records(self):
        with tempfile.TemporaryDirectory() as directory:
            database = str(Path(directory) / "clean-room.sqlite3")
            initialize(database)
            connection = connect(database)
            try:
                connection.execute(
                    "INSERT INTO admin_users(admin_id,username,password_hash,role,status) VALUES(?,?,?,?,?)",
                    ("adm-1", "admin-one", "test-hash-one", "super_admin", "active"))
                connection.execute(
                    "INSERT INTO admin_users(admin_id,username,password_hash,role,status) VALUES(?,?,?,?,?)",
                    ("adm-2", "admin-two", "test-hash-two", "super_admin", "active"))
                connection.execute(
                    "INSERT INTO members(member_id,display_name) VALUES(?,?)",
                    ("CUSTOM-LEGACY-42", "Preserve Existing Member"))
                connection.execute(
                    "ALTER TABLE members ADD COLUMN operator_note TEXT")
                connection.execute(
                    "INSERT INTO device_registry(registry_id,hardware_id,device_type,status) VALUES(?,?,?,?)",
                    ("reg-1", "vending-1", "vending", "active"))
                connection.execute(
                    "INSERT INTO product_slots(registry_id,product_id,name,price_minor,stock,capacity,enabled) "
                    "VALUES(?,?,?,?,?,?,?)",
                    ("reg-1", 1, "Water", 5000, 2, 10, 1))
            finally:
                connection.close()

            initialize(database)
            connection = connect(database)
            try:
                self.assertEqual(connection.execute(
                    "SELECT COUNT(*) FROM admin_users").fetchone()[0], 2)
                self.assertIsNotNone(connection.execute(
                    "SELECT 1 FROM members WHERE member_id='CUSTOM-LEGACY-42'").fetchone())
                self.assertIn("operator_note", {
                    row[1] for row in connection.execute("PRAGMA table_info(members)")})
                self.assertEqual(connection.execute(
                    "SELECT capacity FROM product_slots WHERE registry_id='reg-1' AND product_id=1"
                ).fetchone()[0], 10)
                self.assertEqual(connection.execute("PRAGMA foreign_key_check").fetchall(), [])
            finally:
                connection.close()


if __name__ == "__main__":
    unittest.main()
