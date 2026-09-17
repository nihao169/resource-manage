"""B: pending business routes. Do not register before security is implemented."""
from fastapi import APIRouter
router = APIRouter(prefix="/versions", tags=["versions"])
