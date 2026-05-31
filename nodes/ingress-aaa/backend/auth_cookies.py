import os

from fastapi import HTTPException, Request, Response

COOKIE_ACCESS = "hc_access_token"
COOKIE_REFRESH = "hc_refresh_token"

# 30 days
SESSION_MAX_AGE = int(os.getenv("SESSION_MAX_AGE_SECONDS", str(30 * 24 * 60 * 60)))


def _cookie_secure() -> bool:
    value = os.getenv("COOKIE_SECURE", "true")
    return value.strip().lower() in {"1", "true", "yes", "on"}


def _cookie_samesite() -> str:
    return os.getenv("COOKIE_SAMESITE", "lax").strip().lower()


def set_auth_cookies(response: Response, token_data: dict) -> None:
    access_ttl = int(token_data.get("expires_in") or 3600)
    access_ttl = min(access_ttl, SESSION_MAX_AGE)

    refresh_ttl = int(token_data.get("refresh_expires_in") or SESSION_MAX_AGE)
    refresh_ttl = min(refresh_ttl, SESSION_MAX_AGE) if refresh_ttl > 0 else SESSION_MAX_AGE

    common = {
        "httponly": True,
        "secure": _cookie_secure(),
        "samesite": _cookie_samesite(),
        "path": "/",
    }

    response.set_cookie(
        key=COOKIE_ACCESS,
        value=token_data["access_token"],
        max_age=access_ttl,
        **common,
    )

    refresh_token = token_data.get("refresh_token")
    if refresh_token:
        response.set_cookie(
            key=COOKIE_REFRESH,
            value=refresh_token,
            max_age=SESSION_MAX_AGE,
            **common,
        )


def clear_auth_cookies(response: Response) -> None:
    common = {
        "httponly": True,
        "secure": _cookie_secure(),
        "samesite": _cookie_samesite(),
        "path": "/",
    }
    response.delete_cookie(COOKIE_ACCESS, **common)
    response.delete_cookie(COOKIE_REFRESH, **common)


def extract_access_token(
    request: Request,
    authorization: str | None = None,
) -> str | None:
    if authorization:
        value = authorization.strip()
        if value.lower().startswith("bearer "):
            return value.split(" ", 1)[1].strip() or None
        return value or None

    return request.cookies.get(COOKIE_ACCESS)


def extract_refresh_token(
    request: Request,
    body_refresh: str | None = None,
) -> str | None:
    if body_refresh and body_refresh.strip():
        return body_refresh.strip()
    return request.cookies.get(COOKIE_REFRESH)
