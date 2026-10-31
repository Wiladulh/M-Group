from contextlib import asynccontextmanager
import hashlib
import re
import hmac
import secrets
import json
import sqlite3
import os
import tempfile
import zipfile
import fcntl
from pathlib import Path
from io import BytesIO
from typing import Annotated
from PIL import Image, ImageOps, UnidentifiedImageError

from fastapi import Depends, FastAPI, Header, HTTPException, UploadFile, File, Response, Request
from fastapi.staticfiles import StaticFiles
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from .config import settings
from .db import connect, initialize, transaction
from .security import hash_secret, new_id, verify_secret


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Fail closed: without these secrets, admin auth is unavailable and card UID
    # hashes/device-key hashes would be stored without the configured pepper.
    if not settings.device_key_pepper:
        raise RuntimeError('MGROUP_DEVICE_KEY_PEPPER must be configured')
    initialize(settings.database_path)
    bootstrap=connect(settings.database_path)
    try:
        with transaction(bootstrap):
            if not bootstrap.execute("SELECT 1 FROM admin_users WHERE status='active' LIMIT 1").fetchone():
                username=settings.admin_username.strip().lower()
                if not re.fullmatch(r'[a-z0-9_.-]{3,64}',username) or len(settings.admin_password)<12 or len(settings.admin_password)>128:
                    raise RuntimeError('Set a valid MGROUP_ADMIN_USERNAME (3-64 letters/numbers/._-) and MGROUP_ADMIN_PASSWORD (12-128 characters) during first server installation')
                bootstrap.execute("INSERT INTO admin_users(admin_id,username,password_hash,role,status) VALUES(?,?,?,'super_admin','active')",
                                  (new_id('adm'),username,pin_hash(settings.admin_password)))
    finally:
        bootstrap.close()
    yield

app = FastAPI(title='M-Group API v2', version='2.0.0', lifespan=lifespan)


def db_conn():
    connection = connect(settings.database_path)
    try:
        yield connection
    finally:
        connection.close()

DB = Annotated[sqlite3.Connection, Depends(db_conn)]

class AdminLogin(BaseModel):
    username: str = Field(min_length=1, max_length=64)
    password: str = Field(min_length=1, max_length=128)

class AdminPasswordChange(BaseModel):
    current_password: str = Field(min_length=1, max_length=128)
    new_password: str = Field(min_length=12, max_length=128)
    confirm_password: str = Field(min_length=12, max_length=128)

class MemberCreate(BaseModel):
    display_name: str = Field(min_length=1, max_length=120)
    nik: str | None = Field(default=None, min_length=16, max_length=16, pattern=r'^[0-9]{16}$')
    phone: str | None = Field(default=None, max_length=32)
    email: str | None = Field(default=None, max_length=254)
    address: str | None = Field(default=None, max_length=300)
    birth_place: str | None = Field(default=None, max_length=100)
    birth_date: str | None = Field(default=None, max_length=10)
    sex: str | None = Field(default=None, max_length=24)
    rt: str | None = Field(default=None, max_length=8)
    rw: str | None = Field(default=None, max_length=8)
    village: str | None = Field(default=None, max_length=100)
    district: str | None = Field(default=None, max_length=100)
    city_regency: str | None = Field(default=None, max_length=100)
    province: str | None = Field(default=None, max_length=100)
    religion: str | None = Field(default=None, max_length=50)
    marital_status: str | None = Field(default=None, max_length=50)
    occupation: str | None = Field(default=None, max_length=100)
    citizenship: str | None = Field(default='WNI', max_length=32)
    registration_date: str | None = Field(default=None, max_length=10)
    status: str = Field(default='active', pattern='^(active|suspended|closed)$')
    pin: str | None = Field(default=None, min_length=6, max_length=12, pattern=r'^[0-9]{6,12}$')

class MemberUpdate(BaseModel):
    display_name: str | None = Field(default=None, min_length=1, max_length=120)
    nik: str | None = Field(default=None, min_length=16, max_length=16, pattern=r'^[0-9]{16}$')
    phone: str | None = Field(default=None, max_length=32)
    email: str | None = Field(default=None, max_length=254)
    address: str | None = Field(default=None, max_length=300)
    birth_place: str | None = Field(default=None, max_length=100)
    birth_date: str | None = Field(default=None, max_length=10)
    sex: str | None = Field(default=None, max_length=24)
    rt: str | None = Field(default=None, max_length=8)
    rw: str | None = Field(default=None, max_length=8)
    village: str | None = Field(default=None, max_length=100)
    district: str | None = Field(default=None, max_length=100)
    city_regency: str | None = Field(default=None, max_length=100)
    province: str | None = Field(default=None, max_length=100)
    religion: str | None = Field(default=None, max_length=50)
    marital_status: str | None = Field(default=None, max_length=50)
    occupation: str | None = Field(default=None, max_length=100)
    citizenship: str | None = Field(default=None, max_length=32)
    registration_date: str | None = Field(default=None, max_length=10)
    status: str | None = Field(default=None, pattern='^(active|suspended|closed)$')

class MemberPinReset(BaseModel):
    pin: str = Field(min_length=6, max_length=12, pattern=r'^[0-9]{6,12}$')
    reason: str = Field(min_length=5, max_length=200)

class TopUpRequest(BaseModel):
    request_id: str = Field(min_length=8, max_length=128)
    member_id: str = Field(min_length=1, max_length=128)
    amount_minor: int = Field(gt=0, le=100_000_000)
    description: str = Field(default='Top-up saldo', max_length=200)

class MerchantAccountCreate(BaseModel):
    label: str = Field(min_length=1, max_length=120)


class CashierDeviceConfigure(BaseModel):
    settlement_account_id: str = Field(min_length=1, max_length=128)


class CashierPaymentRequest(BaseModel):
    request_id: str = Field(min_length=8, max_length=128)
    card_uid: str = Field(min_length=4, max_length=128)
    pin: str = Field(min_length=6, max_length=12, pattern=r'^[0-9]{6,12}$')
    amount_minor: int = Field(gt=0, le=100_000_000)


class CashierTopUpRequest(BaseModel):
    request_id: str = Field(min_length=8, max_length=128)
    card_uid: str = Field(min_length=4, max_length=128)
    member_pin: str = Field(min_length=6, max_length=12, pattern=r'^[0-9]{6,12}$')
    amount_minor: int = Field(gt=0, le=100_000_000)

class CardEnroll(BaseModel):
    card_uid: str = Field(min_length=4, max_length=128)

class NfcRegistrationStart(BaseModel):
    registry_id: str = Field(min_length=1, max_length=128)
    replace_existing: bool = False

class NfcRegistrationProgress(BaseModel):
    session_id: str = Field(min_length=1, max_length=128)
    status: str = Field(pattern='^(waiting_nfc|pin_pending|processing|failed)$')

class NfcRegistrationComplete(BaseModel):
    session_id: str = Field(min_length=1, max_length=128)
    card_uid: str = Field(min_length=4, max_length=128)
    pin: str = Field(min_length=6, max_length=12, pattern=r'^[0-9]{6,12}$')


class MemberBalanceLookup(BaseModel):
    card_uid: str = Field(min_length=4, max_length=128)

class DeviceEnrollment(BaseModel):
    hardware_id: str = Field(min_length=1, max_length=128)
    mac_address: str | None = Field(default=None, max_length=32)

class DeviceProvision(BaseModel):
    device_type: str = Field(pattern='^(cashier|vending)$')
    display_name: str = Field(default='', max_length=120)


class PurchaseRequest(BaseModel):
    request_id: str = Field(min_length=8, max_length=128)
    card_uid: str = Field(min_length=4, max_length=128)
    pin: str = Field(min_length=6, max_length=12, pattern=r'^[0-9]{6,12}$')
    product_id: int = Field(ge=1, le=5)
    payment_method: str = Field(default='nfc', pattern='^(nfc|qris)$')
    expected_amount_minor: int | None = Field(default=None, gt=0, le=100_000_000)


class DispenseResult(BaseModel):
    succeeded: bool
    reason: str | None = Field(default=None, max_length=200)


class ProductUpdate(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    price_minor: int = Field(gt=0, le=100_000_000)
    stock: int = Field(ge=0, le=1_000_000)
    capacity: int | None = Field(default=None, ge=0, le=1_000_000)
    enabled: bool | None = None

@app.get('/api/v2/health')
def health():
    return {'status': 'ok', 'service': 'mgroup-api', 'version': '2.0.0'}


def pin_hash(pin: str) -> str:
    salt = secrets.token_hex(16)
    digest = hashlib.pbkdf2_hmac('sha256', pin.encode('utf-8'), salt.encode('ascii'), 310_000).hex()
    sep = chr(36)
    return sep.join(('pbkdf2_sha256', '310000', salt, digest))


def verify_pin(pin: str, encoded: str | None) -> bool:
    if not encoded:
        return False
    try:
        algorithm, rounds, salt, expected = encoded.split(chr(36), 3)
        if algorithm != 'pbkdf2_sha256' or int(rounds) != 310_000:
            return False
        actual = hashlib.pbkdf2_hmac('sha256', pin.encode('utf-8'), salt.encode('ascii'), int(rounds)).hex()
        return hmac.compare_digest(actual, expected)
    except (ValueError, TypeError):
        return False


def card_hash(card_uid: str) -> str:
    return hash_secret(card_uid.strip().upper(), settings.device_key_pepper)


def ensure_system_account(connection: sqlite3.Connection) -> str:
    row = connection.execute("SELECT account_id FROM accounts WHERE account_type='system' LIMIT 1").fetchone()
    if row:
        return row['account_id']
    account_id = new_id('acct')
    connection.execute("INSERT INTO accounts(account_id,account_type,label,balance_minor) VALUES(?,'system','System clearing',0)", (account_id,))
    return account_id


def audit(connection, action, entity_type, entity_id, request_id=None, detail=None):
    connection.execute('INSERT INTO audit_events(audit_id,actor_type,action,entity_type,entity_id,request_id,detail_json) VALUES(?,?,?,?,?,?,?)',
        (new_id('aud'), 'server', action, entity_type, entity_id, request_id, json.dumps(detail or {}, separators=(',', ':'))))


def require_admin_session(connection: DB, request: Request):
    # Admin authentication is exclusively a server-side session cookie.
    # Browser-origin checks plus SameSite=Strict protect state-changing requests.
    if request.method not in {"GET", "HEAD", "OPTIONS"}:
        origin=request.headers.get("origin")
        if origin:
            from urllib.parse import urlsplit
            parsed=urlsplit(origin)
            expected_host=request.headers.get("host","")
            forwarded_proto=request.headers.get("x-forwarded-proto","").split(",")[0].strip()
            expected_scheme=forwarded_proto or request.url.scheme
            if parsed.netloc.lower()!=expected_host.lower() or parsed.scheme.lower()!=expected_scheme.lower():
                raise HTTPException(status_code=403,detail={'code':'CROSS_ORIGIN_REQUEST_REJECTED'})
    token=request.cookies.get("m_group_admin_session","")
    if not token:
        raise HTTPException(status_code=401,detail={'code':'ADMIN_AUTH_REQUIRED'})
    digest=hash_secret(token,settings.device_key_pepper)
    row=connection.execute("""SELECT s.session_id,s.admin_id,u.username,u.status,s.expires_at
        FROM admin_sessions s JOIN admin_users u ON u.admin_id=s.admin_id
        WHERE s.token_hash=? AND s.revoked_at IS NULL AND s.expires_at>CURRENT_TIMESTAMP
        AND u.status='active'""",(digest,)).fetchone()
    if not row:
        raise HTTPException(status_code=401,detail={'code':'ADMIN_SESSION_INVALID_OR_EXPIRED'})
    connection.execute("UPDATE admin_sessions SET last_seen_at=CURRENT_TIMESTAMP WHERE session_id=?",(row['session_id'],))
    return dict(row)

def secure_admin_cookie(request: Request) -> bool:
    forwarded=request.headers.get("x-forwarded-proto","").split(",")[0].strip().lower()
    return request.url.scheme.lower()=="https" or forwarded=="https"

@app.post('/api/v2/admin/auth/login')
def admin_login(payload: AdminLogin, connection: DB, request: Request, response: Response):
    origin=request.headers.get("origin")
    if origin:
        from urllib.parse import urlsplit
        parsed=urlsplit(origin)
        expected_host=request.headers.get("host","")
        forwarded_proto=request.headers.get("x-forwarded-proto","").split(",")[0].strip()
        expected_scheme=forwarded_proto or request.url.scheme
        if parsed.netloc.lower()!=expected_host.lower() or parsed.scheme.lower()!=expected_scheme.lower():
            raise HTTPException(status_code=403,detail={'code':'CROSS_ORIGIN_REQUEST_REJECTED'})
    username=payload.username.strip().lower()
    error_status=0;token=None;user_result=None
    with transaction(connection):
        attempt=connection.execute("SELECT failed_attempts,locked_until FROM admin_login_attempts WHERE username=?",(username,)).fetchone()
        if attempt and attempt['locked_until'] and connection.execute("SELECT julianday(?)>julianday('now')",(attempt['locked_until'],)).fetchone()[0]:
            error_status=429
        else:
            user=connection.execute("SELECT admin_id,username,password_hash,status FROM admin_users WHERE username=?",(username,)).fetchone()
            valid=bool(user and user['status']=='active' and verify_pin(payload.password,user['password_hash']))
            if not valid:
                failures=(attempt['failed_attempts'] if attempt else 0)+1
                locked=failures>=5
                connection.execute("""INSERT INTO admin_login_attempts(username,failed_attempts,locked_until,updated_at)
                    VALUES(?,?,CASE WHEN ? THEN datetime('now','+15 minutes') ELSE NULL END,CURRENT_TIMESTAMP)
                    ON CONFLICT(username) DO UPDATE SET failed_attempts=excluded.failed_attempts,
                    locked_until=excluded.locked_until,updated_at=CURRENT_TIMESTAMP""",(username,failures,int(locked)))
                error_status=429 if locked else 401
            else:
                connection.execute("DELETE FROM admin_login_attempts WHERE username=?",(username,))
                token=secrets.token_urlsafe(32);session_id=new_id('ses')
                connection.execute("""INSERT INTO admin_sessions(session_id,admin_id,token_hash,expires_at)
                    VALUES(?,?,?,datetime('now','+12 hours'))""",
                    (session_id,user['admin_id'],hash_secret(token,settings.device_key_pepper)))
                connection.execute("UPDATE admin_users SET last_login_at=CURRENT_TIMESTAMP,updated_at=CURRENT_TIMESTAMP WHERE admin_id=?",(user['admin_id'],))
                audit(connection,'admin.login','admin_user',user['admin_id'],detail={'username':username})
                user_result={'admin_id':user['admin_id'],'username':user['username'],'session_id':session_id}
    if error_status:
        raise HTTPException(status_code=error_status,detail={'code':'ADMIN_LOGIN_RATE_LIMITED' if error_status==429 else 'INVALID_ADMIN_CREDENTIALS'})
    response.set_cookie(key='m_group_admin_session',value=token,httponly=True,secure=secure_admin_cookie(request),
                        samesite='strict',path='/api/v2',max_age=None)
    return {'authenticated':True,'user':user_result}

@app.get('/api/v2/admin/auth/me',dependencies=[Depends(require_admin_session)])
def admin_me(user=Depends(require_admin_session)):
    return {'admin_id':user['admin_id'],'username':user['username'],'expires_at':user.get('expires_at')}

@app.post('/api/v2/admin/auth/logout',dependencies=[Depends(require_admin_session)])
def admin_logout(connection: DB,request: Request,response: Response,user=Depends(require_admin_session)):
    if user.get('session_id'):
        with transaction(connection):
            connection.execute("UPDATE admin_sessions SET revoked_at=CURRENT_TIMESTAMP WHERE session_id=? AND revoked_at IS NULL",(user['session_id'],))
            audit(connection,'admin.logout','admin_user',user['admin_id'],detail={'session_id':user['session_id']})
    response.delete_cookie(key='m_group_admin_session',path='/api/v2',httponly=True,
                           secure=secure_admin_cookie(request),samesite='strict')
    return {'logged_out':True}

@app.post('/api/v2/admin/auth/change-password',dependencies=[Depends(require_admin_session)])
def admin_change_password(payload: AdminPasswordChange, connection: DB, user=Depends(require_admin_session)):
    if payload.new_password!=payload.confirm_password:
        raise HTTPException(status_code=422,detail={'code':'PASSWORD_CONFIRMATION_MISMATCH'})
    with transaction(connection):
        row=connection.execute("SELECT password_hash FROM admin_users WHERE admin_id=? AND status='active'",(user['admin_id'],)).fetchone()
        if not row or not verify_pin(payload.current_password,row['password_hash']):
            raise HTTPException(status_code=403,detail={'code':'CURRENT_PASSWORD_INVALID'})
        connection.execute("UPDATE admin_users SET password_hash=?,updated_at=CURRENT_TIMESTAMP WHERE admin_id=?",
                           (pin_hash(payload.new_password),user['admin_id']))
        connection.execute("UPDATE admin_sessions SET revoked_at=CURRENT_TIMESTAMP WHERE admin_id=? AND session_id<>? AND revoked_at IS NULL",
                           (user['admin_id'],user.get('session_id') or ''))
        audit(connection,'admin.password.change','admin_user',user['admin_id'])
    return {'password_changed':True,'other_sessions_revoked':True}

@app.get('/api/v2/ready')

def readiness(connection: DB):
    try:
        connection.execute('SELECT 1').fetchone()
    except sqlite3.Error as exc:
        raise HTTPException(status_code=503, detail={'code': 'DATABASE_NOT_READY'}) from exc
    return {'status': 'ready', 'database': 'ok'}

@app.post('/api/v2/admin/devices', status_code=201, dependencies=[Depends(require_admin_session)])
def register_device(payload: DeviceProvision, connection: DB):
    device_type=payload.device_type
    display_name=payload.display_name.strip() or ('Cashier' if device_type=='cashier' else 'Vending')
    registry_id=new_id('reg')
    device_key=secrets.token_urlsafe(32)
    with transaction(connection):
        connection.execute("INSERT INTO device_registry(registry_id,hardware_id,device_type,display_name,status,device_key_hash,device_key_hint) VALUES(?,NULL,?,?,'pending',?,?)",
            (registry_id,device_type,display_name,hash_secret(device_key,settings.device_key_pepper),device_key[-4:]))
        connection.execute("INSERT INTO device_events(event_id,registry_id,hardware_id,event_type,detail_json) VALUES(?, ?, NULL, ?, ?)",
            (new_id('evt'),registry_id,'device.provisioned',json.dumps({'device_type':device_type})))
        if device_type=='vending':
            for product_id in range(1,6):
                connection.execute('INSERT INTO product_slots(registry_id,product_id,name,price_minor,stock) VALUES(?,?,?,?,?)',
                    (registry_id,product_id,f'Produk {product_id}',0,0))
        audit(connection,'device.provision','device',registry_id,detail={'device_type':device_type,'hardware_id_bound':False})
    return {'registry_id':registry_id,'hardware_id':None,'device_type':device_type,'display_name':display_name,
            'device_key':device_key,'key_shown_once':True,'status':'awaiting_device_enrollment',
            'warning':'Simpan Device Key sekarang; key tidak dapat dibaca ulang.'}

@app.post('/api/v2/device/register')
def enroll_device(payload: DeviceEnrollment, connection: DB,
                  x_device_key: Annotated[str | None, Header()] = None):
    hardware_id=payload.hardware_id.strip()
    mac=(payload.mac_address or '').strip().upper() or None
    if not hardware_id:
        raise HTTPException(status_code=422,detail={'code':'HARDWARE_ID_REQUIRED'})
    if mac and (len(mac)>32 or any(ch not in '0123456789ABCDEF:' for ch in mac)):
        raise HTTPException(status_code=422,detail={'code':'INVALID_MAC_ADDRESS'})
    if not x_device_key or len(x_device_key)>256:
        raise HTTPException(status_code=401,detail={'code':'DEVICE_UNAUTHORIZED'})
    digest=hash_secret(x_device_key,settings.device_key_pepper)
    with transaction(connection):
        row=connection.execute('SELECT registry_id,hardware_id,status,device_type FROM device_registry WHERE device_key_hash=?',(digest,)).fetchone()
        if not row:
            raise HTTPException(status_code=401,detail={'code':'DEVICE_UNAUTHORIZED'})
        if row['status']=='active' and row['hardware_id']==hardware_id:
            connection.execute('UPDATE device_registry SET mac_address=COALESCE(?,mac_address),last_seen_at=CURRENT_TIMESTAMP WHERE registry_id=?',(mac,row['registry_id']))
            return {'registry_id':row['registry_id'],'hardware_id':hardware_id,'device_type':row['device_type'],'status':'active','idempotent_replay':True}
        if row['status']!='pending' or row['hardware_id'] is not None:
            raise HTTPException(status_code=409,detail={'code':'DEVICE_KEY_ALREADY_BOUND'})
        try:
            connection.execute("UPDATE device_registry SET hardware_id=?,mac_address=?,status='active',last_seen_at=CURRENT_TIMESTAMP,updated_at=CURRENT_TIMESTAMP WHERE registry_id=? AND status='pending' AND hardware_id IS NULL",(hardware_id,mac,row['registry_id']))
        except sqlite3.IntegrityError as exc:
            raise HTTPException(status_code=409,detail={'code':'HARDWARE_ID_ALREADY_REGISTERED'}) from exc
        connection.execute('INSERT INTO device_events(event_id,registry_id,hardware_id,event_type,detail_json) VALUES(?,?,?,?,?)',
            (new_id('evt'),row['registry_id'],hardware_id,'device.enrolled',json.dumps({'mac_address':mac})))
        audit(connection,'device.enroll','device',row['registry_id'],detail={'hardware_id':hardware_id,'mac_address':mac})
    return {'registry_id':row['registry_id'],'hardware_id':hardware_id,'device_type':row['device_type'],'status':'active','idempotent_replay':False}


@app.get('/api/v2/admin/devices', dependencies=[Depends(require_admin_session)])
def admin_devices(connection: DB):
    rows=connection.execute("""SELECT registry_id,hardware_id,device_type,display_name,status,mac_address,
        device_key_hint,created_at,updated_at,last_seen_at,revoked_at FROM device_registry
        ORDER BY created_at DESC""").fetchall()
    return {'items':[dict(row) for row in rows]}

@app.post('/api/v2/admin/devices/{registry_id}/rotate-key', dependencies=[Depends(require_admin_session)])
def rotate_device_key(registry_id: str, connection: DB):
    key=secrets.token_urlsafe(32)
    with transaction(connection):
        row=connection.execute("SELECT registry_id,status FROM device_registry WHERE registry_id=?",(registry_id,)).fetchone()
        if not row:
            raise HTTPException(status_code=404,detail={'code':'DEVICE_NOT_FOUND'})
        if row['status'] in ('disabled','revoked'):
            raise HTTPException(status_code=409,detail={'code':'DEVICE_NOT_ACTIVE'})
        connection.execute("UPDATE device_registry SET device_key_hash=?,device_key_hint=?,updated_at=CURRENT_TIMESTAMP WHERE registry_id=?",
            (hash_secret(key,settings.device_key_pepper),key[-4:],registry_id))
        audit(connection,'device.key.rotate','device',registry_id,detail={'key_shown_once':True})
    return {'registry_id':registry_id,'device_key':key,'key_shown_once':True,'status':'rotated'}

@app.post('/api/v2/admin/devices/{registry_id}/replace-hardware', dependencies=[Depends(require_admin_session)])
def replace_device_hardware(registry_id: str, connection: DB):
    """Authorize a replacement ESP32 while preserving the server-issued logical registry ID."""
    key=secrets.token_urlsafe(32)
    with transaction(connection):
        row=connection.execute(
            "SELECT registry_id,hardware_id,status FROM device_registry WHERE registry_id=?",
            (registry_id,),
        ).fetchone()
        if not row:
            raise HTTPException(status_code=404,detail={'code':'DEVICE_NOT_FOUND'})
        if row['status'] in ('disabled','revoked'):
            raise HTTPException(status_code=409,detail={'code':'DEVICE_NOT_ACTIVE'})
        previous_hardware_id=row['hardware_id']
        if previous_hardware_id:
            pending=connection.execute(
                """SELECT COUNT(*) AS count FROM transactions
                   WHERE hardware_id=? AND transaction_type='purchase' AND status='pending'""",
                (previous_hardware_id,),
            ).fetchone()
            if pending and pending['count']:
                raise HTTPException(status_code=409,detail={'code':'DEVICE_HAS_PENDING_TRANSACTIONS',
                    'message':'Reconcile pending vending dispense transactions before replacing this board.'})
        connection.execute(
            """UPDATE device_registry
               SET hardware_id=NULL,mac_address=NULL,status='pending',
                   device_key_hash=?,device_key_hint=?,revoked_at=NULL,updated_at=CURRENT_TIMESTAMP
               WHERE registry_id=?""",
            (hash_secret(key,settings.device_key_pepper),key[-4:],registry_id),
        )
        connection.execute(
            'INSERT INTO device_events(event_id,registry_id,hardware_id,event_type,detail_json) VALUES(?,?,?,?,?)',
            (new_id('evt'),registry_id,previous_hardware_id,'device.hardware.replacement_authorized',
             json.dumps({'previous_hardware_id':previous_hardware_id,'key_shown_once':True})),
        )
        connection.execute(
            """UPDATE nfc_registration_sessions SET status='failed',error_code='CASHIER_HARDWARE_REPLACED'
               WHERE registry_id=? AND status IN ('scan_pending','waiting_nfc','pin_pending','processing')""",
            (registry_id,),
        )
        audit(connection,'device.hardware.replace','device',registry_id,
              detail={'previous_hardware_id':previous_hardware_id,'registry_id_preserved':True})
    return {
        'registry_id':registry_id,'device_key':key,'key_shown_once':True,
        'status':'awaiting_device_enrollment',
        'previous_hardware_id':previous_hardware_id,
        'message':'Masukkan Device Key baru ke hardware pengganti. Registry ID dan konfigurasi slot tetap dipertahankan.',
    }


@app.post('/api/v2/admin/devices/{registry_id}/revoke', dependencies=[Depends(require_admin_session)])
def revoke_device_key(registry_id: str, connection: DB):
    with transaction(connection):
        row=connection.execute("SELECT registry_id,hardware_id,status FROM device_registry WHERE registry_id=?",(registry_id,)).fetchone()
        if not row:
            raise HTTPException(status_code=404,detail={'code':'DEVICE_NOT_FOUND'})
        if row['hardware_id']:
            pending=connection.execute(
                """SELECT COUNT(*) AS count FROM transactions
                   WHERE hardware_id=? AND transaction_type='purchase' AND status='pending'""",
                (row['hardware_id'],),
            ).fetchone()
            if pending and pending['count']:
                raise HTTPException(status_code=409,detail={'code':'DEVICE_HAS_PENDING_TRANSACTIONS',
                    'message':'Reconcile pending vending dispense transactions before revoking this device.'})
        connection.execute('INSERT INTO device_events(event_id,registry_id,hardware_id,event_type,detail_json) VALUES(?,?,?,?,?)',
            (new_id('evt'),registry_id,row['hardware_id'],'device.revoked',json.dumps({'previous_status':row['status']})))
        connection.execute("UPDATE device_registry SET hardware_id=NULL,status='revoked',device_key_hash=NULL,device_key_hint=NULL,revoked_at=CURRENT_TIMESTAMP,updated_at=CURRENT_TIMESTAMP WHERE registry_id=?",(registry_id,))
        connection.execute("UPDATE nfc_registration_sessions SET status='failed',error_code='CASHIER_REVOKED' WHERE registry_id=? AND status IN ('scan_pending','waiting_nfc','pin_pending','processing')",(registry_id,))
        audit(connection,'device.key.revoke','device',registry_id,detail={'previous_hardware_id':row['hardware_id']})
    return {'registry_id':registry_id,'status':'revoked'}

def authenticated_device(connection: sqlite3.Connection, device_key: str | None):
    if not device_key or len(device_key) > 256:
        raise HTTPException(status_code=401, detail={'code': 'DEVICE_UNAUTHORIZED'})
    rows = connection.execute("SELECT registry_id,hardware_id,device_type,status,device_key_hash FROM device_registry WHERE status='active'").fetchall()
    for row in rows:
        if row['device_key_hash'] and verify_secret(device_key, row['device_key_hash'], settings.device_key_pepper):
            connection.execute('UPDATE device_registry SET last_seen_at=CURRENT_TIMESTAMP WHERE registry_id=?', (row['registry_id'],))
            return row
    raise HTTPException(status_code=401, detail={'code': 'DEVICE_UNAUTHORIZED'})

@app.get('/api/v2/device/me')
def device_me(connection: DB, x_device_key: Annotated[str | None, Header()] = None):
    device = authenticated_device(connection, x_device_key)
    return {'registry_id': device['registry_id'], 'hardware_id': device['hardware_id'], 'device_type': device['device_type']}

@app.get('/api/v2/device/products')
def device_products(connection: DB, x_device_key: Annotated[str | None, Header()] = None):
    device = authenticated_device(connection, x_device_key)
    if device['device_type'] != 'vending':
        raise HTTPException(status_code=403, detail={'code': 'VENDING_DEVICE_REQUIRED'})
    rows = connection.execute(
        """SELECT p.product_id,p.name,p.price_minor,p.stock,p.capacity,p.enabled,i.sha256 AS image_sha256
           FROM product_slots p LEFT JOIN product_images i
             ON i.registry_id=p.registry_id AND i.product_id=p.product_id
           WHERE p.registry_id=? ORDER BY p.product_id""",
        (device['registry_id'],),
    ).fetchall()
    items=[]
    for row in rows:
        item=dict(row)
        item['image_url']=f"/api/v2/device/products/{item['product_id']}/image" if item.get('image_sha256') else None
        items.append(item)
    return {'registry_id': device['registry_id'], 'items': items}



@app.get('/api/v2/device/products/{product_id}/image')
def device_product_image(product_id: int, connection: DB,
                         x_device_key: Annotated[str | None, Header()] = None):
    """Serve a product thumbnail only to the authenticated vending registry."""
    device=authenticated_device(connection,x_device_key)
    if device['device_type']!='vending':
        raise HTTPException(status_code=403,detail={'code':'VENDING_DEVICE_REQUIRED'})
    if product_id not in range(1,6):
        raise HTTPException(status_code=404,detail={'code':'PRODUCT_IMAGE_NOT_FOUND'})
    row=connection.execute(
        "SELECT image_data,sha256,content_type FROM product_images WHERE registry_id=? AND product_id=?",
        (device['registry_id'],product_id)
    ).fetchone()
    if not row:
        raise HTTPException(status_code=404,detail={'code':'PRODUCT_IMAGE_NOT_FOUND'})
    return Response(content=bytes(row['image_data']),media_type=row['content_type'],
                    headers={'ETag':'"'+row['sha256']+'"' ,'Cache-Control':'private, max-age=300'})


@app.post('/api/v2/devices/member-balance')
def device_member_balance(payload: MemberBalanceLookup, connection: DB,
                          x_device_key: Annotated[str | None, Header()] = None):
    device = authenticated_device(connection, x_device_key)
    if device['device_type'] not in ('cashier', 'vending'):
        raise HTTPException(status_code=403, detail={'code': 'DEVICE_TYPE_NOT_ALLOWED'})
    row = connection.execute("""
        SELECT m.member_id, m.display_name, m.status AS member_status,
               a.balance_minor, a.currency, a.status AS account_status,a.updated_at AS balance_version
        FROM member_cards c
        JOIN members m ON m.member_id=c.member_id
        JOIN accounts a ON a.member_id=m.member_id AND a.account_type='member'
        WHERE c.card_uid_hash=? AND c.status='active'
    """, (card_hash(payload.card_uid),)).fetchone()
    if not row or row['member_status'] != 'active' or row['account_status'] != 'active':
        raise HTTPException(status_code=401, detail={'code': 'CARD_NOT_AUTHORIZED'})
    return {'member_id': row['member_id'], 'display_name': row['display_name'],
            'member_status': row['member_status'], 'account_status': row['account_status'], 'card_status': 'active',
            'balance_minor': row['balance_minor'], 'currency': row['currency'],
            'balance_version': row['balance_version']}


@app.post('/api/v2/members', status_code=201, dependencies=[Depends(require_admin_session)])
def create_member(payload: MemberCreate, connection: DB):
    display_name = payload.display_name.strip()
    if not display_name:
        raise HTTPException(status_code=422, detail={'code': 'INVALID_DISPLAY_NAME'})
    account_id = new_id('acct')
    try:
        with transaction(connection):
            ids = connection.execute("SELECT member_id FROM members WHERE member_id GLOB 'UID-[0-9]*'").fetchall()
            largest = max((int(row['member_id'][4:]) for row in ids if row['member_id'][4:].isdigit()), default=0)
            member_id = f'UID-{largest + 1:05d}'
            profile = payload.model_dump(exclude={'display_name','nik','phone','email','pin','status'}, exclude_none=True)
            connection.execute('INSERT INTO members(member_id,display_name,nik,phone,email,profile_json,status,pin_hash) VALUES(?,?,?,?,?,?,?,?)',
                (member_id, display_name, payload.nik, payload.phone, payload.email,
                 json.dumps(profile, separators=(',', ':')),payload.status,pin_hash(payload.pin) if payload.pin else None))
            connection.execute("INSERT INTO accounts(account_id,member_id,account_type) VALUES(?,?,'member')", (account_id, member_id))
            audit(connection, 'member.create', 'member', member_id, detail={'nik_present': bool(payload.nik)})
    except sqlite3.IntegrityError as exc:
        raise HTTPException(status_code=409, detail={'code': 'MEMBER_CREATE_CONFLICT'}) from exc
    return {'member_id': member_id, 'display_name': display_name, 'account_id': account_id,
            'nik': payload.nik, 'phone': payload.phone, 'email': payload.email,
            'balance_minor': 0, 'status': payload.status, 'pin_configured': bool(payload.pin)}

@app.get('/api/v2/members', dependencies=[Depends(require_admin_session)])
def list_members(connection: DB):
    rows = connection.execute("SELECT m.member_id,m.display_name,m.nik,m.phone,m.email,m.profile_json,m.status,a.account_id,a.balance_minor,(SELECT COUNT(*) FROM member_cards c WHERE c.member_id=m.member_id AND c.status='active') AS active_cards FROM members m JOIN accounts a ON a.member_id=m.member_id ORDER BY m.created_at DESC").fetchall()
    items=[]
    for row in rows:
        item=dict(row)
        profile=json.loads(item.pop('profile_json') or '{}')
        item.update(profile)
        items.append(item)
    return {'items': items}

@app.patch('/api/v2/admin/members/{member_id}', dependencies=[Depends(require_admin_session)])
def update_member(member_id: str, payload: MemberUpdate, connection: DB):
    fields=payload.model_dump(exclude_unset=True)
    if not fields:
        raise HTTPException(status_code=422,detail={'code':'NO_MEMBER_FIELDS'})
    with transaction(connection):
        current=connection.execute("SELECT member_id,display_name,nik,phone,email,profile_json,status FROM members WHERE member_id=?",(member_id,)).fetchone()
        if not current:
            raise HTTPException(status_code=404,detail={'code':'MEMBER_NOT_FOUND'})
        profile=json.loads(current['profile_json'] or '{}')
        for key in ('address','birth_place','birth_date','sex','rt','rw','village','district','city_regency','province','religion','marital_status','occupation','citizenship','registration_date'):
            if key in fields: profile[key]=fields.pop(key)
        if 'display_name' in fields and fields['display_name'] is not None: fields['display_name']=fields['display_name'].strip()
        fields['profile_json']=json.dumps(profile,separators=(',',':'))
        sets=','.join(f"{key}=?" for key in fields)
        values=list(fields.values())+[member_id]
        connection.execute(f"UPDATE members SET {sets},updated_at=CURRENT_TIMESTAMP WHERE member_id=?",values)
        audit(connection,'member.update','member',member_id,detail={'fields':sorted(payload.model_fields_set)})
    return {'member_id':member_id,'status':'updated'}

@app.post('/api/v2/admin/members/{member_id}/reset-pin', dependencies=[Depends(require_admin_session)])
def reset_member_pin(member_id: str, payload: MemberPinReset, connection: DB):
    with transaction(connection):
        row=connection.execute("SELECT status FROM members WHERE member_id=?",(member_id,)).fetchone()
        if not row:
            raise HTTPException(status_code=404,detail={'code':'MEMBER_NOT_FOUND'})
        connection.execute("UPDATE members SET pin_hash=?,updated_at=CURRENT_TIMESTAMP WHERE member_id=?",
                           (pin_hash(payload.pin),member_id))
        audit(connection,'member.pin.reset','member',member_id,detail={'reason':payload.reason})
    return {'member_id':member_id,'pin_configured':True}

@app.get('/api/v2/admin/members/{member_id}/cards', dependencies=[Depends(require_admin_session)])
def list_member_cards(member_id: str, connection: DB):
    if not connection.execute("SELECT 1 FROM members WHERE member_id=?",(member_id,)).fetchone():
        raise HTTPException(status_code=404,detail={'code':'MEMBER_NOT_FOUND'})
    rows=connection.execute("SELECT card_id,status,substr(card_uid_hash,1,8) AS card_fingerprint,created_at FROM member_cards WHERE member_id=? ORDER BY created_at DESC",(member_id,)).fetchall()
    return {'items':[dict(row) for row in rows]}

@app.post('/api/v2/admin/members/{member_id}/cards/{card_id}/revoke', dependencies=[Depends(require_admin_session)])
def revoke_member_card(member_id: str, card_id: str, connection: DB):
    with transaction(connection):
        row=connection.execute("SELECT card_id,status FROM member_cards WHERE card_id=? AND member_id=?",(card_id,member_id)).fetchone()
        if not row:
            raise HTTPException(status_code=404,detail={'code':'CARD_NOT_FOUND'})
        connection.execute("UPDATE member_cards SET status='revoked' WHERE card_id=?",(card_id,))
        audit(connection,'member.card.revoke','member',member_id,detail={'card_id':card_id})
    return {'member_id':member_id,'card_id':card_id,'status':'revoked'}

@app.post('/api/v2/finance/top-ups', dependencies=[Depends(require_admin_session)])
def top_up(payload: TopUpRequest, connection: DB):
    transaction_id = new_id('txn')
    try:
        with transaction(connection):
            prior = connection.execute("SELECT transaction_id,status,member_id,amount_minor,transaction_type,metadata_json FROM transactions WHERE request_id=?", (payload.request_id,)).fetchone()
            if prior:
                prior_metadata = json.loads(prior['metadata_json'] or '{}')
                if (prior['member_id'] != payload.member_id or prior['amount_minor'] != payload.amount_minor
                    or prior['transaction_type'] != 'top_up' or prior['status'] != 'succeeded'
                    or prior_metadata.get('source') == 'cashier'):
                    raise HTTPException(status_code=409, detail={'code': 'IDEMPOTENCY_CONFLICT'})
                return {'transaction_id': prior['transaction_id'], 'status': prior['status'], 'idempotent_replay': True}
            account = connection.execute("SELECT account_id,balance_minor,status FROM accounts WHERE member_id=? AND account_type='member'", (payload.member_id,)).fetchone()
            if not account:
                raise HTTPException(status_code=404, detail={'code': 'MEMBER_ACCOUNT_NOT_FOUND'})
            if account['status'] != 'active':
                raise HTTPException(status_code=409, detail={'code': 'ACCOUNT_NOT_ACTIVE'})
            system_account_id = ensure_system_account(connection)
            connection.execute("INSERT INTO transactions(transaction_id,request_id,member_id,transaction_type,amount_minor,status,metadata_json,completed_at) VALUES(?,?,?,'top_up',?,'succeeded',?,CURRENT_TIMESTAMP)", (transaction_id, payload.request_id, payload.member_id, payload.amount_minor, json.dumps({'description': payload.description})))
            connection.execute('UPDATE accounts SET balance_minor=balance_minor+?,updated_at=CURRENT_TIMESTAMP WHERE account_id=?', (payload.amount_minor, account['account_id']))
            connection.execute('UPDATE accounts SET balance_minor=balance_minor+?,updated_at=CURRENT_TIMESTAMP WHERE account_id=?', (payload.amount_minor, system_account_id))
            connection.execute("INSERT INTO ledger_entries(entry_id,transaction_id,account_id,direction,amount_minor) VALUES(?,?,?,'credit',?)", (new_id('led'), transaction_id, account['account_id'], payload.amount_minor))
            connection.execute("INSERT INTO ledger_entries(entry_id,transaction_id,account_id,direction,amount_minor) VALUES(?,?,?,'debit',?)", (new_id('led'), transaction_id, system_account_id, payload.amount_minor))
            audit(connection, 'finance.top_up', 'transaction', transaction_id, payload.request_id, {'member_id': payload.member_id, 'amount_minor': payload.amount_minor})
    except sqlite3.IntegrityError as exc:
        raise HTTPException(status_code=409, detail={'code': 'IDEMPOTENCY_CONFLICT'}) from exc
    return {'transaction_id': transaction_id, 'status': 'succeeded', 'idempotent_replay': False}


@app.post('/api/v2/admin/merchant-accounts', status_code=201, dependencies=[Depends(require_admin_session)])
def create_merchant_account(payload: MerchantAccountCreate, connection: DB):
    label = payload.label.strip()
    if not label:
        raise HTTPException(status_code=422, detail={'code': 'INVALID_MERCHANT_LABEL'})
    account_id = new_id('merchant')
    with transaction(connection):
        connection.execute("INSERT INTO accounts(account_id,account_type,label,balance_minor) VALUES(?,'merchant',?,0)",
                           (account_id,label))
        audit(connection, 'merchant.account.create', 'account', account_id, detail={'label': label})
    return {'account_id': account_id, 'label': label, 'account_type': 'merchant', 'currency': 'IDR', 'balance_minor': 0}


@app.put('/api/v2/admin/cashier-devices/{registry_id}/configuration', dependencies=[Depends(require_admin_session)])
def configure_cashier_device(registry_id: str, payload: CashierDeviceConfigure, connection: DB):
    with transaction(connection):
        device=connection.execute("SELECT registry_id,status FROM device_registry WHERE registry_id=? AND device_type='cashier'",(registry_id,)).fetchone()
        if not device: raise HTTPException(status_code=404,detail={'code':'CASHIER_DEVICE_NOT_FOUND'})
        if device['status']!='active': raise HTTPException(status_code=409,detail={'code':'CASHIER_DEVICE_NOT_ACTIVE'})
        settlement=connection.execute("SELECT account_id,status FROM accounts WHERE account_id=? AND account_type='merchant'",(payload.settlement_account_id,)).fetchone()
        if not settlement: raise HTTPException(status_code=422,detail={'code':'MERCHANT_SETTLEMENT_ACCOUNT_REQUIRED'})
        if settlement['status']!='active': raise HTTPException(status_code=409,detail={'code':'SETTLEMENT_ACCOUNT_NOT_ACTIVE'})
        connection.execute("""INSERT INTO cashier_device_config(registry_id,settlement_account_id,updated_at)
            VALUES(?,?,CURRENT_TIMESTAMP)
            ON CONFLICT(registry_id) DO UPDATE SET settlement_account_id=excluded.settlement_account_id,updated_at=CURRENT_TIMESTAMP""",
            (registry_id,settlement['account_id']))
        audit(connection,'cashier.device.configure','device',registry_id,detail={'settlement_account_id':settlement['account_id']})
    return {'registry_id':registry_id,'settlement_account_id':settlement['account_id'],'status':'configured'}


def _cashier_member_with_valid_pin(connection: sqlite3.Connection, device, card_uid: str, pin: str):
    digest = card_hash(card_uid)
    error = None
    member = None
    with transaction(connection):
        member = connection.execute("""
            SELECT m.member_id,m.status AS member_status,m.pin_hash,
                   a.account_id,a.balance_minor,a.status AS account_status,a.currency
            FROM member_cards c
            JOIN members m ON m.member_id=c.member_id
            JOIN accounts a ON a.member_id=m.member_id AND a.account_type='member'
            WHERE c.card_uid_hash=? AND c.status='active'
        """, (digest,)).fetchone()
        if not member or member['member_status'] != 'active' or member['account_status'] != 'active':
            error = (401, 'CARD_NOT_AUTHORIZED')
        else:
            attempt = connection.execute(
                'SELECT failed_attempts,locked_until FROM pin_attempts WHERE card_hash=? AND hardware_id=?',
                (digest, device['hardware_id'])).fetchone()
            card_attempt = connection.execute(
                'SELECT failed_attempts,locked_until FROM pin_card_attempts WHERE card_hash=?',
                (digest,)).fetchone()
            locked = connection.execute(
                "SELECT CASE WHEN (? IS NOT NULL AND julianday(?) > julianday('now')) OR (? IS NOT NULL AND julianday(?) > julianday('now')) THEN 1 ELSE 0 END",
                (attempt['locked_until'] if attempt else None, attempt['locked_until'] if attempt else None,
                 card_attempt['locked_until'] if card_attempt else None, card_attempt['locked_until'] if card_attempt else None)).fetchone()[0]
            if locked:
                error = (429, 'PIN_TEMPORARILY_LOCKED')
            elif not verify_pin(pin, member['pin_hash']):
                device_failures = (attempt['failed_attempts'] if attempt else 0) + 1
                card_failures = (card_attempt['failed_attempts'] if card_attempt else 0) + 1
                device_lock = device_failures >= 5
                card_lock = card_failures >= 5
                connection.execute(
                    "INSERT INTO pin_attempts(card_hash,hardware_id,failed_attempts,locked_until,updated_at) VALUES(?,?,?,CASE WHEN ? THEN datetime('now','+5 minutes') ELSE NULL END,CURRENT_TIMESTAMP) ON CONFLICT(card_hash,hardware_id) DO UPDATE SET failed_attempts=excluded.failed_attempts,locked_until=excluded.locked_until,updated_at=CURRENT_TIMESTAMP",
                    (digest, device['hardware_id'], device_failures, int(device_lock)))
                connection.execute(
                    "INSERT INTO pin_card_attempts(card_hash,failed_attempts,locked_until,updated_at) VALUES(?,?,CASE WHEN ? THEN datetime('now','+5 minutes') ELSE NULL END,CURRENT_TIMESTAMP) ON CONFLICT(card_hash) DO UPDATE SET failed_attempts=excluded.failed_attempts,locked_until=excluded.locked_until,updated_at=CURRENT_TIMESTAMP",
                    (digest, card_failures, int(card_lock)))
                error = (429, 'PIN_TEMPORARILY_LOCKED') if card_lock or device_lock else (401, 'INVALID_PIN')
            else:
                connection.execute('DELETE FROM pin_attempts WHERE card_hash=? AND hardware_id=?',
                                   (digest, device['hardware_id']))
                connection.execute('DELETE FROM pin_card_attempts WHERE card_hash=?', (digest,))
    if error:
        raise HTTPException(status_code=error[0], detail={'code': error[1]})
    return digest, member


def _cashier_settlement_config(connection: sqlite3.Connection, device):
    config=connection.execute("SELECT settlement_account_id FROM cashier_device_config WHERE registry_id=?",(device['registry_id'],)).fetchone()
    if not config:
        raise HTTPException(status_code=409, detail={'code':'CASHIER_NOT_CONFIGURED'})
    return config


@app.post('/api/v2/cashier/payments', status_code=201)
def cashier_payment_v2(payload: CashierPaymentRequest, connection: DB,
                       x_device_key: Annotated[str | None, Header()] = None):
    device = authenticated_device(connection, x_device_key)
    if device['device_type'] != 'cashier':
        raise HTTPException(status_code=403, detail={'code': 'CASHIER_DEVICE_REQUIRED'})
    digest, member = _cashier_member_with_valid_pin(connection, device, payload.card_uid, payload.pin)
    config = _cashier_settlement_config(connection, device)
    transaction_id = new_id('txn')
    try:
        with transaction(connection):
            prior = connection.execute(
                'SELECT transaction_id,member_id,amount_minor,transaction_type,hardware_id,status,metadata_json FROM transactions WHERE request_id=?',
                (payload.request_id,)).fetchone()
            if prior:
                meta = json.loads(prior['metadata_json'] or '{}')
                if (prior['transaction_type'] != 'cashier_payment' or prior['hardware_id'] != device['hardware_id']
                    or prior['member_id'] != member['member_id'] or prior['amount_minor'] != payload.amount_minor
                    or meta.get('card_hash') != digest or meta.get('settlement_account_id') != config['settlement_account_id']
                    or prior['status'] != 'succeeded'):
                    raise HTTPException(status_code=409, detail={'code': 'IDEMPOTENCY_CONFLICT'})
                current = connection.execute("SELECT balance_minor,updated_at FROM accounts WHERE member_id=? AND account_type='member'",(prior['member_id'],)).fetchone()
                return {'transaction_id': prior['transaction_id'], 'request_id': payload.request_id,
                        'member_id': prior['member_id'], 'status': prior['status'], 'amount_minor': prior['amount_minor'],
                        'balance_after_minor': current['balance_minor'] if current else None,
                        'balance_version': current['updated_at'] if current else None,'idempotent_replay': True}
            account = connection.execute(
                "SELECT account_id,balance_minor,status,currency FROM accounts WHERE member_id=? AND account_type='member'",
                (member['member_id'],)).fetchone()
            settlement = connection.execute(
                "SELECT account_id,balance_minor,status,currency FROM accounts WHERE account_id=? AND account_type='merchant'",
                (config['settlement_account_id'],)).fetchone()
            if not account or account['status'] != 'active':
                raise HTTPException(status_code=409, detail={'code': 'ACCOUNT_NOT_ACTIVE'})
            if not settlement or settlement['status'] != 'active':
                raise HTTPException(status_code=409, detail={'code': 'SETTLEMENT_ACCOUNT_NOT_ACTIVE'})
            if account['currency'] != settlement['currency']:
                raise HTTPException(status_code=409, detail={'code': 'CURRENCY_MISMATCH'})
            if account['balance_minor'] < payload.amount_minor:
                raise HTTPException(status_code=409, detail={'code': 'INSUFFICIENT_BALANCE'})
            connection.execute("""
                INSERT INTO transactions(transaction_id,request_id,hardware_id,member_id,transaction_type,
                    amount_minor,currency,status,metadata_json,completed_at)
                VALUES(?,?,?,?,?,?,?,'succeeded',?,CURRENT_TIMESTAMP)
            """, (transaction_id, payload.request_id, device['hardware_id'], member['member_id'],
                  'cashier_payment', payload.amount_minor, account['currency'],
                  json.dumps({'card_hash': digest, 'settlement_account_id': settlement['account_id'],
                              'source': 'cashier'}, separators=(',', ':'))))
            debit = connection.execute(
                "UPDATE accounts SET balance_minor=balance_minor-?,updated_at=CURRENT_TIMESTAMP WHERE account_id=? AND status='active' AND balance_minor>=?",
                (payload.amount_minor, account['account_id'], payload.amount_minor))
            if debit.rowcount != 1:
                raise HTTPException(status_code=409, detail={'code': 'INSUFFICIENT_BALANCE'})
            connection.execute('UPDATE accounts SET balance_minor=balance_minor+?,updated_at=CURRENT_TIMESTAMP WHERE account_id=?',
                               (payload.amount_minor, settlement['account_id']))
            connection.execute("INSERT INTO ledger_entries(entry_id,transaction_id,account_id,direction,amount_minor) VALUES(?,?,?,'debit',?)",
                               (new_id('led'), transaction_id, account['account_id'], payload.amount_minor))
            connection.execute("INSERT INTO ledger_entries(entry_id,transaction_id,account_id,direction,amount_minor) VALUES(?,?,?,'credit',?)",
                               (new_id('led'), transaction_id, settlement['account_id'], payload.amount_minor))
            audit(connection, 'cashier.payment', 'transaction', transaction_id, payload.request_id,
                  {'hardware_id': device['hardware_id'],
                   'settlement_account_id': settlement['account_id'], 'amount_minor': payload.amount_minor})
            balance_after = account['balance_minor'] - payload.amount_minor
    except sqlite3.IntegrityError as exc:
        raise HTTPException(status_code=409, detail={'code': 'IDEMPOTENCY_CONFLICT'}) from exc
    return {'transaction_id': transaction_id, 'request_id': payload.request_id, 'member_id': member['member_id'], 'status': 'succeeded',
            'amount_minor': payload.amount_minor, 'balance_after_minor': balance_after,
            'balance_version': connection.execute("SELECT updated_at FROM accounts WHERE member_id=? AND account_type='member'",(member['member_id'],)).fetchone()['updated_at'], 'idempotent_replay': False}


@app.post('/api/v2/cashier/top-ups', status_code=201)
def cashier_top_up_v2(payload: CashierTopUpRequest, connection: DB,
                      x_device_key: Annotated[str | None, Header()] = None):
    device = authenticated_device(connection, x_device_key)
    if device['device_type'] != 'cashier':
        raise HTTPException(status_code=403, detail={'code': 'CASHIER_DEVICE_REQUIRED'})
    config = _cashier_settlement_config(connection, device)
    digest, member = _cashier_member_with_valid_pin(connection, device, payload.card_uid, payload.member_pin)
    transaction_id = new_id('txn')
    try:
        with transaction(connection):
            prior = connection.execute(
                'SELECT transaction_id,member_id,amount_minor,transaction_type,hardware_id,status,metadata_json FROM transactions WHERE request_id=?',
                (payload.request_id,)).fetchone()
            if prior:
                meta = json.loads(prior['metadata_json'] or '{}')
                if (prior['transaction_type'] != 'top_up' or prior['hardware_id'] != device['hardware_id']
                    or prior['member_id'] != member['member_id'] or prior['amount_minor'] != payload.amount_minor
                    or meta.get('source') != 'cashier' or meta.get('card_hash') != digest
                    or prior['status'] != 'succeeded'):
                    raise HTTPException(status_code=409, detail={'code': 'IDEMPOTENCY_CONFLICT'})
                current = connection.execute("SELECT balance_minor,updated_at FROM accounts WHERE member_id=? AND account_type='member'",(prior['member_id'],)).fetchone()
                return {'transaction_id': prior['transaction_id'], 'request_id': payload.request_id,
                        'member_id': prior['member_id'], 'status': prior['status'], 'amount_minor': prior['amount_minor'],
                        'balance_after_minor': current['balance_minor'] if current else None,
                        'balance_version': current['updated_at'] if current else None,'idempotent_replay': True}
            account = connection.execute(
                "SELECT account_id,balance_minor,status,currency FROM accounts WHERE member_id=? AND account_type='member'",
                (member['member_id'],)).fetchone()
            if not account or account['status'] != 'active':
                raise HTTPException(status_code=409, detail={'code': 'ACCOUNT_NOT_ACTIVE'})
            system_id = ensure_system_account(connection)
            system = connection.execute("SELECT account_id,balance_minor,status,currency FROM accounts WHERE account_id=?",
                                        (system_id,)).fetchone()
            if system['status'] != 'active' or system['currency'] != account['currency']:
                raise HTTPException(status_code=409, detail={'code': 'SYSTEM_ACCOUNT_NOT_ACTIVE'})
            connection.execute("""
                INSERT INTO transactions(transaction_id,request_id,hardware_id,member_id,transaction_type,
                    amount_minor,currency,status,metadata_json,completed_at)
                VALUES(?,?,?,?,?,?,?,'succeeded',?,CURRENT_TIMESTAMP)
            """, (transaction_id, payload.request_id, device['hardware_id'], member['member_id'],
                  'top_up', payload.amount_minor, account['currency'],
                  json.dumps({'card_hash': digest, 'source': 'cashier'}, separators=(',', ':'))))
            connection.execute('UPDATE accounts SET balance_minor=balance_minor+?,updated_at=CURRENT_TIMESTAMP WHERE account_id=?',
                               (payload.amount_minor, account['account_id']))
            connection.execute('UPDATE accounts SET balance_minor=balance_minor+?,updated_at=CURRENT_TIMESTAMP WHERE account_id=?',
                               (payload.amount_minor, system_id))
            connection.execute("INSERT INTO ledger_entries(entry_id,transaction_id,account_id,direction,amount_minor) VALUES(?,?,?,'credit',?)",
                               (new_id('led'), transaction_id, account['account_id'], payload.amount_minor))
            connection.execute("INSERT INTO ledger_entries(entry_id,transaction_id,account_id,direction,amount_minor) VALUES(?,?,?,'debit',?)",
                               (new_id('led'), transaction_id, system_id, payload.amount_minor))
            audit(connection, 'cashier.top_up', 'transaction', transaction_id, payload.request_id,
                  {'hardware_id': device['hardware_id'], 'amount_minor': payload.amount_minor})
            balance_after = account['balance_minor'] + payload.amount_minor
    except sqlite3.IntegrityError as exc:
        raise HTTPException(status_code=409, detail={'code': 'IDEMPOTENCY_CONFLICT'}) from exc
    return {'transaction_id': transaction_id, 'request_id': payload.request_id, 'status': 'succeeded',
            'amount_minor': payload.amount_minor, 'balance_after_minor': balance_after, 'idempotent_replay': False}


@app.get('/api/v2/vending/devices', dependencies=[Depends(require_admin_session)])
def vending_devices(connection: DB):
    rows = connection.execute("SELECT registry_id,hardware_id,display_name,status,mac_address,last_seen_at FROM device_registry WHERE device_type='vending' ORDER BY created_at DESC").fetchall()
    return {'items': [dict(row) for row in rows]}

@app.get('/api/v2/vending/devices/{registry_id}/products', dependencies=[Depends(require_admin_session)])
def get_products(registry_id: str, connection: DB):
    device = connection.execute("SELECT registry_id FROM device_registry WHERE registry_id=? AND device_type='vending'", (registry_id,)).fetchone()
    if not device:
        raise HTTPException(status_code=404, detail={'code': 'VENDING_DEVICE_NOT_FOUND'})
    rows = connection.execute("""SELECT p.product_id,p.name,p.price_minor,p.stock,p.capacity,p.enabled,p.nfc_promo_percent,p.qris_promo_percent,
        i.sha256 AS image_sha256,i.byte_size AS image_size,i.content_type
        FROM product_slots p LEFT JOIN product_images i ON i.registry_id=p.registry_id AND i.product_id=p.product_id
        WHERE p.registry_id=? ORDER BY p.product_id""", (registry_id,)).fetchall()
    items=[]
    for row in rows:
        item=dict(row)
        item['image_url']=f"/api/v2/device/products/{item['product_id']}/image" if item.get('image_sha256') else None
        items.append(item)
    return {'registry_id': registry_id, 'items': items}

@app.put('/api/v2/vending/devices/{registry_id}/products/{product_id}', dependencies=[Depends(require_admin_session)])
def update_product(registry_id: str, product_id: int, payload: ProductUpdate, connection: DB):
    if product_id not in range(1, 6):
        raise HTTPException(status_code=422, detail={'code': 'INVALID_PRODUCT_SLOT'})
    normalized_name = payload.name.strip()
    if not normalized_name:
        raise HTTPException(status_code=422, detail={'code': 'INVALID_PRODUCT_NAME'})
    with transaction(connection):
        current=connection.execute("SELECT capacity,enabled FROM product_slots WHERE registry_id=? AND product_id=?",(registry_id,product_id)).fetchone()
        if not current:
            raise HTTPException(status_code=404, detail={'code': 'PRODUCT_SLOT_NOT_FOUND'})
        capacity=payload.capacity if payload.capacity is not None else max(current['capacity'],payload.stock)
        enabled=int(payload.enabled) if payload.enabled is not None else current['enabled']
        if payload.stock>capacity:
            raise HTTPException(status_code=422,detail={'code':'STOCK_EXCEEDS_CAPACITY'})
        result = connection.execute('UPDATE product_slots SET name=?,price_minor=?,stock=?,capacity=?,enabled=?,updated_at=CURRENT_TIMESTAMP WHERE registry_id=? AND product_id=?', (normalized_name, payload.price_minor, payload.stock, capacity, enabled, registry_id, product_id))
        if result.rowcount != 1:
            raise HTTPException(status_code=404, detail={'code': 'PRODUCT_SLOT_NOT_FOUND'})
        connection.execute('INSERT INTO audit_events(audit_id,actor_type,action,entity_type,entity_id,detail_json) VALUES(?,?,?,?,?,?)', (new_id('aud'), 'admin', 'vending.product.update', 'product_slot', f'{registry_id}:{product_id}', json.dumps({**payload.model_dump(), 'capacity':capacity,'enabled':bool(enabled),'name': normalized_name})))
    return {'registry_id': registry_id, 'product_id': product_id, 'name': normalized_name,'price_minor':payload.price_minor,'stock':payload.stock,'capacity':capacity,'enabled':bool(enabled),'nfc_promo_percent': 0, 'qris_promo_percent': 0}

@app.post('/api/v2/admin/vending/devices/{registry_id}/products/{product_id}/image', dependencies=[Depends(require_admin_session)])
async def upload_product_image(registry_id: str, product_id: int, connection: DB, file: UploadFile = File(...)):
    if product_id not in range(1,6):
        raise HTTPException(status_code=422,detail={'code':'INVALID_PRODUCT_SLOT'})
    raw=await file.read(2*1024*1024+1)
    if not raw or len(raw)>2*1024*1024:
        raise HTTPException(status_code=413,detail={'code':'IMAGE_MUST_BE_2MB_OR_SMALLER'})
    try:
        image=Image.open(BytesIO(raw))
        if image.format not in ('PNG','JPEG','WEBP'):
            raise HTTPException(status_code=415,detail={'code':'UNSUPPORTED_IMAGE_FORMAT'})
        if image.width<1 or image.height<1 or image.width>4096 or image.height>4096 or image.width*image.height>16_000_000:
            raise HTTPException(status_code=413,detail={'code':'IMAGE_DIMENSIONS_TOO_LARGE'})
        # Normalize all accepted uploads to bounded JPEG thumbnails so the
        # ESP32-S3 can decode them without a WebP runtime or large heap use.
        image=ImageOps.exif_transpose(image)
        image.load()
        if image.mode=='RGBA':
            background=Image.new('RGB',image.size,(255,255,255))
            background.paste(image,mask=image.getchannel('A'))
            image=background
        else:
            image=image.convert('RGB')
        image.thumbnail((256,192),Image.Resampling.LANCZOS)
        optimized=b''
        for quality in (82,76,70,64,58,52,46):
            output=BytesIO()
            image.save(output,format='JPEG',quality=quality,optimize=True,progressive=False)
            optimized=output.getvalue()
            if len(optimized)<=64*1024:
                break
        if len(optimized)>64*1024:
            image.thumbnail((192,144),Image.Resampling.LANCZOS)
            output=BytesIO()
            image.save(output,format='JPEG',quality=42,optimize=True,progressive=False)
            optimized=output.getvalue()
    except HTTPException:
        raise
    except (UnidentifiedImageError,OSError,ValueError) as exc:
        raise HTTPException(status_code=415,detail={'code':'INVALID_IMAGE_CONTENT'}) from exc
    if not optimized or len(optimized)>64*1024:
        raise HTTPException(status_code=413,detail={'code':'OPTIMIZED_IMAGE_MUST_BE_64KIB_OR_SMALLER'})
    digest=hashlib.sha256(optimized).hexdigest()
    with transaction(connection):
        slot=connection.execute("SELECT 1 FROM product_slots WHERE registry_id=? AND product_id=?",(registry_id,product_id)).fetchone()
        if not slot:
            raise HTTPException(status_code=404,detail={'code':'PRODUCT_SLOT_NOT_FOUND'})
        connection.execute("""INSERT INTO product_images(registry_id,product_id,content_type,image_data,sha256,byte_size,updated_at)
            VALUES(?,?, 'image/jpeg',?,?,?,CURRENT_TIMESTAMP)
            ON CONFLICT(registry_id,product_id) DO UPDATE SET content_type=excluded.content_type,image_data=excluded.image_data,
            sha256=excluded.sha256,byte_size=excluded.byte_size,updated_at=CURRENT_TIMESTAMP""",
            (registry_id,product_id,optimized,digest,len(optimized)))
        audit(connection,'vending.product.image.upload','product_slot',f'{registry_id}:{product_id}',
              detail={'sha256':digest,'byte_size':len(optimized),'content_type':'image/jpeg'})
    return {'registry_id':registry_id,'product_id':product_id,'sha256':digest,'byte_size':len(optimized),'content_type':'image/jpeg'}

@app.get('/api/v2/admin/vending/devices/{registry_id}/products/{product_id}/image', dependencies=[Depends(require_admin_session)])
def get_product_image(registry_id: str, product_id: int, connection: DB):
    row=connection.execute("SELECT image_data,sha256,content_type FROM product_images WHERE registry_id=? AND product_id=?",(registry_id,product_id)).fetchone()
    if not row:
        raise HTTPException(status_code=404,detail={'code':'PRODUCT_IMAGE_NOT_FOUND'})
    return Response(content=bytes(row['image_data']),media_type=row['content_type'],headers={'ETag':'"'+row['sha256']+'"','Cache-Control':'private, max-age=300'})

@app.post('/api/v2/members/{member_id}/cards', status_code=201, dependencies=[Depends(require_admin_session)])
def enroll_card(member_id: str, payload: CardEnroll, connection: DB):
    digest = card_hash(payload.card_uid)
    card_id = new_id('card')
    try:
        with transaction(connection):
            member = connection.execute('SELECT member_id,status FROM members WHERE member_id=?', (member_id,)).fetchone()
            if not member:
                raise HTTPException(status_code=404, detail={'code': 'MEMBER_NOT_FOUND'})
            if member['status'] != 'active':
                raise HTTPException(status_code=409, detail={'code': 'MEMBER_NOT_ACTIVE'})
            connection.execute("INSERT INTO member_cards(card_id,member_id,card_uid_hash,status) VALUES(?,?,?,'active')",
                (card_id, member_id, digest))
            audit(connection, 'member.card.enroll', 'member', member_id,
                  detail={'card_id': card_id, 'card_uid_hint': payload.card_uid.strip()[-4:]})
    except sqlite3.IntegrityError as exc:
        raise HTTPException(status_code=409, detail={'code': 'CARD_ALREADY_ENROLLED'}) from exc
    return {'card_id': card_id, 'member_id': member_id, 'status': 'active'}


@app.post('/api/v2/admin/members/{member_id}/nfc-registration', status_code=201, dependencies=[Depends(require_admin_session)])
def start_nfc_registration(member_id: str, payload: NfcRegistrationStart, connection: DB):
    with transaction(connection):
        member=connection.execute("SELECT member_id,status FROM members WHERE member_id=?",(member_id,)).fetchone()
        if not member:
            raise HTTPException(status_code=404,detail={'code':'MEMBER_NOT_FOUND'})
        if member['status']!='active':
            raise HTTPException(status_code=409,detail={'code':'MEMBER_NOT_ACTIVE'})
        cashier=connection.execute("SELECT registry_id,hardware_id,status FROM device_registry WHERE registry_id=? AND device_type='cashier'",(payload.registry_id,)).fetchone()
        if not cashier or cashier['status']!='active':
            raise HTTPException(status_code=409,detail={'code':'CASHIER_NOT_AVAILABLE'})
        pending=connection.execute("""SELECT session_id FROM nfc_registration_sessions
            WHERE registry_id=? AND status IN ('scan_pending','waiting_nfc','pin_pending','processing')
            AND expires_at>CURRENT_TIMESTAMP""",(payload.registry_id,)).fetchone()
        if pending:
            raise HTTPException(status_code=409,detail={'code':'CASHIER_REGISTRATION_BUSY'})
        session_id=new_id('nfc')
        connection.execute("""INSERT INTO nfc_registration_sessions
            (session_id,member_id,registry_id,status,expires_at,replace_existing)
            VALUES(?,?,?,'scan_pending',datetime('now','+5 minutes'),?)""",
            (session_id,member_id,payload.registry_id,int(payload.replace_existing)))
        audit(connection,'member.nfc_registration.start','member',member_id,
              detail={'session_id':session_id,'registry_id':payload.registry_id,'replace_existing':payload.replace_existing})
    return {'session_id':session_id,'member_id':member_id,'registry_id':payload.registry_id,
            'status':'scan_pending','expires_in_seconds':300}

@app.get('/api/v2/admin/nfc-registration/{session_id}', dependencies=[Depends(require_admin_session)])
def nfc_registration_status(session_id: str, connection: DB):
    with transaction(connection):
        row=connection.execute("""SELECT s.session_id,s.member_id,s.registry_id,s.status,s.created_at,s.expires_at,
            s.completed_at,s.error_code,m.display_name,d.hardware_id,d.display_name AS cashier_name
            FROM nfc_registration_sessions s JOIN members m ON m.member_id=s.member_id
            JOIN device_registry d ON d.registry_id=s.registry_id WHERE s.session_id=?""",(session_id,)).fetchone()
        if not row:
            raise HTTPException(status_code=404,detail={'code':'NFC_SESSION_NOT_FOUND'})
        if row['status'] in ('scan_pending','waiting_nfc','pin_pending','processing') and row['expires_at']<=connection.execute("SELECT CURRENT_TIMESTAMP").fetchone()[0]:
            connection.execute("UPDATE nfc_registration_sessions SET status='expired',error_code='SESSION_EXPIRED' WHERE session_id=?",(session_id,))
            row=connection.execute("""SELECT s.session_id,s.member_id,s.registry_id,s.status,s.created_at,s.expires_at,
                s.completed_at,s.error_code,m.display_name,d.hardware_id,d.display_name AS cashier_name
                FROM nfc_registration_sessions s JOIN members m ON m.member_id=s.member_id
                JOIN device_registry d ON d.registry_id=s.registry_id WHERE s.session_id=?""",(session_id,)).fetchone()
    return dict(row)

@app.get('/api/v2/cashier/nfc-registration')
def cashier_nfc_registration(connection: DB, x_device_key: Annotated[str | None, Header()] = None):
    device=authenticated_device(connection,x_device_key)
    if device['device_type']!='cashier':
        raise HTTPException(status_code=403,detail={'code':'CASHIER_DEVICE_REQUIRED'})
    with transaction(connection):
        connection.execute("""UPDATE nfc_registration_sessions SET status='expired',error_code='SESSION_EXPIRED'
            WHERE registry_id=? AND status IN ('scan_pending','waiting_nfc','pin_pending','processing')
            AND expires_at<=CURRENT_TIMESTAMP""",(device['registry_id'],))
        row=connection.execute("""SELECT s.session_id,s.member_id,s.status,s.expires_at,m.display_name
            FROM nfc_registration_sessions s JOIN members m ON m.member_id=s.member_id
            WHERE s.registry_id=? AND s.status IN ('scan_pending','waiting_nfc','pin_pending','processing')
            AND s.expires_at>CURRENT_TIMESTAMP ORDER BY s.created_at LIMIT 1""",(device['registry_id'],)).fetchone()
    return dict(row) if row else {'status':'idle'}

@app.post('/api/v2/cashier/nfc-registration/progress')
def cashier_nfc_registration_progress(payload: NfcRegistrationProgress, connection: DB,
                                      x_device_key: Annotated[str | None, Header()] = None):
    device=authenticated_device(connection,x_device_key)
    if device['device_type']!='cashier':
        raise HTTPException(status_code=403,detail={'code':'CASHIER_DEVICE_REQUIRED'})
    transitions={'scan_pending':{'waiting_nfc','failed'},'waiting_nfc':{'waiting_nfc','pin_pending','failed'},
                 'pin_pending':{'pin_pending','processing','failed'},'processing':{'processing','failed'}}
    expired=False
    with transaction(connection):
        row=connection.execute("SELECT status,expires_at FROM nfc_registration_sessions WHERE session_id=? AND registry_id=?",
                               (payload.session_id,device['registry_id'])).fetchone()
        if not row:
            raise HTTPException(status_code=404,detail={'code':'NFC_SESSION_NOT_FOUND'})
        if row['status'] not in transitions:
            raise HTTPException(status_code=409,detail={'code':'NFC_SESSION_NOT_ACTIVE'})
        if row['expires_at']<=connection.execute("SELECT CURRENT_TIMESTAMP").fetchone()[0]:
            connection.execute("UPDATE nfc_registration_sessions SET status='expired',error_code='SESSION_EXPIRED' WHERE session_id=?",(payload.session_id,))
            expired=True
        elif payload.status not in transitions[row['status']]:
            raise HTTPException(status_code=409,detail={'code':'INVALID_NFC_STATUS_TRANSITION'})
        else:
            connection.execute("UPDATE nfc_registration_sessions SET status=? WHERE session_id=?",(payload.status,payload.session_id))
    if expired:
        raise HTTPException(status_code=409,detail={'code':'NFC_SESSION_EXPIRED'})
    return {'session_id':payload.session_id,'status':payload.status}

@app.post('/api/v2/cashier/nfc-registration/complete')
def cashier_nfc_registration_complete(payload: NfcRegistrationComplete, connection: DB,
                                     x_device_key: Annotated[str | None, Header()] = None):
    device=authenticated_device(connection,x_device_key)
    if device['device_type']!='cashier':
        raise HTTPException(status_code=403,detail={'code':'CASHIER_DEVICE_REQUIRED'})
    digest=card_hash(payload.card_uid)
    expired=False
    result=None
    with transaction(connection):
        session=connection.execute("""SELECT session_id,member_id,status,expires_at,replace_existing
            FROM nfc_registration_sessions WHERE session_id=? AND registry_id=?""",
            (payload.session_id,device['registry_id'])).fetchone()
        if not session:
            raise HTTPException(status_code=404,detail={'code':'NFC_SESSION_NOT_FOUND'})
        if session['status']=='completed':
            prior=connection.execute("SELECT card_id FROM member_cards WHERE member_id=? AND card_uid_hash=? AND status='active'",
                                     (session['member_id'],digest)).fetchone()
            if prior:
                return {'session_id':payload.session_id,'member_id':session['member_id'],'status':'completed','idempotent_replay':True}
            raise HTTPException(status_code=409,detail={'code':'NFC_SESSION_ALREADY_COMPLETED'})
        if session['status'] not in ('pin_pending','processing'):
            raise HTTPException(status_code=409,detail={'code':'NFC_SESSION_NOT_READY'})
        if session['expires_at']<=connection.execute("SELECT CURRENT_TIMESTAMP").fetchone()[0]:
            connection.execute("UPDATE nfc_registration_sessions SET status='expired',error_code='SESSION_EXPIRED' WHERE session_id=?",(payload.session_id,))
            expired=True
        else:
            member=connection.execute("SELECT member_id,status FROM members WHERE member_id=?",(session['member_id'],)).fetchone()
            if not member or member['status']!='active':
                raise HTTPException(status_code=409,detail={'code':'MEMBER_NOT_ACTIVE'})
            if connection.execute("SELECT 1 FROM member_cards WHERE card_uid_hash=? AND status='active'",(digest,)).fetchone():
                raise HTTPException(status_code=409,detail={'code':'CARD_ALREADY_ENROLLED'})
            if session['replace_existing']:
                connection.execute("UPDATE member_cards SET status='revoked' WHERE member_id=? AND status='active'",(session['member_id'],))
            connection.execute("INSERT INTO member_cards(card_id,member_id,card_uid_hash,status) VALUES(?,?,?,'active')",
                               (new_id('card'),session['member_id'],digest))
            connection.execute("UPDATE members SET pin_hash=?,updated_at=CURRENT_TIMESTAMP WHERE member_id=?",
                               (pin_hash(payload.pin),session['member_id']))
            connection.execute("""UPDATE nfc_registration_sessions SET status='completed',card_uid_hash=?,card_uid_hint=?,
                completed_at=CURRENT_TIMESTAMP,error_code=NULL WHERE session_id=?""",
                (digest,payload.card_uid.strip()[-4:],payload.session_id))
            audit(connection,'member.nfc_registration.complete','member',session['member_id'],
                  detail={'session_id':payload.session_id,'registry_id':device['registry_id'],'card_uid_hint':payload.card_uid.strip()[-4:]})
            result={'session_id':payload.session_id,'member_id':session['member_id'],'status':'completed','pin_configured':True,'idempotent_replay':False}
    if expired:
        raise HTTPException(status_code=409,detail={'code':'NFC_SESSION_EXPIRED'})
    return result


@app.post('/api/v2/vending/purchases', status_code=201)
def purchase(payload: PurchaseRequest, connection: DB, x_device_key: Annotated[str | None, Header()] = None):
    device = authenticated_device(connection, x_device_key)
    if device['device_type'] != 'vending':
        raise HTTPException(status_code=403, detail={'code': 'VENDING_DEVICE_REQUIRED'})
    if payload.payment_method == 'qris':
        raise HTTPException(status_code=409, detail={'code': 'QRIS_PROVIDER_NOT_CONFIGURED'})
    digest = card_hash(payload.card_uid)
    # Persist throttling in its own transaction so a rejected PIN does not roll
    # back the security counter with the purchase transaction.
    with transaction(connection):
        pin_member = connection.execute(
            "SELECT m.member_id,m.status,m.pin_hash FROM member_cards c JOIN members m ON m.member_id=c.member_id WHERE c.card_uid_hash=? AND c.status='active'",
            (digest,)).fetchone()
        if not pin_member or pin_member['status'] != 'active':
            raise HTTPException(status_code=401, detail={'code': 'CARD_NOT_AUTHORIZED'})
        attempt = connection.execute(
            'SELECT failed_attempts,locked_until FROM pin_attempts WHERE card_hash=? AND hardware_id=?',
            (digest, device['hardware_id'])).fetchone()
        card_attempt = connection.execute(
            'SELECT failed_attempts,locked_until FROM pin_card_attempts WHERE card_hash=?',
            (digest,)).fetchone()
        locked = connection.execute(
            "SELECT CASE WHEN (? IS NOT NULL AND julianday(?) > julianday('now')) OR (? IS NOT NULL AND julianday(?) > julianday('now')) THEN 1 ELSE 0 END",
            (attempt['locked_until'] if attempt else None, attempt['locked_until'] if attempt else None,
             card_attempt['locked_until'] if card_attempt else None, card_attempt['locked_until'] if card_attempt else None)).fetchone()[0]
        if locked:
            raise HTTPException(status_code=429, detail={'code': 'PIN_TEMPORARILY_LOCKED'})
        if not verify_pin(payload.pin, pin_member['pin_hash']):
            device_failures = (attempt['failed_attempts'] if attempt else 0) + 1
            card_failures = (card_attempt['failed_attempts'] if card_attempt else 0) + 1
            device_lock = device_failures >= 5
            card_lock = card_failures >= 5
            connection.execute(
                "INSERT INTO pin_attempts(card_hash,hardware_id,failed_attempts,locked_until,updated_at) VALUES(?,?,?,CASE WHEN ? THEN datetime('now','+5 minutes') ELSE NULL END,CURRENT_TIMESTAMP) ON CONFLICT(card_hash,hardware_id) DO UPDATE SET failed_attempts=excluded.failed_attempts,locked_until=excluded.locked_until,updated_at=CURRENT_TIMESTAMP",
                (digest, device['hardware_id'], device_failures, int(device_lock)))
            connection.execute(
                "INSERT INTO pin_card_attempts(card_hash,failed_attempts,locked_until,updated_at) VALUES(?,?,CASE WHEN ? THEN datetime('now','+5 minutes') ELSE NULL END,CURRENT_TIMESTAMP) ON CONFLICT(card_hash) DO UPDATE SET failed_attempts=excluded.failed_attempts,locked_until=excluded.locked_until,updated_at=CURRENT_TIMESTAMP",
                (digest, card_failures, int(card_lock)))
            pin_error = {'code': 'PIN_TEMPORARILY_LOCKED'} if card_lock or device_lock else {'code': 'INVALID_PIN'}
        else:
            connection.execute(
                'DELETE FROM pin_attempts WHERE card_hash=? AND hardware_id=?',
                (digest, device['hardware_id']))
            connection.execute(
                'DELETE FROM pin_card_attempts WHERE card_hash=?',
                (digest,))
            pin_error = None
    if pin_error:
        raise HTTPException(status_code=429 if pin_error['code'] == 'PIN_TEMPORARILY_LOCKED' else 401, detail=pin_error)
    try:
        with transaction(connection):
            prior = connection.execute("SELECT transaction_id,status,member_id,amount_minor,hardware_id,transaction_type,metadata_json FROM transactions WHERE request_id=?",
                (payload.request_id,)).fetchone()
            if prior:
                meta = json.loads(prior['metadata_json'] or '{}')
                if (prior['transaction_type'] != 'purchase' or prior['hardware_id'] != device['hardware_id']
                    or meta.get('product_id') != payload.product_id or meta.get('card_hash') != digest
                    or (payload.expected_amount_minor is not None and prior['amount_minor'] != payload.expected_amount_minor)
                    or meta.get('payment_method','nfc') != payload.payment_method):
                    raise HTTPException(status_code=409, detail={'code': 'IDEMPOTENCY_CONFLICT'})
                current = connection.execute("SELECT balance_minor,updated_at FROM accounts WHERE member_id=? AND account_type='member'",(prior['member_id'],)).fetchone()
                return {'transaction_id': prior['transaction_id'], 'member_id': prior['member_id'], 'status': prior['status'],
                        'amount_minor': prior['amount_minor'],
                        'balance_after_minor': current['balance_minor'] if current else None,
                        'balance_version': current['updated_at'] if current else None,'idempotent_replay': True}
            member = connection.execute("SELECT m.member_id,m.status,m.pin_hash FROM member_cards c JOIN members m ON m.member_id=c.member_id WHERE c.card_uid_hash=? AND c.status='active'",
                (digest,)).fetchone()
            if not member or member['status'] != 'active':
                raise HTTPException(status_code=401, detail={'code': 'CARD_NOT_AUTHORIZED'})
            if not verify_pin(payload.pin, member['pin_hash']):
                raise HTTPException(status_code=401, detail={'code': 'INVALID_PIN'})
            product = connection.execute('SELECT name,price_minor,stock,enabled FROM product_slots WHERE registry_id=? AND product_id=?',
                (device['registry_id'], payload.product_id)).fetchone()
            if not product:
                raise HTTPException(status_code=404, detail={'code': 'PRODUCT_SLOT_NOT_FOUND'})
            if not product['enabled']:
                raise HTTPException(status_code=409, detail={'code':'PRODUCT_DISABLED'})
            if product['stock'] < 1:
                raise HTTPException(status_code=409, detail={'code': 'OUT_OF_STOCK'})
            if product['price_minor'] <= 0:
                raise HTTPException(status_code=409, detail={'code': 'PRODUCT_PRICE_NOT_CONFIGURED'})
            account = connection.execute("SELECT account_id,balance_minor,status FROM accounts WHERE member_id=? AND account_type='member'",
                (member['member_id'],)).fetchone()
            if not account or account['status'] != 'active':
                raise HTTPException(status_code=409, detail={'code': 'ACCOUNT_NOT_ACTIVE'})
            amount = product['price_minor']
            if payload.expected_amount_minor is not None and amount != payload.expected_amount_minor:
                raise HTTPException(status_code=409, detail={'code':'CATALOG_PRICE_CHANGED'})
            if account['balance_minor'] < amount:
                raise HTTPException(status_code=409, detail={'code': 'INSUFFICIENT_BALANCE'})
            system_id = ensure_system_account(connection)
            system_account = connection.execute("SELECT balance_minor FROM accounts WHERE account_id=? AND account_type='system'", (system_id,)).fetchone()
            if not system_account or system_account['balance_minor'] < amount:
                raise HTTPException(status_code=409, detail={'code': 'SYSTEM_ACCOUNT_INSUFFICIENT_BALANCE'})
            transaction_id = new_id('txn')
            metadata = {'product_id': payload.product_id, 'registry_id': device['registry_id'],
                        'card_hash': digest, 'product_name': product['name'], 'payment_method': payload.payment_method,
                        'dispense_status': 'pending'}
            connection.execute("INSERT INTO transactions(transaction_id,request_id,hardware_id,member_id,transaction_type,amount_minor,status,metadata_json) VALUES(?,?,?,?,'purchase',?,'pending',?)",
                (transaction_id, payload.request_id, device['hardware_id'], member['member_id'], amount, json.dumps(metadata)))
            debited = connection.execute("UPDATE accounts SET balance_minor=balance_minor-?,updated_at=CURRENT_TIMESTAMP WHERE account_id=? AND status='active' AND balance_minor>=?",
                (amount, account['account_id'], amount))
            stocked = connection.execute("UPDATE product_slots SET stock=stock-1,updated_at=CURRENT_TIMESTAMP WHERE registry_id=? AND product_id=? AND stock>0",
                (device['registry_id'], payload.product_id))
            if debited.rowcount != 1:
                raise HTTPException(status_code=409, detail={'code': 'INSUFFICIENT_BALANCE'})
            if stocked.rowcount != 1:
                raise HTTPException(status_code=409, detail={'code': 'OUT_OF_STOCK'})
            system_debited = connection.execute("UPDATE accounts SET balance_minor=balance_minor-?,updated_at=CURRENT_TIMESTAMP WHERE account_id=? AND account_type='system' AND balance_minor>=?", (amount, system_id, amount))
            if system_debited.rowcount != 1:
                raise HTTPException(status_code=409, detail={'code': 'SYSTEM_ACCOUNT_INSUFFICIENT_BALANCE'})
            connection.execute("INSERT INTO ledger_entries(entry_id,transaction_id,account_id,direction,amount_minor) VALUES(?,?,?,'debit',?)",
                (new_id('led'), transaction_id, account['account_id'], amount))
            connection.execute("INSERT INTO ledger_entries(entry_id,transaction_id,account_id,direction,amount_minor) VALUES(?,?,?,'credit',?)",
                (new_id('led'), transaction_id, system_id, amount))
            audit(connection, 'vending.purchase', 'transaction', transaction_id, payload.request_id,
                  {'registry_id': device['registry_id'], 'product_id': payload.product_id,
                   'member_id': member['member_id'], 'amount_minor': amount})
    except sqlite3.IntegrityError as exc:
        raise HTTPException(status_code=409, detail={'code': 'IDEMPOTENCY_CONFLICT'}) from exc
    current_balance = connection.execute("SELECT balance_minor,updated_at FROM accounts WHERE member_id=? AND account_type='member'",(member['member_id'],)).fetchone()
    return {'transaction_id': transaction_id, 'member_id': member['member_id'], 'status': 'pending', 'amount_minor': amount,
            'balance_after_minor': current_balance['balance_minor'] if current_balance else None,
            'balance_version': current_balance['updated_at'] if current_balance else None,
            'dispense_confirmation_required': True, 'idempotent_replay': False}


@app.post('/api/v2/vending/transactions/{transaction_id}/dispense-result')
def dispense_result(transaction_id: str, payload: DispenseResult, connection: DB,
                    x_device_key: Annotated[str | None, Header()] = None):
    device = authenticated_device(connection, x_device_key)
    if device['device_type'] != 'vending':
        raise HTTPException(status_code=403, detail={'code': 'VENDING_DEVICE_REQUIRED'})
    with transaction(connection):
        row = connection.execute("SELECT transaction_id,request_id,hardware_id,member_id,transaction_type,amount_minor,status,metadata_json FROM transactions WHERE transaction_id=?",
            (transaction_id,)).fetchone()
        if not row or row['transaction_type'] != 'purchase' or row['hardware_id'] != device['hardware_id']:
            raise HTTPException(status_code=404, detail={'code': 'PURCHASE_NOT_FOUND'})
        meta = json.loads(row['metadata_json'] or '{}')
        if meta.get('dispense_status') in ('succeeded', 'failed'):
            current = connection.execute("SELECT balance_minor,updated_at FROM accounts WHERE member_id=? AND account_type='member'",(row['member_id'],)).fetchone()
            return {'transaction_id': transaction_id, 'member_id': row['member_id'], 'status': row['status'],
                    'dispense_status': meta['dispense_status'],
                    'balance_after_minor': current['balance_minor'] if current else None,
                    'balance_version': current['updated_at'] if current else None,'idempotent_replay': True}
        if payload.succeeded:
            meta['dispense_status'] = 'succeeded'
            connection.execute("UPDATE transactions SET status='succeeded',metadata_json=?,completed_at=CURRENT_TIMESTAMP WHERE transaction_id=?",
                (json.dumps(meta), transaction_id))
            audit(connection, 'vending.dispense.succeeded', 'transaction', transaction_id, row['request_id'])
            current = connection.execute("SELECT balance_minor,updated_at FROM accounts WHERE member_id=? AND account_type='member'",(row['member_id'],)).fetchone()
            return {'transaction_id': transaction_id, 'member_id': row['member_id'], 'status': 'succeeded', 'dispense_status': 'succeeded',
                    'balance_after_minor': current['balance_minor'] if current else None,
                    'balance_version': current['updated_at'] if current else None,'idempotent_replay': False}
        account = connection.execute("SELECT account_id FROM accounts WHERE member_id=? AND account_type='member'",
            (row['member_id'],)).fetchone()
        if not account:
            raise HTTPException(status_code=500, detail={'code': 'MEMBER_ACCOUNT_MISSING'})
        system_id = ensure_system_account(connection)
        connection.execute("UPDATE accounts SET balance_minor=balance_minor+?,updated_at=CURRENT_TIMESTAMP WHERE account_id=?",
            (row['amount_minor'], account['account_id']))
        connection.execute("UPDATE accounts SET balance_minor=balance_minor+?,updated_at=CURRENT_TIMESTAMP WHERE account_id=? AND account_type='system'",
            (row['amount_minor'], system_id))
        connection.execute("UPDATE product_slots SET stock=stock+1,updated_at=CURRENT_TIMESTAMP WHERE registry_id=? AND product_id=?",
            (meta['registry_id'], meta['product_id']))
        connection.execute("INSERT INTO ledger_entries(entry_id,transaction_id,account_id,direction,amount_minor) VALUES(?,?,?,'credit',?)",
            (new_id('led'), transaction_id, account['account_id'], row['amount_minor']))
        connection.execute("INSERT INTO ledger_entries(entry_id,transaction_id,account_id,direction,amount_minor) VALUES(?,?,?,'debit',?)",
            (new_id('led'), transaction_id, system_id, row['amount_minor']))
        meta['dispense_status'] = 'failed'
        meta['dispense_failure_reason'] = payload.reason or 'dispense_failed'
        connection.execute("UPDATE transactions SET status='reversed',metadata_json=?,completed_at=CURRENT_TIMESTAMP WHERE transaction_id=?",
            (json.dumps(meta), transaction_id))
        audit(connection, 'vending.dispense.refund', 'transaction', transaction_id, row['request_id'],
              {'reason': meta['dispense_failure_reason']})
    current = connection.execute("SELECT balance_minor,updated_at FROM accounts WHERE member_id=? AND account_type='member'",(row['member_id'],)).fetchone()
    return {'transaction_id': transaction_id, 'member_id': row['member_id'], 'status': 'reversed', 'dispense_status': 'failed',
            'refunded_amount_minor': row['amount_minor'],
            'balance_after_minor': current['balance_minor'] if current else None,
            'balance_version': current['updated_at'] if current else None,'idempotent_replay': False}


@app.get('/api/v2/admin/finance/reconciliation', dependencies=[Depends(require_admin_session)])
def finance_reconciliation(connection: DB):
    transaction_rows = connection.execute("""
        SELECT t.transaction_id, t.request_id,
               SUM(CASE WHEN l.direction='debit' THEN l.amount_minor ELSE 0 END) AS debit_total,
               SUM(CASE WHEN l.direction='credit' THEN l.amount_minor ELSE 0 END) AS credit_total
        FROM transactions t
        LEFT JOIN ledger_entries l ON l.transaction_id=t.transaction_id
        GROUP BY t.transaction_id, t.request_id
        HAVING debit_total != credit_total
        ORDER BY t.transaction_id
        LIMIT 500
    """).fetchall()
    account_rows = connection.execute("""
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
        HAVING balance_minor != ledger_balance
        ORDER BY a.account_id
        LIMIT 500
    """).fetchall()
    pending_rows = connection.execute("""
        SELECT transaction_id, request_id, hardware_id, member_id, amount_minor, created_at
        FROM transactions
        WHERE transaction_type='purchase' AND status='pending'
        ORDER BY created_at
        LIMIT 500
    """).fetchall()
    transaction_imbalances = [dict(row) for row in transaction_rows]
    account_mismatches = [dict(row) for row in account_rows]
    pending_purchases = [dict(row) for row in pending_rows]
    return {
        'status': 'attention_required' if transaction_imbalances or account_mismatches or pending_purchases else 'ok',
        'transaction_imbalances': transaction_imbalances,
        'account_mismatches': account_mismatches,
        'pending_purchases': pending_purchases,
        'pending_purchases_require_review': bool(pending_purchases),
    }


@app.get('/api/v2/admin/accounts', dependencies=[Depends(require_admin_session)])
def admin_accounts(connection: DB):
    rows=connection.execute("""SELECT a.account_id,a.member_id,m.display_name AS member_name,a.account_type,a.label,
        a.currency,a.balance_minor,a.status,a.updated_at FROM accounts a
        LEFT JOIN members m ON m.member_id=a.member_id ORDER BY a.account_type,a.created_at DESC""").fetchall()
    return {'items':[dict(row) for row in rows]}

@app.get('/api/v2/admin/accounts/{account_id}/ledger', dependencies=[Depends(require_admin_session)])
def account_ledger(account_id: str, connection: DB, limit: int = 100):
    limit=max(1,min(limit,500))
    if not connection.execute("SELECT 1 FROM accounts WHERE account_id=?",(account_id,)).fetchone():
        raise HTTPException(status_code=404,detail={'code':'ACCOUNT_NOT_FOUND'})
    rows=connection.execute("""SELECT l.entry_id,l.transaction_id,l.direction,l.amount_minor,l.created_at,
        t.request_id,t.transaction_type,t.status,t.hardware_id,t.member_id,t.metadata_json
        FROM ledger_entries l JOIN transactions t ON t.transaction_id=l.transaction_id
        WHERE l.account_id=? ORDER BY l.created_at DESC LIMIT ?""",(account_id,limit)).fetchall()
    return {'account_id':account_id,'items':[dict(row) for row in rows]}

@app.post('/api/v2/finance/withdrawals', dependencies=[Depends(require_admin_session)])
def withdraw(payload: TopUpRequest, connection: DB):
    transaction_id=new_id('txn')
    try:
        with transaction(connection):
            prior=connection.execute("SELECT transaction_id,member_id,amount_minor,transaction_type,status FROM transactions WHERE request_id=?",(payload.request_id,)).fetchone()
            if prior:
                if prior['member_id']!=payload.member_id or prior['amount_minor']!=payload.amount_minor or prior['transaction_type']!='withdrawal' or prior['status']!='succeeded':
                    raise HTTPException(status_code=409,detail={'code':'IDEMPOTENCY_CONFLICT'})
                return {'transaction_id':prior['transaction_id'],'status':prior['status'],'idempotent_replay':True}
            account=connection.execute("SELECT account_id,balance_minor,status,currency FROM accounts WHERE member_id=? AND account_type='member'",(payload.member_id,)).fetchone()
            if not account:
                raise HTTPException(status_code=404,detail={'code':'MEMBER_ACCOUNT_NOT_FOUND'})
            if account['status']!='active':
                raise HTTPException(status_code=409,detail={'code':'ACCOUNT_NOT_ACTIVE'})
            if account['balance_minor']<payload.amount_minor:
                raise HTTPException(status_code=409,detail={'code':'INSUFFICIENT_BALANCE'})
            system_id=ensure_system_account(connection)
            system=connection.execute("SELECT balance_minor,status,currency FROM accounts WHERE account_id=?",(system_id,)).fetchone()
            if not system or system['status']!='active' or system['currency']!=account['currency'] or system['balance_minor']<payload.amount_minor:
                raise HTTPException(status_code=409,detail={'code':'SYSTEM_ACCOUNT_INSUFFICIENT_BALANCE'})
            connection.execute("""INSERT INTO transactions(transaction_id,request_id,member_id,transaction_type,
                amount_minor,currency,status,metadata_json,completed_at) VALUES(?,?,?,'withdrawal',?,?,'succeeded',?,CURRENT_TIMESTAMP)""",
                (transaction_id,payload.request_id,payload.member_id,payload.amount_minor,account['currency'],
                 json.dumps({'description':payload.description},separators=(',',':'))))
            debited=connection.execute("UPDATE accounts SET balance_minor=balance_minor-?,updated_at=CURRENT_TIMESTAMP WHERE account_id=? AND status='active' AND balance_minor>=?",
                (payload.amount_minor,account['account_id'],payload.amount_minor))
            system_debit=connection.execute("UPDATE accounts SET balance_minor=balance_minor-?,updated_at=CURRENT_TIMESTAMP WHERE account_id=? AND status='active' AND balance_minor>=?",
                (payload.amount_minor,system_id,payload.amount_minor))
            if debited.rowcount!=1 or system_debit.rowcount!=1:
                raise HTTPException(status_code=409,detail={'code':'INSUFFICIENT_BALANCE'})
            connection.execute("INSERT INTO ledger_entries(entry_id,transaction_id,account_id,direction,amount_minor) VALUES(?,?,?,'debit',?)",
                (new_id('led'),transaction_id,account['account_id'],payload.amount_minor))
            connection.execute("INSERT INTO ledger_entries(entry_id,transaction_id,account_id,direction,amount_minor) VALUES(?,?,?,'credit',?)",
                (new_id('led'),transaction_id,system_id,payload.amount_minor))
            audit(connection,'finance.withdrawal','transaction',transaction_id,payload.request_id,
                  {'member_id':payload.member_id,'amount_minor':payload.amount_minor,'description':payload.description})
    except sqlite3.IntegrityError as exc:
        raise HTTPException(status_code=409,detail={'code':'IDEMPOTENCY_CONFLICT'}) from exc
    return {'transaction_id':transaction_id,'status':'succeeded','idempotent_replay':False}

def _transaction_window(period: str, date: str | None, start_date: str | None, end_date: str | None):
    import datetime as dt
    from zoneinfo import ZoneInfo
    jakarta=ZoneInfo('Asia/Jakarta')
    selected=dt.date.fromisoformat(date) if date else dt.datetime.now(jakarta).date()
    period_alias={'1d':'day','1w':'week','1m':'month'}
    period=period_alias.get(period,period)
    if period=='day':
        start=selected; end=start+dt.timedelta(days=1)
    elif period=='week':
        start=selected-dt.timedelta(days=selected.weekday()); end=start+dt.timedelta(days=7)
    elif period=='month':
        start=selected.replace(day=1); end=(start.replace(year=start.year+1,month=1) if start.month==12 else start.replace(month=start.month+1))
    elif period in {'3m','5m','1y'}:
        months={'3m':3,'5m':5,'1y':12}[period]
        end=selected.replace(day=1)
        index=end.year*12+(end.month-1)-(months-1)
        start=dt.date(index//12,index%12+1,1)
        end_index=end.year*12+end.month
        end=dt.date(end_index//12,end_index%12+1,1)
    elif period=='custom':
        if not start_date or not end_date: raise HTTPException(status_code=400,detail={'code':'CUSTOM_RANGE_REQUIRED'})
        start=dt.date.fromisoformat(start_date); inclusive_end=dt.date.fromisoformat(end_date)
        if start>inclusive_end: raise HTTPException(status_code=400,detail={'code':'INVALID_DATE_RANGE'})
        end=inclusive_end+dt.timedelta(days=1)
    elif period=='all':
        return None,None
    else:
        raise HTTPException(status_code=400,detail={'code':'INVALID_PERIOD'})
    utc_start=dt.datetime.combine(start,dt.time.min,tzinfo=jakarta).astimezone(dt.timezone.utc).strftime('%Y-%m-%d %H:%M:%S')
    utc_end=dt.datetime.combine(end,dt.time.min,tzinfo=jakarta).astimezone(dt.timezone.utc).strftime('%Y-%m-%d %H:%M:%S')
    return utc_start,utc_end

@app.get('/api/v2/admin/transactions', dependencies=[Depends(require_admin_session)])
def admin_transactions(connection: DB, period: str = 'week', date: str | None = None,
                       start_date: str | None = None, end_date: str | None = None,
                       source: str = 'ALL', status: str = 'ALL', transaction_type: str = 'ALL',
                       member_id: str = '', hardware_id: str = '', transaction_id: str = '',
                       limit: int = 500):
    source=source.upper(); status=status.lower(); transaction_type=transaction_type.lower()
    if source not in {'ALL','CASHIER','VENDING','TOPUP'}: raise HTTPException(status_code=400,detail={'code':'INVALID_SOURCE'})
    if status not in {'all','pending','succeeded','declined','reversed'}: raise HTTPException(status_code=400,detail={'code':'INVALID_STATUS'})
    allowed_types={'all','purchase','cashier_payment','top_up','withdrawal','refund','adjustment','transfer'}
    if transaction_type not in allowed_types: raise HTTPException(status_code=400,detail={'code':'INVALID_TRANSACTION_TYPE'})
    start,end=_transaction_window(period,date,start_date,end_date)
    sql="""SELECT t.transaction_id,t.request_id,t.hardware_id,d.display_name AS device_name,t.member_id,m.display_name AS member_name,
        t.transaction_type,t.amount_minor,t.currency,t.status,t.metadata_json,t.created_at,t.completed_at
        FROM transactions t LEFT JOIN members m ON m.member_id=t.member_id
        LEFT JOIN device_registry d ON d.hardware_id=t.hardware_id WHERE 1=1"""
    args=[]
    if start:
        sql+=" AND t.created_at>=? AND t.created_at<?";args.extend([start,end])
    if source=='CASHIER':
        sql+=" AND (t.transaction_type='cashier_payment' OR (t.transaction_type='top_up' AND t.metadata_json LIKE '%\"source\":\"cashier\"%'))"
    elif source=='VENDING': sql+=" AND t.transaction_type='purchase'"
    elif source=='TOPUP': sql+=" AND t.transaction_type='top_up'"
    if status!='all': sql+=" AND t.status=?";args.append(status)
    if transaction_type!='all': sql+=" AND t.transaction_type=?";args.append(transaction_type)
    if member_id.strip(): sql+=" AND t.member_id=?";args.append(member_id.strip())
    if hardware_id.strip(): sql+=" AND t.hardware_id=?";args.append(hardware_id.strip())
    if transaction_id.strip(): sql+=" AND (t.transaction_id LIKE ? OR t.request_id LIKE ?)";args.extend(['%'+transaction_id.strip()+'%','%'+transaction_id.strip()+'%'])
    sql+=" ORDER BY t.created_at DESC LIMIT ?";args.append(max(1,min(limit,1000)))
    rows=connection.execute(sql,args).fetchall()
    items=[]
    for row in rows:
        item=dict(row)
        try: item['metadata']=json.loads(item.pop('metadata_json') or '{}')
        except (TypeError,ValueError): item['metadata']={}
        items.append(item)
    return {'items':items,'period':period,'source':source,'status':status,'transaction_type':transaction_type,
            'start_utc':start,'end_utc_exclusive':end,'timezone':'Asia/Jakarta'}

@app.get('/api/v2/admin/dashboard', dependencies=[Depends(require_admin_session)])
def admin_dashboard(connection: DB, period: str = 'week'):
    start,end=_transaction_window(period,None,None,None)
    member_count=connection.execute("SELECT COUNT(*) FROM members").fetchone()[0]
    active_devices=connection.execute("SELECT COUNT(*) FROM device_registry WHERE status='active'").fetchone()[0]
    balance=connection.execute("SELECT COALESCE(SUM(balance_minor),0) FROM accounts WHERE account_type='member' AND status='active'").fetchone()[0]
    tx_sql="SELECT COUNT(*) FROM transactions WHERE status='succeeded'"
    tx_args=[]
    if start: tx_sql+=" AND created_at>=? AND created_at<?";tx_args=[start,end]
    successful=connection.execute(tx_sql,tx_args).fetchone()[0]
    recent=connection.execute("""SELECT t.transaction_id,t.request_id,t.hardware_id,d.display_name AS device_name,
        t.member_id,m.display_name AS member_name,t.transaction_type,t.amount_minor,t.currency,t.status,t.metadata_json,t.created_at
        FROM transactions t LEFT JOIN members m ON m.member_id=t.member_id LEFT JOIN device_registry d ON d.hardware_id=t.hardware_id
        ORDER BY t.created_at DESC LIMIT 10""").fetchall()
    sales=connection.execute("""SELECT t.hardware_id,t.amount_minor,t.metadata_json,t.created_at
        FROM transactions t WHERE t.transaction_type='purchase' AND t.status='succeeded'"""+(" AND t.created_at>=? AND t.created_at<?" if start else ""),
        ([start,end] if start else [])).fetchall()
    used={};products={}
    for row in sales:
        meta=json.loads(row['metadata_json'] or '{}')
        hid=row['hardware_id'] or 'unknown'
        used[hid]=used.get(hid,0)+1
        pid=str(meta.get('product_id','?')); key=(hid,pid)
        item=products.setdefault(key,{'hardware_id':hid,'product_id':pid,'product_name':meta.get('product_name',f'Produk {pid}'),'units_sold':0,'revenue_minor':0})
        item['units_sold']+=1;item['revenue_minor']+=row['amount_minor']
    names={r['hardware_id']:r['display_name'] or r['hardware_id'] for r in connection.execute("SELECT hardware_id,display_name FROM device_registry WHERE device_type='vending'").fetchall()}
    analytics_sql="SELECT created_at FROM transactions WHERE status='succeeded'"
    analytics_args=[]
    if start:
        analytics_sql+=" AND created_at>=? AND created_at<?";analytics_args=[start,end]
    analytics_rows=connection.execute(analytics_sql,analytics_args).fetchall()
    from datetime import datetime,timezone
    from zoneinfo import ZoneInfo
    jakarta=ZoneInfo('Asia/Jakarta');daily={}
    for row in analytics_rows:
        try:
            local=datetime.strptime(row['created_at'][:19],'%Y-%m-%d %H:%M:%S').replace(tzinfo=timezone.utc).astimezone(jakarta)
            day=local.strftime('%Y-%m-%d')
            daily[day]=daily.get(day,0)+1
        except (TypeError,ValueError):
            continue
    channel_sql="SELECT transaction_type,amount_minor,metadata_json FROM transactions WHERE status='succeeded'"
    channel_args=[]
    if start:
        channel_sql+=" AND created_at>=? AND created_at<?";channel_args=[start,end]
    channel_rows=connection.execute(channel_sql,channel_args).fetchall()
    channels={}
    for row in channel_rows:
        try: meta=json.loads(row['metadata_json'] or '{}')
        except (TypeError,ValueError): meta={}
        channel=meta.get('payment_method') or row['transaction_type'].replace('_',' ').title()
        slot=channels.setdefault(channel,{'channel':channel,'transactions':0,'amount_minor':0})
        slot['transactions']+=1;slot['amount_minor']+=row['amount_minor']
    return {'period':period,'summary':{'members':member_count,'active_devices':active_devices,'member_balance_minor':balance,'successful_transactions':successful},
        'analytics':[{'date':k,'count':v} for k,v in sorted(daily.items())],
        'most_used_vending':[{'hardware_id':k,'device_name':names.get(k,k),'transactions':v} for k,v in sorted(used.items(),key=lambda x:x[1],reverse=True)[:10]],
        'best_selling_products':sorted(products.values(),key=lambda x:x['units_sold'],reverse=True)[:10],
        'payment_channels':sorted(channels.values(),key=lambda x:x['transactions'],reverse=True),
        'recent_transactions':[dict(r) for r in recent]}

@app.get('/api/v2/admin/reports/transactions.xlsx', dependencies=[Depends(require_admin_session)])
def export_transactions_xlsx(connection: DB, period: str = 'week', date: str | None = None,
                             start_date: str | None = None, end_date: str | None = None,
                             source: str = 'ALL', status: str = 'ALL', transaction_type: str = 'ALL',
                             member_id: str = '', hardware_id: str = '', transaction_id: str = '',
                             limit: int = 1000):
    from openpyxl import Workbook
    from datetime import datetime
    from zoneinfo import ZoneInfo
    data=admin_transactions(connection,period,date,start_date,end_date,source,status,transaction_type,
                            member_id,hardware_id,transaction_id,limit)
    workbook=Workbook()
    sheet=workbook.active
    sheet.title='Transactions'
    columns=['transaction_id','request_id','created_at','completed_at','member_id','member_name','hardware_id',
             'device_name','transaction_type','amount_minor','currency','status','metadata']
    sheet.append(columns)
    for item in data['items']:
        sheet.append([json.dumps(item.get(key),ensure_ascii=False,separators=(',',':')) if key=='metadata' else item.get(key) for key in columns])
    for cell in sheet[1]:
        cell.font=__import__('openpyxl').styles.Font(bold=True)
    sheet.freeze_panes='A2'
    sheet.auto_filter.ref=sheet.dimensions
    meta=workbook.create_sheet('Report metadata')
    for key,value in [('timezone','Asia/Jakarta'),('period',period),('source',source.upper()),('status',status.lower()),
                      ('transaction_type',transaction_type.lower()),('member_id',member_id),('hardware_id',hardware_id),
                      ('transaction_id_filter',transaction_id),('start_utc',data['start_utc']),('end_utc_exclusive',data['end_utc_exclusive']),
                      ('exported_at',datetime.now(ZoneInfo('Asia/Jakarta')).isoformat()),('row_count',len(data['items']))]:
        meta.append([key,value or ''])
    stream=BytesIO()
    workbook.save(stream)
    stream.seek(0)
    stamp=datetime.now(ZoneInfo('Asia/Jakarta')).strftime('%Y%m%d_%H%M%S')
    filename=f"M-Group_Transactions_{source.upper()}_{stamp}_{new_id('rpt')[-6:]}.xlsx"
    return StreamingResponse(stream,media_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
        headers={'Content-Disposition':f'attachment; filename="{filename}"'})

@app.post('/api/v2/admin/backup', dependencies=[Depends(require_admin_session)])
def create_backup(connection: DB):
    from datetime import datetime, timezone
    database_bytes=connection.serialize()
    if not database_bytes:
        raise HTTPException(status_code=500,detail={'code':'DATABASE_SNAPSHOT_EMPTY'})
    manifest={'format':'mgroup-v2-native-backup','schema':'clean-room-v2','created_at_utc':datetime.now(timezone.utc).isoformat(),
              'sha256':hashlib.sha256(database_bytes).hexdigest(),'size_bytes':len(database_bytes)}
    stream=BytesIO()
    with zipfile.ZipFile(stream,'w',compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr('database.sqlite3',database_bytes)
        archive.writestr('manifest.json',json.dumps(manifest,sort_keys=True,indent=2))
    stream.seek(0)
    filename='M-Group_BACKUP_'+datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')+'.mgroup.zip'
    return StreamingResponse(stream,media_type='application/zip',headers={'Content-Disposition':f'attachment; filename="{filename}"'})

@app.post('/api/v2/admin/backup/restore', dependencies=[Depends(require_admin_session)])
async def restore_backup(connection: DB, file: UploadFile = File(...)):
    max_bytes=100*1024*1024
    raw=await file.read(max_bytes+1)
    if not raw or len(raw)>max_bytes:
        raise HTTPException(status_code=413,detail={'code':'BACKUP_ARCHIVE_TOO_LARGE'})
    try:
        with zipfile.ZipFile(BytesIO(raw),'r') as archive:
            names=set(archive.namelist())
            if len(archive.infolist())!=2 or names!={'database.sqlite3','manifest.json'}:
                raise HTTPException(status_code=400,detail={'code':'INVALID_BACKUP_CONTENTS'})
            if archive.getinfo('manifest.json').file_size>65536:
                raise HTTPException(status_code=413,detail={'code':'BACKUP_MANIFEST_TOO_LARGE'})
            if archive.getinfo('database.sqlite3').file_size>max_bytes:
                raise HTTPException(status_code=413,detail={'code':'BACKUP_DATABASE_TOO_LARGE'})
            database_bytes=archive.read('database.sqlite3')
            manifest=json.loads(archive.read('manifest.json').decode('utf-8'))
    except (zipfile.BadZipFile,KeyError,UnicodeDecodeError,json.JSONDecodeError) as exc:
        raise HTTPException(status_code=400,detail={'code':'INVALID_BACKUP_ARCHIVE'}) from exc
    if manifest.get('format')!='mgroup-v2-native-backup' or manifest.get('sha256')!=hashlib.sha256(database_bytes).hexdigest():
        raise HTTPException(status_code=400,detail={'code':'BACKUP_CHECKSUM_MISMATCH'})
    target=Path(settings.database_path)
    if str(target)==':memory:':
        raise HTTPException(status_code=409,detail={'code':'RESTORE_REQUIRES_FILE_DATABASE'})
    target.parent.mkdir(parents=True,exist_ok=True)
    temp_path=None
    try:
        with tempfile.NamedTemporaryFile(prefix='.mgroup-restore-',suffix='.sqlite3',dir=target.parent,delete=False) as temp:
            temp.write(database_bytes);temp.flush();os.fsync(temp.fileno());temp_path=Path(temp.name)
        check=sqlite3.connect(str(temp_path))
        try:
            check.execute('PRAGMA foreign_keys=ON')
            integrity=check.execute('PRAGMA integrity_check').fetchone()[0]
            fk_errors=check.execute('PRAGMA foreign_key_check').fetchall()
            if integrity!='ok' or fk_errors:
                raise HTTPException(status_code=400,detail={'code':'RESTORED_DATABASE_INTEGRITY_FAILED'})
            required={'device_registry','members','member_cards','accounts','transactions','ledger_entries','audit_events','product_slots'}
            found={row[0] for row in check.execute("SELECT name FROM sqlite_master WHERE type='table'")}
            if not required.issubset(found):
                raise HTTPException(status_code=400,detail={'code':'BACKUP_SCHEMA_NOT_COMPATIBLE'})
        finally:
            check.close()
        # Release this request's shared database lock, then take an exclusive
        # file lock so other API connections finish before the atomic file swap.
        connection.close()
        lock_path=Path(str(target)+'.lock')
        lock_fd=os.open(lock_path,os.O_CREAT|os.O_RDWR,0o600)
        try:
            fcntl.flock(lock_fd,fcntl.LOCK_EX)
            os.replace(temp_path,target);temp_path=None
            os.chmod(target,0o600)
            for sidecar in (Path(str(target)+'-wal'),Path(str(target)+'-shm')):
                try: sidecar.unlink()
                except FileNotFoundError: pass
        finally:
            fcntl.flock(lock_fd,fcntl.LOCK_UN);os.close(lock_fd)
    finally:
        if temp_path is not None:
            try: temp_path.unlink()
            except FileNotFoundError: pass
    return {'status':'restored','integrity_check':'ok','foreign_key_errors':0,'backup_sha256':manifest['sha256'],
            'warning':'Database replaced atomically after all existing shared-lock connections completed.'}


@app.get('/api/v2/admin/audit', dependencies=[Depends(require_admin_session)])
def list_audit(connection: DB, limit: int = 100, action: str = '', entity_type: str = '',
               entity_id: str = '', request_id: str = ''):
    limit=max(1,min(limit,500))
    sql='SELECT audit_id,actor_type,actor_id,action,entity_type,entity_id,request_id,detail_json,created_at FROM audit_events WHERE 1=1'
    args=[]
    if action.strip(): sql+=' AND action LIKE ?';args.append('%'+action.strip()+'%')
    if entity_type.strip(): sql+=' AND entity_type=?';args.append(entity_type.strip())
    if entity_id.strip(): sql+=' AND entity_id LIKE ?';args.append('%'+entity_id.strip()+'%')
    if request_id.strip(): sql+=' AND request_id LIKE ?';args.append('%'+request_id.strip()+'%')
    sql+=' ORDER BY created_at DESC LIMIT ?';args.append(limit)
    rows=connection.execute(sql,args).fetchall()
    items=[]
    for row in rows:
        item=dict(row)
        try:item['detail']=json.loads(item.pop('detail_json') or '{}')
        except (TypeError,ValueError):item['detail']={}
        items.append(item)
    return {'items':items}

# Serve the canonical v2 WebUI from the same origin as the API so HttpOnly
# admin session cookies and same-origin API requests work without a second server.
WEBUI_DIR=Path(__file__).resolve().parents[2] / 'webui'
if WEBUI_DIR.is_dir():
    app.mount("/", StaticFiles(directory=str(WEBUI_DIR), html=True), name="mgroup-v2-webui")
