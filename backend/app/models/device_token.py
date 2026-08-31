from sqlalchemy import Column, DateTime, ForeignKey, Integer, String, UniqueConstraint, func

from app.database import Base


class DeviceToken(Base):
    """A push destination for a user's device (an Expo push token).

    One row per token, uniquely owned: registering an already-known token re-points it at the
    current user and bumps last_seen_at (a device re-registers on each launch / token refresh).
    Rows are deleted on explicit unregister (logout) and pruned when Expo reports the token as
    no longer registered.
    """

    __tablename__ = "device_tokens"
    __table_args__ = (UniqueConstraint("token", name="uq_device_tokens_token"),)

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    token = Column(String(255), nullable=False)
    # "android" | "ios" | "web" | null — informational; Expo routes by the token itself.
    platform = Column(String(20), nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
    last_seen_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
