"""Stub auth. Every route resolves the current user through this single
function -- when real auth arrives, only this function changes."""

from fastapi import Depends
from sqlalchemy.orm import Session

from levelup.core.config import settings
from levelup.core.db import get_session
from levelup.models.user import User


def get_current_user(session: Session = Depends(get_session)) -> User:
    return session.query(User).filter_by(id=settings.default_owner_id).one()
