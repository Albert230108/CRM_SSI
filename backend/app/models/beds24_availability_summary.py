from sqlalchemy import Column, DateTime, Integer, JSON, Text, func

from app.database import Base


class Beds24AvailabilitySummary(Base):
    """A single-row cache of the parsed room availability, in two shapes.

    Refreshed on a background poll (see beds24_availability_service.refresh_availability_summary)
    rather than fetched live per draft - one row, overwritten each refresh, mirroring the
    AdminSettings singleton-row pattern.

    `summary_text` is prose fed to AI-agent prompts as context (free check-in/check-out lines for
    each room - see get_cached_summary). `rooms_json` is structured, free-ranges-only data for
    the Availability tab UI, which formats and labels dates itself - see
    beds24_availability_service.parse_availability_structured.
    """

    __tablename__ = "beds24_availability_summary"

    id = Column(Integer, primary_key=True, index=True)
    refreshed_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
    summary_text = Column(Text, nullable=False, default="")
    context_note = Column(Text, nullable=False, default="", server_default="")
    rooms_json = Column(JSON, nullable=True)
