import importlib
import os
import tempfile
import unittest
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'backend'))

from fastapi.testclient import TestClient


class FinancialIdempotencyTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp_dir = tempfile.TemporaryDirectory()
        os.environ['MGROUP_DB_PATH'] = str(Path(cls.temp_dir.name) / 'financial-idempotency.sqlite3')
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

    def create_member_with_balance(self, suffix):
        member = self.client.post('/api/v2/members', headers=self.admin_headers(),
            json={'display_name': f'Ledger {suffix}', 'pin': '123456'})
        self.assertEqual(member.status_code, 201, member.text)
        member_id = member.json()['member_id']
        card = self.client.post(f'/api/v2/members/{member_id}/cards', headers=self.admin_headers(),
            json={'card_uid': f'04-IDEMPOTENCY-{suffix}'})
        self.assertEqual(card.status_code, 201, card.text)
        topup = self.client.post('/api/v2/finance/top-ups', headers=self.admin_headers(),
            json={'request_id': f'idempotency-topup-{suffix}', 'member_id': member_id,
                  'amount_minor': 20000, 'description': 'Test balance'})
        self.assertEqual(topup.status_code, 200, topup.text)
        return member_id, f'04-IDEMPOTENCY-{suffix}'

    def create_vending(self, hardware_id):
        response = self.client.post('/api/v2/admin/devices', headers=self.admin_headers(),
            json={'hardware_id': hardware_id, 'device_type': 'vending', 'display_name': hardware_id})
        self.assertEqual(response.status_code, 201, response.text)
        return response.json()

    def test_top_up_idempotency_conflict_does_not_change_balance(self):
        member = self.client.post('/api/v2/members', headers=self.admin_headers(),
            json={'display_name': 'Top-up Idempotency'})
        self.assertEqual(member.status_code, 201, member.text)
        member_id = member.json()['member_id']
        payload = {'request_id': 'topup-conflict-request-01', 'member_id': member_id,
                   'amount_minor': 7000, 'description': 'Initial'}
        first = self.client.post('/api/v2/finance/top-ups', headers=self.admin_headers(), json=payload)
        self.assertEqual(first.status_code, 200, first.text)
        conflict = self.client.post('/api/v2/finance/top-ups', headers=self.admin_headers(),
            json={**payload, 'amount_minor': 9000})
        self.assertEqual(conflict.status_code, 409, conflict.text)
        members = self.client.get('/api/v2/members', headers=self.admin_headers()).json()['items']
        row = next(item for item in members if item['member_id'] == member_id)
        self.assertEqual(row['balance_minor'], 7000)

        db = self.main.connect(self.main.settings.database_path)
        try:
            count = db.execute(
                "SELECT COUNT(*) FROM transactions WHERE request_id='topup-conflict-request-01'"
            ).fetchone()[0]
            self.assertEqual(count, 1)
            entries = db.execute(
                "SELECT COUNT(*) FROM ledger_entries WHERE transaction_id=?",
                (first.json()['transaction_id'],),
            ).fetchone()[0]
            self.assertEqual(entries, 2)
        finally:
            db.close()

    def test_purchase_idempotency_conflict_cannot_debit_or_dispense_twice(self):
        member_id, card_uid = self.create_member_with_balance('PURCHASE01')
        vending = self.create_vending('vending-idempotency-01')
        headers = {'X-Device-Key': vending['device_key']}
        product = self.client.put(
            f"/api/v2/vending/devices/{vending['registry_id']}/products/1",
            headers=self.admin_headers(),
            json={'name': 'Air Mineral', 'price_minor': 5000, 'stock': 2},
        )
        self.assertEqual(product.status_code, 200, product.text)
        payload = {'request_id': 'purchase-idempotency-01', 'card_uid': card_uid,
                   'pin': '123456', 'product_id': 1}
        first = self.client.post('/api/v2/vending/purchases', headers=headers, json=payload)
        self.assertEqual(first.status_code, 201, first.text)
        self.assertEqual(first.json()['status'], 'pending', 'purchase must not be final before dispense confirmation')
        replay = self.client.post('/api/v2/vending/purchases', headers=headers, json=payload)
        self.assertEqual(replay.status_code, 201, replay.text)
        self.assertTrue(replay.json()['idempotent_replay'])

        conflict = self.client.post('/api/v2/vending/purchases', headers=headers,
            json={**payload, 'product_id': 2})
        self.assertEqual(conflict.status_code, 409, conflict.text)

        members = self.client.get('/api/v2/members', headers=self.admin_headers()).json()['items']
        self.assertEqual(next(item for item in members if item['member_id'] == member_id)['balance_minor'], 15000)
        products = self.client.get(
            f"/api/v2/vending/devices/{vending['registry_id']}/products",
            headers=self.admin_headers(),
        ).json()['items']
        self.assertEqual(products[0]['stock'], 1)
        transaction_id = first.json()['transaction_id']
        success = self.client.post(
            '/api/v2/vending/transactions/' + transaction_id + '/dispense-result',
            headers=headers,
            json={'succeeded': True},
        )
        self.assertEqual(success.status_code, 200, success.text)
        self.assertEqual(success.json()['status'], 'succeeded')
        db = self.main.connect(self.main.settings.database_path)
        try:
            count = db.execute(
                "SELECT COUNT(*) FROM transactions WHERE request_id='purchase-idempotency-01'"
            ).fetchone()[0]
            self.assertEqual(count, 1)
            entries = db.execute(
                "SELECT COUNT(*) FROM ledger_entries WHERE transaction_id=?",
                (first.json()['transaction_id'],),
            ).fetchone()[0]
            self.assertEqual(entries, 2)
        finally:
            db.close()

    def test_dispense_result_is_bound_to_originating_vending_device(self):
        member_id, card_uid = self.create_member_with_balance('DISPENSE01')
        vending = self.create_vending('vending-dispense-origin-01')
        other_vending = self.create_vending('vending-dispense-other-01')
        product = self.client.put(
            f"/api/v2/vending/devices/{vending['registry_id']}/products/1",
            headers=self.admin_headers(),
            json={'name': 'Air Mineral', 'price_minor': 5000, 'stock': 1},
        )
        self.assertEqual(product.status_code, 200, product.text)
        purchase = self.client.post('/api/v2/vending/purchases',
            headers={'X-Device-Key': vending['device_key']},
            json={'request_id': 'dispense-origin-request-01', 'card_uid': card_uid,
                  'pin': '123456', 'product_id': 1})
        self.assertEqual(purchase.status_code, 201, purchase.text)
        transaction_id = purchase.json()['transaction_id']

        foreign_result = self.client.post(
            f'/api/v2/vending/transactions/{transaction_id}/dispense-result',
            headers={'X-Device-Key': other_vending['device_key']},
            json={'succeeded': False, 'reason': 'forged-result'},
        )
        self.assertEqual(foreign_result.status_code, 404, foreign_result.text)

        correct_result = self.client.post(
            f'/api/v2/vending/transactions/{transaction_id}/dispense-result',
            headers={'X-Device-Key': vending['device_key']},
            json={'succeeded': False, 'reason': 'servo_timeout'},
        )
        self.assertEqual(correct_result.status_code, 200, correct_result.text)
        self.assertEqual(correct_result.json()['status'], 'reversed')
        repeated = self.client.post(
            f'/api/v2/vending/transactions/{transaction_id}/dispense-result',
            headers={'X-Device-Key': vending['device_key']},
            json={'succeeded': False, 'reason': 'servo_timeout'},
        )
        self.assertTrue(repeated.json()['idempotent_replay'])

        members = self.client.get('/api/v2/members', headers=self.admin_headers()).json()['items']
        self.assertEqual(next(item for item in members if item['member_id'] == member_id)['balance_minor'], 20000)


    def test_member_and_system_account_balances_reconcile_with_ledger(self):
        member_id, card_uid = self.create_member_with_balance('RECONCILE01')
        vending = self.create_vending('vending-reconcile-01')
        headers = {'X-Device-Key': vending['device_key']}
        updated = self.client.put(
            f"/api/v2/vending/devices/{vending['registry_id']}/products/1",
            headers=self.admin_headers(),
            json={'name': 'Air Mineral', 'price_minor': 5000, 'stock': 2},
        )
        self.assertEqual(updated.status_code, 200, updated.text)
        purchase = self.client.post('/api/v2/vending/purchases', headers=headers,
            json={'request_id': 'purchase-reconcile-01', 'card_uid': card_uid,
                  'pin': '123456', 'product_id': 1})
        self.assertEqual(purchase.status_code, 201, purchase.text)
        failed = self.client.post(
            f"/api/v2/vending/transactions/{purchase.json()['transaction_id']}/dispense-result",
            headers=headers, json={'succeeded': False, 'reason': 'test_refund'})
        self.assertEqual(failed.status_code, 200, failed.text)

        db = self.main.connect(self.main.settings.database_path)
        try:
            rows = db.execute("""
                SELECT a.account_id, a.account_type, a.balance_minor,
                       COALESCE(SUM(CASE
                           WHEN a.account_type='system' AND l.direction='debit' THEN l.amount_minor
                           WHEN a.account_type!='system' AND l.direction='credit' THEN l.amount_minor
                           ELSE 0 END), 0)
                       - COALESCE(SUM(CASE
                           WHEN a.account_type='system' AND l.direction='credit' THEN l.amount_minor
                           WHEN a.account_type!='system' AND l.direction='debit' THEN l.amount_minor
                           ELSE 0 END), 0) AS ledger_balance
                FROM accounts a
                LEFT JOIN ledger_entries l ON l.account_id=a.account_id
                GROUP BY a.account_id, a.account_type, a.balance_minor
            """).fetchall()
            self.assertTrue(rows)
            for row in rows:
                with self.subTest(account_id=row['account_id'], account_type=row['account_type']):
                    self.assertEqual(row['balance_minor'], row['ledger_balance'])
            member = db.execute("SELECT balance_minor FROM accounts WHERE member_id=? AND account_type='member'",
                (member_id,)).fetchone()
            self.assertEqual(member['balance_minor'], 20000)
        finally:
            db.close()


if __name__ == '__main__':
    unittest.main()
