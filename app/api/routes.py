from fastapi import APIRouter, HTTPException, Header, UploadFile, File, Request, Response
from fastapi.responses import FileResponse
from pydantic import BaseModel
import hashlib
import secrets
import re
import io
import zipfile
from app.identity.service import IdentityService
from app.identity.management import MemberManagementService
from app.device.management import DeviceManagementService
from app.vending.promo import PromotionService
from app.payment.service import PaymentService
from app.financial.service import FinancialService
from app.vending.service import VendingService
from app.core.backup import export_excel, export_rows_excel, create_native_backup, restore_native_backup, import_excel
from pathlib import Path
from uuid import uuid4
import time
from urllib.parse import urlsplit
from app.core.auth import hash_password, hash_session_token, new_session_token, verify_password

MAX_BACKUP_UPLOAD_BYTES = 100 * 1024 * 1024
MAX_EXCEL_UPLOAD_BYTES = 25 * 1024 * 1024
MAX_EXCEL_EXPANDED_BYTES = 100 * 1024 * 1024

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
    """Register a logical M-Group endpoint using a server-issued credential only."""
    device_type: str
    device_key: str

class DeviceProvisionRequest(BaseModel):
    device_type: str

class FinancialRequest(BaseModel):
    amount: int
    reference: str | None = None
    idempotency_key: str | None = None

class VendingRegisterRequest(BaseModel):
    machine_id: str
    name: str
    location: str = ""
    status: str = "active"

class VendingUpdateRequest(BaseModel):
    name: str | None = None
    location: str | None = None
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
    cashier_device_id: str
    operator_id: str = "admin"

class NfcRegistrationCompleteRequest(BaseModel):
    session_id: str
    card_uid: str
    pin: str

class CashierDepositRequest(BaseModel):
    credential_id: str
    amount: int
    operator_pin: str
    member_pin: str
    idempotency_key: str

class MemberBalanceLookupRequest(BaseModel):
    card_uid: str

class OperatorPinRequest(BaseModel):
    pin: str

class AdminLoginRequest(BaseModel):
    username: str
    password: str

class AdminAccountUpdateRequest(BaseModel):
    current_password: str
    username: str
    new_password: str | None = None

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

    def require_device(device_id: str, device_key: str | None):
        """Validate a key against an internal credential record, never a client identity."""
        if not device_key:
            raise HTTPException(401, "device_auth_required")
        digest = hashlib.sha256(device_key.encode("utf-8")).hexdigest()
        with db.connect() as c:
            rows = c.execute(
                "SELECT device_id,status,auth_key_hash,device_type FROM device_registry WHERE auth_key_hash=?",
                (digest,),
            ).fetchall()
        if len(rows) != 1:
            raise HTTPException(403, "invalid_device_key")
        row = rows[0]
        if row["status"] != "active":
            raise HTTPException(403, "credential_disabled")
        if not secrets.compare_digest(digest, row["auth_key_hash"] or ""):
            raise HTTPException(403, "invalid_device_key")
        if device_id is not None and row["device_id"] != device_id:
            raise HTTPException(403, "credential_scope_mismatch")
        return row

    def require_device_key(device_key: str | None, allowed_types: set[str]):
        if not device_key:
            raise HTTPException(401, "device_auth_required")
        digest = hashlib.sha256(device_key.encode("utf-8")).hexdigest()
        with db.connect() as c:
            rows = c.execute(
                "SELECT device_type,status,auth_key_hash FROM device_registry WHERE auth_key_hash=?",
                (digest,),
            ).fetchall()
        if len(rows) != 1:
            raise HTTPException(403, "invalid_device_key")
        row = rows[0]
        if row["status"] != "active":
            raise HTTPException(403, "device_not_active")
        if not secrets.compare_digest(digest, row["auth_key_hash"] or ""):
            raise HTTPException(403, "invalid_device_key")
        if row["device_type"] not in allowed_types:
            raise HTTPException(403, "device_type_not_allowed")
        return row

    def resolve_vending_machine(identifier: str):
        """Resolve a business machine ID only; authentication is handled by its key."""
        with db.connect() as c:
            row = c.execute(
                "SELECT machine_id FROM vending_machines WHERE machine_id=?",
                (identifier,),
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
                "SELECT username,password_hash FROM webui_admin_accounts ORDER BY updated_at DESC LIMIT 1"
            ).fetchone()
            if account is None and configured_username and configured_hash:
                c.execute(
                    "INSERT OR IGNORE INTO webui_admin_accounts(username,password_hash,updated_at) VALUES(?,?,?)",
                    (configured_username, configured_hash, now),
                )
                account = c.execute(
                    "SELECT username,password_hash FROM webui_admin_accounts ORDER BY updated_at DESC LIMIT 1"
                ).fetchone()
            failures = c.execute(
                "SELECT COUNT(*) FROM webui_login_attempts WHERE client_key=? AND succeeded=0 AND attempted_at>=?",
                (client_key, now - 900),
            ).fetchone()[0]
            c.commit()
        if account is None:
            raise HTTPException(503, "admin_login_not_configured")
        if failures >= 10:
            raise HTTPException(429, "login_rate_limited")
        password_valid = verify_password(q.password, account["password_hash"])
        username_valid = secrets.compare_digest(username, account["username"])
        valid = username_valid and password_valid
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
        return {"authenticated": True, "username": account["username"]}

    @r.get("/auth/session")
    def admin_session(request: Request):
        token = request.cookies.get("m_group_session", "")
        if not token:
            raise HTTPException(401, "admin_session_required")
        now = int(time.time())
        with db.connect() as c:
            row = c.execute(
                """SELECT username FROM webui_sessions
                   WHERE session_hash=? AND revoked_at IS NULL AND expires_at>? AND last_seen>?""",
                (hash_session_token(token), now, now - 1800),
            ).fetchone()
            if row:
                c.execute("UPDATE webui_sessions SET last_seen=? WHERE session_hash=?",
                          (now, hash_session_token(token)))
                c.commit()
        if not row:
            raise HTTPException(401, "admin_session_expired")
        return {"authenticated": True, "username": row["username"]}

    @r.post("/auth/account")
    def admin_account_update(q: AdminAccountUpdateRequest, request: Request):
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
        if q.new_password is not None and len(q.new_password) < 8:
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
                "SELECT password_hash FROM webui_admin_accounts WHERE username=?",
                (session["username"],),
            ).fetchone()
            if account is None or not verify_password(q.current_password, account["password_hash"]):
                raise HTTPException(403, "invalid_current_password")
            password_hash = hash_password(q.new_password) if q.new_password else account["password_hash"]
            c.execute("DELETE FROM webui_admin_accounts")
            c.execute(
                "INSERT INTO webui_admin_accounts(username,password_hash,updated_at) VALUES(?,?,?)",
                (username, password_hash, now),
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
        return {"events":[dict(x) for x in rows]}

    @r.post("/devices/handshake")
    def device_handshake(q: DeviceRegisterRequest):
        """Backward-compatible alias; validation and event logging live in register."""
        result = device_register(q)
        return {**result, "handshake": "accepted"}

    @r.get("/devices/{device_id}/events")
    def device_events(request: Request, device_id,limit:int=100):
        require_admin(request)
        limit=max(1,min(limit,500))
        with db.connect() as c:
            rows=c.execute("SELECT id,device_id,event_type,payload,created_at FROM device_events WHERE device_id=? ORDER BY id DESC LIMIT ?",(device_id,limit)).fetchall()
        return {"device_id":device_id,"events":[dict(x) for x in rows]}

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
            payments_rows=c.execute("""SELECT transaction_id,credential_id,account_id,amount,final_amount,status,method,provider,transaction_source,created_at
                   FROM payment_transactions ORDER BY created_at DESC LIMIT 50""").fetchall()
            vending_rows=c.execute("""SELECT transaction_id,machine_id,product_id,account_id,amount,status,created_at
                   FROM vending_transactions ORDER BY created_at DESC LIMIT 50""").fetchall()
            loans=c.execute("""SELECT loan_id,member_id,principal,installment_amount,remaining_balance,status,created_at
                   FROM loan_accounts ORDER BY created_at DESC LIMIT 50""").fetchall()
            machines=c.execute("SELECT machine_id,name,status,location,NULL AS last_seen FROM vending_machines ORDER BY name").fetchall()
            products=c.execute("""SELECT CAST(slot AS TEXT) AS product_id,machine_id,name,price,stock,capacity,slot,slot AS servo_channel,enabled
                   FROM vending_products WHERE slot BETWEEN 1 AND 5 ORDER BY machine_id,slot""").fetchall()
            devices=c.execute("SELECT device_type,status,last_seen FROM device_registry ORDER BY created_at").fetchall()
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
                SELECT m.machine_id,m.name,COUNT(v.transaction_id) AS transactions
                FROM vending_machines m LEFT JOIN vending_transactions v
                  ON v.machine_id=m.machine_id AND v.status='completed' AND v.created_at>=datetime('now',?)
                GROUP BY m.machine_id,m.name ORDER BY transactions DESC,m.name LIMIT 5
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
                "analytics_period":period,"analytics":[dict(x) for x in analytics_rows],"most_used_vending":[dict(x) for x in most_used_rows],"payment_channels":[dict(x) for x in payment_channel_rows],
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
        try:
            return members.soft_delete(member_id)
        except ValueError as e:
            raise HTTPException(404,str(e))

    @r.post("/members/{member_id}/nfc-cards")
    def member_add_nfc(request: Request, member_id,q: NfcCardRequest):
        require_admin(request)
        try:
            return members.add_card(member_id,q.card_uid,q.credential_id)
        except ValueError as e:
            code=str(e)
            raise HTTPException(409 if "already" in code else 400,code)

    @r.post("/members/{member_id}/nfc-cards/{card_id}/revoke")
    def member_revoke_nfc(request: Request, member_id,card_id):
        require_admin(request)
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

    @r.get("/devices/{device_id}")
    def device_get(request: Request, device_id):
        require_admin(request)
        result = devices.get(device_id)
        if result is None:
            raise HTTPException(404,"device_not_found")
        return result

    @r.patch("/devices/{device_id}")
    def device_update(request: Request, device_id,q: DeviceHeartbeatRequest):
        require_admin(request)
        try:
            return devices.update(device_id,q.device_type,q.status,q.display_name)
        except ValueError as e:
            raise HTTPException(400,str(e))

    @r.post("/devices/register")
    def device_register(q: DeviceRegisterRequest):
        """Activate a pre-provisioned endpoint using only its server-issued key.

        No client-supplied hardware identifier is accepted, stored, or returned.
        The registry row is an internal credential record, not a hardware identity.
        """
        device_type = q.device_type.strip().lower()
        if device_type == "esp32-vending":
            device_type = "esp32-s3-vending"
        device_key = q.device_key.strip()
        if device_type not in DeviceManagementService.ALLOWED_TYPES:
            raise HTTPException(400, "invalid_device_type")
        if not device_key:
            raise HTTPException(400, "device_key_required")

        digest = hashlib.sha256(device_key.encode("utf-8")).hexdigest()
        with db.connect() as c:
            row = c.execute(
                """SELECT device_id, device_type, status, auth_key_hash
                   FROM device_registry WHERE auth_key_hash=? LIMIT 1""",
                (digest,),
            ).fetchone()
            if row is None or not row["auth_key_hash"]:
                raise HTTPException(403, "device_not_provisioned")
            if not secrets.compare_digest(digest, row["auth_key_hash"]):
                raise HTTPException(403, "invalid_device_key")
            if row["status"] == "disabled":
                raise HTTPException(403, "credential_disabled")
            stored_type = "esp32-s3-vending" if row["device_type"] == "esp32-vending" else row["device_type"]
            if stored_type != device_type:
                raise HTTPException(403, "credential_scope_mismatch")

            c.execute(
                """UPDATE device_registry
                   SET device_type=?, status='active', last_seen=CURRENT_TIMESTAMP,
                       updated_at=CURRENT_TIMESTAMP
                   WHERE device_id=?""",
                (device_type, row["device_id"]),
            )
            c.execute(
                "INSERT INTO device_events(device_id,event_type,payload) VALUES(?,?,?)",
                (row["device_id"], "credential_registration", '{"result":"accepted"}'),
            )
            c.commit()
        return {"device_type": device_type, "status": "active", "registered": True}

    @r.delete("/devices/{device_id}")
    def device_delete(request: Request, device_id):
        require_admin(request)
        try:
            return devices.soft_delete(device_id)
        except ValueError as e:
            raise HTTPException(404,str(e))

    @r.post("/devices/provision")
    def device_provision_auto(request: Request, q: DeviceProvisionRequest):
        """Issue a one-time server credential; no hardware identity is requested or returned."""
        require_admin(request)
        device_type = q.device_type.strip().lower()
        if device_type == "esp32-vending":
            device_type = "esp32-s3-vending"
        if device_type not in DeviceManagementService.ALLOWED_TYPES:
            raise HTTPException(400, "invalid_device_type")
        credential_ref = "cred-" + uuid4().hex
        key = secrets.token_urlsafe(32)
        digest = hashlib.sha256(key.encode("utf-8")).hexdigest()
        with db.connect() as c:
            c.execute(
                """INSERT INTO device_registry
                   (device_id,device_type,display_name,status,last_seen,auth_key_hash,
                    auth_key_hint,created_at,updated_at)
                   VALUES(?,?,'Perangkat M-Group','active',NULL,?,?,CURRENT_TIMESTAMP,CURRENT_TIMESTAMP)""",
                (credential_ref, device_type, digest, key[-6:]),
            )
            c.execute(
                "INSERT INTO audit_events(event_type,entity_type,entity_id,detail) VALUES(?,?,?,?)",
                ("credential", "provisioned", credential_ref, f"type={device_type};result=issued"),
            )
            c.commit()
        return {"device_type": device_type, "device_key": key,
                "status": "active", "key_shown_once": True}

    @r.post("/devices/heartbeat")
    def device_heartbeat(q: DeviceHeartbeatRequest,
                         x_m_group_device_key: str | None = Header(default=None)):
        """Record endpoint liveness using its server-issued key, without a path ID."""
        credential = require_device_key(
            x_m_group_device_key,
            DeviceManagementService.ALLOWED_TYPES,
        )
        if q.status != "active":
            raise HTTPException(400, "invalid_heartbeat_status")
        device_type = q.device_type.strip().lower()
        if device_type == "esp32-vending":
            device_type = "esp32-s3-vending"
        if device_type not in DeviceManagementService.ALLOWED_TYPES:
            raise HTTPException(400, "invalid_device_type")
        if credential["device_type"] != device_type:
            raise HTTPException(403, "credential_scope_mismatch")
        digest = credential["auth_key_hash"]
        with db.connect() as c:
            c.execute(
                "UPDATE device_registry SET last_seen=CURRENT_TIMESTAMP WHERE auth_key_hash=?",
                (digest,),
            )
            c.execute(
                "INSERT INTO device_events(device_id,event_type,payload) "
                "SELECT device_id,'heartbeat',? FROM device_registry WHERE auth_key_hash=?",
                (q.model_copy(update={"device_type": device_type}).model_dump_json(), digest),
            )
            c.commit()
        return {"device_type": device_type, "status": "active"}

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
        """Read-only balance lookup authorized solely by a server-issued key."""
        card_uid = q.card_uid.strip()
        if not card_uid:
            raise HTTPException(400, "card_uid_required")
        credential = require_device_key(
            x_m_group_device_key,
            {"esp32-cashier", "esp32-vending", "esp32-s3-vending", "cashier", "vending"},
        )
        # Internal rate-limit partition only; never returned as an API identity.
        credential_ref = hashlib.sha256((credential["auth_key_hash"] or "").encode("utf-8")).hexdigest()[:32]
        uid_hash = hashlib.sha256(card_uid.casefold().encode("utf-8")).hexdigest()
        now = time.time()
        with db.connect() as c:
            prior = c.execute(
                "SELECT last_lookup_at FROM device_balance_lookup_limits WHERE device_id=? AND card_uid_hash=?",
                (credential_ref, uid_hash),
            ).fetchone()
            if prior and now - float(prior["last_lookup_at"]) < 2.0:
                raise HTTPException(429, "balance_lookup_rate_limited", headers={"Retry-After": "2"})
            c.execute(
                """INSERT INTO device_balance_lookup_limits(device_id,card_uid_hash,last_lookup_at)
                   VALUES(?,?,?) ON CONFLICT(device_id,card_uid_hash)
                   DO UPDATE SET last_lookup_at=excluded.last_lookup_at""",
                (credential_ref, uid_hash, now),
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
        if not account:
            raise HTTPException(404, "account_not_found")
        return {
            "member_id": member["member_id"],
            "account_id": account["account_id"],
            "balance": financial.balance(account["account_id"]),
            "read_only": True,
        }

    @r.get("/accounts/{account_id}/ledger")
    def account_ledger(request: Request, account_id,limit:int=100):
        require_admin(request)
        try:return {"account_id":account_id,"entries":financial.ledger(account_id,limit)}
        except ValueError as e:raise HTTPException(404,str(e))

    @r.post("/accounts/{account_id}/credit")
    def account_credit(request: Request, account_id,q:FinancialRequest):
        require_admin(request)
        try:return financial.credit(account_id,q.amount,q.reference,q.idempotency_key)
        except ValueError as e:
            code=str(e); raise HTTPException(409 if code=="insufficient_balance" else 400,code)

    @r.post("/accounts/{account_id}/debit")
    def account_debit(request: Request, account_id,q:FinancialRequest):
        require_admin(request)
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
        try:return vending.register(q.machine_id,q.name,q.location,q.status)
        except ValueError as e: raise HTTPException(409 if "already" in str(e) else 400,str(e))

    @r.get("/vending/{machine_id}")
    def vending_detail(request: Request, machine_id):
        require_admin(request)
        try:return {"machine":vending.machine(machine_id),"slots":vending.slots(machine_id)}
        except ValueError as e:raise HTTPException(404,str(e))

    @r.patch("/vending/{machine_id}")
    def vending_update(request: Request, machine_id,q:VendingUpdateRequest):
        require_admin(request)
        try:return vending.update_machine(machine_id,q.name,q.location,q.status)
        except ValueError as e:raise HTTPException(409 if "already" in str(e) else 400,str(e))

    @r.post("/vending/{machine_id}/enable")
    def vending_enable(request: Request, machine_id):
        require_admin(request)
        try:return vending.set_status(machine_id,"active")
        except ValueError as e:raise HTTPException(404 if str(e)=="machine_not_found" else 400,str(e))

    @r.post("/vending/{machine_id}/disable")
    def vending_disable(request: Request, machine_id):
        require_admin(request)
        try:return vending.set_status(machine_id,"disabled")
        except ValueError as e:raise HTTPException(404 if str(e)=="machine_not_found" else 400,str(e))

    @r.get("/vending/{machine_id}/products")
    def vending_products(request: Request, machine_id, x_m_group_device_key: str | None = Header(default=None)):
        machine = resolve_vending_machine(machine_id)
        if x_m_group_device_key:
            require_device_key(x_m_group_device_key, {"esp32-vending", "esp32-s3-vending", "vending"})
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
        return {"machine": machine, "products": catalog}

    @r.put("/vending/{machine_id}/products/{product_id}")
    def vending_product(request: Request, machine_id,product_id,q:VendingProductRequest):
        require_admin(request)
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
            machine = resolve_vending_machine(machine_id)
            require_device_key(x_m_group_device_key, {"esp32-vending", "esp32-s3-vending", "vending"})
            require_device_key(x_m_group_device_key, {"esp32-vending", "esp32-s3-vending", "vending"})
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
            require_device_key(x_m_group_device_key, {"esp32-vending", "esp32-s3-vending", "vending"})
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
            if not machine.get("device_id"): raise HTTPException(403,"machine_device_not_configured")
            require_device_key(x_m_group_device_key, {"esp32-vending", "esp32-s3-vending", "vending"})
            return public_vending_transaction(vending.authorize(transaction_id))
        except PermissionError as e:raise HTTPException(403,str(e))
        except ValueError as e:raise HTTPException(400,str(e))

    @r.post("/vending/transactions/{transaction_id}/dispense")
    def vending_dispense(transaction_id,q:VendingDispenseRequest,x_m_group_device_key: str | None = Header(default=None)):
        try:
            tx=vending.get(transaction_id)
            machine=vending.machine(tx["machine_id"])
            if not machine.get("device_id"): raise HTTPException(403,"machine_device_not_configured")
            require_device_key(x_m_group_device_key, {"esp32-vending", "esp32-s3-vending", "vending"})
            return public_vending_transaction(vending.dispense(transaction_id,q.success))
        except ValueError as e:raise HTTPException(409,str(e))

    @r.post("/payments")
    def payment(request: Request, q:PaymentRequest):
        require_admin(request)
        if q.method == "NFC":
            if not q.pin:
                raise HTTPException(403, "pin_required")
            try:
                if not identity.verify_credential_pin(q.credential_id, q.pin):
                    raise HTTPException(403, "invalid_pin")
            except PermissionError as e:
                raise HTTPException(403, str(e))
        try:return payments.pay(**q.model_dump())
        except PermissionError as e:raise HTTPException(403,str(e))
        except ValueError as e:
            code=str(e)
            raise HTTPException(409 if code in {"insufficient_balance", "idempotency_key_conflict"} else 400,code)

    @r.post("/members/{member_id}/nfc-registration/start")
    def nfc_registration_start(request: Request, member_id,q:NfcRegistrationStartRequest):
        require_admin(request)
        member=members.get(member_id)
        if not member or member.get("status")!="active":
            raise HTTPException(404,"member_not_found")
        with db.connect() as c:
            device=c.execute(
                "SELECT device_id,device_type,status FROM device_registry WHERE device_id=?",
                (q.cashier_device_id,)
            ).fetchone()
            if not device or device["device_type"]!="esp32-cashier" or device["status"]!="active":
                raise HTTPException(409,"cashier_not_active")
            pending=c.execute(
                "SELECT session_id FROM nfc_registration_sessions WHERE device_id=? AND status='scan_pending' "
                "AND expires_at>CURRENT_TIMESTAMP",(q.cashier_device_id,)
            ).fetchone()
            if pending:
                raise HTTPException(409,"cashier_registration_busy")
            session_id="nfc-reg-"+uuid4().hex
            c.execute(
                """INSERT INTO nfc_registration_sessions
                   (session_id,member_id,device_id,status,expires_at)
                   VALUES(?,?,?,'scan_pending',datetime('now','+5 minutes'))""",
                (session_id,member_id,q.cashier_device_id)
            )
            c.execute(
                "INSERT INTO audit_events(event_type,entity_type,entity_id,detail) VALUES(?,?,?,?)",
                ("identity","nfc_registration",session_id,f"started:member={member_id}:device={q.cashier_device_id}")
            )
            c.commit()
        return {"session_id":session_id,"member_id":member_id,"cashier_device_id":q.cashier_device_id,"status":"scan_pending"}

    @r.post("/members/{member_id}/nfc-replacement/start")
    def nfc_replacement_start(request: Request, member_id,q:NfcRegistrationStartRequest):
        require_admin(request)
        if not q.operator_id.strip():
            raise HTTPException(400,"operator_id_required")
        member=members.get(member_id)
        if not member or member.get("status")!="active":
            raise HTTPException(404,"member_not_found")
        with db.connect() as c:
            device=c.execute("SELECT device_id,device_type,status FROM device_registry WHERE device_id=?",(q.cashier_device_id,)).fetchone()
            if not device or device["device_type"]!="esp32-cashier" or device["status"]!="active":
                raise HTTPException(409,"cashier_not_active")
            pending=c.execute("SELECT session_id FROM nfc_registration_sessions WHERE device_id=? AND status='scan_pending' AND expires_at>CURRENT_TIMESTAMP",(q.cashier_device_id,)).fetchone()
            if pending:
                raise HTTPException(409,"cashier_registration_busy")
            session_id="nfc-replace-"+uuid4().hex
            c.execute("INSERT INTO nfc_registration_sessions(session_id,member_id,device_id,status,expires_at) VALUES(?,?,?,'scan_pending',datetime('now','+5 minutes'))",(session_id,member_id,q.cashier_device_id))
            c.execute("INSERT INTO nfc_replacement_intents(session_id,member_id,operator_id) VALUES(?,?,?)",(session_id,member_id,q.operator_id.strip()))
            c.execute("INSERT INTO audit_events(event_type,entity_type,entity_id,detail) VALUES(?,?,?,?)",("nfc_replacement","member",member_id,f"started:session={session_id}:device={q.cashier_device_id}"))
            c.commit()
        return {"session_id":session_id,"member_id":member_id,"cashier_device_id":q.cashier_device_id,"status":"scan_pending","operation":"replacement"}

    @r.get("/members/{member_id}/nfc-registration/{session_id}")
    def nfc_registration_status(request: Request, member_id,session_id):
        require_admin(request)
        with db.connect() as c:
            row=c.execute(
                "SELECT session_id,member_id,device_id,status,card_uid,credential_id,created_at,completed_at "
                "FROM nfc_registration_sessions WHERE session_id=? AND member_id=?",
                (session_id,member_id)
            ).fetchone()
        if not row: raise HTTPException(404,"registration_session_not_found")
        return dict(row)

    @r.get("/cashier/{device_id}/nfc-registration")
    def cashier_nfc_registration(device_id,x_m_group_device_key: str | None = Header(default=None)):
        require_device(device_id,x_m_group_device_key)
        with db.connect() as c:
            row=c.execute(
                """SELECT session_id,member_id,status
                   FROM nfc_registration_sessions
                   WHERE device_id=? AND status='scan_pending' AND expires_at>CURRENT_TIMESTAMP
                   ORDER BY created_at LIMIT 1""",
                (device_id,)
            ).fetchone()
        if not row:
            return {"status":"idle"}
        return {"status":"scan_pending","session_id":row["session_id"],"member_id":row["member_id"]}

    @r.post("/cashier/{device_id}/nfc-registration/complete")
    def cashier_nfc_registration_complete(device_id,q:NfcRegistrationCompleteRequest,
                                           x_m_group_device_key: str | None = Header(default=None)):
        require_device(device_id,x_m_group_device_key)
        if not q.pin.isdigit() or len(q.pin)!=4:
            raise HTTPException(400,"registration_pin_must_be_4_digits")
        card_uid=(q.card_uid or "").strip().upper()
        if not card_uid: raise HTTPException(400,"card_uid_required")
        with db.connect() as c:
            session=c.execute(
                "SELECT * FROM nfc_registration_sessions WHERE session_id=? AND device_id=?",
                (q.session_id,device_id)
            ).fetchone()
            if not session: raise HTTPException(404,"registration_session_not_found")
            if session["status"]!="scan_pending": raise HTTPException(409,"registration_session_not_pending")
            if session["expires_at"]<=__import__("datetime").datetime.now().strftime("%Y-%m-%d %H:%M:%S"):
                c.execute("UPDATE nfc_registration_sessions SET status='expired' WHERE session_id=?",(q.session_id,))
                c.commit()
                raise HTTPException(409,"registration_session_expired")
            replacement=c.execute("SELECT operator_id FROM nfc_replacement_intents WHERE session_id=? AND member_id=?",(q.session_id,session["member_id"])).fetchone()
            duplicate=c.execute(
                "SELECT member_id FROM member_nfc_cards WHERE UPPER(card_uid)=? AND status='active'",
                (card_uid,)
            ).fetchone()
            if duplicate:
                raise HTTPException(409,"nfc_card_already_registered")
            credential_id="nfc-"+card_uid.replace(":","").replace("-","").lower()
            cred=c.execute("SELECT member_id FROM identity_credentials WHERE credential_id=?",(credential_id,)).fetchone()
            if cred and cred["member_id"]!=session["member_id"]:
                raise HTTPException(409,"credential_already_registered")
        if replacement:
            if not identity.verify_pin(session["member_id"],q.pin):
                raise HTTPException(403,"invalid_member_pin_for_card_replacement")
        else:
            identity.set_pin(session["member_id"],q.pin)
        try:
            with db.connect() as c:
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
                    ("identity","nfc_registration",q.session_id,f"completed:member={session['member_id']}:device={device_id}")
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
        if not q.pin.isdigit() or not 4 <= len(q.pin) <= 6:
            raise HTTPException(400,"pin_must_be_4_to_6_digits")
        salt=secrets.token_hex(16)
        digest=hashlib.pbkdf2_hmac("sha256",q.pin.encode(),salt.encode(),120000).hex()
        with db.connect() as c:
            c.execute("INSERT OR REPLACE INTO system_meta(key,value) VALUES('cashier_operator_pin_hash',?)",(salt+":"+digest,))
            c.execute("INSERT INTO audit_events(event_type,entity_type,entity_id,detail) VALUES(?,?,?,?)",("cashier","operator_pin","system","updated"))
            c.commit()
        return {"status":"pin_updated"}

    def verify_operator_pin(pin):
        with db.connect() as c:
            row=c.execute("SELECT value FROM system_meta WHERE key='cashier_operator_pin_hash'").fetchone()
        if not row or not row["value"] or ":" not in row["value"]: return False
        salt,digest=row["value"].split(":",1)
        got=hashlib.pbkdf2_hmac("sha256",pin.encode(),salt.encode(),120000).hex()
        return secrets.compare_digest(got,digest)

    @r.post("/cashier/deposits")
    def cashier_deposit(q:CashierDepositRequest,x_m_group_device_key: str | None = Header(default=None)):
        credential = require_device_key(x_m_group_device_key, {"esp32-cashier", "cashier"})
        device_id = hashlib.sha256((credential["auth_key_hash"] or "").encode("utf-8")).hexdigest()[:32]
        if not verify_operator_pin(q.operator_pin):
            raise HTTPException(403,"invalid_operator_pin")
        if not q.idempotency_key:
            raise HTTPException(400,"idempotency_key_required")
        if not isinstance(q.amount,int) or isinstance(q.amount,bool) or q.amount<=0:
            raise HTTPException(400,"amount_must_be_positive_integer")

        financial_key = "cashier-deposit:" + q.idempotency_key
        with db.connect() as c:
            old = c.execute("SELECT * FROM cashier_deposits WHERE idempotency_key=?",(q.idempotency_key,)).fetchone()
            if old:
                if (old["device_id"] != device_id or old["credential_id"] != q.credential_id
                    or old["amount"] != q.amount):
                    raise HTTPException(409,"idempotency_key_conflict")
                fin = c.execute(
                    "SELECT transaction_id FROM financial_transactions WHERE idempotency_key=?",
                    (financial_key,),
                ).fetchone()
                result = dict(old)
                result["financial_transaction_id"] = fin["transaction_id"] if fin else None
                return result

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
                    if (old["device_id"] != device_id or old["credential_id"] != q.credential_id
                        or old["amount"] != q.amount):
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
                    (transaction_id,device_id,credential_id,member_id,account_id,amount,status,idempotency_key,balance_before,balance_after,completed_at)
                    VALUES(?,?,?,?,?,?,?,?,?,?,CURRENT_TIMESTAMP)""",
                    (tid,device_id,q.credential_id,account["member_id"],account["account_id"],q.amount,"completed",q.idempotency_key,before,after))
                c.execute("INSERT INTO audit_events(event_type,entity_type,entity_id,detail) VALUES(?,?,?,?)",
                          ("cashier","cashier_deposit",tid,f"deposit:{q.amount}:member={account['member_id']}:device={device_id}"))
                c.commit()
        except ValueError as e:
            code = str(e)
            raise HTTPException(409 if code == "idempotency_key_conflict" else 400, code)
        return {"transaction_id":tid,"status":"completed","member_id":account["member_id"],"account_id":account["account_id"],"amount":q.amount,"balance_before":before,"balance_after":after,"financial_transaction_id":fin["transaction_id"]}

    @r.post("/cashier/payments")
    def cashier_payment(q:PaymentRequest,x_m_group_device_key: str | None = Header(default=None)):
        try:
            require_device_key(x_m_group_device_key, {"esp32-cashier", "cashier"})
            if q.method!="NFC":raise HTTPException(400,"cashier_requires_nfc")
            if q.provider!="local":raise HTTPException(400,"invalid_nfc_provider")
            result=payments.pay(**q.model_dump(), require_pin=True)
            with db.connect() as c:
                c.execute("UPDATE payment_transactions SET transaction_source='CASHIER' WHERE transaction_id=?",(result["transaction_id"],))
                c.commit()
            return result
        except PermissionError as e:raise HTTPException(403,str(e))
        except ValueError as e:
            code=str(e)
            raise HTTPException(409 if code in {"insufficient_balance", "idempotency_key_conflict"} else 400,code)

    @r.get("/audit/report")
    def audit_report(request: Request, source:str="ALL",period:str="day",date:str|None=None,method:str="ALL"):
        require_admin(request)
        source=source.upper()
        if source not in {"ALL","CASHIER","VENDING"}: raise HTTPException(400,"invalid_source")
        if period not in {"day","week","month"}: raise HTTPException(400,"invalid_period")
        method=method.upper()
        if method not in {"ALL","NFC","QRIS"}: raise HTTPException(400,"invalid_method")
        import datetime as dt
        date=date or dt.date.today().isoformat()
        if period=="day":
            selected_day=dt.date.fromisoformat(date)
            start=selected_day.isoformat()
            end=(selected_day+dt.timedelta(days=1)).isoformat()
        elif period=="month":
            y,m=map(int,date[:7].split("-")); start=f"{y:04d}-{m:02d}-01"
            end=f"{y+1:04d}-01-01" if m==12 else f"{y:04d}-{m+1:02d}-01"
        else:
            d=dt.date.fromisoformat(date); monday=d-dt.timedelta(days=d.weekday())
            start=monday.isoformat(); end=(monday+dt.timedelta(days=7)).isoformat()
        queries=[]
        if source in {"ALL","CASHIER"}:
            queries.append("""SELECT transaction_id,created_at,'CASHIER' source,member_id,account_id,
                              'DEPOSIT' transaction_type,amount,status,'NFC' payment_method,'local' payment_provider
                              FROM cashier_deposits""")
            queries.append("""SELECT p.transaction_id,p.created_at,'CASHIER' source,a.member_id,p.account_id,
                              'PAYMENT' transaction_type,COALESCE(p.final_amount,p.amount) amount,p.status,
                              COALESCE(p.method,'NFC') payment_method,COALESCE(p.provider,'local') payment_provider
                              FROM payment_transactions p
                              LEFT JOIN financial_accounts a ON a.account_id=p.account_id
                              WHERE p.transaction_source='CASHIER'""")
        if source in {"ALL","VENDING"}:
            queries.append("""SELECT v.transaction_id,v.created_at,'VENDING' source,a.member_id,
                              v.account_id,'PURCHASE' transaction_type,v.amount,v.status,
                              COALESCE(v.payment_method,'NFC') payment_method,COALESCE(v.payment_provider,'local') payment_provider
                              FROM vending_transactions v
                              LEFT JOIN vending_machines m ON m.machine_id=v.machine_id
                              LEFT JOIN financial_accounts a ON a.account_id=v.account_id""")
        combined=" UNION ALL ".join("SELECT * FROM ("+q+") WHERE created_at>=? AND created_at<?" for q in queries)
        sql="SELECT * FROM ("+combined+") WHERE (?='ALL' OR UPPER(COALESCE(payment_method,''))=?) ORDER BY created_at DESC"
        args=[v for _ in queries for v in (start,end)]+[method,method]
        with db.connect() as c:
            rows=c.execute(sql,args).fetchall()
        return {"source":source,"period":period,"method":method,"start":start,"end":end,"transactions":[dict(x) for x in rows]}

    @r.get("/audit/export.xlsx")
    def audit_export(request: Request, source:str="ALL",period:str="day",date:str|None=None,method:str="ALL"):
        require_admin(request)
        # Reuse the endpoint's authorization and parameter validation, passing
        # the already-validated token explicitly because this is a direct call.
        data=audit_report(request, source, period, date, method)
        root=Path(getattr(app_settings,"data_dir",Path.home()/".local/share/M-Group"))/"exports"
        root.mkdir(parents=True,exist_ok=True)
        method_segment=f"-{data['method'].lower()}" if data["method"]!="ALL" else ""
        path=root/f"audit-{data['source'].lower()}-{data['period']}{method_segment}-{data['start']}.xlsx"
        export_rows_excel(data["transactions"],path)
        return FileResponse(path,filename=path.name,media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")

    @r.post("/backup")
    def backup_create(request: Request):
        require_admin(request)
        root=Path(getattr(app_settings,"data_dir",Path.home()/".local/share/M-Group"))/"backups"
        root.mkdir(parents=True,exist_ok=True)
        import datetime as dt
        path=root/f"M-Group_BACKUP_{dt.datetime.now().strftime('%Y%m%d_%H%M%S')}.mgroup.zip"
        create_native_backup(db,path,include_excel=True)
        return FileResponse(path,filename=path.name,media_type="application/zip")

    @r.post("/backup/restore")
    async def backup_restore(request: Request, file:UploadFile=File(...)):
        require_admin(request)
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
            return {"status":"restored","manifest":result,"pre_restore_backup":snapshot.name}
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
        if not file.filename or not file.filename.lower().endswith(".xlsx"):
            raise HTTPException(400,"invalid_excel_file")
        content = await file.read(MAX_EXCEL_UPLOAD_BYTES + 1)
        if len(content) > MAX_EXCEL_UPLOAD_BYTES:
            raise HTTPException(413,"excel_upload_too_large")
        try:
            with zipfile.ZipFile(io.BytesIO(content)) as archive:
                infos = archive.infolist()
                names = {info.filename for info in infos}
                if "[Content_Types].xml" not in names or "xl/workbook.xml" not in names:
                    raise ValueError("invalid_excel_archive")
                if len(infos) > 1000 or sum(info.file_size for info in infos) > MAX_EXCEL_EXPANDED_BYTES:
                    raise ValueError("excel_archive_too_large")
        except Exception:
            raise HTTPException(400,"invalid_excel_archive")
        root=Path(getattr(app_settings,"data_dir",Path.home()/".local/share/M-Group"))/"imports"
        root.mkdir(parents=True,exist_ok=True)
        path=root/f"import-{uuid4().hex}.xlsx"
        try:
            path.write_bytes(content)
            result=import_excel(db,path)
            return {"status":"imported","result":result}
        except Exception:
            raise HTTPException(400,"invalid_excel_archive")
        finally:
            path.unlink(missing_ok=True)
            await file.close()

    return r
