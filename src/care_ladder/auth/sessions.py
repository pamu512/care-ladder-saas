"""Signed session tokens (itsdangerous) for the care_ladder_session cookie."""
from itsdangerous import BadSignature, URLSafeTimedSerializer

from pydantic import BaseModel

COOKIE_NAME = "care_ladder_session"
_MAX_AGE_SECONDS = 7 * 24 * 3600


class SessionData(BaseModel):
    user_id: str
    tenant_id: str
    email: str


def _serializer(secret: str) -> URLSafeTimedSerializer:
    return URLSafeTimedSerializer(secret, salt="care-ladder-session")


def create_session_token(data: SessionData, secret: str) -> str:
    return _serializer(secret).dumps(data.model_dump())


def read_session_token(token: str, secret: str) -> SessionData | None:
    try:
        payload = _serializer(secret).loads(token, max_age=_MAX_AGE_SECONDS)
    except BadSignature:
        return None
    try:
        return SessionData.model_validate(payload)
    except Exception:
        return None


def cookie_kwargs() -> dict:
    return {
        "cookie_name": COOKIE_NAME,
        "max_age": _MAX_AGE_SECONDS,
        "httponly": True,
        "samesite": "lax",
    }
