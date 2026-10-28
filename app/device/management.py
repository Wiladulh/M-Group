import hashlib
import secrets


class DeviceManagementService:
    ALLOWED_TYPES = {"esp32-cashier", "esp32-vending", "esp32-s3-vending", "cashier", "vending"}
    ALLOWED_STATUS = {"active", "pending", "awaiting_device_registration", "offline", "disabled", "maintenance", "unassigned"}

    def __init__(self, db):
        self.db = db

    def list(self, include_deleted=False):
        where = "" if include_deleted else "WHERE deleted_at IS NULL"
        with self.db.connect() as c:
            rows = c.execute(
                f"""SELECT registry_id,hardware_id,device_type,mac_address,display_name,
                           status,last_seen,auth_key_hint,created_at,updated_at,deleted_at
                    FROM device_registry {where}
                    ORDER BY registry_id"""
            ).fetchall()
            return [dict(r) for r in rows]

    def get(self, device_ref):
        if not isinstance(device_ref, str) or not device_ref.strip():
            return None
        device_ref = device_ref.strip()
        with self.db.connect() as c:
            # Resolve the server-issued registry ID first. A physical identifier
            # must never shadow a logical registry identifier with the same text.
            row = c.execute(
                """SELECT registry_id,hardware_id,device_type,mac_address,display_name,
                          status,last_seen,auth_key_hint,created_at,updated_at,deleted_at
                   FROM device_registry WHERE registry_id=?""",
                (device_ref,),
            ).fetchone()
            if row is None:
                row = c.execute(
                    """SELECT registry_id,hardware_id,device_type,mac_address,display_name,
                              status,last_seen,auth_key_hint,created_at,updated_at,deleted_at
                       FROM device_registry WHERE hardware_id=?""",
                    (device_ref,),
                ).fetchone()
            return dict(row) if row else None

    def update(self, device_ref, device_type=None, status=None, display_name=None):
        current = self.get(device_ref)
        if current is None:
            raise ValueError("device_not_found")
        if current["deleted_at"] is not None:
            raise ValueError("device_deleted")
        if current["status"] == "disabled" and status == "active":
            raise ValueError("disabled_device_requires_reprovisioning")
        if device_type is not None and device_type not in self.ALLOWED_TYPES:
            raise ValueError("invalid_device_type")
        if status is not None and status not in self.ALLOWED_STATUS:
            raise ValueError("invalid_device_status")
        if display_name is not None:
            display_name = display_name.strip()
            if not display_name or len(display_name) > 120 or any(ord(ch) < 32 for ch in display_name):
                raise ValueError("invalid_device_location")
        new_type = device_type or current["device_type"]
        new_status = status or current["status"]
        new_name = display_name if display_name is not None else current["display_name"]
        with self.db.connect() as c:
            c.execute(
                """UPDATE device_registry
                   SET device_type=?,status=?,display_name=?,updated_at=CURRENT_TIMESTAMP
                   WHERE registry_id=? AND deleted_at IS NULL""",
                (new_type, new_status, new_name, current["registry_id"]),
            )
            if c.execute("SELECT changes()").fetchone()[0] != 1:
                raise ValueError("device_update_conflict")
            c.commit()
        return self.get(current["registry_id"])

    def rotate_auth_key(self, device_ref):
        """Rotate a device secret; return the plaintext key once to the caller."""
        current = self.get(device_ref)
        if current is None:
            raise ValueError("device_not_found")
        if current["deleted_at"] is not None or current["status"] == "disabled":
            raise ValueError("device_not_active")
        new_key = secrets.token_urlsafe(32)
        digest = hashlib.sha256(new_key.encode("utf-8")).hexdigest()
        hint = new_key[-4:]
        with self.db.connect() as c:
            c.execute("BEGIN IMMEDIATE")
            c.execute(
                """UPDATE device_registry
                   SET auth_key_hash=?,auth_key_hint=?,updated_at=CURRENT_TIMESTAMP
                   WHERE registry_id=? AND deleted_at IS NULL AND status!='disabled'""",
                (digest, hint, current["registry_id"]),
            )
            if c.execute("SELECT changes()").fetchone()[0] != 1:
                raise ValueError("device_key_rotation_conflict")
            c.execute(
                """INSERT INTO device_events(hardware_id,event_type,payload)
                   VALUES(?,?,?)""",
                (current["hardware_id"] or current["registry_id"], "auth_key_rotated", "key rotated by device management"),
            )
            c.commit()
        return {"registry_id": current["registry_id"], "hardware_id": current["hardware_id"], "auth_key": new_key}

    def replace_hardware_mac(self, device_ref, new_mac_address):
        """Rebind a replacement board's MAC while preserving the logical registry ID and key."""
        current = self.get(device_ref)
        if current is None:
            raise ValueError("device_not_found")
        if current["deleted_at"] is not None or current["status"] == "disabled":
            raise ValueError("device_not_active")
        if not isinstance(new_mac_address, str):
            raise ValueError("invalid_mac_address")
        mac = new_mac_address.strip().upper().replace("-", ":")
        parts = mac.split(":")
        if len(parts) != 6 or any(len(part) != 2 for part in parts):
            raise ValueError("invalid_mac_address")
        try:
            octets = [int(part, 16) for part in parts]
        except ValueError as exc:
            raise ValueError("invalid_mac_address") from exc
        if all(value == 0 for value in octets) or all(value == 255 for value in octets) or (octets[0] & 1):
            raise ValueError("invalid_mac_address")
        with self.db.connect() as c:
            c.execute("BEGIN IMMEDIATE")
            duplicate = c.execute(
                "SELECT registry_id FROM device_registry WHERE mac_address=? AND registry_id<>? AND deleted_at IS NULL",
                (mac, current["registry_id"]),
            ).fetchone()
            if duplicate:
                raise ValueError("mac_address_already_registered")
            c.execute(
                """UPDATE device_registry
                   SET hardware_id=?,mac_address=?,updated_at=CURRENT_TIMESTAMP
                   WHERE registry_id=? AND deleted_at IS NULL AND status!='disabled'""",
                (mac, mac, current["registry_id"]),
            )
            if c.execute("SELECT changes()").fetchone()[0] != 1:
                raise ValueError("device_rebind_conflict")
            c.execute(
                """INSERT INTO device_events(hardware_id,event_type,payload)
                   VALUES(?,?,?)""",
                (current["hardware_id"] or current["registry_id"], "hardware_mac_replaced", f"mac={mac}"),
            )
            c.commit()
        return self.get(current["registry_id"])

    def soft_delete(self, device_ref):
        current = self.get(device_ref)
        if current is None:
            raise ValueError("device_not_found")
        if current["deleted_at"] is not None:
            return current
        with self.db.connect() as c:
            c.execute(
                """UPDATE device_registry
                   SET status='disabled',auth_key_hash=NULL,auth_key_hint=NULL,
                       deleted_at=CURRENT_TIMESTAMP,updated_at=CURRENT_TIMESTAMP
                   WHERE registry_id=? AND deleted_at IS NULL""",
                (current["registry_id"],),
            )
            c.commit()
        return self.get(current["registry_id"])
