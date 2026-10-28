from datetime import datetime, timezone
from uuid import uuid4


class PromotionService:
    METHODS = {"NFC"}
    SCOPES = {"global", "local"}

    def __init__(self, db):
        self.db = db

    @staticmethod
    def _now():
        return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")

    def list(self, machine_id=None, payment_method=None, include_disabled=True):
        clauses = []
        args = []
        if machine_id is not None:
            clauses.append("(scope='global' OR machine_id=?)")
            args.append(machine_id)
        if payment_method is not None:
            clauses.append("payment_method=?")
            args.append(payment_method)
        if not include_disabled:
            clauses.append("enabled=1")
        where = (" WHERE " + " AND ".join(clauses)) if clauses else ""
        with self.db.connect() as c:
            rows = c.execute(
                f"""
                SELECT promo_id,scope,machine_id,product_id,payment_method,
                       payment_provider,discount_percent,starts_at,ends_at,
                       priority,enabled,created_at,updated_at
                FROM vending_promotion_policies
                {where}
                ORDER BY scope,priority DESC,created_at DESC
                """,
                tuple(args),
            ).fetchall()
            return [dict(r) for r in rows]

    def create(self, scope, machine_id, product_id, payment_method,
               payment_provider, discount_percent, starts_at=None,
               ends_at=None, priority=0, enabled=True):
        if scope not in self.SCOPES:
            raise ValueError("invalid_promo_scope")
        if payment_method not in self.METHODS:
            raise ValueError("invalid_payment_method")
        if scope == "global":
            machine_id = None
        elif not machine_id:
            raise ValueError("machine_id_required_for_local_promo")
        discount_percent = float(discount_percent)
        if not 0.1 <= discount_percent <= 100.0:
            raise ValueError("discount_percent_out_of_range")
        if ends_at and starts_at and ends_at <= starts_at:
            raise ValueError("invalid_promo_time_range")
        promo_id = "promo-" + uuid4().hex
        now = self._now()
        with self.db.connect() as c:
            c.execute(
                """
                INSERT INTO vending_promotion_policies
                (promo_id,scope,machine_id,product_id,payment_method,
                 payment_provider,discount_percent,starts_at,ends_at,
                 priority,enabled,created_at,updated_at)
                VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)
                """,
                (promo_id,scope,machine_id,product_id,payment_method,
                 payment_provider,discount_percent,starts_at,ends_at,
                 int(priority),1 if enabled else 0,now,now),
            )
            c.commit()
        return self.get(promo_id)

    def get(self, promo_id):
        with self.db.connect() as c:
            row = c.execute(
                "SELECT * FROM vending_promotion_policies WHERE promo_id=?",
                (promo_id,),
            ).fetchone()
            return dict(row) if row else None

    def update(self, promo_id, **changes):
        current = self.get(promo_id)
        if current is None:
            raise ValueError("promo_not_found")
        merged = {k: current[k] for k in current}
        merged.update({k: v for k, v in changes.items() if v is not None})
        scope = merged["scope"]
        if scope not in self.SCOPES:
            raise ValueError("invalid_promo_scope")
        if merged["payment_method"] not in self.METHODS:
            raise ValueError("invalid_payment_method")
        if scope == "global":
            merged["machine_id"] = None
        elif not merged["machine_id"]:
            raise ValueError("machine_id_required_for_local_promo")
        if not 0.1 <= float(merged["discount_percent"]) <= 100.0:
            raise ValueError("discount_percent_out_of_range")
        if merged["ends_at"] and merged["starts_at"] and merged["ends_at"] <= merged["starts_at"]:
            raise ValueError("invalid_promo_time_range")
        now = self._now()
        with self.db.connect() as c:
            c.execute(
                """
                UPDATE vending_promotion_policies
                SET scope=?,machine_id=?,product_id=?,payment_method=?,
                    payment_provider=?,discount_percent=?,starts_at=?,
                    ends_at=?,priority=?,enabled=?,updated_at=?
                WHERE promo_id=?
                """,
                (merged["scope"],merged["machine_id"],merged["product_id"],
                 merged["payment_method"],merged["payment_provider"],
                 float(merged["discount_percent"]),merged["starts_at"],
                 merged["ends_at"],int(merged["priority"]),
                 1 if merged["enabled"] else 0,now,promo_id),
            )
            c.commit()
        return self.get(promo_id)

    def resolve(self, machine_id, product_id, payment_method, payment_provider=None, now=None):
        if payment_method not in self.METHODS:
            raise ValueError("invalid_payment_method")
        now = now or self._now()
        with self.db.connect() as c:
            row = c.execute(
                """
                SELECT * FROM vending_promotion_policies
                WHERE enabled=1
                  AND payment_method=?
                  AND (payment_provider IS NULL OR payment_provider=?)
                  AND (starts_at IS NULL OR starts_at<=?)
                  AND (ends_at IS NULL OR ends_at>?)
                  AND (
                    scope='global' OR
                    (scope='local' AND machine_id=?)
                  )
                  AND (product_id IS NULL OR product_id=?)
                ORDER BY
                  CASE WHEN scope='local' THEN 1 ELSE 0 END DESC,
                  CASE WHEN product_id IS NOT NULL THEN 1 ELSE 0 END DESC,
                  priority DESC, created_at DESC
                """,
                (payment_method,payment_provider,now,now,machine_id,product_id),
            ).fetchone()
            return dict(row) if row else None

    @staticmethod
    def calculate(original_amount, discount_percent):
        original_amount = int(original_amount)
        if original_amount <= 0:
            raise ValueError("original_amount_must_be_positive")
        discount_percent = float(discount_percent)
        if not 0.1 <= discount_percent <= 100.0:
            raise ValueError("discount_percent_out_of_range")
        discount = int(original_amount * discount_percent / 100.0)
        final_amount = original_amount - discount
        return discount, final_amount
