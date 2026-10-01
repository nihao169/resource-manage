from typing import Annotated
from uuid import UUID
from fastapi import APIRouter, Cookie, Depends, Query, Request, Response
from app.core.security import (ACCESS_COOKIE, CSRF_COOKIE, REFRESH_COOKIE, CurrentActor,
    create_csrf_token, current_actor, decode_token, read_key, require_csrf)
from app.core.security import ensure_business_access, require_idempotency_key
from app.schemas.dto import LoginInput, PasswordInput
from app.services.auth_service import AuthService
router = APIRouter(prefix="/auth", tags=["auth"])

def _envelope(request, data):
    return {"data": data, "request_id": str(request.state.request_id)}

def _service(request):
    return AuthService(request.app.state.resources, request.app.state.settings)

def _set_auth_cookies(response, result, request):
    secure = request.app.state.settings.cookie_secure
    response.set_cookie(ACCESS_COOKIE, result["access"], secure=secure, httponly=True,
        samesite="lax", path="/", max_age=request.app.state.settings.access_ttl_seconds)
    response.set_cookie(REFRESH_COOKIE, result["refresh"], secure=secure, httponly=True,
        samesite="strict", path="/", max_age=request.app.state.settings.refresh_ttl_seconds)
    response.set_cookie(CSRF_COOKIE, result["csrf"], secure=secure, httponly=False,
        samesite="strict", path="/", max_age=request.app.state.settings.refresh_ttl_seconds)

def _clear_auth_cookies(response):
    for name in (ACCESS_COOKIE, REFRESH_COOKIE, CSRF_COOKIE):
        response.delete_cookie(name, path="/")

@router.get("/csrf")
def csrf(request: Request, response: Response):
    binding = "preauth"
    access = request.cookies.get(ACCESS_COOKIE)
    if access:
        try:
            binding = decode_token(access, read_key(request.app.state.settings, "jwt_key_file"),
                token_type="access")["sid"]
        except Exception:
            pass
    token, expires = create_csrf_token(binding,
        read_key(request.app.state.settings, "csrf_key_file"),
        request.app.state.settings.refresh_ttl_seconds)
    response.set_cookie(CSRF_COOKIE, token, secure=request.app.state.settings.cookie_secure,
        httponly=False, samesite="strict", path="/",
        max_age=request.app.state.settings.refresh_ttl_seconds)
    response.headers["Cache-Control"] = "no-store"
    return _envelope(request, {"csrf_token": token, "expires_at": expires})

@router.post("/login", status_code=201, dependencies=[Depends(require_csrf)])
def login(payload: LoginInput, request: Request, response: Response):
    result = _service(request).login(payload.username, payload.password,
        user_agent=request.headers.get("user-agent"),
        source_ip=request.client.host if request.client else None, request_id=request.state.request_id)
    _set_auth_cookies(response, result, request)
    return _envelope(request, result["data"])

@router.post("/refresh", dependencies=[Depends(require_csrf)])
def refresh(request: Request, response: Response,
            refresh_token: Annotated[str | None, Cookie(alias=REFRESH_COOKIE)] = None,
            csrf_token: Annotated[str | None, Cookie(alias=CSRF_COOKIE)] = None):
    result = _service(request).refresh(refresh_token, csrf_token)
    _set_auth_cookies(response, result, request)
    return _envelope(request, result["data"])

@router.post("/logout", dependencies=[Depends(require_csrf)])
def logout(request: Request, response: Response,
           access_token: Annotated[str | None, Cookie(alias=ACCESS_COOKIE)] = None,
           refresh_token: Annotated[str | None, Cookie(alias=REFRESH_COOKIE)] = None):
    session_id = None
    if access_token:
        try:
            claims = decode_token(access_token, read_key(request.app.state.settings, "jwt_key_file"),
                token_type="access")
            session_id = UUID(claims["sid"])
        except Exception:
            pass
    _service(request).logout(session_id, refresh_token)
    _clear_auth_cookies(response)
    return _envelope(request, {"logged_out": True})

@router.get("/me")
def me(request: Request, actor: Annotated[CurrentActor, Depends(current_actor)]):
    with request.app.state.resources.engine.connect() as connection:
        from app.repositories.user_repository import UserRepository
        row = UserRepository().by_id(connection, actor.user_id)
    return _envelope(request, AuthService.public_user(row))

@router.post("/password", dependencies=[Depends(require_csrf), Depends(require_idempotency_key)])
def password(payload: PasswordInput, request: Request, response: Response,
             actor: Annotated[CurrentActor, Depends(current_actor)]):
    _service(request).change_password(actor, payload.current_password, payload.new_password,
        request.state.request_id)
    _clear_auth_cookies(response)
    return _envelope(request, {"password_changed": True, "logged_out": True})

@router.get("/sessions")
def sessions(request: Request, actor: Annotated[CurrentActor, Depends(current_actor)],
             page: int = Query(1, ge=1), page_size: int = Query(50, ge=1, le=200)):
    ensure_business_access(actor)
    return _envelope(request, _service(request).sessions(actor, page, page_size))

@router.delete("/sessions/{session_id}",
               dependencies=[Depends(require_csrf), Depends(require_idempotency_key)])
def revoke_session(session_id: UUID, request: Request, response: Response,
                   actor: Annotated[CurrentActor, Depends(current_actor)]):
    ensure_business_access(actor)
    _service(request).revoke(actor, session_id)
    if session_id == actor.session_id:
        _clear_auth_cookies(response)
    return _envelope(request, {"session_id": session_id, "revoked": True})
