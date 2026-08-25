from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.core.dependencies import get_current_user, get_db
from app.models.beds24_availability_summary import Beds24AvailabilitySummary
from app.models.user import User

router = APIRouter(tags=["beds24-availability"])


class Beds24AvailabilityFreeRange(BaseModel):
    check_in: str
    check_out: str


class Beds24AvailabilityRoom(BaseModel):
    room_name: str
    free_ranges: list[Beds24AvailabilityFreeRange]


class Beds24AvailabilitySummaryRead(BaseModel):
    summary_text: str
    refreshed_at: Optional[datetime] = None
    rooms: list[Beds24AvailabilityRoom] = []


@router.get("/beds24-availability", response_model=Beds24AvailabilitySummaryRead)
def get_beds24_availability_summary(db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    row = db.query(Beds24AvailabilitySummary).first()
    if row is None:
        return Beds24AvailabilitySummaryRead(summary_text="Availability has not been fetched yet.", refreshed_at=None, rooms=[])
    return Beds24AvailabilitySummaryRead(summary_text=row.summary_text, refreshed_at=row.refreshed_at, rooms=row.rooms_json or [])
