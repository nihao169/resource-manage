"""B: sanitized public errors shared by both backend owners."""
from fastapi import Request
from fastapi.responses import JSONResponse

class BusinessError(Exception):
    def __init__(self, code: str, message: str, status: int = 500, details: dict | None = None):
        self.code, self.message, self.status, self.details = code, message, status, details or {}

def error_response(request: Request, error: BusinessError):
    request_id = str(request.state.request_id)
    return JSONResponse(status_code=error.status,
        content={"error": {"code": error.code, "message": error.message, "details": error.details},
                 "request_id": request_id},
        headers={"X-Request-ID": request_id})
