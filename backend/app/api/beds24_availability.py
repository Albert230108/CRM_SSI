from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.core.dependencies import get_current_user, get_db
from app.models.beds24_availability_summary import Beds24AvailabilitySummary
from app.models.user import User
from app.services import beds24_availability_service

router = APIRouter(tags=["beds24-availability"])


class Beds24AvailabilityFreeRange(BaseModel):
    check_in: str
    check_out: str


class Beds24AvailabilityRoom(BaseModel):
    room_name: str
    free_ranges: list[Beds24AvailabilityFreeRange]


class Beds24AvailabilitySummaryRead(BaseModel):
    summary_text: str
    context_note: str
    refreshed_at: Optional[datetime] = None
    rooms: list[Beds24AvailabilityRoom] = []


class Beds24AvailabilityContextNoteUpdate(BaseModel):
    context_note: str


class Beds24AvailabilityContextNoteRead(BaseModel):
    context_note: str


@router.get("/beds24-availability", response_model=Beds24AvailabilitySummaryRead)
def get_beds24_availability_summary(db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    row = db.query(Beds24AvailabilitySummary).first()
    if row is None:
        return Beds24AvailabilitySummaryRead(
            summary_text="Availability has not been fetched yet.",
            context_note="",
            refreshed_at=None,
            rooms=[],
        )
    return Beds24AvailabilitySummaryRead(
        summary_text=row.summary_text,
        context_note=row.context_note,
        refreshed_at=row.refreshed_at,
        rooms=row.rooms_json or [],
    )


@router.patch("/beds24-availability/context-note", response_model=Beds24AvailabilityContextNoteRead)
def update_beds24_availability_context_note(
    payload: Beds24AvailabilityContextNoteUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> Beds24AvailabilityContextNoteRead:
    row = db.query(Beds24AvailabilitySummary).first()
    if row is None:
        row = Beds24AvailabilitySummary(
            summary_text=beds24_availability_service.get_cached_summary(db),
            rooms_json=[],
            context_note=payload.context_note,
        )
        db.add(row)
    else:
        row.context_note = payload.context_note
    db.commit()
    db.refresh(row)
    return Beds24AvailabilityContextNoteRead(context_note=row.context_note)
