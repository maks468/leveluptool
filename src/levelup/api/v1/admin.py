"""Destructive, tool-wide administrative actions -- currently just the
pipeline/CRM-workflow reset. Deliberately its own small router, separate
from the domain routers, since nothing here is a normal CRUD operation."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from levelup.api.v1.schemas import (
    AutoEnrichSettingsOut,
    AutoEnrichSettingsUpdate,
    ClearPipelineResultOut,
    ResetConfirmRequest,
    ResetResultOut,
)
from levelup.core.db import get_session
from levelup.models.admin import AutoEnrichSettings
from levelup.services.admin.reset import clear_pipeline, reset_pipeline_workflow

router = APIRouter(prefix="/admin", tags=["admin"])

REQUIRED_CONFIRMATION = "confirm"


@router.post("/reset-pipeline", response_model=ResetResultOut)
def reset_pipeline(body: ResetConfirmRequest, session: Session = Depends(get_session)):
    if body.confirmation.strip().lower() != REQUIRED_CONFIRMATION:
        raise HTTPException(400, f'Type "{REQUIRED_CONFIRMATION}" exactly to confirm this action.')
    counts = reset_pipeline_workflow(session)
    return ResetResultOut(**counts)


@router.post("/clear-pipeline", response_model=ClearPipelineResultOut)
def clear_pipeline_only(body: ResetConfirmRequest, session: Session = Depends(get_session)):
    """Empties the pipeline and its outreach history, keeping every
    enriched contact. Same typed confirmation as the full reset -- it's
    still irreversible, just far narrower."""
    if body.confirmation.strip().lower() != REQUIRED_CONFIRMATION:
        raise HTTPException(400, f'Type "{REQUIRED_CONFIRMATION}" exactly to confirm this action.')
    counts = clear_pipeline(session)
    return ClearPipelineResultOut(**counts)


def _get_or_create_settings(session: Session) -> AutoEnrichSettings:
    settings = session.query(AutoEnrichSettings).filter_by(id=1).one_or_none()
    if settings is None:
        settings = AutoEnrichSettings(id=1)
        session.add(settings)
        session.commit()
    return settings


@router.get("/auto-enrich-settings", response_model=AutoEnrichSettingsOut)
def get_auto_enrich_settings(session: Session = Depends(get_session)):
    return _get_or_create_settings(session)


@router.patch("/auto-enrich-settings", response_model=AutoEnrichSettingsOut)
def update_auto_enrich_settings(body: AutoEnrichSettingsUpdate, session: Session = Depends(get_session)):
    settings = _get_or_create_settings(session)
    if body.enabled is not None:
        settings.enabled = body.enabled
    if body.schools_per_run is not None:
        if body.schools_per_run < 1:
            raise HTTPException(400, "schools_per_run must be at least 1")
        settings.schools_per_run = body.schools_per_run
    if body.interval_minutes is not None:
        if body.interval_minutes < 1:
            raise HTTPException(400, "interval_minutes must be at least 1")
        settings.interval_minutes = body.interval_minutes
    session.commit()
    return settings
