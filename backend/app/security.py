from datetime import datetime, timedelta, timezone

import bcrypt
import jwt

from app import config


def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode(), bcrypt.gensalt()).decode()


def verify_password(password: str, password_hash: str) -> bool:
    return bcrypt.checkpw(password.encode(), password_hash.encode())


def create_token(user) -> str:
    exp = datetime.now(timezone.utc) + timedelta(
        minutes=config.JWT_EXPIRE_MINUTES
    )
    return jwt.encode(
        {"sub": str(user.id), "role": user.role, "typ": "access", "exp": exp},
        config.JWT_SECRET,
        algorithm="HS256",
    )


def create_reset_token(user) -> str:
    exp = datetime.now(timezone.utc) + timedelta(minutes=15)
    # ph ties the token to the current password, so it works only once.
    return jwt.encode(
        {
            "sub": str(user.id),
            "typ": "reset",
            "ph": user.password_hash[-12:],
            "exp": exp,
        },
        config.JWT_SECRET,
        algorithm="HS256",
    )


def decode_token(token: str, typ: str = "access") -> dict | None:
    try:
        claims = jwt.decode(token, config.JWT_SECRET, algorithms=["HS256"])
    except jwt.PyJWTError:
        return None
    return claims if claims.get("typ") == typ else None
