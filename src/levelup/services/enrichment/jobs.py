"""Runs a batch enrichment job. A failed school never blocks or hides the
rest of the batch -- each item's status/error is tracked independently.
"""

from __future__ import annotations

from datetime import datetime, timezone

from levelup.core.db import SessionLocal
from levelup.models.enrichment import EnrichmentJob, EnrichmentJobItem, SchoolContact
from levelup.models.pipeline import ActivityType
from levelup.models.school import School
from levelup.services.enrichment.rspo_detail import fetch_rspo_detail, parse_director_and_contacts
from levelup.services.enrichment.scraper import scrape_school_website
from levelup.services.enrichment.verifier import (
    campaign_email_tier,
    classify_contact_quality,
    email_level_hint,
    is_non_school_email,
    is_personal_email_for,
)
from levelup.services.pipeline.activity import log_activity

RSPO_SOURCE_URL_PREFIX = "https://rspo.gov.pl/api/Institution/"


def _upsert_contact(
    session,
    *,
    school_id: int,
    contact_type: str,
    person_name: str | None,
    email: str | None,
    phone: str | None,
    source_url: str | None,
    job_id: int,
    quality: str,
) -> None:
    """Re-enriching the same school repeatedly (re-clicking "Enrich", or a
    bulk batch that happens to include an already-enriched school) used to
    insert a brand-new SchoolContact row every time, even when it was the
    exact same person found again -- a school could end up listing its own
    director five times. Matching on (school_id, contact_type, normalized
    name) tells "the same person, found again" apart from "a genuinely
    different person in the same role" (e.g. two distinct English
    teachers), updating the former in place and only inserting a new row
    for the latter."""
    normalized_name = person_name.strip().lower() if person_name else None
    existing = session.query(SchoolContact).filter_by(school_id=school_id, contact_type=contact_type).all()
    match = next(
        (c for c in existing if (c.person_name.strip().lower() if c.person_name else None) == normalized_name),
        None,
    )
    if match:
        match.person_name = person_name
        match.email = email
        match.phone = phone
        match.source_url = source_url
        match.enrichment_job_id = job_id
        match.contact_quality = quality
        match.captured_at = datetime.now(timezone.utc)
    else:
        session.add(
            SchoolContact(
                school_id=school_id,
                contact_type=contact_type,
                person_name=person_name,
                email=email,
                phone=phone,
                source_url=source_url,
                enrichment_job_id=job_id,
                contact_quality=quality,
            )
        )


def create_job(session, school_ids: list[int], requested_by: int, is_automatic: bool = False) -> EnrichmentJob:
    job = EnrichmentJob(requested_by=requested_by, status="pending", is_automatic=is_automatic)
    session.add(job)
    session.flush()
    for school_id in school_ids:
        session.add(EnrichmentJobItem(job_id=job.id, school_id=school_id, status="pending"))
    session.commit()
    return job


def run_job(job_id: int) -> None:
    """Runs synchronously against its own DB session -- intended to be
    invoked via FastAPI BackgroundTasks so the triggering request returns
    immediately."""
    session = SessionLocal()
    try:
        job = session.query(EnrichmentJob).filter_by(id=job_id).one()
        job.status = "running"
        session.commit()

        items = session.query(EnrichmentJobItem).filter_by(job_id=job_id).all()
        for item in items:
            item.status = "running"
            item.started_at = datetime.now(timezone.utc)
            session.commit()

            try:
                school = session.query(School).filter_by(id=item.school_id).one()

                # Retire any RODO/data-protection address a PREVIOUS run
                # stored before these were recognized as never-useful -- the
                # upsert below only ever overwrites or adds, never deletes,
                # so a school whose only old email was e.g.
                # "inspektor@coreconsulting.pl" would otherwise keep it
                # forever. Re-enriching should clean that up.
                for stale in session.query(SchoolContact).filter_by(school_id=school.id).all():
                    if is_non_school_email(stale.email):
                        session.delete(stale)

                # RSPO's own detail API is authoritative and official -- try it
                # FIRST, before any website scraping. It never has the English
                # teacher's name, so the website is still crawled regardless,
                # but a director name found here always wins over a scraped one.
                rspo_info: dict = {}
                if school.rspo_id:
                    detail = fetch_rspo_detail(school.rspo_id)
                    if detail:
                        rspo_info = parse_director_and_contacts(detail)

                # FLOOR, step 1 -- make sure there's a site to crawl at all.
                # RSPO records a website for nearly every school, so when our
                # stored URL is blank, crawl RSPO's instead (and backfill it
                # for next time) -- a "no website on file" school shouldn't
                # fall straight through to a dead search.
                effective_website = school.website_url or rspo_info.get("website")
                if not school.website_url and rspo_info.get("website"):
                    school.website_url = rspo_info.get("website")

                result = scrape_school_website(school.name, school.city, effective_website)

                # Special-education population(s) detected from the site and
                # the school's own name (e.g. "Special-needs school; Visual
                # impairment"). Only ever set when something was found -- a
                # run that turns up nothing never wipes a prior detection,
                # same "blank beats a guess" discipline as every other field.
                # Speciality is derived from the school's official NAME only
                # now (name-based is deterministic), so always reflect it --
                # including clearing a stale value that an earlier body-text
                # scan wrongly set (e.g. a false "Visual impairment" picked up
                # from a website accessibility declaration).
                specialties = result.get("specialties") or []
                school.specialty = "; ".join(specialties) if specialties else None

                # A discovered_website_url is only ever set from a URL the
                # crawler itself successfully fetched -- either the same
                # organization's site under a corrected hostname, or this
                # school's own dedicated subsite found via a shared hub
                # domain's own navigation. Well-grounded enough to correct
                # the stale/imprecise value RSPO's own registry had on file.
                discovered_url = result.get("discovered_website_url")
                website_url_corrected = None
                if discovered_url and discovered_url != school.website_url:
                    website_url_corrected = {"from": school.website_url, "to": discovered_url}
                    school.website_url = discovered_url

                director_name = rspo_info.get("director_name") or result.get("director_name")
                director_from_rspo = bool(rspo_info.get("director_name"))
                director_source_url = (
                    f"{RSPO_SOURCE_URL_PREFIX}{school.rspo_id}" if director_from_rspo else result.get("source_url")
                )
                teacher_name = result.get("english_teacher_name")
                phone = result.get("phone") or rspo_info.get("phone")

                # Every email ever seen (own site + RSPO's registry line),
                # deduped case-insensitively. Which one (if any) is a
                # SPECIFIC person's own address can only be judged now that
                # both names are final -- never assumed from the address
                # alone, and never attached to a person without that proof.
                # Non-school addresses -- a RODO/data-protection mailbox
                # (iod@, inspektor@) or a known outsourced compliance/IT/legal
                # vendor's domain (e.g. coreconsulting.pl, zontekiwspolnicy.pl)
                # -- are dropped here outright. They reach the vendor, never
                # the school, so they must not be attached to a person OR kept
                # as the general email; a blank beats that misleading a contact.
                seen_lower: set[str] = set()
                all_emails: list[str] = []
                for candidate in [*result.get("all_emails", []), rspo_info.get("email")]:
                    if (
                        candidate
                        and candidate.lower() not in seen_lower
                        and not is_non_school_email(candidate)
                    ):
                        seen_lower.add(candidate.lower())
                        all_emails.append(candidate)

                director_email = next((e for e in all_emails if is_personal_email_for(e, director_name)), None)
                teacher_email = next((e for e in all_emails if is_personal_email_for(e, teacher_name)), None)
                claimed = {e for e in (director_email, teacher_email) if e}
                unclaimed = [e for e in all_emails if e not in claimed]
                # On a shared domain that hosts several schools of one group,
                # an email whose section code names a DIFFERENT level than
                # this school (e.g. "sp@smsw.pl" while enriching the liceum)
                # is demoted below every non-level-specific address, so the
                # liceum lands on "sekretariat@smsw.pl" rather than the
                # primary school's box. A soft penalty, not a hard exclude:
                # if such a mismatched address is genuinely all that exists,
                # it's still better than nothing.
                school_level = school.level.value

                # FLOOR, step 2 -- the school's own email, the one field we
                # want on ~100% of schools. RSPO's official registered address
                # (almost always the sekretariat@/szkola@ box, present for
                # ~98% of schools) is the floor and the default -- but we then
                # compare it against every address scraped from the site and
                # keep whichever is best SUITED to an outreach campaign: a
                # monitored office/secretariat inbox beats an unlabelled
                # address beats a recruitment-only one (campaign_email_tier).
                # A shared-domain box for the wrong school level (sp@ for the
                # liceum) is demoted, and RSPO wins genuine ties as the
                # authoritative source. Personal addresses are already claimed
                # above, so this slot is always the general office contact.
                rspo_email = rspo_info.get("email")

                def _general_rank(email: str) -> tuple[int, int, int]:
                    hint = email_level_hint(email)
                    level_mismatch = 1 if (hint is not None and hint != school_level) else 0
                    rspo_tiebreak = 0 if email == rspo_email else 1
                    return (level_mismatch, campaign_email_tier(email), rspo_tiebreak)

                general_email = min(unclaimed, key=_general_rank) if unclaimed else None

                if director_name:
                    _upsert_contact(
                        session,
                        school_id=school.id,
                        contact_type="director",
                        person_name=director_name,
                        email=director_email,
                        phone=phone if director_email else None,
                        source_url=director_source_url,
                        job_id=job_id,
                        quality=classify_contact_quality(director_name, director_email),
                    )
                    school.director_name = director_name

                if teacher_name:
                    _upsert_contact(
                        session,
                        school_id=school.id,
                        contact_type="english_coordinator",
                        person_name=teacher_name,
                        email=teacher_email,
                        phone=phone if teacher_email else None,
                        source_url=result.get("source_url"),
                        job_id=job_id,
                        quality=classify_contact_quality(teacher_name, teacher_email),
                    )
                    school.english_teacher_name = teacher_name

                # FLOOR, step 3 -- record the general office contact whenever
                # there's EITHER an email or (from RSPO's registry) a phone.
                # A real email that isn't verified as a specific person's own
                # is kept here, nameless, never pinned to a name we can't back
                # up. Recording on phone-only too means even a school with no
                # scrapable email still yields a reachable contact.
                general_source = result.get("source_url") or (
                    f"{RSPO_SOURCE_URL_PREFIX}{school.rspo_id}" if rspo_info else None
                )
                if general_email or phone:
                    _upsert_contact(
                        session,
                        school_id=school.id,
                        contact_type="general",
                        person_name=None,
                        email=general_email,
                        phone=phone,
                        source_url=general_source,
                        job_id=job_id,
                        quality=classify_contact_quality(None, general_email),
                    )

                sources_checked = list(result.get("sources_checked", []))
                if school.rspo_id:
                    sources_checked.insert(
                        0,
                        {
                            "url": f"{RSPO_SOURCE_URL_PREFIX}{school.rspo_id}",
                            "status": "ok" if rspo_info else "unreachable",
                        },
                    )
                log_activity(
                    session,
                    school_id=school.id,
                    activity_type=ActivityType.ENRICHMENT_COMPLETED.value,
                    metadata={
                        "found_email": bool(general_email or director_email or teacher_email),
                        "found_phone": bool(phone),
                        "found_director_email": bool(director_email),
                        "found_teacher_email": bool(teacher_email),
                        "found_general_email": bool(general_email),
                        "found_director_name": bool(director_name),
                        "found_english_teacher_name": bool(teacher_name),
                        "director_source": "rspo_registry" if director_from_rspo else ("website" if result.get("director_name") else None),
                        "specialties_detected": specialties,
                        "js_rendered_site": bool(result.get("js_app_shell")),
                        "js_render_used": bool(result.get("js_render_used")),
                        "website_url_corrected": website_url_corrected,
                        "sources_checked": sources_checked,
                        "sources_checked_count": len(sources_checked),
                        "sources_ok_count": sum(1 for s in sources_checked if s["status"] == "ok"),
                    },
                )
                item.status = "success"
            except Exception as exc:  # noqa: BLE001 -- one school's failure must not sink the batch
                item.status = "failed"
                item.error_message = str(exc)

            item.finished_at = datetime.now(timezone.utc)
            session.commit()

        job.status = "done"
        session.commit()
    finally:
        session.close()
