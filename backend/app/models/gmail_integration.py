from sqlalchemy import Boolean, Column, DateTime, Integer, JSON, String, Text, func

from app.database import Base


class GmailAccount(Base):
    __tablename__ = "gmail_accounts"

    id = Column(Integer, primary_key=True, index=True)
    email_address = Column(String(255), nullable=False, unique=True, index=True)
    display_name = Column(String(255), nullable=True)
    google_account_id = Column(String(255), nullable=True, unique=True, index=True)
    refresh_token_encrypted = Column(Text, nullable=True)
    token_uri = Column(String(500), nullable=True)
    scopes_json = Column(JSON, nullable=True)
    credentials_json = Column(JSON, nullable=True)
    is_active = Column(Boolean, nullable=False, default=True, server_default="true")
    last_synced_at = Column(DateTime(timezone=True), nullable=True)
    last_history_id = Column(String(100), nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now())


class Conversation(Base):
    __tablename__ = "conversations"

    id = Column(Integer, primary_key=True, index=True)
    provider = Column(String(50), nullable=False, index=True)
    provider_account_id = Column(Integer, nullable=True, index=True)
    provider_thread_id = Column(String(255), nullable=False, index=True)
    tenant_id = Column(Integer, nullable=True, index=True)
    subject = Column(String(500), nullable=True)
    last_message_at = Column(DateTime(timezone=True), nullable=True, index=True)
    preview_text = Column(Text, nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now())


class ConversationMessage(Base):
    __tablename__ = "conversation_messages"

    id = Column(Integer, primary_key=True, index=True)
    conversation_id = Column(Integer, nullable=False, index=True)
    provider = Column(String(50), nullable=False, index=True)
    provider_message_id = Column(String(255), nullable=False, unique=True, index=True)
    direction = Column(String(20), nullable=False)
    sender_email = Column(String(255), nullable=True, index=True)
    recipient_email = Column(String(255), nullable=True)
    subject = Column(String(500), nullable=True)
    body = Column(Text, nullable=False)
    sent_at = Column(DateTime(timezone=True), nullable=False, index=True)
    raw_payload = Column(JSON, nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now())

