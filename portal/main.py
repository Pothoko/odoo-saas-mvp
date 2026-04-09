"""
SaaS Portal — main entrypoint.

Provides:
  POST   /api/v1/instances           — provision a new Odoo tenant
  GET    /api/v1/instances           — list all tenants
  GET    /api/v1/instances/{id}      — status of a tenant
  DELETE /api/v1/instances/{id}      — tear down a tenant
  POST   /api/v1/instances/{id}/stop — suspend
  POST   /api/v1/instances/{id}/start— resume
  GET    /api/v1/instances/{id}/logs — pod logs
  GET    /api/v1/instances/{id}/config
  PUT|PATCH /api/v1/instances/{id}/config
  GET    /api/v1/instances/check/{id}— availability check
  GET    /healthz                    — liveness probe
  GET    /ui                         — web dashboard (StaticFiles)
"""
from __future__ import annotations

import logging
import os
import uuid
import time
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Depends, HTTPException, Request, Security
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.security.api_key import APIKeyHeader
from fastapi.staticfiles import StaticFiles
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from slowapi.util import get_remote_address

from routers import instances

# ── JSON logging ──────────────────────────────────────────────────────────────
try:
    from pythonjsonlogger import jsonlogger  # type: ignore
    _handler = logging.StreamHandler()
    _handler.setFormatter(
        jsonlogger.JsonFormatter(
            "%(asctime)s %(name)s %(levelname)s %(message)s %(request_id)s"
        )
    )
    logging.root.handlers = [_handler]
except ImportError:
    logging.basicConfig(level=logging.INFO)

LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO").upper()
logging.root.setLevel(getattr(logging, LOG_LEVEL, logging.INFO))
logger = logging.getLogger(__name__)


# ── Auth ──────────────────────────────────────────────────────────────────────
api_key_header = APIKeyHeader(name="X-API-Key", auto_error=True)


def verify_key(key: str = Security(api_key_header)) -> str:
    # Lee en tiempo de ejecución para que los tests puedan sobrescribir API_KEY
    expected = os.getenv("API_KEY", "changeme")
    if key != expected:
        raise HTTPException(status_code=403, detail="Forbidden")
    return key


# ── Rate limiter ──────────────────────────────────────────────────────────────
limiter = Limiter(key_func=get_remote_address, default_limits=["120/minute"])


# ── Lifespan ──────────────────────────────────────────────────────────────────
@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("SaaS portal starting …")
    yield
    logger.info("SaaS portal shutting down …")


# ── App ───────────────────────────────────────────────────────────────────────
app = FastAPI(
    title="Odoo SaaS Portal",
    version="1.1.0",
    description="API de gestión de tenants Odoo multitenant sobre K3s.",
    lifespan=lifespan,
    docs_url="/docs",
    redoc_url="/redoc",
)

# Rate limiter handlers
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

# CORS — configurable via env para producción
_raw_origins = os.getenv("CORS_ORIGINS", "*")
_origins = [o.strip() for o in _raw_origins.split(",")] if _raw_origins != "*" else ["*"]

app.add_middleware(
    CORSMiddleware,
    allow_origins=_origins,
    allow_credentials=_raw_origins != "*",
    allow_methods=["*"],
    allow_headers=["*"],
)


# ── Request ID middleware ─────────────────────────────────────────────────────
@app.middleware("http")
async def request_id_middleware(request: Request, call_next):
    request_id = request.headers.get("X-Request-ID", str(uuid.uuid4()))
    request.state.request_id = request_id
    start = time.perf_counter()
    response = await call_next(request)
    duration_ms = int((time.perf_counter() - start) * 1000)
    response.headers["X-Request-ID"] = request_id
    response.headers["X-Response-Time"] = f"{duration_ms}ms"
    logger.info(
        "HTTP %s %s → %s (%dms)",
        request.method,
        request.url.path,
        response.status_code,
        duration_ms,
        extra={"request_id": request_id},
    )
    return response


# ── Security headers middleware ───────────────────────────────────────────────
@app.middleware("http")
async def security_headers_middleware(request: Request, call_next):
    response = await call_next(request)
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["X-XSS-Protection"] = "1; mode=block"
    response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
    response.headers["Permissions-Policy"] = "geolocation=(), microphone=(), camera=()"
    return response


# ── Global exception handler ──────────────────────────────────────────────────
@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    request_id = getattr(request.state, "request_id", "unknown")
    logger.exception("Unhandled exception [%s]", request_id)
    return JSONResponse(
        status_code=500,
        content={
            "error": "InternalServerError",
            "detail": str(exc),
            "request_id": request_id,
        },
    )


# ── Routers ───────────────────────────────────────────────────────────────────
app.include_router(
    instances.router,
    prefix="/api/v1/instances",
    tags=["instances"],
    dependencies=[Depends(verify_key)],
)


# ── Health ────────────────────────────────────────────────────────────────────
@app.get("/healthz", tags=["health"])
def healthz():
    return {"status": "ok", "version": app.version}


# ── Static files (Frontend UI) ─────────────────────────────────────────────
_static_dir = Path(__file__).parent / "static"
if _static_dir.is_dir():
    app.mount("/ui", StaticFiles(directory=str(_static_dir), html=True), name="ui")
    logger.info("Frontend UI mounted at /ui")
else:
    logger.warning("No static/ directory found — UI not available")
