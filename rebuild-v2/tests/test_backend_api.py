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

    def activate_device(self, provisioned, hardware_id):
        response = self.client.post('/api/v2/device/register',
            headers={'X-Device-Key': provisioned['device_key']},
            json={'hardware_id': hardware_id, 'mac_address': None})
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()['status'], 'active')
        return response.json()
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

    def test_admin_read_and_write_routes_reject_missing_or_invalid_tokens(self):
        protected_reads = (
            '/api/v2/members',
            '/api/v2/vending/devices',
            '/api/v2/admin/audit',
            '/api/v2/admin/finance/reconciliation',
        )
        for path in protected_reads:
            with self.subTest(path=path):
                self.assertEqual(self.client.get(path).status_code, 401)
                self.assertEqual(self.client.get(path, headers={'Authorization': 'Bearer wrong-token'}).status_code, 401)

        denied = self.client.post('/api/v2/admin/devices',
            json={'hardware_id': 'unauthorized-device', 'device_type': 'vending', 'display_name': 'Unauthorized'})
        self.assertEqual(denied.status_code, 401, denied.text)
        self.assertEqual(self.client.post('/api/v2/admin/devices',
            headers={'Authorization': 'Bearer wrong-token'},
            json={'hardware_id': 'unauthorized-device', 'device_type': 'vending', 'display_name': 'Unauthorized'}).status_code, 401)

    def test_device_provisioning_and_authentication(self):
        response = self.client.post('/api/v2/admin/devices', headers=self.admin_headers(),
            json={'hardware_id': 'cashier-unit-001', 'device_type': 'cashier', 'display_name': 'Kasir 1'})
        self.assertEqual(response.status_code, 201, response.text)
        self.activate_device(response.json(), 'cashier-unit-001')
        body = response.json()
        self.assertNotIn('device_key_hash', body)
        auth = self.client.get('/api/v2/device/me', headers={'X-Device-Key': body['device_key']})
        self.assertEqual(auth.status_code, 200, auth.text)
        self.assertEqual(auth.json()['hardware_id'], 'cashier-unit-001')
        self.assertEqual(self.client.get('/api/v2/device/me', headers={'X-Device-Key': 'wrong-key'}).status_code, 401)

    def test_device_member_balance_is_read_only_and_requires_active_enrollment(self):
        member = self.client.post('/api/v2/members', headers=self.admin_headers(),
            json={'display_name': 'Balance Lookup'})
        self.assertEqual(member.status_code, 201, member.text)
        member_id = member.json()['member_id']
        card = self.client.post(f"/api/v2/members/{member_id}/cards",
            headers=self.admin_headers(), json={'card_uid': '04-BALANCE-LOOKUP'})
        self.assertEqual(card.status_code, 201, card.text)
        topup = self.client.post('/api/v2/finance/top-ups', headers=self.admin_headers(),
            json={'request_id': 'balance-lookup-topup-01', 'member_id': member_id,
                  'amount_minor': 12500})
        self.assertEqual(topup.status_code, 200, topup.text)
        device = self.client.post('/api/v2/admin/devices', headers=self.admin_headers(),
            json={'hardware_id': 'cashier-balance-lookup-01', 'device_type': 'cashier',
                  'display_name': 'Balance Lookup Cashier'})
        self.assertEqual(device.status_code, 201, device.text)
        self.activate_device(device.json(), 'cashier-balance-lookup-01')
        headers = {'X-Device-Key': device.json()['device_key']}

        db = self.main.connect(self.main.settings.database_path)
        try:
            before_transactions = db.execute("SELECT COUNT(*) FROM transactions").fetchone()[0]
            before_entries = db.execute("SELECT COUNT(*) FROM ledger_entries").fetchone()[0]
        finally:
            db.close()

        response = self.client.post('/api/v2/devices/member-balance', headers=headers,
            json={'card_uid': '04-BALANCE-LOOKUP'})
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()['member_id'], member_id)
        self.assertEqual(response.json()['balance_minor'], 12500)
        self.assertEqual(response.json()['currency'], 'IDR')
        self.assertNotIn('card_uid', response.json())
        self.assertEqual(self.client.post('/api/v2/devices/member-balance',
            headers=headers, json={'card_uid': '04-UNKNOWN-BALANCE'}).status_code, 401)
        self.assertEqual(self.client.post('/api/v2/devices/member-balance',
            json={'card_uid': '04-BALANCE-LOOKUP'}).status_code, 401)

        db = self.main.connect(self.main.settings.database_path)
        try:
            self.assertEqual(db.execute("SELECT COUNT(*) FROM transactions").fetchone()[0],
                             before_transactions)
            self.assertEqual(db.execute("SELECT COUNT(*) FROM ledger_entries").fetchone()[0],
                             before_entries)
        finally:
            db.close()

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
        self.activate_device(response.json(), 'vending-unit-001')
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


    def test_vending_device_can_read_its_own_product_catalog_only(self):
        vending = self.client.post('/api/v2/admin/devices', headers=self.admin_headers(),
            json={'hardware_id': 'vending-catalog-01', 'device_type': 'vending',
                  'display_name': 'Vending Catalog'})
        self.assertEqual(vending.status_code, 201, vending.text)
        self.activate_device(vending.json(), 'vending-catalog-01')
        self.client.put(f"/api/v2/vending/devices/{vending.json()['registry_id']}/products/1",
            headers=self.admin_headers(),
            json={'name': 'Air Mineral', 'price_minor': 5000, 'stock': 7})
        response = self.client.get('/api/v2/device/products',
            headers={'X-Device-Key': vending.json()['device_key']})
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()['registry_id'], vending.json()['registry_id'])
        self.assertEqual(len(response.json()['items']), 5)
        self.assertEqual(response.json()['items'][0],
            {'product_id': 1, 'name': 'Air Mineral', 'price_minor': 5000, 'stock': 7})
        self.assertEqual(self.client.get('/api/v2/device/products').status_code, 401)

        cashier = self.client.post('/api/v2/admin/devices', headers=self.admin_headers(),
            json={'hardware_id': 'cashier-catalog-denied-01', 'device_type': 'cashier',
                  'display_name': 'Cashier Catalog Denied'})
        self.assertEqual(cashier.status_code, 201, cashier.text)
        self.activate_device(cashier.json(), 'cashier-catalog-denied-01')
        denied = self.client.get('/api/v2/device/products',
            headers={'X-Device-Key': cashier.json()['device_key']})
        self.assertEqual(denied.status_code, 403, denied.text)

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
        self.activate_device(device.json(), 'vending-purchase-001')
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
        self.activate_device(device.json(), 'vending-pin-lock-001')
        headers = {'X-Device-Key': device.json()['device_key']}
        for attempt in range(4):
            response = self.client.post('/api/v2/vending/purchases', headers=headers,
                json={'request_id': f'bad-pin-request-{attempt:02d}', 'card_uid': '04-LOCK-0001',
                      'pin': '999999', 'product_id': 1})
            self.assertEqual(response.status_code, 401, response.text)
        # Switching to another registered vending unit must not reset the
        # card-wide counter and bypass the lockout.
        second_device = self.client.post('/api/v2/admin/devices', headers=self.admin_headers(),
            json={'hardware_id': 'vending-pin-lock-002', 'device_type': 'vending', 'display_name': 'Vending Lock 2'})
        self.assertEqual(second_device.status_code, 201, second_device.text)
        self.activate_device(second_device.json(), 'vending-pin-lock-002')
        second_headers = {'X-Device-Key': second_device.json()['device_key']}
        locked = self.client.post('/api/v2/vending/purchases', headers=second_headers,
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
        self.activate_device(device.json(), 'vending-blank-name-001')
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
        self.activate_device(device.json(), 'cashier-purchase-denied-001')
        response = self.client.post('/api/v2/vending/purchases',
            headers={'X-Device-Key': device.json()['device_key']},
            json={'request_id': 'cashier-purchase-0001', 'card_uid': '04-CA-FE-01',
                  'pin': '123456', 'product_id': 1})
        self.assertEqual(response.status_code, 403, response.text)


    def test_v2_cashier_payment_and_topup_are_authenticated_idempotent_and_ledgered(self):
        member = self.client.post('/api/v2/members', headers=self.admin_headers(),
            json={'display_name': 'Cashier Member', 'pin': '123456'})
        self.assertEqual(member.status_code, 201, member.text)
        member_id = member.json()['member_id']
        card = self.client.post(f'/api/v2/members/{member_id}/cards',
            headers=self.admin_headers(), json={'card_uid': '04-CASHIER-V2-0001'})
        self.assertEqual(card.status_code, 201, card.text)
        initial_topup = self.client.post('/api/v2/finance/top-ups', headers=self.admin_headers(),
            json={'request_id': 'cashier-v2-seed-0001', 'member_id': member_id, 'amount_minor': 30000})
        self.assertEqual(initial_topup.status_code, 200, initial_topup.text)

        device = self.client.post('/api/v2/admin/devices', headers=self.admin_headers(),
            json={'hardware_id': 'cashier-v2-unit-0001', 'device_type': 'cashier',
                  'display_name': 'Cashier v2'})
        self.assertEqual(device.status_code, 201, device.text)
        self.activate_device(device.json(), 'cashier-v2-unit-0001')
        registry_id = device.json()['registry_id']
        headers = {'X-Device-Key': device.json()['device_key']}

        merchant = self.client.post('/api/v2/admin/merchant-accounts', headers=self.admin_headers(),
            json={'label': 'Cashier v2 settlement'})
        self.assertEqual(merchant.status_code, 201, merchant.text)
        merchant_id = merchant.json()['account_id']
        configured = self.client.put(f'/api/v2/admin/cashier-devices/{registry_id}/configuration',
            headers=self.admin_headers(), json={'operator_id': 'operator-v2-001',
                'operator_name': 'Operator V2', 'operator_pin': '654321',
                'settlement_account_id': merchant_id})
        self.assertEqual(configured.status_code, 200, configured.text)

        payment_payload = {'request_id': 'cashier-v2-payment-0001', 'card_uid': '04-CASHIER-V2-0001',
                           'pin': '123456', 'amount_minor': 5000}
        payment = self.client.post('/api/v2/cashier/payments', headers=headers, json=payment_payload)
        self.assertEqual(payment.status_code, 201, payment.text)
        self.assertEqual(payment.json()['balance_after_minor'], 25000)
        replay = self.client.post('/api/v2/cashier/payments', headers=headers, json=payment_payload)
        self.assertEqual(replay.status_code, 201, replay.text)
        self.assertTrue(replay.json()['idempotent_replay'])
        conflict = self.client.post('/api/v2/cashier/payments', headers=headers,
            json={**payment_payload, 'amount_minor': 6000})
        self.assertEqual(conflict.status_code, 409, conflict.text)

        topup_payload = {'request_id': 'cashier-v2-topup-0001', 'card_uid': '04-CASHIER-V2-0001',
                         'operator_pin': '654321', 'member_pin': '123456', 'amount_minor': 7000}
        topup = self.client.post('/api/v2/cashier/top-ups', headers=headers, json=topup_payload)
        self.assertEqual(topup.status_code, 201, topup.text)
        topup_replay = self.client.post('/api/v2/cashier/top-ups', headers=headers, json=topup_payload)
        self.assertEqual(topup_replay.status_code, 201, topup_replay.text)
        self.assertTrue(topup_replay.json()['idempotent_replay'])
        bad_operator = self.client.post('/api/v2/cashier/top-ups', headers=headers,
            json={**topup_payload, 'request_id': 'cashier-v2-topup-bad-01', 'operator_pin': '000000'})
        self.assertEqual(bad_operator.status_code, 401, bad_operator.text)

        db = self.main.connect(self.main.settings.database_path)
        try:
            payment_row = db.execute("SELECT transaction_id FROM transactions WHERE request_id=?",
                                     (payment_payload['request_id'],)).fetchone()
            topup_row = db.execute("SELECT transaction_id FROM transactions WHERE request_id=?",
                                   (topup_payload['request_id'],)).fetchone()
            self.assertIsNotNone(payment_row)
            self.assertIsNotNone(topup_row)
            self.assertEqual(db.execute("SELECT COUNT(*) FROM transactions WHERE request_id IN (?,?)",
                (payment_payload['request_id'], topup_payload['request_id'])).fetchone()[0], 2)
            for transaction_id in (payment_row['transaction_id'], topup_row['transaction_id']):
                totals = db.execute("SELECT SUM(CASE WHEN direction='debit' THEN amount_minor ELSE 0 END) debits, SUM(CASE WHEN direction='credit' THEN amount_minor ELSE 0 END) credits, COUNT(*) entries FROM ledger_entries WHERE transaction_id=?",
                                    (transaction_id,)).fetchone()
                self.assertEqual(totals['debits'], totals['credits'])
                self.assertEqual(totals['entries'], 2)
            member_balance = db.execute("SELECT balance_minor FROM accounts WHERE member_id=? AND account_type='member'",
                                        (member_id,)).fetchone()[0]
            merchant_balance = db.execute("SELECT balance_minor FROM accounts WHERE account_id=?", (merchant_id,)).fetchone()[0]
            self.assertEqual(member_balance, 32000)
            self.assertEqual(merchant_balance, 5000)
        finally:
            db.close()

    def test_v2_cashier_endpoints_reject_missing_and_wrong_device_credentials(self):
        self.assertEqual(self.client.post('/api/v2/cashier/payments',
            json={'request_id': 'cashier-no-key-0001', 'card_uid': '04-UNKNOWN', 'pin': '123456',
                  'amount_minor': 5000}).status_code, 401)
        vending = self.client.post('/api/v2/admin/devices', headers=self.admin_headers(),
            json={'hardware_id': 'vending-cashier-endpoint-001', 'device_type': 'vending',
                  'display_name': 'Wrong device'})
        self.assertEqual(vending.status_code, 201, vending.text)
        self.activate_device(vending.json(), 'vending-cashier-endpoint-001')
        response = self.client.post('/api/v2/cashier/payments',
            headers={'X-Device-Key': vending.json()['device_key']},
            json={'request_id': 'cashier-wrong-type-0001', 'card_uid': '04-UNKNOWN',
                  'pin': '123456', 'amount_minor': 5000})
        self.assertEqual(response.status_code, 403, response.text)


    def test_same_nfc_card_vending_then_cashier_payment_keeps_one_authoritative_balance(self):
        card_uid = '04-MGROUP-SHARED-CARD-01'
        member = self.client.post('/api/v2/members', headers=self.admin_headers(),
            json={'display_name': 'Shared Card Member', 'pin': '123456'})
        self.assertEqual(member.status_code, 201, member.text)
        member_id = member.json()['member_id']
        enrolled = self.client.post(f'/api/v2/members/{member_id}/cards',
            headers=self.admin_headers(), json={'card_uid': card_uid})
        self.assertEqual(enrolled.status_code, 201, enrolled.text)
        seed = self.client.post('/api/v2/finance/top-ups', headers=self.admin_headers(),
            json={'request_id': 'shared-card-seed-0001', 'member_id': member_id, 'amount_minor': 30000})
        self.assertEqual(seed.status_code, 200, seed.text)

        vending = self.client.post('/api/v2/admin/devices', headers=self.admin_headers(),
            json={'hardware_id': 'shared-card-vending-01', 'device_type': 'vending',
                  'display_name': 'Shared Card Vending'})
        self.assertEqual(vending.status_code, 201, vending.text)
        self.activate_device(vending.json(), 'shared-card-vending-01')
        vending_headers = {'X-Device-Key': vending.json()['device_key']}
        product = self.client.put(
            f"/api/v2/vending/devices/{vending.json()['registry_id']}/products/1",
            headers=self.admin_headers(),
            json={'name': 'Air Mineral', 'price_minor': 5000, 'stock': 2})
        self.assertEqual(product.status_code, 200, product.text)
        catalog = self.client.get('/api/v2/device/products', headers=vending_headers)
        self.assertEqual(catalog.status_code, 200, catalog.text)
        self.assertEqual(catalog.json()['items'][0]['price_minor'], 5000)

        balance_before = self.client.post('/api/v2/devices/member-balance',
            headers=vending_headers, json={'card_uid': card_uid})
        self.assertEqual(balance_before.status_code, 200, balance_before.text)
        self.assertEqual(balance_before.json()['balance_minor'], 30000)

        purchase = self.client.post('/api/v2/vending/purchases', headers=vending_headers,
            json={'request_id': 'shared-card-vend-0001', 'card_uid': card_uid,
                  'pin': '123456', 'product_id': 1, 'expected_amount_minor': 5000})
        self.assertEqual(purchase.status_code, 201, purchase.text)
        self.assertEqual(purchase.json()['amount_minor'], 5000)
        dispensed = self.client.post(
            f"/api/v2/vending/transactions/{purchase.json()['transaction_id']}/dispense-result",
            headers=vending_headers, json={'succeeded': True})
        self.assertEqual(dispensed.status_code, 200, dispensed.text)
        self.assertEqual(dispensed.json()['status'], 'succeeded')
        self.assertEqual(dispensed.json()['balance_after_minor'], 25000)

        cashier = self.client.post('/api/v2/admin/devices', headers=self.admin_headers(),
            json={'hardware_id': 'shared-card-cashier-01', 'device_type': 'cashier',
                  'display_name': 'Shared Card Cashier'})
        self.assertEqual(cashier.status_code, 201, cashier.text)
        self.activate_device(cashier.json(), 'shared-card-cashier-01')
        cashier_headers = {'X-Device-Key': cashier.json()['device_key']}
        merchant = self.client.post('/api/v2/admin/merchant-accounts', headers=self.admin_headers(),
            json={'label': 'Shared Card Settlement'})
        self.assertEqual(merchant.status_code, 201, merchant.text)
        configured = self.client.put(
            f"/api/v2/admin/cashier-devices/{cashier.json()['registry_id']}/configuration",
            headers=self.admin_headers(),
            json={'operator_id': 'shared-card-operator', 'operator_name': 'Operator',
                  'operator_pin': '654321', 'settlement_account_id': merchant.json()['account_id']})
        self.assertEqual(configured.status_code, 200, configured.text)

        cashier_balance = self.client.post('/api/v2/devices/member-balance',
            headers=cashier_headers, json={'card_uid': card_uid})
        self.assertEqual(cashier_balance.status_code, 200, cashier_balance.text)
        self.assertEqual(cashier_balance.json()['balance_minor'], 25000)
        payment_payload = {'request_id': 'shared-card-cash-0001', 'card_uid': card_uid,
                           'pin': '123456', 'amount_minor': 3000}
        payment = self.client.post('/api/v2/cashier/payments',
            headers=cashier_headers, json=payment_payload)
        self.assertEqual(payment.status_code, 201, payment.text)
        self.assertEqual(payment.json()['balance_after_minor'], 22000)
        replay = self.client.post('/api/v2/cashier/payments',
            headers=cashier_headers, json=payment_payload)
        self.assertEqual(replay.status_code, 201, replay.text)
        self.assertTrue(replay.json()['idempotent_replay'])

        final_balance = self.client.post('/api/v2/devices/member-balance',
            headers=vending_headers, json={'card_uid': card_uid})
        self.assertEqual(final_balance.status_code, 200, final_balance.text)
        self.assertEqual(final_balance.json()['balance_minor'], 22000)

        db = self.main.connect(self.main.settings.database_path)
        try:
            member_account = db.execute(
                "SELECT account_id,balance_minor FROM accounts WHERE member_id=? AND account_type='member'",
                (member_id,)).fetchone()
            self.assertEqual(member_account['balance_minor'], 22000)
            for request_id in ('shared-card-seed-0001', 'shared-card-vend-0001', 'shared-card-cash-0001'):
                row = db.execute(
                    "SELECT transaction_id FROM transactions WHERE request_id=?", (request_id,)).fetchone()
                self.assertIsNotNone(row, request_id)
                totals = db.execute(
                    "SELECT SUM(CASE WHEN direction='debit' THEN amount_minor ELSE 0 END) debits, "
                    "SUM(CASE WHEN direction='credit' THEN amount_minor ELSE 0 END) credits "
                    "FROM ledger_entries WHERE transaction_id=?", (row['transaction_id'],)).fetchone()
                self.assertEqual(totals['debits'], totals['credits'], request_id)
            net_ledger = db.execute(
                "SELECT COALESCE(SUM(CASE WHEN direction='credit' THEN amount_minor ELSE -amount_minor END),0) "
                "FROM ledger_entries WHERE account_id=?", (member_account['account_id'],)).fetchone()[0]
            self.assertEqual(net_ledger, 22000)
            self.assertEqual(db.execute(
                "SELECT COUNT(*) FROM transactions WHERE request_id='shared-card-cash-0001'").fetchone()[0], 1)
        finally:
            db.close()

if __name__ == '__main__':
    unittest.main()
