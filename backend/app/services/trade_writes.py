"""Conditional writes for a trade's status. Every path that closes or
answers a trade (respond, cancel, commissioner approve/deny) reads the
row, checks it, and then writes. Two of those paths can interleave, so the
write only lands if the row is still in the state the check saw. A miss
is a 409 and the caller's transaction rolls back."""
from fastapi import HTTPException
from sqlalchemy import update
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.transaction import Transaction, TransactionStatus

TRADE_CHANGED = "This trade changed while you were looking at it. Refresh and try again."


async def write_pending_trade(
    db: AsyncSession, trade: Transaction, *, unanswered: bool = False, **values
) -> None:
    conditions = [Transaction.id == trade.id, Transaction.status == TransactionStatus.PENDING]
    if unanswered:
        conditions.append(Transaction.details["recipient_response"].as_string().is_(None))
    result = await db.execute(
        update(Transaction)
        .where(*conditions)
        .values(**values)
        .execution_options(synchronize_session=False)
    )
    if result.rowcount == 0:
        raise HTTPException(status_code=409, detail=TRADE_CHANGED)
