from contextlib import asynccontextmanager
from pathlib import Path
import hashlib
import hmac
import secrets
import json
import sqlite3
from typing import Annotated

from fastapi import Depends, FastAPI, Header, HTTPException, Request
from pydantic import BaseModel, Field

from .config import settings
from .db import connect, initialize, transaction
from .security import hash_secret, new_id, require_admin, verify_secret


@asynccontextmanager
async def lifespan(app: FastAPI):
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
    pin: str | None = Field(default=None, min_length=6, max_length=12, pattern=r'^[0-9]{6,12}')

class TopUpRequest(BaseModel):
    request_id: str = Field(min_length=8, max_length=128)
    member_id: str = Field(min_length=1, max_length=128)
    amount_minor: int = Field(gt=0, le=100_000_000)
    description: str = Field(default='Top-up saldo', max_length=200)

class ProductUpdate(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    price_minor: int = Field(ge=0, le=100_000_000)
    stock: int = Field(ge=0, le=1_000_000)

@app.get('/api/v2/health')
def health():
    return {'status': 'ok', 'service': 'mgroup-api', 'version': '2.0.0'}


def pin_hash(pin: str) -> str:
    salt = secrets.token_hex(16)
    digest = hashlib.pbkdf2_hmac('sha256', pin.encode('utf-8'), salt.encode('ascii'), 310_000).hex()
    return 'pbkdf2_sha256' + '

@app.get('/api/v2/ready')
def readiness(connection: DB):
    try:
        connection.execute('SELECT 1').fetchone()
    except sqlite3.Error as exc:
        raise HTTPException(status_code=503, detail={'code': 'DATABASE_NOT_READY'}) from exc
    return {'status': 'ready', 'database': 'ok'}

@app.post('/api/v2/admin/devices', status_code=201, dependencies=[Depends(require_admin)])
def register_device(payload: dict, connection: DB):
    hardware_id = str(payload.get('hardware_id', '')).strip()
    device_type = payload.get('device_type')
    display_name = str(payload.get('display_name', '')).strip()
    if not hardware_id or len(hardware_id) > 128 or device_type not in ('cashier', 'vending'):
        raise HTTPException(status_code=422, detail={'code': 'INVALID_DEVICE_REGISTRATION'})
    registry_id = new_id('reg')
    device_key = secrets.token_urlsafe(32)
    try:
        with transaction(connection):
            connection.execute('INSERT INTO device_registry(registry_id,hardware_id,device_type,display_name,status,device_key_hash,device_key_hint) VALUES(?,?,?,?,?,?,?)',
                (registry_id, hardware_id, device_type, display_name, 'active', hash_secret(device_key, settings.device_key_pepper), device_key[-4:]))
            connection.execute('INSERT INTO device_events(event_id,registry_id,hardware_id,event_type,detail_json) VALUES(?,?,?,?,?)',
                (new_id('evt'), registry_id, hardware_id, 'device.provisioned', json.dumps({'device_type': device_type})))
            if device_type == 'vending':
                for product_id in range(1, 6):
                    connection.execute('INSERT INTO product_slots(registry_id,product_id,name,price_minor,stock) VALUES(?,?,?,?,?)', (registry_id, product_id, f'Produk {product_id}', 0, 0))
            connection.execute('INSERT INTO audit_events(audit_id,actor_type,action,entity_type,entity_id,detail_json) VALUES(?,?,?,?,?,?)',
                (new_id('aud'), 'admin', 'device.provision', 'device', registry_id, json.dumps({'hardware_id': hardware_id, 'device_type': device_type})))
    except sqlite3.IntegrityError as exc:
        raise HTTPException(status_code=409, detail={'code': 'DEVICE_ALREADY_REGISTERED'}) from exc
    return {'registry_id': registry_id, 'hardware_id': hardware_id, 'device_type': device_type, 'device_key': secrets_token, 'warning': 'Simpan device_key sekarang; nilainya tidak dapat dibaca ulang.'}


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
            connection.execute('INSERT INTO members(member_id,display_name,pin_hash) VALUES(?,?,?)',
                (member_id, display_name, pin_hash(payload.pin) if payload.pin else None))
            connection.execute("INSERT INTO accounts(account_id,member_id,account_type) VALUES(?,?,'member')", (account_id, member_id))
            audit(connection, 'member.create', 'member', member_id)
    except sqlite3.IntegrityError as exc:
        raise HTTPException(status_code=409, detail={'code': 'MEMBER_CREATE_CONFLICT'}) from exc
    return {'member_id': member_id, 'display_name': display_name, 'account_id': account_id,
            'balance_minor': 0, 'status': 'active', 'pin_configured': bool(payload.pin)}

@app.get('/api/v2/members', dependencies=[Depends(require_admin)])
def list_members(connection: DB):
    rows = connection.execute('SELECT m.member_id,m.display_name,m.status,a.balance_minor FROM members m JOIN accounts a ON a.member_id=m.member_id ORDER BY m.created_at DESC').fetchall()
    return {'items': [dict(row) for row in rows]}

@app.post('/api/v2/finance/top-ups', dependencies=[Depends(require_admin)])
def top_up(payload: TopUpRequest, connection: DB):
    transaction_id = new_id('txn')
    try:
        with transaction(connection):
            prior = connection.execute("SELECT transaction_id,status,member_id,amount_minor,transaction_type FROM transactions WHERE request_id=?", (payload.request_id,)).fetchone()
            if prior:
                if prior['member_id'] != payload.member_id or prior['amount_minor'] != payload.amount_minor or prior['transaction_type'] != 'top_up' or prior['status'] != 'succeeded':
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
            connection.execute("INSERT INTO ledger_entries(entry_id,transaction_id,account_id,direction,amount_minor) VALUES(?,?,?,'credit',?)", (new_id('led'), transaction_id, account['account_id'], payload.amount_minor))
            connection.execute("INSERT INTO ledger_entries(entry_id,transaction_id,account_id,direction,amount_minor) VALUES(?,?,?,'debit',?)", (new_id('led'), transaction_id, system_account_id, payload.amount_minor))
            audit(connection, 'finance.top_up', 'transaction', transaction_id, payload.request_id, {'member_id': payload.member_id, 'amount_minor': payload.amount_minor})
    except sqlite3.IntegrityError as exc:
        raise HTTPException(status_code=409, detail={'code': 'IDEMPOTENCY_CONFLICT'}) from exc
    return {'transaction_id': transaction_id, 'status': 'succeeded', 'idempotent_replay': False}


@app.get('/api/v2/vending/devices', dependencies=[Depends(require_admin)])
def vending_devices(connection: DB):
    rows = connection.execute("SELECT registry_id,hardware_id,display_name,status,mac_address,last_seen_at FROM device_registry WHERE device_type='vending' ORDER BY created_at DESC").fetchall()
    return {'items': [dict(row) for row in rows]}

@app.get('/api/v2/vending/devices/{registry_id}/products', dependencies=[Depends(require_admin)])
def get_products(registry_id: str, connection: DB):
    device = connection.execute("SELECT registry_id FROM device_registry WHERE registry_id=? AND device_type='vending'", (registry_id,)).fetchone()
    if not device:
        raise HTTPException(status_code=404, detail={'code': 'VENDING_DEVICE_NOT_FOUND'})
    rows = connection.execute('SELECT product_id,name,price_minor,stock,image_path,nfc_promo_percent,qris_promo_percent FROM product_slots WHERE registry_id=? ORDER BY product_id', (registry_id,)).fetchall()
    return {'registry_id': registry_id, 'items': [dict(row) for row in rows]}

@app.put('/api/v2/vending/devices/{registry_id}/products/{product_id}', dependencies=[Depends(require_admin)])
def update_product(registry_id: str, product_id: int, payload: ProductUpdate, connection: DB):
    if product_id not in range(1, 6):
        raise HTTPException(status_code=422, detail={'code': 'INVALID_PRODUCT_SLOT'})
    with transaction(connection):
        result = connection.execute('UPDATE product_slots SET name=?,price_minor=?,stock=?,updated_at=CURRENT_TIMESTAMP WHERE registry_id=? AND product_id=?', (payload.name.strip(), payload.price_minor, payload.stock, registry_id, product_id))
        if result.rowcount != 1:
            raise HTTPException(status_code=404, detail={'code': 'PRODUCT_SLOT_NOT_FOUND'})
        connection.execute('INSERT INTO audit_events(audit_id,actor_type,action,entity_type,entity_id,detail_json) VALUES(?,?,?,?,?,?)', (new_id('aud'), 'admin', 'vending.product.update', 'product_slot', f'{registry_id}:{product_id}', json.dumps(payload.model_dump())))
    return {'registry_id': registry_id, 'product_id': product_id, **payload.model_dump(), 'nfc_promo_percent': 0, 'qris_promo_percent': 0}

@app.get('/api/v2/admin/audit', dependencies=[Depends(require_admin)])
def list_audit(connection: DB, limit: int = 100):
    limit = max(1, min(limit, 500))
    rows = connection.execute('SELECT audit_id,actor_type,actor_id,action,entity_type,entity_id,request_id,detail_json,created_at FROM audit_events ORDER BY created_at DESC LIMIT ?', (limit,)).fetchall()
    return {'items': [dict(row) for row in rows]}
)

class CardEnroll(BaseModel):
    card_uid: str = Field(min_length=4, max_length=128)

class PurchaseRequest(BaseModel):
    request_id: str = Field(min_length=8, max_length=128)
    card_uid: str = Field(min_length=4, max_length=128)
    pin: str = Field(min_length=6, max_length=12, pattern=r'^\\d{6,12}

class TopUpRequest(BaseModel):
    request_id: str = Field(min_length=8, max_length=128)
    member_id: str = Field(min_length=1, max_length=128)
    amount_minor: int = Field(gt=0, le=100_000_000)
    description: str = Field(default='Top-up saldo', max_length=200)

class PurchaseRequest(BaseModel):
    request_id: str = Field(min_length=8, max_length=128)
    member_id: str = Field(min_length=1, max_length=128)
    product_id: int = Field(ge=1, le=5)
    payment_method: str = Field(pattern='^(nfc|qris)$')

class ProductUpdate(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    price_minor: int = Field(ge=0, le=100_000_000)
    stock: int = Field(ge=0, le=1_000_000)

@app.get('/api/v2/health')
def health():
    return {'status': 'ok', 'service': 'mgroup-api', 'version': '2.0.0'}

@app.get('/api/v2/ready')
def readiness(connection: DB):
    try:
        connection.execute('SELECT 1').fetchone()
    except sqlite3.Error as exc:
        raise HTTPException(status_code=503, detail={'code': 'DATABASE_NOT_READY'}) from exc
    return {'status': 'ready', 'database': 'ok'}

@app.post('/api/v2/admin/devices', status_code=201, dependencies=[Depends(require_admin)])
def register_device(payload: dict, connection: DB):
    hardware_id = str(payload.get('hardware_id', '')).strip()
    device_type = payload.get('device_type')
    display_name = str(payload.get('display_name', '')).strip()
    if not hardware_id or len(hardware_id) > 128 or device_type not in ('cashier', 'vending'):
        raise HTTPException(status_code=422, detail={'code': 'INVALID_DEVICE_REGISTRATION'})
    registry_id = new_id('reg')
    device_key = secrets_token = __import__('secrets').token_urlsafe(32)
    try:
        with transaction(connection):
            connection.execute('INSERT INTO device_registry(registry_id,hardware_id,device_type,display_name,status,device_key_hash,device_key_hint) VALUES(?,?,?,?,?,?,?)',
                (registry_id, hardware_id, device_type, display_name, 'active', hash_secret(device_key, settings.device_key_pepper), device_key[-4:]))
            connection.execute('INSERT INTO device_events(event_id,registry_id,hardware_id,event_type,detail_json) VALUES(?,?,?,?,?)',
                (new_id('evt'), registry_id, hardware_id, 'device.provisioned', json.dumps({'device_type': device_type})))
            if device_type == 'vending':
                for product_id in range(1, 6):
                    connection.execute('INSERT INTO product_slots(registry_id,product_id,name,price_minor,stock) VALUES(?,?,?,?,?)', (registry_id, product_id, f'Produk {product_id}', 0, 0))
            connection.execute('INSERT INTO audit_events(audit_id,actor_type,action,entity_type,entity_id,detail_json) VALUES(?,?,?,?,?,?)',
                (new_id('aud'), 'admin', 'device.provision', 'device', registry_id, json.dumps({'hardware_id': hardware_id, 'device_type': device_type})))
    except sqlite3.IntegrityError as exc:
        raise HTTPException(status_code=409, detail={'code': 'DEVICE_ALREADY_REGISTERED'}) from exc
    return {'registry_id': registry_id, 'hardware_id': hardware_id, 'device_type': device_type, 'device_key': secrets_token, 'warning': 'Simpan device_key sekarang; nilainya tidak dapat dibaca ulang.'}


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

@app.post('/api/v2/members', status_code=201, dependencies=[Depends(require_admin)])
def create_member(payload: MemberCreate, connection: DB):
    member_id = 'NTR-' + str(connection.execute("SELECT COUNT(*) + 1 FROM members").fetchone()[0]).zfill(5)
    account_id = new_id('acct')
    try:
        with transaction(connection):
            connection.execute('INSERT INTO members(member_id,display_name) VALUES(?,?)', (member_id, payload.display_name.strip()))
            connection.execute("INSERT INTO accounts(account_id,member_id,account_type) VALUES(?,?,'member')", (account_id, member_id))
            connection.execute('INSERT INTO audit_events(audit_id,actor_type,action,entity_type,entity_id) VALUES(?,?,?,?,?)', (new_id('aud'), 'admin', 'member.create', 'member', member_id))
    except sqlite3.IntegrityError as exc:
        raise HTTPException(status_code=409, detail={'code': 'MEMBER_CREATE_CONFLICT'}) from exc
    return {'member_id': member_id, 'display_name': payload.display_name.strip(), 'account_id': account_id, 'balance_minor': 0, 'status': 'active'}

@app.get('/api/v2/members', dependencies=[Depends(require_admin)])
def list_members(connection: DB):
    rows = connection.execute('SELECT m.member_id,m.display_name,m.status,a.balance_minor FROM members m JOIN accounts a ON a.member_id=m.member_id ORDER BY m.created_at DESC').fetchall()
    return {'items': [dict(row) for row in rows]}

@app.post('/api/v2/finance/top-ups', dependencies=[Depends(require_admin)])
def top_up(payload: TopUpRequest, connection: DB):
    prior = connection.execute('SELECT transaction_id,status,member_id,amount_minor FROM transactions WHERE request_id=?', (payload.request_id,)).fetchone()
    if prior:
        if prior['member_id'] != payload.member_id or prior['amount_minor'] != payload.amount_minor or prior['status'] != 'succeeded':
            raise HTTPException(status_code=409, detail={'code': 'IDEMPOTENCY_CONFLICT'})
        return {'transaction_id': prior['transaction_id'], 'status': prior['status'], 'idempotent_replay': True}
    account = connection.execute("SELECT account_id,balance_minor,status FROM accounts WHERE member_id=? AND account_type='member'", (payload.member_id,)).fetchone()
    if not account:
        raise HTTPException(status_code=404, detail={'code': 'MEMBER_ACCOUNT_NOT_FOUND'})
    if account['status'] != 'active':
        raise HTTPException(status_code=409, detail={'code': 'ACCOUNT_NOT_ACTIVE'})
    transaction_id = new_id('txn')
    system_account = connection.execute("SELECT account_id FROM accounts WHERE account_type='system' LIMIT 1").fetchone()
    with transaction(connection):
        if not system_account:
            system_id = new_id('acct')
            connection.execute("INSERT INTO accounts(account_id,account_type,balance_minor) VALUES(?,'system',0)", (system_id,))
            system_account_id = system_id
        else:
            system_account_id = system_account['account_id']
        connection.execute("INSERT INTO transactions(transaction_id,request_id,member_id,transaction_type,amount_minor,status,metadata_json,completed_at) VALUES(?,?,?,'top_up',?,'succeeded',?,CURRENT_TIMESTAMP)", (transaction_id, payload.request_id, payload.member_id, payload.amount_minor, json.dumps({'description': payload.description})))
        connection.execute('UPDATE accounts SET balance_minor=balance_minor+?,updated_at=CURRENT_TIMESTAMP WHERE account_id=?', (payload.amount_minor, account['account_id']))
        connection.execute("INSERT INTO ledger_entries(entry_id,transaction_id,account_id,direction,amount_minor) VALUES(?,?,?,'credit',?)", (new_id('led'), transaction_id, account['account_id'], payload.amount_minor))
        connection.execute("INSERT INTO ledger_entries(entry_id,transaction_id,account_id,direction,amount_minor) VALUES(?,?,?,'debit',?)", (new_id('led'), transaction_id, system_account_id, payload.amount_minor))
        connection.execute('INSERT INTO audit_events(audit_id,actor_type,action,entity_type,entity_id,request_id,detail_json) VALUES(?,?,?,?,?,?,?)', (new_id('aud'), 'admin', 'finance.top_up', 'transaction', transaction_id, payload.request_id, json.dumps({'member_id': payload.member_id, 'amount_minor': payload.amount_minor})))
    return {'transaction_id': transaction_id, 'status': 'succeeded', 'idempotent_replay': False}

@app.get('/api/v2/vending/devices', dependencies=[Depends(require_admin)])
def vending_devices(connection: DB):
    rows = connection.execute("SELECT registry_id,hardware_id,display_name,status,mac_address,last_seen_at FROM device_registry WHERE device_type='vending' ORDER BY created_at DESC").fetchall()
    return {'items': [dict(row) for row in rows]}

@app.get('/api/v2/vending/devices/{registry_id}/products', dependencies=[Depends(require_admin)])
def get_products(registry_id: str, connection: DB):
    device = connection.execute("SELECT registry_id FROM device_registry WHERE registry_id=? AND device_type='vending'", (registry_id,)).fetchone()
    if not device:
        raise HTTPException(status_code=404, detail={'code': 'VENDING_DEVICE_NOT_FOUND'})
    rows = connection.execute('SELECT product_id,name,price_minor,stock,image_path,nfc_promo_percent,qris_promo_percent FROM product_slots WHERE registry_id=? ORDER BY product_id', (registry_id,)).fetchall()
    return {'registry_id': registry_id, 'items': [dict(row) for row in rows]}

@app.put('/api/v2/vending/devices/{registry_id}/products/{product_id}', dependencies=[Depends(require_admin)])
def update_product(registry_id: str, product_id: int, payload: ProductUpdate, connection: DB):
    if product_id not in range(1, 6):
        raise HTTPException(status_code=422, detail={'code': 'INVALID_PRODUCT_SLOT'})
    with transaction(connection):
        result = connection.execute('UPDATE product_slots SET name=?,price_minor=?,stock=?,updated_at=CURRENT_TIMESTAMP WHERE registry_id=? AND product_id=?', (payload.name.strip(), payload.price_minor, payload.stock, registry_id, product_id))
        if result.rowcount != 1:
            raise HTTPException(status_code=404, detail={'code': 'PRODUCT_SLOT_NOT_FOUND'})
        connection.execute('INSERT INTO audit_events(audit_id,actor_type,action,entity_type,entity_id,detail_json) VALUES(?,?,?,?,?,?)', (new_id('aud'), 'admin', 'vending.product.update', 'product_slot', f'{registry_id}:{product_id}', json.dumps(payload.model_dump())))
    return {'registry_id': registry_id, 'product_id': product_id, **payload.model_dump(), 'nfc_promo_percent': 0, 'qris_promo_percent': 0}

@app.get('/api/v2/admin/audit', dependencies=[Depends(require_admin)])
def list_audit(connection: DB, limit: int = 100):
    limit = max(1, min(limit, 500))
    rows = connection.execute('SELECT audit_id,actor_type,actor_id,action,entity_type,entity_id,request_id,detail_json,created_at FROM audit_events ORDER BY created_at DESC LIMIT ?', (limit,)).fetchall()
    return {'items': [dict(row) for row in rows]}
)
    product_id: int = Field(ge=1, le=5)

class DispenseResult(BaseModel):
    succeeded: bool
    reason: str | None = Field(default=None, max_length=200)

class TopUpRequest(BaseModel):
    request_id: str = Field(min_length=8, max_length=128)
    member_id: str = Field(min_length=1, max_length=128)
    amount_minor: int = Field(gt=0, le=100_000_000)
    description: str = Field(default='Top-up saldo', max_length=200)

class PurchaseRequest(BaseModel):
    request_id: str = Field(min_length=8, max_length=128)
    member_id: str = Field(min_length=1, max_length=128)
    product_id: int = Field(ge=1, le=5)
    payment_method: str = Field(pattern='^(nfc|qris)$')

class ProductUpdate(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    price_minor: int = Field(ge=0, le=100_000_000)
    stock: int = Field(ge=0, le=1_000_000)

@app.get('/api/v2/health')
def health():
    return {'status': 'ok', 'service': 'mgroup-api', 'version': '2.0.0'}

@app.get('/api/v2/ready')
def readiness(connection: DB):
    try:
        connection.execute('SELECT 1').fetchone()
    except sqlite3.Error as exc:
        raise HTTPException(status_code=503, detail={'code': 'DATABASE_NOT_READY'}) from exc
    return {'status': 'ready', 'database': 'ok'}

@app.post('/api/v2/admin/devices', status_code=201, dependencies=[Depends(require_admin)])
def register_device(payload: dict, connection: DB):
    hardware_id = str(payload.get('hardware_id', '')).strip()
    device_type = payload.get('device_type')
    display_name = str(payload.get('display_name', '')).strip()
    if not hardware_id or len(hardware_id) > 128 or device_type not in ('cashier', 'vending'):
        raise HTTPException(status_code=422, detail={'code': 'INVALID_DEVICE_REGISTRATION'})
    registry_id = new_id('reg')
    device_key = secrets_token = __import__('secrets').token_urlsafe(32)
    try:
        with transaction(connection):
            connection.execute('INSERT INTO device_registry(registry_id,hardware_id,device_type,display_name,status,device_key_hash,device_key_hint) VALUES(?,?,?,?,?,?,?)',
                (registry_id, hardware_id, device_type, display_name, 'active', hash_secret(device_key, settings.device_key_pepper), device_key[-4:]))
            connection.execute('INSERT INTO device_events(event_id,registry_id,hardware_id,event_type,detail_json) VALUES(?,?,?,?,?)',
                (new_id('evt'), registry_id, hardware_id, 'device.provisioned', json.dumps({'device_type': device_type})))
            if device_type == 'vending':
                for product_id in range(1, 6):
                    connection.execute('INSERT INTO product_slots(registry_id,product_id,name,price_minor,stock) VALUES(?,?,?,?,?)', (registry_id, product_id, f'Produk {product_id}', 0, 0))
            connection.execute('INSERT INTO audit_events(audit_id,actor_type,action,entity_type,entity_id,detail_json) VALUES(?,?,?,?,?,?)',
                (new_id('aud'), 'admin', 'device.provision', 'device', registry_id, json.dumps({'hardware_id': hardware_id, 'device_type': device_type})))
    except sqlite3.IntegrityError as exc:
        raise HTTPException(status_code=409, detail={'code': 'DEVICE_ALREADY_REGISTERED'}) from exc
    return {'registry_id': registry_id, 'hardware_id': hardware_id, 'device_type': device_type, 'device_key': secrets_token, 'warning': 'Simpan device_key sekarang; nilainya tidak dapat dibaca ulang.'}


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

@app.post('/api/v2/members', status_code=201, dependencies=[Depends(require_admin)])
def create_member(payload: MemberCreate, connection: DB):
    member_id = 'NTR-' + str(connection.execute("SELECT COUNT(*) + 1 FROM members").fetchone()[0]).zfill(5)
    account_id = new_id('acct')
    try:
        with transaction(connection):
            connection.execute('INSERT INTO members(member_id,display_name) VALUES(?,?)', (member_id, payload.display_name.strip()))
            connection.execute("INSERT INTO accounts(account_id,member_id,account_type) VALUES(?,?,'member')", (account_id, member_id))
            connection.execute('INSERT INTO audit_events(audit_id,actor_type,action,entity_type,entity_id) VALUES(?,?,?,?,?)', (new_id('aud'), 'admin', 'member.create', 'member', member_id))
    except sqlite3.IntegrityError as exc:
        raise HTTPException(status_code=409, detail={'code': 'MEMBER_CREATE_CONFLICT'}) from exc
    return {'member_id': member_id, 'display_name': payload.display_name.strip(), 'account_id': account_id, 'balance_minor': 0, 'status': 'active'}

@app.get('/api/v2/members', dependencies=[Depends(require_admin)])
def list_members(connection: DB):
    rows = connection.execute('SELECT m.member_id,m.display_name,m.status,a.balance_minor FROM members m JOIN accounts a ON a.member_id=m.member_id ORDER BY m.created_at DESC').fetchall()
    return {'items': [dict(row) for row in rows]}

@app.post('/api/v2/finance/top-ups', dependencies=[Depends(require_admin)])
def top_up(payload: TopUpRequest, connection: DB):
    prior = connection.execute('SELECT transaction_id,status,member_id,amount_minor FROM transactions WHERE request_id=?', (payload.request_id,)).fetchone()
    if prior:
        if prior['member_id'] != payload.member_id or prior['amount_minor'] != payload.amount_minor or prior['status'] != 'succeeded':
            raise HTTPException(status_code=409, detail={'code': 'IDEMPOTENCY_CONFLICT'})
        return {'transaction_id': prior['transaction_id'], 'status': prior['status'], 'idempotent_replay': True}
    account = connection.execute("SELECT account_id,balance_minor,status FROM accounts WHERE member_id=? AND account_type='member'", (payload.member_id,)).fetchone()
    if not account:
        raise HTTPException(status_code=404, detail={'code': 'MEMBER_ACCOUNT_NOT_FOUND'})
    if account['status'] != 'active':
        raise HTTPException(status_code=409, detail={'code': 'ACCOUNT_NOT_ACTIVE'})
    transaction_id = new_id('txn')
    system_account = connection.execute("SELECT account_id FROM accounts WHERE account_type='system' LIMIT 1").fetchone()
    with transaction(connection):
        if not system_account:
            system_id = new_id('acct')
            connection.execute("INSERT INTO accounts(account_id,account_type,balance_minor) VALUES(?,'system',0)", (system_id,))
            system_account_id = system_id
        else:
            system_account_id = system_account['account_id']
        connection.execute("INSERT INTO transactions(transaction_id,request_id,member_id,transaction_type,amount_minor,status,metadata_json,completed_at) VALUES(?,?,?,'top_up',?,'succeeded',?,CURRENT_TIMESTAMP)", (transaction_id, payload.request_id, payload.member_id, payload.amount_minor, json.dumps({'description': payload.description})))
        connection.execute('UPDATE accounts SET balance_minor=balance_minor+?,updated_at=CURRENT_TIMESTAMP WHERE account_id=?', (payload.amount_minor, account['account_id']))
        connection.execute("INSERT INTO ledger_entries(entry_id,transaction_id,account_id,direction,amount_minor) VALUES(?,?,?,'credit',?)", (new_id('led'), transaction_id, account['account_id'], payload.amount_minor))
        connection.execute("INSERT INTO ledger_entries(entry_id,transaction_id,account_id,direction,amount_minor) VALUES(?,?,?,'debit',?)", (new_id('led'), transaction_id, system_account_id, payload.amount_minor))
        connection.execute('INSERT INTO audit_events(audit_id,actor_type,action,entity_type,entity_id,request_id,detail_json) VALUES(?,?,?,?,?,?,?)', (new_id('aud'), 'admin', 'finance.top_up', 'transaction', transaction_id, payload.request_id, json.dumps({'member_id': payload.member_id, 'amount_minor': payload.amount_minor})))
    return {'transaction_id': transaction_id, 'status': 'succeeded', 'idempotent_replay': False}

@app.get('/api/v2/vending/devices', dependencies=[Depends(require_admin)])
def vending_devices(connection: DB):
    rows = connection.execute("SELECT registry_id,hardware_id,display_name,status,mac_address,last_seen_at FROM device_registry WHERE device_type='vending' ORDER BY created_at DESC").fetchall()
    return {'items': [dict(row) for row in rows]}

@app.get('/api/v2/vending/devices/{registry_id}/products', dependencies=[Depends(require_admin)])
def get_products(registry_id: str, connection: DB):
    device = connection.execute("SELECT registry_id FROM device_registry WHERE registry_id=? AND device_type='vending'", (registry_id,)).fetchone()
    if not device:
        raise HTTPException(status_code=404, detail={'code': 'VENDING_DEVICE_NOT_FOUND'})
    rows = connection.execute('SELECT product_id,name,price_minor,stock,image_path,nfc_promo_percent,qris_promo_percent FROM product_slots WHERE registry_id=? ORDER BY product_id', (registry_id,)).fetchall()
    return {'registry_id': registry_id, 'items': [dict(row) for row in rows]}

@app.put('/api/v2/vending/devices/{registry_id}/products/{product_id}', dependencies=[Depends(require_admin)])
def update_product(registry_id: str, product_id: int, payload: ProductUpdate, connection: DB):
    if product_id not in range(1, 6):
        raise HTTPException(status_code=422, detail={'code': 'INVALID_PRODUCT_SLOT'})
    with transaction(connection):
        result = connection.execute('UPDATE product_slots SET name=?,price_minor=?,stock=?,updated_at=CURRENT_TIMESTAMP WHERE registry_id=? AND product_id=?', (payload.name.strip(), payload.price_minor, payload.stock, registry_id, product_id))
        if result.rowcount != 1:
            raise HTTPException(status_code=404, detail={'code': 'PRODUCT_SLOT_NOT_FOUND'})
        connection.execute('INSERT INTO audit_events(audit_id,actor_type,action,entity_type,entity_id,detail_json) VALUES(?,?,?,?,?,?)', (new_id('aud'), 'admin', 'vending.product.update', 'product_slot', f'{registry_id}:{product_id}', json.dumps(payload.model_dump())))
    return {'registry_id': registry_id, 'product_id': product_id, **payload.model_dump(), 'nfc_promo_percent': 0, 'qris_promo_percent': 0}

@app.get('/api/v2/admin/audit', dependencies=[Depends(require_admin)])
def list_audit(connection: DB, limit: int = 100):
    limit = max(1, min(limit, 500))
    rows = connection.execute('SELECT audit_id,actor_type,actor_id,action,entity_type,entity_id,request_id,detail_json,created_at FROM audit_events ORDER BY created_at DESC LIMIT ?', (limit,)).fetchall()
    return {'items': [dict(row) for row in rows]}
 + salt + '

@app.get('/api/v2/ready')
def readiness(connection: DB):
    try:
        connection.execute('SELECT 1').fetchone()
    except sqlite3.Error as exc:
        raise HTTPException(status_code=503, detail={'code': 'DATABASE_NOT_READY'}) from exc
    return {'status': 'ready', 'database': 'ok'}

@app.post('/api/v2/admin/devices', status_code=201, dependencies=[Depends(require_admin)])
def register_device(payload: dict, connection: DB):
    hardware_id = str(payload.get('hardware_id', '')).strip()
    device_type = payload.get('device_type')
    display_name = str(payload.get('display_name', '')).strip()
    if not hardware_id or len(hardware_id) > 128 or device_type not in ('cashier', 'vending'):
        raise HTTPException(status_code=422, detail={'code': 'INVALID_DEVICE_REGISTRATION'})
    registry_id = new_id('reg')
    device_key = secrets_token = __import__('secrets').token_urlsafe(32)
    try:
        with transaction(connection):
            connection.execute('INSERT INTO device_registry(registry_id,hardware_id,device_type,display_name,status,device_key_hash,device_key_hint) VALUES(?,?,?,?,?,?,?)',
                (registry_id, hardware_id, device_type, display_name, 'active', hash_secret(device_key, settings.device_key_pepper), device_key[-4:]))
            connection.execute('INSERT INTO device_events(event_id,registry_id,hardware_id,event_type,detail_json) VALUES(?,?,?,?,?)',
                (new_id('evt'), registry_id, hardware_id, 'device.provisioned', json.dumps({'device_type': device_type})))
            if device_type == 'vending':
                for product_id in range(1, 6):
                    connection.execute('INSERT INTO product_slots(registry_id,product_id,name,price_minor,stock) VALUES(?,?,?,?,?)', (registry_id, product_id, f'Produk {product_id}', 0, 0))
            connection.execute('INSERT INTO audit_events(audit_id,actor_type,action,entity_type,entity_id,detail_json) VALUES(?,?,?,?,?,?)',
                (new_id('aud'), 'admin', 'device.provision', 'device', registry_id, json.dumps({'hardware_id': hardware_id, 'device_type': device_type})))
    except sqlite3.IntegrityError as exc:
        raise HTTPException(status_code=409, detail={'code': 'DEVICE_ALREADY_REGISTERED'}) from exc
    return {'registry_id': registry_id, 'hardware_id': hardware_id, 'device_type': device_type, 'device_key': secrets_token, 'warning': 'Simpan device_key sekarang; nilainya tidak dapat dibaca ulang.'}


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

@app.post('/api/v2/members', status_code=201, dependencies=[Depends(require_admin)])
def create_member(payload: MemberCreate, connection: DB):
    member_id = 'NTR-' + str(connection.execute("SELECT COUNT(*) + 1 FROM members").fetchone()[0]).zfill(5)
    account_id = new_id('acct')
    try:
        with transaction(connection):
            connection.execute('INSERT INTO members(member_id,display_name) VALUES(?,?)', (member_id, payload.display_name.strip()))
            connection.execute("INSERT INTO accounts(account_id,member_id,account_type) VALUES(?,?,'member')", (account_id, member_id))
            connection.execute('INSERT INTO audit_events(audit_id,actor_type,action,entity_type,entity_id) VALUES(?,?,?,?,?)', (new_id('aud'), 'admin', 'member.create', 'member', member_id))
    except sqlite3.IntegrityError as exc:
        raise HTTPException(status_code=409, detail={'code': 'MEMBER_CREATE_CONFLICT'}) from exc
    return {'member_id': member_id, 'display_name': payload.display_name.strip(), 'account_id': account_id, 'balance_minor': 0, 'status': 'active'}

@app.get('/api/v2/members', dependencies=[Depends(require_admin)])
def list_members(connection: DB):
    rows = connection.execute('SELECT m.member_id,m.display_name,m.status,a.balance_minor FROM members m JOIN accounts a ON a.member_id=m.member_id ORDER BY m.created_at DESC').fetchall()
    return {'items': [dict(row) for row in rows]}

@app.post('/api/v2/finance/top-ups', dependencies=[Depends(require_admin)])
def top_up(payload: TopUpRequest, connection: DB):
    prior = connection.execute('SELECT transaction_id,status,member_id,amount_minor FROM transactions WHERE request_id=?', (payload.request_id,)).fetchone()
    if prior:
        if prior['member_id'] != payload.member_id or prior['amount_minor'] != payload.amount_minor or prior['status'] != 'succeeded':
            raise HTTPException(status_code=409, detail={'code': 'IDEMPOTENCY_CONFLICT'})
        return {'transaction_id': prior['transaction_id'], 'status': prior['status'], 'idempotent_replay': True}
    account = connection.execute("SELECT account_id,balance_minor,status FROM accounts WHERE member_id=? AND account_type='member'", (payload.member_id,)).fetchone()
    if not account:
        raise HTTPException(status_code=404, detail={'code': 'MEMBER_ACCOUNT_NOT_FOUND'})
    if account['status'] != 'active':
        raise HTTPException(status_code=409, detail={'code': 'ACCOUNT_NOT_ACTIVE'})
    transaction_id = new_id('txn')
    system_account = connection.execute("SELECT account_id FROM accounts WHERE account_type='system' LIMIT 1").fetchone()
    with transaction(connection):
        if not system_account:
            system_id = new_id('acct')
            connection.execute("INSERT INTO accounts(account_id,account_type,balance_minor) VALUES(?,'system',0)", (system_id,))
            system_account_id = system_id
        else:
            system_account_id = system_account['account_id']
        connection.execute("INSERT INTO transactions(transaction_id,request_id,member_id,transaction_type,amount_minor,status,metadata_json,completed_at) VALUES(?,?,?,'top_up',?,'succeeded',?,CURRENT_TIMESTAMP)", (transaction_id, payload.request_id, payload.member_id, payload.amount_minor, json.dumps({'description': payload.description})))
        connection.execute('UPDATE accounts SET balance_minor=balance_minor+?,updated_at=CURRENT_TIMESTAMP WHERE account_id=?', (payload.amount_minor, account['account_id']))
        connection.execute("INSERT INTO ledger_entries(entry_id,transaction_id,account_id,direction,amount_minor) VALUES(?,?,?,'credit',?)", (new_id('led'), transaction_id, account['account_id'], payload.amount_minor))
        connection.execute("INSERT INTO ledger_entries(entry_id,transaction_id,account_id,direction,amount_minor) VALUES(?,?,?,'debit',?)", (new_id('led'), transaction_id, system_account_id, payload.amount_minor))
        connection.execute('INSERT INTO audit_events(audit_id,actor_type,action,entity_type,entity_id,request_id,detail_json) VALUES(?,?,?,?,?,?,?)', (new_id('aud'), 'admin', 'finance.top_up', 'transaction', transaction_id, payload.request_id, json.dumps({'member_id': payload.member_id, 'amount_minor': payload.amount_minor})))
    return {'transaction_id': transaction_id, 'status': 'succeeded', 'idempotent_replay': False}

@app.get('/api/v2/vending/devices', dependencies=[Depends(require_admin)])
def vending_devices(connection: DB):
    rows = connection.execute("SELECT registry_id,hardware_id,display_name,status,mac_address,last_seen_at FROM device_registry WHERE device_type='vending' ORDER BY created_at DESC").fetchall()
    return {'items': [dict(row) for row in rows]}

@app.get('/api/v2/vending/devices/{registry_id}/products', dependencies=[Depends(require_admin)])
def get_products(registry_id: str, connection: DB):
    device = connection.execute("SELECT registry_id FROM device_registry WHERE registry_id=? AND device_type='vending'", (registry_id,)).fetchone()
    if not device:
        raise HTTPException(status_code=404, detail={'code': 'VENDING_DEVICE_NOT_FOUND'})
    rows = connection.execute('SELECT product_id,name,price_minor,stock,image_path,nfc_promo_percent,qris_promo_percent FROM product_slots WHERE registry_id=? ORDER BY product_id', (registry_id,)).fetchall()
    return {'registry_id': registry_id, 'items': [dict(row) for row in rows]}

@app.put('/api/v2/vending/devices/{registry_id}/products/{product_id}', dependencies=[Depends(require_admin)])
def update_product(registry_id: str, product_id: int, payload: ProductUpdate, connection: DB):
    if product_id not in range(1, 6):
        raise HTTPException(status_code=422, detail={'code': 'INVALID_PRODUCT_SLOT'})
    with transaction(connection):
        result = connection.execute('UPDATE product_slots SET name=?,price_minor=?,stock=?,updated_at=CURRENT_TIMESTAMP WHERE registry_id=? AND product_id=?', (payload.name.strip(), payload.price_minor, payload.stock, registry_id, product_id))
        if result.rowcount != 1:
            raise HTTPException(status_code=404, detail={'code': 'PRODUCT_SLOT_NOT_FOUND'})
        connection.execute('INSERT INTO audit_events(audit_id,actor_type,action,entity_type,entity_id,detail_json) VALUES(?,?,?,?,?,?)', (new_id('aud'), 'admin', 'vending.product.update', 'product_slot', f'{registry_id}:{product_id}', json.dumps(payload.model_dump())))
    return {'registry_id': registry_id, 'product_id': product_id, **payload.model_dump(), 'nfc_promo_percent': 0, 'qris_promo_percent': 0}

@app.get('/api/v2/admin/audit', dependencies=[Depends(require_admin)])
def list_audit(connection: DB, limit: int = 100):
    limit = max(1, min(limit, 500))
    rows = connection.execute('SELECT audit_id,actor_type,actor_id,action,entity_type,entity_id,request_id,detail_json,created_at FROM audit_events ORDER BY created_at DESC LIMIT ?', (limit,)).fetchall()
    return {'items': [dict(row) for row in rows]}
)

class CardEnroll(BaseModel):
    card_uid: str = Field(min_length=4, max_length=128)

class PurchaseRequest(BaseModel):
    request_id: str = Field(min_length=8, max_length=128)
    card_uid: str = Field(min_length=4, max_length=128)
    pin: str = Field(min_length=6, max_length=12, pattern=r'^\\d{6,12}

class TopUpRequest(BaseModel):
    request_id: str = Field(min_length=8, max_length=128)
    member_id: str = Field(min_length=1, max_length=128)
    amount_minor: int = Field(gt=0, le=100_000_000)
    description: str = Field(default='Top-up saldo', max_length=200)

class PurchaseRequest(BaseModel):
    request_id: str = Field(min_length=8, max_length=128)
    member_id: str = Field(min_length=1, max_length=128)
    product_id: int = Field(ge=1, le=5)
    payment_method: str = Field(pattern='^(nfc|qris)$')

class ProductUpdate(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    price_minor: int = Field(ge=0, le=100_000_000)
    stock: int = Field(ge=0, le=1_000_000)

@app.get('/api/v2/health')
def health():
    return {'status': 'ok', 'service': 'mgroup-api', 'version': '2.0.0'}

@app.get('/api/v2/ready')
def readiness(connection: DB):
    try:
        connection.execute('SELECT 1').fetchone()
    except sqlite3.Error as exc:
        raise HTTPException(status_code=503, detail={'code': 'DATABASE_NOT_READY'}) from exc
    return {'status': 'ready', 'database': 'ok'}

@app.post('/api/v2/admin/devices', status_code=201, dependencies=[Depends(require_admin)])
def register_device(payload: dict, connection: DB):
    hardware_id = str(payload.get('hardware_id', '')).strip()
    device_type = payload.get('device_type')
    display_name = str(payload.get('display_name', '')).strip()
    if not hardware_id or len(hardware_id) > 128 or device_type not in ('cashier', 'vending'):
        raise HTTPException(status_code=422, detail={'code': 'INVALID_DEVICE_REGISTRATION'})
    registry_id = new_id('reg')
    device_key = secrets_token = __import__('secrets').token_urlsafe(32)
    try:
        with transaction(connection):
            connection.execute('INSERT INTO device_registry(registry_id,hardware_id,device_type,display_name,status,device_key_hash,device_key_hint) VALUES(?,?,?,?,?,?,?)',
                (registry_id, hardware_id, device_type, display_name, 'active', hash_secret(device_key, settings.device_key_pepper), device_key[-4:]))
            connection.execute('INSERT INTO device_events(event_id,registry_id,hardware_id,event_type,detail_json) VALUES(?,?,?,?,?)',
                (new_id('evt'), registry_id, hardware_id, 'device.provisioned', json.dumps({'device_type': device_type})))
            if device_type == 'vending':
                for product_id in range(1, 6):
                    connection.execute('INSERT INTO product_slots(registry_id,product_id,name,price_minor,stock) VALUES(?,?,?,?,?)', (registry_id, product_id, f'Produk {product_id}', 0, 0))
            connection.execute('INSERT INTO audit_events(audit_id,actor_type,action,entity_type,entity_id,detail_json) VALUES(?,?,?,?,?,?)',
                (new_id('aud'), 'admin', 'device.provision', 'device', registry_id, json.dumps({'hardware_id': hardware_id, 'device_type': device_type})))
    except sqlite3.IntegrityError as exc:
        raise HTTPException(status_code=409, detail={'code': 'DEVICE_ALREADY_REGISTERED'}) from exc
    return {'registry_id': registry_id, 'hardware_id': hardware_id, 'device_type': device_type, 'device_key': secrets_token, 'warning': 'Simpan device_key sekarang; nilainya tidak dapat dibaca ulang.'}


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

@app.post('/api/v2/members', status_code=201, dependencies=[Depends(require_admin)])
def create_member(payload: MemberCreate, connection: DB):
    member_id = 'NTR-' + str(connection.execute("SELECT COUNT(*) + 1 FROM members").fetchone()[0]).zfill(5)
    account_id = new_id('acct')
    try:
        with transaction(connection):
            connection.execute('INSERT INTO members(member_id,display_name) VALUES(?,?)', (member_id, payload.display_name.strip()))
            connection.execute("INSERT INTO accounts(account_id,member_id,account_type) VALUES(?,?,'member')", (account_id, member_id))
            connection.execute('INSERT INTO audit_events(audit_id,actor_type,action,entity_type,entity_id) VALUES(?,?,?,?,?)', (new_id('aud'), 'admin', 'member.create', 'member', member_id))
    except sqlite3.IntegrityError as exc:
        raise HTTPException(status_code=409, detail={'code': 'MEMBER_CREATE_CONFLICT'}) from exc
    return {'member_id': member_id, 'display_name': payload.display_name.strip(), 'account_id': account_id, 'balance_minor': 0, 'status': 'active'}

@app.get('/api/v2/members', dependencies=[Depends(require_admin)])
def list_members(connection: DB):
    rows = connection.execute('SELECT m.member_id,m.display_name,m.status,a.balance_minor FROM members m JOIN accounts a ON a.member_id=m.member_id ORDER BY m.created_at DESC').fetchall()
    return {'items': [dict(row) for row in rows]}

@app.post('/api/v2/finance/top-ups', dependencies=[Depends(require_admin)])
def top_up(payload: TopUpRequest, connection: DB):
    prior = connection.execute('SELECT transaction_id,status,member_id,amount_minor FROM transactions WHERE request_id=?', (payload.request_id,)).fetchone()
    if prior:
        if prior['member_id'] != payload.member_id or prior['amount_minor'] != payload.amount_minor or prior['status'] != 'succeeded':
            raise HTTPException(status_code=409, detail={'code': 'IDEMPOTENCY_CONFLICT'})
        return {'transaction_id': prior['transaction_id'], 'status': prior['status'], 'idempotent_replay': True}
    account = connection.execute("SELECT account_id,balance_minor,status FROM accounts WHERE member_id=? AND account_type='member'", (payload.member_id,)).fetchone()
    if not account:
        raise HTTPException(status_code=404, detail={'code': 'MEMBER_ACCOUNT_NOT_FOUND'})
    if account['status'] != 'active':
        raise HTTPException(status_code=409, detail={'code': 'ACCOUNT_NOT_ACTIVE'})
    transaction_id = new_id('txn')
    system_account = connection.execute("SELECT account_id FROM accounts WHERE account_type='system' LIMIT 1").fetchone()
    with transaction(connection):
        if not system_account:
            system_id = new_id('acct')
            connection.execute("INSERT INTO accounts(account_id,account_type,balance_minor) VALUES(?,'system',0)", (system_id,))
            system_account_id = system_id
        else:
            system_account_id = system_account['account_id']
        connection.execute("INSERT INTO transactions(transaction_id,request_id,member_id,transaction_type,amount_minor,status,metadata_json,completed_at) VALUES(?,?,?,'top_up',?,'succeeded',?,CURRENT_TIMESTAMP)", (transaction_id, payload.request_id, payload.member_id, payload.amount_minor, json.dumps({'description': payload.description})))
        connection.execute('UPDATE accounts SET balance_minor=balance_minor+?,updated_at=CURRENT_TIMESTAMP WHERE account_id=?', (payload.amount_minor, account['account_id']))
        connection.execute("INSERT INTO ledger_entries(entry_id,transaction_id,account_id,direction,amount_minor) VALUES(?,?,?,'credit',?)", (new_id('led'), transaction_id, account['account_id'], payload.amount_minor))
        connection.execute("INSERT INTO ledger_entries(entry_id,transaction_id,account_id,direction,amount_minor) VALUES(?,?,?,'debit',?)", (new_id('led'), transaction_id, system_account_id, payload.amount_minor))
        connection.execute('INSERT INTO audit_events(audit_id,actor_type,action,entity_type,entity_id,request_id,detail_json) VALUES(?,?,?,?,?,?,?)', (new_id('aud'), 'admin', 'finance.top_up', 'transaction', transaction_id, payload.request_id, json.dumps({'member_id': payload.member_id, 'amount_minor': payload.amount_minor})))
    return {'transaction_id': transaction_id, 'status': 'succeeded', 'idempotent_replay': False}

@app.get('/api/v2/vending/devices', dependencies=[Depends(require_admin)])
def vending_devices(connection: DB):
    rows = connection.execute("SELECT registry_id,hardware_id,display_name,status,mac_address,last_seen_at FROM device_registry WHERE device_type='vending' ORDER BY created_at DESC").fetchall()
    return {'items': [dict(row) for row in rows]}

@app.get('/api/v2/vending/devices/{registry_id}/products', dependencies=[Depends(require_admin)])
def get_products(registry_id: str, connection: DB):
    device = connection.execute("SELECT registry_id FROM device_registry WHERE registry_id=? AND device_type='vending'", (registry_id,)).fetchone()
    if not device:
        raise HTTPException(status_code=404, detail={'code': 'VENDING_DEVICE_NOT_FOUND'})
    rows = connection.execute('SELECT product_id,name,price_minor,stock,image_path,nfc_promo_percent,qris_promo_percent FROM product_slots WHERE registry_id=? ORDER BY product_id', (registry_id,)).fetchall()
    return {'registry_id': registry_id, 'items': [dict(row) for row in rows]}

@app.put('/api/v2/vending/devices/{registry_id}/products/{product_id}', dependencies=[Depends(require_admin)])
def update_product(registry_id: str, product_id: int, payload: ProductUpdate, connection: DB):
    if product_id not in range(1, 6):
        raise HTTPException(status_code=422, detail={'code': 'INVALID_PRODUCT_SLOT'})
    with transaction(connection):
        result = connection.execute('UPDATE product_slots SET name=?,price_minor=?,stock=?,updated_at=CURRENT_TIMESTAMP WHERE registry_id=? AND product_id=?', (payload.name.strip(), payload.price_minor, payload.stock, registry_id, product_id))
        if result.rowcount != 1:
            raise HTTPException(status_code=404, detail={'code': 'PRODUCT_SLOT_NOT_FOUND'})
        connection.execute('INSERT INTO audit_events(audit_id,actor_type,action,entity_type,entity_id,detail_json) VALUES(?,?,?,?,?,?)', (new_id('aud'), 'admin', 'vending.product.update', 'product_slot', f'{registry_id}:{product_id}', json.dumps(payload.model_dump())))
    return {'registry_id': registry_id, 'product_id': product_id, **payload.model_dump(), 'nfc_promo_percent': 0, 'qris_promo_percent': 0}

@app.get('/api/v2/admin/audit', dependencies=[Depends(require_admin)])
def list_audit(connection: DB, limit: int = 100):
    limit = max(1, min(limit, 500))
    rows = connection.execute('SELECT audit_id,actor_type,actor_id,action,entity_type,entity_id,request_id,detail_json,created_at FROM audit_events ORDER BY created_at DESC LIMIT ?', (limit,)).fetchall()
    return {'items': [dict(row) for row in rows]}
)
    product_id: int = Field(ge=1, le=5)

class DispenseResult(BaseModel):
    succeeded: bool
    reason: str | None = Field(default=None, max_length=200)

class TopUpRequest(BaseModel):
    request_id: str = Field(min_length=8, max_length=128)
    member_id: str = Field(min_length=1, max_length=128)
    amount_minor: int = Field(gt=0, le=100_000_000)
    description: str = Field(default='Top-up saldo', max_length=200)

class PurchaseRequest(BaseModel):
    request_id: str = Field(min_length=8, max_length=128)
    member_id: str = Field(min_length=1, max_length=128)
    product_id: int = Field(ge=1, le=5)
    payment_method: str = Field(pattern='^(nfc|qris)$')

class ProductUpdate(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    price_minor: int = Field(ge=0, le=100_000_000)
    stock: int = Field(ge=0, le=1_000_000)

@app.get('/api/v2/health')
def health():
    return {'status': 'ok', 'service': 'mgroup-api', 'version': '2.0.0'}

@app.get('/api/v2/ready')
def readiness(connection: DB):
    try:
        connection.execute('SELECT 1').fetchone()
    except sqlite3.Error as exc:
        raise HTTPException(status_code=503, detail={'code': 'DATABASE_NOT_READY'}) from exc
    return {'status': 'ready', 'database': 'ok'}

@app.post('/api/v2/admin/devices', status_code=201, dependencies=[Depends(require_admin)])
def register_device(payload: dict, connection: DB):
    hardware_id = str(payload.get('hardware_id', '')).strip()
    device_type = payload.get('device_type')
    display_name = str(payload.get('display_name', '')).strip()
    if not hardware_id or len(hardware_id) > 128 or device_type not in ('cashier', 'vending'):
        raise HTTPException(status_code=422, detail={'code': 'INVALID_DEVICE_REGISTRATION'})
    registry_id = new_id('reg')
    device_key = secrets_token = __import__('secrets').token_urlsafe(32)
    try:
        with transaction(connection):
            connection.execute('INSERT INTO device_registry(registry_id,hardware_id,device_type,display_name,status,device_key_hash,device_key_hint) VALUES(?,?,?,?,?,?,?)',
                (registry_id, hardware_id, device_type, display_name, 'active', hash_secret(device_key, settings.device_key_pepper), device_key[-4:]))
            connection.execute('INSERT INTO device_events(event_id,registry_id,hardware_id,event_type,detail_json) VALUES(?,?,?,?,?)',
                (new_id('evt'), registry_id, hardware_id, 'device.provisioned', json.dumps({'device_type': device_type})))
            if device_type == 'vending':
                for product_id in range(1, 6):
                    connection.execute('INSERT INTO product_slots(registry_id,product_id,name,price_minor,stock) VALUES(?,?,?,?,?)', (registry_id, product_id, f'Produk {product_id}', 0, 0))
            connection.execute('INSERT INTO audit_events(audit_id,actor_type,action,entity_type,entity_id,detail_json) VALUES(?,?,?,?,?,?)',
                (new_id('aud'), 'admin', 'device.provision', 'device', registry_id, json.dumps({'hardware_id': hardware_id, 'device_type': device_type})))
    except sqlite3.IntegrityError as exc:
        raise HTTPException(status_code=409, detail={'code': 'DEVICE_ALREADY_REGISTERED'}) from exc
    return {'registry_id': registry_id, 'hardware_id': hardware_id, 'device_type': device_type, 'device_key': secrets_token, 'warning': 'Simpan device_key sekarang; nilainya tidak dapat dibaca ulang.'}


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

@app.post('/api/v2/members', status_code=201, dependencies=[Depends(require_admin)])
def create_member(payload: MemberCreate, connection: DB):
    member_id = 'NTR-' + str(connection.execute("SELECT COUNT(*) + 1 FROM members").fetchone()[0]).zfill(5)
    account_id = new_id('acct')
    try:
        with transaction(connection):
            connection.execute('INSERT INTO members(member_id,display_name) VALUES(?,?)', (member_id, payload.display_name.strip()))
            connection.execute("INSERT INTO accounts(account_id,member_id,account_type) VALUES(?,?,'member')", (account_id, member_id))
            connection.execute('INSERT INTO audit_events(audit_id,actor_type,action,entity_type,entity_id) VALUES(?,?,?,?,?)', (new_id('aud'), 'admin', 'member.create', 'member', member_id))
    except sqlite3.IntegrityError as exc:
        raise HTTPException(status_code=409, detail={'code': 'MEMBER_CREATE_CONFLICT'}) from exc
    return {'member_id': member_id, 'display_name': payload.display_name.strip(), 'account_id': account_id, 'balance_minor': 0, 'status': 'active'}

@app.get('/api/v2/members', dependencies=[Depends(require_admin)])
def list_members(connection: DB):
    rows = connection.execute('SELECT m.member_id,m.display_name,m.status,a.balance_minor FROM members m JOIN accounts a ON a.member_id=m.member_id ORDER BY m.created_at DESC').fetchall()
    return {'items': [dict(row) for row in rows]}

@app.post('/api/v2/finance/top-ups', dependencies=[Depends(require_admin)])
def top_up(payload: TopUpRequest, connection: DB):
    prior = connection.execute('SELECT transaction_id,status,member_id,amount_minor FROM transactions WHERE request_id=?', (payload.request_id,)).fetchone()
    if prior:
        if prior['member_id'] != payload.member_id or prior['amount_minor'] != payload.amount_minor or prior['status'] != 'succeeded':
            raise HTTPException(status_code=409, detail={'code': 'IDEMPOTENCY_CONFLICT'})
        return {'transaction_id': prior['transaction_id'], 'status': prior['status'], 'idempotent_replay': True}
    account = connection.execute("SELECT account_id,balance_minor,status FROM accounts WHERE member_id=? AND account_type='member'", (payload.member_id,)).fetchone()
    if not account:
        raise HTTPException(status_code=404, detail={'code': 'MEMBER_ACCOUNT_NOT_FOUND'})
    if account['status'] != 'active':
        raise HTTPException(status_code=409, detail={'code': 'ACCOUNT_NOT_ACTIVE'})
    transaction_id = new_id('txn')
    system_account = connection.execute("SELECT account_id FROM accounts WHERE account_type='system' LIMIT 1").fetchone()
    with transaction(connection):
        if not system_account:
            system_id = new_id('acct')
            connection.execute("INSERT INTO accounts(account_id,account_type,balance_minor) VALUES(?,'system',0)", (system_id,))
            system_account_id = system_id
        else:
            system_account_id = system_account['account_id']
        connection.execute("INSERT INTO transactions(transaction_id,request_id,member_id,transaction_type,amount_minor,status,metadata_json,completed_at) VALUES(?,?,?,'top_up',?,'succeeded',?,CURRENT_TIMESTAMP)", (transaction_id, payload.request_id, payload.member_id, payload.amount_minor, json.dumps({'description': payload.description})))
        connection.execute('UPDATE accounts SET balance_minor=balance_minor+?,updated_at=CURRENT_TIMESTAMP WHERE account_id=?', (payload.amount_minor, account['account_id']))
        connection.execute("INSERT INTO ledger_entries(entry_id,transaction_id,account_id,direction,amount_minor) VALUES(?,?,?,'credit',?)", (new_id('led'), transaction_id, account['account_id'], payload.amount_minor))
        connection.execute("INSERT INTO ledger_entries(entry_id,transaction_id,account_id,direction,amount_minor) VALUES(?,?,?,'debit',?)", (new_id('led'), transaction_id, system_account_id, payload.amount_minor))
        connection.execute('INSERT INTO audit_events(audit_id,actor_type,action,entity_type,entity_id,request_id,detail_json) VALUES(?,?,?,?,?,?,?)', (new_id('aud'), 'admin', 'finance.top_up', 'transaction', transaction_id, payload.request_id, json.dumps({'member_id': payload.member_id, 'amount_minor': payload.amount_minor})))
    return {'transaction_id': transaction_id, 'status': 'succeeded', 'idempotent_replay': False}

@app.get('/api/v2/vending/devices', dependencies=[Depends(require_admin)])
def vending_devices(connection: DB):
    rows = connection.execute("SELECT registry_id,hardware_id,display_name,status,mac_address,last_seen_at FROM device_registry WHERE device_type='vending' ORDER BY created_at DESC").fetchall()
    return {'items': [dict(row) for row in rows]}

@app.get('/api/v2/vending/devices/{registry_id}/products', dependencies=[Depends(require_admin)])
def get_products(registry_id: str, connection: DB):
    device = connection.execute("SELECT registry_id FROM device_registry WHERE registry_id=? AND device_type='vending'", (registry_id,)).fetchone()
    if not device:
        raise HTTPException(status_code=404, detail={'code': 'VENDING_DEVICE_NOT_FOUND'})
    rows = connection.execute('SELECT product_id,name,price_minor,stock,image_path,nfc_promo_percent,qris_promo_percent FROM product_slots WHERE registry_id=? ORDER BY product_id', (registry_id,)).fetchall()
    return {'registry_id': registry_id, 'items': [dict(row) for row in rows]}

@app.put('/api/v2/vending/devices/{registry_id}/products/{product_id}', dependencies=[Depends(require_admin)])
def update_product(registry_id: str, product_id: int, payload: ProductUpdate, connection: DB):
    if product_id not in range(1, 6):
        raise HTTPException(status_code=422, detail={'code': 'INVALID_PRODUCT_SLOT'})
    with transaction(connection):
        result = connection.execute('UPDATE product_slots SET name=?,price_minor=?,stock=?,updated_at=CURRENT_TIMESTAMP WHERE registry_id=? AND product_id=?', (payload.name.strip(), payload.price_minor, payload.stock, registry_id, product_id))
        if result.rowcount != 1:
            raise HTTPException(status_code=404, detail={'code': 'PRODUCT_SLOT_NOT_FOUND'})
        connection.execute('INSERT INTO audit_events(audit_id,actor_type,action,entity_type,entity_id,detail_json) VALUES(?,?,?,?,?,?)', (new_id('aud'), 'admin', 'vending.product.update', 'product_slot', f'{registry_id}:{product_id}', json.dumps(payload.model_dump())))
    return {'registry_id': registry_id, 'product_id': product_id, **payload.model_dump(), 'nfc_promo_percent': 0, 'qris_promo_percent': 0}

@app.get('/api/v2/admin/audit', dependencies=[Depends(require_admin)])
def list_audit(connection: DB, limit: int = 100):
    limit = max(1, min(limit, 500))
    rows = connection.execute('SELECT audit_id,actor_type,actor_id,action,entity_type,entity_id,request_id,detail_json,created_at FROM audit_events ORDER BY created_at DESC LIMIT ?', (limit,)).fetchall()
    return {'items': [dict(row) for row in rows]}
 + digest


def verify_pin(pin: str, encoded: str | None) -> bool:
    if not encoded:
        return False
    try:
        algorithm, rounds, salt, expected = encoded.split('

@app.get('/api/v2/ready')
def readiness(connection: DB):
    try:
        connection.execute('SELECT 1').fetchone()
    except sqlite3.Error as exc:
        raise HTTPException(status_code=503, detail={'code': 'DATABASE_NOT_READY'}) from exc
    return {'status': 'ready', 'database': 'ok'}

@app.post('/api/v2/admin/devices', status_code=201, dependencies=[Depends(require_admin)])
def register_device(payload: dict, connection: DB):
    hardware_id = str(payload.get('hardware_id', '')).strip()
    device_type = payload.get('device_type')
    display_name = str(payload.get('display_name', '')).strip()
    if not hardware_id or len(hardware_id) > 128 or device_type not in ('cashier', 'vending'):
        raise HTTPException(status_code=422, detail={'code': 'INVALID_DEVICE_REGISTRATION'})
    registry_id = new_id('reg')
    device_key = secrets_token = __import__('secrets').token_urlsafe(32)
    try:
        with transaction(connection):
            connection.execute('INSERT INTO device_registry(registry_id,hardware_id,device_type,display_name,status,device_key_hash,device_key_hint) VALUES(?,?,?,?,?,?,?)',
                (registry_id, hardware_id, device_type, display_name, 'active', hash_secret(device_key, settings.device_key_pepper), device_key[-4:]))
            connection.execute('INSERT INTO device_events(event_id,registry_id,hardware_id,event_type,detail_json) VALUES(?,?,?,?,?)',
                (new_id('evt'), registry_id, hardware_id, 'device.provisioned', json.dumps({'device_type': device_type})))
            if device_type == 'vending':
                for product_id in range(1, 6):
                    connection.execute('INSERT INTO product_slots(registry_id,product_id,name,price_minor,stock) VALUES(?,?,?,?,?)', (registry_id, product_id, f'Produk {product_id}', 0, 0))
            connection.execute('INSERT INTO audit_events(audit_id,actor_type,action,entity_type,entity_id,detail_json) VALUES(?,?,?,?,?,?)',
                (new_id('aud'), 'admin', 'device.provision', 'device', registry_id, json.dumps({'hardware_id': hardware_id, 'device_type': device_type})))
    except sqlite3.IntegrityError as exc:
        raise HTTPException(status_code=409, detail={'code': 'DEVICE_ALREADY_REGISTERED'}) from exc
    return {'registry_id': registry_id, 'hardware_id': hardware_id, 'device_type': device_type, 'device_key': secrets_token, 'warning': 'Simpan device_key sekarang; nilainya tidak dapat dibaca ulang.'}


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

@app.post('/api/v2/members', status_code=201, dependencies=[Depends(require_admin)])
def create_member(payload: MemberCreate, connection: DB):
    member_id = 'NTR-' + str(connection.execute("SELECT COUNT(*) + 1 FROM members").fetchone()[0]).zfill(5)
    account_id = new_id('acct')
    try:
        with transaction(connection):
            connection.execute('INSERT INTO members(member_id,display_name) VALUES(?,?)', (member_id, payload.display_name.strip()))
            connection.execute("INSERT INTO accounts(account_id,member_id,account_type) VALUES(?,?,'member')", (account_id, member_id))
            connection.execute('INSERT INTO audit_events(audit_id,actor_type,action,entity_type,entity_id) VALUES(?,?,?,?,?)', (new_id('aud'), 'admin', 'member.create', 'member', member_id))
    except sqlite3.IntegrityError as exc:
        raise HTTPException(status_code=409, detail={'code': 'MEMBER_CREATE_CONFLICT'}) from exc
    return {'member_id': member_id, 'display_name': payload.display_name.strip(), 'account_id': account_id, 'balance_minor': 0, 'status': 'active'}

@app.get('/api/v2/members', dependencies=[Depends(require_admin)])
def list_members(connection: DB):
    rows = connection.execute('SELECT m.member_id,m.display_name,m.status,a.balance_minor FROM members m JOIN accounts a ON a.member_id=m.member_id ORDER BY m.created_at DESC').fetchall()
    return {'items': [dict(row) for row in rows]}

@app.post('/api/v2/finance/top-ups', dependencies=[Depends(require_admin)])
def top_up(payload: TopUpRequest, connection: DB):
    prior = connection.execute('SELECT transaction_id,status,member_id,amount_minor FROM transactions WHERE request_id=?', (payload.request_id,)).fetchone()
    if prior:
        if prior['member_id'] != payload.member_id or prior['amount_minor'] != payload.amount_minor or prior['status'] != 'succeeded':
            raise HTTPException(status_code=409, detail={'code': 'IDEMPOTENCY_CONFLICT'})
        return {'transaction_id': prior['transaction_id'], 'status': prior['status'], 'idempotent_replay': True}
    account = connection.execute("SELECT account_id,balance_minor,status FROM accounts WHERE member_id=? AND account_type='member'", (payload.member_id,)).fetchone()
    if not account:
        raise HTTPException(status_code=404, detail={'code': 'MEMBER_ACCOUNT_NOT_FOUND'})
    if account['status'] != 'active':
        raise HTTPException(status_code=409, detail={'code': 'ACCOUNT_NOT_ACTIVE'})
    transaction_id = new_id('txn')
    system_account = connection.execute("SELECT account_id FROM accounts WHERE account_type='system' LIMIT 1").fetchone()
    with transaction(connection):
        if not system_account:
            system_id = new_id('acct')
            connection.execute("INSERT INTO accounts(account_id,account_type,balance_minor) VALUES(?,'system',0)", (system_id,))
            system_account_id = system_id
        else:
            system_account_id = system_account['account_id']
        connection.execute("INSERT INTO transactions(transaction_id,request_id,member_id,transaction_type,amount_minor,status,metadata_json,completed_at) VALUES(?,?,?,'top_up',?,'succeeded',?,CURRENT_TIMESTAMP)", (transaction_id, payload.request_id, payload.member_id, payload.amount_minor, json.dumps({'description': payload.description})))
        connection.execute('UPDATE accounts SET balance_minor=balance_minor+?,updated_at=CURRENT_TIMESTAMP WHERE account_id=?', (payload.amount_minor, account['account_id']))
        connection.execute("INSERT INTO ledger_entries(entry_id,transaction_id,account_id,direction,amount_minor) VALUES(?,?,?,'credit',?)", (new_id('led'), transaction_id, account['account_id'], payload.amount_minor))
        connection.execute("INSERT INTO ledger_entries(entry_id,transaction_id,account_id,direction,amount_minor) VALUES(?,?,?,'debit',?)", (new_id('led'), transaction_id, system_account_id, payload.amount_minor))
        connection.execute('INSERT INTO audit_events(audit_id,actor_type,action,entity_type,entity_id,request_id,detail_json) VALUES(?,?,?,?,?,?,?)', (new_id('aud'), 'admin', 'finance.top_up', 'transaction', transaction_id, payload.request_id, json.dumps({'member_id': payload.member_id, 'amount_minor': payload.amount_minor})))
    return {'transaction_id': transaction_id, 'status': 'succeeded', 'idempotent_replay': False}

@app.get('/api/v2/vending/devices', dependencies=[Depends(require_admin)])
def vending_devices(connection: DB):
    rows = connection.execute("SELECT registry_id,hardware_id,display_name,status,mac_address,last_seen_at FROM device_registry WHERE device_type='vending' ORDER BY created_at DESC").fetchall()
    return {'items': [dict(row) for row in rows]}

@app.get('/api/v2/vending/devices/{registry_id}/products', dependencies=[Depends(require_admin)])
def get_products(registry_id: str, connection: DB):
    device = connection.execute("SELECT registry_id FROM device_registry WHERE registry_id=? AND device_type='vending'", (registry_id,)).fetchone()
    if not device:
        raise HTTPException(status_code=404, detail={'code': 'VENDING_DEVICE_NOT_FOUND'})
    rows = connection.execute('SELECT product_id,name,price_minor,stock,image_path,nfc_promo_percent,qris_promo_percent FROM product_slots WHERE registry_id=? ORDER BY product_id', (registry_id,)).fetchall()
    return {'registry_id': registry_id, 'items': [dict(row) for row in rows]}

@app.put('/api/v2/vending/devices/{registry_id}/products/{product_id}', dependencies=[Depends(require_admin)])
def update_product(registry_id: str, product_id: int, payload: ProductUpdate, connection: DB):
    if product_id not in range(1, 6):
        raise HTTPException(status_code=422, detail={'code': 'INVALID_PRODUCT_SLOT'})
    with transaction(connection):
        result = connection.execute('UPDATE product_slots SET name=?,price_minor=?,stock=?,updated_at=CURRENT_TIMESTAMP WHERE registry_id=? AND product_id=?', (payload.name.strip(), payload.price_minor, payload.stock, registry_id, product_id))
        if result.rowcount != 1:
            raise HTTPException(status_code=404, detail={'code': 'PRODUCT_SLOT_NOT_FOUND'})
        connection.execute('INSERT INTO audit_events(audit_id,actor_type,action,entity_type,entity_id,detail_json) VALUES(?,?,?,?,?,?)', (new_id('aud'), 'admin', 'vending.product.update', 'product_slot', f'{registry_id}:{product_id}', json.dumps(payload.model_dump())))
    return {'registry_id': registry_id, 'product_id': product_id, **payload.model_dump(), 'nfc_promo_percent': 0, 'qris_promo_percent': 0}

@app.get('/api/v2/admin/audit', dependencies=[Depends(require_admin)])
def list_audit(connection: DB, limit: int = 100):
    limit = max(1, min(limit, 500))
    rows = connection.execute('SELECT audit_id,actor_type,actor_id,action,entity_type,entity_id,request_id,detail_json,created_at FROM audit_events ORDER BY created_at DESC LIMIT ?', (limit,)).fetchall()
    return {'items': [dict(row) for row in rows]}
)

class CardEnroll(BaseModel):
    card_uid: str = Field(min_length=4, max_length=128)

class PurchaseRequest(BaseModel):
    request_id: str = Field(min_length=8, max_length=128)
    card_uid: str = Field(min_length=4, max_length=128)
    pin: str = Field(min_length=6, max_length=12, pattern=r'^\\d{6,12}

class TopUpRequest(BaseModel):
    request_id: str = Field(min_length=8, max_length=128)
    member_id: str = Field(min_length=1, max_length=128)
    amount_minor: int = Field(gt=0, le=100_000_000)
    description: str = Field(default='Top-up saldo', max_length=200)

class PurchaseRequest(BaseModel):
    request_id: str = Field(min_length=8, max_length=128)
    member_id: str = Field(min_length=1, max_length=128)
    product_id: int = Field(ge=1, le=5)
    payment_method: str = Field(pattern='^(nfc|qris)$')

class ProductUpdate(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    price_minor: int = Field(ge=0, le=100_000_000)
    stock: int = Field(ge=0, le=1_000_000)

@app.get('/api/v2/health')
def health():
    return {'status': 'ok', 'service': 'mgroup-api', 'version': '2.0.0'}

@app.get('/api/v2/ready')
def readiness(connection: DB):
    try:
        connection.execute('SELECT 1').fetchone()
    except sqlite3.Error as exc:
        raise HTTPException(status_code=503, detail={'code': 'DATABASE_NOT_READY'}) from exc
    return {'status': 'ready', 'database': 'ok'}

@app.post('/api/v2/admin/devices', status_code=201, dependencies=[Depends(require_admin)])
def register_device(payload: dict, connection: DB):
    hardware_id = str(payload.get('hardware_id', '')).strip()
    device_type = payload.get('device_type')
    display_name = str(payload.get('display_name', '')).strip()
    if not hardware_id or len(hardware_id) > 128 or device_type not in ('cashier', 'vending'):
        raise HTTPException(status_code=422, detail={'code': 'INVALID_DEVICE_REGISTRATION'})
    registry_id = new_id('reg')
    device_key = secrets_token = __import__('secrets').token_urlsafe(32)
    try:
        with transaction(connection):
            connection.execute('INSERT INTO device_registry(registry_id,hardware_id,device_type,display_name,status,device_key_hash,device_key_hint) VALUES(?,?,?,?,?,?,?)',
                (registry_id, hardware_id, device_type, display_name, 'active', hash_secret(device_key, settings.device_key_pepper), device_key[-4:]))
            connection.execute('INSERT INTO device_events(event_id,registry_id,hardware_id,event_type,detail_json) VALUES(?,?,?,?,?)',
                (new_id('evt'), registry_id, hardware_id, 'device.provisioned', json.dumps({'device_type': device_type})))
            if device_type == 'vending':
                for product_id in range(1, 6):
                    connection.execute('INSERT INTO product_slots(registry_id,product_id,name,price_minor,stock) VALUES(?,?,?,?,?)', (registry_id, product_id, f'Produk {product_id}', 0, 0))
            connection.execute('INSERT INTO audit_events(audit_id,actor_type,action,entity_type,entity_id,detail_json) VALUES(?,?,?,?,?,?)',
                (new_id('aud'), 'admin', 'device.provision', 'device', registry_id, json.dumps({'hardware_id': hardware_id, 'device_type': device_type})))
    except sqlite3.IntegrityError as exc:
        raise HTTPException(status_code=409, detail={'code': 'DEVICE_ALREADY_REGISTERED'}) from exc
    return {'registry_id': registry_id, 'hardware_id': hardware_id, 'device_type': device_type, 'device_key': secrets_token, 'warning': 'Simpan device_key sekarang; nilainya tidak dapat dibaca ulang.'}


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

@app.post('/api/v2/members', status_code=201, dependencies=[Depends(require_admin)])
def create_member(payload: MemberCreate, connection: DB):
    member_id = 'NTR-' + str(connection.execute("SELECT COUNT(*) + 1 FROM members").fetchone()[0]).zfill(5)
    account_id = new_id('acct')
    try:
        with transaction(connection):
            connection.execute('INSERT INTO members(member_id,display_name) VALUES(?,?)', (member_id, payload.display_name.strip()))
            connection.execute("INSERT INTO accounts(account_id,member_id,account_type) VALUES(?,?,'member')", (account_id, member_id))
            connection.execute('INSERT INTO audit_events(audit_id,actor_type,action,entity_type,entity_id) VALUES(?,?,?,?,?)', (new_id('aud'), 'admin', 'member.create', 'member', member_id))
    except sqlite3.IntegrityError as exc:
        raise HTTPException(status_code=409, detail={'code': 'MEMBER_CREATE_CONFLICT'}) from exc
    return {'member_id': member_id, 'display_name': payload.display_name.strip(), 'account_id': account_id, 'balance_minor': 0, 'status': 'active'}

@app.get('/api/v2/members', dependencies=[Depends(require_admin)])
def list_members(connection: DB):
    rows = connection.execute('SELECT m.member_id,m.display_name,m.status,a.balance_minor FROM members m JOIN accounts a ON a.member_id=m.member_id ORDER BY m.created_at DESC').fetchall()
    return {'items': [dict(row) for row in rows]}

@app.post('/api/v2/finance/top-ups', dependencies=[Depends(require_admin)])
def top_up(payload: TopUpRequest, connection: DB):
    prior = connection.execute('SELECT transaction_id,status,member_id,amount_minor FROM transactions WHERE request_id=?', (payload.request_id,)).fetchone()
    if prior:
        if prior['member_id'] != payload.member_id or prior['amount_minor'] != payload.amount_minor or prior['status'] != 'succeeded':
            raise HTTPException(status_code=409, detail={'code': 'IDEMPOTENCY_CONFLICT'})
        return {'transaction_id': prior['transaction_id'], 'status': prior['status'], 'idempotent_replay': True}
    account = connection.execute("SELECT account_id,balance_minor,status FROM accounts WHERE member_id=? AND account_type='member'", (payload.member_id,)).fetchone()
    if not account:
        raise HTTPException(status_code=404, detail={'code': 'MEMBER_ACCOUNT_NOT_FOUND'})
    if account['status'] != 'active':
        raise HTTPException(status_code=409, detail={'code': 'ACCOUNT_NOT_ACTIVE'})
    transaction_id = new_id('txn')
    system_account = connection.execute("SELECT account_id FROM accounts WHERE account_type='system' LIMIT 1").fetchone()
    with transaction(connection):
        if not system_account:
            system_id = new_id('acct')
            connection.execute("INSERT INTO accounts(account_id,account_type,balance_minor) VALUES(?,'system',0)", (system_id,))
            system_account_id = system_id
        else:
            system_account_id = system_account['account_id']
        connection.execute("INSERT INTO transactions(transaction_id,request_id,member_id,transaction_type,amount_minor,status,metadata_json,completed_at) VALUES(?,?,?,'top_up',?,'succeeded',?,CURRENT_TIMESTAMP)", (transaction_id, payload.request_id, payload.member_id, payload.amount_minor, json.dumps({'description': payload.description})))
        connection.execute('UPDATE accounts SET balance_minor=balance_minor+?,updated_at=CURRENT_TIMESTAMP WHERE account_id=?', (payload.amount_minor, account['account_id']))
        connection.execute("INSERT INTO ledger_entries(entry_id,transaction_id,account_id,direction,amount_minor) VALUES(?,?,?,'credit',?)", (new_id('led'), transaction_id, account['account_id'], payload.amount_minor))
        connection.execute("INSERT INTO ledger_entries(entry_id,transaction_id,account_id,direction,amount_minor) VALUES(?,?,?,'debit',?)", (new_id('led'), transaction_id, system_account_id, payload.amount_minor))
        connection.execute('INSERT INTO audit_events(audit_id,actor_type,action,entity_type,entity_id,request_id,detail_json) VALUES(?,?,?,?,?,?,?)', (new_id('aud'), 'admin', 'finance.top_up', 'transaction', transaction_id, payload.request_id, json.dumps({'member_id': payload.member_id, 'amount_minor': payload.amount_minor})))
    return {'transaction_id': transaction_id, 'status': 'succeeded', 'idempotent_replay': False}

@app.get('/api/v2/vending/devices', dependencies=[Depends(require_admin)])
def vending_devices(connection: DB):
    rows = connection.execute("SELECT registry_id,hardware_id,display_name,status,mac_address,last_seen_at FROM device_registry WHERE device_type='vending' ORDER BY created_at DESC").fetchall()
    return {'items': [dict(row) for row in rows]}

@app.get('/api/v2/vending/devices/{registry_id}/products', dependencies=[Depends(require_admin)])
def get_products(registry_id: str, connection: DB):
    device = connection.execute("SELECT registry_id FROM device_registry WHERE registry_id=? AND device_type='vending'", (registry_id,)).fetchone()
    if not device:
        raise HTTPException(status_code=404, detail={'code': 'VENDING_DEVICE_NOT_FOUND'})
    rows = connection.execute('SELECT product_id,name,price_minor,stock,image_path,nfc_promo_percent,qris_promo_percent FROM product_slots WHERE registry_id=? ORDER BY product_id', (registry_id,)).fetchall()
    return {'registry_id': registry_id, 'items': [dict(row) for row in rows]}

@app.put('/api/v2/vending/devices/{registry_id}/products/{product_id}', dependencies=[Depends(require_admin)])
def update_product(registry_id: str, product_id: int, payload: ProductUpdate, connection: DB):
    if product_id not in range(1, 6):
        raise HTTPException(status_code=422, detail={'code': 'INVALID_PRODUCT_SLOT'})
    with transaction(connection):
        result = connection.execute('UPDATE product_slots SET name=?,price_minor=?,stock=?,updated_at=CURRENT_TIMESTAMP WHERE registry_id=? AND product_id=?', (payload.name.strip(), payload.price_minor, payload.stock, registry_id, product_id))
        if result.rowcount != 1:
            raise HTTPException(status_code=404, detail={'code': 'PRODUCT_SLOT_NOT_FOUND'})
        connection.execute('INSERT INTO audit_events(audit_id,actor_type,action,entity_type,entity_id,detail_json) VALUES(?,?,?,?,?,?)', (new_id('aud'), 'admin', 'vending.product.update', 'product_slot', f'{registry_id}:{product_id}', json.dumps(payload.model_dump())))
    return {'registry_id': registry_id, 'product_id': product_id, **payload.model_dump(), 'nfc_promo_percent': 0, 'qris_promo_percent': 0}

@app.get('/api/v2/admin/audit', dependencies=[Depends(require_admin)])
def list_audit(connection: DB, limit: int = 100):
    limit = max(1, min(limit, 500))
    rows = connection.execute('SELECT audit_id,actor_type,actor_id,action,entity_type,entity_id,request_id,detail_json,created_at FROM audit_events ORDER BY created_at DESC LIMIT ?', (limit,)).fetchall()
    return {'items': [dict(row) for row in rows]}
)
    product_id: int = Field(ge=1, le=5)

class DispenseResult(BaseModel):
    succeeded: bool
    reason: str | None = Field(default=None, max_length=200)

class TopUpRequest(BaseModel):
    request_id: str = Field(min_length=8, max_length=128)
    member_id: str = Field(min_length=1, max_length=128)
    amount_minor: int = Field(gt=0, le=100_000_000)
    description: str = Field(default='Top-up saldo', max_length=200)

class PurchaseRequest(BaseModel):
    request_id: str = Field(min_length=8, max_length=128)
    member_id: str = Field(min_length=1, max_length=128)
    product_id: int = Field(ge=1, le=5)
    payment_method: str = Field(pattern='^(nfc|qris)$')

class ProductUpdate(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    price_minor: int = Field(ge=0, le=100_000_000)
    stock: int = Field(ge=0, le=1_000_000)

@app.get('/api/v2/health')
def health():
    return {'status': 'ok', 'service': 'mgroup-api', 'version': '2.0.0'}

@app.get('/api/v2/ready')
def readiness(connection: DB):
    try:
        connection.execute('SELECT 1').fetchone()
    except sqlite3.Error as exc:
        raise HTTPException(status_code=503, detail={'code': 'DATABASE_NOT_READY'}) from exc
    return {'status': 'ready', 'database': 'ok'}

@app.post('/api/v2/admin/devices', status_code=201, dependencies=[Depends(require_admin)])
def register_device(payload: dict, connection: DB):
    hardware_id = str(payload.get('hardware_id', '')).strip()
    device_type = payload.get('device_type')
    display_name = str(payload.get('display_name', '')).strip()
    if not hardware_id or len(hardware_id) > 128 or device_type not in ('cashier', 'vending'):
        raise HTTPException(status_code=422, detail={'code': 'INVALID_DEVICE_REGISTRATION'})
    registry_id = new_id('reg')
    device_key = secrets_token = __import__('secrets').token_urlsafe(32)
    try:
        with transaction(connection):
            connection.execute('INSERT INTO device_registry(registry_id,hardware_id,device_type,display_name,status,device_key_hash,device_key_hint) VALUES(?,?,?,?,?,?,?)',
                (registry_id, hardware_id, device_type, display_name, 'active', hash_secret(device_key, settings.device_key_pepper), device_key[-4:]))
            connection.execute('INSERT INTO device_events(event_id,registry_id,hardware_id,event_type,detail_json) VALUES(?,?,?,?,?)',
                (new_id('evt'), registry_id, hardware_id, 'device.provisioned', json.dumps({'device_type': device_type})))
            if device_type == 'vending':
                for product_id in range(1, 6):
                    connection.execute('INSERT INTO product_slots(registry_id,product_id,name,price_minor,stock) VALUES(?,?,?,?,?)', (registry_id, product_id, f'Produk {product_id}', 0, 0))
            connection.execute('INSERT INTO audit_events(audit_id,actor_type,action,entity_type,entity_id,detail_json) VALUES(?,?,?,?,?,?)',
                (new_id('aud'), 'admin', 'device.provision', 'device', registry_id, json.dumps({'hardware_id': hardware_id, 'device_type': device_type})))
    except sqlite3.IntegrityError as exc:
        raise HTTPException(status_code=409, detail={'code': 'DEVICE_ALREADY_REGISTERED'}) from exc
    return {'registry_id': registry_id, 'hardware_id': hardware_id, 'device_type': device_type, 'device_key': secrets_token, 'warning': 'Simpan device_key sekarang; nilainya tidak dapat dibaca ulang.'}


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

@app.post('/api/v2/members', status_code=201, dependencies=[Depends(require_admin)])
def create_member(payload: MemberCreate, connection: DB):
    member_id = 'NTR-' + str(connection.execute("SELECT COUNT(*) + 1 FROM members").fetchone()[0]).zfill(5)
    account_id = new_id('acct')
    try:
        with transaction(connection):
            connection.execute('INSERT INTO members(member_id,display_name) VALUES(?,?)', (member_id, payload.display_name.strip()))
            connection.execute("INSERT INTO accounts(account_id,member_id,account_type) VALUES(?,?,'member')", (account_id, member_id))
            connection.execute('INSERT INTO audit_events(audit_id,actor_type,action,entity_type,entity_id) VALUES(?,?,?,?,?)', (new_id('aud'), 'admin', 'member.create', 'member', member_id))
    except sqlite3.IntegrityError as exc:
        raise HTTPException(status_code=409, detail={'code': 'MEMBER_CREATE_CONFLICT'}) from exc
    return {'member_id': member_id, 'display_name': payload.display_name.strip(), 'account_id': account_id, 'balance_minor': 0, 'status': 'active'}

@app.get('/api/v2/members', dependencies=[Depends(require_admin)])
def list_members(connection: DB):
    rows = connection.execute('SELECT m.member_id,m.display_name,m.status,a.balance_minor FROM members m JOIN accounts a ON a.member_id=m.member_id ORDER BY m.created_at DESC').fetchall()
    return {'items': [dict(row) for row in rows]}

@app.post('/api/v2/finance/top-ups', dependencies=[Depends(require_admin)])
def top_up(payload: TopUpRequest, connection: DB):
    prior = connection.execute('SELECT transaction_id,status,member_id,amount_minor FROM transactions WHERE request_id=?', (payload.request_id,)).fetchone()
    if prior:
        if prior['member_id'] != payload.member_id or prior['amount_minor'] != payload.amount_minor or prior['status'] != 'succeeded':
            raise HTTPException(status_code=409, detail={'code': 'IDEMPOTENCY_CONFLICT'})
        return {'transaction_id': prior['transaction_id'], 'status': prior['status'], 'idempotent_replay': True}
    account = connection.execute("SELECT account_id,balance_minor,status FROM accounts WHERE member_id=? AND account_type='member'", (payload.member_id,)).fetchone()
    if not account:
        raise HTTPException(status_code=404, detail={'code': 'MEMBER_ACCOUNT_NOT_FOUND'})
    if account['status'] != 'active':
        raise HTTPException(status_code=409, detail={'code': 'ACCOUNT_NOT_ACTIVE'})
    transaction_id = new_id('txn')
    system_account = connection.execute("SELECT account_id FROM accounts WHERE account_type='system' LIMIT 1").fetchone()
    with transaction(connection):
        if not system_account:
            system_id = new_id('acct')
            connection.execute("INSERT INTO accounts(account_id,account_type,balance_minor) VALUES(?,'system',0)", (system_id,))
            system_account_id = system_id
        else:
            system_account_id = system_account['account_id']
        connection.execute("INSERT INTO transactions(transaction_id,request_id,member_id,transaction_type,amount_minor,status,metadata_json,completed_at) VALUES(?,?,?,'top_up',?,'succeeded',?,CURRENT_TIMESTAMP)", (transaction_id, payload.request_id, payload.member_id, payload.amount_minor, json.dumps({'description': payload.description})))
        connection.execute('UPDATE accounts SET balance_minor=balance_minor+?,updated_at=CURRENT_TIMESTAMP WHERE account_id=?', (payload.amount_minor, account['account_id']))
        connection.execute("INSERT INTO ledger_entries(entry_id,transaction_id,account_id,direction,amount_minor) VALUES(?,?,?,'credit',?)", (new_id('led'), transaction_id, account['account_id'], payload.amount_minor))
        connection.execute("INSERT INTO ledger_entries(entry_id,transaction_id,account_id,direction,amount_minor) VALUES(?,?,?,'debit',?)", (new_id('led'), transaction_id, system_account_id, payload.amount_minor))
        connection.execute('INSERT INTO audit_events(audit_id,actor_type,action,entity_type,entity_id,request_id,detail_json) VALUES(?,?,?,?,?,?,?)', (new_id('aud'), 'admin', 'finance.top_up', 'transaction', transaction_id, payload.request_id, json.dumps({'member_id': payload.member_id, 'amount_minor': payload.amount_minor})))
    return {'transaction_id': transaction_id, 'status': 'succeeded', 'idempotent_replay': False}

@app.get('/api/v2/vending/devices', dependencies=[Depends(require_admin)])
def vending_devices(connection: DB):
    rows = connection.execute("SELECT registry_id,hardware_id,display_name,status,mac_address,last_seen_at FROM device_registry WHERE device_type='vending' ORDER BY created_at DESC").fetchall()
    return {'items': [dict(row) for row in rows]}

@app.get('/api/v2/vending/devices/{registry_id}/products', dependencies=[Depends(require_admin)])
def get_products(registry_id: str, connection: DB):
    device = connection.execute("SELECT registry_id FROM device_registry WHERE registry_id=? AND device_type='vending'", (registry_id,)).fetchone()
    if not device:
        raise HTTPException(status_code=404, detail={'code': 'VENDING_DEVICE_NOT_FOUND'})
    rows = connection.execute('SELECT product_id,name,price_minor,stock,image_path,nfc_promo_percent,qris_promo_percent FROM product_slots WHERE registry_id=? ORDER BY product_id', (registry_id,)).fetchall()
    return {'registry_id': registry_id, 'items': [dict(row) for row in rows]}

@app.put('/api/v2/vending/devices/{registry_id}/products/{product_id}', dependencies=[Depends(require_admin)])
def update_product(registry_id: str, product_id: int, payload: ProductUpdate, connection: DB):
    if product_id not in range(1, 6):
        raise HTTPException(status_code=422, detail={'code': 'INVALID_PRODUCT_SLOT'})
    with transaction(connection):
        result = connection.execute('UPDATE product_slots SET name=?,price_minor=?,stock=?,updated_at=CURRENT_TIMESTAMP WHERE registry_id=? AND product_id=?', (payload.name.strip(), payload.price_minor, payload.stock, registry_id, product_id))
        if result.rowcount != 1:
            raise HTTPException(status_code=404, detail={'code': 'PRODUCT_SLOT_NOT_FOUND'})
        connection.execute('INSERT INTO audit_events(audit_id,actor_type,action,entity_type,entity_id,detail_json) VALUES(?,?,?,?,?,?)', (new_id('aud'), 'admin', 'vending.product.update', 'product_slot', f'{registry_id}:{product_id}', json.dumps(payload.model_dump())))
    return {'registry_id': registry_id, 'product_id': product_id, **payload.model_dump(), 'nfc_promo_percent': 0, 'qris_promo_percent': 0}

@app.get('/api/v2/admin/audit', dependencies=[Depends(require_admin)])
def list_audit(connection: DB, limit: int = 100):
    limit = max(1, min(limit, 500))
    rows = connection.execute('SELECT audit_id,actor_type,actor_id,action,entity_type,entity_id,request_id,detail_json,created_at FROM audit_events ORDER BY created_at DESC LIMIT ?', (limit,)).fetchall()
    return {'items': [dict(row) for row in rows]}
, 3)
        if algorithm != 'pbkdf2_sha256' or int(rounds) != 310_000:
            return False
        actual = hashlib.pbkdf2_hmac('sha256', pin.encode('utf-8'), salt.encode('ascii'), int(rounds)).hex()
        return hmac.compare_digest(actual, expected)
    except (ValueError, TypeError):
        return False


def card_hash(card_uid: str) -> str:
    return hash_secret(card_uid.strip().upper(), settings.device_key_pepper)


def ensure_system_account(connection: sqlite3.Connection) -> str:
    row = connection.execute(\"SELECT account_id FROM accounts WHERE account_type='system' LIMIT 1\").fetchone()
    if row:
        return row['account_id']
    account_id = new_id('acct')
    connection.execute(\"INSERT INTO accounts(account_id,account_type,balance_minor) VALUES(?,'system',0)\", (account_id,))
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
def register_device(payload: dict, connection: DB):
    hardware_id = str(payload.get('hardware_id', '')).strip()
    device_type = payload.get('device_type')
    display_name = str(payload.get('display_name', '')).strip()
    if not hardware_id or len(hardware_id) > 128 or device_type not in ('cashier', 'vending'):
        raise HTTPException(status_code=422, detail={'code': 'INVALID_DEVICE_REGISTRATION'})
    registry_id = new_id('reg')
    device_key = secrets_token = __import__('secrets').token_urlsafe(32)
    try:
        with transaction(connection):
            connection.execute('INSERT INTO device_registry(registry_id,hardware_id,device_type,display_name,status,device_key_hash,device_key_hint) VALUES(?,?,?,?,?,?,?)',
                (registry_id, hardware_id, device_type, display_name, 'active', hash_secret(device_key, settings.device_key_pepper), device_key[-4:]))
            connection.execute('INSERT INTO device_events(event_id,registry_id,hardware_id,event_type,detail_json) VALUES(?,?,?,?,?)',
                (new_id('evt'), registry_id, hardware_id, 'device.provisioned', json.dumps({'device_type': device_type})))
            if device_type == 'vending':
                for product_id in range(1, 6):
                    connection.execute('INSERT INTO product_slots(registry_id,product_id,name,price_minor,stock) VALUES(?,?,?,?,?)', (registry_id, product_id, f'Produk {product_id}', 0, 0))
            connection.execute('INSERT INTO audit_events(audit_id,actor_type,action,entity_type,entity_id,detail_json) VALUES(?,?,?,?,?,?)',
                (new_id('aud'), 'admin', 'device.provision', 'device', registry_id, json.dumps({'hardware_id': hardware_id, 'device_type': device_type})))
    except sqlite3.IntegrityError as exc:
        raise HTTPException(status_code=409, detail={'code': 'DEVICE_ALREADY_REGISTERED'}) from exc
    return {'registry_id': registry_id, 'hardware_id': hardware_id, 'device_type': device_type, 'device_key': secrets_token, 'warning': 'Simpan device_key sekarang; nilainya tidak dapat dibaca ulang.'}


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

@app.post('/api/v2/members', status_code=201, dependencies=[Depends(require_admin)])
def create_member(payload: MemberCreate, connection: DB):
    member_id = 'NTR-' + str(connection.execute("SELECT COUNT(*) + 1 FROM members").fetchone()[0]).zfill(5)
    account_id = new_id('acct')
    try:
        with transaction(connection):
            connection.execute('INSERT INTO members(member_id,display_name) VALUES(?,?)', (member_id, payload.display_name.strip()))
            connection.execute("INSERT INTO accounts(account_id,member_id,account_type) VALUES(?,?,'member')", (account_id, member_id))
            connection.execute('INSERT INTO audit_events(audit_id,actor_type,action,entity_type,entity_id) VALUES(?,?,?,?,?)', (new_id('aud'), 'admin', 'member.create', 'member', member_id))
    except sqlite3.IntegrityError as exc:
        raise HTTPException(status_code=409, detail={'code': 'MEMBER_CREATE_CONFLICT'}) from exc
    return {'member_id': member_id, 'display_name': payload.display_name.strip(), 'account_id': account_id, 'balance_minor': 0, 'status': 'active'}

@app.get('/api/v2/members', dependencies=[Depends(require_admin)])
def list_members(connection: DB):
    rows = connection.execute('SELECT m.member_id,m.display_name,m.status,a.balance_minor FROM members m JOIN accounts a ON a.member_id=m.member_id ORDER BY m.created_at DESC').fetchall()
    return {'items': [dict(row) for row in rows]}

@app.post('/api/v2/finance/top-ups', dependencies=[Depends(require_admin)])
def top_up(payload: TopUpRequest, connection: DB):
    prior = connection.execute('SELECT transaction_id,status,member_id,amount_minor FROM transactions WHERE request_id=?', (payload.request_id,)).fetchone()
    if prior:
        if prior['member_id'] != payload.member_id or prior['amount_minor'] != payload.amount_minor or prior['status'] != 'succeeded':
            raise HTTPException(status_code=409, detail={'code': 'IDEMPOTENCY_CONFLICT'})
        return {'transaction_id': prior['transaction_id'], 'status': prior['status'], 'idempotent_replay': True}
    account = connection.execute("SELECT account_id,balance_minor,status FROM accounts WHERE member_id=? AND account_type='member'", (payload.member_id,)).fetchone()
    if not account:
        raise HTTPException(status_code=404, detail={'code': 'MEMBER_ACCOUNT_NOT_FOUND'})
    if account['status'] != 'active':
        raise HTTPException(status_code=409, detail={'code': 'ACCOUNT_NOT_ACTIVE'})
    transaction_id = new_id('txn')
    system_account = connection.execute("SELECT account_id FROM accounts WHERE account_type='system' LIMIT 1").fetchone()
    with transaction(connection):
        if not system_account:
            system_id = new_id('acct')
            connection.execute("INSERT INTO accounts(account_id,account_type,balance_minor) VALUES(?,'system',0)", (system_id,))
            system_account_id = system_id
        else:
            system_account_id = system_account['account_id']
        connection.execute("INSERT INTO transactions(transaction_id,request_id,member_id,transaction_type,amount_minor,status,metadata_json,completed_at) VALUES(?,?,?,'top_up',?,'succeeded',?,CURRENT_TIMESTAMP)", (transaction_id, payload.request_id, payload.member_id, payload.amount_minor, json.dumps({'description': payload.description})))
        connection.execute('UPDATE accounts SET balance_minor=balance_minor+?,updated_at=CURRENT_TIMESTAMP WHERE account_id=?', (payload.amount_minor, account['account_id']))
        connection.execute("INSERT INTO ledger_entries(entry_id,transaction_id,account_id,direction,amount_minor) VALUES(?,?,?,'credit',?)", (new_id('led'), transaction_id, account['account_id'], payload.amount_minor))
        connection.execute("INSERT INTO ledger_entries(entry_id,transaction_id,account_id,direction,amount_minor) VALUES(?,?,?,'debit',?)", (new_id('led'), transaction_id, system_account_id, payload.amount_minor))
        connection.execute('INSERT INTO audit_events(audit_id,actor_type,action,entity_type,entity_id,request_id,detail_json) VALUES(?,?,?,?,?,?,?)', (new_id('aud'), 'admin', 'finance.top_up', 'transaction', transaction_id, payload.request_id, json.dumps({'member_id': payload.member_id, 'amount_minor': payload.amount_minor})))
    return {'transaction_id': transaction_id, 'status': 'succeeded', 'idempotent_replay': False}

@app.get('/api/v2/vending/devices', dependencies=[Depends(require_admin)])
def vending_devices(connection: DB):
    rows = connection.execute("SELECT registry_id,hardware_id,display_name,status,mac_address,last_seen_at FROM device_registry WHERE device_type='vending' ORDER BY created_at DESC").fetchall()
    return {'items': [dict(row) for row in rows]}

@app.get('/api/v2/vending/devices/{registry_id}/products', dependencies=[Depends(require_admin)])
def get_products(registry_id: str, connection: DB):
    device = connection.execute("SELECT registry_id FROM device_registry WHERE registry_id=? AND device_type='vending'", (registry_id,)).fetchone()
    if not device:
        raise HTTPException(status_code=404, detail={'code': 'VENDING_DEVICE_NOT_FOUND'})
    rows = connection.execute('SELECT product_id,name,price_minor,stock,image_path,nfc_promo_percent,qris_promo_percent FROM product_slots WHERE registry_id=? ORDER BY product_id', (registry_id,)).fetchall()
    return {'registry_id': registry_id, 'items': [dict(row) for row in rows]}

@app.put('/api/v2/vending/devices/{registry_id}/products/{product_id}', dependencies=[Depends(require_admin)])
def update_product(registry_id: str, product_id: int, payload: ProductUpdate, connection: DB):
    if product_id not in range(1, 6):
        raise HTTPException(status_code=422, detail={'code': 'INVALID_PRODUCT_SLOT'})
    with transaction(connection):
        result = connection.execute('UPDATE product_slots SET name=?,price_minor=?,stock=?,updated_at=CURRENT_TIMESTAMP WHERE registry_id=? AND product_id=?', (payload.name.strip(), payload.price_minor, payload.stock, registry_id, product_id))
        if result.rowcount != 1:
            raise HTTPException(status_code=404, detail={'code': 'PRODUCT_SLOT_NOT_FOUND'})
        connection.execute('INSERT INTO audit_events(audit_id,actor_type,action,entity_type,entity_id,detail_json) VALUES(?,?,?,?,?,?)', (new_id('aud'), 'admin', 'vending.product.update', 'product_slot', f'{registry_id}:{product_id}', json.dumps(payload.model_dump())))
    return {'registry_id': registry_id, 'product_id': product_id, **payload.model_dump(), 'nfc_promo_percent': 0, 'qris_promo_percent': 0}

@app.get('/api/v2/admin/audit', dependencies=[Depends(require_admin)])
def list_audit(connection: DB, limit: int = 100):
    limit = max(1, min(limit, 500))
    rows = connection.execute('SELECT audit_id,actor_type,actor_id,action,entity_type,entity_id,request_id,detail_json,created_at FROM audit_events ORDER BY created_at DESC LIMIT ?', (limit,)).fetchall()
    return {'items': [dict(row) for row in rows]}
)

class CardEnroll(BaseModel):
    card_uid: str = Field(min_length=4, max_length=128)

class PurchaseRequest(BaseModel):
    request_id: str = Field(min_length=8, max_length=128)
    card_uid: str = Field(min_length=4, max_length=128)
    pin: str = Field(min_length=6, max_length=12, pattern=r'^\\d{6,12}

class TopUpRequest(BaseModel):
    request_id: str = Field(min_length=8, max_length=128)
    member_id: str = Field(min_length=1, max_length=128)
    amount_minor: int = Field(gt=0, le=100_000_000)
    description: str = Field(default='Top-up saldo', max_length=200)

class PurchaseRequest(BaseModel):
    request_id: str = Field(min_length=8, max_length=128)
    member_id: str = Field(min_length=1, max_length=128)
    product_id: int = Field(ge=1, le=5)
    payment_method: str = Field(pattern='^(nfc|qris)$')

class ProductUpdate(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    price_minor: int = Field(ge=0, le=100_000_000)
    stock: int = Field(ge=0, le=1_000_000)

@app.get('/api/v2/health')
def health():
    return {'status': 'ok', 'service': 'mgroup-api', 'version': '2.0.0'}

@app.get('/api/v2/ready')
def readiness(connection: DB):
    try:
        connection.execute('SELECT 1').fetchone()
    except sqlite3.Error as exc:
        raise HTTPException(status_code=503, detail={'code': 'DATABASE_NOT_READY'}) from exc
    return {'status': 'ready', 'database': 'ok'}

@app.post('/api/v2/admin/devices', status_code=201, dependencies=[Depends(require_admin)])
def register_device(payload: dict, connection: DB):
    hardware_id = str(payload.get('hardware_id', '')).strip()
    device_type = payload.get('device_type')
    display_name = str(payload.get('display_name', '')).strip()
    if not hardware_id or len(hardware_id) > 128 or device_type not in ('cashier', 'vending'):
        raise HTTPException(status_code=422, detail={'code': 'INVALID_DEVICE_REGISTRATION'})
    registry_id = new_id('reg')
    device_key = secrets_token = __import__('secrets').token_urlsafe(32)
    try:
        with transaction(connection):
            connection.execute('INSERT INTO device_registry(registry_id,hardware_id,device_type,display_name,status,device_key_hash,device_key_hint) VALUES(?,?,?,?,?,?,?)',
                (registry_id, hardware_id, device_type, display_name, 'active', hash_secret(device_key, settings.device_key_pepper), device_key[-4:]))
            connection.execute('INSERT INTO device_events(event_id,registry_id,hardware_id,event_type,detail_json) VALUES(?,?,?,?,?)',
                (new_id('evt'), registry_id, hardware_id, 'device.provisioned', json.dumps({'device_type': device_type})))
            if device_type == 'vending':
                for product_id in range(1, 6):
                    connection.execute('INSERT INTO product_slots(registry_id,product_id,name,price_minor,stock) VALUES(?,?,?,?,?)', (registry_id, product_id, f'Produk {product_id}', 0, 0))
            connection.execute('INSERT INTO audit_events(audit_id,actor_type,action,entity_type,entity_id,detail_json) VALUES(?,?,?,?,?,?)',
                (new_id('aud'), 'admin', 'device.provision', 'device', registry_id, json.dumps({'hardware_id': hardware_id, 'device_type': device_type})))
    except sqlite3.IntegrityError as exc:
        raise HTTPException(status_code=409, detail={'code': 'DEVICE_ALREADY_REGISTERED'}) from exc
    return {'registry_id': registry_id, 'hardware_id': hardware_id, 'device_type': device_type, 'device_key': secrets_token, 'warning': 'Simpan device_key sekarang; nilainya tidak dapat dibaca ulang.'}


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

@app.post('/api/v2/members', status_code=201, dependencies=[Depends(require_admin)])
def create_member(payload: MemberCreate, connection: DB):
    member_id = 'NTR-' + str(connection.execute("SELECT COUNT(*) + 1 FROM members").fetchone()[0]).zfill(5)
    account_id = new_id('acct')
    try:
        with transaction(connection):
            connection.execute('INSERT INTO members(member_id,display_name) VALUES(?,?)', (member_id, payload.display_name.strip()))
            connection.execute("INSERT INTO accounts(account_id,member_id,account_type) VALUES(?,?,'member')", (account_id, member_id))
            connection.execute('INSERT INTO audit_events(audit_id,actor_type,action,entity_type,entity_id) VALUES(?,?,?,?,?)', (new_id('aud'), 'admin', 'member.create', 'member', member_id))
    except sqlite3.IntegrityError as exc:
        raise HTTPException(status_code=409, detail={'code': 'MEMBER_CREATE_CONFLICT'}) from exc
    return {'member_id': member_id, 'display_name': payload.display_name.strip(), 'account_id': account_id, 'balance_minor': 0, 'status': 'active'}

@app.get('/api/v2/members', dependencies=[Depends(require_admin)])
def list_members(connection: DB):
    rows = connection.execute('SELECT m.member_id,m.display_name,m.status,a.balance_minor FROM members m JOIN accounts a ON a.member_id=m.member_id ORDER BY m.created_at DESC').fetchall()
    return {'items': [dict(row) for row in rows]}

@app.post('/api/v2/finance/top-ups', dependencies=[Depends(require_admin)])
def top_up(payload: TopUpRequest, connection: DB):
    prior = connection.execute('SELECT transaction_id,status,member_id,amount_minor FROM transactions WHERE request_id=?', (payload.request_id,)).fetchone()
    if prior:
        if prior['member_id'] != payload.member_id or prior['amount_minor'] != payload.amount_minor or prior['status'] != 'succeeded':
            raise HTTPException(status_code=409, detail={'code': 'IDEMPOTENCY_CONFLICT'})
        return {'transaction_id': prior['transaction_id'], 'status': prior['status'], 'idempotent_replay': True}
    account = connection.execute("SELECT account_id,balance_minor,status FROM accounts WHERE member_id=? AND account_type='member'", (payload.member_id,)).fetchone()
    if not account:
        raise HTTPException(status_code=404, detail={'code': 'MEMBER_ACCOUNT_NOT_FOUND'})
    if account['status'] != 'active':
        raise HTTPException(status_code=409, detail={'code': 'ACCOUNT_NOT_ACTIVE'})
    transaction_id = new_id('txn')
    system_account = connection.execute("SELECT account_id FROM accounts WHERE account_type='system' LIMIT 1").fetchone()
    with transaction(connection):
        if not system_account:
            system_id = new_id('acct')
            connection.execute("INSERT INTO accounts(account_id,account_type,balance_minor) VALUES(?,'system',0)", (system_id,))
            system_account_id = system_id
        else:
            system_account_id = system_account['account_id']
        connection.execute("INSERT INTO transactions(transaction_id,request_id,member_id,transaction_type,amount_minor,status,metadata_json,completed_at) VALUES(?,?,?,'top_up',?,'succeeded',?,CURRENT_TIMESTAMP)", (transaction_id, payload.request_id, payload.member_id, payload.amount_minor, json.dumps({'description': payload.description})))
        connection.execute('UPDATE accounts SET balance_minor=balance_minor+?,updated_at=CURRENT_TIMESTAMP WHERE account_id=?', (payload.amount_minor, account['account_id']))
        connection.execute("INSERT INTO ledger_entries(entry_id,transaction_id,account_id,direction,amount_minor) VALUES(?,?,?,'credit',?)", (new_id('led'), transaction_id, account['account_id'], payload.amount_minor))
        connection.execute("INSERT INTO ledger_entries(entry_id,transaction_id,account_id,direction,amount_minor) VALUES(?,?,?,'debit',?)", (new_id('led'), transaction_id, system_account_id, payload.amount_minor))
        connection.execute('INSERT INTO audit_events(audit_id,actor_type,action,entity_type,entity_id,request_id,detail_json) VALUES(?,?,?,?,?,?,?)', (new_id('aud'), 'admin', 'finance.top_up', 'transaction', transaction_id, payload.request_id, json.dumps({'member_id': payload.member_id, 'amount_minor': payload.amount_minor})))
    return {'transaction_id': transaction_id, 'status': 'succeeded', 'idempotent_replay': False}

@app.get('/api/v2/vending/devices', dependencies=[Depends(require_admin)])
def vending_devices(connection: DB):
    rows = connection.execute("SELECT registry_id,hardware_id,display_name,status,mac_address,last_seen_at FROM device_registry WHERE device_type='vending' ORDER BY created_at DESC").fetchall()
    return {'items': [dict(row) for row in rows]}

@app.get('/api/v2/vending/devices/{registry_id}/products', dependencies=[Depends(require_admin)])
def get_products(registry_id: str, connection: DB):
    device = connection.execute("SELECT registry_id FROM device_registry WHERE registry_id=? AND device_type='vending'", (registry_id,)).fetchone()
    if not device:
        raise HTTPException(status_code=404, detail={'code': 'VENDING_DEVICE_NOT_FOUND'})
    rows = connection.execute('SELECT product_id,name,price_minor,stock,image_path,nfc_promo_percent,qris_promo_percent FROM product_slots WHERE registry_id=? ORDER BY product_id', (registry_id,)).fetchall()
    return {'registry_id': registry_id, 'items': [dict(row) for row in rows]}

@app.put('/api/v2/vending/devices/{registry_id}/products/{product_id}', dependencies=[Depends(require_admin)])
def update_product(registry_id: str, product_id: int, payload: ProductUpdate, connection: DB):
    if product_id not in range(1, 6):
        raise HTTPException(status_code=422, detail={'code': 'INVALID_PRODUCT_SLOT'})
    with transaction(connection):
        result = connection.execute('UPDATE product_slots SET name=?,price_minor=?,stock=?,updated_at=CURRENT_TIMESTAMP WHERE registry_id=? AND product_id=?', (payload.name.strip(), payload.price_minor, payload.stock, registry_id, product_id))
        if result.rowcount != 1:
            raise HTTPException(status_code=404, detail={'code': 'PRODUCT_SLOT_NOT_FOUND'})
        connection.execute('INSERT INTO audit_events(audit_id,actor_type,action,entity_type,entity_id,detail_json) VALUES(?,?,?,?,?,?)', (new_id('aud'), 'admin', 'vending.product.update', 'product_slot', f'{registry_id}:{product_id}', json.dumps(payload.model_dump())))
    return {'registry_id': registry_id, 'product_id': product_id, **payload.model_dump(), 'nfc_promo_percent': 0, 'qris_promo_percent': 0}

@app.get('/api/v2/admin/audit', dependencies=[Depends(require_admin)])
def list_audit(connection: DB, limit: int = 100):
    limit = max(1, min(limit, 500))
    rows = connection.execute('SELECT audit_id,actor_type,actor_id,action,entity_type,entity_id,request_id,detail_json,created_at FROM audit_events ORDER BY created_at DESC LIMIT ?', (limit,)).fetchall()
    return {'items': [dict(row) for row in rows]}
)
    product_id: int = Field(ge=1, le=5)

class DispenseResult(BaseModel):
    succeeded: bool
    reason: str | None = Field(default=None, max_length=200)

class TopUpRequest(BaseModel):
    request_id: str = Field(min_length=8, max_length=128)
    member_id: str = Field(min_length=1, max_length=128)
    amount_minor: int = Field(gt=0, le=100_000_000)
    description: str = Field(default='Top-up saldo', max_length=200)

class PurchaseRequest(BaseModel):
    request_id: str = Field(min_length=8, max_length=128)
    member_id: str = Field(min_length=1, max_length=128)
    product_id: int = Field(ge=1, le=5)
    payment_method: str = Field(pattern='^(nfc|qris)$')

class ProductUpdate(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    price_minor: int = Field(ge=0, le=100_000_000)
    stock: int = Field(ge=0, le=1_000_000)

@app.get('/api/v2/health')
def health():
    return {'status': 'ok', 'service': 'mgroup-api', 'version': '2.0.0'}

@app.get('/api/v2/ready')
def readiness(connection: DB):
    try:
        connection.execute('SELECT 1').fetchone()
    except sqlite3.Error as exc:
        raise HTTPException(status_code=503, detail={'code': 'DATABASE_NOT_READY'}) from exc
    return {'status': 'ready', 'database': 'ok'}

@app.post('/api/v2/admin/devices', status_code=201, dependencies=[Depends(require_admin)])
def register_device(payload: dict, connection: DB):
    hardware_id = str(payload.get('hardware_id', '')).strip()
    device_type = payload.get('device_type')
    display_name = str(payload.get('display_name', '')).strip()
    if not hardware_id or len(hardware_id) > 128 or device_type not in ('cashier', 'vending'):
        raise HTTPException(status_code=422, detail={'code': 'INVALID_DEVICE_REGISTRATION'})
    registry_id = new_id('reg')
    device_key = secrets_token = __import__('secrets').token_urlsafe(32)
    try:
        with transaction(connection):
            connection.execute('INSERT INTO device_registry(registry_id,hardware_id,device_type,display_name,status,device_key_hash,device_key_hint) VALUES(?,?,?,?,?,?,?)',
                (registry_id, hardware_id, device_type, display_name, 'active', hash_secret(device_key, settings.device_key_pepper), device_key[-4:]))
            connection.execute('INSERT INTO device_events(event_id,registry_id,hardware_id,event_type,detail_json) VALUES(?,?,?,?,?)',
                (new_id('evt'), registry_id, hardware_id, 'device.provisioned', json.dumps({'device_type': device_type})))
            if device_type == 'vending':
                for product_id in range(1, 6):
                    connection.execute('INSERT INTO product_slots(registry_id,product_id,name,price_minor,stock) VALUES(?,?,?,?,?)', (registry_id, product_id, f'Produk {product_id}', 0, 0))
            connection.execute('INSERT INTO audit_events(audit_id,actor_type,action,entity_type,entity_id,detail_json) VALUES(?,?,?,?,?,?)',
                (new_id('aud'), 'admin', 'device.provision', 'device', registry_id, json.dumps({'hardware_id': hardware_id, 'device_type': device_type})))
    except sqlite3.IntegrityError as exc:
        raise HTTPException(status_code=409, detail={'code': 'DEVICE_ALREADY_REGISTERED'}) from exc
    return {'registry_id': registry_id, 'hardware_id': hardware_id, 'device_type': device_type, 'device_key': secrets_token, 'warning': 'Simpan device_key sekarang; nilainya tidak dapat dibaca ulang.'}


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

@app.post('/api/v2/members', status_code=201, dependencies=[Depends(require_admin)])
def create_member(payload: MemberCreate, connection: DB):
    member_id = 'NTR-' + str(connection.execute("SELECT COUNT(*) + 1 FROM members").fetchone()[0]).zfill(5)
    account_id = new_id('acct')
    try:
        with transaction(connection):
            connection.execute('INSERT INTO members(member_id,display_name) VALUES(?,?)', (member_id, payload.display_name.strip()))
            connection.execute("INSERT INTO accounts(account_id,member_id,account_type) VALUES(?,?,'member')", (account_id, member_id))
            connection.execute('INSERT INTO audit_events(audit_id,actor_type,action,entity_type,entity_id) VALUES(?,?,?,?,?)', (new_id('aud'), 'admin', 'member.create', 'member', member_id))
    except sqlite3.IntegrityError as exc:
        raise HTTPException(status_code=409, detail={'code': 'MEMBER_CREATE_CONFLICT'}) from exc
    return {'member_id': member_id, 'display_name': payload.display_name.strip(), 'account_id': account_id, 'balance_minor': 0, 'status': 'active'}

@app.get('/api/v2/members', dependencies=[Depends(require_admin)])
def list_members(connection: DB):
    rows = connection.execute('SELECT m.member_id,m.display_name,m.status,a.balance_minor FROM members m JOIN accounts a ON a.member_id=m.member_id ORDER BY m.created_at DESC').fetchall()
    return {'items': [dict(row) for row in rows]}

@app.post('/api/v2/finance/top-ups', dependencies=[Depends(require_admin)])
def top_up(payload: TopUpRequest, connection: DB):
    prior = connection.execute('SELECT transaction_id,status,member_id,amount_minor FROM transactions WHERE request_id=?', (payload.request_id,)).fetchone()
    if prior:
        if prior['member_id'] != payload.member_id or prior['amount_minor'] != payload.amount_minor or prior['status'] != 'succeeded':
            raise HTTPException(status_code=409, detail={'code': 'IDEMPOTENCY_CONFLICT'})
        return {'transaction_id': prior['transaction_id'], 'status': prior['status'], 'idempotent_replay': True}
    account = connection.execute("SELECT account_id,balance_minor,status FROM accounts WHERE member_id=? AND account_type='member'", (payload.member_id,)).fetchone()
    if not account:
        raise HTTPException(status_code=404, detail={'code': 'MEMBER_ACCOUNT_NOT_FOUND'})
    if account['status'] != 'active':
        raise HTTPException(status_code=409, detail={'code': 'ACCOUNT_NOT_ACTIVE'})
    transaction_id = new_id('txn')
    system_account = connection.execute("SELECT account_id FROM accounts WHERE account_type='system' LIMIT 1").fetchone()
    with transaction(connection):
        if not system_account:
            system_id = new_id('acct')
            connection.execute("INSERT INTO accounts(account_id,account_type,balance_minor) VALUES(?,'system',0)", (system_id,))
            system_account_id = system_id
        else:
            system_account_id = system_account['account_id']
        connection.execute("INSERT INTO transactions(transaction_id,request_id,member_id,transaction_type,amount_minor,status,metadata_json,completed_at) VALUES(?,?,?,'top_up',?,'succeeded',?,CURRENT_TIMESTAMP)", (transaction_id, payload.request_id, payload.member_id, payload.amount_minor, json.dumps({'description': payload.description})))
        connection.execute('UPDATE accounts SET balance_minor=balance_minor+?,updated_at=CURRENT_TIMESTAMP WHERE account_id=?', (payload.amount_minor, account['account_id']))
        connection.execute("INSERT INTO ledger_entries(entry_id,transaction_id,account_id,direction,amount_minor) VALUES(?,?,?,'credit',?)", (new_id('led'), transaction_id, account['account_id'], payload.amount_minor))
        connection.execute("INSERT INTO ledger_entries(entry_id,transaction_id,account_id,direction,amount_minor) VALUES(?,?,?,'debit',?)", (new_id('led'), transaction_id, system_account_id, payload.amount_minor))
        connection.execute('INSERT INTO audit_events(audit_id,actor_type,action,entity_type,entity_id,request_id,detail_json) VALUES(?,?,?,?,?,?,?)', (new_id('aud'), 'admin', 'finance.top_up', 'transaction', transaction_id, payload.request_id, json.dumps({'member_id': payload.member_id, 'amount_minor': payload.amount_minor})))
    return {'transaction_id': transaction_id, 'status': 'succeeded', 'idempotent_replay': False}

@app.get('/api/v2/vending/devices', dependencies=[Depends(require_admin)])
def vending_devices(connection: DB):
    rows = connection.execute("SELECT registry_id,hardware_id,display_name,status,mac_address,last_seen_at FROM device_registry WHERE device_type='vending' ORDER BY created_at DESC").fetchall()
    return {'items': [dict(row) for row in rows]}

@app.get('/api/v2/vending/devices/{registry_id}/products', dependencies=[Depends(require_admin)])
def get_products(registry_id: str, connection: DB):
    device = connection.execute("SELECT registry_id FROM device_registry WHERE registry_id=? AND device_type='vending'", (registry_id,)).fetchone()
    if not device:
        raise HTTPException(status_code=404, detail={'code': 'VENDING_DEVICE_NOT_FOUND'})
    rows = connection.execute('SELECT product_id,name,price_minor,stock,image_path,nfc_promo_percent,qris_promo_percent FROM product_slots WHERE registry_id=? ORDER BY product_id', (registry_id,)).fetchall()
    return {'registry_id': registry_id, 'items': [dict(row) for row in rows]}

@app.put('/api/v2/vending/devices/{registry_id}/products/{product_id}', dependencies=[Depends(require_admin)])
def update_product(registry_id: str, product_id: int, payload: ProductUpdate, connection: DB):
    if product_id not in range(1, 6):
        raise HTTPException(status_code=422, detail={'code': 'INVALID_PRODUCT_SLOT'})
    with transaction(connection):
        result = connection.execute('UPDATE product_slots SET name=?,price_minor=?,stock=?,updated_at=CURRENT_TIMESTAMP WHERE registry_id=? AND product_id=?', (payload.name.strip(), payload.price_minor, payload.stock, registry_id, product_id))
        if result.rowcount != 1:
            raise HTTPException(status_code=404, detail={'code': 'PRODUCT_SLOT_NOT_FOUND'})
        connection.execute('INSERT INTO audit_events(audit_id,actor_type,action,entity_type,entity_id,detail_json) VALUES(?,?,?,?,?,?)', (new_id('aud'), 'admin', 'vending.product.update', 'product_slot', f'{registry_id}:{product_id}', json.dumps(payload.model_dump())))
    return {'registry_id': registry_id, 'product_id': product_id, **payload.model_dump(), 'nfc_promo_percent': 0, 'qris_promo_percent': 0}

@app.get('/api/v2/admin/audit', dependencies=[Depends(require_admin)])
def list_audit(connection: DB, limit: int = 100):
    limit = max(1, min(limit, 500))
    rows = connection.execute('SELECT audit_id,actor_type,actor_id,action,entity_type,entity_id,request_id,detail_json,created_at FROM audit_events ORDER BY created_at DESC LIMIT ?', (limit,)).fetchall()
    return {'items': [dict(row) for row in rows]}
 + '310000'

@app.get('/api/v2/ready')
def readiness(connection: DB):
    try:
        connection.execute('SELECT 1').fetchone()
    except sqlite3.Error as exc:
        raise HTTPException(status_code=503, detail={'code': 'DATABASE_NOT_READY'}) from exc
    return {'status': 'ready', 'database': 'ok'}

@app.post('/api/v2/admin/devices', status_code=201, dependencies=[Depends(require_admin)])
def register_device(payload: dict, connection: DB):
    hardware_id = str(payload.get('hardware_id', '')).strip()
    device_type = payload.get('device_type')
    display_name = str(payload.get('display_name', '')).strip()
    if not hardware_id or len(hardware_id) > 128 or device_type not in ('cashier', 'vending'):
        raise HTTPException(status_code=422, detail={'code': 'INVALID_DEVICE_REGISTRATION'})
    registry_id = new_id('reg')
    device_key = secrets.token_urlsafe(32)
    try:
        with transaction(connection):
            connection.execute('INSERT INTO device_registry(registry_id,hardware_id,device_type,display_name,status,device_key_hash,device_key_hint) VALUES(?,?,?,?,?,?,?)',
                (registry_id, hardware_id, device_type, display_name, 'active', hash_secret(device_key, settings.device_key_pepper), device_key[-4:]))
            connection.execute('INSERT INTO device_events(event_id,registry_id,hardware_id,event_type,detail_json) VALUES(?,?,?,?,?)',
                (new_id('evt'), registry_id, hardware_id, 'device.provisioned', json.dumps({'device_type': device_type})))
            if device_type == 'vending':
                for product_id in range(1, 6):
                    connection.execute('INSERT INTO product_slots(registry_id,product_id,name,price_minor,stock) VALUES(?,?,?,?,?)', (registry_id, product_id, f'Produk {product_id}', 0, 0))
            connection.execute('INSERT INTO audit_events(audit_id,actor_type,action,entity_type,entity_id,detail_json) VALUES(?,?,?,?,?,?)',
                (new_id('aud'), 'admin', 'device.provision', 'device', registry_id, json.dumps({'hardware_id': hardware_id, 'device_type': device_type})))
    except sqlite3.IntegrityError as exc:
        raise HTTPException(status_code=409, detail={'code': 'DEVICE_ALREADY_REGISTERED'}) from exc
    return {'registry_id': registry_id, 'hardware_id': hardware_id, 'device_type': device_type, 'device_key': secrets_token, 'warning': 'Simpan device_key sekarang; nilainya tidak dapat dibaca ulang.'}


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
            connection.execute('INSERT INTO members(member_id,display_name,pin_hash) VALUES(?,?,?)',
                (member_id, display_name, pin_hash(payload.pin) if payload.pin else None))
            connection.execute("INSERT INTO accounts(account_id,member_id,account_type) VALUES(?,?,'member')", (account_id, member_id))
            audit(connection, 'member.create', 'member', member_id)
    except sqlite3.IntegrityError as exc:
        raise HTTPException(status_code=409, detail={'code': 'MEMBER_CREATE_CONFLICT'}) from exc
    return {'member_id': member_id, 'display_name': display_name, 'account_id': account_id,
            'balance_minor': 0, 'status': 'active', 'pin_configured': bool(payload.pin)}

@app.get('/api/v2/members', dependencies=[Depends(require_admin)])
def list_members(connection: DB):
    rows = connection.execute('SELECT m.member_id,m.display_name,m.status,a.balance_minor FROM members m JOIN accounts a ON a.member_id=m.member_id ORDER BY m.created_at DESC').fetchall()
    return {'items': [dict(row) for row in rows]}

@app.post('/api/v2/finance/top-ups', dependencies=[Depends(require_admin)])
def top_up(payload: TopUpRequest, connection: DB):
    transaction_id = new_id('txn')
    try:
        with transaction(connection):
            prior = connection.execute("SELECT transaction_id,status,member_id,amount_minor,transaction_type FROM transactions WHERE request_id=?", (payload.request_id,)).fetchone()
            if prior:
                if prior['member_id'] != payload.member_id or prior['amount_minor'] != payload.amount_minor or prior['transaction_type'] != 'top_up' or prior['status'] != 'succeeded':
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
            connection.execute("INSERT INTO ledger_entries(entry_id,transaction_id,account_id,direction,amount_minor) VALUES(?,?,?,'credit',?)", (new_id('led'), transaction_id, account['account_id'], payload.amount_minor))
            connection.execute("INSERT INTO ledger_entries(entry_id,transaction_id,account_id,direction,amount_minor) VALUES(?,?,?,'debit',?)", (new_id('led'), transaction_id, system_account_id, payload.amount_minor))
            audit(connection, 'finance.top_up', 'transaction', transaction_id, payload.request_id, {'member_id': payload.member_id, 'amount_minor': payload.amount_minor})
    except sqlite3.IntegrityError as exc:
        raise HTTPException(status_code=409, detail={'code': 'IDEMPOTENCY_CONFLICT'}) from exc
    return {'transaction_id': transaction_id, 'status': 'succeeded', 'idempotent_replay': False}


@app.get('/api/v2/vending/devices', dependencies=[Depends(require_admin)])
def vending_devices(connection: DB):
    rows = connection.execute("SELECT registry_id,hardware_id,display_name,status,mac_address,last_seen_at FROM device_registry WHERE device_type='vending' ORDER BY created_at DESC").fetchall()
    return {'items': [dict(row) for row in rows]}

@app.get('/api/v2/vending/devices/{registry_id}/products', dependencies=[Depends(require_admin)])
def get_products(registry_id: str, connection: DB):
    device = connection.execute("SELECT registry_id FROM device_registry WHERE registry_id=? AND device_type='vending'", (registry_id,)).fetchone()
    if not device:
        raise HTTPException(status_code=404, detail={'code': 'VENDING_DEVICE_NOT_FOUND'})
    rows = connection.execute('SELECT product_id,name,price_minor,stock,image_path,nfc_promo_percent,qris_promo_percent FROM product_slots WHERE registry_id=? ORDER BY product_id', (registry_id,)).fetchall()
    return {'registry_id': registry_id, 'items': [dict(row) for row in rows]}

@app.put('/api/v2/vending/devices/{registry_id}/products/{product_id}', dependencies=[Depends(require_admin)])
def update_product(registry_id: str, product_id: int, payload: ProductUpdate, connection: DB):
    if product_id not in range(1, 6):
        raise HTTPException(status_code=422, detail={'code': 'INVALID_PRODUCT_SLOT'})
    with transaction(connection):
        result = connection.execute('UPDATE product_slots SET name=?,price_minor=?,stock=?,updated_at=CURRENT_TIMESTAMP WHERE registry_id=? AND product_id=?', (payload.name.strip(), payload.price_minor, payload.stock, registry_id, product_id))
        if result.rowcount != 1:
            raise HTTPException(status_code=404, detail={'code': 'PRODUCT_SLOT_NOT_FOUND'})
        connection.execute('INSERT INTO audit_events(audit_id,actor_type,action,entity_type,entity_id,detail_json) VALUES(?,?,?,?,?,?)', (new_id('aud'), 'admin', 'vending.product.update', 'product_slot', f'{registry_id}:{product_id}', json.dumps(payload.model_dump())))
    return {'registry_id': registry_id, 'product_id': product_id, **payload.model_dump(), 'nfc_promo_percent': 0, 'qris_promo_percent': 0}

@app.get('/api/v2/admin/audit', dependencies=[Depends(require_admin)])
def list_audit(connection: DB, limit: int = 100):
    limit = max(1, min(limit, 500))
    rows = connection.execute('SELECT audit_id,actor_type,actor_id,action,entity_type,entity_id,request_id,detail_json,created_at FROM audit_events ORDER BY created_at DESC LIMIT ?', (limit,)).fetchall()
    return {'items': [dict(row) for row in rows]}
)

class CardEnroll(BaseModel):
    card_uid: str = Field(min_length=4, max_length=128)

class PurchaseRequest(BaseModel):
    request_id: str = Field(min_length=8, max_length=128)
    card_uid: str = Field(min_length=4, max_length=128)
    pin: str = Field(min_length=6, max_length=12, pattern=r'^\\d{6,12}

class TopUpRequest(BaseModel):
    request_id: str = Field(min_length=8, max_length=128)
    member_id: str = Field(min_length=1, max_length=128)
    amount_minor: int = Field(gt=0, le=100_000_000)
    description: str = Field(default='Top-up saldo', max_length=200)

class PurchaseRequest(BaseModel):
    request_id: str = Field(min_length=8, max_length=128)
    member_id: str = Field(min_length=1, max_length=128)
    product_id: int = Field(ge=1, le=5)
    payment_method: str = Field(pattern='^(nfc|qris)$')

class ProductUpdate(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    price_minor: int = Field(ge=0, le=100_000_000)
    stock: int = Field(ge=0, le=1_000_000)

@app.get('/api/v2/health')
def health():
    return {'status': 'ok', 'service': 'mgroup-api', 'version': '2.0.0'}

@app.get('/api/v2/ready')
def readiness(connection: DB):
    try:
        connection.execute('SELECT 1').fetchone()
    except sqlite3.Error as exc:
        raise HTTPException(status_code=503, detail={'code': 'DATABASE_NOT_READY'}) from exc
    return {'status': 'ready', 'database': 'ok'}

@app.post('/api/v2/admin/devices', status_code=201, dependencies=[Depends(require_admin)])
def register_device(payload: dict, connection: DB):
    hardware_id = str(payload.get('hardware_id', '')).strip()
    device_type = payload.get('device_type')
    display_name = str(payload.get('display_name', '')).strip()
    if not hardware_id or len(hardware_id) > 128 or device_type not in ('cashier', 'vending'):
        raise HTTPException(status_code=422, detail={'code': 'INVALID_DEVICE_REGISTRATION'})
    registry_id = new_id('reg')
    device_key = secrets_token = __import__('secrets').token_urlsafe(32)
    try:
        with transaction(connection):
            connection.execute('INSERT INTO device_registry(registry_id,hardware_id,device_type,display_name,status,device_key_hash,device_key_hint) VALUES(?,?,?,?,?,?,?)',
                (registry_id, hardware_id, device_type, display_name, 'active', hash_secret(device_key, settings.device_key_pepper), device_key[-4:]))
            connection.execute('INSERT INTO device_events(event_id,registry_id,hardware_id,event_type,detail_json) VALUES(?,?,?,?,?)',
                (new_id('evt'), registry_id, hardware_id, 'device.provisioned', json.dumps({'device_type': device_type})))
            if device_type == 'vending':
                for product_id in range(1, 6):
                    connection.execute('INSERT INTO product_slots(registry_id,product_id,name,price_minor,stock) VALUES(?,?,?,?,?)', (registry_id, product_id, f'Produk {product_id}', 0, 0))
            connection.execute('INSERT INTO audit_events(audit_id,actor_type,action,entity_type,entity_id,detail_json) VALUES(?,?,?,?,?,?)',
                (new_id('aud'), 'admin', 'device.provision', 'device', registry_id, json.dumps({'hardware_id': hardware_id, 'device_type': device_type})))
    except sqlite3.IntegrityError as exc:
        raise HTTPException(status_code=409, detail={'code': 'DEVICE_ALREADY_REGISTERED'}) from exc
    return {'registry_id': registry_id, 'hardware_id': hardware_id, 'device_type': device_type, 'device_key': secrets_token, 'warning': 'Simpan device_key sekarang; nilainya tidak dapat dibaca ulang.'}


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

@app.post('/api/v2/members', status_code=201, dependencies=[Depends(require_admin)])
def create_member(payload: MemberCreate, connection: DB):
    member_id = 'NTR-' + str(connection.execute("SELECT COUNT(*) + 1 FROM members").fetchone()[0]).zfill(5)
    account_id = new_id('acct')
    try:
        with transaction(connection):
            connection.execute('INSERT INTO members(member_id,display_name) VALUES(?,?)', (member_id, payload.display_name.strip()))
            connection.execute("INSERT INTO accounts(account_id,member_id,account_type) VALUES(?,?,'member')", (account_id, member_id))
            connection.execute('INSERT INTO audit_events(audit_id,actor_type,action,entity_type,entity_id) VALUES(?,?,?,?,?)', (new_id('aud'), 'admin', 'member.create', 'member', member_id))
    except sqlite3.IntegrityError as exc:
        raise HTTPException(status_code=409, detail={'code': 'MEMBER_CREATE_CONFLICT'}) from exc
    return {'member_id': member_id, 'display_name': payload.display_name.strip(), 'account_id': account_id, 'balance_minor': 0, 'status': 'active'}

@app.get('/api/v2/members', dependencies=[Depends(require_admin)])
def list_members(connection: DB):
    rows = connection.execute('SELECT m.member_id,m.display_name,m.status,a.balance_minor FROM members m JOIN accounts a ON a.member_id=m.member_id ORDER BY m.created_at DESC').fetchall()
    return {'items': [dict(row) for row in rows]}

@app.post('/api/v2/finance/top-ups', dependencies=[Depends(require_admin)])
def top_up(payload: TopUpRequest, connection: DB):
    prior = connection.execute('SELECT transaction_id,status,member_id,amount_minor FROM transactions WHERE request_id=?', (payload.request_id,)).fetchone()
    if prior:
        if prior['member_id'] != payload.member_id or prior['amount_minor'] != payload.amount_minor or prior['status'] != 'succeeded':
            raise HTTPException(status_code=409, detail={'code': 'IDEMPOTENCY_CONFLICT'})
        return {'transaction_id': prior['transaction_id'], 'status': prior['status'], 'idempotent_replay': True}
    account = connection.execute("SELECT account_id,balance_minor,status FROM accounts WHERE member_id=? AND account_type='member'", (payload.member_id,)).fetchone()
    if not account:
        raise HTTPException(status_code=404, detail={'code': 'MEMBER_ACCOUNT_NOT_FOUND'})
    if account['status'] != 'active':
        raise HTTPException(status_code=409, detail={'code': 'ACCOUNT_NOT_ACTIVE'})
    transaction_id = new_id('txn')
    system_account = connection.execute("SELECT account_id FROM accounts WHERE account_type='system' LIMIT 1").fetchone()
    with transaction(connection):
        if not system_account:
            system_id = new_id('acct')
            connection.execute("INSERT INTO accounts(account_id,account_type,balance_minor) VALUES(?,'system',0)", (system_id,))
            system_account_id = system_id
        else:
            system_account_id = system_account['account_id']
        connection.execute("INSERT INTO transactions(transaction_id,request_id,member_id,transaction_type,amount_minor,status,metadata_json,completed_at) VALUES(?,?,?,'top_up',?,'succeeded',?,CURRENT_TIMESTAMP)", (transaction_id, payload.request_id, payload.member_id, payload.amount_minor, json.dumps({'description': payload.description})))
        connection.execute('UPDATE accounts SET balance_minor=balance_minor+?,updated_at=CURRENT_TIMESTAMP WHERE account_id=?', (payload.amount_minor, account['account_id']))
        connection.execute("INSERT INTO ledger_entries(entry_id,transaction_id,account_id,direction,amount_minor) VALUES(?,?,?,'credit',?)", (new_id('led'), transaction_id, account['account_id'], payload.amount_minor))
        connection.execute("INSERT INTO ledger_entries(entry_id,transaction_id,account_id,direction,amount_minor) VALUES(?,?,?,'debit',?)", (new_id('led'), transaction_id, system_account_id, payload.amount_minor))
        connection.execute('INSERT INTO audit_events(audit_id,actor_type,action,entity_type,entity_id,request_id,detail_json) VALUES(?,?,?,?,?,?,?)', (new_id('aud'), 'admin', 'finance.top_up', 'transaction', transaction_id, payload.request_id, json.dumps({'member_id': payload.member_id, 'amount_minor': payload.amount_minor})))
    return {'transaction_id': transaction_id, 'status': 'succeeded', 'idempotent_replay': False}

@app.get('/api/v2/vending/devices', dependencies=[Depends(require_admin)])
def vending_devices(connection: DB):
    rows = connection.execute("SELECT registry_id,hardware_id,display_name,status,mac_address,last_seen_at FROM device_registry WHERE device_type='vending' ORDER BY created_at DESC").fetchall()
    return {'items': [dict(row) for row in rows]}

@app.get('/api/v2/vending/devices/{registry_id}/products', dependencies=[Depends(require_admin)])
def get_products(registry_id: str, connection: DB):
    device = connection.execute("SELECT registry_id FROM device_registry WHERE registry_id=? AND device_type='vending'", (registry_id,)).fetchone()
    if not device:
        raise HTTPException(status_code=404, detail={'code': 'VENDING_DEVICE_NOT_FOUND'})
    rows = connection.execute('SELECT product_id,name,price_minor,stock,image_path,nfc_promo_percent,qris_promo_percent FROM product_slots WHERE registry_id=? ORDER BY product_id', (registry_id,)).fetchall()
    return {'registry_id': registry_id, 'items': [dict(row) for row in rows]}

@app.put('/api/v2/vending/devices/{registry_id}/products/{product_id}', dependencies=[Depends(require_admin)])
def update_product(registry_id: str, product_id: int, payload: ProductUpdate, connection: DB):
    if product_id not in range(1, 6):
        raise HTTPException(status_code=422, detail={'code': 'INVALID_PRODUCT_SLOT'})
    with transaction(connection):
        result = connection.execute('UPDATE product_slots SET name=?,price_minor=?,stock=?,updated_at=CURRENT_TIMESTAMP WHERE registry_id=? AND product_id=?', (payload.name.strip(), payload.price_minor, payload.stock, registry_id, product_id))
        if result.rowcount != 1:
            raise HTTPException(status_code=404, detail={'code': 'PRODUCT_SLOT_NOT_FOUND'})
        connection.execute('INSERT INTO audit_events(audit_id,actor_type,action,entity_type,entity_id,detail_json) VALUES(?,?,?,?,?,?)', (new_id('aud'), 'admin', 'vending.product.update', 'product_slot', f'{registry_id}:{product_id}', json.dumps(payload.model_dump())))
    return {'registry_id': registry_id, 'product_id': product_id, **payload.model_dump(), 'nfc_promo_percent': 0, 'qris_promo_percent': 0}

@app.get('/api/v2/admin/audit', dependencies=[Depends(require_admin)])
def list_audit(connection: DB, limit: int = 100):
    limit = max(1, min(limit, 500))
    rows = connection.execute('SELECT audit_id,actor_type,actor_id,action,entity_type,entity_id,request_id,detail_json,created_at FROM audit_events ORDER BY created_at DESC LIMIT ?', (limit,)).fetchall()
    return {'items': [dict(row) for row in rows]}
)
    product_id: int = Field(ge=1, le=5)

class DispenseResult(BaseModel):
    succeeded: bool
    reason: str | None = Field(default=None, max_length=200)

class TopUpRequest(BaseModel):
    request_id: str = Field(min_length=8, max_length=128)
    member_id: str = Field(min_length=1, max_length=128)
    amount_minor: int = Field(gt=0, le=100_000_000)
    description: str = Field(default='Top-up saldo', max_length=200)

class PurchaseRequest(BaseModel):
    request_id: str = Field(min_length=8, max_length=128)
    member_id: str = Field(min_length=1, max_length=128)
    product_id: int = Field(ge=1, le=5)
    payment_method: str = Field(pattern='^(nfc|qris)$')

class ProductUpdate(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    price_minor: int = Field(ge=0, le=100_000_000)
    stock: int = Field(ge=0, le=1_000_000)

@app.get('/api/v2/health')
def health():
    return {'status': 'ok', 'service': 'mgroup-api', 'version': '2.0.0'}

@app.get('/api/v2/ready')
def readiness(connection: DB):
    try:
        connection.execute('SELECT 1').fetchone()
    except sqlite3.Error as exc:
        raise HTTPException(status_code=503, detail={'code': 'DATABASE_NOT_READY'}) from exc
    return {'status': 'ready', 'database': 'ok'}

@app.post('/api/v2/admin/devices', status_code=201, dependencies=[Depends(require_admin)])
def register_device(payload: dict, connection: DB):
    hardware_id = str(payload.get('hardware_id', '')).strip()
    device_type = payload.get('device_type')
    display_name = str(payload.get('display_name', '')).strip()
    if not hardware_id or len(hardware_id) > 128 or device_type not in ('cashier', 'vending'):
        raise HTTPException(status_code=422, detail={'code': 'INVALID_DEVICE_REGISTRATION'})
    registry_id = new_id('reg')
    device_key = secrets_token = __import__('secrets').token_urlsafe(32)
    try:
        with transaction(connection):
            connection.execute('INSERT INTO device_registry(registry_id,hardware_id,device_type,display_name,status,device_key_hash,device_key_hint) VALUES(?,?,?,?,?,?,?)',
                (registry_id, hardware_id, device_type, display_name, 'active', hash_secret(device_key, settings.device_key_pepper), device_key[-4:]))
            connection.execute('INSERT INTO device_events(event_id,registry_id,hardware_id,event_type,detail_json) VALUES(?,?,?,?,?)',
                (new_id('evt'), registry_id, hardware_id, 'device.provisioned', json.dumps({'device_type': device_type})))
            if device_type == 'vending':
                for product_id in range(1, 6):
                    connection.execute('INSERT INTO product_slots(registry_id,product_id,name,price_minor,stock) VALUES(?,?,?,?,?)', (registry_id, product_id, f'Produk {product_id}', 0, 0))
            connection.execute('INSERT INTO audit_events(audit_id,actor_type,action,entity_type,entity_id,detail_json) VALUES(?,?,?,?,?,?)',
                (new_id('aud'), 'admin', 'device.provision', 'device', registry_id, json.dumps({'hardware_id': hardware_id, 'device_type': device_type})))
    except sqlite3.IntegrityError as exc:
        raise HTTPException(status_code=409, detail={'code': 'DEVICE_ALREADY_REGISTERED'}) from exc
    return {'registry_id': registry_id, 'hardware_id': hardware_id, 'device_type': device_type, 'device_key': secrets_token, 'warning': 'Simpan device_key sekarang; nilainya tidak dapat dibaca ulang.'}


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

@app.post('/api/v2/members', status_code=201, dependencies=[Depends(require_admin)])
def create_member(payload: MemberCreate, connection: DB):
    member_id = 'NTR-' + str(connection.execute("SELECT COUNT(*) + 1 FROM members").fetchone()[0]).zfill(5)
    account_id = new_id('acct')
    try:
        with transaction(connection):
            connection.execute('INSERT INTO members(member_id,display_name) VALUES(?,?)', (member_id, payload.display_name.strip()))
            connection.execute("INSERT INTO accounts(account_id,member_id,account_type) VALUES(?,?,'member')", (account_id, member_id))
            connection.execute('INSERT INTO audit_events(audit_id,actor_type,action,entity_type,entity_id) VALUES(?,?,?,?,?)', (new_id('aud'), 'admin', 'member.create', 'member', member_id))
    except sqlite3.IntegrityError as exc:
        raise HTTPException(status_code=409, detail={'code': 'MEMBER_CREATE_CONFLICT'}) from exc
    return {'member_id': member_id, 'display_name': payload.display_name.strip(), 'account_id': account_id, 'balance_minor': 0, 'status': 'active'}

@app.get('/api/v2/members', dependencies=[Depends(require_admin)])
def list_members(connection: DB):
    rows = connection.execute('SELECT m.member_id,m.display_name,m.status,a.balance_minor FROM members m JOIN accounts a ON a.member_id=m.member_id ORDER BY m.created_at DESC').fetchall()
    return {'items': [dict(row) for row in rows]}

@app.post('/api/v2/finance/top-ups', dependencies=[Depends(require_admin)])
def top_up(payload: TopUpRequest, connection: DB):
    prior = connection.execute('SELECT transaction_id,status,member_id,amount_minor FROM transactions WHERE request_id=?', (payload.request_id,)).fetchone()
    if prior:
        if prior['member_id'] != payload.member_id or prior['amount_minor'] != payload.amount_minor or prior['status'] != 'succeeded':
            raise HTTPException(status_code=409, detail={'code': 'IDEMPOTENCY_CONFLICT'})
        return {'transaction_id': prior['transaction_id'], 'status': prior['status'], 'idempotent_replay': True}
    account = connection.execute("SELECT account_id,balance_minor,status FROM accounts WHERE member_id=? AND account_type='member'", (payload.member_id,)).fetchone()
    if not account:
        raise HTTPException(status_code=404, detail={'code': 'MEMBER_ACCOUNT_NOT_FOUND'})
    if account['status'] != 'active':
        raise HTTPException(status_code=409, detail={'code': 'ACCOUNT_NOT_ACTIVE'})
    transaction_id = new_id('txn')
    system_account = connection.execute("SELECT account_id FROM accounts WHERE account_type='system' LIMIT 1").fetchone()
    with transaction(connection):
        if not system_account:
            system_id = new_id('acct')
            connection.execute("INSERT INTO accounts(account_id,account_type,balance_minor) VALUES(?,'system',0)", (system_id,))
            system_account_id = system_id
        else:
            system_account_id = system_account['account_id']
        connection.execute("INSERT INTO transactions(transaction_id,request_id,member_id,transaction_type,amount_minor,status,metadata_json,completed_at) VALUES(?,?,?,'top_up',?,'succeeded',?,CURRENT_TIMESTAMP)", (transaction_id, payload.request_id, payload.member_id, payload.amount_minor, json.dumps({'description': payload.description})))
        connection.execute('UPDATE accounts SET balance_minor=balance_minor+?,updated_at=CURRENT_TIMESTAMP WHERE account_id=?', (payload.amount_minor, account['account_id']))
        connection.execute("INSERT INTO ledger_entries(entry_id,transaction_id,account_id,direction,amount_minor) VALUES(?,?,?,'credit',?)", (new_id('led'), transaction_id, account['account_id'], payload.amount_minor))
        connection.execute("INSERT INTO ledger_entries(entry_id,transaction_id,account_id,direction,amount_minor) VALUES(?,?,?,'debit',?)", (new_id('led'), transaction_id, system_account_id, payload.amount_minor))
        connection.execute('INSERT INTO audit_events(audit_id,actor_type,action,entity_type,entity_id,request_id,detail_json) VALUES(?,?,?,?,?,?,?)', (new_id('aud'), 'admin', 'finance.top_up', 'transaction', transaction_id, payload.request_id, json.dumps({'member_id': payload.member_id, 'amount_minor': payload.amount_minor})))
    return {'transaction_id': transaction_id, 'status': 'succeeded', 'idempotent_replay': False}

@app.get('/api/v2/vending/devices', dependencies=[Depends(require_admin)])
def vending_devices(connection: DB):
    rows = connection.execute("SELECT registry_id,hardware_id,display_name,status,mac_address,last_seen_at FROM device_registry WHERE device_type='vending' ORDER BY created_at DESC").fetchall()
    return {'items': [dict(row) for row in rows]}

@app.get('/api/v2/vending/devices/{registry_id}/products', dependencies=[Depends(require_admin)])
def get_products(registry_id: str, connection: DB):
    device = connection.execute("SELECT registry_id FROM device_registry WHERE registry_id=? AND device_type='vending'", (registry_id,)).fetchone()
    if not device:
        raise HTTPException(status_code=404, detail={'code': 'VENDING_DEVICE_NOT_FOUND'})
    rows = connection.execute('SELECT product_id,name,price_minor,stock,image_path,nfc_promo_percent,qris_promo_percent FROM product_slots WHERE registry_id=? ORDER BY product_id', (registry_id,)).fetchall()
    return {'registry_id': registry_id, 'items': [dict(row) for row in rows]}

@app.put('/api/v2/vending/devices/{registry_id}/products/{product_id}', dependencies=[Depends(require_admin)])
def update_product(registry_id: str, product_id: int, payload: ProductUpdate, connection: DB):
    if product_id not in range(1, 6):
        raise HTTPException(status_code=422, detail={'code': 'INVALID_PRODUCT_SLOT'})
    with transaction(connection):
        result = connection.execute('UPDATE product_slots SET name=?,price_minor=?,stock=?,updated_at=CURRENT_TIMESTAMP WHERE registry_id=? AND product_id=?', (payload.name.strip(), payload.price_minor, payload.stock, registry_id, product_id))
        if result.rowcount != 1:
            raise HTTPException(status_code=404, detail={'code': 'PRODUCT_SLOT_NOT_FOUND'})
        connection.execute('INSERT INTO audit_events(audit_id,actor_type,action,entity_type,entity_id,detail_json) VALUES(?,?,?,?,?,?)', (new_id('aud'), 'admin', 'vending.product.update', 'product_slot', f'{registry_id}:{product_id}', json.dumps(payload.model_dump())))
    return {'registry_id': registry_id, 'product_id': product_id, **payload.model_dump(), 'nfc_promo_percent': 0, 'qris_promo_percent': 0}

@app.get('/api/v2/admin/audit', dependencies=[Depends(require_admin)])
def list_audit(connection: DB, limit: int = 100):
    limit = max(1, min(limit, 500))
    rows = connection.execute('SELECT audit_id,actor_type,actor_id,action,entity_type,entity_id,request_id,detail_json,created_at FROM audit_events ORDER BY created_at DESC LIMIT ?', (limit,)).fetchall()
    return {'items': [dict(row) for row in rows]}
 + salt + '

@app.get('/api/v2/ready')
def readiness(connection: DB):
    try:
        connection.execute('SELECT 1').fetchone()
    except sqlite3.Error as exc:
        raise HTTPException(status_code=503, detail={'code': 'DATABASE_NOT_READY'}) from exc
    return {'status': 'ready', 'database': 'ok'}

@app.post('/api/v2/admin/devices', status_code=201, dependencies=[Depends(require_admin)])
def register_device(payload: dict, connection: DB):
    hardware_id = str(payload.get('hardware_id', '')).strip()
    device_type = payload.get('device_type')
    display_name = str(payload.get('display_name', '')).strip()
    if not hardware_id or len(hardware_id) > 128 or device_type not in ('cashier', 'vending'):
        raise HTTPException(status_code=422, detail={'code': 'INVALID_DEVICE_REGISTRATION'})
    registry_id = new_id('reg')
    device_key = secrets_token = __import__('secrets').token_urlsafe(32)
    try:
        with transaction(connection):
            connection.execute('INSERT INTO device_registry(registry_id,hardware_id,device_type,display_name,status,device_key_hash,device_key_hint) VALUES(?,?,?,?,?,?,?)',
                (registry_id, hardware_id, device_type, display_name, 'active', hash_secret(device_key, settings.device_key_pepper), device_key[-4:]))
            connection.execute('INSERT INTO device_events(event_id,registry_id,hardware_id,event_type,detail_json) VALUES(?,?,?,?,?)',
                (new_id('evt'), registry_id, hardware_id, 'device.provisioned', json.dumps({'device_type': device_type})))
            if device_type == 'vending':
                for product_id in range(1, 6):
                    connection.execute('INSERT INTO product_slots(registry_id,product_id,name,price_minor,stock) VALUES(?,?,?,?,?)', (registry_id, product_id, f'Produk {product_id}', 0, 0))
            connection.execute('INSERT INTO audit_events(audit_id,actor_type,action,entity_type,entity_id,detail_json) VALUES(?,?,?,?,?,?)',
                (new_id('aud'), 'admin', 'device.provision', 'device', registry_id, json.dumps({'hardware_id': hardware_id, 'device_type': device_type})))
    except sqlite3.IntegrityError as exc:
        raise HTTPException(status_code=409, detail={'code': 'DEVICE_ALREADY_REGISTERED'}) from exc
    return {'registry_id': registry_id, 'hardware_id': hardware_id, 'device_type': device_type, 'device_key': secrets_token, 'warning': 'Simpan device_key sekarang; nilainya tidak dapat dibaca ulang.'}


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

@app.post('/api/v2/members', status_code=201, dependencies=[Depends(require_admin)])
def create_member(payload: MemberCreate, connection: DB):
    member_id = 'NTR-' + str(connection.execute("SELECT COUNT(*) + 1 FROM members").fetchone()[0]).zfill(5)
    account_id = new_id('acct')
    try:
        with transaction(connection):
            connection.execute('INSERT INTO members(member_id,display_name) VALUES(?,?)', (member_id, payload.display_name.strip()))
            connection.execute("INSERT INTO accounts(account_id,member_id,account_type) VALUES(?,?,'member')", (account_id, member_id))
            connection.execute('INSERT INTO audit_events(audit_id,actor_type,action,entity_type,entity_id) VALUES(?,?,?,?,?)', (new_id('aud'), 'admin', 'member.create', 'member', member_id))
    except sqlite3.IntegrityError as exc:
        raise HTTPException(status_code=409, detail={'code': 'MEMBER_CREATE_CONFLICT'}) from exc
    return {'member_id': member_id, 'display_name': payload.display_name.strip(), 'account_id': account_id, 'balance_minor': 0, 'status': 'active'}

@app.get('/api/v2/members', dependencies=[Depends(require_admin)])
def list_members(connection: DB):
    rows = connection.execute('SELECT m.member_id,m.display_name,m.status,a.balance_minor FROM members m JOIN accounts a ON a.member_id=m.member_id ORDER BY m.created_at DESC').fetchall()
    return {'items': [dict(row) for row in rows]}

@app.post('/api/v2/finance/top-ups', dependencies=[Depends(require_admin)])
def top_up(payload: TopUpRequest, connection: DB):
    prior = connection.execute('SELECT transaction_id,status,member_id,amount_minor FROM transactions WHERE request_id=?', (payload.request_id,)).fetchone()
    if prior:
        if prior['member_id'] != payload.member_id or prior['amount_minor'] != payload.amount_minor or prior['status'] != 'succeeded':
            raise HTTPException(status_code=409, detail={'code': 'IDEMPOTENCY_CONFLICT'})
        return {'transaction_id': prior['transaction_id'], 'status': prior['status'], 'idempotent_replay': True}
    account = connection.execute("SELECT account_id,balance_minor,status FROM accounts WHERE member_id=? AND account_type='member'", (payload.member_id,)).fetchone()
    if not account:
        raise HTTPException(status_code=404, detail={'code': 'MEMBER_ACCOUNT_NOT_FOUND'})
    if account['status'] != 'active':
        raise HTTPException(status_code=409, detail={'code': 'ACCOUNT_NOT_ACTIVE'})
    transaction_id = new_id('txn')
    system_account = connection.execute("SELECT account_id FROM accounts WHERE account_type='system' LIMIT 1").fetchone()
    with transaction(connection):
        if not system_account:
            system_id = new_id('acct')
            connection.execute("INSERT INTO accounts(account_id,account_type,balance_minor) VALUES(?,'system',0)", (system_id,))
            system_account_id = system_id
        else:
            system_account_id = system_account['account_id']
        connection.execute("INSERT INTO transactions(transaction_id,request_id,member_id,transaction_type,amount_minor,status,metadata_json,completed_at) VALUES(?,?,?,'top_up',?,'succeeded',?,CURRENT_TIMESTAMP)", (transaction_id, payload.request_id, payload.member_id, payload.amount_minor, json.dumps({'description': payload.description})))
        connection.execute('UPDATE accounts SET balance_minor=balance_minor+?,updated_at=CURRENT_TIMESTAMP WHERE account_id=?', (payload.amount_minor, account['account_id']))
        connection.execute("INSERT INTO ledger_entries(entry_id,transaction_id,account_id,direction,amount_minor) VALUES(?,?,?,'credit',?)", (new_id('led'), transaction_id, account['account_id'], payload.amount_minor))
        connection.execute("INSERT INTO ledger_entries(entry_id,transaction_id,account_id,direction,amount_minor) VALUES(?,?,?,'debit',?)", (new_id('led'), transaction_id, system_account_id, payload.amount_minor))
        connection.execute('INSERT INTO audit_events(audit_id,actor_type,action,entity_type,entity_id,request_id,detail_json) VALUES(?,?,?,?,?,?,?)', (new_id('aud'), 'admin', 'finance.top_up', 'transaction', transaction_id, payload.request_id, json.dumps({'member_id': payload.member_id, 'amount_minor': payload.amount_minor})))
    return {'transaction_id': transaction_id, 'status': 'succeeded', 'idempotent_replay': False}

@app.get('/api/v2/vending/devices', dependencies=[Depends(require_admin)])
def vending_devices(connection: DB):
    rows = connection.execute("SELECT registry_id,hardware_id,display_name,status,mac_address,last_seen_at FROM device_registry WHERE device_type='vending' ORDER BY created_at DESC").fetchall()
    return {'items': [dict(row) for row in rows]}

@app.get('/api/v2/vending/devices/{registry_id}/products', dependencies=[Depends(require_admin)])
def get_products(registry_id: str, connection: DB):
    device = connection.execute("SELECT registry_id FROM device_registry WHERE registry_id=? AND device_type='vending'", (registry_id,)).fetchone()
    if not device:
        raise HTTPException(status_code=404, detail={'code': 'VENDING_DEVICE_NOT_FOUND'})
    rows = connection.execute('SELECT product_id,name,price_minor,stock,image_path,nfc_promo_percent,qris_promo_percent FROM product_slots WHERE registry_id=? ORDER BY product_id', (registry_id,)).fetchall()
    return {'registry_id': registry_id, 'items': [dict(row) for row in rows]}

@app.put('/api/v2/vending/devices/{registry_id}/products/{product_id}', dependencies=[Depends(require_admin)])
def update_product(registry_id: str, product_id: int, payload: ProductUpdate, connection: DB):
    if product_id not in range(1, 6):
        raise HTTPException(status_code=422, detail={'code': 'INVALID_PRODUCT_SLOT'})
    with transaction(connection):
        result = connection.execute('UPDATE product_slots SET name=?,price_minor=?,stock=?,updated_at=CURRENT_TIMESTAMP WHERE registry_id=? AND product_id=?', (payload.name.strip(), payload.price_minor, payload.stock, registry_id, product_id))
        if result.rowcount != 1:
            raise HTTPException(status_code=404, detail={'code': 'PRODUCT_SLOT_NOT_FOUND'})
        connection.execute('INSERT INTO audit_events(audit_id,actor_type,action,entity_type,entity_id,detail_json) VALUES(?,?,?,?,?,?)', (new_id('aud'), 'admin', 'vending.product.update', 'product_slot', f'{registry_id}:{product_id}', json.dumps(payload.model_dump())))
    return {'registry_id': registry_id, 'product_id': product_id, **payload.model_dump(), 'nfc_promo_percent': 0, 'qris_promo_percent': 0}

@app.get('/api/v2/admin/audit', dependencies=[Depends(require_admin)])
def list_audit(connection: DB, limit: int = 100):
    limit = max(1, min(limit, 500))
    rows = connection.execute('SELECT audit_id,actor_type,actor_id,action,entity_type,entity_id,request_id,detail_json,created_at FROM audit_events ORDER BY created_at DESC LIMIT ?', (limit,)).fetchall()
    return {'items': [dict(row) for row in rows]}
)

class CardEnroll(BaseModel):
    card_uid: str = Field(min_length=4, max_length=128)

class PurchaseRequest(BaseModel):
    request_id: str = Field(min_length=8, max_length=128)
    card_uid: str = Field(min_length=4, max_length=128)
    pin: str = Field(min_length=6, max_length=12, pattern=r'^\\d{6,12}

class TopUpRequest(BaseModel):
    request_id: str = Field(min_length=8, max_length=128)
    member_id: str = Field(min_length=1, max_length=128)
    amount_minor: int = Field(gt=0, le=100_000_000)
    description: str = Field(default='Top-up saldo', max_length=200)

class PurchaseRequest(BaseModel):
    request_id: str = Field(min_length=8, max_length=128)
    member_id: str = Field(min_length=1, max_length=128)
    product_id: int = Field(ge=1, le=5)
    payment_method: str = Field(pattern='^(nfc|qris)$')

class ProductUpdate(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    price_minor: int = Field(ge=0, le=100_000_000)
    stock: int = Field(ge=0, le=1_000_000)

@app.get('/api/v2/health')
def health():
    return {'status': 'ok', 'service': 'mgroup-api', 'version': '2.0.0'}

@app.get('/api/v2/ready')
def readiness(connection: DB):
    try:
        connection.execute('SELECT 1').fetchone()
    except sqlite3.Error as exc:
        raise HTTPException(status_code=503, detail={'code': 'DATABASE_NOT_READY'}) from exc
    return {'status': 'ready', 'database': 'ok'}

@app.post('/api/v2/admin/devices', status_code=201, dependencies=[Depends(require_admin)])
def register_device(payload: dict, connection: DB):
    hardware_id = str(payload.get('hardware_id', '')).strip()
    device_type = payload.get('device_type')
    display_name = str(payload.get('display_name', '')).strip()
    if not hardware_id or len(hardware_id) > 128 or device_type not in ('cashier', 'vending'):
        raise HTTPException(status_code=422, detail={'code': 'INVALID_DEVICE_REGISTRATION'})
    registry_id = new_id('reg')
    device_key = secrets_token = __import__('secrets').token_urlsafe(32)
    try:
        with transaction(connection):
            connection.execute('INSERT INTO device_registry(registry_id,hardware_id,device_type,display_name,status,device_key_hash,device_key_hint) VALUES(?,?,?,?,?,?,?)',
                (registry_id, hardware_id, device_type, display_name, 'active', hash_secret(device_key, settings.device_key_pepper), device_key[-4:]))
            connection.execute('INSERT INTO device_events(event_id,registry_id,hardware_id,event_type,detail_json) VALUES(?,?,?,?,?)',
                (new_id('evt'), registry_id, hardware_id, 'device.provisioned', json.dumps({'device_type': device_type})))
            if device_type == 'vending':
                for product_id in range(1, 6):
                    connection.execute('INSERT INTO product_slots(registry_id,product_id,name,price_minor,stock) VALUES(?,?,?,?,?)', (registry_id, product_id, f'Produk {product_id}', 0, 0))
            connection.execute('INSERT INTO audit_events(audit_id,actor_type,action,entity_type,entity_id,detail_json) VALUES(?,?,?,?,?,?)',
                (new_id('aud'), 'admin', 'device.provision', 'device', registry_id, json.dumps({'hardware_id': hardware_id, 'device_type': device_type})))
    except sqlite3.IntegrityError as exc:
        raise HTTPException(status_code=409, detail={'code': 'DEVICE_ALREADY_REGISTERED'}) from exc
    return {'registry_id': registry_id, 'hardware_id': hardware_id, 'device_type': device_type, 'device_key': secrets_token, 'warning': 'Simpan device_key sekarang; nilainya tidak dapat dibaca ulang.'}


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

@app.post('/api/v2/members', status_code=201, dependencies=[Depends(require_admin)])
def create_member(payload: MemberCreate, connection: DB):
    member_id = 'NTR-' + str(connection.execute("SELECT COUNT(*) + 1 FROM members").fetchone()[0]).zfill(5)
    account_id = new_id('acct')
    try:
        with transaction(connection):
            connection.execute('INSERT INTO members(member_id,display_name) VALUES(?,?)', (member_id, payload.display_name.strip()))
            connection.execute("INSERT INTO accounts(account_id,member_id,account_type) VALUES(?,?,'member')", (account_id, member_id))
            connection.execute('INSERT INTO audit_events(audit_id,actor_type,action,entity_type,entity_id) VALUES(?,?,?,?,?)', (new_id('aud'), 'admin', 'member.create', 'member', member_id))
    except sqlite3.IntegrityError as exc:
        raise HTTPException(status_code=409, detail={'code': 'MEMBER_CREATE_CONFLICT'}) from exc
    return {'member_id': member_id, 'display_name': payload.display_name.strip(), 'account_id': account_id, 'balance_minor': 0, 'status': 'active'}

@app.get('/api/v2/members', dependencies=[Depends(require_admin)])
def list_members(connection: DB):
    rows = connection.execute('SELECT m.member_id,m.display_name,m.status,a.balance_minor FROM members m JOIN accounts a ON a.member_id=m.member_id ORDER BY m.created_at DESC').fetchall()
    return {'items': [dict(row) for row in rows]}

@app.post('/api/v2/finance/top-ups', dependencies=[Depends(require_admin)])
def top_up(payload: TopUpRequest, connection: DB):
    prior = connection.execute('SELECT transaction_id,status,member_id,amount_minor FROM transactions WHERE request_id=?', (payload.request_id,)).fetchone()
    if prior:
        if prior['member_id'] != payload.member_id or prior['amount_minor'] != payload.amount_minor or prior['status'] != 'succeeded':
            raise HTTPException(status_code=409, detail={'code': 'IDEMPOTENCY_CONFLICT'})
        return {'transaction_id': prior['transaction_id'], 'status': prior['status'], 'idempotent_replay': True}
    account = connection.execute("SELECT account_id,balance_minor,status FROM accounts WHERE member_id=? AND account_type='member'", (payload.member_id,)).fetchone()
    if not account:
        raise HTTPException(status_code=404, detail={'code': 'MEMBER_ACCOUNT_NOT_FOUND'})
    if account['status'] != 'active':
        raise HTTPException(status_code=409, detail={'code': 'ACCOUNT_NOT_ACTIVE'})
    transaction_id = new_id('txn')
    system_account = connection.execute("SELECT account_id FROM accounts WHERE account_type='system' LIMIT 1").fetchone()
    with transaction(connection):
        if not system_account:
            system_id = new_id('acct')
            connection.execute("INSERT INTO accounts(account_id,account_type,balance_minor) VALUES(?,'system',0)", (system_id,))
            system_account_id = system_id
        else:
            system_account_id = system_account['account_id']
        connection.execute("INSERT INTO transactions(transaction_id,request_id,member_id,transaction_type,amount_minor,status,metadata_json,completed_at) VALUES(?,?,?,'top_up',?,'succeeded',?,CURRENT_TIMESTAMP)", (transaction_id, payload.request_id, payload.member_id, payload.amount_minor, json.dumps({'description': payload.description})))
        connection.execute('UPDATE accounts SET balance_minor=balance_minor+?,updated_at=CURRENT_TIMESTAMP WHERE account_id=?', (payload.amount_minor, account['account_id']))
        connection.execute("INSERT INTO ledger_entries(entry_id,transaction_id,account_id,direction,amount_minor) VALUES(?,?,?,'credit',?)", (new_id('led'), transaction_id, account['account_id'], payload.amount_minor))
        connection.execute("INSERT INTO ledger_entries(entry_id,transaction_id,account_id,direction,amount_minor) VALUES(?,?,?,'debit',?)", (new_id('led'), transaction_id, system_account_id, payload.amount_minor))
        connection.execute('INSERT INTO audit_events(audit_id,actor_type,action,entity_type,entity_id,request_id,detail_json) VALUES(?,?,?,?,?,?,?)', (new_id('aud'), 'admin', 'finance.top_up', 'transaction', transaction_id, payload.request_id, json.dumps({'member_id': payload.member_id, 'amount_minor': payload.amount_minor})))
    return {'transaction_id': transaction_id, 'status': 'succeeded', 'idempotent_replay': False}

@app.get('/api/v2/vending/devices', dependencies=[Depends(require_admin)])
def vending_devices(connection: DB):
    rows = connection.execute("SELECT registry_id,hardware_id,display_name,status,mac_address,last_seen_at FROM device_registry WHERE device_type='vending' ORDER BY created_at DESC").fetchall()
    return {'items': [dict(row) for row in rows]}

@app.get('/api/v2/vending/devices/{registry_id}/products', dependencies=[Depends(require_admin)])
def get_products(registry_id: str, connection: DB):
    device = connection.execute("SELECT registry_id FROM device_registry WHERE registry_id=? AND device_type='vending'", (registry_id,)).fetchone()
    if not device:
        raise HTTPException(status_code=404, detail={'code': 'VENDING_DEVICE_NOT_FOUND'})
    rows = connection.execute('SELECT product_id,name,price_minor,stock,image_path,nfc_promo_percent,qris_promo_percent FROM product_slots WHERE registry_id=? ORDER BY product_id', (registry_id,)).fetchall()
    return {'registry_id': registry_id, 'items': [dict(row) for row in rows]}

@app.put('/api/v2/vending/devices/{registry_id}/products/{product_id}', dependencies=[Depends(require_admin)])
def update_product(registry_id: str, product_id: int, payload: ProductUpdate, connection: DB):
    if product_id not in range(1, 6):
        raise HTTPException(status_code=422, detail={'code': 'INVALID_PRODUCT_SLOT'})
    with transaction(connection):
        result = connection.execute('UPDATE product_slots SET name=?,price_minor=?,stock=?,updated_at=CURRENT_TIMESTAMP WHERE registry_id=? AND product_id=?', (payload.name.strip(), payload.price_minor, payload.stock, registry_id, product_id))
        if result.rowcount != 1:
            raise HTTPException(status_code=404, detail={'code': 'PRODUCT_SLOT_NOT_FOUND'})
        connection.execute('INSERT INTO audit_events(audit_id,actor_type,action,entity_type,entity_id,detail_json) VALUES(?,?,?,?,?,?)', (new_id('aud'), 'admin', 'vending.product.update', 'product_slot', f'{registry_id}:{product_id}', json.dumps(payload.model_dump())))
    return {'registry_id': registry_id, 'product_id': product_id, **payload.model_dump(), 'nfc_promo_percent': 0, 'qris_promo_percent': 0}

@app.get('/api/v2/admin/audit', dependencies=[Depends(require_admin)])
def list_audit(connection: DB, limit: int = 100):
    limit = max(1, min(limit, 500))
    rows = connection.execute('SELECT audit_id,actor_type,actor_id,action,entity_type,entity_id,request_id,detail_json,created_at FROM audit_events ORDER BY created_at DESC LIMIT ?', (limit,)).fetchall()
    return {'items': [dict(row) for row in rows]}
)
    product_id: int = Field(ge=1, le=5)

class DispenseResult(BaseModel):
    succeeded: bool
    reason: str | None = Field(default=None, max_length=200)

class TopUpRequest(BaseModel):
    request_id: str = Field(min_length=8, max_length=128)
    member_id: str = Field(min_length=1, max_length=128)
    amount_minor: int = Field(gt=0, le=100_000_000)
    description: str = Field(default='Top-up saldo', max_length=200)

class PurchaseRequest(BaseModel):
    request_id: str = Field(min_length=8, max_length=128)
    member_id: str = Field(min_length=1, max_length=128)
    product_id: int = Field(ge=1, le=5)
    payment_method: str = Field(pattern='^(nfc|qris)$')

class ProductUpdate(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    price_minor: int = Field(ge=0, le=100_000_000)
    stock: int = Field(ge=0, le=1_000_000)

@app.get('/api/v2/health')
def health():
    return {'status': 'ok', 'service': 'mgroup-api', 'version': '2.0.0'}

@app.get('/api/v2/ready')
def readiness(connection: DB):
    try:
        connection.execute('SELECT 1').fetchone()
    except sqlite3.Error as exc:
        raise HTTPException(status_code=503, detail={'code': 'DATABASE_NOT_READY'}) from exc
    return {'status': 'ready', 'database': 'ok'}

@app.post('/api/v2/admin/devices', status_code=201, dependencies=[Depends(require_admin)])
def register_device(payload: dict, connection: DB):
    hardware_id = str(payload.get('hardware_id', '')).strip()
    device_type = payload.get('device_type')
    display_name = str(payload.get('display_name', '')).strip()
    if not hardware_id or len(hardware_id) > 128 or device_type not in ('cashier', 'vending'):
        raise HTTPException(status_code=422, detail={'code': 'INVALID_DEVICE_REGISTRATION'})
    registry_id = new_id('reg')
    device_key = secrets_token = __import__('secrets').token_urlsafe(32)
    try:
        with transaction(connection):
            connection.execute('INSERT INTO device_registry(registry_id,hardware_id,device_type,display_name,status,device_key_hash,device_key_hint) VALUES(?,?,?,?,?,?,?)',
                (registry_id, hardware_id, device_type, display_name, 'active', hash_secret(device_key, settings.device_key_pepper), device_key[-4:]))
            connection.execute('INSERT INTO device_events(event_id,registry_id,hardware_id,event_type,detail_json) VALUES(?,?,?,?,?)',
                (new_id('evt'), registry_id, hardware_id, 'device.provisioned', json.dumps({'device_type': device_type})))
            if device_type == 'vending':
                for product_id in range(1, 6):
                    connection.execute('INSERT INTO product_slots(registry_id,product_id,name,price_minor,stock) VALUES(?,?,?,?,?)', (registry_id, product_id, f'Produk {product_id}', 0, 0))
            connection.execute('INSERT INTO audit_events(audit_id,actor_type,action,entity_type,entity_id,detail_json) VALUES(?,?,?,?,?,?)',
                (new_id('aud'), 'admin', 'device.provision', 'device', registry_id, json.dumps({'hardware_id': hardware_id, 'device_type': device_type})))
    except sqlite3.IntegrityError as exc:
        raise HTTPException(status_code=409, detail={'code': 'DEVICE_ALREADY_REGISTERED'}) from exc
    return {'registry_id': registry_id, 'hardware_id': hardware_id, 'device_type': device_type, 'device_key': secrets_token, 'warning': 'Simpan device_key sekarang; nilainya tidak dapat dibaca ulang.'}


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

@app.post('/api/v2/members', status_code=201, dependencies=[Depends(require_admin)])
def create_member(payload: MemberCreate, connection: DB):
    member_id = 'NTR-' + str(connection.execute("SELECT COUNT(*) + 1 FROM members").fetchone()[0]).zfill(5)
    account_id = new_id('acct')
    try:
        with transaction(connection):
            connection.execute('INSERT INTO members(member_id,display_name) VALUES(?,?)', (member_id, payload.display_name.strip()))
            connection.execute("INSERT INTO accounts(account_id,member_id,account_type) VALUES(?,?,'member')", (account_id, member_id))
            connection.execute('INSERT INTO audit_events(audit_id,actor_type,action,entity_type,entity_id) VALUES(?,?,?,?,?)', (new_id('aud'), 'admin', 'member.create', 'member', member_id))
    except sqlite3.IntegrityError as exc:
        raise HTTPException(status_code=409, detail={'code': 'MEMBER_CREATE_CONFLICT'}) from exc
    return {'member_id': member_id, 'display_name': payload.display_name.strip(), 'account_id': account_id, 'balance_minor': 0, 'status': 'active'}

@app.get('/api/v2/members', dependencies=[Depends(require_admin)])
def list_members(connection: DB):
    rows = connection.execute('SELECT m.member_id,m.display_name,m.status,a.balance_minor FROM members m JOIN accounts a ON a.member_id=m.member_id ORDER BY m.created_at DESC').fetchall()
    return {'items': [dict(row) for row in rows]}

@app.post('/api/v2/finance/top-ups', dependencies=[Depends(require_admin)])
def top_up(payload: TopUpRequest, connection: DB):
    prior = connection.execute('SELECT transaction_id,status,member_id,amount_minor FROM transactions WHERE request_id=?', (payload.request_id,)).fetchone()
    if prior:
        if prior['member_id'] != payload.member_id or prior['amount_minor'] != payload.amount_minor or prior['status'] != 'succeeded':
            raise HTTPException(status_code=409, detail={'code': 'IDEMPOTENCY_CONFLICT'})
        return {'transaction_id': prior['transaction_id'], 'status': prior['status'], 'idempotent_replay': True}
    account = connection.execute("SELECT account_id,balance_minor,status FROM accounts WHERE member_id=? AND account_type='member'", (payload.member_id,)).fetchone()
    if not account:
        raise HTTPException(status_code=404, detail={'code': 'MEMBER_ACCOUNT_NOT_FOUND'})
    if account['status'] != 'active':
        raise HTTPException(status_code=409, detail={'code': 'ACCOUNT_NOT_ACTIVE'})
    transaction_id = new_id('txn')
    system_account = connection.execute("SELECT account_id FROM accounts WHERE account_type='system' LIMIT 1").fetchone()
    with transaction(connection):
        if not system_account:
            system_id = new_id('acct')
            connection.execute("INSERT INTO accounts(account_id,account_type,balance_minor) VALUES(?,'system',0)", (system_id,))
            system_account_id = system_id
        else:
            system_account_id = system_account['account_id']
        connection.execute("INSERT INTO transactions(transaction_id,request_id,member_id,transaction_type,amount_minor,status,metadata_json,completed_at) VALUES(?,?,?,'top_up',?,'succeeded',?,CURRENT_TIMESTAMP)", (transaction_id, payload.request_id, payload.member_id, payload.amount_minor, json.dumps({'description': payload.description})))
        connection.execute('UPDATE accounts SET balance_minor=balance_minor+?,updated_at=CURRENT_TIMESTAMP WHERE account_id=?', (payload.amount_minor, account['account_id']))
        connection.execute("INSERT INTO ledger_entries(entry_id,transaction_id,account_id,direction,amount_minor) VALUES(?,?,?,'credit',?)", (new_id('led'), transaction_id, account['account_id'], payload.amount_minor))
        connection.execute("INSERT INTO ledger_entries(entry_id,transaction_id,account_id,direction,amount_minor) VALUES(?,?,?,'debit',?)", (new_id('led'), transaction_id, system_account_id, payload.amount_minor))
        connection.execute('INSERT INTO audit_events(audit_id,actor_type,action,entity_type,entity_id,request_id,detail_json) VALUES(?,?,?,?,?,?,?)', (new_id('aud'), 'admin', 'finance.top_up', 'transaction', transaction_id, payload.request_id, json.dumps({'member_id': payload.member_id, 'amount_minor': payload.amount_minor})))
    return {'transaction_id': transaction_id, 'status': 'succeeded', 'idempotent_replay': False}

@app.get('/api/v2/vending/devices', dependencies=[Depends(require_admin)])
def vending_devices(connection: DB):
    rows = connection.execute("SELECT registry_id,hardware_id,display_name,status,mac_address,last_seen_at FROM device_registry WHERE device_type='vending' ORDER BY created_at DESC").fetchall()
    return {'items': [dict(row) for row in rows]}

@app.get('/api/v2/vending/devices/{registry_id}/products', dependencies=[Depends(require_admin)])
def get_products(registry_id: str, connection: DB):
    device = connection.execute("SELECT registry_id FROM device_registry WHERE registry_id=? AND device_type='vending'", (registry_id,)).fetchone()
    if not device:
        raise HTTPException(status_code=404, detail={'code': 'VENDING_DEVICE_NOT_FOUND'})
    rows = connection.execute('SELECT product_id,name,price_minor,stock,image_path,nfc_promo_percent,qris_promo_percent FROM product_slots WHERE registry_id=? ORDER BY product_id', (registry_id,)).fetchall()
    return {'registry_id': registry_id, 'items': [dict(row) for row in rows]}

@app.put('/api/v2/vending/devices/{registry_id}/products/{product_id}', dependencies=[Depends(require_admin)])
def update_product(registry_id: str, product_id: int, payload: ProductUpdate, connection: DB):
    if product_id not in range(1, 6):
        raise HTTPException(status_code=422, detail={'code': 'INVALID_PRODUCT_SLOT'})
    with transaction(connection):
        result = connection.execute('UPDATE product_slots SET name=?,price_minor=?,stock=?,updated_at=CURRENT_TIMESTAMP WHERE registry_id=? AND product_id=?', (payload.name.strip(), payload.price_minor, payload.stock, registry_id, product_id))
        if result.rowcount != 1:
            raise HTTPException(status_code=404, detail={'code': 'PRODUCT_SLOT_NOT_FOUND'})
        connection.execute('INSERT INTO audit_events(audit_id,actor_type,action,entity_type,entity_id,detail_json) VALUES(?,?,?,?,?,?)', (new_id('aud'), 'admin', 'vending.product.update', 'product_slot', f'{registry_id}:{product_id}', json.dumps(payload.model_dump())))
    return {'registry_id': registry_id, 'product_id': product_id, **payload.model_dump(), 'nfc_promo_percent': 0, 'qris_promo_percent': 0}

@app.get('/api/v2/admin/audit', dependencies=[Depends(require_admin)])
def list_audit(connection: DB, limit: int = 100):
    limit = max(1, min(limit, 500))
    rows = connection.execute('SELECT audit_id,actor_type,actor_id,action,entity_type,entity_id,request_id,detail_json,created_at FROM audit_events ORDER BY created_at DESC LIMIT ?', (limit,)).fetchall()
    return {'items': [dict(row) for row in rows]}
 + digest


def verify_pin(pin: str, encoded: str | None) -> bool:
    if not encoded:
        return False
    try:
        algorithm, rounds, salt, expected = encoded.split('

@app.get('/api/v2/ready')
def readiness(connection: DB):
    try:
        connection.execute('SELECT 1').fetchone()
    except sqlite3.Error as exc:
        raise HTTPException(status_code=503, detail={'code': 'DATABASE_NOT_READY'}) from exc
    return {'status': 'ready', 'database': 'ok'}

@app.post('/api/v2/admin/devices', status_code=201, dependencies=[Depends(require_admin)])
def register_device(payload: dict, connection: DB):
    hardware_id = str(payload.get('hardware_id', '')).strip()
    device_type = payload.get('device_type')
    display_name = str(payload.get('display_name', '')).strip()
    if not hardware_id or len(hardware_id) > 128 or device_type not in ('cashier', 'vending'):
        raise HTTPException(status_code=422, detail={'code': 'INVALID_DEVICE_REGISTRATION'})
    registry_id = new_id('reg')
    device_key = secrets_token = __import__('secrets').token_urlsafe(32)
    try:
        with transaction(connection):
            connection.execute('INSERT INTO device_registry(registry_id,hardware_id,device_type,display_name,status,device_key_hash,device_key_hint) VALUES(?,?,?,?,?,?,?)',
                (registry_id, hardware_id, device_type, display_name, 'active', hash_secret(device_key, settings.device_key_pepper), device_key[-4:]))
            connection.execute('INSERT INTO device_events(event_id,registry_id,hardware_id,event_type,detail_json) VALUES(?,?,?,?,?)',
                (new_id('evt'), registry_id, hardware_id, 'device.provisioned', json.dumps({'device_type': device_type})))
            if device_type == 'vending':
                for product_id in range(1, 6):
                    connection.execute('INSERT INTO product_slots(registry_id,product_id,name,price_minor,stock) VALUES(?,?,?,?,?)', (registry_id, product_id, f'Produk {product_id}', 0, 0))
            connection.execute('INSERT INTO audit_events(audit_id,actor_type,action,entity_type,entity_id,detail_json) VALUES(?,?,?,?,?,?)',
                (new_id('aud'), 'admin', 'device.provision', 'device', registry_id, json.dumps({'hardware_id': hardware_id, 'device_type': device_type})))
    except sqlite3.IntegrityError as exc:
        raise HTTPException(status_code=409, detail={'code': 'DEVICE_ALREADY_REGISTERED'}) from exc
    return {'registry_id': registry_id, 'hardware_id': hardware_id, 'device_type': device_type, 'device_key': secrets_token, 'warning': 'Simpan device_key sekarang; nilainya tidak dapat dibaca ulang.'}


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

@app.post('/api/v2/members', status_code=201, dependencies=[Depends(require_admin)])
def create_member(payload: MemberCreate, connection: DB):
    member_id = 'NTR-' + str(connection.execute("SELECT COUNT(*) + 1 FROM members").fetchone()[0]).zfill(5)
    account_id = new_id('acct')
    try:
        with transaction(connection):
            connection.execute('INSERT INTO members(member_id,display_name) VALUES(?,?)', (member_id, payload.display_name.strip()))
            connection.execute("INSERT INTO accounts(account_id,member_id,account_type) VALUES(?,?,'member')", (account_id, member_id))
            connection.execute('INSERT INTO audit_events(audit_id,actor_type,action,entity_type,entity_id) VALUES(?,?,?,?,?)', (new_id('aud'), 'admin', 'member.create', 'member', member_id))
    except sqlite3.IntegrityError as exc:
        raise HTTPException(status_code=409, detail={'code': 'MEMBER_CREATE_CONFLICT'}) from exc
    return {'member_id': member_id, 'display_name': payload.display_name.strip(), 'account_id': account_id, 'balance_minor': 0, 'status': 'active'}

@app.get('/api/v2/members', dependencies=[Depends(require_admin)])
def list_members(connection: DB):
    rows = connection.execute('SELECT m.member_id,m.display_name,m.status,a.balance_minor FROM members m JOIN accounts a ON a.member_id=m.member_id ORDER BY m.created_at DESC').fetchall()
    return {'items': [dict(row) for row in rows]}

@app.post('/api/v2/finance/top-ups', dependencies=[Depends(require_admin)])
def top_up(payload: TopUpRequest, connection: DB):
    prior = connection.execute('SELECT transaction_id,status,member_id,amount_minor FROM transactions WHERE request_id=?', (payload.request_id,)).fetchone()
    if prior:
        if prior['member_id'] != payload.member_id or prior['amount_minor'] != payload.amount_minor or prior['status'] != 'succeeded':
            raise HTTPException(status_code=409, detail={'code': 'IDEMPOTENCY_CONFLICT'})
        return {'transaction_id': prior['transaction_id'], 'status': prior['status'], 'idempotent_replay': True}
    account = connection.execute("SELECT account_id,balance_minor,status FROM accounts WHERE member_id=? AND account_type='member'", (payload.member_id,)).fetchone()
    if not account:
        raise HTTPException(status_code=404, detail={'code': 'MEMBER_ACCOUNT_NOT_FOUND'})
    if account['status'] != 'active':
        raise HTTPException(status_code=409, detail={'code': 'ACCOUNT_NOT_ACTIVE'})
    transaction_id = new_id('txn')
    system_account = connection.execute("SELECT account_id FROM accounts WHERE account_type='system' LIMIT 1").fetchone()
    with transaction(connection):
        if not system_account:
            system_id = new_id('acct')
            connection.execute("INSERT INTO accounts(account_id,account_type,balance_minor) VALUES(?,'system',0)", (system_id,))
            system_account_id = system_id
        else:
            system_account_id = system_account['account_id']
        connection.execute("INSERT INTO transactions(transaction_id,request_id,member_id,transaction_type,amount_minor,status,metadata_json,completed_at) VALUES(?,?,?,'top_up',?,'succeeded',?,CURRENT_TIMESTAMP)", (transaction_id, payload.request_id, payload.member_id, payload.amount_minor, json.dumps({'description': payload.description})))
        connection.execute('UPDATE accounts SET balance_minor=balance_minor+?,updated_at=CURRENT_TIMESTAMP WHERE account_id=?', (payload.amount_minor, account['account_id']))
        connection.execute("INSERT INTO ledger_entries(entry_id,transaction_id,account_id,direction,amount_minor) VALUES(?,?,?,'credit',?)", (new_id('led'), transaction_id, account['account_id'], payload.amount_minor))
        connection.execute("INSERT INTO ledger_entries(entry_id,transaction_id,account_id,direction,amount_minor) VALUES(?,?,?,'debit',?)", (new_id('led'), transaction_id, system_account_id, payload.amount_minor))
        connection.execute('INSERT INTO audit_events(audit_id,actor_type,action,entity_type,entity_id,request_id,detail_json) VALUES(?,?,?,?,?,?,?)', (new_id('aud'), 'admin', 'finance.top_up', 'transaction', transaction_id, payload.request_id, json.dumps({'member_id': payload.member_id, 'amount_minor': payload.amount_minor})))
    return {'transaction_id': transaction_id, 'status': 'succeeded', 'idempotent_replay': False}

@app.get('/api/v2/vending/devices', dependencies=[Depends(require_admin)])
def vending_devices(connection: DB):
    rows = connection.execute("SELECT registry_id,hardware_id,display_name,status,mac_address,last_seen_at FROM device_registry WHERE device_type='vending' ORDER BY created_at DESC").fetchall()
    return {'items': [dict(row) for row in rows]}

@app.get('/api/v2/vending/devices/{registry_id}/products', dependencies=[Depends(require_admin)])
def get_products(registry_id: str, connection: DB):
    device = connection.execute("SELECT registry_id FROM device_registry WHERE registry_id=? AND device_type='vending'", (registry_id,)).fetchone()
    if not device:
        raise HTTPException(status_code=404, detail={'code': 'VENDING_DEVICE_NOT_FOUND'})
    rows = connection.execute('SELECT product_id,name,price_minor,stock,image_path,nfc_promo_percent,qris_promo_percent FROM product_slots WHERE registry_id=? ORDER BY product_id', (registry_id,)).fetchall()
    return {'registry_id': registry_id, 'items': [dict(row) for row in rows]}

@app.put('/api/v2/vending/devices/{registry_id}/products/{product_id}', dependencies=[Depends(require_admin)])
def update_product(registry_id: str, product_id: int, payload: ProductUpdate, connection: DB):
    if product_id not in range(1, 6):
        raise HTTPException(status_code=422, detail={'code': 'INVALID_PRODUCT_SLOT'})
    with transaction(connection):
        result = connection.execute('UPDATE product_slots SET name=?,price_minor=?,stock=?,updated_at=CURRENT_TIMESTAMP WHERE registry_id=? AND product_id=?', (payload.name.strip(), payload.price_minor, payload.stock, registry_id, product_id))
        if result.rowcount != 1:
            raise HTTPException(status_code=404, detail={'code': 'PRODUCT_SLOT_NOT_FOUND'})
        connection.execute('INSERT INTO audit_events(audit_id,actor_type,action,entity_type,entity_id,detail_json) VALUES(?,?,?,?,?,?)', (new_id('aud'), 'admin', 'vending.product.update', 'product_slot', f'{registry_id}:{product_id}', json.dumps(payload.model_dump())))
    return {'registry_id': registry_id, 'product_id': product_id, **payload.model_dump(), 'nfc_promo_percent': 0, 'qris_promo_percent': 0}

@app.get('/api/v2/admin/audit', dependencies=[Depends(require_admin)])
def list_audit(connection: DB, limit: int = 100):
    limit = max(1, min(limit, 500))
    rows = connection.execute('SELECT audit_id,actor_type,actor_id,action,entity_type,entity_id,request_id,detail_json,created_at FROM audit_events ORDER BY created_at DESC LIMIT ?', (limit,)).fetchall()
    return {'items': [dict(row) for row in rows]}
)

class CardEnroll(BaseModel):
    card_uid: str = Field(min_length=4, max_length=128)

class PurchaseRequest(BaseModel):
    request_id: str = Field(min_length=8, max_length=128)
    card_uid: str = Field(min_length=4, max_length=128)
    pin: str = Field(min_length=6, max_length=12, pattern=r'^\\d{6,12}

class TopUpRequest(BaseModel):
    request_id: str = Field(min_length=8, max_length=128)
    member_id: str = Field(min_length=1, max_length=128)
    amount_minor: int = Field(gt=0, le=100_000_000)
    description: str = Field(default='Top-up saldo', max_length=200)

class PurchaseRequest(BaseModel):
    request_id: str = Field(min_length=8, max_length=128)
    member_id: str = Field(min_length=1, max_length=128)
    product_id: int = Field(ge=1, le=5)
    payment_method: str = Field(pattern='^(nfc|qris)$')

class ProductUpdate(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    price_minor: int = Field(ge=0, le=100_000_000)
    stock: int = Field(ge=0, le=1_000_000)

@app.get('/api/v2/health')
def health():
    return {'status': 'ok', 'service': 'mgroup-api', 'version': '2.0.0'}

@app.get('/api/v2/ready')
def readiness(connection: DB):
    try:
        connection.execute('SELECT 1').fetchone()
    except sqlite3.Error as exc:
        raise HTTPException(status_code=503, detail={'code': 'DATABASE_NOT_READY'}) from exc
    return {'status': 'ready', 'database': 'ok'}

@app.post('/api/v2/admin/devices', status_code=201, dependencies=[Depends(require_admin)])
def register_device(payload: dict, connection: DB):
    hardware_id = str(payload.get('hardware_id', '')).strip()
    device_type = payload.get('device_type')
    display_name = str(payload.get('display_name', '')).strip()
    if not hardware_id or len(hardware_id) > 128 or device_type not in ('cashier', 'vending'):
        raise HTTPException(status_code=422, detail={'code': 'INVALID_DEVICE_REGISTRATION'})
    registry_id = new_id('reg')
    device_key = secrets_token = __import__('secrets').token_urlsafe(32)
    try:
        with transaction(connection):
            connection.execute('INSERT INTO device_registry(registry_id,hardware_id,device_type,display_name,status,device_key_hash,device_key_hint) VALUES(?,?,?,?,?,?,?)',
                (registry_id, hardware_id, device_type, display_name, 'active', hash_secret(device_key, settings.device_key_pepper), device_key[-4:]))
            connection.execute('INSERT INTO device_events(event_id,registry_id,hardware_id,event_type,detail_json) VALUES(?,?,?,?,?)',
                (new_id('evt'), registry_id, hardware_id, 'device.provisioned', json.dumps({'device_type': device_type})))
            if device_type == 'vending':
                for product_id in range(1, 6):
                    connection.execute('INSERT INTO product_slots(registry_id,product_id,name,price_minor,stock) VALUES(?,?,?,?,?)', (registry_id, product_id, f'Produk {product_id}', 0, 0))
            connection.execute('INSERT INTO audit_events(audit_id,actor_type,action,entity_type,entity_id,detail_json) VALUES(?,?,?,?,?,?)',
                (new_id('aud'), 'admin', 'device.provision', 'device', registry_id, json.dumps({'hardware_id': hardware_id, 'device_type': device_type})))
    except sqlite3.IntegrityError as exc:
        raise HTTPException(status_code=409, detail={'code': 'DEVICE_ALREADY_REGISTERED'}) from exc
    return {'registry_id': registry_id, 'hardware_id': hardware_id, 'device_type': device_type, 'device_key': secrets_token, 'warning': 'Simpan device_key sekarang; nilainya tidak dapat dibaca ulang.'}


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

@app.post('/api/v2/members', status_code=201, dependencies=[Depends(require_admin)])
def create_member(payload: MemberCreate, connection: DB):
    member_id = 'NTR-' + str(connection.execute("SELECT COUNT(*) + 1 FROM members").fetchone()[0]).zfill(5)
    account_id = new_id('acct')
    try:
        with transaction(connection):
            connection.execute('INSERT INTO members(member_id,display_name) VALUES(?,?)', (member_id, payload.display_name.strip()))
            connection.execute("INSERT INTO accounts(account_id,member_id,account_type) VALUES(?,?,'member')", (account_id, member_id))
            connection.execute('INSERT INTO audit_events(audit_id,actor_type,action,entity_type,entity_id) VALUES(?,?,?,?,?)', (new_id('aud'), 'admin', 'member.create', 'member', member_id))
    except sqlite3.IntegrityError as exc:
        raise HTTPException(status_code=409, detail={'code': 'MEMBER_CREATE_CONFLICT'}) from exc
    return {'member_id': member_id, 'display_name': payload.display_name.strip(), 'account_id': account_id, 'balance_minor': 0, 'status': 'active'}

@app.get('/api/v2/members', dependencies=[Depends(require_admin)])
def list_members(connection: DB):
    rows = connection.execute('SELECT m.member_id,m.display_name,m.status,a.balance_minor FROM members m JOIN accounts a ON a.member_id=m.member_id ORDER BY m.created_at DESC').fetchall()
    return {'items': [dict(row) for row in rows]}

@app.post('/api/v2/finance/top-ups', dependencies=[Depends(require_admin)])
def top_up(payload: TopUpRequest, connection: DB):
    prior = connection.execute('SELECT transaction_id,status,member_id,amount_minor FROM transactions WHERE request_id=?', (payload.request_id,)).fetchone()
    if prior:
        if prior['member_id'] != payload.member_id or prior['amount_minor'] != payload.amount_minor or prior['status'] != 'succeeded':
            raise HTTPException(status_code=409, detail={'code': 'IDEMPOTENCY_CONFLICT'})
        return {'transaction_id': prior['transaction_id'], 'status': prior['status'], 'idempotent_replay': True}
    account = connection.execute("SELECT account_id,balance_minor,status FROM accounts WHERE member_id=? AND account_type='member'", (payload.member_id,)).fetchone()
    if not account:
        raise HTTPException(status_code=404, detail={'code': 'MEMBER_ACCOUNT_NOT_FOUND'})
    if account['status'] != 'active':
        raise HTTPException(status_code=409, detail={'code': 'ACCOUNT_NOT_ACTIVE'})
    transaction_id = new_id('txn')
    system_account = connection.execute("SELECT account_id FROM accounts WHERE account_type='system' LIMIT 1").fetchone()
    with transaction(connection):
        if not system_account:
            system_id = new_id('acct')
            connection.execute("INSERT INTO accounts(account_id,account_type,balance_minor) VALUES(?,'system',0)", (system_id,))
            system_account_id = system_id
        else:
            system_account_id = system_account['account_id']
        connection.execute("INSERT INTO transactions(transaction_id,request_id,member_id,transaction_type,amount_minor,status,metadata_json,completed_at) VALUES(?,?,?,'top_up',?,'succeeded',?,CURRENT_TIMESTAMP)", (transaction_id, payload.request_id, payload.member_id, payload.amount_minor, json.dumps({'description': payload.description})))
        connection.execute('UPDATE accounts SET balance_minor=balance_minor+?,updated_at=CURRENT_TIMESTAMP WHERE account_id=?', (payload.amount_minor, account['account_id']))
        connection.execute("INSERT INTO ledger_entries(entry_id,transaction_id,account_id,direction,amount_minor) VALUES(?,?,?,'credit',?)", (new_id('led'), transaction_id, account['account_id'], payload.amount_minor))
        connection.execute("INSERT INTO ledger_entries(entry_id,transaction_id,account_id,direction,amount_minor) VALUES(?,?,?,'debit',?)", (new_id('led'), transaction_id, system_account_id, payload.amount_minor))
        connection.execute('INSERT INTO audit_events(audit_id,actor_type,action,entity_type,entity_id,request_id,detail_json) VALUES(?,?,?,?,?,?,?)', (new_id('aud'), 'admin', 'finance.top_up', 'transaction', transaction_id, payload.request_id, json.dumps({'member_id': payload.member_id, 'amount_minor': payload.amount_minor})))
    return {'transaction_id': transaction_id, 'status': 'succeeded', 'idempotent_replay': False}

@app.get('/api/v2/vending/devices', dependencies=[Depends(require_admin)])
def vending_devices(connection: DB):
    rows = connection.execute("SELECT registry_id,hardware_id,display_name,status,mac_address,last_seen_at FROM device_registry WHERE device_type='vending' ORDER BY created_at DESC").fetchall()
    return {'items': [dict(row) for row in rows]}

@app.get('/api/v2/vending/devices/{registry_id}/products', dependencies=[Depends(require_admin)])
def get_products(registry_id: str, connection: DB):
    device = connection.execute("SELECT registry_id FROM device_registry WHERE registry_id=? AND device_type='vending'", (registry_id,)).fetchone()
    if not device:
        raise HTTPException(status_code=404, detail={'code': 'VENDING_DEVICE_NOT_FOUND'})
    rows = connection.execute('SELECT product_id,name,price_minor,stock,image_path,nfc_promo_percent,qris_promo_percent FROM product_slots WHERE registry_id=? ORDER BY product_id', (registry_id,)).fetchall()
    return {'registry_id': registry_id, 'items': [dict(row) for row in rows]}

@app.put('/api/v2/vending/devices/{registry_id}/products/{product_id}', dependencies=[Depends(require_admin)])
def update_product(registry_id: str, product_id: int, payload: ProductUpdate, connection: DB):
    if product_id not in range(1, 6):
        raise HTTPException(status_code=422, detail={'code': 'INVALID_PRODUCT_SLOT'})
    with transaction(connection):
        result = connection.execute('UPDATE product_slots SET name=?,price_minor=?,stock=?,updated_at=CURRENT_TIMESTAMP WHERE registry_id=? AND product_id=?', (payload.name.strip(), payload.price_minor, payload.stock, registry_id, product_id))
        if result.rowcount != 1:
            raise HTTPException(status_code=404, detail={'code': 'PRODUCT_SLOT_NOT_FOUND'})
        connection.execute('INSERT INTO audit_events(audit_id,actor_type,action,entity_type,entity_id,detail_json) VALUES(?,?,?,?,?,?)', (new_id('aud'), 'admin', 'vending.product.update', 'product_slot', f'{registry_id}:{product_id}', json.dumps(payload.model_dump())))
    return {'registry_id': registry_id, 'product_id': product_id, **payload.model_dump(), 'nfc_promo_percent': 0, 'qris_promo_percent': 0}

@app.get('/api/v2/admin/audit', dependencies=[Depends(require_admin)])
def list_audit(connection: DB, limit: int = 100):
    limit = max(1, min(limit, 500))
    rows = connection.execute('SELECT audit_id,actor_type,actor_id,action,entity_type,entity_id,request_id,detail_json,created_at FROM audit_events ORDER BY created_at DESC LIMIT ?', (limit,)).fetchall()
    return {'items': [dict(row) for row in rows]}
)
    product_id: int = Field(ge=1, le=5)

class DispenseResult(BaseModel):
    succeeded: bool
    reason: str | None = Field(default=None, max_length=200)

class TopUpRequest(BaseModel):
    request_id: str = Field(min_length=8, max_length=128)
    member_id: str = Field(min_length=1, max_length=128)
    amount_minor: int = Field(gt=0, le=100_000_000)
    description: str = Field(default='Top-up saldo', max_length=200)

class PurchaseRequest(BaseModel):
    request_id: str = Field(min_length=8, max_length=128)
    member_id: str = Field(min_length=1, max_length=128)
    product_id: int = Field(ge=1, le=5)
    payment_method: str = Field(pattern='^(nfc|qris)$')

class ProductUpdate(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    price_minor: int = Field(ge=0, le=100_000_000)
    stock: int = Field(ge=0, le=1_000_000)

@app.get('/api/v2/health')
def health():
    return {'status': 'ok', 'service': 'mgroup-api', 'version': '2.0.0'}

@app.get('/api/v2/ready')
def readiness(connection: DB):
    try:
        connection.execute('SELECT 1').fetchone()
    except sqlite3.Error as exc:
        raise HTTPException(status_code=503, detail={'code': 'DATABASE_NOT_READY'}) from exc
    return {'status': 'ready', 'database': 'ok'}

@app.post('/api/v2/admin/devices', status_code=201, dependencies=[Depends(require_admin)])
def register_device(payload: dict, connection: DB):
    hardware_id = str(payload.get('hardware_id', '')).strip()
    device_type = payload.get('device_type')
    display_name = str(payload.get('display_name', '')).strip()
    if not hardware_id or len(hardware_id) > 128 or device_type not in ('cashier', 'vending'):
        raise HTTPException(status_code=422, detail={'code': 'INVALID_DEVICE_REGISTRATION'})
    registry_id = new_id('reg')
    device_key = secrets_token = __import__('secrets').token_urlsafe(32)
    try:
        with transaction(connection):
            connection.execute('INSERT INTO device_registry(registry_id,hardware_id,device_type,display_name,status,device_key_hash,device_key_hint) VALUES(?,?,?,?,?,?,?)',
                (registry_id, hardware_id, device_type, display_name, 'active', hash_secret(device_key, settings.device_key_pepper), device_key[-4:]))
            connection.execute('INSERT INTO device_events(event_id,registry_id,hardware_id,event_type,detail_json) VALUES(?,?,?,?,?)',
                (new_id('evt'), registry_id, hardware_id, 'device.provisioned', json.dumps({'device_type': device_type})))
            if device_type == 'vending':
                for product_id in range(1, 6):
                    connection.execute('INSERT INTO product_slots(registry_id,product_id,name,price_minor,stock) VALUES(?,?,?,?,?)', (registry_id, product_id, f'Produk {product_id}', 0, 0))
            connection.execute('INSERT INTO audit_events(audit_id,actor_type,action,entity_type,entity_id,detail_json) VALUES(?,?,?,?,?,?)',
                (new_id('aud'), 'admin', 'device.provision', 'device', registry_id, json.dumps({'hardware_id': hardware_id, 'device_type': device_type})))
    except sqlite3.IntegrityError as exc:
        raise HTTPException(status_code=409, detail={'code': 'DEVICE_ALREADY_REGISTERED'}) from exc
    return {'registry_id': registry_id, 'hardware_id': hardware_id, 'device_type': device_type, 'device_key': secrets_token, 'warning': 'Simpan device_key sekarang; nilainya tidak dapat dibaca ulang.'}


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

@app.post('/api/v2/members', status_code=201, dependencies=[Depends(require_admin)])
def create_member(payload: MemberCreate, connection: DB):
    member_id = 'NTR-' + str(connection.execute("SELECT COUNT(*) + 1 FROM members").fetchone()[0]).zfill(5)
    account_id = new_id('acct')
    try:
        with transaction(connection):
            connection.execute('INSERT INTO members(member_id,display_name) VALUES(?,?)', (member_id, payload.display_name.strip()))
            connection.execute("INSERT INTO accounts(account_id,member_id,account_type) VALUES(?,?,'member')", (account_id, member_id))
            connection.execute('INSERT INTO audit_events(audit_id,actor_type,action,entity_type,entity_id) VALUES(?,?,?,?,?)', (new_id('aud'), 'admin', 'member.create', 'member', member_id))
    except sqlite3.IntegrityError as exc:
        raise HTTPException(status_code=409, detail={'code': 'MEMBER_CREATE_CONFLICT'}) from exc
    return {'member_id': member_id, 'display_name': payload.display_name.strip(), 'account_id': account_id, 'balance_minor': 0, 'status': 'active'}

@app.get('/api/v2/members', dependencies=[Depends(require_admin)])
def list_members(connection: DB):
    rows = connection.execute('SELECT m.member_id,m.display_name,m.status,a.balance_minor FROM members m JOIN accounts a ON a.member_id=m.member_id ORDER BY m.created_at DESC').fetchall()
    return {'items': [dict(row) for row in rows]}

@app.post('/api/v2/finance/top-ups', dependencies=[Depends(require_admin)])
def top_up(payload: TopUpRequest, connection: DB):
    prior = connection.execute('SELECT transaction_id,status,member_id,amount_minor FROM transactions WHERE request_id=?', (payload.request_id,)).fetchone()
    if prior:
        if prior['member_id'] != payload.member_id or prior['amount_minor'] != payload.amount_minor or prior['status'] != 'succeeded':
            raise HTTPException(status_code=409, detail={'code': 'IDEMPOTENCY_CONFLICT'})
        return {'transaction_id': prior['transaction_id'], 'status': prior['status'], 'idempotent_replay': True}
    account = connection.execute("SELECT account_id,balance_minor,status FROM accounts WHERE member_id=? AND account_type='member'", (payload.member_id,)).fetchone()
    if not account:
        raise HTTPException(status_code=404, detail={'code': 'MEMBER_ACCOUNT_NOT_FOUND'})
    if account['status'] != 'active':
        raise HTTPException(status_code=409, detail={'code': 'ACCOUNT_NOT_ACTIVE'})
    transaction_id = new_id('txn')
    system_account = connection.execute("SELECT account_id FROM accounts WHERE account_type='system' LIMIT 1").fetchone()
    with transaction(connection):
        if not system_account:
            system_id = new_id('acct')
            connection.execute("INSERT INTO accounts(account_id,account_type,balance_minor) VALUES(?,'system',0)", (system_id,))
            system_account_id = system_id
        else:
            system_account_id = system_account['account_id']
        connection.execute("INSERT INTO transactions(transaction_id,request_id,member_id,transaction_type,amount_minor,status,metadata_json,completed_at) VALUES(?,?,?,'top_up',?,'succeeded',?,CURRENT_TIMESTAMP)", (transaction_id, payload.request_id, payload.member_id, payload.amount_minor, json.dumps({'description': payload.description})))
        connection.execute('UPDATE accounts SET balance_minor=balance_minor+?,updated_at=CURRENT_TIMESTAMP WHERE account_id=?', (payload.amount_minor, account['account_id']))
        connection.execute("INSERT INTO ledger_entries(entry_id,transaction_id,account_id,direction,amount_minor) VALUES(?,?,?,'credit',?)", (new_id('led'), transaction_id, account['account_id'], payload.amount_minor))
        connection.execute("INSERT INTO ledger_entries(entry_id,transaction_id,account_id,direction,amount_minor) VALUES(?,?,?,'debit',?)", (new_id('led'), transaction_id, system_account_id, payload.amount_minor))
        connection.execute('INSERT INTO audit_events(audit_id,actor_type,action,entity_type,entity_id,request_id,detail_json) VALUES(?,?,?,?,?,?,?)', (new_id('aud'), 'admin', 'finance.top_up', 'transaction', transaction_id, payload.request_id, json.dumps({'member_id': payload.member_id, 'amount_minor': payload.amount_minor})))
    return {'transaction_id': transaction_id, 'status': 'succeeded', 'idempotent_replay': False}

@app.get('/api/v2/vending/devices', dependencies=[Depends(require_admin)])
def vending_devices(connection: DB):
    rows = connection.execute("SELECT registry_id,hardware_id,display_name,status,mac_address,last_seen_at FROM device_registry WHERE device_type='vending' ORDER BY created_at DESC").fetchall()
    return {'items': [dict(row) for row in rows]}

@app.get('/api/v2/vending/devices/{registry_id}/products', dependencies=[Depends(require_admin)])
def get_products(registry_id: str, connection: DB):
    device = connection.execute("SELECT registry_id FROM device_registry WHERE registry_id=? AND device_type='vending'", (registry_id,)).fetchone()
    if not device:
        raise HTTPException(status_code=404, detail={'code': 'VENDING_DEVICE_NOT_FOUND'})
    rows = connection.execute('SELECT product_id,name,price_minor,stock,image_path,nfc_promo_percent,qris_promo_percent FROM product_slots WHERE registry_id=? ORDER BY product_id', (registry_id,)).fetchall()
    return {'registry_id': registry_id, 'items': [dict(row) for row in rows]}

@app.put('/api/v2/vending/devices/{registry_id}/products/{product_id}', dependencies=[Depends(require_admin)])
def update_product(registry_id: str, product_id: int, payload: ProductUpdate, connection: DB):
    if product_id not in range(1, 6):
        raise HTTPException(status_code=422, detail={'code': 'INVALID_PRODUCT_SLOT'})
    with transaction(connection):
        result = connection.execute('UPDATE product_slots SET name=?,price_minor=?,stock=?,updated_at=CURRENT_TIMESTAMP WHERE registry_id=? AND product_id=?', (payload.name.strip(), payload.price_minor, payload.stock, registry_id, product_id))
        if result.rowcount != 1:
            raise HTTPException(status_code=404, detail={'code': 'PRODUCT_SLOT_NOT_FOUND'})
        connection.execute('INSERT INTO audit_events(audit_id,actor_type,action,entity_type,entity_id,detail_json) VALUES(?,?,?,?,?,?)', (new_id('aud'), 'admin', 'vending.product.update', 'product_slot', f'{registry_id}:{product_id}', json.dumps(payload.model_dump())))
    return {'registry_id': registry_id, 'product_id': product_id, **payload.model_dump(), 'nfc_promo_percent': 0, 'qris_promo_percent': 0}

@app.get('/api/v2/admin/audit', dependencies=[Depends(require_admin)])
def list_audit(connection: DB, limit: int = 100):
    limit = max(1, min(limit, 500))
    rows = connection.execute('SELECT audit_id,actor_type,actor_id,action,entity_type,entity_id,request_id,detail_json,created_at FROM audit_events ORDER BY created_at DESC LIMIT ?', (limit,)).fetchall()
    return {'items': [dict(row) for row in rows]}
, 3)
        if algorithm != 'pbkdf2_sha256' or int(rounds) != 310_000:
            return False
        actual = hashlib.pbkdf2_hmac('sha256', pin.encode('utf-8'), salt.encode('ascii'), int(rounds)).hex()
        return hmac.compare_digest(actual, expected)
    except (ValueError, TypeError):
        return False


def card_hash(card_uid: str) -> str:
    return hash_secret(card_uid.strip().upper(), settings.device_key_pepper)


def ensure_system_account(connection: sqlite3.Connection) -> str:
    row = connection.execute(\"SELECT account_id FROM accounts WHERE account_type='system' LIMIT 1\").fetchone()
    if row:
        return row['account_id']
    account_id = new_id('acct')
    connection.execute(\"INSERT INTO accounts(account_id,account_type,balance_minor) VALUES(?,'system',0)\", (account_id,))
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
def register_device(payload: dict, connection: DB):
    hardware_id = str(payload.get('hardware_id', '')).strip()
    device_type = payload.get('device_type')
    display_name = str(payload.get('display_name', '')).strip()
    if not hardware_id or len(hardware_id) > 128 or device_type not in ('cashier', 'vending'):
        raise HTTPException(status_code=422, detail={'code': 'INVALID_DEVICE_REGISTRATION'})
    registry_id = new_id('reg')
    device_key = secrets_token = __import__('secrets').token_urlsafe(32)
    try:
        with transaction(connection):
            connection.execute('INSERT INTO device_registry(registry_id,hardware_id,device_type,display_name,status,device_key_hash,device_key_hint) VALUES(?,?,?,?,?,?,?)',
                (registry_id, hardware_id, device_type, display_name, 'active', hash_secret(device_key, settings.device_key_pepper), device_key[-4:]))
            connection.execute('INSERT INTO device_events(event_id,registry_id,hardware_id,event_type,detail_json) VALUES(?,?,?,?,?)',
                (new_id('evt'), registry_id, hardware_id, 'device.provisioned', json.dumps({'device_type': device_type})))
            if device_type == 'vending':
                for product_id in range(1, 6):
                    connection.execute('INSERT INTO product_slots(registry_id,product_id,name,price_minor,stock) VALUES(?,?,?,?,?)', (registry_id, product_id, f'Produk {product_id}', 0, 0))
            connection.execute('INSERT INTO audit_events(audit_id,actor_type,action,entity_type,entity_id,detail_json) VALUES(?,?,?,?,?,?)',
                (new_id('aud'), 'admin', 'device.provision', 'device', registry_id, json.dumps({'hardware_id': hardware_id, 'device_type': device_type})))
    except sqlite3.IntegrityError as exc:
        raise HTTPException(status_code=409, detail={'code': 'DEVICE_ALREADY_REGISTERED'}) from exc
    return {'registry_id': registry_id, 'hardware_id': hardware_id, 'device_type': device_type, 'device_key': secrets_token, 'warning': 'Simpan device_key sekarang; nilainya tidak dapat dibaca ulang.'}


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

@app.post('/api/v2/members', status_code=201, dependencies=[Depends(require_admin)])
def create_member(payload: MemberCreate, connection: DB):
    member_id = 'NTR-' + str(connection.execute("SELECT COUNT(*) + 1 FROM members").fetchone()[0]).zfill(5)
    account_id = new_id('acct')
    try:
        with transaction(connection):
            connection.execute('INSERT INTO members(member_id,display_name) VALUES(?,?)', (member_id, payload.display_name.strip()))
            connection.execute("INSERT INTO accounts(account_id,member_id,account_type) VALUES(?,?,'member')", (account_id, member_id))
            connection.execute('INSERT INTO audit_events(audit_id,actor_type,action,entity_type,entity_id) VALUES(?,?,?,?,?)', (new_id('aud'), 'admin', 'member.create', 'member', member_id))
    except sqlite3.IntegrityError as exc:
        raise HTTPException(status_code=409, detail={'code': 'MEMBER_CREATE_CONFLICT'}) from exc
    return {'member_id': member_id, 'display_name': payload.display_name.strip(), 'account_id': account_id, 'balance_minor': 0, 'status': 'active'}

@app.get('/api/v2/members', dependencies=[Depends(require_admin)])
def list_members(connection: DB):
    rows = connection.execute('SELECT m.member_id,m.display_name,m.status,a.balance_minor FROM members m JOIN accounts a ON a.member_id=m.member_id ORDER BY m.created_at DESC').fetchall()
    return {'items': [dict(row) for row in rows]}

@app.post('/api/v2/finance/top-ups', dependencies=[Depends(require_admin)])
def top_up(payload: TopUpRequest, connection: DB):
    prior = connection.execute('SELECT transaction_id,status,member_id,amount_minor FROM transactions WHERE request_id=?', (payload.request_id,)).fetchone()
    if prior:
        if prior['member_id'] != payload.member_id or prior['amount_minor'] != payload.amount_minor or prior['status'] != 'succeeded':
            raise HTTPException(status_code=409, detail={'code': 'IDEMPOTENCY_CONFLICT'})
        return {'transaction_id': prior['transaction_id'], 'status': prior['status'], 'idempotent_replay': True}
    account = connection.execute("SELECT account_id,balance_minor,status FROM accounts WHERE member_id=? AND account_type='member'", (payload.member_id,)).fetchone()
    if not account:
        raise HTTPException(status_code=404, detail={'code': 'MEMBER_ACCOUNT_NOT_FOUND'})
    if account['status'] != 'active':
        raise HTTPException(status_code=409, detail={'code': 'ACCOUNT_NOT_ACTIVE'})
    transaction_id = new_id('txn')
    system_account = connection.execute("SELECT account_id FROM accounts WHERE account_type='system' LIMIT 1").fetchone()
    with transaction(connection):
        if not system_account:
            system_id = new_id('acct')
            connection.execute("INSERT INTO accounts(account_id,account_type,balance_minor) VALUES(?,'system',0)", (system_id,))
            system_account_id = system_id
        else:
            system_account_id = system_account['account_id']
        connection.execute("INSERT INTO transactions(transaction_id,request_id,member_id,transaction_type,amount_minor,status,metadata_json,completed_at) VALUES(?,?,?,'top_up',?,'succeeded',?,CURRENT_TIMESTAMP)", (transaction_id, payload.request_id, payload.member_id, payload.amount_minor, json.dumps({'description': payload.description})))
        connection.execute('UPDATE accounts SET balance_minor=balance_minor+?,updated_at=CURRENT_TIMESTAMP WHERE account_id=?', (payload.amount_minor, account['account_id']))
        connection.execute("INSERT INTO ledger_entries(entry_id,transaction_id,account_id,direction,amount_minor) VALUES(?,?,?,'credit',?)", (new_id('led'), transaction_id, account['account_id'], payload.amount_minor))
        connection.execute("INSERT INTO ledger_entries(entry_id,transaction_id,account_id,direction,amount_minor) VALUES(?,?,?,'debit',?)", (new_id('led'), transaction_id, system_account_id, payload.amount_minor))
        connection.execute('INSERT INTO audit_events(audit_id,actor_type,action,entity_type,entity_id,request_id,detail_json) VALUES(?,?,?,?,?,?,?)', (new_id('aud'), 'admin', 'finance.top_up', 'transaction', transaction_id, payload.request_id, json.dumps({'member_id': payload.member_id, 'amount_minor': payload.amount_minor})))
    return {'transaction_id': transaction_id, 'status': 'succeeded', 'idempotent_replay': False}

@app.get('/api/v2/vending/devices', dependencies=[Depends(require_admin)])
def vending_devices(connection: DB):
    rows = connection.execute("SELECT registry_id,hardware_id,display_name,status,mac_address,last_seen_at FROM device_registry WHERE device_type='vending' ORDER BY created_at DESC").fetchall()
    return {'items': [dict(row) for row in rows]}

@app.get('/api/v2/vending/devices/{registry_id}/products', dependencies=[Depends(require_admin)])
def get_products(registry_id: str, connection: DB):
    device = connection.execute("SELECT registry_id FROM device_registry WHERE registry_id=? AND device_type='vending'", (registry_id,)).fetchone()
    if not device:
        raise HTTPException(status_code=404, detail={'code': 'VENDING_DEVICE_NOT_FOUND'})
    rows = connection.execute('SELECT product_id,name,price_minor,stock,image_path,nfc_promo_percent,qris_promo_percent FROM product_slots WHERE registry_id=? ORDER BY product_id', (registry_id,)).fetchall()
    return {'registry_id': registry_id, 'items': [dict(row) for row in rows]}

@app.put('/api/v2/vending/devices/{registry_id}/products/{product_id}', dependencies=[Depends(require_admin)])
def update_product(registry_id: str, product_id: int, payload: ProductUpdate, connection: DB):
    if product_id not in range(1, 6):
        raise HTTPException(status_code=422, detail={'code': 'INVALID_PRODUCT_SLOT'})
    with transaction(connection):
        result = connection.execute('UPDATE product_slots SET name=?,price_minor=?,stock=?,updated_at=CURRENT_TIMESTAMP WHERE registry_id=? AND product_id=?', (payload.name.strip(), payload.price_minor, payload.stock, registry_id, product_id))
        if result.rowcount != 1:
            raise HTTPException(status_code=404, detail={'code': 'PRODUCT_SLOT_NOT_FOUND'})
        connection.execute('INSERT INTO audit_events(audit_id,actor_type,action,entity_type,entity_id,detail_json) VALUES(?,?,?,?,?,?)', (new_id('aud'), 'admin', 'vending.product.update', 'product_slot', f'{registry_id}:{product_id}', json.dumps(payload.model_dump())))
    return {'registry_id': registry_id, 'product_id': product_id, **payload.model_dump(), 'nfc_promo_percent': 0, 'qris_promo_percent': 0}

@app.get('/api/v2/admin/audit', dependencies=[Depends(require_admin)])
def list_audit(connection: DB, limit: int = 100):
    limit = max(1, min(limit, 500))
    rows = connection.execute('SELECT audit_id,actor_type,actor_id,action,entity_type,entity_id,request_id,detail_json,created_at FROM audit_events ORDER BY created_at DESC LIMIT ?', (limit,)).fetchall()
    return {'items': [dict(row) for row in rows]}
)

class CardEnroll(BaseModel):
    card_uid: str = Field(min_length=4, max_length=128)

class PurchaseRequest(BaseModel):
    request_id: str = Field(min_length=8, max_length=128)
    card_uid: str = Field(min_length=4, max_length=128)
    pin: str = Field(min_length=6, max_length=12, pattern=r'^\\d{6,12}

class TopUpRequest(BaseModel):
    request_id: str = Field(min_length=8, max_length=128)
    member_id: str = Field(min_length=1, max_length=128)
    amount_minor: int = Field(gt=0, le=100_000_000)
    description: str = Field(default='Top-up saldo', max_length=200)

class PurchaseRequest(BaseModel):
    request_id: str = Field(min_length=8, max_length=128)
    member_id: str = Field(min_length=1, max_length=128)
    product_id: int = Field(ge=1, le=5)
    payment_method: str = Field(pattern='^(nfc|qris)$')

class ProductUpdate(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    price_minor: int = Field(ge=0, le=100_000_000)
    stock: int = Field(ge=0, le=1_000_000)

@app.get('/api/v2/health')
def health():
    return {'status': 'ok', 'service': 'mgroup-api', 'version': '2.0.0'}

@app.get('/api/v2/ready')
def readiness(connection: DB):
    try:
        connection.execute('SELECT 1').fetchone()
    except sqlite3.Error as exc:
        raise HTTPException(status_code=503, detail={'code': 'DATABASE_NOT_READY'}) from exc
    return {'status': 'ready', 'database': 'ok'}

@app.post('/api/v2/admin/devices', status_code=201, dependencies=[Depends(require_admin)])
def register_device(payload: dict, connection: DB):
    hardware_id = str(payload.get('hardware_id', '')).strip()
    device_type = payload.get('device_type')
    display_name = str(payload.get('display_name', '')).strip()
    if not hardware_id or len(hardware_id) > 128 or device_type not in ('cashier', 'vending'):
        raise HTTPException(status_code=422, detail={'code': 'INVALID_DEVICE_REGISTRATION'})
    registry_id = new_id('reg')
    device_key = secrets_token = __import__('secrets').token_urlsafe(32)
    try:
        with transaction(connection):
            connection.execute('INSERT INTO device_registry(registry_id,hardware_id,device_type,display_name,status,device_key_hash,device_key_hint) VALUES(?,?,?,?,?,?,?)',
                (registry_id, hardware_id, device_type, display_name, 'active', hash_secret(device_key, settings.device_key_pepper), device_key[-4:]))
            connection.execute('INSERT INTO device_events(event_id,registry_id,hardware_id,event_type,detail_json) VALUES(?,?,?,?,?)',
                (new_id('evt'), registry_id, hardware_id, 'device.provisioned', json.dumps({'device_type': device_type})))
            if device_type == 'vending':
                for product_id in range(1, 6):
                    connection.execute('INSERT INTO product_slots(registry_id,product_id,name,price_minor,stock) VALUES(?,?,?,?,?)', (registry_id, product_id, f'Produk {product_id}', 0, 0))
            connection.execute('INSERT INTO audit_events(audit_id,actor_type,action,entity_type,entity_id,detail_json) VALUES(?,?,?,?,?,?)',
                (new_id('aud'), 'admin', 'device.provision', 'device', registry_id, json.dumps({'hardware_id': hardware_id, 'device_type': device_type})))
    except sqlite3.IntegrityError as exc:
        raise HTTPException(status_code=409, detail={'code': 'DEVICE_ALREADY_REGISTERED'}) from exc
    return {'registry_id': registry_id, 'hardware_id': hardware_id, 'device_type': device_type, 'device_key': secrets_token, 'warning': 'Simpan device_key sekarang; nilainya tidak dapat dibaca ulang.'}


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

@app.post('/api/v2/members', status_code=201, dependencies=[Depends(require_admin)])
def create_member(payload: MemberCreate, connection: DB):
    member_id = 'NTR-' + str(connection.execute("SELECT COUNT(*) + 1 FROM members").fetchone()[0]).zfill(5)
    account_id = new_id('acct')
    try:
        with transaction(connection):
            connection.execute('INSERT INTO members(member_id,display_name) VALUES(?,?)', (member_id, payload.display_name.strip()))
            connection.execute("INSERT INTO accounts(account_id,member_id,account_type) VALUES(?,?,'member')", (account_id, member_id))
            connection.execute('INSERT INTO audit_events(audit_id,actor_type,action,entity_type,entity_id) VALUES(?,?,?,?,?)', (new_id('aud'), 'admin', 'member.create', 'member', member_id))
    except sqlite3.IntegrityError as exc:
        raise HTTPException(status_code=409, detail={'code': 'MEMBER_CREATE_CONFLICT'}) from exc
    return {'member_id': member_id, 'display_name': payload.display_name.strip(), 'account_id': account_id, 'balance_minor': 0, 'status': 'active'}

@app.get('/api/v2/members', dependencies=[Depends(require_admin)])
def list_members(connection: DB):
    rows = connection.execute('SELECT m.member_id,m.display_name,m.status,a.balance_minor FROM members m JOIN accounts a ON a.member_id=m.member_id ORDER BY m.created_at DESC').fetchall()
    return {'items': [dict(row) for row in rows]}

@app.post('/api/v2/finance/top-ups', dependencies=[Depends(require_admin)])
def top_up(payload: TopUpRequest, connection: DB):
    prior = connection.execute('SELECT transaction_id,status,member_id,amount_minor FROM transactions WHERE request_id=?', (payload.request_id,)).fetchone()
    if prior:
        if prior['member_id'] != payload.member_id or prior['amount_minor'] != payload.amount_minor or prior['status'] != 'succeeded':
            raise HTTPException(status_code=409, detail={'code': 'IDEMPOTENCY_CONFLICT'})
        return {'transaction_id': prior['transaction_id'], 'status': prior['status'], 'idempotent_replay': True}
    account = connection.execute("SELECT account_id,balance_minor,status FROM accounts WHERE member_id=? AND account_type='member'", (payload.member_id,)).fetchone()
    if not account:
        raise HTTPException(status_code=404, detail={'code': 'MEMBER_ACCOUNT_NOT_FOUND'})
    if account['status'] != 'active':
        raise HTTPException(status_code=409, detail={'code': 'ACCOUNT_NOT_ACTIVE'})
    transaction_id = new_id('txn')
    system_account = connection.execute("SELECT account_id FROM accounts WHERE account_type='system' LIMIT 1").fetchone()
    with transaction(connection):
        if not system_account:
            system_id = new_id('acct')
            connection.execute("INSERT INTO accounts(account_id,account_type,balance_minor) VALUES(?,'system',0)", (system_id,))
            system_account_id = system_id
        else:
            system_account_id = system_account['account_id']
        connection.execute("INSERT INTO transactions(transaction_id,request_id,member_id,transaction_type,amount_minor,status,metadata_json,completed_at) VALUES(?,?,?,'top_up',?,'succeeded',?,CURRENT_TIMESTAMP)", (transaction_id, payload.request_id, payload.member_id, payload.amount_minor, json.dumps({'description': payload.description})))
        connection.execute('UPDATE accounts SET balance_minor=balance_minor+?,updated_at=CURRENT_TIMESTAMP WHERE account_id=?', (payload.amount_minor, account['account_id']))
        connection.execute("INSERT INTO ledger_entries(entry_id,transaction_id,account_id,direction,amount_minor) VALUES(?,?,?,'credit',?)", (new_id('led'), transaction_id, account['account_id'], payload.amount_minor))
        connection.execute("INSERT INTO ledger_entries(entry_id,transaction_id,account_id,direction,amount_minor) VALUES(?,?,?,'debit',?)", (new_id('led'), transaction_id, system_account_id, payload.amount_minor))
        connection.execute('INSERT INTO audit_events(audit_id,actor_type,action,entity_type,entity_id,request_id,detail_json) VALUES(?,?,?,?,?,?,?)', (new_id('aud'), 'admin', 'finance.top_up', 'transaction', transaction_id, payload.request_id, json.dumps({'member_id': payload.member_id, 'amount_minor': payload.amount_minor})))
    return {'transaction_id': transaction_id, 'status': 'succeeded', 'idempotent_replay': False}

@app.get('/api/v2/vending/devices', dependencies=[Depends(require_admin)])
def vending_devices(connection: DB):
    rows = connection.execute("SELECT registry_id,hardware_id,display_name,status,mac_address,last_seen_at FROM device_registry WHERE device_type='vending' ORDER BY created_at DESC").fetchall()
    return {'items': [dict(row) for row in rows]}

@app.get('/api/v2/vending/devices/{registry_id}/products', dependencies=[Depends(require_admin)])
def get_products(registry_id: str, connection: DB):
    device = connection.execute("SELECT registry_id FROM device_registry WHERE registry_id=? AND device_type='vending'", (registry_id,)).fetchone()
    if not device:
        raise HTTPException(status_code=404, detail={'code': 'VENDING_DEVICE_NOT_FOUND'})
    rows = connection.execute('SELECT product_id,name,price_minor,stock,image_path,nfc_promo_percent,qris_promo_percent FROM product_slots WHERE registry_id=? ORDER BY product_id', (registry_id,)).fetchall()
    return {'registry_id': registry_id, 'items': [dict(row) for row in rows]}

@app.put('/api/v2/vending/devices/{registry_id}/products/{product_id}', dependencies=[Depends(require_admin)])
def update_product(registry_id: str, product_id: int, payload: ProductUpdate, connection: DB):
    if product_id not in range(1, 6):
        raise HTTPException(status_code=422, detail={'code': 'INVALID_PRODUCT_SLOT'})
    with transaction(connection):
        result = connection.execute('UPDATE product_slots SET name=?,price_minor=?,stock=?,updated_at=CURRENT_TIMESTAMP WHERE registry_id=? AND product_id=?', (payload.name.strip(), payload.price_minor, payload.stock, registry_id, product_id))
        if result.rowcount != 1:
            raise HTTPException(status_code=404, detail={'code': 'PRODUCT_SLOT_NOT_FOUND'})
        connection.execute('INSERT INTO audit_events(audit_id,actor_type,action,entity_type,entity_id,detail_json) VALUES(?,?,?,?,?,?)', (new_id('aud'), 'admin', 'vending.product.update', 'product_slot', f'{registry_id}:{product_id}', json.dumps(payload.model_dump())))
    return {'registry_id': registry_id, 'product_id': product_id, **payload.model_dump(), 'nfc_promo_percent': 0, 'qris_promo_percent': 0}

@app.get('/api/v2/admin/audit', dependencies=[Depends(require_admin)])
def list_audit(connection: DB, limit: int = 100):
    limit = max(1, min(limit, 500))
    rows = connection.execute('SELECT audit_id,actor_type,actor_id,action,entity_type,entity_id,request_id,detail_json,created_at FROM audit_events ORDER BY created_at DESC LIMIT ?', (limit,)).fetchall()
    return {'items': [dict(row) for row in rows]}
)
    product_id: int = Field(ge=1, le=5)

class DispenseResult(BaseModel):
    succeeded: bool
    reason: str | None = Field(default=None, max_length=200)

class TopUpRequest(BaseModel):
    request_id: str = Field(min_length=8, max_length=128)
    member_id: str = Field(min_length=1, max_length=128)
    amount_minor: int = Field(gt=0, le=100_000_000)
    description: str = Field(default='Top-up saldo', max_length=200)

class PurchaseRequest(BaseModel):
    request_id: str = Field(min_length=8, max_length=128)
    member_id: str = Field(min_length=1, max_length=128)
    product_id: int = Field(ge=1, le=5)
    payment_method: str = Field(pattern='^(nfc|qris)$')

class ProductUpdate(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    price_minor: int = Field(ge=0, le=100_000_000)
    stock: int = Field(ge=0, le=1_000_000)

@app.get('/api/v2/health')
def health():
    return {'status': 'ok', 'service': 'mgroup-api', 'version': '2.0.0'}

@app.get('/api/v2/ready')
def readiness(connection: DB):
    try:
        connection.execute('SELECT 1').fetchone()
    except sqlite3.Error as exc:
        raise HTTPException(status_code=503, detail={'code': 'DATABASE_NOT_READY'}) from exc
    return {'status': 'ready', 'database': 'ok'}

@app.post('/api/v2/admin/devices', status_code=201, dependencies=[Depends(require_admin)])
def register_device(payload: dict, connection: DB):
    hardware_id = str(payload.get('hardware_id', '')).strip()
    device_type = payload.get('device_type')
    display_name = str(payload.get('display_name', '')).strip()
    if not hardware_id or len(hardware_id) > 128 or device_type not in ('cashier', 'vending'):
        raise HTTPException(status_code=422, detail={'code': 'INVALID_DEVICE_REGISTRATION'})
    registry_id = new_id('reg')
    device_key = secrets_token = __import__('secrets').token_urlsafe(32)
    try:
        with transaction(connection):
            connection.execute('INSERT INTO device_registry(registry_id,hardware_id,device_type,display_name,status,device_key_hash,device_key_hint) VALUES(?,?,?,?,?,?,?)',
                (registry_id, hardware_id, device_type, display_name, 'active', hash_secret(device_key, settings.device_key_pepper), device_key[-4:]))
            connection.execute('INSERT INTO device_events(event_id,registry_id,hardware_id,event_type,detail_json) VALUES(?,?,?,?,?)',
                (new_id('evt'), registry_id, hardware_id, 'device.provisioned', json.dumps({'device_type': device_type})))
            if device_type == 'vending':
                for product_id in range(1, 6):
                    connection.execute('INSERT INTO product_slots(registry_id,product_id,name,price_minor,stock) VALUES(?,?,?,?,?)', (registry_id, product_id, f'Produk {product_id}', 0, 0))
            connection.execute('INSERT INTO audit_events(audit_id,actor_type,action,entity_type,entity_id,detail_json) VALUES(?,?,?,?,?,?)',
                (new_id('aud'), 'admin', 'device.provision', 'device', registry_id, json.dumps({'hardware_id': hardware_id, 'device_type': device_type})))
    except sqlite3.IntegrityError as exc:
        raise HTTPException(status_code=409, detail={'code': 'DEVICE_ALREADY_REGISTERED'}) from exc
    return {'registry_id': registry_id, 'hardware_id': hardware_id, 'device_type': device_type, 'device_key': secrets_token, 'warning': 'Simpan device_key sekarang; nilainya tidak dapat dibaca ulang.'}


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

@app.post('/api/v2/members', status_code=201, dependencies=[Depends(require_admin)])
def create_member(payload: MemberCreate, connection: DB):
    member_id = 'NTR-' + str(connection.execute("SELECT COUNT(*) + 1 FROM members").fetchone()[0]).zfill(5)
    account_id = new_id('acct')
    try:
        with transaction(connection):
            connection.execute('INSERT INTO members(member_id,display_name) VALUES(?,?)', (member_id, payload.display_name.strip()))
            connection.execute("INSERT INTO accounts(account_id,member_id,account_type) VALUES(?,?,'member')", (account_id, member_id))
            connection.execute('INSERT INTO audit_events(audit_id,actor_type,action,entity_type,entity_id) VALUES(?,?,?,?,?)', (new_id('aud'), 'admin', 'member.create', 'member', member_id))
    except sqlite3.IntegrityError as exc:
        raise HTTPException(status_code=409, detail={'code': 'MEMBER_CREATE_CONFLICT'}) from exc
    return {'member_id': member_id, 'display_name': payload.display_name.strip(), 'account_id': account_id, 'balance_minor': 0, 'status': 'active'}

@app.get('/api/v2/members', dependencies=[Depends(require_admin)])
def list_members(connection: DB):
    rows = connection.execute('SELECT m.member_id,m.display_name,m.status,a.balance_minor FROM members m JOIN accounts a ON a.member_id=m.member_id ORDER BY m.created_at DESC').fetchall()
    return {'items': [dict(row) for row in rows]}

@app.post('/api/v2/finance/top-ups', dependencies=[Depends(require_admin)])
def top_up(payload: TopUpRequest, connection: DB):
    prior = connection.execute('SELECT transaction_id,status,member_id,amount_minor FROM transactions WHERE request_id=?', (payload.request_id,)).fetchone()
    if prior:
        if prior['member_id'] != payload.member_id or prior['amount_minor'] != payload.amount_minor or prior['status'] != 'succeeded':
            raise HTTPException(status_code=409, detail={'code': 'IDEMPOTENCY_CONFLICT'})
        return {'transaction_id': prior['transaction_id'], 'status': prior['status'], 'idempotent_replay': True}
    account = connection.execute("SELECT account_id,balance_minor,status FROM accounts WHERE member_id=? AND account_type='member'", (payload.member_id,)).fetchone()
    if not account:
        raise HTTPException(status_code=404, detail={'code': 'MEMBER_ACCOUNT_NOT_FOUND'})
    if account['status'] != 'active':
        raise HTTPException(status_code=409, detail={'code': 'ACCOUNT_NOT_ACTIVE'})
    transaction_id = new_id('txn')
    system_account = connection.execute("SELECT account_id FROM accounts WHERE account_type='system' LIMIT 1").fetchone()
    with transaction(connection):
        if not system_account:
            system_id = new_id('acct')
            connection.execute("INSERT INTO accounts(account_id,account_type,balance_minor) VALUES(?,'system',0)", (system_id,))
            system_account_id = system_id
        else:
            system_account_id = system_account['account_id']
        connection.execute("INSERT INTO transactions(transaction_id,request_id,member_id,transaction_type,amount_minor,status,metadata_json,completed_at) VALUES(?,?,?,'top_up',?,'succeeded',?,CURRENT_TIMESTAMP)", (transaction_id, payload.request_id, payload.member_id, payload.amount_minor, json.dumps({'description': payload.description})))
        connection.execute('UPDATE accounts SET balance_minor=balance_minor+?,updated_at=CURRENT_TIMESTAMP WHERE account_id=?', (payload.amount_minor, account['account_id']))
        connection.execute("INSERT INTO ledger_entries(entry_id,transaction_id,account_id,direction,amount_minor) VALUES(?,?,?,'credit',?)", (new_id('led'), transaction_id, account['account_id'], payload.amount_minor))
        connection.execute("INSERT INTO ledger_entries(entry_id,transaction_id,account_id,direction,amount_minor) VALUES(?,?,?,'debit',?)", (new_id('led'), transaction_id, system_account_id, payload.amount_minor))
        connection.execute('INSERT INTO audit_events(audit_id,actor_type,action,entity_type,entity_id,request_id,detail_json) VALUES(?,?,?,?,?,?,?)', (new_id('aud'), 'admin', 'finance.top_up', 'transaction', transaction_id, payload.request_id, json.dumps({'member_id': payload.member_id, 'amount_minor': payload.amount_minor})))
    return {'transaction_id': transaction_id, 'status': 'succeeded', 'idempotent_replay': False}

@app.get('/api/v2/vending/devices', dependencies=[Depends(require_admin)])
def vending_devices(connection: DB):
    rows = connection.execute("SELECT registry_id,hardware_id,display_name,status,mac_address,last_seen_at FROM device_registry WHERE device_type='vending' ORDER BY created_at DESC").fetchall()
    return {'items': [dict(row) for row in rows]}

@app.get('/api/v2/vending/devices/{registry_id}/products', dependencies=[Depends(require_admin)])
def get_products(registry_id: str, connection: DB):
    device = connection.execute("SELECT registry_id FROM device_registry WHERE registry_id=? AND device_type='vending'", (registry_id,)).fetchone()
    if not device:
        raise HTTPException(status_code=404, detail={'code': 'VENDING_DEVICE_NOT_FOUND'})
    rows = connection.execute('SELECT product_id,name,price_minor,stock,image_path,nfc_promo_percent,qris_promo_percent FROM product_slots WHERE registry_id=? ORDER BY product_id', (registry_id,)).fetchall()
    return {'registry_id': registry_id, 'items': [dict(row) for row in rows]}

@app.put('/api/v2/vending/devices/{registry_id}/products/{product_id}', dependencies=[Depends(require_admin)])
def update_product(registry_id: str, product_id: int, payload: ProductUpdate, connection: DB):
    if product_id not in range(1, 6):
        raise HTTPException(status_code=422, detail={'code': 'INVALID_PRODUCT_SLOT'})
    with transaction(connection):
        result = connection.execute('UPDATE product_slots SET name=?,price_minor=?,stock=?,updated_at=CURRENT_TIMESTAMP WHERE registry_id=? AND product_id=?', (payload.name.strip(), payload.price_minor, payload.stock, registry_id, product_id))
        if result.rowcount != 1:
            raise HTTPException(status_code=404, detail={'code': 'PRODUCT_SLOT_NOT_FOUND'})
        connection.execute('INSERT INTO audit_events(audit_id,actor_type,action,entity_type,entity_id,detail_json) VALUES(?,?,?,?,?,?)', (new_id('aud'), 'admin', 'vending.product.update', 'product_slot', f'{registry_id}:{product_id}', json.dumps(payload.model_dump())))
    return {'registry_id': registry_id, 'product_id': product_id, **payload.model_dump(), 'nfc_promo_percent': 0, 'qris_promo_percent': 0}

@app.get('/api/v2/admin/audit', dependencies=[Depends(require_admin)])
def list_audit(connection: DB, limit: int = 100):
    limit = max(1, min(limit, 500))
    rows = connection.execute('SELECT audit_id,actor_type,actor_id,action,entity_type,entity_id,request_id,detail_json,created_at FROM audit_events ORDER BY created_at DESC LIMIT ?', (limit,)).fetchall()
    return {'items': [dict(row) for row in rows]}
