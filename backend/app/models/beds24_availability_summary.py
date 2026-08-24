from sqlalchemy import Column, DateTime, Integer, Text, func

from app.database import Base


class Beds24AvailabilitySummary(Base):
    """A single-row cache of the parsed, human-readable room availability summary.

    Refreshed on a background poll (see beds24_availability_service.refresh_availability_summary)
    rather than fetched live per draft - one row, overwritten each refresh, mirroring the
    AdminSettings singleton-row pattern.
    """

    __tablename__ = "beds24_availability_summary"

    id = Column(Integer, primary_key=True, index=True)
    refreshed_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
    summary_text = Column(Text, nullable=False, default="")
