from sqlalchemy import Column, DateTime, ForeignKey, Integer, JSON, String, func

from app.database import Base


class ActionSavedView(Base):
    """A per-user saved tab on the Actions page: a named bundle of structured filters plus a sort.

    Private to the owning user (scoped by user_id everywhere). Filtering and sorting themselves are
    applied client-side in Actions.tsx - this row just persists the choices so a tab can be reopened.
    `tag_ids` is a JSON list of ActionTagDefinition ids; the other filter columns are nullable so an
    unset column means "no constraint on this dimension".
    """

    __tablename__ = "action_saved_views"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    name = Column(String(120), nullable=False)
    position = Column(Integer, nullable=False, default=0, server_default="0")

    status = Column(String(20), nullable=True)  # open | done | dismissed | NULL (all)
    priority = Column(String(4), nullable=True)  # p1..p4 or NULL (any)
    tag_ids = Column(JSON, nullable=False, default=list, server_default="[]")
    tag_match = Column(String(4), nullable=False, default="any", server_default="any")  # any | all
    due_bucket = Column(String(20), nullable=True)  # overdue | today | upcoming | NULL (any)
    scope = Column(String(20), nullable=False, default="all", server_default="all")  # all | tenant | general
    sort_field = Column(String(20), nullable=False, default="due_date", server_default="due_date")  # due_date | priority | created_at
    sort_dir = Column(String(4), nullable=False, default="asc", server_default="asc")  # asc | desc

    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now())
