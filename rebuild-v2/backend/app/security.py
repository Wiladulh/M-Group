import hashlib
import hmac
import secrets


def hash_secret(secret: str, pepper: str = '') -> str:
    return hashlib.sha256((pepper + secret).encode('utf-8')).hexdigest()


def verify_secret(secret: str, expected_hash: str, pepper: str = '') -> bool:
    return hmac.compare_digest(hash_secret(secret, pepper), expected_hash)


def new_id(prefix: str) -> str:
    return f'{prefix}_{secrets.token_urlsafe(18)}'
