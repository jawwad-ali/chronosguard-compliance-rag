"""Versioned API surface — routers register here, mounted at /api/v1."""

from fastapi import APIRouter

from chronosguard.api.v1.me import router as me_router
from chronosguard.api.v1.regulatory import router as regulatory_router

v1_router = APIRouter()
v1_router.include_router(me_router)
v1_router.include_router(regulatory_router)

# Routers are included as chunks land:
#   C4: regulatory/search        C5: policies        C6: audits        C7: admin
