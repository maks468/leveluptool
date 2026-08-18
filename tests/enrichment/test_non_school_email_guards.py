"""Two real leaks the user caught in production exports, pinned forever.

1. SP 190: "rzarzeczna.iod@dbfomokotow.pl" -- a named data-protection
   officer at the DISTRICT bureau -- was stored as the school's contact
   because the RODO check only looked at the local part's PREFIX. An
   address that reaches anyone other than the school must never be kept:
   blank beats a misleading contact.

2. SP 350: "EMiecznikowska@eduwarszawa.pl" -- the director's own address
   in the very common concatenated initial+surname format -- could never
   be attributed to her because structural verification demanded
   separator-split tokens, so the school graded partial with the priority
   email already in hand.
"""

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

import levelup.models  # noqa: F401 -- registers every table on Base.metadata
from levelup.core.db import Base
from levelup.models.enrichment import SchoolContact
from levelup.models.school import School, SchoolLevel
from levelup.models.user import User
from levelup.services.enrichment.jobs import _upsert_contact
from levelup.services.enrichment.verifier import (
    classify_contact_quality,
    is_data_protection_email,
    is_non_school_email,
    is_personal_email_for,
)


def test_data_protection_marker_is_caught_in_any_token_position():
    # The exact leaked address: marker at the END.
    assert is_data_protection_email("rzarzeczna.iod@dbfomokotow.pl")
    assert is_non_school_email("rzarzeczna.iod@dbfomokotow.pl")
    # Other positions and separators.
    assert is_data_protection_email("iod.kowalski@szkola.pl")
    assert is_data_protection_email("jan-rodo@szkola.pl")
    assert is_data_protection_email("dane.osobowe@szkola.pl")  # prefix path still works


def test_marker_inside_a_surname_is_not_a_marker():
    # Token EQUALITY, not substring -- surnames merely containing the
    # letters must survive.
    assert not is_data_protection_email("j.miodek@szkola.pl")      # "iod" inside "miodek"
    assert not is_data_protection_email("anna.zabini@szkola.pl")   # "abi" inside "zabini"
    assert not is_data_protection_email("sekretariat@szkola.pl")


def test_concatenated_initial_plus_surname_is_personal():
    # The exact SP 350 shape.
    assert is_personal_email_for("EMiecznikowska@eduwarszawa.pl", "Ewa Miecznikowska")
    assert is_personal_email_for("annakowalska@szkola.pl", "Anna Kowalska")
    assert is_personal_email_for("kowalskaa@szkola.pl", "Anna Kowalska")  # surname+initial
    assert classify_contact_quality("Ewa Miecznikowska", "EMiecznikowska@eduwarszawa.pl") == "verified"


def test_retiring_a_condemned_contact_must_not_eat_its_replacement():
    """The SP 190 second-order failure: with autoflush off, deleting the
    condemned row and upserting its replacement into the same slot in one
    session made the upsert 'update' the doomed row -- the commit then ran
    the delete last and destroyed the fresh contact. The production path
    now flushes between retire and upsert; this reproduces the exact
    sequence and pins the surviving row."""
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)()
    session.add(User(id=1, display_name="Owner", email=None))
    session.add(School(id=1, rspo_id="1", name="SP 190", level=SchoolLevel.PRIMARY, raw_import_row={}))
    session.add(SchoolContact(school_id=1, contact_type="general", email="rzarzeczna.iod@dbfomokotow.pl"))
    session.commit()

    # The production sequence: retire (delete) ...
    for stale in session.query(SchoolContact).filter_by(school_id=1).all():
        if is_non_school_email(stale.email):
            session.delete(stale)
    session.flush()  # ... the fix under test ...
    # ... then upsert the replacement into the same slot.
    _upsert_contact(
        session, school_id=1, contact_type="general", person_name=None,
        email="sp190@eduwarszawa.pl", phone=None, source_url="http://www.sp190.waw.pl",
        job_id=None, quality="failed",
    )
    session.commit()

    rows = session.query(SchoolContact).filter_by(school_id=1, contact_type="general").all()
    assert [r.email for r in rows] == ["sp190@eduwarszawa.pl"]


def test_concatenated_form_still_rejects_everyone_else():
    # The same address must NOT verify for a different person...
    assert not is_personal_email_for("EMiecznikowska@eduwarszawa.pl", "Małgorzata Martynowicz")
    # ...an institutional word never matches (the original ATUT lesson)...
    assert not is_personal_email_for("atut@fem.org.pl", "Anna Tutko")
    # ...and a short surname can't produce accidental matches.
    assert not is_personal_email_for("abak@szkola.pl", "Adam Bak")
