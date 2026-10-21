"""Эндпоинты профиля клиента."""

from fastapi import APIRouter

from app.api.deps import ClientUser, SessionDep
from app.schemas.profiles import ClientProfileIn, ClientProfileOut
from app.services import profile_service

router = APIRouter(prefix="/clients", tags=["clients"])


@router.get("/me", response_model=ClientProfileOut)
async def get_my_profile(user: ClientUser, db: SessionDep) -> ClientProfileOut:
    """Прочитать собственный профиль клиента."""
    profile = await profile_service.get_client_profile(db, user)
    return ClientProfileOut.model_validate(profile)


@router.put("/me", response_model=ClientProfileOut)
async def update_my_profile(
    payload: ClientProfileIn,
    user: ClientUser,
    db: SessionDep,
) -> ClientProfileOut:
    """Обновить собственный профиль клиента."""
    profile = await profile_service.update_client_profile(db, user, payload)
    return ClientProfileOut.model_validate(profile)
