import hashlib
import hmac
import secrets
from fastapi import Header, HTTPException
from .config import settings


def hash_secret(secret: str, pepper: str = '') -> str:
    return hashlib.sha256((pepper + secret).encode('utf-8')).hexdigest()


def verify_secret(secret: str, expected_hash: str, pepper: str = '') -> bool:
    return hmac.compare_digest(hash_secret(secret, pepper), expected_hash)


def require_admin(authorization: str | None = Header(default=None)) -> None:
    token = settings.admin_token
    if not token:
        raise HTTPException(status_code=503, detail={'code': 'ADMIN_AUTH_NOT_CONFIGURED'})
    supplied = authorization[7:] if authorization and authorization.startswith('Bearer ') else ''
    if not hmac.compare_digest(supplied, token):
        raise HTTPException(status_code=401, detail={'code': 'UNAUTHORIZED'})


def new_id(prefix: str) -> str:
    return f'{prefix}_{secrets.token_urlsafe(18)}'
