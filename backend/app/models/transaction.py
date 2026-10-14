from datetime import datetime
from decimal import Decimal

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Numeric, String, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class Transaction(Base):
    """Payment attempt for an application (sandbox/mock payments from Phase 3).

    An application may have several rows (e.g. a failed attempt followed by a retry);
    that history is what the anomaly detection component analyses later.
    """

    __tablename__ = "transactions"
    __table_args__ = (CheckConstraint("amount >= 0", name="amount_non_negative"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    application_id: Mapped[int] = mapped_column(
        ForeignKey("applications.id", ondelete="RESTRICT"), index=True
    )
    amount: Mapped[Decimal] = mapped_column(Numeric(10, 2))
    payment_status: Mapped[str] = mapped_column(String(20), default="PENDING", server_default="PENDING")
    transacted_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
