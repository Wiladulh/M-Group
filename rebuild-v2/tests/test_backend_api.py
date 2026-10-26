import importlib
import os
import tempfile
import unittest
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'backend'))

from fastapi.testclient import TestClient


class ServerApiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp_dir = tempfile.TemporaryDirectory()
        os.environ['MGROUP_DB_PATH'] = str(Path(cls.temp_dir.name) / 'server-test.sqlite3')
        os.environ['MGROUP_ADMIN_TOKEN'] = 'test-admin-token-long-enough'
        os.environ['MGROUP_DEVICE_KEY_PEPPER'] = 'test-only-pepper'
        from mgroup_backend import config
        importlib.reload(config)
        from mgroup_backend import main
        importlib.reload(main)
        cls.main = main
        cls.client = TestClient(main.app)
        cls.client.__enter__()

    @classmethod
    def tearDownClass(cls):
        cls.client.__exit__(None, None, None)
        cls.temp_dir.cleanup()
        for key in ('MGROUP_DB_PATH', 'MGROUP_ADMIN_TOKEN', 'MGROUP_DEVICE_KEY_PEPPER'):
            os.environ.pop(key, None)

    def admin_headers(self):
        return {'Authorization': 'Bearer test-admin-token-long-enough'}

    def test_health_and_readiness(self):
        self.assertEqual(self.client.get('/api/v2/health').status_code, 200)
        response = self.client.get('/api/v2/ready')
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()['database'], 'ok')

    def test_admin_routes_require_token(self):
        response = self.client.post('/api/v2/members', json={'display_name': 'Ayu'})
        self.assertEqual(response.status_code, 401)

    def test_device_provisioning_and_authentication(self):
        response = self.client.post('/api/v2/admin/devices', headers=self.admin_headers(),
            json={'hardware_id': 'cashier-unit-001', 'device_type': 'cashier', 'display_name': 'Kasir 1'})
        self.assertEqual(response.status_code, 201, response.text)
        body = response.json()
        self.assertNotIn('device_key_hash', body)
        auth = self.client.get('/api/v2/device/me', headers={'X-Device-Key': body['device_key']})
        self.assertEqual(auth.status_code, 200, auth.text)
        self.assertEqual(auth.json()['hardware_id'], 'cashier-unit-001')
        self.assertEqual(self.client.get('/api/v2/device/me', headers={'X-Device-Key': 'wrong-key'}).status_code, 401)

    def test_member_top_up_is_idempotent(self):
        member = self.client.post('/api/v2/members', headers=self.admin_headers(), json={'display_name': 'Sari'})
        self.assertEqual(member.status_code, 201, member.text)
        member_id = member.json()['member_id']
        payload = {'request_id': 'topup-request-0001', 'member_id': member_id, 'amount_minor': 25000, 'description': 'Isi saldo'}
        first = self.client.post('/api/v2/finance/top-ups', headers=self.admin_headers(), json=payload)
        second = self.client.post('/api/v2/finance/top-ups', headers=self.admin_headers(), json=payload)
        self.assertEqual(first.status_code, 200, first.text)
        self.assertEqual(second.status_code, 200, second.text)
        self.assertFalse(first.json()['idempotent_replay'])
        self.assertTrue(second.json()['idempotent_replay'])
        listed = self.client.get('/api/v2/members', headers=self.admin_headers()).json()['items']
        row = next(item for item in listed if item['member_id'] == member_id)
        self.assertEqual(row['balance_minor'], 25000)

    def test_vending_has_exactly_five_fixed_slots(self):
        response = self.client.post('/api/v2/admin/devices', headers=self.admin_headers(),
            json={'hardware_id': 'vending-unit-001', 'device_type': 'vending', 'display_name': 'Vending 1'})
        self.assertEqual(response.status_code, 201, response.text)
        registry_id = response.json()['registry_id']
        products = self.client.get(f'/api/v2/vending/devices/{registry_id}/products', headers=self.admin_headers())
        self.assertEqual(products.status_code, 200, products.text)
        self.assertEqual([item['product_id'] for item in products.json()['items']], [1, 2, 3, 4, 5])
        updated = self.client.put(f'/api/v2/vending/devices/{registry_id}/products/1', headers=self.admin_headers(),
            json={'name': 'Air Mineral', 'price_minor': 5000, 'stock': 12})
        self.assertEqual(updated.status_code, 200, updated.text)
        self.assertEqual(updated.json()['nfc_promo_percent'], 0)
        self.assertEqual(updated.json()['qris_promo_percent'], 0)
        invalid = self.client.put(f'/api/v2/vending/devices/{registry_id}/products/6', headers=self.admin_headers(),
            json={'name': 'Produk 6', 'price_minor': 1, 'stock': 1})
        self.assertEqual(invalid.status_code, 422)


    def test_nfc_purchase_is_atomic_and_failed_dispense_refunds_once(self):
        member = self.client.post('/api/v2/members', headers=self.admin_headers(),
            json={'display_name': 'Budi', 'pin': '123456'})
        self.assertEqual(member.status_code, 201, member.text)
        member_id = member.json()['member_id']
        card = self.client.post(f'/api/v2/members/{member_id}/cards', headers=self.admin_headers(),
            json={'card_uid': '04-A1-B2-C3'})
        self.assertEqual(card.status_code, 201, card.text)
        topup = self.client.post('/api/v2/finance/top-ups', headers=self.admin_headers(),
            json={'request_id': 'purchase-test-topup-01', 'member_id': member_id, 'amount_minor': 20000})
        self.assertEqual(topup.status_code, 200, topup.text)
        device = self.client.post('/api/v2/admin/devices', headers=self.admin_headers(),
            json={'hardware_id': 'vending-purchase-001', 'device_type': 'vending', 'display_name': 'Vending Test'})
        self.assertEqual(device.status_code, 201, device.text)
        body = device.json()
        headers = {'X-Device-Key': body['device_key']}
        product = self.client.put(f"/api/v2/vending/devices/{body['registry_id']}/products/1",
            headers=self.admin_headers(), json={'name': 'Air Mineral', 'price_minor': 5000, 'stock': 2})
        self.assertEqual(product.status_code, 200, product.text)
        payload = {'request_id': 'purchase-request-0001', 'card_uid': '04-A1-B2-C3', 'pin': '123456', 'product_id': 1}
        purchase = self.client.post('/api/v2/vending/purchases', headers=headers, json=payload)
        self.assertEqual(purchase.status_code, 201, purchase.text)
        transaction_id = purchase.json()['transaction_id']
        self.assertEqual(purchase.json()['amount_minor'], 5000)
        replay = self.client.post('/api/v2/vending/purchases', headers=headers, json=payload)
        self.assertEqual(replay.status_code, 201, replay.text)
        self.assertTrue(replay.json()['idempotent_replay'])
        failed = self.client.post(f'/api/v2/vending/transactions/{transaction_id}/dispense-result',
            headers=headers, json={'succeeded': False, 'reason': 'servo_timeout'})
        self.assertEqual(failed.status_code, 200, failed.text)
        self.assertEqual(failed.json()['status'], 'reversed')
        repeated = self.client.post(f'/api/v2/vending/transactions/{transaction_id}/dispense-result',
            headers=headers, json={'succeeded': False, 'reason': 'servo_timeout'})
        self.assertTrue(repeated.json()['idempotent_replay'])
        products = self.client.get(f"/api/v2/vending/devices/{body['registry_id']}/products",
            headers=self.admin_headers()).json()['items']
        self.assertEqual(products[0]['stock'], 2)
        members = self.client.get('/api/v2/members', headers=self.admin_headers()).json()['items']
        self.assertEqual(next(x for x in members if x['member_id'] == member_id)['balance_minor'], 20000)

        # Independently audit the persisted ledger: top-up, purchase and refund
        # must each balance, and the member account must reconcile to its ledger.
        db = self.main.connect(self.main.settings.database_path)
        try:
            rows = db.execute(
                "SELECT t.transaction_type, t.status, "
                "SUM(CASE WHEN l.direction='debit' THEN l.amount_minor ELSE 0 END) AS debits, "
                "SUM(CASE WHEN l.direction='credit' THEN l.amount_minor ELSE 0 END) AS credits, "
                "COUNT(l.entry_id) AS entry_count "
                "FROM transactions t LEFT JOIN ledger_entries l ON l.transaction_id=t.transaction_id "
                "WHERE t.request_id IN ('purchase-test-topup-01','purchase-request-0001') "
                "GROUP BY t.transaction_id ORDER BY t.transaction_type"
            ).fetchall()
            self.assertEqual(len(rows), 2)
            for row in rows:
                self.assertEqual(row['debits'], row['credits'], dict(row))
                expected_entries = 2 if row['transaction_type'] == 'top_up' else 4
                self.assertEqual(row['entry_count'], expected_entries, dict(row))

            refund_rows = db.execute(
                "SELECT SUM(CASE WHEN direction='debit' THEN amount_minor ELSE 0 END) AS debits, "
                "SUM(CASE WHEN direction='credit' THEN amount_minor ELSE 0 END) AS credits, "
                "COUNT(*) AS entry_count FROM ledger_entries WHERE transaction_id=?",
                (transaction_id,),
            ).fetchone()
            self.assertEqual(refund_rows['debits'], 10000)
            self.assertEqual(refund_rows['credits'], 10000)
            self.assertEqual(refund_rows['entry_count'], 4)

            account = db.execute(
                "SELECT a.account_id, a.balance_minor FROM accounts a "
                "WHERE a.member_id=? AND a.account_type='member'", (member_id,)
            ).fetchone()
            net_ledger = db.execute(
                "SELECT COALESCE(SUM(CASE WHEN direction='credit' THEN amount_minor ELSE -amount_minor END),0) "
                "FROM ledger_entries WHERE account_id=?", (account['account_id'],)
            ).fetchone()[0]
            self.assertEqual(account['balance_minor'], net_ledger)
        finally:
            db.close()


    def test_repeated_invalid_pin_locks_card_for_device(self):
        member = self.client.post('/api/v2/members', headers=self.admin_headers(),
            json={'display_name': 'Pin Limit', 'pin': '123456'})
        self.assertEqual(member.status_code, 201, member.text)
        member_id = member.json()['member_id']
        self.client.post(f'/api/v2/members/{member_id}/cards', headers=self.admin_headers(),
            json={'card_uid': '04-LOCK-0001'})
        device = self.client.post('/api/v2/admin/devices', headers=self.admin_headers(),
            json={'hardware_id': 'vending-pin-lock-001', 'device_type': 'vending', 'display_name': 'Vending Lock'})
        headers = {'X-Device-Key': device.json()['device_key']}
        for attempt in range(4):
            response = self.client.post('/api/v2/vending/purchases', headers=headers,
                json={'request_id': f'bad-pin-request-{attempt:02d}', 'card_uid': '04-LOCK-0001',
                      'pin': '999999', 'product_id': 1})
            self.assertEqual(response.status_code, 401, response.text)
        locked = self.client.post('/api/v2/vending/purchases', headers=headers,
            json={'request_id': 'bad-pin-request-04', 'card_uid': '04-LOCK-0001',
                  'pin': '999999', 'product_id': 1})
        self.assertEqual(locked.status_code, 429, locked.text)
        valid_while_locked = self.client.post('/api/v2/vending/purchases', headers=headers,
            json={'request_id': 'valid-pin-locked-01', 'card_uid': '04-LOCK-0001',
                  'pin': '123456', 'product_id': 1})
        self.assertEqual(valid_while_locked.status_code, 429, valid_while_locked.text)

    def test_product_name_cannot_be_whitespace(self):
        device = self.client.post('/api/v2/admin/devices', headers=self.admin_headers(),
            json={'hardware_id': 'vending-blank-name-001', 'device_type': 'vending', 'display_name': 'Vending'})
        self.assertEqual(device.status_code, 201, device.text)
        registry_id = device.json()['registry_id']
        response = self.client.put(f'/api/v2/vending/devices/{registry_id}/products/1',
            headers=self.admin_headers(), json={'name': '   ', 'price_minor': 5000, 'stock': 1})
        self.assertEqual(response.status_code, 422, response.text)
        products = self.client.get(f'/api/v2/vending/devices/{registry_id}/products',
            headers=self.admin_headers()).json()['items']
        self.assertEqual(products[0]['name'], 'Produk 1')

    def test_cashier_device_cannot_initiate_vending_purchase(self):
        device = self.client.post('/api/v2/admin/devices', headers=self.admin_headers(),
            json={'hardware_id': 'cashier-purchase-denied-001', 'device_type': 'cashier', 'display_name': 'Kasir'})
        self.assertEqual(device.status_code, 201, device.text)
        response = self.client.post('/api/v2/vending/purchases',
            headers={'X-Device-Key': device.json()['device_key']},
            json={'request_id': 'cashier-purchase-0001', 'card_uid': '04-CA-FE-01',
                  'pin': '123456', 'product_id': 1})
        self.assertEqual(response.status_code, 403, response.text)

if __name__ == '__main__':
    unittest.main()
