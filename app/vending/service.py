from uuid import uuid4
from app.payment.service import PaymentService
from app.vending.promo import PromotionService

class VendingService:
    VALID_STATUSES = {"active", "disabled", "maintenance"}

    def __init__(self, db):
        self.db=db
        self.payment=PaymentService(db)
        self.promos=PromotionService(db)

    def machines(self):
        with self.db.connect() as c:
            return [dict(r) for r in c.execute(
                "SELECT machine_id,name,location,device_id,status,created_at,updated_at "
                "FROM vending_machines ORDER BY name,machine_id"
            ).fetchall()]

    def register(self,machine_id,name,location="",device_id=None,status="active"):
        if not machine_id.strip(): raise ValueError("machine_id_required")
        if not name.strip(): raise ValueError("name_required")
        if status not in self.VALID_STATUSES: raise ValueError("invalid_machine_status")
        device_id = device_id.strip() if device_id else None
        with self.db.connect() as c:
            if c.execute("SELECT 1 FROM vending_machines WHERE machine_id=?",(machine_id,)).fetchone():
                raise ValueError("machine_already_exists")
            if device_id and c.execute("SELECT 1 FROM vending_machines WHERE device_id=?",(device_id,)).fetchone():
                raise ValueError("device_already_registered")
            c.execute(
                "INSERT INTO vending_machines(machine_id,name,location,device_id,status) VALUES(?,?,?,?,?)",
                (machine_id,name,location or "",device_id,status)
            )
            c.commit()
        return self.machine(machine_id)

    def update_machine(self,machine_id,name=None,location=None,device_id=None,status=None):
        current=self.machine(machine_id)
        new_name=current["name"] if name is None else name
        new_location=current["location"] if location is None else location
        new_device=current["device_id"] if device_id is None else (device_id.strip() or None)
        new_status=current["status"] if status is None else status
        if not new_name.strip(): raise ValueError("name_required")
        if new_status not in self.VALID_STATUSES: raise ValueError("invalid_machine_status")
        with self.db.connect() as c:
            if new_device and c.execute(
                "SELECT 1 FROM vending_machines WHERE device_id=? AND machine_id<>?",
                (new_device,machine_id)
            ).fetchone():
                raise ValueError("device_already_registered")
            c.execute(
                "UPDATE vending_machines SET name=?,location=?,device_id=?,status=?,updated_at=CURRENT_TIMESTAMP "
                "WHERE machine_id=?",
                (new_name,new_location,new_device,new_status,machine_id)
            )
            c.commit()
        return self.machine(machine_id)

    def set_status(self,machine_id,status):
        return self.update_machine(machine_id,status=status)

    def machine(self,machine_id):
        with self.db.connect() as c:
            r=c.execute(
                "SELECT machine_id,name,location,device_id,status,created_at,updated_at "
                "FROM vending_machines WHERE machine_id=?",(machine_id,)
            ).fetchone()
        if not r: raise ValueError("machine_not_found")
        return dict(r)

    def slots(self,machine_id):
        self.machine(machine_id)
        with self.db.connect() as c:
            rows = {
                r["slot"]: dict(r) for r in c.execute(
                    "SELECT product_id,slot,name,price,stock,capacity,servo_channel,enabled "
                    "FROM vending_products WHERE machine_id=? ORDER BY slot",
                    (machine_id,)
                ).fetchall() if r["slot"] is not None
            }
        return [
            rows.get(slot, {
                "product_id": None, "slot": slot, "name": None, "price": None,
                "stock": 0, "capacity": 0, "servo_channel": slot, "enabled": False
            })
            for slot in range(1,6)
        ]

    def products(self,machine_id):
        self.machine(machine_id)
        with self.db.connect() as c:
            rows = c.execute(
                "SELECT product_id,name,price,stock,enabled,slot,capacity,servo_channel "
                "FROM vending_products WHERE machine_id=? ORDER BY slot,product_id",
                (machine_id,)
            ).fetchall()
        # SQLite stores enabled as 0/1; the public API contract is a JSON boolean.
        return [{**dict(row), "enabled": bool(row["enabled"])} for row in rows]

    def upsert_product(self,machine_id,product_id,name,price,stock,enabled=True,slot=None,capacity=None,servo_channel=None):
        self.machine(machine_id)
        if not product_id.strip() or not name.strip(): raise ValueError("product_required")
        if not isinstance(price,int) or isinstance(price,bool) or price<=0: raise ValueError("price_must_be_positive_integer")
        if not isinstance(stock,int) or isinstance(stock,bool) or stock<0: raise ValueError("stock_must_be_nonnegative_integer")
        if slot is None:
            with self.db.connect() as c:
                existing=c.execute("SELECT slot FROM vending_products WHERE product_id=? AND machine_id=?",(product_id,machine_id)).fetchone()
                if existing and existing["slot"] is not None:
                    slot=existing["slot"]
                else:
                    used={r[0] for r in c.execute("SELECT slot FROM vending_products WHERE machine_id=? AND slot IS NOT NULL",(machine_id,)).fetchall()}
                    free=[x for x in range(1,6) if x not in used]
                    if not free: raise ValueError("no_free_slot")
                    slot=free[0]
        if not isinstance(slot,int) or isinstance(slot,bool) or slot<1 or slot>5: raise ValueError("slot_must_be_1_to_5")
        if capacity is None: capacity=max(stock,0)
        if not isinstance(capacity,int) or isinstance(capacity,bool) or capacity<0: raise ValueError("capacity_must_be_nonnegative_integer")
        if stock>capacity: raise ValueError("stock_exceeds_capacity")
        if servo_channel is None: servo_channel=slot
        if servo_channel != slot: raise ValueError("servo_must_match_slot")
        with self.db.connect() as c:
            conflict=c.execute(
                "SELECT product_id FROM vending_products WHERE machine_id=? AND slot=? AND product_id<>?",
                (machine_id,slot,product_id)
            ).fetchone()
            if conflict: raise ValueError("slot_already_configured")
            c.execute("""INSERT INTO vending_products(product_id,machine_id,name,price,stock,enabled,slot,capacity,servo_channel)
                VALUES(?,?,?,?,?,?,?,?,?) ON CONFLICT(product_id) DO UPDATE SET
                machine_id=excluded.machine_id,name=excluded.name,price=excluded.price,stock=excluded.stock,
                enabled=excluded.enabled,slot=excluded.slot,capacity=excluded.capacity,servo_channel=excluded.servo_channel""",
                (product_id,machine_id,name,price,stock,1 if enabled else 0,slot,capacity,servo_channel))
            c.commit()
        return self.get_product(machine_id,product_id)

    def get_product(self,machine_id,product_id):
        with self.db.connect() as c:
            r=c.execute(
                "SELECT product_id,machine_id,name,price,stock,enabled,slot,capacity,servo_channel "
                "FROM vending_products WHERE product_id=? AND machine_id=?",(product_id,machine_id)
            ).fetchone()
        if not r: raise ValueError("product_not_found")
        return dict(r)

    def begin(self,machine_id,product_id,credential_id,account_id,idempotency_key,payment_method="NFC",payment_provider="local"):
        machine=self.machine(machine_id)
        resolved=self.payment.identity.account_for_credential(credential_id)
        if not resolved["authorized"]:
            raise ValueError(resolved["reason"])
        resolved_account=resolved["account_id"]
        if account_id and account_id != resolved_account:
            raise ValueError("credential_account_mismatch")
        account_id=resolved_account
        if machine["status"]!="active": raise ValueError("machine_not_active")
        if not idempotency_key: raise ValueError("idempotency_key_required")
        if payment_method not in {"NFC","QRIS"}: raise ValueError("unsupported_vending_payment_method")
        if payment_method=="NFC" and payment_provider!="local": raise ValueError("invalid_nfc_provider")
        if payment_method=="QRIS" and not payment_provider: raise ValueError("qris_provider_required")
        with self.db.connect() as c:
            old=c.execute("SELECT * FROM vending_transactions WHERE idempotency_key=?",(idempotency_key,)).fetchone()
            if old: return dict(old)
            p=c.execute("SELECT * FROM vending_products WHERE product_id=? AND machine_id=?",(product_id,machine_id)).fetchone()
            if not p: raise ValueError("product_not_found")
            if not p["enabled"]: raise ValueError("product_disabled")
            if p["stock"]<=0: raise ValueError("out_of_stock")
            promo=self.promos.resolve(machine_id,product_id,payment_method,payment_provider)
            discount=0
            promo_id=None
            if promo:
                discount,_=self.promos.calculate(p["price"],promo["discount_percent"])
                promo_id=promo["promo_id"]
            final_amount=p["price"]-discount
            tx="vend-"+uuid4().hex
            c.execute("""INSERT INTO vending_transactions
                (transaction_id,machine_id,product_id,credential_id,account_id,base_amount,discount_amount,amount,
                 payment_method,payment_provider,payment_status,status,dispense_status,idempotency_key,promo_id)
                VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (tx,machine_id,product_id,credential_id,account_id,p["price"],discount,final_amount,payment_method,payment_provider,
                 "pending","pending","pending",idempotency_key,promo_id))
            c.commit()
        return self.get(tx)

    def authorize(self,transaction_id):
        tx=self.get(transaction_id)
        if tx["status"]=="completed": return tx
        if tx["status"] in {"failed","refunded"}: return tx
        try:
            if tx["payment_method"]=="QRIS":
                raise ValueError("qris_payment_provider_not_activated")
            payment=self.payment.pay(
                tx["credential_id"],None,tx["amount"],
                reference=transaction_id,
                method=tx["payment_method"],
                provider=tx["payment_provider"],
                idempotency_key="vending-payment:"+transaction_id,
                original_amount=tx["base_amount"],
                discount_amount=tx["discount_amount"],
                promo_id=tx.get("promo_id")
            )
        except Exception:
            with self.db.connect() as c:
                c.execute("UPDATE vending_transactions SET status='failed',payment_status='failed',dispense_status='not_started' WHERE transaction_id=?",(transaction_id,))
                c.commit()
            raise
        with self.db.connect() as c:
            c.execute("UPDATE vending_transactions SET status='authorized',payment_status='completed',payment_transaction_id=? WHERE transaction_id=?",(payment["transaction_id"],transaction_id))
            c.commit()
        return self.get(transaction_id)

    def dispense(self,transaction_id,success=True):
        tx=self.get(transaction_id)
        if tx["status"]!="authorized": raise ValueError("transaction_not_authorized")
        if not success: return self._fail_and_refund(tx)
        with self.db.connect() as c:
            p=c.execute("SELECT stock FROM vending_products WHERE product_id=? AND machine_id=?",(tx["product_id"],tx["machine_id"])).fetchone()
            if not p or p["stock"]<=0:
                c.rollback()
                return self._fail_and_refund(tx)
            c.execute("UPDATE vending_products SET stock=stock-1 WHERE product_id=? AND machine_id=? AND stock>0",(tx["product_id"],tx["machine_id"]))
            c.execute("""UPDATE vending_transactions SET status='completed',payment_status='completed',dispense_status='success',
                completed_at=CURRENT_TIMESTAMP WHERE transaction_id=?""",(transaction_id,))
            c.execute("INSERT INTO audit_events(event_type,entity_type,entity_id,detail) VALUES(?,?,?,?)",
                ("vending","vending_transaction",transaction_id,"dispensed"))
            c.commit()
        return self.get(transaction_id)

    def _fail_and_refund(self,tx):
        self.payment.financial.credit(tx["account_id"],tx["amount"],
            reference="refund:"+tx["transaction_id"],
            idempotency_key="vending-refund:"+tx["transaction_id"])
        with self.db.connect() as c:
            c.execute("UPDATE vending_transactions SET status='refunded',payment_status='refunded',dispense_status='failed' WHERE transaction_id=?",(tx["transaction_id"],))
            c.commit()
        return self.get(tx["transaction_id"])

    def get(self,transaction_id):
        with self.db.connect() as c:
            r=c.execute("SELECT * FROM vending_transactions WHERE transaction_id=?",(transaction_id,)).fetchone()
        if not r: raise ValueError("transaction_not_found")
        return dict(r)

    def machine_status(self,machine_id):
        return self.machine(machine_id)
