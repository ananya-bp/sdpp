from datetime import datetime
from decimal import Decimal

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Numeric, String, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class Student(Base):
    """Student academic record.

    In this project these rows are SIMULATED university data (no real KLE Tech records).
    user_id is nullable so a record can exist before the student registers a login.
    """

    __tablename__ = "students"
    __table_args__ = (
        CheckConstraint("cgpa >= 0 AND cgpa <= 10", name="cgpa_range"),
        CheckConstraint("semester >= 1 AND semester <= 8", name="semester_range"),
        CheckConstraint("backlog_count >= 0", name="backlog_non_negative"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), unique=True, nullable=True
    )
    usn: Mapped[str] = mapped_column(String(20), unique=True, index=True)
    full_name: Mapped[str] = mapped_column(String(150))
    department: Mapped[str] = mapped_column(String(100))
    semester: Mapped[int]
    cgpa: Mapped[Decimal] = mapped_column(Numeric(4, 2))
    backlog_count: Mapped[int] = mapped_column(default=0, server_default="0")
    # Provisional values: 'CLEAR' (no dues) / 'DUE'. Finalised with the eligibility rules in Phase 3.
    fee_status: Mapped[str] = mapped_column(String(20), default="CLEAR", server_default="CLEAR")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
