"""Runs a batch enrichment job. A failed school never blocks or hides the
rest of the batch -- each item's status/error is tracked independently.
"""

from __future__ import annotations

import re
import time
from datetime import datetime, timezone

from sqlalchemy.exc import OperationalError

from levelup.core.db import SessionLocal
from levelup.models.enrichment import EnrichmentJob, EnrichmentJobItem, SchoolContact
from levelup.models.pipeline import ActivityType, PipelineState, PipelineStage
from levelup.models.school import EvidenceSource, School
from levelup.services.enrichment import llm_extract
from levelup.services.enrichment.rspo_detail import fetch_rspo_detail, parse_director_and_contacts
from levelup.services.enrichment.scraper import (
    _COMMON_POLISH_FIRST_NAMES,
    _mentions_school_city,
    _normalize_name_order,
    finalize_scrape_result,
    scrape_school_website,
)
from levelup.services.enrichment.verifier import (
    GENERIC_OFFICE_LOCAL_PARTS,
    campaign_email_tier,
    email_priority,
    classify_contact_quality,
    email_level_hint,
    is_deliverable_shape,
    is_non_school_email,
    is_personal_email_for,
)
from levelup.services.pipeline.activity import log_activity
from levelup.services.pipeline.stages import change_stage

RSPO_SOURCE_URL_PREFIX = "https://rspo.gov.pl/api/Institution/"

_CONFIDENCE_RANK = {"high": 0, "medium": 1, "low": 2}

# Roster image/PDF links are lifted straight out of the prepared page text
# (scraper._prepare_page_for_llm already appends an IMAGE_OR_PDF_LINKS
# footer). The model used to be asked for these, which meant paying output
# tokens for a list nothing extracts from -- vision extraction was removed
# under the accuracy policy, so they exist purely as a "worth a human
# look" hint.
_MEDIA_URL_RE = re.compile(r"https?://\S+")


def _roster_media_urls(llm_pages: list[dict], limit: int = 10) -> list[str]:
    urls: list[str] = []
    for page in llm_pages:
        _, marker, tail = (page.get("text") or "").partition("IMAGE_OR_PDF_LINKS:")
        if marker:
            urls.extend(_MEDIA_URL_RE.findall(tail))
    return list(dict.fromkeys(urls))[:limit]


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
    # Final (name, source_url) key: full ties previously fell back to model
    # output order, so re-running enrichment could pick a DIFFERENT person
    # each time. Selection must be deterministic.
    return min(
        candidates,
        key=lambda s: (
            role_rank[s.role],
            _CONFIDENCE_RANK.get(s.confidence, 9),
            url_to_tier.get(s.source_url, 99),
            s.name,
            s.source_url,
        ),
    )


def _same_person(a: str | None, b: str | None) -> bool:
    """Same human, tolerant of word order ("Kudyba Jadwiga" == "Jadwiga
    Kudyba") but nothing looser -- this guards field mixing, so a partial
    overlap must NOT count."""
    if not a or not b:
        return False
    return sorted(a.strip().lower().split()) == sorted(b.strip().lower().split())


def _resolve_email(record, all_emails: list[str], name: str | None) -> str | None:
    """Email attribution priority: (1) the LLM's own pairing on `record`,
    once it has survived grounding validation AND only when the record is
    about the SAME person whose name is being written -- confirmed real
    failure (TEB Rzeszów): RSPO's registry won the director NAME (Jadwiga
    Kudyba) while the LLM's grounded director record described a different
    person (Izabela Józefowska), and this function blindly attached the
    record's email to the registry's name, publishing one person's name
    with another person's address. Fields must never be mixed across two
    different humans. (2) the structural match (is_personal_email_for)
    over every email the crawl ever saw -- inherently safe, it validates
    against the exact name being written."""
    # An address nothing can be sent to is not a contact. One school stored
    # its director as "m.wlazlak-szal@brzegdolny.edu.p" -- a one-letter TLD.
    if record is not None and record.email and _same_person(record.name, name):
        if is_deliverable_shape(record.email) and not _is_institutional_address(record.email, name):
            return record.email
    return next(
        (e for e in all_emails if is_personal_email_for(e, name) and is_deliverable_shape(e)),
        None,
    )


def _is_institutional_address(email: str, name: str | None) -> bool:
    """An office mailbox is not any one person's own address.

    The model will happily pair whatever address sits next to a name on a
    contact page, which put "dyrekcja@spolecznaszkola.pl" on a director and
    "sp10@gzo.nysa.pl" on another -- nine rows in all. Two harms follow: the
    export presents an office box as that person's address, and because a
    person-claimed address is removed from the unclaimed pool, the office
    slot is left with whatever remains. On one school that was
    "m.banasiak@gzo.nysa.pl" -- so the school's own institutional box sat on
    a person while a private inbox became the school's public contact.

    An address that STRUCTURALLY matches the person's own name is theirs
    regardless of what else it looks like."""
    if is_personal_email_for(email, name):
        return False
    return email_priority(email) >= 1 or email_level_hint(email) is not None


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
    # A third-party page can never ORIGINATE a person/role claim
    # (ground_extraction drops any record citing one), so paying to send it
    # is pure waste. Dropped before the budget is spent, freeing that room
    # for the school's own pages.
    candidates = [
        llm_extract.PreparedPage(url=p["url"], text=p["text"], tier=p["tier"], third_party=p["third_party"])
        for p in raw_pages
        if not p["third_party"]
    ]
    # Then drop pages that cannot prove any role we could actually write.
    # Provably lossless -- see llm_extract.pages_that_could_prove.
    writeable_roles = ("director", "english_teacher")
    candidates = llm_extract.pages_that_could_prove(candidates, writeable_roles)
    pages = llm_extract.cap_pages(candidates)
    stats["llm_pages_sent"] = len(pages)
    stats["llm_chars_sent"] = sum(len(p.text) for p in pages)
    if not pages:
        # Nothing in the crawl could yield a writeable contact -- skipping
        # the call entirely costs nothing and saves a whole round trip.
        return None, stats
    pages_by_url = {p.url: p.text for p in pages}
    third_party_urls: set[str] = set()  # none survive the filter above

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
        extraction = llm_extract.ground_extraction(extraction, pages_by_url, school.name, third_party_urls)

    # Escalation is judged on what the routine call actually PROVED, not on
    # the pre-LLM state. still_needed_roles was computed before any LLM ran,
    # so judging by it sent the expensive Opus call (full page bundle
    # re-sent) for nearly every school -- including ones where Haiku had
    # already span-grounded the very roles being "escalated for". A role
    # only stays needed if the grounded routine result has no writeable
    # (high/medium) record for it.
    roles_unproven = set(still_needed_roles)
    if extraction is not None:
        for record in extraction.staff:
            if record.confidence in ("high", "medium"):
                roles_unproven.discard(record.role)

    if roles_unproven and llm_extract.needs_escalation(extraction, pages, roles_unproven):
        try:
            escalated = _call(llm_extract.OPUS_MODEL)
            stats["escalations"] += 1
        except llm_extract.CliUnavailableError:
            # Escalation specifically couldn't connect -- keep whatever the
            # routine call already produced rather than discarding it too.
            escalated = None
        if escalated is not None:
            escalated = llm_extract.ground_extraction(escalated, pages_by_url, school.name, third_party_urls)
            if extraction is None:
                extraction = escalated
            else:
                # Escalation FILLS GAPS, never clobbers: the routine call's
                # grounded records survive; Opus contributes only roles the
                # routine pass didn't ground at all. (Previously the whole
                # routine result was replaced, so a correct high-confidence
                # Haiku record could be silently discarded.)
                have_roles = {r.role for r in extraction.staff}
                extraction.staff.extend(r for r in escalated.staff if r.role not in have_roles)
                extraction.unattributed_emails = list(
                    dict.fromkeys([*extraction.unattributed_emails, *escalated.unattributed_emails])
                )

    return extraction, stats


# NOTE(accuracy policy): the previous vision-extraction path (reading staff
# rosters published as images/PDFs with a vision model) was removed from the
# write pipeline on purpose. A vision result cannot be span-grounded against
# fetched page text the way ground_extraction verifies llm_text records, so
# under the "never write unverified data" policy it may not create contacts.
# Roster image/PDF URLs the text model spots are surfaced in the activity
# metadata (staff_roster_urls) for a human to check manually instead.


_SCHOOL_NR_RE = re.compile(r"\bnr\.?\s*(\d+)\b", re.IGNORECASE)


# ONE PERSON's mailbox, recognised without knowing whose. The office slot is
# meant to be a monitored school inbox, but "i.kurowska@zsp1mm.pl" won it
# over the school's own "zsp1mm@zsp1mm.pl" on a tie, and
# "AKolakowska@eduwarszawa.pl" won it outright -- outreach for those schools
# would land in one teacher's personal inbox.
#
# The test is deliberately narrow, because <word>.<word> is ALSO the shape of
# a perfectly good office box: nsp.lubsko@, ksp.mlociny@, technikum.gdansk@
# and szk.nazaretanek@ are all real school addresses. What separates them is
# the FIRST token -- a single initial, or a name from the first-name list.
# An unrecognised diminutive ("ela.ryznar@") is therefore missed rather than
# guessed at, which is the safe direction: a demotion that fires wrongly
# would throw away a real office address.
def _looks_like_one_persons_mailbox(email: str) -> bool:
    local = email.split("@")[0].lower()
    parts = local.split(".")
    if len(parts) != 2:
        return False
    head, tail = parts
    if not head.isalpha() or not tail.isalpha():
        return False
    if head in GENERIC_OFFICE_LOCAL_PARTS or tail in GENERIC_OFFICE_LOCAL_PARTS:
        return False
    return len(head) == 1 or head in _COMMON_POLISH_FIRST_NAMES


# A number attached to a COMPLEX marker is the complex's number, not the
# school's. Confirmed directly: "SZKOŁA PODSTAWOWA NR 321" sits inside
# "Zespół Szkolno-Przedszkolny nr 7", and its own secretariat address is
# sekretariat.zsp7@eduwarszawa.pl -- the 7 belongs to "zsp". Read as a
# school number it contradicted 321, so the number-conflict demotion below
# pushed the school's real office mailbox BELOW an unlabelled personal
# address on the same domain (AKolakowska@eduwarszawa.pl), which then
# became the stored office contact. Stripping marker-attached numbers
# before the conflict check leaves the rule that motivated it intact: a
# bare sp84@ still cannot win for school nr 350.
_COMPLEX_NUMBER_RE = re.compile(r"(?:zspo|zsp|zso|zsz|zs|msz|zpo|zpow|ze)\s*\d+", re.IGNORECASE)


def _strip_complex_number(local_part: str) -> str:
    return _COMPLEX_NUMBER_RE.sub("", local_part)


# Written names are normalized once, here, so every downstream consumer --
# the CSV export's Polish declensions above all -- sees one canonical form.
# Two shapes came out of a 500-school re-run and both produce embarrassing
# Polish in a letter:
#   * "Bakiera Patrycja" (surname first). Female first names are detected by
#     the "-a" ending rule, so an -a surname looks like a first name and the
#     export declined the SURNAME as the given name: "Szanowna Pani
#     Bakiero", dative "Pani Bakierze Patrycja". _normalize_name_order
#     decides this on a curated first-name list, so it swaps only on proof.
#   * "Bożena Zagórska - Arumińska" / "Aleksandra Kurowska – Susdorf" (a
#     double-barrelled surname spaced or en-dashed). Split on whitespace,
#     only the final token counted as the surname and the first half was
#     silently dropped.
_SPACED_DASH_RE = re.compile(r"\s*[-‐-―]\s*")


def _clean_person_name(name: str | None) -> str | None:
    if not name:
        return name
    cleaned = _SPACED_DASH_RE.sub("-", " ".join(name.split()))
    return _normalize_name_order(cleaned) or cleaned


def pick_general_email(
    candidates: list[str], school_level: str, school_name: str, rspo_email: str | None
) -> str | None:
    """The school's general office box, chosen from every unclaimed
    candidate. Preference order per criterion (lower wins):

    1. Level agreement of the address's own code with THIS school:
       an exact level match (ssp11@ for a Społeczna SP) beats a neutral
       address, which beats a code for a SIBLING level (1slo@ for that
       same SP). Confirmed directly: SSP nr 11 w Białymstoku's own
       ssp11@slosto.biaman.pl lost to the complex-shared slosto@ box
       because neither carried a recognized level code, and RSPO (which
       registers the shared box for every school in the complex) won the
       tie.
    2. A number embedded in the local part that CONTRADICTS the school's
       own number is demoted outright -- sp84@ can never win for school
       nr 350, even if it leaks onto a shared page.
    3. campaign_email_tier: office > unlabelled > recruitment-only.
    4. RSPO's registered address wins remaining ties as the authoritative
       source."""
    candidates = [e for e in candidates if is_deliverable_shape(e)] or candidates
    if not candidates:
        return None
    name_match = _SCHOOL_NR_RE.search(school_name or "")
    school_number = name_match.group(1) if name_match else None

    def rank(email: str) -> tuple[int, int, int, int]:
        hint = email_level_hint(email)
        if hint == school_level:
            level_pref = 0
        elif hint is None:
            level_pref = 1
        else:
            level_pref = 2
        local_digits = re.findall(r"\d+", _strip_complex_number(email.split("@")[0]))
        number_conflict = 1 if (
            school_number and local_digits and school_number not in {d.lstrip("0") or d for d in local_digits}
        ) else 0
        rspo_tiebreak = 0 if email == rspo_email else 1
        personal = 1 if _looks_like_one_persons_mailbox(email) else 0
        return (personal, number_conflict, level_pref, campaign_email_tier(email), rspo_tiebreak)

    return min(candidates, key=rank)


def _same_human(a: str | None, b: str | None) -> bool:
    """Same person, compared on the canonical form -- so a stored name that
    differs only in word order ("Bakiera Patrycja") or dash spelling
    ("Zagórska - Arumińska") is recognised as the same human as its
    canonicalised spelling, rather than as a rival occupant of the slot."""
    return _same_person(_clean_person_name(a), _clean_person_name(b))


# Extraction methods that carry a verbatim, span-grounded quote. Anything
# else (a registry name, a pre-overhaul regex row) is weaker by construction,
# so an LLM record legitimately replaces it.
_GROUNDED_METHODS = frozenset({"llm_text", "llm_vision"})


def _supersedes(
    *,
    challenger_email: str | None,
    challenger_confidence: str | None,
    challenger_method: str | None,
    incumbent,
) -> bool:
    """Should a DIFFERENT person take over a slot that already holds one?

    Only when this run genuinely proved more, in one of three ways:
    an address where the stored row has none (the whole point of the
    contact), higher confidence, or a grounded quote replacing a row that
    never had one. Equal evidence leaves the incumbent alone -- see the
    churn guard in _upsert_contact."""
    if challenger_email and not incumbent.email:
        return True
    if incumbent.email and not challenger_email:
        return False  # never trade a contactable person for an uncontactable one
    challenger_rank = _CONFIDENCE_RANK.get(challenger_confidence, 9)
    incumbent_rank = _CONFIDENCE_RANK.get(incumbent.confidence, 9)
    if challenger_rank != incumbent_rank:
        return challenger_rank < incumbent_rank
    if challenger_method in _GROUNDED_METHODS and incumbent.extraction_method not in _GROUNDED_METHODS:
        return True
    return False


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
    """Each slot (school_id, contact_type) holds exactly ONE current
    contact. Historically a differing name was APPENDED next to the old
    one, so every past mis-extraction stayed on screen forever -- a school
    could show several "directors" at once, which is exactly the "random
    people in random spots" symptom users reported. Now a newly verified
    person REPLACES the slot's previous occupant (the new record has just
    passed the strictest gate in the pipeline, span-grounding + the
    confidence floor -- it is strictly better evidence than any older row).

    Degradation guard: when re-finding the SAME person without an email/
    phone this time, the previously stored email/phone is kept rather than
    wiped -- a run that proves less than last time must not destroy what
    was already proven.

    Churn guard: a DIFFERENT person only takes the slot when they are
    strictly better evidence (see _supersedes). "The new record just passed
    the strictest gate" justified blind replacement only while the stored
    row came from a weaker pipeline. Once both rows are LLM-grounded, a
    school with eight English teachers simply yields whichever one this
    crawl happened to reach -- measured on a 100-school re-run of schools
    that already had a teacher: 19% swapped to a different person and NOT
    ONE gained an email. That churn is not neutral: these names are
    exported with their Polish declensions into prepared outreach, so a
    silent swap invalidates campaign data to buy nothing."""
    # Addresses are stored lowercase. A site that writes the SAME mailbox
    # with different capitalisation on two pages otherwise looks like two
    # different addresses: one re-run changed a school's stored office
    # contact from szkola@weldonschool.pl to szkola@weldonSchool.pl, which
    # is the same inbox and pure churn. It also stops SEKRETARIAT@SCHOOL.PL
    # landing in a mail-merge column that way.
    email = email.strip().lower() if email else email
    existing = session.query(SchoolContact).filter_by(school_id=school_id, contact_type=contact_type).all()
    # "Same person" is judged on the CANONICAL form, not the raw string, so a
    # row differing only in word order or dash spelling is recognised as the
    # same human and gets rewritten to the canonical spelling. Compared
    # literally, "Bakiera Patrycja" and "Patrycja Bakiera" look like two
    # different people, so the churn guard below refused the update and 35
    # mis-declining names survived their own cleanup re-run.
    incumbent = next(
        (
            row
            for row in existing
            if row.person_name and person_name and not _same_human(row.person_name, person_name)
        ),
        None,
    )
    if incumbent is not None and not _supersedes(
        challenger_email=email,
        challenger_confidence=confidence,
        challenger_method=extraction_method,
        incumbent=incumbent,
    ):
        return  # keep the person already on file; this run proved nothing more
    match = None
    for row in existing:
        if person_name and row.person_name and _same_human(row.person_name, person_name):
            match = row
        elif not person_name and not row.person_name:
            match = row
        else:
            session.delete(row)  # superseded occupant of this slot
    if match:
        kept_email = email or match.email
        # The degradation guard keeps what a weaker run couldn't re-prove --
        # but only while it is still LEGITIMATE. Nine person rows held an
        # office mailbox ("dyrekcja@...", "sp10@..."); once _resolve_email
        # started refusing to re-attach those, "email or match.email" simply
        # preserved them forever, so the re-run meant to clear them changed
        # nothing. A slot for a PERSON only keeps an address that still
        # passes today's checks.
        if kept_email and person_name and (
            not is_deliverable_shape(kept_email)
            or _is_institutional_address(kept_email, person_name)
        ):
            kept_email = None
        match.person_name = person_name
        match.email = kept_email
        match.phone = phone or match.phone
        match.source_url = source_url
        match.enrichment_job_id = job_id
        match.contact_quality = classify_contact_quality(person_name, kept_email) if person_name else quality
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
    retired_any = False
    for stale in session.query(SchoolContact).filter_by(school_id=school.id).all():
        if is_non_school_email(stale.email):
            session.delete(stale)
            retired_any = True
    # BUG FIX: the session runs autoflush=False, so without an explicit
    # flush the pending delete is invisible to _upsert_contact's own
    # existing-row query below -- the upsert then "updates" the doomed row
    # and the commit executes the delete last, destroying the fresh
    # contact with it. Confirmed directly: retiring SP 190's leaked IOD
    # address silently ate the same run's newly-found sekretariat email,
    # leaving the school with no general contact at all.
    if retired_any:
        session.flush()

    # RSPO's own detail API is authoritative and official -- try it
    # FIRST, before any website scraping. It never has the English
    # teacher's name, so the website is still crawled regardless,
    # but a director name found here always wins over a scraped one.
    # Per-stage wall-clock, logged in the activity metadata. Without it the
    # cost of a stage could only be inferred by correlating totals across
    # schools -- which is how a 3.9-hour outlier stayed unexplainable.
    timings: dict[str, int] = {}
    started = time.perf_counter()

    def _mark(stage: str) -> None:
        nonlocal started
        now = time.perf_counter()
        timings[f"{stage}_ms"] = int((now - started) * 1000)
        started = now

    rspo_info: dict = {}
    detail = None
    if school.rspo_id:
        detail = fetch_rspo_detail(school.rspo_id)
        if detail:
            rspo_info = parse_director_and_contacts(detail)
    _mark("rspo")

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

    # The LLM nav-picker is injected, not imported by the crawler (which
    # llm_extract itself imports -- see scraper._picked_staff_links). It is
    # only consulted when keyword tiering finds no staff-roster link at
    # all, and is passed only when the CLI is actually usable, so a
    # container without working credentials crawls exactly as before.
    picker = llm_extract.pick_staff_pages if llm_extract.is_llm_usable() else None
    result = scrape_school_website(
        school.name,
        effective_website,
        rspo_email=rspo_info.get("email"),
        staff_page_picker=picker,
        city=school.city,
    )
    _mark("crawl")

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
        # PERSISTING a corrected URL is held to a stricter bar than merely
        # crawling it: once written, every future run starts there, so a
        # wrong adoption poisons the school permanently. Content-level city
        # checks are not enough on chain sites (every branch page lists
        # every city in its nav -- confirmed: TEB re-adopted the /swidnica/
        # branch URL for a Rzeszów school because "Rzeszów" appears in the
        # city selector). The URL ITSELF must name the school's city (or
        # the school's name carries no city to check). A genuinely-better
        # URL that fails this stays un-persisted -- the next run simply
        # re-discovers it from the original URL, which costs a little and
        # risks nothing.
        if _mentions_school_city(school.name, discovered_url):
            website_url_corrected = {"from": school.website_url, "to": discovered_url}
            school.website_url = discovered_url
            school.website_url_source = EvidenceSource.ENRICHMENT
        else:
            website_url_corrected = {"from": school.website_url, "to": discovered_url, "skipped": "url fails city check"}

    # NOTE(accuracy policy): the web-search fallback (augment_with_web_search)
    # was removed from this pipeline on purpose. Search-result pages are
    # third-party: they routinely describe a DIFFERENT school (directories,
    # gmina pages) and were scraped without identity verification -- a
    # documented source of cross-school contact contamination. Under the
    # "never write unverified data" policy, third-party pages may not
    # originate names, emails, or phones. A school whose own site yields
    # nothing stays blank -- blank beats wrong.
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
    # What the LLM is still needed FOR, judged only by sources that can
    # actually write under the accuracy policy: RSPO for the director,
    # nothing else. A regex candidate must not suppress a role here -- it
    # is never written, so "regex found something" is not "we have it".
    still_needed_roles: set[str] = {"english_teacher"}
    if not rspo_info.get("director_name"):
        still_needed_roles.add("director")

    llm_extraction, llm_stats = _run_llm_extraction(result, school, still_needed_roles)
    _mark("llm")

    llm_pages = result.get("llm_pages") or []
    pages_by_url = {p["url"]: p["text"] for p in llm_pages}
    url_to_tier = {p["url"]: p["tier"] for p in llm_pages}

    # ------------------------------------------------------------------
    # ACCURACY POLICY (owner requirement): a NAMED contact is written only
    # when its accuracy is provable -- never guessed, never substituted.
    #   - director: RSPO's official registry, or an LLM record that
    #     survived span-grounding (evidence quote contains BOTH the name
    #     and the role vocabulary, verified in code) with role=="director"
    #     exactly. A deputy is NEVER written as the director.
    #   - english_coordinator: a span-grounded role=="english_teacher"
    #     record only.
    #   - model-reported confidence "low" means the model itself was
    #     unsure: not good enough to write, even span-grounded.
    #   - the regex engine's page-scoped guesses are NEVER written; they
    #     are kept in the activity metadata for observability only.
    # A slot with nothing provable stays empty -- blank beats wrong.
    # ------------------------------------------------------------------
    def _writeable(record):
        return record is not None and record.confidence in ("high", "medium")

    director_record = teacher_record = None
    if llm_extraction is not None:
        director_record = _pick_best_staff(llm_extraction.staff, ("director",), url_to_tier)
        teacher_record = _pick_best_staff(llm_extraction.staff, ("english_teacher",), url_to_tier)
    if not _writeable(director_record):
        director_record = None
    if not _writeable(teacher_record):
        teacher_record = None

    teacher_name = _clean_person_name(teacher_record.name) if teacher_record else None

    # Director: RSPO's registry vs the school's own site. The registry is
    # official but can be STALE (confirmed real failure, TEB Rzeszów: RSPO
    # still listed a former/head-office director while the site named the
    # current one). Resolution:
    #   - both agree (same person)  -> site record wins the row (it carries
    #     evidence + possibly the email), registry corroborates;
    #   - both present, DIFFERENT people -> the site record wins ONLY with
    #     independent structural proof it's current (its own email matches
    #     its own name); otherwise the registry name stands alone. Either
    #     way the conflict is logged -- and fields are NEVER mixed between
    #     the two people.
    #   - one present -> that one.
    rspo_director = rspo_info.get("director_name")
    rspo_director_conflict = None
    use_site_director = False
    if director_record and rspo_director and not _same_person(director_record.name, rspo_director):
        site_self_consistent = bool(director_record.email) and is_personal_email_for(
            director_record.email, director_record.name
        )
        rspo_director_conflict = {
            "rspo": rspo_director,
            "site": director_record.name,
            "resolved_to": "site" if site_self_consistent else "rspo",
        }
        use_site_director = site_self_consistent
    elif director_record:
        use_site_director = True

    if use_site_director:
        director_name = _clean_person_name(director_record.name)
        director_extraction_method = "llm_text"
        director_confidence, director_evidence = director_record.confidence, director_record.evidence
        director_source_url = director_record.source_url
    elif rspo_director:
        director_name = rspo_director
        director_record = None  # never mix the mismatched site record's fields into this row
        director_extraction_method, director_confidence, director_evidence = "rspo", None, None
        director_source_url = f"{RSPO_SOURCE_URL_PREFIX}{school.rspo_id}"
    else:
        director_name = None
        director_record = None
        director_extraction_method = director_confidence = director_evidence = director_source_url = None

    if teacher_record:
        teacher_extraction_method = "llm_text"
        teacher_confidence, teacher_evidence = teacher_record.confidence, teacher_record.evidence
        teacher_source_url = teacher_record.source_url
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
    general_email = pick_general_email(unclaimed, school_level, school.name, rspo_email)

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
        # Observability only -- the regex engine's page-scoped guesses are
        # DELIBERATELY never written as contacts (accuracy policy); logging
        # them lets us measure how often regex and the grounded LLM agree.
        "regex_director_candidate": result.get("director_name"),
        "regex_teacher_candidate": result.get("english_teacher_name"),
        # Registry-vs-site disagreement on who the director is -- always
        # surfaced, never silently resolved (see the resolution rules above).
        "rspo_director_conflict": rspo_director_conflict,
        # Staff rosters published as images/PDFs can't be span-verified, so
        # they're surfaced for a human instead of auto-extracted. Read from
        # the crawled page text, not from paid model output.
        "staff_roster_urls": _roster_media_urls(llm_pages),
        **timings,
        "specialties_detected": specialties,
        "js_rendered_site": bool(result.get("js_app_shell")),
        "js_render_used": bool(result.get("js_render_used")),
        "website_url_corrected": website_url_corrected,
        "sources_checked": sources_checked,
        "sources_checked_count": len(sources_checked),
        "sources_ok_count": sum(1 for s in sources_checked if s["status"] == "ok"),
        "sources_rate_limited_count": sum(1 for s in sources_checked if s["status"] == "rate_limited"),
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


_LOCK_RETRY_DELAYS_SECONDS = (1, 3, 8, 20)


def _with_lock_retry(operation, *, what: str):
    """Run a short DB operation, retrying while SQLite reports the write
    lock as busy.

    BUG FIX: the database runs in rollback-journal mode (see core/db.py --
    deliberately, WAL silently reverted committed data on this Windows bind
    mount), where a writer takes an EXCLUSIVE lock. Two writers exist: a
    batch enrichment run and the auto-enrich background thread. Confirmed
    directly: a 100-school batch died at school 75 because the loop's own
    bookkeeping commit -- not the school's enrichment, which is already
    guarded -- raised "database is locked", killing the runner thread and
    leaving the job "running" with 26 items pending forever, unrecoverable
    without a restart. busy_timeout alone wasn't enough under a long batch,
    so the loop's own writes now wait and retry instead of aborting a run
    that is otherwise perfectly healthy."""
    last: Exception | None = None
    for delay in (*_LOCK_RETRY_DELAYS_SECONDS, None):
        try:
            return operation()
        except OperationalError as exc:  # noqa: PERF203 -- retry loop
            if "locked" not in str(exc).lower() or delay is None:
                raise
            last = exc
            print(f"enrichment: {what} blocked by a DB lock, retrying in {delay}s", flush=True)
            time.sleep(delay)
    raise last  # unreachable: the final iteration re-raises


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
            _with_lock_retry(lambda: session.refresh(job), what="cancel-flag refresh")
            if job.cancel_requested:
                cancelled = True
                break

            item.status = "running"
            item.started_at = datetime.now(timezone.utc)
            _with_lock_retry(session.commit, what="item start")

            try:
                school = session.query(School).filter_by(id=item.school_id).one()
                summary = enrich_school(session, school, job_id=job_id, requested_by=job.requested_by)
                # Fix for the edupage class of failure: a school whose crawl
                # was RATE-LIMITED and which yielded nothing must not be
                # stamped "success" -- that status permanently excludes it
                # from auto-enrich's candidate pool, sealing a temporary
                # platform throttle into a forever-empty school. "cancelled"
                # (the usage-limit precedent) keeps it retryable. A throttled
                # school that still found something keeps its success.
                throttled = (summary or {}).get("sources_rate_limited_count", 0) > 0
                found_anything = any(
                    (summary or {}).get(k)
                    for k in ("found_director_name", "found_english_teacher_name", "found_general_email")
                )
                if throttled and not found_anything:
                    item.status = "cancelled"
                    item.error_message = "site rate-limited the crawl -- retry later"
                else:
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
                # Roll back this school's HALF-WRITTEN mutations first --
                # committing partial state (some contacts written, others
                # not; website corrected but contacts missing) violates the
                # "only verified, complete data" policy. The rollback also
                # discards the item's own status fields set above, so they
                # are re-applied after it.
                session.rollback()
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
                # Discard every partial mutation the crashed enrich_school
                # made (contacts, website corrections, deletions) -- a
                # failed school must leave the database exactly as it found
                # it, not half-updated. The status fields below are set
                # AFTER the rollback so they survive it.
                session.rollback()
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
