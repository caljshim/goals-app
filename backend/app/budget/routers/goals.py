from fastapi import APIRouter, Depends, HTTPException, Response
from sqlmodel import Session

from app.budget.db import get_session
from app.budget import goal_customization
from app.budget.schemas import GoalCheckinUpdate, GoalCreate, GoalGroupEnd, GoalGroupSettingsRead, GoalGroupSettingsUpdate, GoalGroupUpdate, GoalProgressUpdate, GoalRaise, GoalRead, GoalTaskRead, GoalUpdate
from app.budget.services import goals as goals_svc

router = APIRouter(prefix="/api", tags=["goals"])


@router.get("/goals", response_model=list[GoalRead])
def list_goals(archived: bool = False, session: Session = Depends(get_session)):
    return goals_svc.list_with_progress(session, archived=archived)


@router.get("/goal-customization/catalog")
def goal_customization_catalog():
    return goal_customization.catalog()


@router.get("/goal-tasks", response_model=list[GoalTaskRead])
def list_goal_tasks(scope: str, session: Session = Depends(get_session)):
    try:
        return goals_svc.list_tasks(session, scope)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@router.patch("/goals/{goal_id}/checkin", response_model=GoalTaskRead)
def checkin_goal(goal_id: int, body: GoalCheckinUpdate, session: Session = Depends(get_session)):
    try:
        task = goals_svc.set_checkin(session, goal_id, body.scheduled_for, body.completed, body.allow_overdue)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    if not task:
        raise HTTPException(status_code=404, detail="Goal occurrence not found")
    return task


@router.post("/goals", response_model=GoalRead, status_code=201)
def create_goal(body: GoalCreate, session: Session = Depends(get_session)):
    try:
        goal = goals_svc.create_goal(session, body.model_dump())
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return goals_svc.goal_to_read(session, goal)


@router.patch("/goal-groups", response_model=list[GoalRead])
def rename_goal_group(body: GoalGroupUpdate, session: Session = Depends(get_session)):
    try:
        goals = goals_svc.set_goal_group(session, body.goal_ids, body.name)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return [goals_svc.goal_to_read(session, goal) for goal in goals]


@router.get("/goal-groups/{name}/customization", response_model=GoalGroupSettingsRead)
def get_group_customization(name: str, session: Session = Depends(get_session)):
    name = name.strip()
    settings = goals_svc.get_group_settings(session, name)
    return GoalGroupSettingsRead(name=name, icon=settings.icon if settings else None,
                                 color=settings.color if settings else None)


@router.put("/goal-groups/{name}/customization", response_model=GoalGroupSettingsRead)
def set_group_customization(name: str, body: GoalGroupSettingsUpdate, session: Session = Depends(get_session)):
    name = name.strip()
    try:
        settings = goals_svc.set_group_settings(session, name, body.icon, body.color)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return GoalGroupSettingsRead(name=name, icon=settings.icon if settings else None,
                                 color=settings.color if settings else None)


@router.post("/goal-groups/end", response_model=list[int])
def end_goal_group(body: GoalGroupEnd, session: Session = Depends(get_session)):
    try:
        return goals_svc.archive_goal_group(session, body.goal_ids)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@router.patch("/goals/{goal_id}", response_model=GoalRead)
def update_goal(goal_id: int, body: GoalUpdate, session: Session = Depends(get_session)):
    try:
        goal = goals_svc.update_goal(session, goal_id, body.model_dump(exclude_unset=True))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    if not goal:
        raise HTTPException(status_code=404, detail="Goal not found")
    return goals_svc.goal_to_read(session, goal)


@router.patch("/goals/{goal_id}/progress", response_model=GoalRead)
def set_goal_progress(goal_id: int, body: GoalProgressUpdate, session: Session = Depends(get_session)):
    goal = goals_svc.set_progress(session, goal_id, current=body.current, add=body.add)
    if not goal:
        raise HTTPException(status_code=404, detail="Goal not found")
    return goals_svc.goal_to_read(session, goal)


@router.post("/goals/{goal_id}/raise", response_model=GoalRead)
def raise_goal(goal_id: int, body: GoalRaise, session: Session = Depends(get_session)):
    try:
        goal = goals_svc.raise_goal(session, goal_id, body.target)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    if not goal:
        raise HTTPException(status_code=404, detail="Goal not found")
    return goals_svc.goal_to_read(session, goal)


@router.post("/goals/{goal_id}/reset", response_model=GoalRead)
def reset_goal(goal_id: int, session: Session = Depends(get_session)):
    goal = goals_svc.reset_streak(session, goal_id)
    if not goal:
        raise HTTPException(status_code=404, detail="Goal not found")
    return goals_svc.goal_to_read(session, goal)


@router.delete("/goals/{goal_id}", status_code=204)
def delete_goal(goal_id: int, session: Session = Depends(get_session)):
    if not goals_svc.archive_goal(session, goal_id):
        raise HTTPException(status_code=404, detail="Goal not found")
    return Response(status_code=204)
