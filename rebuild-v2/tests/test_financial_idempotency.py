import importlib
import os
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
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

    def activate_device(self, provisioned, hardware_id):
        response = self.client.post('/api/v2/device/register',
            headers={'X-Device-Key': provisioned['device_key']},
            json={'hardware_id': hardware_id, 'mac_address': None})
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()['status'], 'active')
        return response.json()

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
        self.activate_device(response.json(), hardware_id)
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
            json={'name': 'Air Mineral', 'price_minor': 5000, 'stock': 2, 'enabled': True},
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
            json={'name': 'Air Mineral', 'price_minor': 5000, 'stock': 1, 'enabled': True},
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
            json={'name': 'Air Mineral', 'price_minor': 5000, 'stock': 2, 'enabled': True},
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


    def test_finance_reconciliation_endpoint_reports_pending_purchases_and_balances(self):
        member_id, card_uid = self.create_member_with_balance('RECONCILEPENDING')
        vending = self.create_vending('vending-reconcile-pending-01')
        self.client.put(
            f"/api/v2/vending/devices/{vending['registry_id']}/products/1",
            headers=self.admin_headers(),
            json={'name': 'Air Mineral', 'price_minor': 5000, 'stock': 1, 'enabled': True},
        )
        purchase = self.client.post('/api/v2/vending/purchases',
            headers={'X-Device-Key': vending['device_key']},
            json={'request_id': 'purchase-reconcile-pending-01', 'card_uid': card_uid,
                  'pin': '123456', 'product_id': 1})
        self.assertEqual(purchase.status_code, 201, purchase.text)

        report = self.client.get('/api/v2/admin/finance/reconciliation', headers=self.admin_headers())
        self.assertEqual(report.status_code, 200, report.text)
        body = report.json()
        self.assertEqual(body['status'], 'ok')
        self.assertEqual(body['transaction_imbalances'], [])
        self.assertEqual(body['account_mismatches'], [])
        self.assertTrue(body['pending_purchases_require_review'])
        self.assertIn(purchase.json()['transaction_id'],
                      [row['transaction_id'] for row in body['pending_purchases']])


    def test_concurrent_duplicate_purchase_creates_only_one_debit_and_stock_decrement(self):
        member_id, card_uid = self.create_member_with_balance('CONCURRENTBUY')
        vending = self.create_vending('vending-concurrent-buy-01')
        headers = {'X-Device-Key': vending['device_key']}
        self.client.put(f"/api/v2/vending/devices/{vending['registry_id']}/products/1",
            headers=self.admin_headers(),
            json={'name': 'Air Mineral', 'price_minor': 5000, 'stock': 3, 'enabled': True})
        payload = {'request_id': 'purchase-concurrent-request-01', 'card_uid': card_uid,
                   'pin': '123456', 'product_id': 1}

        def send_purchase(_):
            return self.client.post('/api/v2/vending/purchases', headers=headers, json=payload)

        with ThreadPoolExecutor(max_workers=6) as pool:
            responses = list(pool.map(send_purchase, range(6)))
        self.assertTrue(all(response.status_code == 201 for response in responses),
                        [response.text for response in responses])
        transaction_ids = {response.json()['transaction_id'] for response in responses}
        self.assertEqual(len(transaction_ids), 1)
        self.assertEqual(sum(not response.json()['idempotent_replay'] for response in responses), 1)

        db = self.main.connect(self.main.settings.database_path)
        try:
            balance = db.execute("SELECT balance_minor FROM accounts WHERE member_id=? AND account_type='member'",
                                 (member_id,)).fetchone()['balance_minor']
            stock = db.execute("SELECT stock FROM product_slots WHERE registry_id=? AND product_id=1",
                               (vending['registry_id'],)).fetchone()['stock']
            txn_count = db.execute("SELECT COUNT(*) FROM transactions WHERE request_id=?",
                                   ('purchase-concurrent-request-01',)).fetchone()[0]
            entries = db.execute("SELECT COUNT(*) FROM ledger_entries WHERE transaction_id=?",
                                 (next(iter(transaction_ids)),)).fetchone()[0]
            self.assertEqual(balance, 15000)
            self.assertEqual(stock, 2)
            self.assertEqual(txn_count, 1)
            self.assertEqual(entries, 2)
        finally:
            db.close()

    def test_concurrent_failed_dispense_reports_refund_and_restore_stock_once(self):
        member_id, card_uid = self.create_member_with_balance('CONCURRENTREFUND')
        vending = self.create_vending('vending-concurrent-refund-01')
        headers = {'X-Device-Key': vending['device_key']}
        self.client.put(f"/api/v2/vending/devices/{vending['registry_id']}/products/1",
            headers=self.admin_headers(),
            json={'name': 'Air Mineral', 'price_minor': 5000, 'stock': 2, 'enabled': True})
        purchase = self.client.post('/api/v2/vending/purchases', headers=headers,
            json={'request_id': 'purchase-concurrent-refund-01', 'card_uid': card_uid,
                  'pin': '123456', 'product_id': 1})
        self.assertEqual(purchase.status_code, 201, purchase.text)
        transaction_id = purchase.json()['transaction_id']

        def report_failure(_):
            return self.client.post(f'/api/v2/vending/transactions/{transaction_id}/dispense-result',
                headers=headers, json={'succeeded': False, 'reason': 'concurrent_test'})

        with ThreadPoolExecutor(max_workers=6) as pool:
            responses = list(pool.map(report_failure, range(6)))
        self.assertTrue(all(response.status_code == 200 for response in responses),
                        [response.text for response in responses])
        self.assertEqual(sum(not response.json()['idempotent_replay'] for response in responses), 1)
        self.assertTrue(all(response.json()['status'] == 'reversed' for response in responses))

        db = self.main.connect(self.main.settings.database_path)
        try:
            balance = db.execute("SELECT balance_minor FROM accounts WHERE member_id=? AND account_type='member'",
                                 (member_id,)).fetchone()['balance_minor']
            stock = db.execute("SELECT stock FROM product_slots WHERE registry_id=? AND product_id=1",
                               (vending['registry_id'],)).fetchone()['stock']
            entries = db.execute("SELECT COUNT(*) FROM ledger_entries WHERE transaction_id=?",
                                 (transaction_id,)).fetchone()[0]
            refunds = db.execute("SELECT COUNT(*) FROM audit_events WHERE entity_id=? AND action='vending.dispense.refund'",
                                 (transaction_id,)).fetchone()[0]
            self.assertEqual(balance, 20000)
            self.assertEqual(stock, 2)
            self.assertEqual(entries, 4)
            self.assertEqual(refunds, 1)
        finally:
            db.close()


    def test_cashier_configuration_binds_operator_and_merchant_account_server_side(self):
        cashier = self.client.post('/api/v2/admin/devices', headers=self.admin_headers(),
            json={'hardware_id': 'cashier-config-test-01', 'device_type': 'cashier',
                  'display_name': 'Cashier Config Test'})
        self.assertEqual(cashier.status_code, 201, cashier.text)
        self.activate_device(cashier.json(), 'cashier-config-test-01')
        vending = self.create_vending('vending-cashier-config-test-01')

        db = self.main.connect(self.main.settings.database_path)
        merchant_account_id = 'merchant-settlement-config-test-01'
        try:
            db.execute("INSERT INTO accounts(account_id,account_type,balance_minor) VALUES(?,'merchant',0)",
                       (merchant_account_id,))
        finally:
            db.close()

        config = self.client.put(
            f"/api/v2/admin/cashier-devices/{cashier.json()['registry_id']}/configuration",
            headers=self.admin_headers(),
            json={'operator_id': 'operator-config-test-01', 'operator_name': 'Operator Test',
                  'operator_pin': '654321', 'settlement_account_id': merchant_account_id})
        self.assertEqual(config.status_code, 200, config.text)
        self.assertEqual(config.json()['settlement_account_id'], merchant_account_id)
        self.assertEqual(config.json()['operator_id'], 'operator-config-test-01')

        wrong_device = self.client.put(
            f"/api/v2/admin/cashier-devices/{vending['registry_id']}/configuration",
            headers=self.admin_headers(),
            json={'operator_id': 'operator-config-test-02', 'operator_name': 'Operator Test',
                  'operator_pin': '654321', 'settlement_account_id': merchant_account_id})
        self.assertEqual(wrong_device.status_code, 404, wrong_device.text)

        db = self.main.connect(self.main.settings.database_path)
        try:
            row = db.execute("SELECT operator_id,operator_pin_hash,settlement_account_id FROM cashier_device_config WHERE registry_id=?",
                             (cashier.json()['registry_id'],)).fetchone()
            self.assertEqual(row['operator_id'], 'operator-config-test-01')
            self.assertNotEqual(row['operator_pin_hash'], '654321')
            self.assertEqual(row['settlement_account_id'], merchant_account_id)
            self.assertEqual(db.execute("SELECT COUNT(*) FROM audit_events WHERE action='cashier.device.configure' AND entity_id=?",
                                        (cashier.json()['registry_id'],)).fetchone()[0], 1)
        finally:
            db.close()


if __name__ == '__main__':
    unittest.main()
