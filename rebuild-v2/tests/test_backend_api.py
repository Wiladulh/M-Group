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
        from app import config
        importlib.reload(config)
        from app import main
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


if __name__ == '__main__':
    unittest.main()
