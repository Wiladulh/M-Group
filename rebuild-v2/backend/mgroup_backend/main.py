from contextlib import asynccontextmanager
import hashlib
import hmac
import secrets
import json
import sqlite3
from io import BytesIO
from typing import Annotated
from PIL import Image, ImageOps, UnidentifiedImageError

from fastapi import Depends, FastAPI, Header, HTTPException, UploadFile, File, Response
from pydantic import BaseModel, Field

from .config import settings
from .db import connect, initialize, transaction
from .security import hash_secret, new_id, require_admin, verify_secret


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Fail closed: without these secrets, admin auth is unavailable and card UID
    # hashes/device-key hashes would be stored without the configured pepper.
    if not settings.admin_token or not settings.device_key_pepper:
        raise RuntimeError('MGROUP_ADMIN_TOKEN and MGROUP_DEVICE_KEY_PEPPER must be configured')
    initialize(settings.database_path)
    yield

app = FastAPI(title='M-Group API v2', version='2.0.0', lifespan=lifespan)


def db_conn():
    connection = connect(settings.database_path)
    try:
        yield connection
    finally:
        connection.close()

DB = Annotated[sqlite3.Connection, Depends(db_conn)]
Admin = Annotated[None, Depends(require_admin)]

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
    pin: str | None = Field(default=None, min_length=6, max_length=12, pattern=r'^[0-9]{6,12}$')

class TopUpRequest(BaseModel):
    request_id: str = Field(min_length=8, max_length=128)
    member_id: str = Field(min_length=1, max_length=128)
    amount_minor: int = Field(gt=0, le=100_000_000)
    description: str = Field(default='Top-up saldo', max_length=200)

class MerchantAccountCreate(BaseModel):
    label: str = Field(min_length=1, max_length=120)


class CashierDeviceConfigure(BaseModel):
    operator_id: str = Field(min_length=1, max_length=128)
    operator_name: str = Field(min_length=1, max_length=120)
    operator_pin: str = Field(min_length=6, max_length=12, pattern="^[0-9]{6,12}$")
    settlement_account_id: str = Field(min_length=1, max_length=128)


class CashierPaymentRequest(BaseModel):
    request_id: str = Field(min_length=8, max_length=128)
    card_uid: str = Field(min_length=4, max_length=128)
    pin: str = Field(min_length=6, max_length=12, pattern=r'^[0-9]{6,12}$')
    amount_minor: int = Field(gt=0, le=100_000_000)


class CashierTopUpRequest(BaseModel):
    request_id: str = Field(min_length=8, max_length=128)
    card_uid: str = Field(min_length=4, max_length=128)
    operator_pin: str = Field(min_length=6, max_length=12, pattern=r'^[0-9]{6,12}$')
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


class DispenseResult(BaseModel):
    succeeded: bool
    reason: str | None = Field(default=None, max_length=200)


class ProductUpdate(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    price_minor: int = Field(gt=0, le=100_000_000)
    stock: int = Field(ge=0, le=1_000_000)

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
    connection.execute("INSERT INTO accounts(account_id,account_type,balance_minor) VALUES(?,'system',0)", (account_id,))
    return account_id


def audit(connection, action, entity_type, entity_id, request_id=None, detail=None):
    connection.execute('INSERT INTO audit_events(audit_id,actor_type,action,entity_type,entity_id,request_id,detail_json) VALUES(?,?,?,?,?,?,?)',
        (new_id('aud'), 'server', action, entity_type, entity_id, request_id, json.dumps(detail or {}, separators=(',', ':'))))


@app.get('/api/v2/ready')
def readiness(connection: DB):
    try:
        connection.execute('SELECT 1').fetchone()
    except sqlite3.Error as exc:
        raise HTTPException(status_code=503, detail={'code': 'DATABASE_NOT_READY'}) from exc
    return {'status': 'ready', 'database': 'ok'}

@app.post('/api/v2/admin/devices', status_code=201, dependencies=[Depends(require_admin)])
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


@app.get('/api/v2/admin/devices', dependencies=[Depends(require_admin)])
def admin_devices(connection: DB):
    rows=connection.execute("""SELECT registry_id,hardware_id,device_type,display_name,status,mac_address,
        device_key_hint,created_at,updated_at,last_seen_at,revoked_at FROM device_registry
        ORDER BY created_at DESC""").fetchall()
    return {'items':[dict(row) for row in rows]}

@app.post('/api/v2/admin/devices/{registry_id}/rotate-key', dependencies=[Depends(require_admin)])
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

@app.post('/api/v2/admin/devices/{registry_id}/revoke', dependencies=[Depends(require_admin)])
def revoke_device_key(registry_id: str, connection: DB):
    with transaction(connection):
        row=connection.execute("SELECT registry_id,hardware_id,status FROM device_registry WHERE registry_id=?",(registry_id,)).fetchone()
        if not row:
            raise HTTPException(status_code=404,detail={'code':'DEVICE_NOT_FOUND'})
        connection.execute("UPDATE device_registry SET status='revoked',device_key_hash=NULL,device_key_hint=NULL,revoked_at=CURRENT_TIMESTAMP,updated_at=CURRENT_TIMESTAMP WHERE registry_id=?",(registry_id,))
        connection.execute("UPDATE nfc_registration_sessions SET status='failed',error_code='CASHIER_REVOKED' WHERE registry_id=? AND status IN ('scan_pending','waiting_nfc','pin_pending','processing')",(registry_id,))
        audit(connection,'device.key.revoke','device',registry_id,detail={'hardware_id':row['hardware_id']})
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
        'SELECT product_id,name,price_minor,stock FROM product_slots WHERE registry_id=? ORDER BY product_id',
        (device['registry_id'],),
    ).fetchall()
    return {'registry_id': device['registry_id'], 'items': [dict(row) for row in rows]}


@app.post('/api/v2/devices/member-balance')
def device_member_balance(payload: MemberBalanceLookup, connection: DB,
                          x_device_key: Annotated[str | None, Header()] = None):
    device = authenticated_device(connection, x_device_key)
    if device['device_type'] not in ('cashier', 'vending'):
        raise HTTPException(status_code=403, detail={'code': 'DEVICE_TYPE_NOT_ALLOWED'})
    row = connection.execute("""
        SELECT m.member_id, m.display_name, m.status AS member_status,
               a.balance_minor, a.currency, a.status AS account_status
        FROM member_cards c
        JOIN members m ON m.member_id=c.member_id
        JOIN accounts a ON a.member_id=m.member_id AND a.account_type='member'
        WHERE c.card_uid_hash=? AND c.status='active'
    """, (card_hash(payload.card_uid),)).fetchone()
    if not row or row['member_status'] != 'active' or row['account_status'] != 'active':
        raise HTTPException(status_code=401, detail={'code': 'CARD_NOT_AUTHORIZED'})
    return {'member_id': row['member_id'], 'display_name': row['display_name'],
            'balance_minor': row['balance_minor'], 'currency': row['currency']}


@app.post('/api/v2/members', status_code=201, dependencies=[Depends(require_admin)])
def create_member(payload: MemberCreate, connection: DB):
    display_name = payload.display_name.strip()
    if not display_name:
        raise HTTPException(status_code=422, detail={'code': 'INVALID_DISPLAY_NAME'})
    account_id = new_id('acct')
    try:
        with transaction(connection):
            ids = connection.execute("SELECT member_id FROM members WHERE member_id GLOB 'NTR-[0-9]*'").fetchall()
            largest = max((int(row['member_id'][4:]) for row in ids if row['member_id'][4:].isdigit()), default=0)
            member_id = f'NTR-{largest + 1:05d}'
            profile = payload.model_dump(exclude={'display_name','nik','phone','email','pin'}, exclude_none=True)
            connection.execute('INSERT INTO members(member_id,display_name,nik,phone,email,profile_json,pin_hash) VALUES(?,?,?,?,?,?,?)',
                (member_id, display_name, payload.nik, payload.phone, payload.email,
                 json.dumps(profile, separators=(',', ':')), pin_hash(payload.pin) if payload.pin else None))
            connection.execute("INSERT INTO accounts(account_id,member_id,account_type) VALUES(?,?,'member')", (account_id, member_id))
            audit(connection, 'member.create', 'member', member_id, detail={'nik_present': bool(payload.nik)})
    except sqlite3.IntegrityError as exc:
        raise HTTPException(status_code=409, detail={'code': 'MEMBER_CREATE_CONFLICT'}) from exc
    return {'member_id': member_id, 'display_name': display_name, 'account_id': account_id,
            'nik': payload.nik, 'phone': payload.phone, 'email': payload.email,
            'balance_minor': 0, 'status': 'active', 'pin_configured': bool(payload.pin)}

@app.get('/api/v2/members', dependencies=[Depends(require_admin)])
def list_members(connection: DB):
    rows = connection.execute('SELECT m.member_id,m.display_name,m.nik,m.phone,m.email,m.profile_json,m.status,a.account_id,a.balance_minor FROM members m JOIN accounts a ON a.member_id=m.member_id ORDER BY m.created_at DESC').fetchall()
    items=[]
    for row in rows:
        item=dict(row)
        profile=json.loads(item.pop('profile_json') or '{}')
        item.update(profile)
        items.append(item)
    return {'items': items}

@app.post('/api/v2/finance/top-ups', dependencies=[Depends(require_admin)])
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


@app.post('/api/v2/admin/merchant-accounts', status_code=201, dependencies=[Depends(require_admin)])
def create_merchant_account(payload: MerchantAccountCreate, connection: DB):
    label = payload.label.strip()
    if not label:
        raise HTTPException(status_code=422, detail={'code': 'INVALID_MERCHANT_LABEL'})
    account_id = new_id('merchant')
    with transaction(connection):
        connection.execute("INSERT INTO accounts(account_id,account_type,balance_minor) VALUES(?,'merchant',0)",
                           (account_id,))
        audit(connection, 'merchant.account.create', 'account', account_id, detail={'label': label})
    return {'account_id': account_id, 'label': label, 'account_type': 'merchant', 'currency': 'IDR', 'balance_minor': 0}


@app.put('/api/v2/admin/cashier-devices/{registry_id}/configuration', dependencies=[Depends(require_admin)])
def configure_cashier_device(registry_id: str, payload: CashierDeviceConfigure, connection: DB):
    operator_id = payload.operator_id.strip()
    operator_name = payload.operator_name.strip()
    if not operator_id or not operator_name:
        raise HTTPException(status_code=422, detail={'code': 'INVALID_OPERATOR_CONFIGURATION'})
    with transaction(connection):
        device = connection.execute(
            "SELECT registry_id,hardware_id,status FROM device_registry WHERE registry_id=? AND device_type='cashier'",
            (registry_id,),
        ).fetchone()
        if not device:
            raise HTTPException(status_code=404, detail={'code': 'CASHIER_DEVICE_NOT_FOUND'})
        if device['status'] != 'active':
            raise HTTPException(status_code=409, detail={'code': 'CASHIER_DEVICE_NOT_ACTIVE'})
        settlement = connection.execute(
            "SELECT account_id,status FROM accounts WHERE account_id=? AND account_type='merchant'",
            (payload.settlement_account_id,),
        ).fetchone()
        if not settlement:
            raise HTTPException(status_code=422, detail={'code': 'MERCHANT_SETTLEMENT_ACCOUNT_REQUIRED'})
        if settlement['status'] != 'active':
            raise HTTPException(status_code=409, detail={'code': 'SETTLEMENT_ACCOUNT_NOT_ACTIVE'})
        # A cashier device has one server-side operator and one settlement target.
        # Never accept either identity/target from a payment request.
        connection.execute("""
            INSERT INTO cashier_device_config(
                registry_id, operator_id, operator_name, operator_pin_hash,
                settlement_account_id, failed_attempts, locked_until, updated_at
            ) VALUES(?,?,?,?,?,0,NULL,CURRENT_TIMESTAMP)
            ON CONFLICT(registry_id) DO UPDATE SET
                operator_id=excluded.operator_id,
                operator_name=excluded.operator_name,
                operator_pin_hash=excluded.operator_pin_hash,
                settlement_account_id=excluded.settlement_account_id,
                failed_attempts=0, locked_until=NULL, updated_at=CURRENT_TIMESTAMP
        """, (registry_id, operator_id, operator_name, pin_hash(payload.operator_pin),
              settlement['account_id']))
        audit(connection, 'cashier.device.configure', 'device', registry_id, detail={
            'operator_id': operator_id, 'settlement_account_id': settlement['account_id']
        })
    return {'registry_id': registry_id, 'operator_id': operator_id,
            'operator_name': operator_name, 'settlement_account_id': settlement['account_id'],
            'status': 'configured'}


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


def _cashier_operator_config(connection: sqlite3.Connection, device, operator_pin: str | None = None):
    config = connection.execute("""
        SELECT operator_id,operator_name,operator_pin_hash,settlement_account_id,
               failed_attempts,locked_until
        FROM cashier_device_config WHERE registry_id=?
    """, (device['registry_id'],)).fetchone()
    if not config:
        raise HTTPException(status_code=409, detail={'code': 'CASHIER_NOT_CONFIGURED'})
    if operator_pin is None:
        return config
    error = None
    with transaction(connection):
        current = connection.execute(
            'SELECT failed_attempts,locked_until,operator_pin_hash FROM cashier_device_config WHERE registry_id=?',
            (device['registry_id'],)).fetchone()
        locked = connection.execute(
            "SELECT CASE WHEN ? IS NOT NULL AND julianday(?) > julianday('now') THEN 1 ELSE 0 END",
            (current['locked_until'], current['locked_until'])).fetchone()[0]
        if locked:
            error = (429, 'CASHIER_OPERATOR_TEMPORARILY_LOCKED')
        elif not verify_pin(operator_pin, current['operator_pin_hash']):
            failures = current['failed_attempts'] + 1
            connection.execute("""
                UPDATE cashier_device_config
                SET failed_attempts=?,locked_until=CASE WHEN ?>=5 THEN datetime('now','+5 minutes') ELSE NULL END,
                    updated_at=CURRENT_TIMESTAMP WHERE registry_id=?
            """, (failures, failures, device['registry_id']))
            error = (429, 'CASHIER_OPERATOR_TEMPORARILY_LOCKED') if failures >= 5 else (401, 'INVALID_OPERATOR_PIN')
        else:
            connection.execute("""
                UPDATE cashier_device_config SET failed_attempts=0,locked_until=NULL,updated_at=CURRENT_TIMESTAMP
                WHERE registry_id=?
            """, (device['registry_id'],))
    if error:
        raise HTTPException(status_code=error[0], detail={'code': error[1]})
    return config


@app.post('/api/v2/cashier/payments', status_code=201)
def cashier_payment_v2(payload: CashierPaymentRequest, connection: DB,
                       x_device_key: Annotated[str | None, Header()] = None):
    device = authenticated_device(connection, x_device_key)
    if device['device_type'] != 'cashier':
        raise HTTPException(status_code=403, detail={'code': 'CASHIER_DEVICE_REQUIRED'})
    digest, member = _cashier_member_with_valid_pin(connection, device, payload.card_uid, payload.pin)
    config = _cashier_operator_config(connection, device)
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
                return {'transaction_id': prior['transaction_id'], 'request_id': payload.request_id,
                        'status': prior['status'], 'amount_minor': prior['amount_minor'],
                        'idempotent_replay': True}
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
                              'operator_id': config['operator_id'], 'source': 'cashier'}, separators=(',', ':'))))
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
                  {'hardware_id': device['hardware_id'], 'operator_id': config['operator_id'],
                   'settlement_account_id': settlement['account_id'], 'amount_minor': payload.amount_minor})
            balance_after = account['balance_minor'] - payload.amount_minor
    except sqlite3.IntegrityError as exc:
        raise HTTPException(status_code=409, detail={'code': 'IDEMPOTENCY_CONFLICT'}) from exc
    return {'transaction_id': transaction_id, 'request_id': payload.request_id, 'status': 'succeeded',
            'amount_minor': payload.amount_minor, 'balance_after_minor': balance_after, 'idempotent_replay': False}


@app.post('/api/v2/cashier/top-ups', status_code=201)
def cashier_top_up_v2(payload: CashierTopUpRequest, connection: DB,
                      x_device_key: Annotated[str | None, Header()] = None):
    device = authenticated_device(connection, x_device_key)
    if device['device_type'] != 'cashier':
        raise HTTPException(status_code=403, detail={'code': 'CASHIER_DEVICE_REQUIRED'})
    config = _cashier_operator_config(connection, device, payload.operator_pin)
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
                    or meta.get('operator_id') != config['operator_id'] or prior['status'] != 'succeeded'):
                    raise HTTPException(status_code=409, detail={'code': 'IDEMPOTENCY_CONFLICT'})
                return {'transaction_id': prior['transaction_id'], 'request_id': payload.request_id,
                        'status': prior['status'], 'amount_minor': prior['amount_minor'],
                        'idempotent_replay': True}
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
                  json.dumps({'card_hash': digest, 'operator_id': config['operator_id'],
                              'source': 'cashier'}, separators=(',', ':'))))
            connection.execute('UPDATE accounts SET balance_minor=balance_minor+?,updated_at=CURRENT_TIMESTAMP WHERE account_id=?',
                               (payload.amount_minor, account['account_id']))
            connection.execute('UPDATE accounts SET balance_minor=balance_minor+?,updated_at=CURRENT_TIMESTAMP WHERE account_id=?',
                               (payload.amount_minor, system_id))
            connection.execute("INSERT INTO ledger_entries(entry_id,transaction_id,account_id,direction,amount_minor) VALUES(?,?,?,'credit',?)",
                               (new_id('led'), transaction_id, account['account_id'], payload.amount_minor))
            connection.execute("INSERT INTO ledger_entries(entry_id,transaction_id,account_id,direction,amount_minor) VALUES(?,?,?,'debit',?)",
                               (new_id('led'), transaction_id, system_id, payload.amount_minor))
            audit(connection, 'cashier.top_up', 'transaction', transaction_id, payload.request_id,
                  {'hardware_id': device['hardware_id'], 'operator_id': config['operator_id'],
                   'amount_minor': payload.amount_minor})
            balance_after = account['balance_minor'] + payload.amount_minor
    except sqlite3.IntegrityError as exc:
        raise HTTPException(status_code=409, detail={'code': 'IDEMPOTENCY_CONFLICT'}) from exc
    return {'transaction_id': transaction_id, 'request_id': payload.request_id, 'status': 'succeeded',
            'amount_minor': payload.amount_minor, 'balance_after_minor': balance_after, 'idempotent_replay': False}


@app.get('/api/v2/vending/devices', dependencies=[Depends(require_admin)])
def vending_devices(connection: DB):
    rows = connection.execute("SELECT registry_id,hardware_id,display_name,status,mac_address,last_seen_at FROM device_registry WHERE device_type='vending' ORDER BY created_at DESC").fetchall()
    return {'items': [dict(row) for row in rows]}

@app.get('/api/v2/vending/devices/{registry_id}/products', dependencies=[Depends(require_admin)])
def get_products(registry_id: str, connection: DB):
    device = connection.execute("SELECT registry_id FROM device_registry WHERE registry_id=? AND device_type='vending'", (registry_id,)).fetchone()
    if not device:
        raise HTTPException(status_code=404, detail={'code': 'VENDING_DEVICE_NOT_FOUND'})
    rows = connection.execute("""SELECT p.product_id,p.name,p.price_minor,p.stock,p.nfc_promo_percent,p.qris_promo_percent,
        i.sha256 AS image_sha256,i.byte_size AS image_size,i.content_type
        FROM product_slots p LEFT JOIN product_images i ON i.registry_id=p.registry_id AND i.product_id=p.product_id
        WHERE p.registry_id=? ORDER BY p.product_id""", (registry_id,)).fetchall()
    items=[]
    for row in rows:
        item=dict(row)
        item['image_url']=f"/api/v2/admin/vending/devices/{registry_id}/products/{item['product_id']}/image" if item.get('image_sha256') else None
        items.append(item)
    return {'registry_id': registry_id, 'items': items}

@app.put('/api/v2/vending/devices/{registry_id}/products/{product_id}', dependencies=[Depends(require_admin)])
def update_product(registry_id: str, product_id: int, payload: ProductUpdate, connection: DB):
    if product_id not in range(1, 6):
        raise HTTPException(status_code=422, detail={'code': 'INVALID_PRODUCT_SLOT'})
    normalized_name = payload.name.strip()
    if not normalized_name:
        raise HTTPException(status_code=422, detail={'code': 'INVALID_PRODUCT_NAME'})
    with transaction(connection):
        result = connection.execute('UPDATE product_slots SET name=?,price_minor=?,stock=?,updated_at=CURRENT_TIMESTAMP WHERE registry_id=? AND product_id=?', (normalized_name, payload.price_minor, payload.stock, registry_id, product_id))
        if result.rowcount != 1:
            raise HTTPException(status_code=404, detail={'code': 'PRODUCT_SLOT_NOT_FOUND'})
        connection.execute('INSERT INTO audit_events(audit_id,actor_type,action,entity_type,entity_id,detail_json) VALUES(?,?,?,?,?,?)', (new_id('aud'), 'admin', 'vending.product.update', 'product_slot', f'{registry_id}:{product_id}', json.dumps({**payload.model_dump(), 'name': normalized_name})))
    return {'registry_id': registry_id, 'product_id': product_id, **payload.model_dump(), 'name': normalized_name, 'nfc_promo_percent': 0, 'qris_promo_percent': 0}

@app.post('/api/v2/admin/vending/devices/{registry_id}/products/{product_id}/image', dependencies=[Depends(require_admin)])
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
        image=ImageOps.exif_transpose(image)
        image.load()
        if image.mode not in ('RGB','RGBA'):
            image=image.convert('RGBA' if 'A' in image.getbands() else 'RGB')
        image.thumbnail((1600,1600),Image.Resampling.LANCZOS)
        output=BytesIO()
        image.save(output,format='WEBP',quality=84,method=6)
        optimized=output.getvalue()
    except HTTPException:
        raise
    except (UnidentifiedImageError,OSError,ValueError) as exc:
        raise HTTPException(status_code=415,detail={'code':'INVALID_IMAGE_CONTENT'}) from exc
    if not optimized or len(optimized)>2*1024*1024:
        raise HTTPException(status_code=413,detail={'code':'OPTIMIZED_IMAGE_MUST_BE_2MB_OR_SMALLER'})
    digest=hashlib.sha256(optimized).hexdigest()
    with transaction(connection):
        slot=connection.execute("SELECT 1 FROM product_slots WHERE registry_id=? AND product_id=?",(registry_id,product_id)).fetchone()
        if not slot:
            raise HTTPException(status_code=404,detail={'code':'PRODUCT_SLOT_NOT_FOUND'})
        connection.execute("""INSERT INTO product_images(registry_id,product_id,content_type,image_data,sha256,byte_size,updated_at)
            VALUES(?,?, 'image/webp',?,?,?,CURRENT_TIMESTAMP)
            ON CONFLICT(registry_id,product_id) DO UPDATE SET content_type=excluded.content_type,image_data=excluded.image_data,
            sha256=excluded.sha256,byte_size=excluded.byte_size,updated_at=CURRENT_TIMESTAMP""",
            (registry_id,product_id,optimized,digest,len(optimized)))
        audit(connection,'vending.product.image.upload','product_slot',f'{registry_id}:{product_id}',
              detail={'sha256':digest,'byte_size':len(optimized),'content_type':'image/webp'})
    return {'registry_id':registry_id,'product_id':product_id,'sha256':digest,'byte_size':len(optimized),'content_type':'image/webp'}

@app.get('/api/v2/admin/vending/devices/{registry_id}/products/{product_id}/image', dependencies=[Depends(require_admin)])
def get_product_image(registry_id: str, product_id: int, connection: DB):
    row=connection.execute("SELECT image_data,sha256,content_type FROM product_images WHERE registry_id=? AND product_id=?",(registry_id,product_id)).fetchone()
    if not row:
        raise HTTPException(status_code=404,detail={'code':'PRODUCT_IMAGE_NOT_FOUND'})
    return Response(content=bytes(row['image_data']),media_type=row['content_type'],headers={'ETag':'"'+row['sha256']+'"','Cache-Control':'private, max-age=300'})

@app.post('/api/v2/members/{member_id}/cards', status_code=201, dependencies=[Depends(require_admin)])
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


@app.post('/api/v2/admin/members/{member_id}/nfc-registration', status_code=201, dependencies=[Depends(require_admin)])
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

@app.get('/api/v2/admin/nfc-registration/{session_id}', dependencies=[Depends(require_admin)])
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
                    or meta.get('product_id') != payload.product_id or meta.get('card_hash') != digest):
                    raise HTTPException(status_code=409, detail={'code': 'IDEMPOTENCY_CONFLICT'})
                return {'transaction_id': prior['transaction_id'], 'status': prior['status'],
                        'amount_minor': prior['amount_minor'], 'idempotent_replay': True}
            member = connection.execute("SELECT m.member_id,m.status,m.pin_hash FROM member_cards c JOIN members m ON m.member_id=c.member_id WHERE c.card_uid_hash=? AND c.status='active'",
                (digest,)).fetchone()
            if not member or member['status'] != 'active':
                raise HTTPException(status_code=401, detail={'code': 'CARD_NOT_AUTHORIZED'})
            if not verify_pin(payload.pin, member['pin_hash']):
                raise HTTPException(status_code=401, detail={'code': 'INVALID_PIN'})
            product = connection.execute('SELECT name,price_minor,stock FROM product_slots WHERE registry_id=? AND product_id=?',
                (device['registry_id'], payload.product_id)).fetchone()
            if not product:
                raise HTTPException(status_code=404, detail={'code': 'PRODUCT_SLOT_NOT_FOUND'})
            if product['stock'] < 1:
                raise HTTPException(status_code=409, detail={'code': 'OUT_OF_STOCK'})
            if product['price_minor'] <= 0:
                raise HTTPException(status_code=409, detail={'code': 'PRODUCT_PRICE_NOT_CONFIGURED'})
            account = connection.execute("SELECT account_id,balance_minor,status FROM accounts WHERE member_id=? AND account_type='member'",
                (member['member_id'],)).fetchone()
            if not account or account['status'] != 'active':
                raise HTTPException(status_code=409, detail={'code': 'ACCOUNT_NOT_ACTIVE'})
            amount = product['price_minor']
            if account['balance_minor'] < amount:
                raise HTTPException(status_code=409, detail={'code': 'INSUFFICIENT_BALANCE'})
            system_id = ensure_system_account(connection)
            system_account = connection.execute("SELECT balance_minor FROM accounts WHERE account_id=? AND account_type='system'", (system_id,)).fetchone()
            if not system_account or system_account['balance_minor'] < amount:
                raise HTTPException(status_code=409, detail={'code': 'SYSTEM_ACCOUNT_INSUFFICIENT_BALANCE'})
            transaction_id = new_id('txn')
            metadata = {'product_id': payload.product_id, 'registry_id': device['registry_id'],
                        'card_hash': digest, 'product_name': product['name'], 'dispense_status': 'pending'}
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
    return {'transaction_id': transaction_id, 'status': 'pending', 'amount_minor': amount,
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
            return {'transaction_id': transaction_id, 'status': row['status'],
                    'dispense_status': meta['dispense_status'], 'idempotent_replay': True}
        if payload.succeeded:
            meta['dispense_status'] = 'succeeded'
            connection.execute("UPDATE transactions SET status='succeeded',metadata_json=?,completed_at=CURRENT_TIMESTAMP WHERE transaction_id=?",
                (json.dumps(meta), transaction_id))
            audit(connection, 'vending.dispense.succeeded', 'transaction', transaction_id, row['request_id'])
            return {'transaction_id': transaction_id, 'status': 'succeeded', 'dispense_status': 'succeeded',
                    'idempotent_replay': False}
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
    return {'transaction_id': transaction_id, 'status': 'reversed', 'dispense_status': 'failed',
            'refunded_amount_minor': row['amount_minor'], 'idempotent_replay': False}


@app.get('/api/v2/admin/finance/reconciliation', dependencies=[Depends(require_admin)])
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
        'status': 'attention_required' if transaction_imbalances or account_mismatches else 'ok',
        'transaction_imbalances': transaction_imbalances,
        'account_mismatches': account_mismatches,
        'pending_purchases': pending_purchases,
        'pending_purchases_require_review': bool(pending_purchases),
    }


@app.get('/api/v2/admin/audit', dependencies=[Depends(require_admin)])
def list_audit(connection: DB, limit: int = 100):
    limit = max(1, min(limit, 500))
    rows = connection.execute('SELECT audit_id,actor_type,actor_id,action,entity_type,entity_id,request_id,detail_json,created_at FROM audit_events ORDER BY created_at DESC LIMIT ?', (limit,)).fetchall()
    return {'items': [dict(row) for row in rows]}
