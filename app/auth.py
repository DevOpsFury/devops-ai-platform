import secrets

from fastapi import Header, HTTPException, status

from app.config import settings


def require_api_key(x_api_key: str = Header(default="")) -> str:
    expected = settings.app_api_key.get_secret_value()
    if not secrets.compare_digest(x_api_key, expected):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing or invalid X-API-Key",
        )
    return "api-key"
