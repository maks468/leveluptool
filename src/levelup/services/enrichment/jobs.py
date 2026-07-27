"""Runs a batch enrichment job. A failed school never blocks or hides the
rest of the batch -- each item's status/error is tracked independently.
"""

from __future__ import annotations

import os
from datetime import datetime, timezone

from levelup.core.db import SessionLocal
from levelup.models.enrichment import EnrichmentJob, EnrichmentJobItem, SchoolContact
from levelup.models.pipeline import ActivityType, PipelineState, PipelineStage
from levelup.models.school import EvidenceSource, School
from levelup.services.enrichment import llm_extract
from levelup.services.enrichment.rspo_detail import fetch_rspo_detail, parse_director_and_contacts
from levelup.services.enrichment.scraper import (
    augment_with_web_search,
    download_for_vision,
    finalize_scrape_result,
    scrape_school_website,
)
from levelup.services.enrichment.verifier import (
    campaign_email_tier,
    classify_contact_quality,
    email_level_hint,
    is_non_school_email,
    is_personal_email_for,
)
from levelup.services.pipeline.activity import log_activity
from levelup.services.pipeline.stages import change_stage

RSPO_SOURCE_URL_PREFIX = "https://rspo.gov.pl/api/Institution/"

_CONFIDENCE_RANK = {"high": 0, "medium": 1, "low": 2}


def _pick_best_staff(staff: list, roles: tuple[str, ...], url_to_tier: dict[str, int]):
    """Highest confidence wins per role; ties broken by staff-tier source
    first (a lower crawl tier == reached via a higher-priority keyword,
    e.g. a dedicated "kadra" page beats an incidental homepage mention).
    `roles` is given in preference order (e.g. director before
    deputy_director) and used as the first sort key so a lower-ranked role
    never wins over a present higher-ranked one regardless of confidence."""
    candidates = [s for s in staff if s.role in roles]
    if not candidates:
        return None
    role_rank = {role: i for i, role in enumerate(roles)}
    return min(
        candidates,
        key=lambda s: (role_rank[s.role], _CONFIDENCE_RANK.get(s.confidence, 9), url_to_tier.get(s.source_url, 99)),
    )


def _resolve_email(record, all_emails: list[str], name: str | None) -> str | None:
    """Email attribution priority: (1) the LLM's own pairing on `record`,
    once it has survived grounding validation (ground_extraction/
    ground_vision_extraction already stripped anything not verifiably
    tied to this specific person); (2) the existing structural match
    (is_personal_email_for) over every email the crawl ever saw. LLM
    pairing is trusted first since it can use context the structural
    matcher can't (e.g. disambiguating which of two same-surname
    candidates a table row's email actually belongs to)."""
    if record is not None and record.email:
        return record.email
    return next((e for e in all_emails if is_personal_email_for(e, name)), None)


def _run_llm_extraction(result: dict, school: School, still_needed_roles: set[str]):
    """Runs the LLM extraction call(s) for one school: one routine (Haiku)
    call; if that comes back unparseable, one same-tier retry (matching
    the task's "unparseable output twice" escalation trigger); then at
    most one escalation to Opus when llm_extract.needs_escalation says
    the result still looks insufficient. Matches the per-school budget of
    "1 call typical, hard ceiling" from the task spec.

    Returns (grounded SchoolExtraction or None, stats dict). None means
    the LLM path is unavailable or produced nothing usable for this
    school -- the caller falls back to regex. UsageLimitError propagates
    UNCAUGHT: run_job must stop the whole batch cleanly on it, not just
    mark this one school failed (see llm_extract.UsageLimitError)."""
    stats = {"llm_calls": 0, "llm_input_tokens": 0, "llm_output_tokens": 0, "vision_calls": 0, "escalations": 0}
    if not llm_extract.is_llm_usable():
        # Checked (and cached) BEFORE attempting any real call, not just
        # after one fails -- confirmed directly: a container with no
        # working Claude Code credentials still let a real SDK call
        # proceed, which failed with authentication_failed but sometimes
        # left an async generator in a state that never closed (a leaked
        # subprocess per attempt), and one enrichment job was later found
        # hung for 3+ hours on exactly this. Once we know the CLI can't
        # work in this process, never try it again.
        return None, stats

    raw_pages = result.get("llm_pages") or []
    pages = llm_extract.cap_pages(
        [
            llm_extract.PreparedPage(url=p["url"], text=p["text"], tier=p["tier"], third_party=p["third_party"])
            for p in raw_pages
        ]
    )
    if not pages:
        return None, stats
    pages_by_url = {p.url: p.text for p in pages}

    def _call(model: str):
        usage: dict = {}
        extraction = llm_extract.extract_contacts(pages, school.name, school.city, model=model, usage_out=usage)
        stats["llm_calls"] += 1
        stats["llm_input_tokens"] += usage.get("input_tokens", 0)
        stats["llm_output_tokens"] += usage.get("output_tokens", 0)
        return extraction

    try:
        extraction = _call(llm_extract.HAIKU_MODEL)
        if extraction is None:
            extraction = _call(llm_extract.HAIKU_MODEL)  # one same-tier retry before "unparseable twice" counts
    except llm_extract.CliUnavailableError:
        # The CLI was reachable at startup (SDK_AVAILABLE) but failed for
        # THIS call (not logged in, crashed, etc.) -- treated the same as
        # "unavailable", falling back to regex for this school rather than
        # failing the whole item.
        return None, stats

    if extraction is not None:
        extraction = llm_extract.ground_extraction(extraction, pages_by_url, school.name)

    if llm_extract.needs_escalation(extraction, pages, still_needed_roles):
        try:
            escalated = _call(llm_extract.OPUS_MODEL)
            stats["escalations"] += 1
        except llm_extract.CliUnavailableError:
            # Escalation specifically couldn't connect -- keep whatever the
            # routine call already produced rather than discarding it too.
            escalated = None
        if escalated is not None:
            extraction = llm_extract.ground_extraction(escalated, pages_by_url, school.name)

    return extraction, stats


def _run_vision_extraction(extraction, school: School, still_needed_roles: set[str], stats: dict):
    """At most 3 vision calls (Opus), and only while a role this school
    still lacks remains missing after the text extraction above -- a
    staff roster published only as an image or scanned PDF is otherwise
    invisible to every text-based path (regex and LLM-text alike). Mutates
    `stats` in place (vision_calls/token counts) and returns the extraction
    with any newly-found, grounded staff appended."""
    if extraction is None or not still_needed_roles:
        return extraction
    candidate_urls = list(extraction.staff_roster_image_or_pdf_urls)[: llm_extract.MAX_VISION_CALLS_PER_SCHOOL]
    if not candidate_urls:
        return extraction

    website_domain = None
    if school.website_url:
        from urllib.parse import urlparse

        netloc = urlparse(school.website_url).netloc.lower()
        website_domain = netloc[4:] if netloc.startswith("www.") else netloc

    for url in candidate_urls:
        if not still_needed_roles:
            break
        path = download_for_vision(url)
        if path is None:
            continue
        usage: dict = {}
        try:
            reader = llm_extract.extract_from_pdf if path.lower().endswith(".pdf") else llm_extract.extract_from_image
            vision_result = reader(path, url, school.name, school.city, usage_out=usage)
        except llm_extract.CliUnavailableError:
            # Couldn't connect for THIS call -- every further vision
            # attempt this school would fail identically, so stop trying
            # rather than retrying per-URL. UsageLimitError deliberately
            # propagates uncaught (must stop the whole batch, not just
            # vision).
            break
        finally:
            try:
                os.remove(path)
            except OSError:
                pass
        stats["vision_calls"] += 1
        stats["llm_input_tokens"] += usage.get("input_tokens", 0)
        stats["llm_output_tokens"] += usage.get("output_tokens", 0)
        if vision_result is None:
            continue
        vision_result = llm_extract.ground_vision_extraction(vision_result, school_website_domain=website_domain)
        for record in vision_result.staff:
            if record.role in still_needed_roles:
                extraction.staff.append(record)
                still_needed_roles.discard(record.role)

    return extraction


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
    confidence: str | None = None,
    evidence: str | None = None,
    extraction_method: str | None = None,
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
        match.confidence = confidence
        match.evidence = evidence
        match.extraction_method = extraction_method
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
                confidence=confidence,
                evidence=evidence,
                extraction_method=extraction_method,
            )
        )


def _would_be_enriched(director_name: str | None, teacher_name: str | None, result: dict, rspo_info: dict) -> bool:
    """True when RSPO's own registry plus the school's own website crawl
    already leave this school better than "not_enriched" (see
    schools.py's _compute_enrichment_levels), so a web search would be
    pure waste. Mirrors that function's own conditions exactly:
    - "partial"/"successful" both require the English teacher's name --
      already covered by the `teacher_name` check alone.
    - "basic" requires the director's name AND some school email on
      file -- checked here against the same non-school-email filter
      (RODO/vendor addresses) the real contact-building step below
      applies, so a discarded address can't be mistaken for a real one.
    - A priority (personal-verified) email on the director implies both
      a name AND an email are present, which the checks above already
      require -- there's no path to "successful" this function would miss.
    Deliberately conservative: search only ever runs when this is False,
    i.e. only as an actual last resort, never as a first attempt and
    never just to fill in one remaining field on an already-useful entry."""
    if teacher_name:
        return True
    if not director_name:
        return False
    candidates = [*result.get("all_emails", []), rspo_info.get("email")]
    return any(c and not is_non_school_email(c) for c in candidates)


def reap_orphaned_jobs(session) -> int:
    """Call once, at process startup. run_job executes as a FastAPI
    BackgroundTask -- in-process only, so it does NOT survive a redeploy,
    a crash, or a manual container restart. A job/item still marked
    pending/running from a PREVIOUS process is therefore guaranteed
    orphaned: there is no live loop left anywhere that could ever move it
    forward, and (confirmed directly, after this exact scenario happened
    from restarting mid-run while building this feature) it would
    otherwise sit "running" forever -- including forever blocking the
    Stop button's own "Stopping..." indicator, since that reads job
    status too. Swept into "cancelled" the same terminal state an
    explicit Stop produces, since from the schools' point of view it's
    the same outcome: some were finished, the rest weren't reached."""
    stuck_jobs = session.query(EnrichmentJob).filter(EnrichmentJob.status.in_(["pending", "running"])).all()
    if not stuck_jobs:
        return 0
    stuck_job_ids = [j.id for j in stuck_jobs]
    for job in stuck_jobs:
        job.status = "cancelled"
        job.cancel_requested = True
    stuck_items = (
        session.query(EnrichmentJobItem)
        .filter(EnrichmentJobItem.job_id.in_(stuck_job_ids))
        .filter(EnrichmentJobItem.status.in_(["pending", "running"]))
        .all()
    )
    for item in stuck_items:
        item.status = "cancelled"
        item.finished_at = item.finished_at or datetime.now(timezone.utc)
    session.commit()
    return len(stuck_jobs)


def create_job(session, school_ids: list[int], requested_by: int, is_automatic: bool = False) -> EnrichmentJob:
    job = EnrichmentJob(requested_by=requested_by, status="pending", is_automatic=is_automatic)
    session.add(job)
    session.flush()
    for school_id in school_ids:
        session.add(EnrichmentJobItem(job_id=job.id, school_id=school_id, status="pending"))
    session.commit()
    return job


def enrich_school(session, school: School, *, job_id: int | None, requested_by: int | None) -> dict:
    """The complete per-school enrichment logic: RSPO lookup, crawl, last-
    resort search, contact merge/upsert, activity logging. Extracted out of
    run_job's loop (which now just calls this once per item) so the SAME
    exact production logic is also reachable for a dry run -- see
    enrich_school_dry_run below -- without a second, drift-prone
    reimplementation living in an eval script.

    Returns a plain dict summarizing what happened (director_name,
    teacher_name, emails, specialties, website_url_corrected, sources_checked,
    js flags, and -- for the liquidated-school short-circuit --
    school_closed/liquidation_date) so a caller can inspect the outcome
    without re-querying. All mutations land on the SQLAlchemy objects
    passed in; the caller decides whether to commit or roll back."""
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
    detail = None
    if school.rspo_id:
        detail = fetch_rspo_detail(school.rspo_id)
        if detail:
            rspo_info = parse_director_and_contacts(detail)

    # RSPO's own registry is the authoritative record of whether
    # an institution still operates at all -- confirmed
    # directly: a school re-registered under a NEW rspo_id kept
    # its OLD registration imported and marked active, showing
    # up in the Library/Pipeline as a seemingly-blank duplicate
    # of the real, live school (same name/city/address, zero
    # contacts, no website). There's no site worth crawling for
    # something RSPO itself has recorded as closed.
    if detail and detail.get("liquidationDate"):
        school.is_active = False
        # is_active alone only hides it from the Library --
        # the Pipeline listing deliberately never filters by
        # is_active (an already-pulled entry is meant to stay
        # visible until YOU move it, not vanish silently), so a
        # school already pulled in before this was detected
        # would otherwise sit there forever showing blank
        # contact info with no indication why. Moving it to
        # Lost is the same "closed, nothing more to pursue"
        # signal a human would give it by hand. Skipped if
        # already Lost/Won so re-enrichment doesn't spam the
        # activity log with a no-op stage change every time.
        pipeline_state = session.query(PipelineState).filter_by(school_id=school.id).one_or_none()
        if pipeline_state and pipeline_state.stage not in (PipelineStage.WON, PipelineStage.LOST):
            change_stage(session, school.id, PipelineStage.LOST, actor_id=requested_by)
        log_activity(
            session,
            school_id=school.id,
            activity_type=ActivityType.ENRICHMENT_COMPLETED.value,
            metadata={"school_closed": True, "liquidation_date": detail.get("liquidationDate")},
        )
        return {"school_closed": True, "liquidation_date": detail.get("liquidationDate")}

    # FLOOR, step 1 -- make sure there's a site to crawl at all.
    # RSPO records a website for nearly every school, so when our
    # stored URL is blank, crawl RSPO's instead (and backfill it
    # for next time) -- a "no website on file" school shouldn't
    # fall straight through to a dead search.
    effective_website = school.website_url or rspo_info.get("website")
    if not school.website_url and rspo_info.get("website"):
        school.website_url = rspo_info.get("website")

    result = scrape_school_website(school.name, effective_website, rspo_email=rspo_info.get("email"))

    # Special-education population(s) detected from the site,
    # the school's own name, AND RSPO's own authoritative
    # "specificity" field (see rspo_detail.py) -- a school run
    # inside a healthcare or rehabilitation facility routinely
    # carries NO naming hint at all ("PUBLICZNA SZKOŁA
    # PODSTAWOWA PRZY ZAKŁADACH OPIEKI ZDROWOTNEJ" has no
    # "specjalna", no disability keyword, nothing the
    # name-pattern regex alone can catch), while RSPO's own
    # registry still classifies it "specjalna" directly --
    # confirmed directly against real schools a user found
    # were never tagged despite being genuinely dedicated
    # special-needs institutions. Only ever set when something
    # was found -- a run that turns up nothing never wipes a
    # prior detection, same "blank beats a guess" discipline
    # as every other field. Sorted here (rather than waiting
    # for finalize_scrape_result below) since it's already
    # final either way -- a web search never adds to
    # specialties, only to director/teacher/email fields.
    specialties = set(result.get("specialties") or [])
    if rspo_info.get("is_dedicated_special_needs"):
        specialties.add("Special-needs school")
    specialties = sorted(specialties)
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
        school.website_url_source = EvidenceSource.ENRICHMENT

    director_name = rspo_info.get("director_name") or result.get("director_name")

    # LAST RESORT -- a web search only ever runs once RSPO's own
    # registry plus the full website crawl above still leave this
    # school no better than "not_enriched" (see
    # _would_be_enriched). A school that already has enough to be
    # "basic"/"partial"/"successful" never triggers a single
    # search request, even if one specific field (say, the
    # English teacher) is still missing -- confirmed this is
    # what was wanted: search is for genuinely stuck schools,
    # not a way to top up an already-useful entry.
    if not _would_be_enriched(director_name, result.get("english_teacher_name"), result, rspo_info):
        augment_with_web_search(school.name, school.city, result, rspo_id=school.rspo_id)
        director_name = rspo_info.get("director_name") or result.get("director_name")

    finalize_scrape_result(result)

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
        if candidate and candidate.lower() not in seen_lower and not is_non_school_email(candidate):
            seen_lower.add(candidate.lower())
            all_emails.append(candidate)

    # --- LLM extraction: the authoritative source of truth for director/
    # teacher names and email pairing when available (see llm_extract.py)
    # -- runs exactly ONCE here, after the crawl and any web search above,
    # never per-page. Regex's own result.get(...) values (already computed
    # into `result` by scrape_school_website/augment_with_web_search) are
    # used ONLY as the fallback when the LLM path is unavailable for this
    # school entirely (CLI missing/logged out, or every call failed) --
    # nothing regex found is stored otherwise.
    still_needed_roles: set[str] = set()
    if not rspo_info.get("director_name") and not result.get("director_name"):
        still_needed_roles.add("director")
    if not result.get("english_teacher_name"):
        still_needed_roles.add("english_teacher")

    llm_extraction, llm_stats = _run_llm_extraction(result, school, still_needed_roles)
    llm_extraction = _run_vision_extraction(llm_extraction, school, still_needed_roles, llm_stats)

    llm_pages = result.get("llm_pages") or []
    pages_by_url = {p["url"]: p["text"] for p in llm_pages}
    url_to_tier = {p["url"]: p["tier"] for p in llm_pages}
    director_record = teacher_record = None
    if llm_extraction is not None:
        director_record = _pick_best_staff(llm_extraction.staff, ("director", "deputy_director"), url_to_tier)
        teacher_record = _pick_best_staff(llm_extraction.staff, ("english_teacher",), url_to_tier)

    using_llm = llm_extraction is not None
    scraped_director_name = director_record.name if director_record else (None if using_llm else result.get("director_name"))
    teacher_name = teacher_record.name if teacher_record else (None if using_llm else result.get("english_teacher_name"))

    director_from_rspo = bool(rspo_info.get("director_name"))
    director_name = rspo_info.get("director_name") or scraped_director_name

    if director_from_rspo:
        director_extraction_method, director_confidence, director_evidence = "rspo", None, None
        director_source_url = f"{RSPO_SOURCE_URL_PREFIX}{school.rspo_id}"
    elif director_record:
        director_extraction_method = "llm_text" if director_record.source_url in pages_by_url else "llm_vision"
        director_confidence, director_evidence = director_record.confidence, director_record.evidence
        director_source_url = director_record.source_url
    elif scraped_director_name:
        director_extraction_method, director_confidence, director_evidence = "regex", None, None
        director_source_url = result.get("source_url")
    else:
        director_extraction_method = director_confidence = director_evidence = director_source_url = None

    if teacher_record:
        teacher_extraction_method = "llm_text" if teacher_record.source_url in pages_by_url else "llm_vision"
        teacher_confidence, teacher_evidence = teacher_record.confidence, teacher_record.evidence
        teacher_source_url = teacher_record.source_url
    elif teacher_name:
        teacher_extraction_method, teacher_confidence, teacher_evidence = "regex", None, None
        teacher_source_url = result.get("source_url")
    else:
        teacher_extraction_method = teacher_confidence = teacher_evidence = teacher_source_url = None

    director_email = _resolve_email(director_record, all_emails, director_name)
    teacher_email = _resolve_email(teacher_record, all_emails, teacher_name)
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
            confidence=director_confidence,
            evidence=director_evidence,
            extraction_method=director_extraction_method,
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
            source_url=teacher_source_url,
            job_id=job_id,
            quality=classify_contact_quality(teacher_name, teacher_email),
            confidence=teacher_confidence,
            evidence=teacher_evidence,
            extraction_method=teacher_extraction_method,
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
    metadata = {
        "found_email": bool(general_email or director_email or teacher_email),
        "found_phone": bool(phone),
        "found_director_email": bool(director_email),
        "found_teacher_email": bool(teacher_email),
        "found_general_email": bool(general_email),
        "found_director_name": bool(director_name),
        "found_english_teacher_name": bool(teacher_name),
        "director_source": director_extraction_method,
        "teacher_source": teacher_extraction_method,
        "director_confidence": director_confidence,
        "teacher_confidence": teacher_confidence,
        "specialties_detected": specialties,
        "js_rendered_site": bool(result.get("js_app_shell")),
        "js_render_used": bool(result.get("js_render_used")),
        "website_url_corrected": website_url_corrected,
        "sources_checked": sources_checked,
        "sources_checked_count": len(sources_checked),
        "sources_ok_count": sum(1 for s in sources_checked if s["status"] == "ok"),
        **llm_stats,
    }
    log_activity(session, school_id=school.id, activity_type=ActivityType.ENRICHMENT_COMPLETED.value, metadata=metadata)
    return {
        "director_name": director_name,
        "teacher_name": teacher_name,
        "director_email": director_email,
        "teacher_email": teacher_email,
        "general_email": general_email,
        "phone": phone,
        "website_url": school.website_url,
        **metadata,
    }


def enrich_school_dry_run(session, school: School) -> dict:
    """Runs the exact same production logic as a real enrichment job
    (enrich_school), for the eval harness -- but rolls back every DB
    mutation at the end instead of committing, so repeatedly re-running
    the eval against the 12 regression cases (or any other school) never
    perturbs real data. Deliberately a thin wrapper, not a parallel
    reimplementation: the eval must observe exactly what production would
    do, or a bug fixed here could silently not exist there."""
    try:
        return enrich_school(session, school, job_id=None, requested_by=None)
    finally:
        session.rollback()


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
        cancelled = False
        usage_limit_message: str | None = None
        for item in items:
            # Checked fresh before every school (not just once at the top of
            # run_job) -- the Stop button commits cancel_requested from a
            # SEPARATE request/session while this loop is mid-run, so this
            # session's own in-memory `job` needs an explicit refresh to see
            # it. The school currently mid-scrape always finishes rather
            # than being killed outright; everything still "pending" is
            # skipped instead of started.
            session.refresh(job)
            if job.cancel_requested:
                cancelled = True
                break

            item.status = "running"
            item.started_at = datetime.now(timezone.utc)
            session.commit()

            try:
                school = session.query(School).filter_by(id=item.school_id).one()
                enrich_school(session, school, job_id=job_id, requested_by=job.requested_by)
                item.status = "success"
            except llm_extract.UsageLimitError as exc:
                # The shared 5-hour Claude Code usage window is exhausted --
                # this is NOT this school's failure, it's every remaining
                # school's too. Reverting to "cancelled" (never "failed")
                # keeps this school eligible for the next auto-enrich cycle
                # (see auto_enrich._select_candidate_school_ids, which only
                # excludes success/failed items) instead of being treated
                # as a dead end. The whole job stops here, cleanly, rather
                # than burning through the rest of the batch one rejected
                # call at a time.
                item.status = "cancelled"
                if exc.resets_at:
                    resets_at_str = datetime.fromtimestamp(exc.resets_at, tz=timezone.utc).strftime(
                        "%Y-%m-%d %H:%M UTC"
                    )
                    usage_limit_message = f"Claude usage window ({exc.rate_limit_type}) exhausted -- resets at {resets_at_str}"
                else:
                    usage_limit_message = f"Claude usage window exhausted: {exc}"
                item.error_message = usage_limit_message
                item.finished_at = datetime.now(timezone.utc)
                session.commit()
                cancelled = True
                break
            except Exception as exc:  # noqa: BLE001 -- one school's failure must not sink the batch
                item.status = "failed"
                item.error_message = str(exc)

            item.finished_at = datetime.now(timezone.utc)
            session.commit()

        if cancelled:
            # Only "pending" items are stopped short -- one already marked
            # "running" above always runs to completion first, so no
            # half-written school data is ever left behind by a Stop click
            # or a usage-limit stop alike.
            for item in items:
                if item.status == "pending":
                    item.status = "cancelled"
            job.status = "cancelled"
            job.error_message = usage_limit_message
        else:
            job.status = "done"
        session.commit()
    finally:
        session.close()


def cancel_job(session, job_id: int) -> EnrichmentJob:
    """Flags a running/pending job to stop before its next school -- the
    background run_job loop (a separate DB session, since it runs via
    FastAPI BackgroundTasks) checks this flag itself and reacts. A job
    that's already done/cancelled is left alone rather than erroring, so
    a double-click or a stale tray never surfaces a confusing failure."""
    job = session.query(EnrichmentJob).filter_by(id=job_id).one()
    if job.status in ("pending", "running"):
        job.cancel_requested = True
        session.commit()
    return job
