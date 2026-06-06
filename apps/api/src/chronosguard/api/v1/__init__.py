"""Versioned API surface — routers register here, mounted at /api/v1."""

from fastapi import APIRouter

v1_router = APIRouter()

# Routers are included as chunks land:
#   C2: me        C3/C4: regulatory        C5: policies        C6: audits        C7: admin
