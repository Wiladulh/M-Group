from fastapi import APIRouter, HTTPException, Header, UploadFile, File, Request, Response
from fastapi.responses import FileResponse
from pydantic import BaseModel
import hashlib
import secrets
import re
import io
from app.identity.service import IdentityService
from app.identity.management import MemberManagementService
from app.device.management import DeviceManagementService
from app.vending.promo import PromotionService
from app.payment.service import PaymentService
from app.financial.service import FinancialService
from app.vending.service import VendingService
from app.core.backup import export_excel, export_rows_excel, create_native_backup, restore_native_backup
from pathlib import Path
from uuid import uuid4
import time
from urllib.parse import urlsplit
from PIL import Image, UnidentifiedImageError
from app.core.auth import hash_password, hash_session_token, new_session_token, verify_password

MAX_BACKUP_UPLOAD_BYTES = 100 * 1024 * 1024

class PaymentRequest(BaseModel):
    credential_id: str
    account_id: str | None = None
    amount: int | None = None
    reference: str | None = None
    method: str = "NFC"
    provider: str = "local"
    idempotency_key: str | None = None
    pin: str | None = None
    original_amount: int | None = None
    discount_amount: int = 0
    promo_id: str | None = None

    @__import__("pydantic").field_validator("idempotency_key")
    @classmethod
    def validate_idempotency_key(cls, value):
        return value.strip() if value is not None else None

class PinRequest(BaseModel):
    pin: str
    operator_id: str = "admin"
    reason: str = "member_request"
    identity_verified: bool = False

class MemberCorrectionRequest(BaseModel):
    original_transaction_id: str
    corrected_amount: int
    reason: str
    idempotency_key: str
    operator_id: str

class MemberCreateRequest(BaseModel):
    name: str
    nik: str | None = None
    address: str | None = None
    birth_place: str | None = None
    birth_date: str | None = None
    sex: str | None = None
    rt: str | None = None
    rw: str | None = None
    village: str | None = None
    district: str | None = None
    city_regency: str | None = None
    province: str | None = None
    religion: str | None = None
    marital_status: str | None = None
    occupation: str | None = None
    citizenship: str | None = None
    phone: str | None = None
    email: str | None = None
    registration_date: str | None = None

class MemberUpdateRequest(BaseModel):
    name: str | None = None
    nik: str | None = None
    address: str | None = None
    birth_place: str | None = None
    birth_date: str | None = None
    sex: str | None = None
    rt: str | None = None
    rw: str | None = None
    village: str | None = None
    district: str | None = None
    city_regency: str | None = None
    province: str | None = None
    religion: str | None = None
    marital_status: str | None = None
    occupation: str | None = None
    citizenship: str | None = None
    phone: str | None = None
    email: str | None = None
    registration_date: str | None = None
    status: str | None = None

class NfcCardRequest(BaseModel):
    card_uid: str
    credential_id: str | None = None

class PromoRequest(BaseModel):
    scope: str
    machine_id: str | None = None
    product_id: str | None = None
    payment_method: str
    payment_provider: str | None = None
    discount_percent: float
    starts_at: str | None = None
    ends_at: str | None = None
    priority: int = 0
    enabled: bool = True

class PromoUpdateRequest(BaseModel):
    scope: str | None = None
    machine_id: str | None = None
    product_id: str | None = None
    payment_method: str | None = None
    payment_provider: str | None = None
    discount_percent: float | None = None
    starts_at: str | None = None
    ends_at: str | None = None
    priority: int | None = None
    enabled: bool | None = None

class DeviceHeartbeatRequest(BaseModel):
    device_type: str
    status: str = "active"
    display_name: str | None = None

class DeviceRegisterRequest(BaseModel):
    device_type: str
    device_id: str | None = None
    hardware_id: str
    mac_address: str
    device_key: str

class DeviceProvisionRequest(BaseModel):
    device_type: str
    location: str = ""

class FinancialRequest(BaseModel):
    amount: int
    reference: str | None = None
    idempotency_key: str | None = None

    @__import__("pydantic").field_validator("idempotency_key")
    @classmethod
    def validate_idempotency_key(cls, value):
        if value is None:
            return None
        value=value.strip()
        if len(value)<8 or len(value)>128:
            raise ValueError("invalid_idempotency_key")
        return value

class VendingRegisterRequest(BaseModel):
    machine_id: str
    name: str
    location: str = ""
    hardware_id: str | None = None
    status: str = "active"

class VendingUpdateRequest(BaseModel):
    name: str | None = None
    location: str | None = None
    hardware_id: str | None = None
    status: str | None = None

class VendingProductRequest(BaseModel):
    product_id: str
    name: str
    price: int
    stock: int
    enabled: bool = True
    slot: int | None = None
    capacity: int | None = None
    servo_channel: int | None = None

MAX_PRODUCT_IMAGE_BYTES = 2 * 1024 * 1024
MAX_OPTIMIZED_PRODUCT_IMAGE_BYTES = 64 * 1024

class VendingBeginRequest(BaseModel):
    product_id: str
    credential_id: str
    account_id: str | None = None
    idempotency_key: str
    payment_method: str = "NFC"
    payment_provider: str = "local"

class VendingDispenseRequest(BaseModel):
    success: bool = True

class NfcRegistrationStartRequest(BaseModel):
    # Selected active cashier; the session is bound to its server-held key fingerprint.
    cashier_hardware_id: str | None = None
    operator_id: str = "admin"

class NfcRegistrationCompleteRequest(BaseModel):
    session_id: str
    card_uid: str
    pin: str

class NfcRegistrationProgressRequest(BaseModel):
    session_id: str
    status: str

class CashierDepositRequest(BaseModel):
    credential_id: str
    amount: int
    operator_pin: str
    member_pin: str
    idempotency_key: str

class MemberBalanceLookupRequest(BaseModel):
    card_uid: str
    # Optional compatibility field; authentication is by device key only.
    hardware_id: str | None = None

class OperatorPinRequest(BaseModel):
    pin: str

class AdminLoginRequest(BaseModel):
    username: str
    password: str

class AdminAccountUpdateRequest(BaseModel):
    current_password: str
    username: str
    new_password: str | None = None

class AdminUserCreateRequest(BaseModel):
    username: str
    password: str
    role: str

    @__import__("pydantic").field_validator("role")
    @classmethod
    def validate_role(cls, value):
        if value not in {"super_admin", "operator", "auditor"}:
            raise ValueError("invalid_admin_role")
        return value

class AdminUserStatusRequest(BaseModel):
    is_active: bool

class AdminUserPasswordRequest(BaseModel):
    password: str

class AdminUserRoleRequest(BaseModel):
    role: str

    @__import__("pydantic").field_validator("role")
    @classmethod
    def validate_role(cls, value):
        if value not in {"super_admin", "operator", "auditor"}:
            raise ValueError("invalid_admin_role")
        return value

def request_is_https(request: Request) -> bool:
    return request.url.scheme.lower() == "https"

def build_router(db, app_settings=None):
    r = APIRouter(prefix="/api/v1")
    if app_settings is None:
        app_settings = __import__("app.core.config",fromlist=["get_settings"]).get_settings()
    identity = IdentityService(db)
    members = MemberManagementService(db)
    devices = DeviceManagementService(db)
    promos = PromotionService(db)
    payments = PaymentService(db)
    financial = FinancialService(db)
    vending = VendingService(db)

    def require_device_by_key(device_key: str | None, allowed_types=None):
        """Authenticate using the server-issued key, independent of public device IDs."""
        if not device_key:
            raise HTTPException(401,"device_auth_required")
        got=hashlib.sha256(device_key.encode("utf-8")).hexdigest()
        with db.connect() as c:
            rows=c.execute("SELECT registry_id,hardware_id,mac_address,device_type,status,auth_key_hash FROM device_registry WHERE auth_key_hash IS NOT NULL AND status<>'disabled' AND deleted_at IS NULL").fetchall()
        row=next((item for item in rows if secrets.compare_digest(got,item["auth_key_hash"] or "")),None)
        if not row:
            raise HTTPException(403,"invalid_device_key")
        if row["status"]!="active":
            raise HTTPException(403,"device_not_active")
        type_aliases={"cashier":"esp32-cashier","vending":"esp32-s3-vending","esp32-vending":"esp32-s3-vending"}
        device_type=type_aliases.get(row["device_type"],row["device_type"])
        if allowed_types and device_type not in allowed_types:
            raise HTTPException(403,"device_type_not_allowed")
        return {"fingerprint":got,"registry_id":row["registry_id"],"device_id":row["registry_id"],"hardware_id":row["hardware_id"],"mac_address":row["mac_address"],"device_type":device_type}

    def require_device(hardware_id: str, device_key: str | None):
        """Legacy adapter; new endpoints should use require_device_by_key."""
        identity=require_device_by_key(device_key)
        with db.connect() as c:
            row=c.execute("SELECT hardware_id FROM device_registry WHERE hardware_id=?",(hardware_id,)).fetchone()
        if not row or (row["hardware_id"] and identity["hardware_id"] and row["hardware_id"]!=identity["hardware_id"]):
            raise HTTPException(403,"hardware_identity_mismatch")
        return identity


    def resolve_vending_machine(identifier: str):
        """Resolve firmware device IDs and WebUI machine IDs to one canonical machine."""
        with db.connect() as c:
            row = c.execute(
                """SELECT machine_id FROM vending_machines
                   WHERE machine_id=? OR hardware_id=? OR hardware_id IN
                     (SELECT registry_id FROM device_registry WHERE registry_id=?)
                   ORDER BY CASE WHEN machine_id=? THEN 0 ELSE 1 END LIMIT 1""",
                (identifier, identifier, identifier, identifier),
            ).fetchone()
        if not row:
            raise HTTPException(404, "machine_not_found")
        try:
            return vending.machine(row["machine_id"])
        except ValueError as e:
            raise HTTPException(404, str(e))

    def public_vending_transaction(tx):
        result = dict(tx)
        with db.connect() as c:
            row = c.execute(
                "SELECT slot FROM vending_products WHERE product_id=? AND machine_id=?",
                (result.get("product_id"), result.get("machine_id")),
            ).fetchone()
        if row and row["slot"] in range(1, 6):
            result["product_id"] = str(row["slot"])
        return result

    def require_super_admin(request: Request):
        # Reuse session, read-only role, and same-origin checks for all privileged routes.
        require_admin(request)
        if getattr(request.state, "admin_role", None) != "super_admin":
            raise HTTPException(403, "admin_role_forbidden")

    @r.get("/admin/users")
    def list_admin_users(request: Request):
        require_super_admin(request)
        with db.connect() as c:
            rows = c.execute(
                "SELECT username,role,is_active,created_at,updated_at,created_by FROM admin_users ORDER BY username"
            ).fetchall()
        return {"users": [dict(row) for row in rows]}

    @r.post("/admin/users")
    def create_admin_user(q: AdminUserCreateRequest, request: Request):
        require_super_admin(request)
        username = q.username.strip()
        if len(username) < 3 or len(username) > 64 or any(not (ch.isalnum() or ch in "._-") for ch in username):
            raise HTTPException(400, "invalid_admin_username")
        if len(q.password) < 12:
            raise HTTPException(400, "password_too_short")
        now = int(time.time())
        actor = getattr(request.state, "admin_username", "")
        with db.connect() as c:
            try:
                c.execute(
                    "INSERT INTO admin_users(username,password_hash,role,is_active,created_at,updated_at,created_by) VALUES(?,?,?,?,?,?,?)",
                    (username, hash_password(q.password), q.role, 1, now, now, actor),
                )
            except __import__("sqlite3").IntegrityError:
                raise HTTPException(409, "admin_username_already_exists")
            c.execute(
                "INSERT INTO admin_security_events(actor_username,event_type,target_username,detail,created_at) VALUES(?,?,?,?,?)",
                (actor, "admin_created", username, "role="+q.role, now),
            )
            c.commit()
        return {"created": True, "username": username, "role": q.role}

    @r.post("/admin/users/{username}/password")
    def reset_admin_user_password(username: str, q: AdminUserPasswordRequest, request: Request):
        require_super_admin(request)
        if username == getattr(request.state, "admin_username", ""):
            raise HTTPException(409, "use_self_service_for_current_admin")
        if len(q.password) < 12:
            raise HTTPException(400, "password_too_short")
        actor = getattr(request.state, "admin_username", "")
        now = int(time.time())
        with db.connect() as c:
            target = c.execute("SELECT username,role,is_active FROM admin_users WHERE username=?", (username,)).fetchone()
            if not target:
                raise HTTPException(404, "admin_user_not_found")
            if target["role"] == "super_admin" and not target["is_active"]:
                raise HTTPException(409, "cannot_reset_disabled_super_admin")
            c.execute("UPDATE admin_users SET password_hash=?,updated_at=? WHERE username=?", (hash_password(q.password), now, username))
            c.execute("UPDATE webui_sessions SET revoked_at=? WHERE username=? AND revoked_at IS NULL", (now, username))
            c.execute(
                "INSERT INTO admin_security_events(actor_username,event_type,target_username,detail,created_at) VALUES(?,?,?,?,?)",
                (actor, "admin_password_reset", username, "sessions_revoked=1", now),
            )
            c.commit()
        return {"updated": True, "username": username, "sessions_revoked": True}

    @r.patch("/admin/users/{username}/role")
    def set_admin_user_role(username: str, q: AdminUserRoleRequest, request: Request):
        require_super_admin(request)
        actor = getattr(request.state, "admin_username", "")
        if username == actor:
            raise HTTPException(409, "cannot_change_current_admin_role")
        now = int(time.time())
        with db.connect() as c:
            target = c.execute("SELECT username,role,is_active FROM admin_users WHERE username=?", (username,)).fetchone()
            if not target:
                raise HTTPException(404, "admin_user_not_found")
            if target["role"] == q.role:
                return {"updated": False, "username": username, "role": q.role}
            if target["role"] == "super_admin" and target["is_active"] and q.role != "super_admin":
                active = c.execute("SELECT COUNT(*) FROM admin_users WHERE role='super_admin' AND is_active=1").fetchone()[0]
                if active <= 1:
                    raise HTTPException(409, "cannot_demote_last_super_admin")
            c.execute("UPDATE admin_users SET role=?,updated_at=? WHERE username=?", (q.role, now, username))
            c.execute("UPDATE webui_sessions SET revoked_at=? WHERE username=? AND revoked_at IS NULL", (now, username))
            c.execute(
                "INSERT INTO admin_security_events(actor_username,event_type,target_username,detail,created_at) VALUES(?,?,?,?,?)",
                (actor, "admin_role_changed", username, "role="+q.role+";sessions_revoked=1", now),
            )
            c.commit()
        return {"updated": True, "username": username, "role": q.role, "sessions_revoked": True}

    @r.patch("/admin/users/{username}/status")
    def set_admin_user_status(username: str, q: AdminUserStatusRequest, request: Request):
        require_super_admin(request)
        actor = getattr(request.state, "admin_username", "")
        now = int(time.time())
        if username == actor and not q.is_active:
            raise HTTPException(409, "cannot_disable_current_admin")
        with db.connect() as c:
            target = c.execute("SELECT username,role,is_active FROM admin_users WHERE username=?", (username,)).fetchone()
            if not target:
                raise HTTPException(404, "admin_user_not_found")
            if target["role"] == "super_admin" and q.is_active == 0:
                active = c.execute("SELECT COUNT(*) FROM admin_users WHERE role='super_admin' AND is_active=1").fetchone()[0]
                if active <= 1:
                    raise HTTPException(409, "cannot_disable_last_super_admin")
            c.execute("UPDATE admin_users SET is_active=?,updated_at=? WHERE username=?", (int(q.is_active), now, username))
            if not q.is_active:
                c.execute("UPDATE webui_sessions SET revoked_at=? WHERE username=? AND revoked_at IS NULL", (now, username))
            c.execute(
                "INSERT INTO admin_security_events(actor_username,event_type,target_username,detail,created_at) VALUES(?,?,?,?,?)",
                (actor, "admin_status_changed", username, "is_active="+str(int(q.is_active)), now),
            )
            c.commit()
        return {"updated": True, "username": username, "is_active": q.is_active}

    @r.post("/auth/login")
    def admin_login(q: AdminLoginRequest, request: Request, response: Response):
        username = q.username.strip()
        configured_username = getattr(app_settings, "admin_username", "")
        configured_hash = getattr(app_settings, "admin_password_hash", "")
        if request.headers.get("origin"):
            origin = urlsplit(request.headers["origin"])
            if origin.netloc != request.headers.get("host") or origin.scheme.lower() != request.url.scheme.lower():
                raise HTTPException(403, "cross_origin_request_rejected")
        client_ip = request.client.host if request.client else "unknown"
        client_key = hashlib.sha256(client_ip.encode("utf-8")).hexdigest()
        now = int(time.time())
        with db.connect() as c:
            account = c.execute(
                "SELECT username,password_hash,role,is_active FROM admin_users WHERE username=?",
                (username,),
            ).fetchone()
            admin_count = c.execute("SELECT COUNT(*) FROM admin_users").fetchone()[0]
            if admin_count == 0:
                legacy = c.execute(
                    "SELECT username,password_hash FROM webui_admin_accounts ORDER BY updated_at DESC LIMIT 1"
                ).fetchone()
                if legacy is None and configured_username and configured_hash:
                    c.execute(
                        "INSERT OR IGNORE INTO webui_admin_accounts(username,password_hash,updated_at) VALUES(?,?,?)",
                        (configured_username, configured_hash, now),
                    )
                    legacy = c.execute(
                        "SELECT username,password_hash FROM webui_admin_accounts ORDER BY updated_at DESC LIMIT 1"
                    ).fetchone()
                if legacy:
                    c.execute(
                        "INSERT OR IGNORE INTO admin_users(username,password_hash,role,is_active,created_at,updated_at,created_by) VALUES(?,?,'super_admin',1,?,?,?)",
                        (legacy["username"], legacy["password_hash"], now, now, "migration"),
                    )
                    c.execute(
                        "INSERT INTO admin_security_events(actor_username,event_type,target_username,detail,created_at) VALUES(?,?,?,?,?)",
                        ("system", "legacy_admin_imported", legacy["username"], "Legacy admin account promoted to super_admin", now),
                    )
                    account = c.execute(
                        "SELECT username,password_hash,role,is_active FROM admin_users WHERE username=?",
                        (username,),
                    ).fetchone()
            failures = c.execute(
                "SELECT COUNT(*) FROM webui_login_attempts WHERE client_key=? AND succeeded=0 AND attempted_at>=?",
                (client_key, now - 900),
            ).fetchone()[0]
            c.commit()
        if account is None:
            with db.connect() as c:
                configured = c.execute("SELECT COUNT(*) FROM admin_users WHERE is_active=1").fetchone()[0]
            if configured == 0:
                raise HTTPException(503, "admin_login_not_configured")
        if failures >= 10:
            raise HTTPException(429, "login_rate_limited")
        password_valid = verify_password(q.password, account["password_hash"]) if account else False
        username_valid = bool(account) and secrets.compare_digest(username, account["username"])
        valid = username_valid and password_valid and bool(account["is_active"])
        with db.connect() as c:
            c.execute(
                "INSERT INTO webui_login_attempts(client_key,attempted_at,succeeded) VALUES(?,?,?)",
                (client_key, now, 1 if valid else 0),
            )
            c.execute("DELETE FROM webui_login_attempts WHERE attempted_at<?", (now - 86400,))
            if valid:
                token = new_session_token()
                c.execute(
                    "INSERT INTO webui_sessions(session_hash,username,created_at,last_seen,expires_at) VALUES(?,?,?,?,?)",
                    (hash_session_token(token), account["username"], now, now, now + 43200),
                )
            c.commit()
        if not valid:
            raise HTTPException(401, "invalid_username_or_password")
        response.set_cookie(
            key="m_group_session", value=token, max_age=43200, httponly=True,
            secure=request_is_https(request), samesite="lax", path="/",
        )
        return {"authenticated": True, "username": account["username"], "role": account["role"]}

    @r.get("/auth/session")
    def admin_session(request: Request):
        token = request.cookies.get("m_group_session", "")
        if not token:
            raise HTTPException(401, "admin_session_required")
        now = int(time.time())
        with db.connect() as c:
            row = c.execute(
                """SELECT s.username,u.role FROM webui_sessions s
                   JOIN admin_users u ON u.username=s.username
                   WHERE s.session_hash=? AND s.revoked_at IS NULL AND s.expires_at>?
                     AND s.last_seen>? AND u.is_active=1""",
                (hash_session_token(token), now, now - 1800),
            ).fetchone()
            if row:
                c.execute("UPDATE webui_sessions SET last_seen=? WHERE session_hash=?",
                          (now, hash_session_token(token)))
                c.commit()
        if not row:
            raise HTTPException(401, "admin_session_expired")
        return {"authenticated": True, "username": row["username"], "role": row["role"]}

    @r.post("/auth/account")
    def admin_account_update(q: AdminAccountUpdateRequest, request: Request):
        if getattr(request.state, "admin_role", None) == "auditor":
            raise HTTPException(403, "admin_role_read_only")
        origin = request.headers.get("origin")
        if not origin or urlsplit(origin).netloc != request.headers.get("host") or urlsplit(origin).scheme.lower() != request.url.scheme.lower():
            raise HTTPException(403, "same_origin_required")
        token = request.cookies.get("m_group_session", "")
        if not token:
            raise HTTPException(401, "admin_session_required")
        username = q.username.strip()
        if len(username) < 3 or len(username) > 64 or any(
            not (ch.isalnum() or ch in "._-") for ch in username
        ):
            raise HTTPException(400, "invalid_admin_username")
        if q.new_password is not None and len(q.new_password) < 12:
            raise HTTPException(400, "password_too_short")
        now = int(time.time())
        session_hash = hash_session_token(token)
        with db.connect() as c:
            session = c.execute(
                """SELECT username FROM webui_sessions
                   WHERE session_hash=? AND revoked_at IS NULL AND expires_at>? AND last_seen>?""",
                (session_hash, now, now - 1800),
            ).fetchone()
            if session is None:
                raise HTTPException(401, "admin_session_expired")
            account = c.execute(
                "SELECT password_hash FROM admin_users WHERE username=? AND is_active=1",
                (session["username"],),
            ).fetchone()
            if account is None or not verify_password(q.current_password, account["password_hash"]):
                raise HTTPException(403, "invalid_current_password")
            password_hash = hash_password(q.new_password) if q.new_password else account["password_hash"]
            duplicate = c.execute("SELECT 1 FROM admin_users WHERE username<>? AND username=?", (session["username"], username)).fetchone()
            if duplicate:
                raise HTTPException(409, "admin_username_already_exists")
            c.execute(
                "UPDATE admin_users SET username=?,password_hash=?,updated_at=? WHERE username=?",
                (username, password_hash, now, session["username"]),
            )
            c.execute("DELETE FROM webui_admin_accounts")
            c.execute(
                "INSERT INTO webui_admin_accounts(username,password_hash,updated_at) VALUES(?,?,?)",
                (username, password_hash, now),
            )
            c.execute(
                "INSERT INTO admin_security_events(actor_username,event_type,target_username,detail,created_at) VALUES(?,?,?,?,?)",
                (session["username"], "account_updated", username, "Username/password updated", now),
            )
            c.execute(
                "UPDATE webui_sessions SET revoked_at=? WHERE revoked_at IS NULL AND session_hash<>?",
                (now, session_hash),
            )
            c.execute(
                "UPDATE webui_sessions SET username=?,last_seen=? WHERE session_hash=?",
                (username, now, session_hash),
            )
            c.commit()
        return {"updated": True, "username": username, "password_changed": bool(q.new_password)}

    @r.post("/auth/logout")
    def admin_logout(request: Request, response: Response):
        origin = request.headers.get("origin")
        if not origin or urlsplit(origin).netloc != request.headers.get("host") or urlsplit(origin).scheme.lower() != request.url.scheme.lower():
            raise HTTPException(403, "same_origin_required")
        token = request.cookies.get("m_group_session", "")
        if token:
            with db.connect() as c:
                c.execute(
                    "UPDATE webui_sessions SET revoked_at=? WHERE session_hash=? AND revoked_at IS NULL",
                    (int(time.time()), hash_session_token(token)),
                )
                c.commit()
        response.delete_cookie("m_group_session", path="/", httponly=True,
                               secure=request_is_https(request), samesite="lax")
        return {"authenticated": False}

    @r.get("/health")
    def health(): return {"status": "ok", "service": "M-Group"}

    @r.get("/system")
    def system(): return {"service": "M-Group", "api_version": "v1"}

    @r.get("/audit")
    def audit(request: Request, limit: int = 100):
        require_admin(request)
        limit=max(1,min(limit,500))
        with db.connect() as c:
            rows=c.execute("SELECT id,event_type,entity_type,entity_id,detail,created_at FROM audit_events ORDER BY id DESC LIMIT ?",(limit,)).fetchall()
            security_rows=c.execute("SELECT id,actor_username,event_type,target_username,detail,created_at FROM admin_security_events ORDER BY created_at DESC LIMIT ?",(limit,)).fetchall()
        events=[dict(x) for x in rows]
        for row in security_rows:
            event=dict(row)
            event["id"]="admin-"+str(event.pop("id"))
            event["entity_type"]="admin_user"
            event["entity_id"]=event.pop("target_username")
            event["detail"]="actor="+str(event.pop("actor_username") or "system")+"; "+str(event.get("detail") or "")
            event["created_at"]=time.strftime("%Y-%m-%d %H:%M:%S",time.gmtime(int(event["created_at"])))
            events.append(event)
        events.sort(key=lambda item:str(item.get("created_at") or ""),reverse=True)
        return {"events":events[:limit]}

    @r.post("/devices/handshake")
    def device_handshake(q: DeviceRegisterRequest):
        """Backward-compatible alias; validation and event logging live in register."""
        result = device_register(q)
        return {**result, "handshake": "accepted"}

    @r.get("/devices/{hardware_id}/events")
    def device_events(request: Request, hardware_id,limit:int=100):
        require_admin(request)
        limit=max(1,min(limit,500))
        with db.connect() as c:
            rows=c.execute("SELECT id,event_type,payload,created_at FROM device_events WHERE hardware_id=? ORDER BY id DESC LIMIT ?",(hardware_id,limit)).fetchall()
        return {"hardware_id":hardware_id,"events":[dict(x) for x in rows]}

    @r.get("/dashboard")
    def dashboard(request: Request, period: str = "1w"):
        require_admin(request)
        analytics_periods = {
            "1d": ("strftime('%H:00', created_at)", "start of day"),
            "1w": ("date(created_at)", "-6 days"),
            "1m": ("date(created_at)", "-29 days"),
            "3m": ("strftime('%Y-W%W', created_at)", "-89 days"),
            "5m": ("strftime('%Y-W%W', created_at)", "-149 days"),
            "1y": ("strftime('%Y-%m', created_at)", "-364 days"),
        }
        if period not in analytics_periods:
            raise HTTPException(400, "invalid_analytics_period")
        bucket_expr, date_modifier = analytics_periods[period]
        with db.connect() as c:
            members=c.execute("SELECT member_id,name,status,created_at FROM identity_members ORDER BY created_at DESC").fetchall()
            accounts=c.execute("""SELECT a.account_id,a.member_id,m.name AS member_name,a.account_type,a.status,a.created_at
                   FROM financial_accounts a JOIN identity_members m ON m.member_id=a.member_id ORDER BY a.created_at DESC""").fetchall()
            payments_rows=c.execute("""SELECT p.transaction_id,p.credential_id,p.account_id,p.amount,p.final_amount,p.status,
                       p.method,p.provider,p.transaction_source,p.created_at,d.hardware_id AS device_hardware_id
                   FROM payment_transactions p
                   LEFT JOIN payment_device_associations d ON d.transaction_id=p.transaction_id
                   ORDER BY p.created_at DESC LIMIT 50""").fetchall()
            vending_rows=c.execute("""SELECT transaction_id,machine_id,product_id,account_id,amount,status,created_at
                   FROM vending_transactions ORDER BY created_at DESC LIMIT 50""").fetchall()
            loans=c.execute("""SELECT loan_id,member_id,principal,installment_amount,remaining_balance,status,created_at
                   FROM loan_accounts ORDER BY created_at DESC LIMIT 50""").fetchall()
            machines=c.execute("SELECT machine_id,name,status,location,hardware_id,NULL AS last_seen FROM vending_machines ORDER BY name").fetchall()
            products=c.execute("""SELECT CAST(slot AS TEXT) AS product_id,machine_id,name,price,stock,capacity,slot,slot AS servo_channel,enabled
                   FROM vending_products WHERE slot BETWEEN 1 AND 5 ORDER BY machine_id,slot""").fetchall()
            devices=c.execute("SELECT hardware_id,device_type,status,last_seen FROM device_registry ORDER BY hardware_id").fetchall()
            cashier_count=c.execute(
                "SELECT COUNT(*) FROM payment_transactions WHERE transaction_source='CASHIER' AND status='completed'"
            ).fetchone()[0]
            cashier_out=c.execute(
                "SELECT COALESCE(SUM(COALESCE(final_amount,amount)),0) FROM payment_transactions "
                "WHERE transaction_source='CASHIER' AND status='completed' AND created_at>=date('now')"
            ).fetchone()[0]
            cashier_in=c.execute(
                "SELECT COALESCE(SUM(amount),0) FROM cashier_deposits "
                "WHERE status='completed' AND created_at>=date('now')"
            ).fetchone()[0]
            vending_count=c.execute(
                "SELECT COUNT(*) FROM vending_transactions WHERE transaction_source='VENDING' AND status='completed'"
            ).fetchone()[0]
            vending_in=c.execute(
                "SELECT COALESCE(SUM(amount),0) FROM vending_transactions "
                "WHERE transaction_source='VENDING' AND status='completed' AND created_at>=date('now')"
            ).fetchone()[0]
            analytics_rows=c.execute(f"""
                SELECT bucket,COUNT(*) AS transactions FROM (
                    SELECT {bucket_expr} AS bucket,created_at FROM payment_transactions
                      WHERE transaction_source='CASHIER' AND status='completed'
                    UNION ALL
                    SELECT {bucket_expr} AS bucket,created_at FROM cashier_deposits
                      WHERE status='completed'
                    UNION ALL
                    SELECT {bucket_expr} AS bucket,created_at FROM vending_transactions
                      WHERE status='completed'
                )
                WHERE created_at>=datetime('now',?)
                GROUP BY bucket ORDER BY bucket
            """,(date_modifier,)).fetchall()
            most_used_rows=c.execute("""
                SELECT m.machine_id,m.name,m.location,COUNT(v.transaction_id) AS transactions
                FROM vending_machines m LEFT JOIN vending_transactions v
                  ON v.machine_id=m.machine_id AND v.status='completed' AND v.created_at>=datetime('now',?)
                GROUP BY m.machine_id,m.name,m.location ORDER BY transactions DESC,m.name LIMIT 5
            """,(date_modifier,)).fetchall()
            best_selling_rows=c.execute("""
                SELECT CAST(v.product_id AS TEXT) AS product_id,
                       COALESCE(p.name,'Produk ' || v.product_id) AS product_name,
                       v.machine_id, m.name AS vending_name, m.location,
                       i.sha256 AS image_sha256,
                       CASE WHEN i.sha256 IS NOT NULL THEN '/api/v1/vending/' || v.machine_id || '/products/' || CAST(v.product_id AS TEXT) || '/image?v=' || i.sha256 ELSE NULL END AS image_url,
                       COUNT(v.transaction_id) AS units_sold,
                       COALESCE(SUM(v.amount),0) AS revenue
                FROM vending_transactions v
                LEFT JOIN vending_machines m ON m.machine_id=v.machine_id
                LEFT JOIN vending_products p
                  ON p.machine_id=v.machine_id AND CAST(p.slot AS TEXT)=CAST(v.product_id AS TEXT)
                LEFT JOIN vending_product_images i
                  ON i.machine_id=v.machine_id AND CAST(i.product_id AS TEXT)=CAST(v.product_id AS TEXT)
                WHERE v.status='completed' AND v.created_at>=datetime('now',?)
                GROUP BY v.machine_id,v.product_id,p.name,m.name,m.location,i.sha256
                ORDER BY units_sold DESC,revenue DESC,product_name LIMIT 10
            """,(date_modifier,)).fetchall()
            payment_channel_rows=c.execute("""
                SELECT COALESCE(method,'Unknown') AS method,COUNT(*) AS transactions,
                       COALESCE(SUM(COALESCE(final_amount,amount)),0) AS amount
                FROM payment_transactions WHERE status='completed' AND created_at>=datetime('now',?)
                GROUP BY method ORDER BY transactions DESC
            """,(date_modifier,)).fetchall()
        return {"members":[dict(x) for x in members],
                "accounts":[{**dict(x),"balance":financial.balance(x["account_id"])} for x in accounts],
                "payments":[dict(x) for x in payments_rows],"vending_transactions":[dict(x) for x in vending_rows],"loans":[dict(x) for x in loans],
                "machines":[dict(x) for x in machines],"products":[dict(x) for x in products],
                "devices":[dict(x) for x in devices],
                "analytics_period":period,"analytics":[dict(x) for x in analytics_rows],"most_used_vending":[dict(x) for x in most_used_rows],"best_selling_products":[dict(x) for x in best_selling_rows],"payment_channels":[dict(x) for x in payment_channel_rows],
                "stats":{
                    "cashier_transactions":cashier_count,
                    "cashier_money_in_today":cashier_in,
                    "cashier_money_out_today":cashier_out,
                    "vending_transactions":vending_count,
                    "vending_money_in_today":vending_in
                }}

    def require_admin(request: Request):
        if not getattr(request.state, "admin_authenticated", False):
            raise HTTPException(401, "admin_session_required")
        # Auditors have read-only access. All write endpoints using this guard
        # are denied before reaching their business logic.
        if getattr(request.state, "admin_role", None) == "auditor" and request.method.upper() not in {"GET", "HEAD", "OPTIONS"}:
            raise HTTPException(403, "admin_role_read_only")
        if request.method not in {"GET", "HEAD", "OPTIONS"}:
            origin = request.headers.get("origin")
            if not origin or urlsplit(origin).netloc != request.headers.get("host") or urlsplit(origin).scheme.lower() != request.url.scheme.lower():
                raise HTTPException(403, "same_origin_required")

    @r.get("/members")
    def members_list(request: Request, include_deleted: bool = False):
        require_admin(request)
        return {"members": members.list(include_deleted)}

    @r.post("/members")
    def member_create(request: Request, q: MemberCreateRequest):
        require_admin(request)
        try:
            return members.create("",q.name,q.nik,q.address,q.birth_place,q.birth_date,q.sex,q.rt,q.rw,q.village,q.district,q.city_regency,q.province,q.religion,q.marital_status,q.occupation,q.citizenship,q.phone,q.email,q.registration_date)
        except ValueError as e:
            raise HTTPException(409 if "already" in str(e) else 400,str(e))

    @r.get("/members/{member_id}")
    def member_get(request: Request, member_id):
        require_admin(request)
        result = members.get(member_id)
        if result is None:
            raise HTTPException(404,"member_not_found")
        return result

    @r.patch("/members/{member_id}")
    def member_update(request: Request, member_id,q: MemberUpdateRequest):
        require_admin(request)
        try:
            return members.update(member_id,q.name,q.nik,q.address,q.status,q.birth_place,q.birth_date,q.sex,q.rt,q.rw,q.village,q.district,q.city_regency,q.province,q.religion,q.marital_status,q.occupation,q.citizenship,q.phone,q.email,q.registration_date)
        except ValueError as e:
            code=str(e)
            raise HTTPException(409 if "already" in code else 400,code)

    @r.delete("/members/{member_id}")
    def member_delete(request: Request, member_id):
        require_admin(request)
        require_super_admin(request)
        try:
            return members.soft_delete(member_id)
        except ValueError as e:
            raise HTTPException(404,str(e))

    @r.post("/members/{member_id}/nfc-cards")
    def member_add_nfc(request: Request, member_id,q: NfcCardRequest):
        require_admin(request)
        require_super_admin(request)
        try:
            return members.add_card(member_id,q.card_uid,q.credential_id)
        except ValueError as e:
            code=str(e)
            raise HTTPException(409 if "already" in code else 400,code)

    @r.post("/members/{member_id}/nfc-cards/{card_id}/revoke")
    def member_revoke_nfc(request: Request, member_id,card_id):
        require_admin(request)
        require_super_admin(request)
        try:
            member = members.get(member_id)
            if member is None or not any(
                card["card_id"] == card_id for card in member["nfc_cards"]
            ):
                raise HTTPException(404,"nfc_card_not_found")
            return members.revoke_card(card_id)
        except ValueError as e:
            raise HTTPException(404,str(e))

    @r.get("/nfc/cards/{card_uid}")
    def nfc_card_resolve(request: Request, card_uid):
        require_admin(request)
        result = members.resolve_card(card_uid)
        if result is None:
            raise HTTPException(404,"nfc_card_not_found")
        return result

    @r.post("/members/{member_id}/pin")
    def set_member_pin(request: Request, member_id,q:PinRequest):
        require_admin(request)
        require_super_admin(request)
        if not q.operator_id.strip():
            raise HTTPException(400,"operator_id_required")
        if not q.identity_verified:
            raise HTTPException(400,"member_identity_verification_required")
        if len(q.reason.strip()) < 5:
            raise HTTPException(400,"reset_reason_required")
        try:
            result = identity.set_pin(member_id,q.pin,q.operator_id.strip())
            with db.connect() as c:
                c.execute("INSERT INTO audit_events(event_type,entity_type,entity_id,detail) VALUES(?,?,?,?)",
                          ("member_pin_reset","member",member_id,f"operator={q.operator_id.strip()};identity_verified=yes;reason={q.reason.strip()};result=success"))
                c.commit()
            return result
        except ValueError as e:
            raise HTTPException(404 if str(e)=="member_not_found" else 400,str(e))

    @r.post("/members/{member_id}/topup-corrections")
    def member_topup_correction(request: Request, member_id,q:MemberCorrectionRequest):
        require_admin(request)
        require_super_admin(request)
        if not q.operator_id.strip():
            raise HTTPException(400,"operator_id_required")
        try:
            return financial.correct_credit(member_id,q.original_transaction_id,q.corrected_amount,
                                            q.reason,q.idempotency_key,q.operator_id)
        except ValueError as e:
            code=str(e)
            status=404 if code=="original_topup_not_found_for_member" else 409 if code in {
                "original_transaction_already_corrected","idempotency_key_conflict",
                "insufficient_balance_for_correction","original_transaction_not_correctable"
            } else 400
            raise HTTPException(status,code)

    @r.get("/devices")
    def devices_list(request: Request, include_deleted: bool = False):
        require_admin(request)
        return {"devices": devices.list(include_deleted)}

    @r.get("/devices/{hardware_id}")
    def device_get(request: Request, hardware_id):
        require_admin(request)
        result = devices.get(hardware_id)
        if result is None:
            raise HTTPException(404,"device_not_found")
        return result

    @r.patch("/devices/{hardware_id}")
    def device_update(request: Request, hardware_id,q: DeviceHeartbeatRequest):
        require_admin(request)
        require_super_admin(request)
        try:
            return devices.update(hardware_id,q.device_type,q.status,q.display_name)
        except ValueError as e:
            raise HTTPException(400,str(e))

    @r.post("/devices/register")
    def device_register(q: DeviceRegisterRequest):
        """Bind physical MAC to the stable server-issued logical Device ID."""
        device_type=q.device_type.strip().lower()
        if device_type=="esp32-vending": device_type="esp32-s3-vending"
        device_id=q.device_id.strip() if q.device_id else ""
        hardware_id=q.hardware_id.strip().lower()
        mac_address=q.mac_address.strip().upper()
        device_key=q.device_key.strip()
        if device_type not in DeviceManagementService.ALLOWED_TYPES: raise HTTPException(400,"invalid_device_type")
        # hardware_id is the stable server-issued logical identity; it is
        # deliberately independent from the physical Wi-Fi MAC so hardware can
        # be replaced without changing the device's server identity.
        if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._:-]{2,127}",hardware_id):
            raise HTTPException(400,"invalid_hardware_id")
        if not re.fullmatch(r"(?:[0-9A-F]{2}:){5}[0-9A-F]{2}",mac_address):
            raise HTTPException(400,"invalid_mac_address")
        expected_hardware_id=("cashier_" if device_type=="esp32-cashier" else "vending_")+mac_address.replace(":","").lower()
        if hardware_id != expected_hardware_id:
            raise HTTPException(400,"hardware_id_mac_mismatch")
        if not device_key: raise HTTPException(400,"device_key_required")
        digest=hashlib.sha256(device_key.encode("utf-8")).hexdigest()
        with db.connect() as c:
            if device_id:
                if len(device_id)>128: raise HTTPException(400,"device_id_invalid")
                row=c.execute("""SELECT registry_id,hardware_id,device_type,mac_address,display_name,status,auth_key_hash
                                 FROM device_registry WHERE registry_id=?""",(device_id,)).fetchone()
            else:
                # A server-issued key uniquely identifies its registry row. Older
                # firmware can register without echoing a client-supplied logical ID.
                row=c.execute("""SELECT registry_id,hardware_id,device_type,mac_address,display_name,status,auth_key_hash
                                 FROM device_registry WHERE auth_key_hash=? AND deleted_at IS NULL""",(digest,)).fetchone()
                if row: device_id=row["registry_id"]
            if not row: raise HTTPException(403,"device_not_provisioned")
            if not row["auth_key_hash"] or not secrets.compare_digest(digest,row["auth_key_hash"]): raise HTTPException(403,"invalid_device_key")
            if row["status"]=="disabled": raise HTTPException(403,"device_disabled")
            # Registration must not silently override an administrator's maintenance
            # state. Only a newly provisioned device or an already-active device may
            # bind/refresh its physical MAC; maintenance devices require admin action.
            if row["status"] not in {"awaiting_device_registration","active"}:
                raise HTTPException(409,"device_not_available_for_registration")
            stored_type={"cashier":"esp32-cashier","vending":"esp32-s3-vending","esp32-vending":"esp32-s3-vending"}.get(row["device_type"],row["device_type"])
            if stored_type!=device_type: raise HTTPException(403,"device_type_mismatch")
            if row["mac_address"] and row["mac_address"]!=mac_address:
                raise HTTPException(409,"device_replacement_requires_admin_authorization")
            collision=c.execute("""SELECT registry_id FROM device_registry
                                   WHERE mac_address=? AND registry_id<>? AND status<>'disabled' AND deleted_at IS NULL""",
                                (mac_address,device_id)).fetchone()
            if collision: raise HTTPException(409,"device_mac_already_registered")
            previous_hardware_id=row["hardware_id"]
            if previous_hardware_id and previous_hardware_id!=hardware_id:
                # Upgrade legacy MAC-derived IDs to the actual physical MAC and preserve stable machine binding.
                c.execute("UPDATE vending_machines SET hardware_id=? WHERE hardware_id=?",(device_id,previous_hardware_id))
                c.execute("UPDATE cashier_deposits SET hardware_id=? WHERE hardware_id=?",(hardware_id,previous_hardware_id))
                c.execute("UPDATE payment_device_associations SET hardware_id=? WHERE hardware_id=?",(hardware_id,previous_hardware_id))
            c.execute("""UPDATE device_registry SET hardware_id=?,mac_address=?,device_type=?,status='active',
                         last_seen=CURRENT_TIMESTAMP,updated_at=CURRENT_TIMESTAMP WHERE registry_id=?""",
                      (hardware_id,mac_address,device_type,device_id))
            c.execute("INSERT INTO device_events(hardware_id,event_type,payload) VALUES(?,?,?)",
                      (device_id,"registration",q.model_dump_json(exclude={"device_key"})))
            c.commit()
        return {"registry_id":device_id,"device_id":device_id,"hardware_id":hardware_id,
                "mac_address":mac_address,"device_type":device_type,"status":"active","registered":True}

    @r.delete("/devices/{hardware_id}")
    def device_delete(request: Request, hardware_id):
        require_admin(request)
        require_super_admin(request)
        try:
            result=devices.soft_delete(hardware_id)
            with db.connect() as c:
                c.execute("INSERT INTO audit_events(event_type,entity_type,entity_id,detail) VALUES(?,?,?,?)",
                          ("device","access_revoked",result.get("registry_id") or hardware_id,"device_key_invalidated;status=disabled"))
                c.commit()
            return result
        except ValueError as e:
            raise HTTPException(404,str(e))

    @r.post("/devices/provision")
    def device_provision_auto(request: Request, q:DeviceProvisionRequest):
        require_admin(request)
        require_super_admin(request)
        location = q.location.strip()
        if not location or len(location) > 120:
            raise HTTPException(400, "device_location_required_max_120_chars")
        device_type = q.device_type.strip().lower()
        if device_type == "esp32-vending":
            device_type = "esp32-s3-vending"
        if device_type not in DeviceManagementService.ALLOWED_TYPES:
            raise HTTPException(400,"invalid_device_type")
        registry_id="pending-"+uuid4().hex
        # Physical hardware identity is unknown until the provisioned key first registers.
        # Keep it NULL rather than pretending a random server ID is a hardware MAC ID.
        hardware_id=None
        key=secrets.token_urlsafe(32)
        digest=hashlib.sha256(key.encode("utf-8")).hexdigest()
        with db.connect() as c:
            c.execute(
                """INSERT INTO device_registry
                   (registry_id,hardware_id,device_type,mac_address,display_name,status,last_seen,
                    auth_key_hash,auth_key_hint,created_at,updated_at)
                   VALUES(?,?,?,NULL,?,'awaiting_device_registration',NULL,?,?,CURRENT_TIMESTAMP,CURRENT_TIMESTAMP)""",
                (registry_id,hardware_id,device_type,location,digest,key[-6:]),
            )
            c.execute(
                "INSERT INTO audit_events(event_type,entity_type,entity_id,detail) VALUES(?,?,?,?)",
                ("device","provisioned",registry_id,f"type={device_type};location={location}"),
            )
            c.commit()
        return {"registry_id":registry_id,"hardware_id":hardware_id,"device_id":registry_id,
                "display_name":location,"location":location,"device_type":device_type,
                "device_key":key,"status":"awaiting_device_registration","key_shown_once":True}

    @r.post("/devices/{device_ref}/authorize-replacement")
    def device_authorize_replacement(request: Request, device_ref: str):
        """Authorize hardware replacement without changing the logical Device ID."""
        require_admin(request)
        require_super_admin(request)
        with db.connect() as c:
            row=c.execute("SELECT registry_id,hardware_id,device_type,status FROM device_registry WHERE (hardware_id=? OR registry_id=?) AND deleted_at IS NULL",(device_ref,device_ref)).fetchone()
            if not row: raise HTTPException(404,"device_not_found")
            if row["status"]=="disabled": raise HTTPException(409,"device_disabled")
            key=secrets.token_urlsafe(32);digest=hashlib.sha256(key.encode("utf-8")).hexdigest()
            c.execute("""UPDATE device_registry SET hardware_id=NULL,mac_address=NULL,auth_key_hash=?,auth_key_hint=?,
                         status='awaiting_device_registration',last_seen=NULL,updated_at=CURRENT_TIMESTAMP WHERE registry_id=?""",
                      (digest,key[-6:],row["registry_id"]))
            c.execute("INSERT INTO audit_events(event_type,entity_type,entity_id,detail) VALUES(?,?,?,?)",
                      ("device","hardware_replacement_authorized",row["registry_id"],"old_mac_unbound;old_key_revoked;new_key_shown_once=true"))
            c.commit()
        return {"registry_id":row["registry_id"],"device_id":row["registry_id"],"previous_hardware_id":row["hardware_id"],
                "device_type":row["device_type"],"device_key":key,"key_shown_once":True,"status":"awaiting_device_registration"}

    @r.post("/devices/{device_ref}/rotate-key")
    def device_rotate_key(request: Request, device_ref: str):
        require_admin(request)
        require_super_admin(request)
        with db.connect() as c:
            row=c.execute("SELECT registry_id,hardware_id,device_type,status FROM device_registry WHERE (hardware_id=? OR registry_id=?) AND deleted_at IS NULL",(device_ref,device_ref)).fetchone()
            if not row:
                raise HTTPException(404,"device_not_found")
            if row["status"]=="disabled":
                raise HTTPException(409,"device_disabled")
            key=secrets.token_urlsafe(32)
            digest=hashlib.sha256(key.encode("utf-8")).hexdigest()
            c.execute("UPDATE device_registry SET auth_key_hash=?,auth_key_hint=?,updated_at=CURRENT_TIMESTAMP WHERE registry_id=?",
                      (digest,key[-6:],row["registry_id"]))
            c.execute("INSERT INTO audit_events(event_type,entity_type,entity_id,detail) VALUES(?,?,?,?)",
                      ("device","key_rotated",row["registry_id"],"new_key_shown_once=true"))
            c.commit()
        return {"registry_id":row["registry_id"],"device_id":row["registry_id"],"hardware_id":row["hardware_id"],"device_type":row["device_type"],
                "device_key":key,"key_shown_once":True,"status":"rotated"}

    @r.post("/devices/{hardware_id}/provision")
    def device_provision_legacy(request: Request, hardware_id,q:DeviceProvisionRequest):
        """Deprecated compatibility endpoint; new firmware must use key-only provisioning."""
        require_admin(request)
        require_super_admin(request)
        legacy_id = hardware_id.strip()
        device_type = q.device_type.strip().lower()
        if device_type == "esp32-vending":
            device_type = "esp32-s3-vending"
        if not legacy_id:
            raise HTTPException(400, "hardware_id_required")
        if device_type not in DeviceManagementService.ALLOWED_TYPES:
            raise HTTPException(400, "invalid_device_type")
        key = secrets.token_urlsafe(32)
        digest = hashlib.sha256(key.encode("utf-8")).hexdigest()
        with db.connect() as c:
            existing = c.execute(
                "SELECT hardware_id FROM device_registry WHERE hardware_id=? OR hardware_id=?",
                (legacy_id, legacy_id),
            ).fetchone()
            if existing:
                raise HTTPException(409, "legacy_hardware_id_already_exists_use_key_rotation_workflow")
            c.execute(
                """INSERT INTO device_registry
                   (registry_id,hardware_id,device_type,status,last_seen,auth_key_hash,auth_key_hint,created_at,updated_at)
                   VALUES(?,?,?,'active',NULL,?,?,CURRENT_TIMESTAMP,CURRENT_TIMESTAMP)""",
                (uuid4().hex, legacy_id, device_type, digest, key[-6:]),
            )
            c.execute(
                "INSERT INTO audit_events(event_type,entity_type,entity_id,detail) VALUES(?,?,?,?)",
                ("device", "legacy_provisioned", legacy_id, f"type={device_type};deprecated=true"),
            )
            c.commit()
        return {"hardware_id": legacy_id, "device_type": device_type, "device_key": key,
                "deprecated": True, "use_endpoint": "/api/v1/devices/provision"}

    @r.post("/devices/heartbeat")
    def device_heartbeat_by_key(q:DeviceHeartbeatRequest,x_m_group_device_key: str | None = Header(default=None)):
        """Key-only heartbeat; the public API does not require a device ID."""
        identity=require_device_by_key(x_m_group_device_key)
        if not q.device_type.strip():
            raise HTTPException(400,"device_type_required")
        device_type=q.device_type.strip().lower()
        if device_type=="esp32-vending":
            device_type="esp32-s3-vending"
        if device_type not in DeviceManagementService.ALLOWED_TYPES:
            raise HTTPException(400,"invalid_device_type")
        if q.status!="active":
            raise HTTPException(400,"invalid_heartbeat_status")
        location=(q.display_name or "").strip()
        if len(location)>120 or any(ord(ch)<32 for ch in location):
            raise HTTPException(400,"invalid_device_location")
        with db.connect() as c:
            row=c.execute("SELECT registry_id,hardware_id,device_type,display_name FROM device_registry WHERE registry_id=?",(identity["registry_id"],)).fetchone()
            stored_type={"cashier":"esp32-cashier","vending":"esp32-s3-vending","esp32-vending":"esp32-s3-vending"}.get(row["device_type"],row["device_type"]) if row else None
            if not row or stored_type!=device_type:
                raise HTTPException(409,"device_type_mismatch")
            c.execute("UPDATE device_registry SET last_seen=CURRENT_TIMESTAMP WHERE registry_id=?",(row["registry_id"],))
            if location and location != row["display_name"]:
                c.execute("UPDATE device_registry SET display_name=?,updated_at=CURRENT_TIMESTAMP WHERE registry_id=?",
                          (location,row["registry_id"]))
                c.execute(
                    "INSERT INTO admin_security_events(actor_username,event_type,target_username,detail,created_at) VALUES(?,?,?,?,?)",
                    ("device:"+identity["registry_id"],"device_location_updated",identity["registry_id"],"installation_location_updated",int(time.time())),
                )
            c.execute("INSERT INTO device_events(hardware_id,event_type,payload) VALUES(?,?,?)",
                      (identity["registry_id"],"heartbeat",q.model_copy(update={"device_type":device_type}).model_dump_json()))
            c.commit()
        return {"registry_id":identity["registry_id"],"device_id":identity["registry_id"],"hardware_id":identity["hardware_id"],"device_type":device_type,"status":"active"}

    @r.post("/devices/{hardware_id}/heartbeat")
    def device_heartbeat(hardware_id,q:DeviceHeartbeatRequest,x_m_group_device_key: str | None = Header(default=None)):
        if not hardware_id.strip(): raise HTTPException(400,"hardware_id_required")
        if not q.device_type.strip(): raise HTTPException(400,"device_type_required")
        # Heartbeat is telemetry, not an administrative status mutation. Only an
        # admin may disable/maintain a device; accepting status from firmware lets
        # a device accidentally lock itself out or write arbitrary registry states.
        if q.status != "active":
            raise HTTPException(400,"invalid_heartbeat_status")
        device_type = q.device_type.strip().lower()
        if device_type == "esp32-vending":
            device_type = "esp32-s3-vending"
        if device_type not in DeviceManagementService.ALLOWED_TYPES:
            raise HTTPException(400,"invalid_device_type")
        require_device(hardware_id,x_m_group_device_key)
        with db.connect() as c:
            row = c.execute(
                "SELECT device_type,display_name FROM device_registry WHERE hardware_id=?", (hardware_id,)
            ).fetchone()
            stored_type = {"cashier":"esp32-cashier","vending":"esp32-s3-vending","esp32-vending":"esp32-s3-vending"}.get(row["device_type"], row["device_type"]) if row else None
            if not row or stored_type != device_type:
                raise HTTPException(409,"device_type_mismatch")
            location=(q.display_name or "").strip()
            if len(location)>120 or any(ord(ch)<32 for ch in location):
                raise HTTPException(400,"invalid_device_location")
            if location and row["display_name"] != location:
                c.execute("UPDATE device_registry SET last_seen=CURRENT_TIMESTAMP,display_name=?,updated_at=CURRENT_TIMESTAMP WHERE hardware_id=?",
                          (location,hardware_id))
                c.execute(
                    "INSERT INTO admin_security_events(actor_username,event_type,target_username,detail,created_at) VALUES(?,?,?,?,?)",
                    ("device:"+hardware_id,"device_location_updated",hardware_id,"installation_location_updated",int(time.time())),
                )
            else:
                c.execute("UPDATE device_registry SET last_seen=CURRENT_TIMESTAMP WHERE registry_id=?",
                          (hardware_id,))
            c.execute("INSERT INTO device_events(hardware_id,event_type,payload) VALUES(?,?,?)",
                      (hardware_id,"heartbeat",q.model_copy(update={"device_type": device_type,"display_name":location or q.display_name}).model_dump_json()))
            c.commit()
        return {"hardware_id":hardware_id,"device_type":device_type,"status":"active"}

    @r.post("/access/{credential_id}")
    def access(request: Request, credential_id):
        require_admin(request)
        result=identity.authorize_credential(credential_id)
        with db.connect() as c:
            c.execute("INSERT INTO identity_access_events(credential_id,member_id,result,reason) VALUES(?,?,?,?)",
                      (credential_id,result.get("member_id"),"allowed" if result["authorized"] else "denied",result["reason"]))
            c.commit()
        return result

    @r.get("/credentials/{credential_id}/account")
    def credential_account(request: Request, credential_id):
        require_admin(request)
        result=identity.account_for_credential(credential_id)
        if not result["authorized"]: raise HTTPException(404,result["reason"])
        return result

    @r.get("/accounts/{account_id}/balance")
    def account_balance(request: Request, account_id):
        require_admin(request)
        try:return {"account_id":account_id,"balance":financial.balance(account_id)}
        except ValueError as e:raise HTTPException(404,str(e))

    @r.post("/devices/member-balance")
    def device_member_balance(q: MemberBalanceLookupRequest,
                              x_m_group_device_key: str | None = Header(default=None)):
        """Read-only balance lookup authenticated by device key, without a device ID."""
        identity=require_device_by_key(x_m_group_device_key, {"esp32-cashier","esp32-vending","esp32-s3-vending","cashier","vending"})
        device_fingerprint=identity["fingerprint"]
        card_uid = q.card_uid.strip()
        if not card_uid:
            raise HTTPException(400, "card_uid_required")
        # Suppress duplicate NFC reads per key/card pair; public IDs are irrelevant.
        uid_hash = hashlib.sha256(card_uid.casefold().encode("utf-8")).hexdigest()
        now = time.time()
        with db.connect() as c:
            prior = c.execute(
                "SELECT last_lookup_at FROM device_balance_lookup_limits WHERE hardware_id=? AND card_uid_hash=?",
                (device_fingerprint, uid_hash),
            ).fetchone()
            if prior and now - float(prior["last_lookup_at"]) < 2.0:
                raise HTTPException(429, "balance_lookup_rate_limited", headers={"Retry-After": "2"})
            c.execute(
                """INSERT INTO device_balance_lookup_limits(hardware_id,card_uid_hash,last_lookup_at)
                   VALUES(?,?,?) ON CONFLICT(hardware_id,card_uid_hash)
                   DO UPDATE SET last_lookup_at=excluded.last_lookup_at""",
                (device_fingerprint, uid_hash, now),
            )
            c.commit()
        member = members.resolve_card(card_uid)
        if member is None:
            raise HTTPException(404, "nfc_card_not_found_or_inactive")
        with db.connect() as c:
            account = c.execute(
                """SELECT account_id FROM financial_accounts
                   WHERE member_id=? AND status='active'
                   ORDER BY CASE WHEN account_type='savings' THEN 0 ELSE 1 END, created_at
                   LIMIT 1""",
                (member["member_id"],),
            ).fetchone()
        if account is None:
            raise HTTPException(404, "member_account_not_found")
        try:
            balance = financial.balance(account["account_id"])
        except ValueError as e:
            raise HTTPException(404, str(e))
        return {
            "member_id": member["member_id"],
            "member_name": member["name"],
            "balance": balance,
            "currency": "IDR",
        }

    @r.get("/accounts/{account_id}/ledger")
    def account_ledger(request: Request, account_id,limit:int=100):
        require_admin(request)
        try:return {"account_id":account_id,"entries":financial.ledger(account_id,limit)}
        except ValueError as e:raise HTTPException(404,str(e))

    @r.post("/accounts/{account_id}/credit")
    def account_credit(request: Request, account_id,q:FinancialRequest):
        require_admin(request)
        require_super_admin(request)
        if not q.idempotency_key:
            raise HTTPException(400,"idempotency_key_required")
        try:return financial.credit(account_id,q.amount,q.reference,q.idempotency_key)
        except ValueError as e:
            code=str(e); raise HTTPException(409 if code=="insufficient_balance" else 400,code)

    @r.post("/accounts/{account_id}/debit")
    def account_debit(request: Request, account_id,q:FinancialRequest):
        require_admin(request)
        require_super_admin(request)
        if not q.idempotency_key:
            raise HTTPException(400,"idempotency_key_required")
        try:return financial.debit(account_id,q.amount,q.reference,q.idempotency_key)
        except ValueError as e:
            code=str(e); raise HTTPException(409 if code=="insufficient_balance" else 400,code)

    @r.get("/promotions")
    def promotions_list(request: Request, machine_id: str | None = None, payment_method: str | None = None,
                         include_disabled: bool = True):
        require_admin(request)
        try:
            return {"promotions": promos.list(machine_id,payment_method,include_disabled)}
        except ValueError as e:
            raise HTTPException(400,str(e))

    @r.post("/promotions")
    def promotion_create(request: Request, q: PromoRequest):
        require_admin(request)
        require_super_admin(request)
        try:
            return promos.create(q.scope,q.machine_id,q.product_id,q.payment_method,
                                 q.payment_provider,q.discount_percent,q.starts_at,q.ends_at,
                                 q.priority,q.enabled)
        except ValueError as e:
            raise HTTPException(400,str(e))

    @r.get("/promotions/resolve")
    def promotion_resolve(request: Request, machine_id: str,product_id: str,payment_method: str,
                           payment_provider: str | None = None):
        require_admin(request)
        try:
            result = promos.resolve(machine_id,product_id,payment_method,payment_provider)
            return {"promotion":result}
        except ValueError as e:
            raise HTTPException(400,str(e))

    @r.get("/promotions/{promo_id}")
    def promotion_get(request: Request, promo_id):
        require_admin(request)
        result = promos.get(promo_id)
        if result is None:
            raise HTTPException(404,"promo_not_found")
        return result

    @r.patch("/promotions/{promo_id}")
    def promotion_update(request: Request, promo_id,q: PromoUpdateRequest):
        require_admin(request)
        require_super_admin(request)
        try:
            return promos.update(promo_id,**q.model_dump(exclude_none=True))
        except ValueError as e:
            raise HTTPException(400,str(e))

    @r.get("/vending")
    def vending_list(request: Request):
        require_admin(request)
        return {"machines": vending.machines()}

    @r.post("/vending")
    def vending_register(request: Request, q:VendingRegisterRequest):
        require_admin(request)
        require_super_admin(request)
        try:return vending.register(q.machine_id,q.name,q.location,q.hardware_id,q.status)
        except ValueError as e: raise HTTPException(409 if "already" in str(e) else 400,str(e))

    @r.get("/vending/{machine_id}")
    def vending_detail(request: Request, machine_id):
        require_admin(request)
        try:return {"machine":vending.machine(machine_id),"slots":vending.slots(machine_id)}
        except ValueError as e:raise HTTPException(404,str(e))

    @r.patch("/vending/{machine_id}")
    def vending_update(request: Request, machine_id,q:VendingUpdateRequest):
        require_admin(request)
        require_super_admin(request)
        try:return vending.update_machine(machine_id,q.name,q.location,q.hardware_id,q.status)
        except ValueError as e:raise HTTPException(409 if "already" in str(e) else 400,str(e))

    @r.post("/vending/{machine_id}/enable")
    def vending_enable(request: Request, machine_id):
        require_admin(request)
        require_super_admin(request)
        try:return vending.set_status(machine_id,"active")
        except ValueError as e:raise HTTPException(404 if str(e)=="machine_not_found" else 400,str(e))

    @r.post("/vending/{machine_id}/disable")
    def vending_disable(request: Request, machine_id):
        require_admin(request)
        require_super_admin(request)
        try:return vending.set_status(machine_id,"disabled")
        except ValueError as e:raise HTTPException(404 if str(e)=="machine_not_found" else 400,str(e))

    @r.get("/vending/{machine_id}/products")
    def vending_products(request: Request, machine_id, x_m_group_device_key: str | None = Header(default=None)):
        machine = resolve_vending_machine(machine_id)
        if x_m_group_device_key:
            identity=require_device_by_key(x_m_group_device_key, {"esp32-vending","esp32-s3-vending","vending"})
            if not machine.get("hardware_id") or machine["hardware_id"] not in {identity["registry_id"], identity.get("hardware_id")}:
                raise HTTPException(403,"machine_device_identity_mismatch")
        else:
            require_admin(request)
        catalog = vending.products(machine["machine_id"])
        # Preserve base price while exposing the exact NFC/local amount shown
        # by the current firmware. QRIS remains a separately configured,
        # inactive payment path.
        for item in catalog:
            item["base_price"] = item["price"]
            item["effective_price"] = item["price"]
            item["discount_amount"] = 0
            item["promo_id"] = None
            promo = promos.resolve(machine["machine_id"], item["product_id"], "NFC", "local")
            if not promo:
                with db.connect() as c:
                    legacy = c.execute(
                        "SELECT product_id FROM vending_products WHERE machine_id=? AND slot=?",
                        (machine["machine_id"], int(item["product_id"])),
                    ).fetchone()
                if legacy:
                    promo = promos.resolve(machine["machine_id"], legacy["product_id"], "NFC", "local")
            if promo:
                discount, _ = promos.calculate(item["price"], promo["discount_percent"])
                item["discount_amount"] = discount
                item["effective_price"] = item["price"] - discount
                item["promo_id"] = promo["promo_id"]
        with db.connect() as c:
            image_rows=c.execute("SELECT product_id,sha256,byte_size,content_type FROM vending_product_images WHERE machine_id=?",(machine["machine_id"],)).fetchall()
        images={str(x["product_id"]):dict(x) for x in image_rows}
        for item in catalog:
            image=images.get(str(item["product_id"]))
            item["image_url"]=("/api/v1/vending/"+machine["machine_id"]+"/products/"+str(item["product_id"])+"/image?v="+image["sha256"] if image else None)
            item["image_sha256"]=image["sha256"] if image else None
            item["image_size"]=image["byte_size"] if image else 0
        return {"machine": machine, "products": catalog}

    @r.get("/vending/{machine_id}/products/{product_id}/image")
    def vending_product_image(machine_id: str, product_id: str, request: Request, v: str | None = None):
        machine=resolve_vending_machine(machine_id)
        if request.headers.get("x-m-group-device-key"):
            identity=require_device_by_key(request.headers.get("x-m-group-device-key"), {"esp32-vending","esp32-s3-vending","vending"})
            if not machine.get("hardware_id") or machine["hardware_id"] not in {identity["registry_id"], identity.get("hardware_id")}:
                raise HTTPException(403,"machine_device_identity_mismatch")
        else:
            require_admin(request)
        with db.connect() as c:
            row=c.execute("SELECT content_type,image_data,sha256 FROM vending_product_images WHERE machine_id=? AND product_id=?",(machine["machine_id"],str(product_id))).fetchone()
        if not row: raise HTTPException(404,"product_image_not_found")
        etag='"'+row["sha256"]+'"'
        if request.headers.get("if-none-match")==etag:
            return Response(status_code=304,headers={"ETag":etag,"Cache-Control":"public, max-age=31536000, immutable"})
        if v and v != row["sha256"]: raise HTTPException(409,"product_image_version_changed")
        return Response(content=bytes(row["image_data"]),media_type=row["content_type"],headers={"ETag":etag,"Cache-Control":"public, max-age=31536000, immutable"})

    @r.post("/vending/{machine_id}/products/{product_id}/image")
    async def vending_product_image_upload(request: Request, machine_id: str, product_id: str, file: UploadFile = File(...)):
        require_admin(request)
        require_super_admin(request)
        machine=resolve_vending_machine(machine_id)
        if str(product_id) not in VendingService.PRODUCT_IDS: raise HTTPException(400,"product_id_must_be_1_to_5")
        raw=await file.read(MAX_PRODUCT_IMAGE_BYTES+1)
        if not raw or len(raw)>MAX_PRODUCT_IMAGE_BYTES: raise HTTPException(413,"product_image_must_be_under_2mb")
        try:
            source=Image.open(io.BytesIO(raw))
            if source.format not in {"PNG","JPEG","WEBP"}: raise HTTPException(415,"unsupported_product_image_format")
            if source.width<1 or source.height<1 or source.width*source.height>20_000_000:
                raise HTTPException(413,"product_image_dimensions_too_large")
            source.verify()
            decoded=Image.open(io.BytesIO(raw))
            if "A" in decoded.getbands():
                rgba=decoded.convert("RGBA")
                source=Image.new("RGB",rgba.size,(255,255,255))
                source.paste(rgba,mask=rgba.getchannel("A"))
            else:
                source=decoded.convert("RGB")
            source.thumbnail((480,480))
            out=io.BytesIO()
            try:
                media_type="image/webp"
                for quality in (72,64,56,48,40):
                    out=io.BytesIO()
                    source.save(out,format="WEBP",quality=quality,method=6)
                    if out.tell()<=MAX_OPTIMIZED_PRODUCT_IMAGE_BYTES:
                        break
            except Exception:
                out=io.BytesIO()
                source.save(out,format="JPEG",quality=55,optimize=True)
                media_type="image/jpeg"
            optimized=out.getvalue()
            if len(optimized)>MAX_OPTIMIZED_PRODUCT_IMAGE_BYTES:
                out=io.BytesIO()
                source.save(out,format="JPEG",quality=40,optimize=True)
                optimized=out.getvalue()
                media_type="image/jpeg"
        except HTTPException:
            raise
        except (UnidentifiedImageError, OSError, ValueError, Image.DecompressionBombError):
            raise HTTPException(415,"invalid_or_corrupt_product_image")
        if len(optimized)>MAX_OPTIMIZED_PRODUCT_IMAGE_BYTES: raise HTTPException(413,"optimized_product_image_must_be_under_64kb")
        digest=hashlib.sha256(optimized).hexdigest()
        with db.connect() as c:
            exists=c.execute("SELECT 1 FROM vending_products WHERE machine_id=? AND (CAST(product_id AS TEXT)=? OR CAST(slot AS TEXT)=?)",(machine["machine_id"],str(product_id),str(product_id))).fetchone()
            if not exists: raise HTTPException(404,"product_not_found")
            c.execute("""INSERT INTO vending_product_images(machine_id,product_id,content_type,image_data,sha256,byte_size,updated_at)
                         VALUES(?,?,?,?,?,?,CURRENT_TIMESTAMP)
                         ON CONFLICT(machine_id,product_id) DO UPDATE SET content_type=excluded.content_type,image_data=excluded.image_data,
                         sha256=excluded.sha256,byte_size=excluded.byte_size,updated_at=CURRENT_TIMESTAMP""",
                      (machine["machine_id"],str(product_id),media_type,optimized,digest,len(optimized)))
            c.execute("INSERT INTO audit_events(event_type,entity_type,entity_id,detail) VALUES(?,?,?,?)",
                      ("inventory","product_image_updated",machine["machine_id"]+":"+str(product_id),"sha256="+digest+";bytes="+str(len(optimized))))
            c.commit()
        return {"machine_id":machine["machine_id"],"product_id":str(product_id),"image_url":"/api/v1/vending/"+machine["machine_id"]+"/products/"+str(product_id)+"/image?v="+digest,"sha256":digest,"byte_size":len(optimized),"content_type":media_type}

    @r.put("/vending/{machine_id}/products/{product_id}")
    def vending_product(request: Request, machine_id,product_id,q:VendingProductRequest):
        require_admin(request)
        require_super_admin(request)
        if product_id not in VendingService.PRODUCT_IDS:
            raise HTTPException(400,"product_id_must_be_1_to_5")
        if q.product_id!=product_id:raise HTTPException(400,"product_id_mismatch")
        slot = int(product_id)
        if q.slot is not None and q.slot != slot:
            raise HTTPException(400,"product_slot_mismatch")
        if q.servo_channel is not None and q.servo_channel != slot:
            raise HTTPException(400,"servo_must_match_slot")
        try:
            result = vending.upsert_product(machine_id,product_id,q.name,q.price,q.stock,q.enabled,slot,q.capacity,slot)
            result["product_id"] = str(result["slot"])
            return result
        except ValueError as e:raise HTTPException(409 if "slot" in str(e) or str(e)=="no_free_slot" else 400,str(e))

    @r.get("/vending/{machine_id}/transactions")
    def vending_machine_transactions(request: Request, machine_id: str, limit: int = 100):
        require_admin(request)
        if limit < 1 or limit > 500:
            raise HTTPException(400, "limit_must_be_1_to_500")
        machine = resolve_vending_machine(machine_id)
        with db.connect() as c:
            rows = c.execute(
                """SELECT transaction_id,machine_id,product_id,credential_id,account_id,amount,
                          status,dispense_status,created_at,completed_at
                   FROM vending_transactions WHERE machine_id=?
                   ORDER BY created_at DESC LIMIT ?""",
                (machine["machine_id"], limit),
            ).fetchall()
        return {
            "machine_id": machine["machine_id"],
            "transactions": [public_vending_transaction(dict(row)) for row in rows],
        }

    @r.post("/vending/{machine_id}/transactions")
    def vending_begin(machine_id,q:VendingBeginRequest,x_m_group_device_key: str | None = Header(default=None)):
        try:
            identity=require_device_by_key(x_m_group_device_key, {"esp32-vending","esp32-s3-vending","vending"})
            machine = resolve_vending_machine(machine_id)
            if not machine.get("hardware_id") or machine["hardware_id"] not in {identity["registry_id"], identity.get("hardware_id")}:
                raise HTTPException(403,"machine_device_identity_mismatch")
            if str(q.product_id) not in VendingService.PRODUCT_IDS:
                raise HTTPException(400,"product_id_must_be_1_to_5")
            return public_vending_transaction(vending.begin(machine["machine_id"],q.product_id,q.credential_id,q.account_id,q.idempotency_key,q.payment_method,q.payment_provider))
        except ValueError as e:raise HTTPException(409 if str(e) in {"out_of_stock","machine_not_active","qris_payment_provider_not_activated"} else 400,str(e))

    @r.get("/vending/transactions/{transaction_id}")
    def vending_transaction_status(transaction_id, x_m_group_device_key: str | None = Header(default=None)):
        """Authenticated reconciliation endpoint for ambiguous device requests."""
        try:
            tx = vending.get(transaction_id)
            machine = vending.machine(tx["machine_id"])
            identity=require_device_by_key(x_m_group_device_key, {"esp32-vending","esp32-s3-vending","vending"})
            if not machine.get("hardware_id") or machine["hardware_id"] not in {identity["registry_id"], identity.get("hardware_id")}:
                raise HTTPException(403,"machine_device_identity_mismatch")
            return public_vending_transaction(tx)
        except HTTPException:
            raise
        except ValueError as e:
            raise HTTPException(404 if str(e) == "transaction_not_found" else 400, str(e))

    @r.post("/vending/transactions/{transaction_id}/authorize")
    def vending_authorize(transaction_id,x_m_group_device_key: str | None = Header(default=None)):
        try:
            tx=vending.get(transaction_id)
            machine=vending.machine(tx["machine_id"])
            identity=require_device_by_key(x_m_group_device_key, {"esp32-vending","esp32-s3-vending","vending"})
            if not machine.get("hardware_id") or machine["hardware_id"] not in {identity["registry_id"], identity.get("hardware_id")}:
                raise HTTPException(403,"machine_device_identity_mismatch")
            return public_vending_transaction(vending.authorize(transaction_id))
        except PermissionError as e:raise HTTPException(403,str(e))
        except ValueError as e:raise HTTPException(400,str(e))

    @r.post("/vending/transactions/{transaction_id}/dispense")
    def vending_dispense(transaction_id,q:VendingDispenseRequest,x_m_group_device_key: str | None = Header(default=None)):
        try:
            tx=vending.get(transaction_id)
            machine=vending.machine(tx["machine_id"])
            identity=require_device_by_key(x_m_group_device_key, {"esp32-vending","esp32-s3-vending","vending"})
            if not machine.get("hardware_id") or machine["hardware_id"] not in {identity["registry_id"], identity.get("hardware_id")}:
                raise HTTPException(403,"machine_device_identity_mismatch")
            return public_vending_transaction(vending.dispense(transaction_id,q.success))
        except ValueError as e:raise HTTPException(409,str(e))

    @r.post("/payments")
    def payment(request: Request, q:PaymentRequest):
        require_admin(request)
        require_super_admin(request)
        # PaymentService owns the single authoritative credential/PIN check.
        # Avoid double verification, duplicate audit events, and race-to-block behavior.
        try:return payments.pay(**q.model_dump())
        except PermissionError as e:raise HTTPException(403,str(e))
        except ValueError as e:
            code=str(e)
            raise HTTPException(409 if code in {"insufficient_balance", "idempotency_key_conflict"} else 400,code)

    @r.post("/members/{member_id}/nfc-registration/start")
    def nfc_registration_start(request: Request, member_id,q:NfcRegistrationStartRequest):
        require_admin(request)
        cashier_hardware_id=(q.cashier_hardware_id or "").strip()
        if not cashier_hardware_id:
            raise HTTPException(400,"cashier_selection_required")
        with db.connect() as c:
            cashier=c.execute("""SELECT registry_id,hardware_id,auth_key_hash FROM device_registry
                WHERE (registry_id=? OR lower(hardware_id)=lower(?))
                  AND device_type IN ('esp32-cashier','cashier')
                  AND status='active' AND deleted_at IS NULL AND auth_key_hash IS NOT NULL
                ORDER BY CASE WHEN registry_id=? THEN 0 ELSE 1 END LIMIT 1""",
                (cashier_hardware_id,cashier_hardware_id,cashier_hardware_id)).fetchone()
        if not cashier:
            raise HTTPException(409,"cashier_not_available")
        cashier_fingerprint=cashier["auth_key_hash"]
        member=members.get(member_id)
        if not member or member.get("status")!="active":
            raise HTTPException(404,"member_not_found")
        actor=getattr(request.state,"admin_username","")
        with db.connect() as c:
            c.execute("BEGIN IMMEDIATE")
            pending=c.execute(
                "SELECT session_id FROM nfc_registration_sessions WHERE hardware_id IN ('*',?) "
                "AND status IN ('scan_pending','waiting_nfc','pin_pending','processing') "
                "AND expires_at>CURRENT_TIMESTAMP",(cashier_fingerprint,)
            ).fetchone()
            if pending:
                raise HTTPException(409,"cashier_registration_busy")
            session_id="nfc-reg-"+uuid4().hex
            c.execute(
                """INSERT INTO nfc_registration_sessions
                   (session_id,member_id,hardware_id,status,expires_at)
                   VALUES(?,?,?,'scan_pending',datetime('now','+5 minutes'))""",
                (session_id,member_id,cashier_fingerprint)
            )
            c.execute(
                "INSERT INTO audit_events(event_type,entity_type,entity_id,detail) VALUES(?,?,?,?)",
                ("identity","nfc_registration",session_id,f"started:member={member_id}:cashier={cashier_hardware_id}:actor={actor}")
            )
            c.commit()
        return {"session_id":session_id,"member_id":member_id,"status":"scan_pending"}

    @r.post("/members/{member_id}/nfc-replacement/start")
    def nfc_replacement_start(request: Request, member_id,q:NfcRegistrationStartRequest):
        require_admin(request)
        operator_id=getattr(request.state,"admin_username","")
        if not operator_id:
            raise HTTPException(401,"admin_session_required")
        cashier_hardware_id=(q.cashier_hardware_id or "").strip()
        if not cashier_hardware_id:
            raise HTTPException(400,"cashier_selection_required")
        with db.connect() as c:
            cashier=c.execute("""SELECT hardware_id,auth_key_hash FROM device_registry
                WHERE lower(hardware_id)=lower(?) AND device_type IN ('esp32-cashier','cashier')
                  AND status='active' AND deleted_at IS NULL AND auth_key_hash IS NOT NULL""",(cashier_hardware_id,)).fetchone()
        if not cashier:
            raise HTTPException(409,"cashier_not_available")
        cashier_fingerprint=cashier["auth_key_hash"]
        member=members.get(member_id)
        if not member or member.get("status")!="active":
            raise HTTPException(404,"member_not_found")
        with db.connect() as c:
            c.execute("BEGIN IMMEDIATE")
            pending=c.execute("SELECT session_id FROM nfc_registration_sessions WHERE hardware_id IN ('*',?) AND status IN ('scan_pending','waiting_nfc','pin_pending','processing') AND expires_at>CURRENT_TIMESTAMP",(cashier_fingerprint,)).fetchone()
            if pending:
                raise HTTPException(409,"cashier_registration_busy")
            session_id="nfc-replace-"+uuid4().hex
            c.execute("INSERT INTO nfc_registration_sessions(session_id,member_id,hardware_id,status,expires_at) VALUES(?,?,?,'scan_pending',datetime('now','+5 minutes'))",(session_id,member_id,cashier_fingerprint))
            c.execute("INSERT INTO nfc_replacement_intents(session_id,member_id,operator_id) VALUES(?,?,?)",(session_id,member_id,operator_id))
            c.execute("INSERT INTO audit_events(event_type,entity_type,entity_id,detail) VALUES(?,?,?,?)",("nfc_replacement","member",member_id,f"started:session={session_id}:cashier={cashier_hardware_id}:operator={operator_id}"))
            c.commit()
        return {"session_id":session_id,"member_id":member_id,"status":"scan_pending","operation":"replacement"}

    @r.get("/members/{member_id}/nfc-registration/{session_id}")
    def nfc_registration_status(request: Request, member_id,session_id):
        require_admin(request)
        with db.connect() as c:
            row=c.execute(
                "SELECT session_id,member_id,status,card_uid,credential_id,created_at,completed_at,expires_at "
                "FROM nfc_registration_sessions WHERE session_id=? AND member_id=?",
                (session_id,member_id)
            ).fetchone()
            if row and row["status"] in {"scan_pending","waiting_nfc","pin_pending","processing"}:
                now_utc=__import__("datetime").datetime.now(__import__("datetime").timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
                if row["expires_at"]<=now_utc:
                    c.execute("UPDATE nfc_registration_sessions SET status='expired' WHERE session_id=?",(session_id,))
                    c.commit()
                    row=c.execute(
                        "SELECT session_id,member_id,status,card_uid,credential_id,created_at,completed_at,expires_at "
                        "FROM nfc_registration_sessions WHERE session_id=? AND member_id=?",
                        (session_id,member_id)
                    ).fetchone()
        if not row: raise HTTPException(404,"registration_session_not_found")
        result=dict(row);result.pop("expires_at",None)
        return result

    @r.get("/cashier/nfc-registration")
    def cashier_nfc_registration(x_m_group_device_key: str | None = Header(default=None)):
        device_identity=require_device_by_key(x_m_group_device_key, {"esp32-cashier","cashier"})
        fingerprint=device_identity["fingerprint"]
        with db.connect() as c:
            c.execute("BEGIN IMMEDIATE")
            row=c.execute(
                """SELECT session_id,member_id,status,hardware_id FROM nfc_registration_sessions
                   WHERE hardware_id IN ('*',?) AND status IN ('scan_pending','waiting_nfc','pin_pending','processing')
                     AND expires_at>CURRENT_TIMESTAMP ORDER BY created_at LIMIT 1""",(fingerprint,)
            ).fetchone()
            if row and row["hardware_id"]=="*":
                claimed=c.execute("UPDATE nfc_registration_sessions SET hardware_id=? WHERE session_id=? AND hardware_id='*'",
                                  (fingerprint,row["session_id"]))
                if claimed.rowcount!=1:
                    c.rollback()
                    return {"status":"idle"}
            c.commit()
        if not row:
            return {"status":"idle"}
        return {"status":row["status"],"session_id":row["session_id"],"member_id":row["member_id"]}

    @r.post("/cashier/nfc-registration/progress")
    def cashier_nfc_registration_progress(q:NfcRegistrationProgressRequest,
                                          x_m_group_device_key: str | None = Header(default=None)):
        identity_row=require_device_by_key(x_m_group_device_key, {"esp32-cashier","cashier"})
        allowed={"waiting_nfc","pin_pending","processing","failed"}
        if q.status not in allowed:
            raise HTTPException(400,"invalid_registration_progress")
        with db.connect() as c:
            session=c.execute("SELECT session_id,status,expires_at FROM nfc_registration_sessions WHERE session_id=? AND hardware_id=?",
                              (q.session_id,identity_row["fingerprint"])).fetchone()
            if not session:
                raise HTTPException(404,"registration_session_not_found")
            if session["status"] not in {"scan_pending","waiting_nfc","pin_pending","processing"}:
                raise HTTPException(409,"registration_session_not_active")
            allowed_transitions={
                "scan_pending":{"waiting_nfc","failed"},
                "waiting_nfc":{"waiting_nfc","pin_pending","failed"},
                "pin_pending":{"pin_pending","processing","failed"},
                "processing":{"processing","failed"},
            }
            if q.status not in allowed_transitions.get(session["status"],set()):
                raise HTTPException(409,"invalid_registration_status_transition")
            if session["expires_at"]<=__import__("datetime").datetime.now(__import__("datetime").timezone.utc).strftime("%Y-%m-%d %H:%M:%S"):
                c.execute("UPDATE nfc_registration_sessions SET status='expired' WHERE session_id=?",(q.session_id,))
                c.commit()
                raise HTTPException(409,"registration_session_expired")
            c.execute("UPDATE nfc_registration_sessions SET status=? WHERE session_id=?",(q.status,q.session_id))
            c.commit()
        return {"session_id":q.session_id,"status":q.status}

    @r.post("/cashier/nfc-registration/complete")
    def cashier_nfc_registration_complete(q:NfcRegistrationCompleteRequest,
                                           x_m_group_device_key: str | None = Header(default=None)):
        device_identity=require_device_by_key(x_m_group_device_key, {"esp32-cashier","cashier"})
        cashier_fingerprint=device_identity["fingerprint"]
        if not q.pin.isdigit() or len(q.pin)!=4:
            raise HTTPException(400,"registration_pin_must_be_4_digits")
        card_uid=(q.card_uid or "").strip().upper()
        if not card_uid: raise HTTPException(400,"card_uid_required")
        with db.connect() as c:
            session=c.execute(
                "SELECT * FROM nfc_registration_sessions WHERE session_id=? AND hardware_id=?",
                (q.session_id,cashier_fingerprint)
            ).fetchone()
            if not session: raise HTTPException(404,"registration_session_not_found")
            if session["status"]=="completed":
                expected_credential="nfc-"+card_uid.replace(":","").replace("-","").lower()
                if session["card_uid"]==card_uid and session["credential_id"]==expected_credential and identity.verify_pin(session["member_id"],q.pin):
                    return {"session_id":q.session_id,"member_id":session["member_id"],"credential_id":expected_credential,"card_uid":card_uid,"status":"completed","pin_status":"set"}
                raise HTTPException(409,"registration_session_already_completed")
            if session["status"] not in {"scan_pending","processing"}: raise HTTPException(409,"registration_session_not_pending")
            if session["expires_at"]<=__import__("datetime").datetime.now(__import__("datetime").timezone.utc).strftime("%Y-%m-%d %H:%M:%S"):
                c.execute("UPDATE nfc_registration_sessions SET status='expired' WHERE session_id=?",(q.session_id,))
                c.commit()
                raise HTTPException(409,"registration_session_expired")
            replacement=c.execute("SELECT operator_id FROM nfc_replacement_intents WHERE session_id=? AND member_id=?",(q.session_id,session["member_id"])).fetchone()
            duplicate=c.execute(
                "SELECT member_id,status FROM member_nfc_cards WHERE UPPER(card_uid)=?",
                (card_uid,)
            ).fetchone()
            if duplicate:
                raise HTTPException(409,"nfc_card_already_registered")
            credential_id="nfc-"+card_uid.replace(":","").replace("-","").lower()
            cred=c.execute("SELECT member_id FROM identity_credentials WHERE credential_id=?",(credential_id,)).fetchone()
            if cred and cred["member_id"]!=session["member_id"]:
                raise HTTPException(409,"credential_already_registered")
        if replacement:
            with db.connect() as c:
                active_credential=c.execute(
                    "SELECT credential_id FROM member_nfc_cards WHERE member_id=? AND status='active' "
                    "ORDER BY created_at DESC LIMIT 1",(session["member_id"],)
                ).fetchone()
            if not active_credential or not active_credential["credential_id"]:
                raise HTTPException(409,"active_member_credential_required_for_replacement")
            try:
                pin_ok=identity.verify_credential_pin(active_credential["credential_id"],q.pin)
            except PermissionError as exc:
                raise HTTPException(403,str(exc))
            if not pin_ok:
                raise HTTPException(403,"invalid_member_pin_for_card_replacement")
            pin_salt=None;pin_hash=None
        else:
            pin_salt=secrets.token_hex(16)
            pin_hash=identity._hash_pin(q.pin,pin_salt)
        try:
            with db.connect() as c:
                c.execute("BEGIN IMMEDIATE")
                # Re-read the session under the write lock. The earlier read is only
                # preliminary validation; two concurrent completion requests must not
                # both be allowed to finish the same registration session.
                locked_session=c.execute(
                    "SELECT member_id,status,expires_at,hardware_id FROM nfc_registration_sessions WHERE session_id=?",
                    (q.session_id,)
                ).fetchone()
                if not locked_session or locked_session["member_id"] != session["member_id"] or locked_session["hardware_id"] != cashier_fingerprint:
                    raise HTTPException(404,"registration_session_not_found")
                if locked_session["status"] not in {"scan_pending","processing"}:
                    raise HTTPException(409,"registration_session_not_pending")
                if locked_session["expires_at"] <= __import__("datetime").datetime.now(__import__("datetime").timezone.utc).strftime("%Y-%m-%d %H:%M:%S"):
                    c.execute("UPDATE nfc_registration_sessions SET status='expired' WHERE session_id=? AND status IN ('scan_pending','processing')",(q.session_id,))
                    c.commit()
                    raise HTTPException(409,"registration_session_expired")
                # Recheck ownership after acquiring the write lock to prevent two cashiers
                # from binding the same UID concurrently.
                duplicate=c.execute("SELECT member_id FROM member_nfc_cards WHERE UPPER(card_uid)=?",(card_uid,)).fetchone()
                if duplicate: raise HTTPException(409,"nfc_card_already_registered")
                credential_owner=c.execute("SELECT member_id FROM identity_credentials WHERE credential_id=?",(credential_id,)).fetchone()
                if credential_owner: raise HTTPException(409,"credential_already_registered")
                if not replacement:
                    c.execute("UPDATE identity_members SET pin_salt=?,pin_hash=? WHERE member_id=?",(pin_salt,pin_hash,session["member_id"]))
                if replacement:
                    old_credentials=c.execute("SELECT credential_id FROM member_nfc_cards WHERE member_id=? AND status='active'",(session["member_id"],)).fetchall()
                    c.execute("UPDATE member_nfc_cards SET status='revoked',revoked_at=CURRENT_TIMESTAMP WHERE member_id=? AND status='active'",(session["member_id"],))
                    for old_credential in old_credentials:
                        if old_credential["credential_id"]:
                            c.execute("UPDATE identity_credentials SET status='inactive',enabled=0 WHERE credential_id=?",(old_credential["credential_id"],))
                    old_ids=",".join(x["credential_id"] for x in old_credentials if x["credential_id"])
                    c.execute("INSERT INTO audit_events(event_type,entity_type,entity_id,detail) VALUES(?,?,?,?)",
                              ("nfc_replacement","member",session["member_id"],f"old_credentials={old_ids or 'none'};new_credential={credential_id};operator={replacement['operator_id']};result=success"))
                c.execute(
                    "INSERT INTO identity_credentials(credential_id,member_id,credential_type,status) VALUES(?,?, 'nfc','active')",
                    (credential_id,session["member_id"])
                )
                c.execute(
                    "INSERT INTO member_nfc_cards(card_id,member_id,credential_id,card_uid,status) VALUES(?,?,?,?, 'active')",
                    ("nfc-"+uuid4().hex,session["member_id"],credential_id,card_uid)
                )
                c.execute(
                    """UPDATE nfc_registration_sessions
                       SET status='completed',card_uid=?,credential_id=?,completed_at=CURRENT_TIMESTAMP
                       WHERE session_id=?""",
                    (card_uid,credential_id,q.session_id)
                )
                c.execute(
                    "INSERT INTO audit_events(event_type,entity_type,entity_id,detail) VALUES(?,?,?,?)",
                    ("identity","nfc_registration",q.session_id,f"completed:member={session['member_id']}:cashier_key={cashier_fingerprint}")
                )
                c.commit()
        except Exception as exc:
            if "UNIQUE" in str(exc).upper():
                raise HTTPException(409,"nfc_card_already_registered")
            raise
        return {"session_id":q.session_id,"member_id":session["member_id"],"credential_id":credential_id,
                "card_uid":card_uid,"status":"completed","pin_status":"set"}

    @r.post("/cashier/operator-pin")
    def cashier_operator_pin(request: Request, q:OperatorPinRequest):
        require_admin(request)
        require_super_admin(request)
        if not q.pin.isdigit() or not 4 <= len(q.pin) <= 6:
            raise HTTPException(400,"pin_must_be_4_to_6_digits")
        salt=secrets.token_hex(16)
        digest=hashlib.pbkdf2_hmac("sha256",q.pin.encode(),salt.encode(),120000).hex()
        with db.connect() as c:
            c.execute("INSERT OR REPLACE INTO system_meta(key,value) VALUES('cashier_operator_pin_hash',?)",(salt+":"+digest,))
            c.execute("INSERT INTO audit_events(event_type,entity_type,entity_id,detail) VALUES(?,?,?,?)",("cashier","operator_pin","system","updated"))
            c.commit()
        return {"status":"pin_updated"}

    def verify_operator_pin(pin, hardware_id):
        now=int(time.time())
        client_key="operator-pin:"+str(hardware_id)
        with db.connect() as c:
            failures=c.execute(
                "SELECT COUNT(*) FROM webui_login_attempts WHERE client_key=? AND succeeded=0 AND attempted_at>=?",
                (client_key,now-900),
            ).fetchone()[0]
            if failures>=5:
                raise HTTPException(429,"operator_pin_rate_limited",headers={"Retry-After":"900"})
            row=c.execute("SELECT value FROM system_meta WHERE key='cashier_operator_pin_hash'").fetchone()
        valid=False
        if row and row["value"] and ":" in row["value"]:
            salt,digest=row["value"].split(":",1)
            got=hashlib.pbkdf2_hmac("sha256",pin.encode(),salt.encode(),120000).hex()
            valid=secrets.compare_digest(got,digest)
        with db.connect() as c:
            c.execute("INSERT INTO webui_login_attempts(client_key,attempted_at,succeeded) VALUES(?,?,?)",
                      (client_key,now,1 if valid else 0))
            c.execute("DELETE FROM webui_login_attempts WHERE attempted_at<?",(now-86400,))
            c.commit()
        return valid

    @r.post("/cashier/deposits")
    def cashier_deposit(q:CashierDepositRequest,x_m_group_device_key: str | None = Header(default=None)):
        # Device-key fingerprint is the cashier identity; no device ID header or registry lookup is needed.
        cashier_identity=require_device_by_key(x_m_group_device_key, {"esp32-cashier","cashier"})
        hardware_id = cashier_identity["hardware_id"]
        if not verify_operator_pin(q.operator_pin, hardware_id):
            raise HTTPException(403,"invalid_operator_pin")
        if not q.idempotency_key:
            raise HTTPException(400,"idempotency_key_required")
        if not isinstance(q.amount,int) or isinstance(q.amount,bool) or q.amount<=0:
            raise HTTPException(400,"amount_must_be_positive_integer")

        financial_key = "cashier-deposit:" + q.idempotency_key

        auth=identity.authorize_credential(q.credential_id)
        if not auth["authorized"]:
            raise HTTPException(403,auth["reason"])
        account=identity.account_for_credential(q.credential_id)
        if not account["authorized"]:
            raise HTTPException(404,account["reason"])
        try:
            pin_ok=identity.verify_credential_pin(q.credential_id,q.member_pin)
        except PermissionError as e:
            raise HTTPException(403,str(e))
        if not pin_ok:
            raise HTTPException(403,"invalid_pin")

        before = 0
        tid = "cash-" + uuid4().hex
        try:
            with db.connect() as c:
                c.execute("BEGIN IMMEDIATE")
                # Recheck under a write lock to make retries/concurrent taps atomic.
                old = c.execute("SELECT * FROM cashier_deposits WHERE idempotency_key=?",(q.idempotency_key,)).fetchone()
                if old:
                    # An idempotent retry may replay only on the same physical
                    # cashier. Keep transaction attribution immutable across retries.
                    if (old["credential_id"] != q.credential_id or old["amount"] != q.amount
                        or old["hardware_id"] != hardware_id):
                        raise HTTPException(409,"idempotency_key_conflict")
                    fin = c.execute(
                        "SELECT transaction_id FROM financial_transactions WHERE idempotency_key=?",
                        (financial_key,),
                    ).fetchone()
                    result = dict(old)
                    result["financial_transaction_id"] = fin["transaction_id"] if fin else None
                    return result
                orphan = c.execute(
                    "SELECT transaction_id,account_id,amount,transaction_type,reference FROM financial_transactions WHERE idempotency_key=?",
                    (financial_key,),
                ).fetchone()
                if orphan:
                    raise HTTPException(409,"cashier_deposit_reconciliation_required")
                before = int(c.execute(
                    "SELECT COALESCE(SUM(CASE WHEN direction='credit' THEN amount ELSE -amount END),0) "
                    "FROM financial_ledger WHERE account_id=?",
                    (account["account_id"],),
                ).fetchone()[0])
                fin = financial.credit_on_connection(
                    c, account["account_id"], q.amount,
                    reference=financial_key, idempotency_key=financial_key,
                )
                after = before + q.amount
                c.execute("""INSERT INTO cashier_deposits
                    (transaction_id,hardware_id,credential_id,member_id,account_id,amount,status,idempotency_key,balance_before,balance_after,completed_at)
                    VALUES(?,?,?,?,?,?,?,?,?,?,CURRENT_TIMESTAMP)""",
                    (tid,hardware_id,q.credential_id,account["member_id"],account["account_id"],q.amount,"completed",q.idempotency_key,before,after))
                c.execute("INSERT INTO audit_events(event_type,entity_type,entity_id,detail) VALUES(?,?,?,?)",
                          ("cashier","cashier_deposit",tid,f"deposit:{q.amount}:member={account['member_id']}:cashier_key={hardware_id}"))
                c.commit()
        except ValueError as e:
            code = str(e)
            raise HTTPException(409 if code == "idempotency_key_conflict" else 400, code)
        return {"transaction_id":tid,"status":"completed","hardware_id":hardware_id,"member_id":account["member_id"],"account_id":account["account_id"],"amount":q.amount,"balance_before":before,"balance_after":after,"financial_transaction_id":fin["transaction_id"]}

    @r.post("/cashier/payments")
    def cashier_payment(q:PaymentRequest,x_m_group_device_key: str | None = Header(default=None)):
        try:
            identity = require_device_by_key(x_m_group_device_key, {"esp32-cashier","cashier"})
            if q.method!="NFC":raise HTTPException(400,"cashier_requires_nfc")
            if q.provider!="local":raise HTTPException(400,"invalid_nfc_provider")
            payload=q.model_dump()
            if not q.idempotency_key or len(q.idempotency_key)<8 or len(q.idempotency_key)>128:
                raise HTTPException(400,"invalid_idempotency_key")
            payload["transaction_source"]="CASHIER"
            payload["device_hardware_id"]=identity["hardware_id"] or identity["registry_id"]
            result=payments.pay(**payload)
            return {**result,"hardware_id":identity["hardware_id"],"device_id":identity["registry_id"]}
        except PermissionError as e:raise HTTPException(403,str(e))
        except ValueError as e:
            code=str(e)
            raise HTTPException(409 if code in {"insufficient_balance", "idempotency_key_conflict"} else 400,code)

    @r.get("/audit/report")
    def audit_report(request: Request, source:str="ALL",period:str="day",date:str|None=None,method:str="ALL",
                     start_date:str|None=None,end_date:str|None=None,hardware_id:str="ALL",
                     member_id:str="ALL",status:str="ALL",transaction_id:str=""):
        require_admin(request)
        source=source.upper()
        if source not in {"ALL","CASHIER","VENDING","TOPUP"}: raise HTTPException(400,"invalid_source")
        if period not in {"day","week","month","custom"}: raise HTTPException(400,"invalid_period")
        method=method.upper()
        if method not in {"ALL","NFC","QRIS","CASH"}: raise HTTPException(400,"invalid_method")
        status=status.upper()
        if status not in {"ALL","COMPLETED","PENDING","FAILED","CANCELLED","REFUNDED","REFUNDING","AUTHORIZED","CREATED"}:
            raise HTTPException(400,"invalid_status")
        member_id=(member_id or "ALL").strip()
        transaction_id=(transaction_id or "").strip()
        if len(member_id)>128 or len(transaction_id)>128:
            raise HTTPException(400,"audit_filter_too_long")
        import datetime as dt
        from zoneinfo import ZoneInfo
        jakarta=ZoneInfo("Asia/Jakarta")
        date=date or dt.datetime.now(jakarta).date().isoformat()
        try:
            if period=="custom":
                if not start_date or not end_date:
                    raise ValueError("custom_date_range_required")
                selected_start=dt.date.fromisoformat(start_date)
                selected_end=dt.date.fromisoformat(end_date)
                if selected_start > selected_end:
                    raise ValueError("start_date_after_end_date")
                start=selected_start.isoformat()
                end=(selected_end+dt.timedelta(days=1)).isoformat()
            elif period=="day":
                selected_day=dt.date.fromisoformat(date)
                start=selected_day.isoformat()
                end=(selected_day+dt.timedelta(days=1)).isoformat()
            elif period=="month":
                selected_month=dt.date.fromisoformat(date)
                y,m=selected_month.year,selected_month.month
                start=f"{y:04d}-{m:02d}-01"
                end=f"{y+1:04d}-01-01" if m==12 else f"{y:04d}-{m+1:02d}-01"
            else:
                selected_day=dt.date.fromisoformat(date)
                start=(selected_day-dt.timedelta(days=6)).isoformat()
                end=(selected_day+dt.timedelta(days=1)).isoformat()
            # Transaction timestamps are stored as UTC by SQLite CURRENT_TIMESTAMP.
            # Translate local Asia/Jakarta midnight boundaries to UTC before filtering.
            query_start=dt.datetime.combine(dt.date.fromisoformat(start),dt.time.min,tzinfo=jakarta).astimezone(dt.timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
            query_end=dt.datetime.combine(dt.date.fromisoformat(end),dt.time.min,tzinfo=jakarta).astimezone(dt.timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
        except ValueError as exc:
            raise HTTPException(400,str(exc) or "invalid_date")
        queries=[]
        if source in {"ALL","CASHIER"}:
            queries.append("""SELECT transaction_id,created_at,'CASHIER' source,hardware_id,member_id,account_id,
                              'DEPOSIT' transaction_type,amount,status,'NFC' payment_method,'local' payment_provider
                              FROM cashier_deposits""")
            queries.append("""SELECT p.transaction_id,p.created_at,'CASHIER' source,pda.hardware_id,a.member_id,p.account_id,
                              'PAYMENT' transaction_type,COALESCE(p.final_amount,p.amount) amount,p.status,
                              COALESCE(p.method,'NFC') payment_method,COALESCE(p.provider,'local') payment_provider
                              FROM payment_transactions p
                              LEFT JOIN payment_device_associations pda ON pda.transaction_id=p.transaction_id
                              LEFT JOIN financial_accounts a ON a.account_id=p.account_id
                              WHERE p.transaction_source='CASHIER'""")
        if source == "TOPUP":
            queries.append("""SELECT transaction_id,created_at,'TOPUP' source,hardware_id,member_id,account_id,
                              'TOPUP' transaction_type,amount,status,'NFC' payment_method,'local' payment_provider
                              FROM cashier_deposits""")
        if source in {"ALL","TOPUP"}:
            queries.append("""SELECT f.transaction_id,f.created_at,'TOPUP' source,NULL hardware_id,a.member_id,f.account_id,
                              'TOPUP' transaction_type,f.amount,f.status,'CASH' payment_method,'local' payment_provider
                              FROM financial_transactions f JOIN financial_accounts a ON a.account_id=f.account_id
                              WHERE f.transaction_type='credit' AND COALESCE(f.idempotency_key,'') NOT LIKE 'cashier-deposit:%'""")
        if source in {"ALL","VENDING"}:
            queries.append("""SELECT v.transaction_id,v.created_at,'VENDING' source,m.hardware_id,a.member_id,
                              v.account_id,'PURCHASE' transaction_type,v.amount,v.status,
                              COALESCE(v.payment_method,'NFC') payment_method,COALESCE(v.payment_provider,'local') payment_provider
                              FROM vending_transactions v
                              LEFT JOIN vending_machines m ON m.machine_id=v.machine_id
                              LEFT JOIN financial_accounts a ON a.account_id=v.account_id""")
        combined=" UNION ALL ".join("SELECT * FROM ("+q+") WHERE created_at>=? AND created_at<?" for q in queries)
        sql="SELECT * FROM ("+combined+") WHERE (?='ALL' OR UPPER(COALESCE(payment_method,''))=?) ORDER BY created_at DESC"
        args=[v for _ in queries for v in (query_start,query_end)]+[method,method]
        with db.connect() as c:
            rows=c.execute(sql,args).fetchall()
        transactions=[dict(x) for x in rows]
        if hardware_id and hardware_id!="ALL":
            transactions=[x for x in transactions if x.get("hardware_id")==hardware_id]
        if member_id and member_id!="ALL":
            transactions=[x for x in transactions if member_id.lower() in str(x.get("member_id") or "").lower()]
        if status!="ALL":
            transactions=[x for x in transactions if str(x.get("status") or "").upper()==status]
        if transaction_id:
            transactions=[x for x in transactions if transaction_id.lower() in str(x.get("transaction_id") or "").lower()]
        for transaction in transactions:
            created=transaction.get("created_at")
            if created:
                try:
                    parsed=dt.datetime.strptime(str(created)[:19],"%Y-%m-%d %H:%M:%S").replace(tzinfo=dt.timezone.utc)
                    transaction["created_at"]=parsed.astimezone(jakarta).strftime("%Y-%m-%d %H:%M:%S")
                except ValueError:
                    pass
        return {"source":source,"period":period,"method":method,"start":start,"end":end,"hardware_id":hardware_id,
                "member_id":member_id,"status":status,"transaction_id":transaction_id,"transactions":transactions}

    @r.get("/audit/export.xlsx")
    def audit_export(request: Request, source:str="ALL",period:str="day",date:str|None=None,method:str="ALL",
                     start_date:str|None=None,end_date:str|None=None,hardware_id:str="ALL",
                     member_id:str="ALL",status:str="ALL",transaction_id:str=""):
        require_admin(request)
        # Reuse the endpoint's authorization and parameter validation.
        data=audit_report(request, source, period, date, method, start_date, end_date, hardware_id, member_id, status, transaction_id)
        root=Path(getattr(app_settings,"data_dir",Path.home()/".local/share/M-Group"))/"exports"
        root.mkdir(parents=True,exist_ok=True)
        method_segment=f"-{data['method'].lower()}" if data["method"]!="ALL" else ""
        import datetime as dt
        end_inclusive=(dt.date.fromisoformat(data["end"])-dt.timedelta(days=1)).isoformat()
        if data["period"] == "day":
            export_label = f"audit-{data['source'].lower()}-day-{data['start']}"
        else:
            export_label = f"audit-{data['source'].lower()}-{data['period']}-{data['start']}-to-{end_inclusive}"
        path=root/f"{export_label}{method_segment}.xlsx"
        export_rows_excel(data["transactions"],path,metadata={"source":data["source"],"period":data["period"],"start":data["start"],"end":end_inclusive,"method":data["method"]})
        with db.connect() as c:
            c.execute(
                "INSERT INTO admin_security_events(actor_username,event_type,target_username,detail,created_at) VALUES(?,?,?,?,?)",
                (getattr(request.state,"admin_username",""),"audit_export",None,
                 f"source={data['source']};period={data['period']};start={data['start']};end={end_inclusive};method={data['method']};rows={len(data['transactions'])}",int(time.time())),
            )
            c.commit()
        return FileResponse(path,filename=path.name,media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")

    @r.post("/backup")
    def backup_create(request: Request):
        require_admin(request)
        require_super_admin(request)
        root=Path(getattr(app_settings,"data_dir",Path.home()/".local/share/M-Group"))/"backups"
        root.mkdir(parents=True,exist_ok=True)
        import datetime as dt
        path=root/f"M-Group_BACKUP_{dt.datetime.now().strftime('%Y%m%d_%H%M%S')}_{uuid4().hex[:8]}.mgroup.zip"
        create_native_backup(db,path,include_excel=True)
        with db.connect() as c:
            c.execute(
                "INSERT INTO admin_security_events(actor_username,event_type,target_username,detail,created_at) VALUES(?,?,?,?,?)",
                (getattr(request.state,"admin_username",""),"backup_created",None,"file="+path.name,int(time.time())),
            )
            c.commit()
        return FileResponse(path,filename=path.name,media_type="application/zip")

    @r.post("/backup/restore")
    async def backup_restore(request: Request, file:UploadFile=File(...)):
        require_admin(request)
        require_super_admin(request)
        if not file.filename or not file.filename.endswith(".mgroup.zip"):
            raise HTTPException(400,"invalid_backup_file")
        content = await file.read(MAX_BACKUP_UPLOAD_BYTES + 1)
        if len(content) > MAX_BACKUP_UPLOAD_BYTES:
            raise HTTPException(413,"backup_upload_too_large")
        root=Path(getattr(app_settings,"data_dir",Path.home()/".local/share/M-Group"))/"backups"
        root.mkdir(parents=True,exist_ok=True)
        # Preserve the current live database before replacing it. Keep the
        # snapshot even if validation/restoration fails so operators can recover.
        import datetime as dt
        snapshot=root/f"M-Group_PRE_RESTORE_{dt.datetime.now().strftime('%Y%m%d_%H%M%S')}_{uuid4().hex[:8]}.mgroup.zip"
        path=root/f"restore-upload-{uuid4().hex}.mgroup.zip"
        try:
            create_native_backup(db,snapshot,include_excel=False)
            path.write_bytes(content)
            result=restore_native_backup(db,path)
            # A restored snapshot may contain sessions that were revoked after it was taken.
            # Revoke every session after the database switch so restore cannot resurrect old access.
            restored_at=int(time.time())
            actor=getattr(request.state,"admin_username","")
            with db.connect() as c:
                c.execute("UPDATE webui_sessions SET revoked_at=? WHERE revoked_at IS NULL",(restored_at,))
                c.execute(
                    "INSERT INTO admin_security_events(actor_username,event_type,target_username,detail,created_at) VALUES(?,?,?,?,?)",
                    (actor,"backup_restore",None,"all_admin_sessions_revoked;pre_restore_backup="+snapshot.name,restored_at),
                )
                c.commit()
            return {"status":"restored","manifest":result,"pre_restore_backup":snapshot.name,"admin_sessions_revoked":True}
        except HTTPException:
            raise
        except Exception:
            raise HTTPException(400,"invalid_backup_archive")
        finally:
            path.unlink(missing_ok=True)
            await file.close()

    @r.post("/backup/import-excel")
    async def backup_import_excel(request: Request, file:UploadFile=File(...)):
        require_admin(request)
        require_super_admin(request)
        # An XLSX export is a reporting artifact, not a transactionally complete
        # recovery image. Until import can reconcile every cashier deposit with
        # its ledger entries and idempotency records, fail closed.
        raise HTTPException(501,"excel_import_disabled_use_native_backup")

    return r
