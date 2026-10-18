import hashlib
import hmac
import secrets


ALGORITHM = "pbkdf2_sha256"
DEFAULT_ITERATIONS = 310_000


def hash_password(password: str, iterations: int = DEFAULT_ITERATIONS) -> str:
    if not password:
        raise ValueError("password_required")
    salt = secrets.token_bytes(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, iterations)
    return ALGORITHM + "$" + str(iterations) + "$" + salt.hex() + "$" + digest.hex()


def verify_password(password: str, encoded: str) -> bool:
    try:
        algorithm, iteration_text, salt_hex, digest_hex = encoded.split("$", 3)
        iterations = int(iteration_text)
        if algorithm != ALGORITHM or not 100_000 <= iterations <= 2_000_000:
            return False
        salt = bytes.fromhex(salt_hex)
        expected = bytes.fromhex(digest_hex)
        if len(salt) < 16 or len(expected) != 32:
            return False
        actual = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, iterations)
        return hmac.compare_digest(actual, expected)
    except (ValueError, TypeError, AttributeError):
        return False


def hash_session_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def new_session_token() -> str:
    return secrets.token_urlsafe(32)
