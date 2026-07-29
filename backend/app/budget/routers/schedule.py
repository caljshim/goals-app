from datetime import date

from fastapi import APIRouter, Depends, HTTPException, Response
from sqlmodel import Session

from app.budget.db import get_session
from app.budget.schemas import (
    CalendarEventCreate,
    CalendarEventRead,
    CalendarEventUpdate,
    ReminderCreate,
    ReminderRead,
    ReminderUpdate,
    ScheduleItemRead,
)
from app.budget.services import schedule as schedule_svc


router = APIRouter(prefix="/api", tags=["schedule"])


@router.get("/schedule", response_model=list[ScheduleItemRead])
def list_schedule(start: date, end: date, session: Session = Depends(get_session)):
    try:
        return schedule_svc.list_schedule(session, start, end)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@router.post("/reminders", response_model=ReminderRead, status_code=201)
def create_reminder(body: ReminderCreate, session: Session = Depends(get_session)):
    try:
        return schedule_svc.create_reminder(session, body.model_dump())
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@router.patch("/reminders/{reminder_id}", response_model=ReminderRead)
def update_reminder(reminder_id: int, body: ReminderUpdate, session: Session = Depends(get_session)):
    try:
        reminder = schedule_svc.update_reminder(
            session, reminder_id, body.model_dump(exclude_unset=True)
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    if reminder is None:
        raise HTTPException(status_code=404, detail="Reminder not found")
    return reminder


@router.delete("/reminders/{reminder_id}", status_code=204)
def delete_reminder(reminder_id: int, session: Session = Depends(get_session)):
    if not schedule_svc.delete_reminder(session, reminder_id):
        raise HTTPException(status_code=404, detail="Reminder not found")
    return Response(status_code=204)


@router.get("/events", response_model=list[CalendarEventRead])
def list_events(
    start: date | None = None,
    end: date | None = None,
    session: Session = Depends(get_session),
):
    return schedule_svc.list_events(session, start, end)


@router.post("/events", response_model=CalendarEventRead, status_code=201)
def create_event(body: CalendarEventCreate, session: Session = Depends(get_session)):
    try:
        return schedule_svc.create_event(session, body.model_dump())
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@router.patch("/events/{event_id}", response_model=CalendarEventRead)
def update_event(
    event_id: int, body: CalendarEventUpdate, session: Session = Depends(get_session)
):
    try:
        event = schedule_svc.update_event(
            session, event_id, body.model_dump(exclude_unset=True)
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    if event is None:
        raise HTTPException(status_code=404, detail="Event not found")
    return event


@router.delete("/events/{event_id}", status_code=204)
def delete_event(event_id: int, session: Session = Depends(get_session)):
    if not schedule_svc.delete_event(session, event_id):
        raise HTTPException(status_code=404, detail="Event not found")
    return Response(status_code=204)
