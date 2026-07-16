"""Saved Views, Tags, and Global Search -- the Tier-1 CRM gaps identified
against Twenty CRM's data model (Views, multi-select tags) for a
25,000-school library that gets systematically worked through over time
rather than browsed as a handful of active deals."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import or_
from sqlalchemy.orm import Session

from levelup.api.v1.schemas import (
    BulkActionResult,
    BulkTagRequest,
    SavedViewCreate,
    SavedViewOut,
    SchoolSearchResultOut,
    TagCreate,
    TagOut,
)
from levelup.core.db import get_session
from levelup.core.security import get_current_user
from levelup.models.crm import SavedView, SchoolTag, Tag
from levelup.models.pipeline import PipelineState
from levelup.models.school import School
from levelup.models.score import CurrentScore, SchoolScore
from levelup.models.user import User

router = APIRouter(tags=["crm"])


# ---------------- Saved Views ----------------


@router.get("/saved-views", response_model=list[SavedViewOut])
def list_saved_views(
    session: Session = Depends(get_session), user: User = Depends(get_current_user), scope: str = "library"
):
    return (
        session.query(SavedView)
        .filter_by(owner_id=user.id, scope=scope)
        .order_by(SavedView.is_favorite.desc(), SavedView.updated_at.desc())
        .all()
    )


@router.post("/saved-views", response_model=SavedViewOut)
def create_saved_view(
    body: SavedViewCreate, session: Session = Depends(get_session), user: User = Depends(get_current_user)
):
    view = SavedView(
        owner_id=user.id,
        name=body.name,
        scope=body.scope,
        filters_json=body.filters_json,
        sort=body.sort,
        result_limit=body.result_limit,
    )
    session.add(view)
    session.commit()
    return view


@router.patch("/saved-views/{view_id}", response_model=SavedViewOut)
def update_saved_view(
    view_id: int,
    body: SavedViewCreate,
    session: Session = Depends(get_session),
    user: User = Depends(get_current_user),
):
    view = session.query(SavedView).filter_by(id=view_id, owner_id=user.id).one_or_none()
    if view is None:
        raise HTTPException(404, "Saved view not found")
    view.name = body.name
    view.filters_json = body.filters_json
    view.sort = body.sort
    view.result_limit = body.result_limit
    session.commit()
    return view


@router.patch("/saved-views/{view_id}/favorite", response_model=SavedViewOut)
def toggle_saved_view_favorite(
    view_id: int, session: Session = Depends(get_session), user: User = Depends(get_current_user)
):
    view = session.query(SavedView).filter_by(id=view_id, owner_id=user.id).one_or_none()
    if view is None:
        raise HTTPException(404, "Saved view not found")
    view.is_favorite = not view.is_favorite
    session.commit()
    return view


@router.delete("/saved-views/{view_id}", status_code=204)
def delete_saved_view(
    view_id: int, session: Session = Depends(get_session), user: User = Depends(get_current_user)
):
    view = session.query(SavedView).filter_by(id=view_id, owner_id=user.id).one_or_none()
    if view is None:
        raise HTTPException(404, "Saved view not found")
    session.delete(view)
    session.commit()


# ---------------- Tags ----------------


@router.get("/tags", response_model=list[TagOut])
def list_tags(session: Session = Depends(get_session)):
    return session.query(Tag).order_by(Tag.name).all()


@router.post("/tags", response_model=TagOut)
def create_tag(body: TagCreate, session: Session = Depends(get_session)):
    existing = session.query(Tag).filter_by(name=body.name).one_or_none()
    if existing:
        return existing
    tag = Tag(name=body.name, color=body.color)
    session.add(tag)
    session.commit()
    return tag


@router.delete("/tags/{tag_id}", status_code=204)
def delete_tag(tag_id: int, session: Session = Depends(get_session)):
    tag = session.query(Tag).filter_by(id=tag_id).one_or_none()
    if tag is None:
        raise HTTPException(404, "Tag not found")
    session.query(SchoolTag).filter_by(tag_id=tag_id).delete()
    session.delete(tag)
    session.commit()


@router.get("/schools/{school_id}/tags", response_model=list[TagOut])
def get_school_tags(school_id: int, session: Session = Depends(get_session)):
    return (
        session.query(Tag)
        .join(SchoolTag, SchoolTag.tag_id == Tag.id)
        .filter(SchoolTag.school_id == school_id)
        .order_by(Tag.name)
        .all()
    )


@router.put("/schools/{school_id}/tags/{tag_id}", status_code=204)
def add_school_tag(school_id: int, tag_id: int, session: Session = Depends(get_session)):
    existing = session.query(SchoolTag).filter_by(school_id=school_id, tag_id=tag_id).one_or_none()
    if not existing:
        session.add(SchoolTag(school_id=school_id, tag_id=tag_id))
        session.commit()


@router.delete("/schools/{school_id}/tags/{tag_id}", status_code=204)
def remove_school_tag(school_id: int, tag_id: int, session: Session = Depends(get_session)):
    session.query(SchoolTag).filter_by(school_id=school_id, tag_id=tag_id).delete()
    session.commit()


@router.put("/tags/{tag_id}/bulk", response_model=BulkActionResult)
def bulk_add_school_tag(tag_id: int, body: BulkTagRequest, session: Session = Depends(get_session)):
    tag = session.query(Tag).filter_by(id=tag_id).one_or_none()
    if tag is None:
        raise HTTPException(404, "Tag not found")
    already = {
        row.school_id
        for row in session.query(SchoolTag.school_id)
        .filter(SchoolTag.tag_id == tag_id, SchoolTag.school_id.in_(body.school_ids))
        .all()
    }
    updated = 0
    for school_id in body.school_ids:
        if school_id in already:
            continue
        session.add(SchoolTag(school_id=school_id, tag_id=tag_id))
        updated += 1
    session.commit()
    return BulkActionResult(updated=updated)


# ---------------- Global search ----------------
# With 25k+ records, there was previously no way to just type a school's
# name and jump to it -- only structured dropdown filters. Matches on name
# or city, ranked by score so the most promising match surfaces first.


@router.get("/search", response_model=list[SchoolSearchResultOut])
def search_schools(q: str, session: Session = Depends(get_session)):
    q = q.strip()
    if len(q) < 2:
        return []
    like = f"%{q}%"
    rows = (
        session.query(School, PipelineState, SchoolScore)
        .outerjoin(PipelineState, PipelineState.school_id == School.id)
        .outerjoin(CurrentScore, CurrentScore.school_id == School.id)
        .outerjoin(SchoolScore, SchoolScore.id == CurrentScore.score_id)
        .filter(School.is_active.is_(True), or_(School.name.ilike(like), School.city.ilike(like)))
        .order_by(SchoolScore.total_score.desc().nulls_last())
        .limit(20)
        .all()
    )
    return [
        SchoolSearchResultOut(
            id=school.id,
            name=school.name,
            city=school.city,
            voivodeship=school.voivodeship,
            level=school.level.value,
            score=score.total_score if score else None,
            in_pipeline=pipeline_state is not None,
        )
        for school, pipeline_state, score in rows
    ]
