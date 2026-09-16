from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, ConfigDict
from sqlalchemy.orm import Session

from app.core.dependencies import get_current_user, get_db
from app.models.app_knowledge_entry import AppKnowledgeEntry
from app.models.assistant_conversation import AssistantConversation
from app.models.user import User
from app.services import ai_assistant_service, app_knowledge_service

router = APIRouter(prefix="/ai-assistant", tags=["ai-assistant"])


# --- Conversations -------------------------------------------------------------------


class ConversationRead(BaseModel):
    id: int
    title: str
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


class ConversationCreate(BaseModel):
    title: str | None = None


class ConversationRename(BaseModel):
    title: str


class MessageRead(BaseModel):
    id: int
    role: str
    content: str
    tool_trace: dict | None = None
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


class AskRequest(BaseModel):
    question: str
    screen_context: dict | None = None
    use_crm: bool = False


def _get_owned_conversation(db: Session, conversation_id: int, user: User) -> AssistantConversation:
    conversation = ai_assistant_service.get_conversation(db, conversation_id, user.id)
    if conversation is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Conversation not found")
    return conversation


@router.get("/conversations", response_model=list[ConversationRead])
def list_conversations(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    return ai_assistant_service.list_conversations(db, current_user.id)


@router.post("/conversations", response_model=ConversationRead, status_code=status.HTTP_201_CREATED)
def create_conversation(
    payload: ConversationCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    conversation = ai_assistant_service.create_conversation(db, current_user.id, payload.title)
    db.commit()
    db.refresh(conversation)
    return conversation


@router.get("/conversations/{conversation_id}", response_model=list[MessageRead])
def get_conversation_messages(
    conversation_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    conversation = _get_owned_conversation(db, conversation_id, current_user)
    return ai_assistant_service.list_messages(db, conversation.id)


@router.patch("/conversations/{conversation_id}", response_model=ConversationRead)
def rename_conversation(
    conversation_id: int,
    payload: ConversationRename,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    conversation = _get_owned_conversation(db, conversation_id, current_user)
    title = payload.title.strip()
    if not title:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="title is required")
    ai_assistant_service.rename_conversation(db, conversation, title)
    db.commit()
    db.refresh(conversation)
    return conversation


@router.delete("/conversations/{conversation_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_conversation(
    conversation_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    conversation = _get_owned_conversation(db, conversation_id, current_user)
    ai_assistant_service.delete_conversation(db, conversation)
    db.commit()


@router.post("/conversations/{conversation_id}/messages", response_model=MessageRead, status_code=status.HTTP_201_CREATED)
def ask(
    conversation_id: int,
    payload: AskRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    conversation = _get_owned_conversation(db, conversation_id, current_user)
    question = payload.question.strip()
    if not question:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="question is required")

    assistant_message = ai_assistant_service.ask(
        db,
        conversation,
        question,
        screen_context=payload.screen_context,
        use_crm=payload.use_crm,
    )
    db.commit()
    db.refresh(assistant_message)
    return assistant_message


# --- Knowledge base --------------------------------------------------------------------


class KnowledgeEntryRead(BaseModel):
    id: int
    title: str
    body: str
    category: str | None = None
    source: str
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


class KnowledgeEntryCreate(BaseModel):
    title: str
    body: str
    category: str | None = None
    source: str = "user"  # a saved AI suggestion is posted with source="ai"


class KnowledgeEntryUpdate(BaseModel):
    title: str | None = None
    body: str | None = None
    category: str | None = None


def _get_knowledge_entry(db: Session, entry_id: int) -> AppKnowledgeEntry:
    entry = app_knowledge_service.get_entry(db, entry_id)
    if entry is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Knowledge base entry not found")
    return entry


@router.get("/knowledge", response_model=list[KnowledgeEntryRead])
def list_knowledge(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    return app_knowledge_service.list_entries(db)


@router.post("/knowledge", response_model=KnowledgeEntryRead, status_code=status.HTTP_201_CREATED)
def create_knowledge(
    payload: KnowledgeEntryCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    if not payload.title.strip() or not payload.body.strip():
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="title and body are required")
    entry = app_knowledge_service.create_entry(
        db,
        title=payload.title,
        body=payload.body,
        category=payload.category,
        source=payload.source,
        created_by_user_id=current_user.id,
    )
    db.commit()
    db.refresh(entry)
    return entry


@router.patch("/knowledge/{entry_id}", response_model=KnowledgeEntryRead)
def update_knowledge(
    entry_id: int,
    payload: KnowledgeEntryUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    entry = _get_knowledge_entry(db, entry_id)
    app_knowledge_service.update_entry(db, entry, title=payload.title, body=payload.body, category=payload.category)
    db.commit()
    db.refresh(entry)
    return entry


@router.delete("/knowledge/{entry_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_knowledge(
    entry_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    entry = _get_knowledge_entry(db, entry_id)
    app_knowledge_service.delete_entry(db, entry)
    db.commit()
