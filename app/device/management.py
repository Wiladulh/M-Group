class DeviceManagementService:
    ALLOWED_TYPES = {"esp32-cashier", "esp32-vending", "esp32-s3-vending", "cashier", "vending"}
    ALLOWED_STATUS = {"active", "pending", "offline", "disabled", "maintenance", "unassigned"}

    def __init__(self, db):
        self.db = db

    @staticmethod
    def _public_ref(row):
        item = dict(row)
        item.pop("device_id", None)
        return item

    def internal_id_by_key_hint(self, key_hint):
        """Resolve the admin-only, non-secret key hint without exposing the DB key."""
        if not key_hint or not str(key_hint).strip():
            raise ValueError("device_not_found")
        with self.db.connect() as c:
            rows = c.execute(
                "SELECT device_id FROM device_registry WHERE substr(auth_key_hash,1,12)=? AND deleted_at IS NULL",
                (str(key_hint).strip(),),
            ).fetchall()
        if not rows:
            raise ValueError("device_not_found")
        if len(rows) != 1:
            raise ValueError("device_key_hint_not_unique")
        return rows[0]["device_id"]

    def get_by_key_hint(self, key_hint):
        try:
            device_id = self.internal_id_by_key_hint(key_hint)
        except ValueError as exc:
            if str(exc) == "device_not_found":
                return None
            raise
        return self.get(device_id)

    def update_by_key_hint(self, key_hint, device_type=None, status=None, display_name=None):
        device_id = self.internal_id_by_key_hint(key_hint)
        return self.update(device_id, device_type, status, display_name)

    def soft_delete_by_key_hint(self, key_hint):
        device_id = self.internal_id_by_key_hint(key_hint)
        return self.soft_delete(device_id)

    def list(self, include_deleted=False):
        where = "" if include_deleted else "WHERE deleted_at IS NULL"
        with self.db.connect() as c:
            rows = c.execute(
                f"""SELECT device_id,device_type,mac_address,display_name,
                           status,last_seen,substr(auth_key_hash,1,12) AS device_key_hint,created_at,updated_at,deleted_at
                    FROM device_registry {where}
                    ORDER BY device_id"""
            ).fetchall()
            return [self._public_ref(r) for r in rows]

    def get(self, device_id):
        with self.db.connect() as c:
            row = c.execute(
                """SELECT device_id,device_type,mac_address,display_name,
                          status,last_seen,COALESCE(auth_key_hint,substr(auth_key_hash,-10)) AS auth_key_hint,created_at,updated_at,deleted_at
                   FROM device_registry WHERE device_id=?""",
                (device_id,),
            ).fetchone()
            return self._public_ref(row) if row else None

    def update(self, device_id, device_type=None, status=None, display_name=None):
        current = self.get(device_id)
        if current is None:
            raise ValueError("device_not_found")
        if device_type is not None and device_type not in self.ALLOWED_TYPES:
            raise ValueError("invalid_device_type")
        if status is not None and status not in self.ALLOWED_STATUS:
            raise ValueError("invalid_device_status")
        if display_name is not None and not display_name.strip():
            raise ValueError("display_name_required")
        new_type = device_type or current["device_type"]
        new_status = status or current["status"]
        new_name = display_name if display_name is not None else current["display_name"]
        with self.db.connect() as c:
            c.execute(
                """UPDATE device_registry
                   SET device_type=?,status=?,display_name=?,updated_at=CURRENT_TIMESTAMP
                   WHERE device_id=?""",
                (new_type, new_status, new_name, device_id),
            )
            normalized_type = "esp32-s3-vending" if new_type == "esp32-vending" else new_type
            if normalized_type in {"esp32-s3-vending", "vending"}:
                machine_status = new_status if new_status in {"active", "disabled", "maintenance"} else "disabled"
                c.execute(
                    """UPDATE vending_machines
                       SET name=?,location=?,status=?,updated_at=CURRENT_TIMESTAMP
                       WHERE device_id=?""",
                    (new_name, new_name, machine_status, device_id),
                )
            c.commit()
        return self.get(device_id)

    def soft_delete(self, device_id):
        current = self.get(device_id)
        if current is None:
            raise ValueError("device_not_found")
        with self.db.connect() as c:
            c.execute(
                """UPDATE device_registry
                   SET status='disabled',deleted_at=CURRENT_TIMESTAMP,updated_at=CURRENT_TIMESTAMP
                   WHERE device_id=?""",
                (device_id,),
            )
            c.commit()
        return self.get(device_id)
