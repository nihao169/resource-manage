"""Shared application: only real infrastructure routes are registered."""
import logging
from contextlib import asynccontextmanager
from uuid import uuid4
import anyio
from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from starlette.exceptions import HTTPException
from app.core.config import Settings
from app.core.errors import BusinessError, error_response
from app.core.resources import make_resources
from app.services.health_service import HealthService

logger = logging.getLogger(__name__)

def create_app(settings: Settings | None = None, resource_factory=make_resources):
    settings = settings or Settings()

    @asynccontextmanager
    async def lifespan(application):
        resources = resource_factory(settings)
        application.state.resources = resources
        try:
            yield
        finally:
            resources.close()

    development = settings.app_env == "development"
    application = FastAPI(title="File Manager Skeleton", lifespan=lifespan,
        docs_url="/api/docs" if development else None,
        openapi_url="/api/openapi.json" if development else None, redoc_url=None)

    @application.middleware("http")
    async def request_identifier(request: Request, call_next):
        request.state.request_id = uuid4()
        response = await call_next(request)
        response.headers["X-Request-ID"] = str(request.state.request_id)
        return response

    @application.exception_handler(BusinessError)
    async def handle_business(request, exc):
        return error_response(request, exc)

    @application.exception_handler(HTTPException)
    async def handle_http(request, exc):
        code = "NOT_FOUND" if exc.status_code == 404 else "INVALID_REQUEST"
        return error_response(request, BusinessError(code, "请求不可用", exc.status_code))

    @application.exception_handler(RequestValidationError)
    async def handle_validation(request, exc):
        details = {"fields": [{"loc": list(e["loc"]), "type": e["type"]} for e in exc.errors()]}
        return error_response(request, BusinessError("VALIDATION_ERROR", "参数校验失败", 422, details))

    @application.exception_handler(Exception)
    async def handle_unknown(request, exc):
        logger.error("Unhandled request failure: request_id=%s", request.state.request_id)
        return error_response(request, BusinessError("INTERNAL_ERROR", "内部错误"))

    @application.get("/api/health/live", tags=["Infrastructure"])
    async def live(request: Request):
        return {"data": {"status": "live"}, "request_id": str(request.state.request_id)}

    @application.get("/api/health/ready", tags=["Infrastructure"])
    async def ready(request: Request):
        data = await anyio.to_thread.run_sync(HealthService(application.state.resources).ready)
        return {"data": data, "request_id": str(request.state.request_id)}

    return application

app = create_app()

