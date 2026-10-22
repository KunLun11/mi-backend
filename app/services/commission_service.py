"""Бизнес-логика комиссии сервиса по проведённым сессиям."""

from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.models import (
    Commission,
    CommissionRateType,
    CommissionStatus,
    TherapySession,
)


async def create_commission(db: AsyncSession, session: TherapySession) -> Commission:
    """Создать комиссию за проведённую сессию (идемпотентно).

    На MVP используется фиксированная ставка `COMMISSION_FIXED_RUB`
    (по умолчанию 500 ₽). Флаш выполняется здесь, коммит — вызывающей стороной.
    """
    existing = await db.scalar(select(Commission).where(Commission.session_id == session.id))
    if existing is not None:
        return existing

    amount = get_settings().commission_fixed_rub
    commission = Commission(
        session_id=session.id,
        amount_rub=amount,
        rate_type=CommissionRateType.FIXED,
        rate_value=Decimal(amount),
        status=CommissionStatus.PENDING,
    )
    db.add(commission)
    await db.flush()
    return commission
