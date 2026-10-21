"""Агрегирующий роутер `/api/v1`.

Роутеры фаз подключаются здесь по мере реализации.
"""

from fastapi import APIRouter

from app.api.v1.routes.auth import router as auth_router

api_router = APIRouter()

api_router.include_router(auth_router)
