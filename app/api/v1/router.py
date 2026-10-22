"""Агрегирующий роутер `/api/v1`.

Роутеры фаз подключаются здесь по мере реализации.
"""

from fastapi import APIRouter

from app.api.v1.routes.auth import router as auth_router
from app.api.v1.routes.clients import router as clients_router
from app.api.v1.routes.dictionaries import router as dictionaries_router
from app.api.v1.routes.psychologists import router as psychologists_router
from app.api.v1.routes.quizzes import router as quizzes_router
from app.api.v1.routes.session_requests import router as session_requests_router
from app.api.v1.routes.sessions import router as sessions_router

api_router = APIRouter()

api_router.include_router(auth_router)
api_router.include_router(clients_router)
api_router.include_router(psychologists_router)
api_router.include_router(dictionaries_router)
api_router.include_router(quizzes_router)
api_router.include_router(session_requests_router)
api_router.include_router(sessions_router)
