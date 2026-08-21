"""Claude-powered contact extraction -- the authoritative source for
director/teacher names and email pairing, replacing the regex family in
scraper.py (DIRECTOR_RE, ENGLISH_TEACHER_*, _staff_entries, ...). Those
regexes are kept only as (a) a steering signal for the crawl's early-stop
heuristic (_is_complete) and (b) the offline fallback when the CLI is
unavailable -- nothing they extract is stored otherwise.

BILLING, non-negotiable: every call here runs through the Claude Agent SDK
against the user's own locally-installed, subscription-authenticated
Claude Code CLI -- never the pay-as-you-go Anthropic API. See
_child_env() for how ANTHROPIC_API_KEY is structurally kept out of the
child process. Confirmed directly (isolated test calls, see project
notes): even with allowed_tools=[] and an isolated cwd/settings, every
call draws from the SAME 5-hour rolling usage window as the user's own
interactive Claude Code sessions, not a separate quota -- see
UsageLimitError, which callers (jobs.py) must treat as "stop the batch
cleanly", never as a per-school failure.

Every public function returns None on any SDK failure (CLI unavailable,
usage limit, unparseable output after retry) -- it never raises into the
crawl. Callers are expected to log the failure into sources_checked
themselves (e.g. {"llm": "failed"}) and fall back to regex extraction.
UsageLimitError is the one exception that DOES propagate, since jobs.py
needs to distinguish "this school's extraction failed" from "the whole
batch must stop now" -- see run_job's handling in jobs.py.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import re
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ValidationError

from levelup.services.enrichment.scraper import EMAIL_RE, _is_patron_name, _patron_name_tokens

logger = logging.getLogger(__name__)

try:
    from claude_agent_sdk import (
        AssistantMessage,
        ClaudeAgentOptions,
        RateLimitEvent,
        ResultMessage,
        TextBlock,
        query,
    )
    from claude_agent_sdk._errors import ClaudeSDKError

    SDK_AVAILABLE = True
except ImportError:  # claude-agent-sdk not installed, or its own CLI discovery fails at import time
    SDK_AVAILABLE = False
    ClaudeSDKError = Exception  # placeholder so the except clause below still parses when the SDK is absent

# Routine per-school extraction. Escalation (a staff-bearing page that
# still returned zero staff, a still-needed role at low confidence, or
# unparseable output twice) and every vision call use the Opus tier --
# see EXTRACTION_ARCHITECTURE.md-equivalent notes in jobs.py/scraper.py
# for the exact triggers.
HAIKU_MODEL = "claude-haiku-4-5"
OPUS_MODEL = "claude-opus-4-8"

# A neutral, isolated cwd for every call -- combined with setting_sources=[]
# below, this keeps this PROJECT's own CLAUDE.md/settings (and any other
# directory-scoped configuration) from ever loading into an extraction
# call, which exists only to run one narrow, structured task. Must exist
# on disk before the child process can be spawned into it (confirmed
# directly: Windows' CreateProcess rejects a nonexistent cwd outright).
_ISOLATED_CWD_PATH = Path(tempfile.gettempdir()) / "levelup_llm_extract"
_ISOLATED_CWD_PATH.mkdir(parents=True, exist_ok=True)
_ISOLATED_CWD = str(_ISOLATED_CWD_PATH)

# Per-school hard ceiling from the task spec: 1 call typical (routine
# extraction), at most 1 escalation, at most 3 vision calls. Enforced by
# CALLERS (jobs.py) counting their own calls -- this module has no
# cross-call state to enforce it itself.
MAX_VISION_CALLS_PER_SCHOOL = 3

# Backstops, not the primary limiter: pages_that_could_prove() below
# removes pages that provably cannot yield a writeable record, which is
# what actually keeps the bundle small. These stay as a ceiling and are
# env-tunable so the budget can be adjusted without a code change (and so
# a future config UI has somewhere to write).
MAX_PAGES_PER_SCHOOL = int(os.getenv("LEVELUP_LLM_MAX_PAGES", "8"))
MAX_CHARS_PER_SCHOOL = int(os.getenv("LEVELUP_LLM_MAX_CHARS", "50000"))
MAX_IMAGE_BYTES = 10 * 1024 * 1024
MAX_PDF_BYTES = 10 * 1024 * 1024
MAX_PDF_PAGES = 10


class UsageLimitError(Exception):
    """The shared 5-hour Claude Code usage window is exhausted (or the CLI
    otherwise rejected the call as a rate/usage limit) -- callers must end
    the whole batch cleanly (job -> "cancelled", current item reverted,
    remaining items left "pending"), never mark just this school "failed".
    A failed/success EnrichmentJobItem excludes a school from the next
    auto-enrich cycle (see auto_enrich._select_candidate_school_ids); a
    cancelled one does not, so schools caught by this stay eligible."""

    def __init__(self, message: str, *, resets_at: int | None = None, rate_limit_type: str | None = None):
        super().__init__(message)
        self.resets_at = resets_at
        self.rate_limit_type = rate_limit_type


class CliUnavailableError(Exception):
    """The Claude Code CLI itself can't be reached at all (not installed,
    not logged in, bundled-CLI discovery failed) -- distinct from
    UsageLimitError so callers fall back to regex extraction for this
    school instead of stalling the whole batch."""


# The only roles anything downstream can write (jobs.py writes "director"
# and "english_teacher" slots; deputy is kept so a deputy is recognizable
# as NOT the director rather than being silently re-roled). The Literal
# below deliberately still ACCEPTS the two legacy values: a model that
# ignores the prompt and emits one stray "other_teacher" must not fail
# schema validation and void the whole extraction -- such records are
# dropped in ground_extraction instead.
TARGET_ROLES = frozenset({"director", "deputy_director", "english_teacher"})


class StaffRecord(BaseModel):
    name: str
    role: Literal["director", "deputy_director", "english_teacher", "other_teacher", "other_staff"]
    subjects: list[str] = []
    email: str | None = None
    email_evidence: str | None = None
    evidence: str
    source_url: str
    confidence: Literal["high", "medium", "low"]


class SchoolExtraction(BaseModel):
    staff: list[StaffRecord] = []
    unattributed_emails: list[str] = []
    phone: str | None = None
    staff_roster_image_or_pdf_urls: list[str] = []
    notes: str | None = None


@dataclass
class PreparedPage:
    """One page's structure-preserving text, ready to hand to the LLM --
    built by scraper.py's _prepare_page_for_llm from the same HTML the
    regex crawl already fetched (never a second fetch). tier mirrors the
    crawl's own keyword-priority tier (lower = higher priority), used only
    to decide which pages survive cap_pages' budget. third_party marks a
    page reached via augment_with_web_search rather than the school's own
    site -- confidence on anything sourced from it is capped "medium"
    regardless of what the model itself reports."""

    url: str
    text: str
    tier: int = 0
    third_party: bool = False


def cap_pages(
    pages: list[PreparedPage], *, max_pages: int = MAX_PAGES_PER_SCHOOL, max_chars: int = MAX_CHARS_PER_SCHOOL
) -> list[PreparedPage]:
    """Prioritized by tier (ascending -- lower tier is higher priority,
    same convention as the crawl's own frontier), capped at max_pages AND
    a running character budget so one very long page can't crowd out
    every other page's chance of appearing in the same call."""
    ordered = sorted(pages, key=lambda p: p.tier)
    kept: list[PreparedPage] = []
    total_chars = 0
    for page in ordered:
        if len(kept) >= max_pages:
            break
        if total_chars + len(page.text) > max_chars and kept:
            continue
        kept.append(page)
        total_chars += len(page.text)
    return kept


def pages_that_could_prove(pages: list[PreparedPage], roles) -> list[PreparedPage]:
    """Drops pages that CANNOT possibly yield a writeable record, so they
    are never paid for. This is a pure cost filter with provably zero
    effect on what gets written, because it is derived from the grounding
    gate itself: ground_extraction only keeps a record whose evidence span
    -- a verbatim quote from THAT page -- contains the role's own
    vocabulary (_ROLE_EVIDENCE_KEYWORDS). A page whose text contains none
    of that vocabulary therefore cannot produce a single surviving record
    for any of `roles`, no matter what the model says about it.

    Cross-page pairing can't be lost either: a record's name, role quote
    and email_evidence must all ground against the ONE page it cites, so
    a page contributing only an address was already unusable on its own.

    Roles with no vocabulary entry (the legacy other_* values) are ignored
    here -- they are dropped by ground_extraction anyway."""
    vocabulary = tuple(kw for role in roles for kw in _ROLE_EVIDENCE_KEYWORDS.get(role, ()))
    if not vocabulary:
        return pages
    return [page for page in pages if any(kw in page.text.lower() for kw in vocabulary)]


def _child_env() -> dict[str, str]:
    """The SDK merges options.env ON TOP of the fully-inherited parent
    env (see claude_agent_sdk's subprocess transport: `{**inherited_env,
    ..., **options.env}`) -- there is no way to make a merge DELETE a key,
    so passing an empty dict would leave a real ANTHROPIC_API_KEY (if one
    were ever set in this process's environment, e.g. via a stray .env
    file) fully intact and still billing pay-as-you-go. Overriding it to
    an EMPTY STRING instead wins the merge unconditionally, and the CLI
    (a Node process) treats "" as falsy exactly like an unset var, so it
    falls through to its normal subscription-authenticated session --
    structurally impossible for a leaked key to flip billing here."""
    return {"ANTHROPIC_API_KEY": ""}


def _extract_text(msg: AssistantMessage) -> str:
    return "".join(block.text for block in msg.content if isinstance(block, TextBlock))


# Hard wall-clock ceiling per LLM call. Without one, a wedged CLI
# subprocess stalls its school FOREVER: the batch item stays "running", the
# Stop button's cooperative cancel never gets a chance to fire (it is only
# checked between schools), and the job tray shows an eternal spinner --
# the residual form of the "job hung 3+ hours" incident. 5 minutes is far
# above any legitimate single-call latency observed (even Opus over a full
# 50k-char page bundle), so a trip means "stuck", not "slow".
CALL_TIMEOUT_SECONDS = 300


async def _run_query(
    prompt: str, *, system_prompt: str, model: str, allowed_tools: list[str]
) -> tuple[str | None, dict]:
    options = ClaudeAgentOptions(
        system_prompt=system_prompt,
        max_turns=1,
        allowed_tools=allowed_tools,
        setting_sources=[],
        model=model,
        env=_child_env(),
        cwd=_ISOLATED_CWD,
    )
    final_text: str | None = None
    usage = {"input_tokens": 0, "output_tokens": 0, "cost_usd": 0.0}

    try:
        # The deadline wraps the whole stream in place rather than via a
        # second wrapper generator: wrapping produced "aclose(): asynchronous
        # generator is already running" whenever the SDK errored mid-stream,
        # because the outer generator was closed while the inner one was
        # still executing.
        async with asyncio.timeout(CALL_TIMEOUT_SECONDS):
            async for msg in query(prompt=prompt, options=options):
                if isinstance(msg, RateLimitEvent):
                    info = msg.rate_limit_info
                    if info.status == "rejected":
                        raise UsageLimitError(
                            f"Claude usage window exhausted ({info.rate_limit_type})",
                            resets_at=info.resets_at,
                            rate_limit_type=info.rate_limit_type,
                        )
                elif isinstance(msg, AssistantMessage):
                    if msg.error == "rate_limit":
                        raise UsageLimitError("Claude usage window exhausted (assistant error)")
                    if msg.error is not None:
                        logger.warning("llm_extract: assistant error %r for model %s", msg.error, model)
                        return None, usage
                    text = _extract_text(msg)
                    if text:
                        final_text = (final_text or "") + text
                elif isinstance(msg, ResultMessage):
                    if msg.usage:
                        usage["input_tokens"] = msg.usage.get("input_tokens", 0)
                        usage["output_tokens"] = msg.usage.get("output_tokens", 0)
                    usage["cost_usd"] = msg.total_cost_usd or 0.0
                    if msg.is_error:
                        errors_text = " ".join(msg.errors or [])
                        if (
                            msg.api_error_status == 429
                            or "rate" in errors_text.lower()
                            or "usage" in errors_text.lower()
                        ):
                            raise UsageLimitError(f"Claude call failed as a usage/rate limit: {errors_text}")
                        logger.warning("llm_extract: result error for model %s: %s", model, errors_text)
                        return None, usage
    except UsageLimitError:
        raise
    except TimeoutError as exc:
        # A wedged CLI subprocess, not a slow model -- see CALL_TIMEOUT_SECONDS.
        # Treated exactly like an unreachable CLI: this school falls back
        # gracefully instead of hanging the whole batch.
        raise CliUnavailableError(
            f"Claude call exceeded {CALL_TIMEOUT_SECONDS}s -- treating the CLI as wedged"
        ) from exc
    except ClaudeSDKError as exc:
        # The CLI itself couldn't be reached at all (not installed, not
        # logged in, bundled-CLI discovery failed, the process crashed) --
        # distinct from "the model call ran but returned nothing usable".
        # Translated to CliUnavailableError so callers fall back to regex
        # for just this school instead of the raw SDK exception type
        # propagating uncaught into run_job's generic error handling.
        raise CliUnavailableError(f"Claude Code CLI unreachable: {exc}") from exc

    return final_text, usage


def _run_sync(coro):
    """enrich_school (jobs.py) and the eval script both call this module
    from plain synchronous code with no event loop of their own already
    running -- run_job executes inside a FastAPI BackgroundTasks worker
    thread or auto_enrich's own daemon thread, neither of which has an
    active asyncio loop, so a fresh asyncio.run() per call is safe."""
    return asyncio.run(coro)


_JSON_FENCE_RE = re.compile(r"```(?:json)?\s*(\{.*\})\s*```", re.DOTALL)


def _parse_json_response(text: str) -> dict | None:
    """Models routinely wrap JSON in a markdown fence despite instructions
    not to -- stripped here rather than fought over in the prompt."""
    fence_match = _JSON_FENCE_RE.search(text)
    candidate = fence_match.group(1) if fence_match else text.strip()
    try:
        return json.loads(candidate)
    except json.JSONDecodeError:
        return None


_TEXT_EXTRACTION_SYSTEM_PROMPT = """You extract staff contact information from Polish school website pages. You are given the text of one or more pages, each preceded by a "=== PAGE: <url> ===" marker.

Return ONLY a single JSON object (no markdown fences, no commentary) matching exactly this shape:
{
  "staff": [
    {
      "name": "First Last",
      "role": "director" | "deputy_director" | "english_teacher",
      "email": "..." or null,
      "email_evidence": "verbatim quote containing both the surname and the email" or null,
      "evidence": "verbatim quote from the page proving this person and this role",
      "source_url": "the exact PAGE url this record came from",
      "confidence": "high" | "medium" | "low"
    }
  ]
}

SCOPE -- read this first, it controls the size of your answer:
- Return ONLY people holding one of these three roles: director, deputy_director, english_teacher.
- Do NOT return any other teacher or staff member. Other subjects' teachers, secretaries, librarians, counsellors and so on are discarded unread, so listing them only wastes the response. A staff page naming 40 teachers should normally yield 1-4 records here.
- Return every English teacher you find (a school can have several), but no other subject's teacher.
- Emit no fields other than those shown above.

Non-negotiable rules:
- Only extract a person whose name is LITERALLY written on one of the given pages. Never infer, guess, or complete a name. The only normalization allowed is reversing a "Surname Firstname" listing to "Firstname Surname".
- Every staff record MUST have a verbatim `evidence` quote (copied text, not paraphrased) and the exact `source_url` of the page it came from.
- The `evidence` quote must be ONE contiguous passage that contains BOTH the person's name AND the words stating their role (e.g. "Dyrektor szkoły: mgr Jan Nowak", "Anna Kowalska - nauczyciel języka angielskiego"). If no single passage on the page ties the name to the role, DO NOT output that record at all -- a record whose quote shows only the name, or only the role, will be discarded.
- "Wicedyrektor" / "zastępca dyrektora" is deputy_director, NEVER director. If the only leadership named is a deputy, do not output any director record.
- Only set `email` on a person when the page ITSELF associates that email with that specific person (adjacent in a table row, in a "Name - email" pattern, etc). If an email exists on the page but isn't clearly tied to one person, leave `email` null -- never guess which person an address belongs to. Unpaired addresses are collected separately by other code, so you do not need to report them.
- `email_evidence` must be a verbatim quote containing BOTH the person's surname and the email address together; if you can't quote both together, leave `email` and `email_evidence` null.
- The school's patron/namesake (the person in "im. ..." / "imienia ...") is NEVER staff, even if their name appears prominently.
- Recognize Polish role vocabulary: "dyrektor" = director, "wicedyrektor"/"zastępca dyrektora" = deputy_director, "nauczyciel języka angielskiego"/"nauczyciel j. angielskiego"/"anglista" (a teacher whose only or primary subject is English) = english_teacher. Some bilingual schools label roles in English directly ("English teacher", "Principal") -- recognize those the same way.
- An empty "staff" list is a completely valid, honest answer when the given pages genuinely name none of these three roles -- never fabricate a record to avoid returning empty.

NOT STAFF -- every one of these was observed on a real Polish school site sitting right next to the words "język angielski", and each would produce a WRONG contact. A wrong name is far worse than an empty answer:
- PUPILS in competition or exam results: "Wojewódzki Konkurs Przedmiotowy ... Język Angielski: Karolina Brzozowska - tytuł laureata", "finalistka", "II miejsce", "dyplom", "gratulujemy". A subject heading above a list of prize-winners names children, not teachers.
- JOB ADVERTS and application forms: "Poszukujemy nauczyciela języka angielskiego", "oferta pracy", "Wybierz stanowisko: Nauczyciel języka angielskiego". The post is VACANT -- nobody named nearby holds it.
- PAST or OTHER employment in a biography: "pracowała jako nauczycielka języka angielskiego w latach ...", "during her studies she taught English". Only a CURRENT role at THIS school counts.
- A QUALIFICATION that the same passage then contradicts: "z wykształcenia jestem iberystką i anglistką ... uczę hiszpańskiego" -- she teaches Spanish. Being trained in English is not teaching it; an explicit statement of what someone teaches always wins.
- GUESTS and outsiders: workshop presenters ("Jak pomóc dziecku w nauce angielskiego - mgr Alicja Gromadzka"), competition jurors, Erasmus experts, visiting native speakers billed as an event.
- A CLASS TUTOR with no subject named: "Klasa 4A - Anna Nowak" states who the form tutor is, not what they teach.
- A person at a DIFFERENT institution sharing the website: "anglistki w naszym przedszkolu" on a site covering both a kindergarten and a school is evidence about the kindergarten. If the passage names a different institution than the school given above, do not output the record.
- PURELY ADMINISTRATIVE titles: "Head of English Section", "koordynator", "metodyk" describe managing or advising, not teaching. Output such a person only if the text separately says they teach English.
- An email PATTERN rather than an address: "firstname.lastname@school.pl", "imie.nazwisko@...". Never assemble an address from a pattern.
"""

_VISION_SYSTEM_PROMPT = """You read an image or a scanned/exported PDF page from a Polish school's staff roster and extract staff contact information.

Return ONLY a single JSON object (no markdown fences, no commentary) matching exactly this shape:
{
  "staff": [
    {
      "name": "First Last",
      "role": "director" | "deputy_director" | "english_teacher" | "other_teacher" | "other_staff",
      "subjects": ["..."],
      "email": "..." or null,
      "email_evidence": "verbatim text near the name that also shows the email" or null,
      "evidence": "verbatim text you can read next to this name proving the role",
      "source_url": "{source_url}",
      "confidence": "high" | "medium" | "low"
    }
  ],
  "unattributed_emails": [],
  "phone": null,
  "staff_roster_image_or_pdf_urls": [],
  "notes": "..." or null
}

Non-negotiable rules:
- Only extract a name you can actually read in the image/PDF. Never guess a name that's blurry, cut off, or ambiguous -- skip it instead.
- Every record needs a non-empty `evidence` string quoting what you read next to the name.
- Only set `email` when the image itself shows that email next to that specific name.
- The school's patron/namesake is never staff.
- Recognize Polish role vocabulary (dyrektor, wicedyrektor/zastępca dyrektora, nauczyciel języka angielskiego/anglista) the same way a text extraction would.
- confidence should be "medium" at most unless you're confident the surrounding page context ties this image to the school's own official site (i.e. treat any doubt about provenance the same as a third-party page).
- An empty "staff" list is valid if the image genuinely shows no readable staff names.
"""


def _pages_to_prompt(pages: list[PreparedPage], school_name: str, city: str | None) -> str:
    header = f"School: {school_name}" + (f", {city}" if city else "")
    blocks = [header, ""]
    for page in pages:
        tag = " (THIRD-PARTY PAGE -- cap confidence at medium)" if page.third_party else ""
        blocks.append(f"=== PAGE: {page.url}{tag} ===")
        blocks.append(page.text)
        blocks.append("")
    return "\n".join(blocks)


def _validate_extraction(raw: dict) -> SchoolExtraction | None:
    try:
        return SchoolExtraction.model_validate(raw)
    except ValidationError as exc:
        logger.warning("llm_extract: schema validation failed: %s", exc)
        return None


def _contains(haystack: str, needle: str) -> bool:
    """Case-insensitive containment -- used by every grounding check below.

    BUG FIX: those checks compared exact case, and Polish school CMSs
    routinely render staff tables in ALL CAPS ("JEZYK ANGIELSKI | ANNA
    BUJARKIEWICZ PAULINA GIERZYNSKA ..."). The model returns the name
    normalized to "Anna Bujarkiewicz" -- which is exactly what we want
    stored, and what the salutation/declension layer needs -- so the
    name-in-evidence and name-on-page checks both failed and EVERY staff
    record on such a page was silently dropped. Confirmed directly: SP im.
    Mariana Rejewskiego w Bialych Blotach lists five English teachers in
    caps on its /nauczyciele/ page and came back with no teacher at all.

    Case was never the anti-hallucination property here -- the presence of
    the text on the cited page is. A fabricated quote still fails; only
    casing differences now pass.
    """
    return needle.casefold() in haystack.casefold()


def _name_variants(name: str) -> set[str]:
    """A name counts as grounded if the exact string appears on its own
    source page, OR its Last-First reversal does -- Polish staff tables
    are routinely surname-first, and the system prompt already permits
    the model to reverse that ordering. This just re-checks the reversal
    is honest (actually on the page in ONE of the two orders), not
    invented outright."""
    parts = name.split()
    variants = {name}
    if len(parts) == 2:
        variants.add(f"{parts[1]} {parts[0]}")
    return variants


def _surname(name: str) -> str:
    parts = name.split()
    return parts[-1] if parts else name


def _normalize_ws(text: str) -> str:
    # \xa0 (nbsp) appears throughout Polish CMS output and must compare
    # equal to a plain space, or verbatim-quote checks fail on real quotes.
    return re.sub(r"\s+", " ", text.replace("\xa0", " ")).strip()


# The evidence span must itself name the role -- these are the vocabularies
# a span must contain for its claimed role to count as PROVEN by that span.
# Director evidence is additionally rejected when the span carries a deputy
# marker: "Wicedyrektor: X" / "zastępca dyrektora - X" contains "dyrektor"
# but proves the OPPOSITE of role="director". Precision-first: a span
# mentioning both the director and a deputy is ambiguous, so it proves
# neither and the record is dropped.
_ROLE_EVIDENCE_KEYWORDS: dict[str, tuple[str, ...]] = {
    "director": ("dyrektor", "principal", "headmaster", "headmistress"),
    "deputy_director": ("wicedyrektor", "zastępca", "z-ca", "vice-principal", "deputy"),
    "english_teacher": ("angielsk", "anglist", "english"),
}
_DEPUTY_MARKERS = ("wicedyrektor", "zastępc", "z-ca", "p.o.", "wice-", "vice", "deputy")


def _evidence_proves_role(evidence_lower: str, role: str) -> bool:
    keywords = _ROLE_EVIDENCE_KEYWORDS.get(role)
    if keywords is None:
        # other_teacher / other_staff carry no role claim worth verifying --
        # they are never written to a named contact slot anyway.
        return True
    if not any(k in evidence_lower for k in keywords):
        return False
    if role == "director" and any(m in evidence_lower for m in _DEPUTY_MARKERS):
        return False
    return True


def ground_extraction(
    extraction: SchoolExtraction,
    pages_by_url: dict[str, str],
    school_name: str = "",
    third_party_urls: set[str] | frozenset[str] = frozenset(),
) -> SchoolExtraction:
    """The anti-hallucination gate -- enforced in CODE, not left to the
    system prompt's instructions alone. Policy: a contact may only be
    written when the cited page LITERALLY proves it, so every check here
    binds the claim to one contiguous quote rather than to the page as a
    whole (name-somewhere + quote-somewhere allowed any name on a staff
    page to be paired with any role):
      - source_url must be one of the pages actually given to the model,
        and NOT a third-party page (search results/directories may lead us
        to a school's site but never originate a person/role claim);
      - the evidence quote must appear verbatim on that page;
      - the person's name (or its Last-First reversal) must appear INSIDE
        the evidence quote -- the quote is about this person;
      - the evidence quote must contain the claimed role's own vocabulary
        (and, for director, no deputy marker) -- the quote proves this role;
      - the name must also appear verbatim on the page (cheap re-check);
      - the patron/namesake is rejected as staff even if the model missed it;
      - email is kept only when it appears verbatim on the page, parses as
        an email, AND email_evidence is itself a verbatim page quote
        containing both the surname and the address -- otherwise the email
        is demoted to unattributed_emails (the person survives, the
        unproven pairing does not).
    Never raises -- a record that fails any check is dropped/demoted, not
    an error, since "found nothing usable" is what every other layer of
    this app treats a missing field as."""
    patron_tokens = _patron_name_tokens(school_name)
    grounded_staff: list[StaffRecord] = []
    newly_unattributed: list[str] = []

    for record in extraction.staff:
        if record.role not in TARGET_ROLES:
            continue  # a stray other_teacher/other_staff -- nothing downstream can write it
        page_text = pages_by_url.get(record.source_url)
        if page_text is None:
            continue  # source_url wasn't one of the pages given -- can't be grounded, drop
        if record.source_url in third_party_urls:
            continue  # third-party pages never originate a person/role claim
        page_norm = _normalize_ws(page_text)
        evidence_norm = _normalize_ws(record.evidence)
        if not evidence_norm or not _contains(page_norm, evidence_norm):
            continue  # "evidence" must be an actual quote from the page, not a plausible-sounding paraphrase
        name_variants = {_normalize_ws(v) for v in _name_variants(record.name)}
        if not any(_contains(evidence_norm, variant) for variant in name_variants):
            continue  # the quote must be ABOUT this person, not merely coexist with them on the page
        if not _evidence_proves_role(evidence_norm.lower(), record.role):
            continue  # the quote must state the claimed role itself
        if not any(_contains(page_norm, variant) for variant in name_variants):
            continue  # name (or its reversal) doesn't literally appear on its own cited page
        if _is_patron_name(record.name, patron_tokens):
            continue  # the school's own namesake, never staff

        email = record.email
        if email:
            surname = _surname(record.name)
            email_evidence_norm = _normalize_ws(record.email_evidence or "")
            evidence_ok = (
                bool(email_evidence_norm)
                and _contains(page_norm, email_evidence_norm)  # the pairing quote must itself be real page text
                and _contains(email_evidence_norm, surname)
                and _contains(email_evidence_norm, email)
            )
            if not _contains(page_text, email) or not EMAIL_RE.fullmatch(email) or not evidence_ok:
                newly_unattributed.append(email)
                email = None

        grounded_staff.append(record.model_copy(update={"email": email}))

    extraction.staff = grounded_staff
    extraction.unattributed_emails = list(extraction.unattributed_emails) + newly_unattributed
    return extraction


def ground_vision_extraction(extraction: SchoolExtraction, *, school_website_domain: str | None) -> SchoolExtraction:
    """Vision has no page text to check a name against (the "page" is an
    image), so grounding here is weaker by necessity: require a non-empty
    evidence string (already enforced by the schema), a well-formed email,
    and cap confidence at "medium" unless the email's own domain matches
    the school's real website -- a same-domain email is reasonably strong
    independent evidence the image really is this school's own roster."""
    domain = (school_website_domain or "").lower().removeprefix("www.")
    grounded_staff: list[StaffRecord] = []
    for record in extraction.staff:
        if not record.evidence.strip():
            continue
        email = record.email
        if email and not EMAIL_RE.fullmatch(email):
            email = None
        confidence = record.confidence
        email_domain_matches = bool(email) and domain and email.lower().split("@")[-1].removeprefix("www.") == domain
        if confidence == "high" and not email_domain_matches:
            confidence = "medium"
        grounded_staff.append(record.model_copy(update={"email": email, "confidence": confidence}))
    extraction.staff = grounded_staff
    return extraction


def needs_escalation(extraction: SchoolExtraction | None, pages: list[PreparedPage], still_needed_roles: set[str]) -> bool:
    """At most ONE escalation call (Opus) per school. Opus costs roughly an
    order of magnitude more per token than the routine tier and re-sends the
    entire page bundle, so it must only run where it can actually change the
    outcome. Measured on a real 47-school batch, the previous rules fired for
    43% of schools and 13 of those 20 escalations produced nothing at all --
    that waste is what the two gates below remove.

    Escalation now requires ALL of:
      - a role is still genuinely missing (still_needed_roles -- the caller
        recomputes this from what the routine call actually GROUNDED, not
        from the pre-LLM state), and
      - the bundle contains that role's own vocabulary
        (pages_that_could_prove) -- if the word "dyrektor"/"angielsk" never
        appears in the text we sent, no model can ground a record for it and
        a second opinion is provably pointless, and
      - the bundle contains a real staff-bearing page (bip/staff-listing/
        kontakt tiers). The homepage now carries its own HOMEPAGE_TIER so it
        no longer satisfies this test by accident -- previously every school
        passed it, since the homepage was merged at the default tier 0.

    A None extraction (SDK/parse failure) still escalates unconditionally:
    nothing was learned, so the bundle's contents are still unexamined.
    """
    if extraction is None:
        return True
    if not still_needed_roles:
        return False
    provable_roles = {
        role for role in still_needed_roles if pages_that_could_prove(pages, {role})
    }
    if not provable_roles:
        return False  # the evidence to prove these roles simply isn't in the bundle
    if not any(p.tier <= 2 for p in pages):
        return False
    if not extraction.staff:
        return True
    for role in provable_roles:
        role_records = [r for r in extraction.staff if r.role == role]
        if not role_records or all(r.confidence == "low" for r in role_records):
            return True
    return False


def extract_contacts(
    pages: list[PreparedPage],
    school_name: str,
    city: str | None = None,
    *,
    model: str = HAIKU_MODEL,
    usage_out: dict | None = None,
) -> SchoolExtraction | None:
    """The one routine per-school extraction call -- see cap_pages for the
    per-school page/char budget this expects the caller to have already
    applied. Returns None on any SDK/parse failure (never raises, except
    UsageLimitError which the caller must let propagate to stop the
    batch). usage_out, if given, is updated in place with input/output
    token counts and cost -- an optional back-channel so callers can
    accumulate per-school token stats (see the task's activity-metadata
    requirement) without changing this function's primary return type."""
    if not SDK_AVAILABLE:
        raise CliUnavailableError("claude-agent-sdk is not installed")
    if not pages:
        return SchoolExtraction()

    prompt = _pages_to_prompt(pages, school_name, city)
    text, usage = _run_sync(
        _run_query(prompt, system_prompt=_TEXT_EXTRACTION_SYSTEM_PROMPT, model=model, allowed_tools=[])
    )
    if usage_out is not None:
        usage_out.update(usage)
    if text is None:
        return None
    raw = _parse_json_response(text)
    if raw is None:
        logger.warning("llm_extract: unparseable JSON from model %s", model)
        return None
    return _validate_extraction(raw)


_NAV_PICK_SYSTEM_PROMPT = """You are given the navigation links of one Polish school's website, and the school's official name. Your only job is to say which links most likely lead to a page LISTING TEACHING STAFF -- the page that names individual teachers and ideally the subjects they teach.

What such a page is usually called, in any of these forms: "Kadra", "Kadra pedagogiczna", "Grono pedagogiczne", "Nauczyciele", "Nasi nauczyciele", "Nasz zespol", "Rada pedagogiczna", "Pracownicy", "Wychowawcy", "Specjalisci", or in English "Our Team", "Staff", "Teachers", "Faculty", "Meet the team". A page naming ONLY the head teacher ("Dyrekcja", "Dyrektor") is worth much less than one listing the whole teaching body -- rank it lower, but still include it if nothing better exists.

Rules:
- Judge by the visible label AND the URL slug together. An opaque URL with a telling label counts, and a telling slug with an empty label counts.
- The links may include other hostnames. Include one ONLY if it plainly belongs to THIS school (its own subdomain or its own branded domain). Never pick a different school, a municipal/ministry portal, a parish, a newspaper, an e-register login (Librus, Vulcan, edupage login), or social media.
- Never pick news items, competition results, timetables, calendars, galleries, recruitment forms, RODO/privacy notices, or document archives.
- Pick nothing rather than something irrelevant. An empty list is a valid, useful answer.

Return ONLY minified JSON, no prose, no markdown fence:
{"pages":[{"url":"<exact url as given>","why":"<max 8 words>"}]}
At most 4 entries, best first."""


def pick_staff_pages(
    links: list[tuple[str, str]],
    school_name: str,
    city: str | None = None,
    *,
    max_links: int = 90,
    max_results: int = 4,
    model: str = HAIKU_MODEL,
    usage_out: dict | None = None,
) -> list[str]:
    """Ask the model which of a site's links lead to its teaching-staff
    roster. `links` is (label, url) pairs as scraped, in document order.

    This is the LLM-led answer to the crawl's single biggest miss: keyword
    tiering only finds a roster whose label or slug contains a word someone
    thought to list. Auditing 44 high-scoring schools that reached "basic"
    enrichment found the roster was reachable but untiered on many of them
    -- an image-only nav, an English-only nav ("Our Team"), a bare
    "?id=42" permalink, or a roster on the school's own other subdomain.
    A model reading the nav handles all of those shapes at once, where each
    would otherwise need its own heuristic.

    Returns [] on ANY failure (no SDK, unparseable, timeout) so the caller
    simply proceeds with keyword tiering -- never raises except
    UsageLimitError, which must stop the batch (see module docstring).
    Only URLs present in the input are returned, so the model cannot
    invent a destination."""
    if not SDK_AVAILABLE or not links:
        return []
    trimmed = links[:max_links]
    lines = [
        f"{i}. label={label[:70]!r} url={url}"
        for i, (label, url) in enumerate(trimmed, 1)
    ]
    where = f" in {city}" if city else ""
    prompt = (
        f"School: {school_name}{where}\n\n"
        f"Links found on its website:\n" + "\n".join(lines)
    )
    try:
        text, usage = _run_sync(
            _run_query(prompt, system_prompt=_NAV_PICK_SYSTEM_PROMPT, model=model, allowed_tools=[])
        )
    except CliUnavailableError:
        return []
    if usage_out is not None:
        usage_out.update(usage)
    if not text:
        return []
    raw = _parse_json_response(text)
    if not isinstance(raw, dict):
        return []
    allowed = {url for _, url in trimmed}
    picked: list[str] = []
    for entry in raw.get("pages") or []:
        if not isinstance(entry, dict):
            continue
        url = entry.get("url")
        # Only echo back URLs we actually offered -- a hallucinated or
        # subtly-edited URL would send the crawl somewhere unverified.
        if isinstance(url, str) and url in allowed and url not in picked:
            picked.append(url)
        if len(picked) >= max_results:
            break
    return picked


def extract_from_image(
    path: str, source_url: str, school_name: str, city: str | None = None, *, usage_out: dict | None = None
) -> SchoolExtraction | None:
    """Reads one staff-roster image via the SDK's Read tool (the only tool
    allowed for a vision call) -- the caller is responsible for the
    10MB/content-type check and deleting the temp file afterward (see
    scraper.py's vision-download helper)."""
    if not SDK_AVAILABLE:
        raise CliUnavailableError("claude-agent-sdk is not installed")

    prompt = f"Read the image at this exact path and extract staff: {path}"
    system_prompt = _VISION_SYSTEM_PROMPT.replace("{source_url}", source_url)
    text, usage = _run_sync(
        _run_query(prompt, system_prompt=system_prompt, model=OPUS_MODEL, allowed_tools=["Read"])
    )
    if usage_out is not None:
        usage_out.update(usage)
    if text is None:
        return None
    raw = _parse_json_response(text)
    if raw is None:
        return None
    extraction = _validate_extraction(raw)
    if extraction is None:
        return None
    # Grounding for vision is enforced by the CALLER (jobs.py/scraper.py's
    # validation pass) same as text extraction -- non-empty evidence,
    # EMAIL_RE match, confidence cap unless the email domain matches the
    # school's own site. This function's job stops at "did the model
    # return a well-formed extraction".
    return extraction


def extract_from_pdf(
    path: str, source_url: str, school_name: str, city: str | None = None, *, usage_out: dict | None = None
) -> SchoolExtraction | None:
    """Same contract as extract_from_image -- the caller must have already
    skipped this PDF if it's over MAX_PDF_PAGES pages / MAX_PDF_BYTES
    bytes before calling this."""
    if not SDK_AVAILABLE:
        raise CliUnavailableError("claude-agent-sdk is not installed")

    prompt = f"Read the PDF at this exact path and extract staff: {path}"
    system_prompt = _VISION_SYSTEM_PROMPT.replace("{source_url}", source_url)
    text, usage = _run_sync(
        _run_query(prompt, system_prompt=system_prompt, model=OPUS_MODEL, allowed_tools=["Read"])
    )
    if usage_out is not None:
        usage_out.update(usage)
    if text is None:
        return None
    raw = _parse_json_response(text)
    if raw is None:
        return None
    return _validate_extraction(raw)


def check_cli_available() -> bool:
    """Startup check -- deliberately a cheap PRESENCE check (package
    importable + a plausible local Claude Code credentials file), NOT a
    real query() ping. Confirmed directly (see project notes): even a
    trivial ping call costs ~19-25k tokens of cache-creation overhead
    against the SAME shared 5-hour usage window real extraction calls
    draw from -- paying that on every app restart/reload (frequent in
    this dev environment) would burn real budget for zero benefit.

    The result is cached (see is_llm_usable) and used to gate EVERY real
    per-school call, not just logged -- confirmed directly: a container
    with no working credentials still let extract_contacts() attempt a
    real SDK call, which failed with authentication_failed but sometimes
    left the async generator underneath in a state that never fully
    closed (a real subprocess/pidfd leaked per attempt), and one
    enrichment job was later found hung for 3+ hours on exactly this. A
    failed call's error handling isn't a substitute for never making the
    call in the first place once we already know it can't work."""
    global _llm_usable_cache
    if not SDK_AVAILABLE:
        logger.warning("claude-agent-sdk is not installed -- LLM extraction disabled, regex fallback only")
        _llm_usable_cache = False
        return False
    credentials_path = Path.home() / ".claude" / ".credentials.json"
    if not credentials_path.exists():
        logger.warning(
            "claude-agent-sdk is installed but no local Claude Code credentials found at %s -- "
            "LLM extraction will fall back to regex until the CLI is logged in",
            credentials_path,
        )
        _llm_usable_cache = False
        return False
    logger.info("Claude Code CLI appears available for LLM extraction (presence check only, not a live ping)")
    _llm_usable_cache = True
    return True


_llm_usable_cache: bool | None = None


def is_llm_usable() -> bool:
    """The gate every real per-school call (_run_llm_extraction in
    jobs.py) must check FIRST, before attempting extract_contacts/
    extract_from_image/_pdf at all. Computes and caches check_cli_available()
    on first use if main.py's startup hook hasn't already run it (e.g. a
    script calling into this module directly, like the eval harness)."""
    if _llm_usable_cache is None:
        return check_cli_available()
    return _llm_usable_cache


def ping_cli() -> bool:
    """An on-demand, REAL connectivity check (an actual query() call) --
    unlike check_cli_available(), this spends real usage-window budget,
    so it's never called automatically at startup. Use it interactively
    when you specifically want to confirm the CLI is truly reachable
    right now, not just plausibly configured."""
    if not SDK_AVAILABLE:
        return False
    try:
        text, _usage = _run_sync(
            _run_query("ping", system_prompt="Reply with exactly: PONG", model=HAIKU_MODEL, allowed_tools=[])
        )
    except UsageLimitError:
        logger.warning("Claude Code usage window is currently exhausted")
        return True  # the CLI itself is fine; just temporarily throttled
    except CliUnavailableError:
        logger.warning("Claude Code CLI unreachable", exc_info=True)
        return False
    return text is not None
