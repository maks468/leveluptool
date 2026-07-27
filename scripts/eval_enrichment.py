"""Eval harness for the enrichment pipeline, built around 12 known
regression cases collected from manual review of real schools (see CASES
below -- each has a reported_problem the user found by hand plus a known
hint about the likely root cause).

Runs the SAME production logic a real enrichment job runs
(enrich_school_dry_run in jobs.py) rather than a second, drift-prone
reimplementation -- so a case "passing" here means the app would really
produce that result, not just that this script's own approximation of the
pipeline would.

Default mode is a dry run: every DB mutation enrich_school makes is rolled
back at the end (see enrich_school_dry_run), so repeated eval runs never
perturb real data. --commit runs the real job system instead
(create_job + run_job), for an authoritative, fully-persisted result when
you explicitly want one.

Usage:
    python scripts/eval_enrichment.py                # dry run, all 12 cases
    python scripts/eval_enrichment.py --school 5      # just case 5 (KIETRZ)
    python scripts/eval_enrichment.py --commit         # persist via a real job
"""

from __future__ import annotations

import argparse
import sys
import time
from dataclasses import dataclass, field

# Windows' console defaults to cp1252, which can't encode most Polish
# names/diacritics this script prints constantly -- reconfigure to UTF-8
# rather than crashing on the first Ł/ę/ś it hits.
sys.stdout.reconfigure(encoding="utf-8")

from levelup.core.db import SessionLocal
from levelup.models.school import School
from levelup.services.enrichment.jobs import create_job, enrich_school_dry_run, run_job

_DIACRITICS = str.maketrans("ąćęłńóśźżĄĆĘŁŃÓŚŹŻ", "acelnoszzACELNOSZZ")


def _norm(s: str | None) -> str:
    return (s or "").translate(_DIACRITICS).upper()


@dataclass
class Case:
    num: int
    name_contains: list[str]
    reported_problem: str
    hint: str
    city_contains: str | None = None
    exclude_contains: list[str] = field(default_factory=list)
    rspo_id_hint: str | None = None


# The 12 regression cases as reported by the user, each resolved here by a
# case-insensitive, diacritic-normalized CONTAINS match against the
# school's official name (never a hardcoded id) -- so this list stays
# valid across a fresh RSPO re-import. A few names collide with a sibling
# school (a "filia", a same-name duplicate registration, or another school
# in the same town); city_contains/exclude_contains/rspo_id_hint exist
# only to break those specific, confirmed collisions.
CASES: list[Case] = [
    Case(
        1,
        ["WROCLAWSKIEJ AKADEMII BIZNESU"],
        "Director listed on website, never extracted",
        "Likely extraction-stage",
        city_contains="WROCLAW",
        rspo_id_hint="483674",  # two duplicate RSPO registrations share this exact name; this one carries the real website
    ),
    Case(
        2,
        ["KONOPNICKIEJ", "CHROSCICACH"],
        "Wrong English teacher attached -- precision failure, worst class",
        "Must end correct or blank, never wrong",
    ),
    Case(
        3,
        ["DABROWSKIEJ", "BRANICACH"],
        "English teacher not found",
        "Recall failure",
    ),
    Case(
        4,
        ["KSIEZNEJ JADWIGI", "OLESNIE"],
        "English teacher not found",
        "Bilingual school, nonstandard labels",
    ),
    Case(
        5,
        ["W KIETRZU", "JANA PAWLA"],
        "Website in RSPO never attached; nothing extracted",
        "Municipal veto likely rejects correct site",
    ),
    Case(
        6,
        ["KRAPKOWICACH", "BRZECHWY"],
        "Director on website never found (not in RSPO)",
        'EduPage; "Dyrektor ... - mgr Joanna Drescher"',
    ),
    Case(
        7,
        ["FILIPA ROBOTY", "LACZNIKU"],
        "Website and director never found",
        "Website-discovery failure",
        exclude_contains=["FILIA"],
    ),
    Case(
        8,
        ["NR 28", "WOJCIECHA", "OPOLU"],
        "Website, principal email, teacher all missing",
        "psp28.opole.pl bare hub nav",
    ),
    Case(
        9,
        ["PUBLICZNA SZKOLA PODSTAWOWA W BABOROWIE"],
        "Never scraped at all",
        "Stale domain zs_baborow.wodip.opole.pl migrated to zspbaborow.edu.pl",
        city_contains="BABOROW",
        exclude_contains=["CIEZKIEGO"],
    ),
    Case(
        10,
        ["SZARYCH", "DABROWIE"],
        "Website never assigned",
        "Website-discovery failure",
        city_contains="DABROWA",
    ),
    Case(
        11,
        ["RODU DZIALYNSKICH", "BRATIANIE"],
        "Enrichment incomplete",
        'zsbratian.edupage.org; bogus ".org.pl"; director on "O szkole" page (nbsp)',
    ),
    Case(
        12,
        ["NR 4", "JANA PAWLA"],
        "Director/teacher not found",
        'szkola.zsplw.pl behind chooser hub "Wejscie" labels',
        city_contains="LIDZBARK",
    ),
]


def resolve_case(session, case: Case) -> School:
    schools = session.query(School).all()
    candidates = []
    for sc in schools:
        name_n = _norm(sc.name)
        if not all(part in name_n for part in case.name_contains):
            continue
        if case.city_contains and case.city_contains not in _norm(sc.city):
            continue
        if any(part in name_n for part in case.exclude_contains):
            continue
        if case.rspo_id_hint and sc.rspo_id != case.rspo_id_hint:
            continue
        candidates.append(sc)

    if len(candidates) == 1:
        return candidates[0]

    detail = "\n".join(f"    id={sc.id} rspo={sc.rspo_id} {sc.name} | {sc.city}" for sc in candidates)
    raise RuntimeError(
        f"case {case.num}: expected exactly 1 match, got {len(candidates)}:\n{detail or '    (none)'}"
    )


def classify_stage(result: dict) -> str:
    """A deliberately conservative heuristic -- sources_checked records
    only url+status, not which keyword tier each page was reached at, so
    "crawl" (right page never reached) and "extraction" (right page
    reached, name still not pulled out of it) can't be told apart from
    this data alone. Collapsed into one bucket rather than faking a
    precision the underlying data doesn't support; read the printed
    sources_checked list by hand to tell them apart."""
    sources = result.get("sources_checked", [])
    if result.get("school_closed"):
        return "school-closed"
    if not any(s.get("status") == "ok" for s in sources):
        return "website-discovery"
    has_director = bool(result.get("director_name"))
    has_teacher = bool(result.get("teacher_name"))
    if has_director and has_teacher:
        return "pass"
    if has_director or has_teacher:
        return "partial (crawl-or-extraction)"
    return "crawl-or-extraction"


def run_dry(case: Case, school: School) -> dict:
    session = SessionLocal()
    started = time.monotonic()
    try:
        result = enrich_school_dry_run(session, school)
    except Exception as exc:  # noqa: BLE001 -- one case's failure must not sink the eval run
        result = {"error": str(exc), "sources_checked": []}
    finally:
        session.close()
    elapsed = time.monotonic() - started
    result["_elapsed_seconds"] = round(elapsed, 1)
    return result


def run_committed(case: Case, school: School) -> dict:
    session = SessionLocal()
    started = time.monotonic()
    try:
        job = create_job(session, [school.id], requested_by=1, is_automatic=False)
        session.commit()
        job_id = job.id
    finally:
        session.close()

    run_job(job_id)  # opens/closes its own session, same as production

    session = SessionLocal()
    try:
        fresh = session.query(School).filter_by(id=school.id).one()
        result = {
            "director_name": fresh.director_name,
            "teacher_name": fresh.english_teacher_name,
            "website_url": fresh.website_url,
            "sources_checked": [],  # not reconstructed here -- see the job's own activity log for full provenance
        }
    finally:
        session.close()
    result["_elapsed_seconds"] = round(time.monotonic() - started, 1)
    return result


def print_case_report(case: Case, school: School, result: dict) -> None:
    stage = classify_stage(result)
    print(f"\n{'=' * 90}")
    print(f"CASE {case.num}: {school.name}")
    print(f"  city: {school.city}   rspo_id: {school.rspo_id}   school_id: {school.id}")
    print(f"  reported problem : {case.reported_problem}")
    print(f"  hint             : {case.hint}")
    if result.get("error"):
        print(f"  ERROR: {result['error']}")
        print(f"  stage: error")
        return
    if result.get("school_closed"):
        print(f"  school_closed: True, liquidation_date={result.get('liquidation_date')}")
        print(f"  stage: {stage}")
        return
    print(f"  website_url      : {result.get('website_url')}")
    print(f"  director_name    : {result.get('director_name')}")
    print(f"  teacher_name     : {result.get('teacher_name')}")
    print(f"  director_email   : {result.get('director_email')}")
    print(f"  teacher_email    : {result.get('teacher_email')}")
    print(f"  general_email    : {result.get('general_email')}")
    print(
        f"  elapsed          : {result.get('_elapsed_seconds')}s   "
        f"llm_calls: {result.get('llm_calls', 0)}  escalations: {result.get('escalations', 0)}  "
        f"vision_calls: {result.get('vision_calls', 0)}  "
        f"tokens(in/out): {result.get('llm_input_tokens', 0)}/{result.get('llm_output_tokens', 0)}"
    )
    print(f"  director_source  : {result.get('director_source')}   teacher_source: {result.get('teacher_source')}")
    print(f"  STAGE            : {stage}")
    sources = result.get("sources_checked", [])
    print(f"  sources_checked ({len(sources)}):")
    for s in sources[:20]:
        flags = {k: v for k, v in s.items() if k not in ("url", "status")}
        print(f"      [{s.get('status')}] {s.get('url')} {flags if flags else ''}")
    if len(sources) > 20:
        print(f"      ... and {len(sources) - 20} more")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--school", type=int, default=None, help="run only case N (1-12)")
    parser.add_argument("--commit", action="store_true", help="persist via a real enrichment job instead of a dry run")
    args = parser.parse_args()

    cases = [c for c in CASES if args.school is None or c.num == args.school]
    if args.school is not None and not cases:
        print(f"no case numbered {args.school}", file=sys.stderr)
        sys.exit(1)

    session = SessionLocal()
    try:
        resolved = [(case, resolve_case(session, case)) for case in cases]
    finally:
        session.close()

    stage_counts: dict[str, int] = {}
    for case, school in resolved:
        result = run_committed(case, school) if args.commit else run_dry(case, school)
        print_case_report(case, school, result)
        stage = "school-closed" if result.get("school_closed") else classify_stage(result)
        stage_counts[stage] = stage_counts.get(stage, 0) + 1

    print(f"\n{'=' * 90}")
    print(f"SUMMARY ({len(resolved)} case(s), {'committed' if args.commit else 'dry run'}):")
    for stage, count in sorted(stage_counts.items()):
        print(f"  {stage}: {count}")


if __name__ == "__main__":
    main()
