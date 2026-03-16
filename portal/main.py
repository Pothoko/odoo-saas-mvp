"""
SaaS Portal — main entrypoint.

Provides:
  POST /api/v1/instances       — provision a new Odoo tenant
  GET  /api/v1/instances/{id}  — status of a tenant
  DELETE /api/v1/instances/{id} — tear down a tenant
  GET  /healthz                — liveness probe
"""
import logging
import os

from fastapi import FastAPI, Depends, HTTPException, Security
from fastapi.security.api_key import APIKeyHeader
from contextlib import asynccontextmanager

from .routers import instances

logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO)

API_KEY = os.getenv("API_KEY", "changeme")
api_key_header = APIKeyHeader(name="X-API-Key", auto_error=True)


def verify_key(key: str = Security(api_key_header)):
    if key != API_KEY:
        raise HTTPException(status_code=403, detail="Forbidden")
    return key


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("SaaS portal starting …")
    yield
    logger.info("SaaS portal shutting down …")


app = FastAPI(title="Odoo SaaS Portal", lifespan=lifespan)

app.include_router(
    instances.router,
    prefix="/api/v1/instances",
    tags=["instances"],
    dependencies=[Depends(verify_key)],
)


@app.get("/healthz")
def healthz():
    return {"status": "ok"}
