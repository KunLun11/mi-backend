"""Эндпоинты справочников для квиза и онбординга."""

from fastapi import APIRouter

from app.api.deps import CurrentUser, SessionDep
from app.schemas.profiles import DictionaryItem
from app.services import dictionary_service

router = APIRouter(prefix="/dictionaries", tags=["dictionaries"])


@router.get("/approaches", response_model=list[DictionaryItem])
async def list_approaches(
    _user: CurrentUser,
    db: SessionDep,
) -> list[DictionaryItem]:
    """Справочник психотерапевтических подходов."""
    items = await dictionary_service.list_approaches(db)
    return [DictionaryItem.model_validate(item) for item in items]


@router.get("/it-contexts", response_model=list[DictionaryItem])
async def list_it_contexts(
    _user: CurrentUser,
    db: SessionDep,
) -> list[DictionaryItem]:
    """Справочник IT-контекстов."""
    items = await dictionary_service.list_it_contexts(db)
    return [DictionaryItem.model_validate(item) for item in items]


@router.get("/concerns", response_model=list[DictionaryItem])
async def list_concerns(
    _user: CurrentUser,
    db: SessionDep,
) -> list[DictionaryItem]:
    """Справочник основных запросов клиентов."""
    items = await dictionary_service.list_concerns(db)
    return [DictionaryItem.model_validate(item) for item in items]
