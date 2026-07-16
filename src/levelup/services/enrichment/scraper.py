"""Best-effort, multi-source enrichment for a school's contact details.

Crawls the school's own website (homepage plus common Polish school
subpages -- kontakt, o-szkole, dyrekcja, grono pedagogiczne...), then --
if the director or an English teacher still hasn't turned up -- falls
back to a free, no-key web search scoped to the school's own name and
city, and visits whatever it finds (this is the only realistic way to
reach a gmina/powiat/local-news page about a specific school; there's no
reliable way to guess which of Poland's ~2,477 local-government sites
covers a given school without searching for it).

Every URL actually fetched -- successful or not, own-site or found via
search -- is recorded in `sources_checked`, so what was checked stays
visible after the fact. Only ever extracts what's textually present;
anything not found stays None, matching every other "unknown" field in
this app.
"""

from __future__ import annotations

import re
import time
from urllib.parse import urljoin, urlparse

import requests
import urllib3
from bs4 import BeautifulSoup

from levelup.services.enrichment.verifier import email_priority

# Only reached via the SSLError fallback in fetch_page() below, for sites
# with a confirmed-broken certificate chain -- the warning is expected
# there and would otherwise spam every such fetch.
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

EMAIL_RE = re.compile(r"[\w.+-]+@[\w-]+\.[\w.-]+")
PHONE_RE = re.compile(r"(?:tel\.?|telefon)[:\s]*([+\d][\d\s\-()]{6,})", re.IGNORECASE)

# Cloudflare's "email protection" replaces a real mailto/text address with a
# hex-encoded cipher in a data-cfemail attribute (visible text just shows
# "[email protected]") -- ported from a sibling tool's Polish-school scraper,
# which found this a common obfuscation on real school sites. Decoding is a
# simple XOR against the first byte as key, Cloudflare's own published scheme.
def _decode_cf_email(hex_str: str) -> str | None:
    try:
        raw = bytes.fromhex(hex_str)
    except ValueError:
        return None
    if len(raw) < 2:
        return None
    key = raw[0]
    decoded = "".join(chr(b ^ key) for b in raw[1:])
    return decoded if "@" in decoded else None


# Plain-text "user at domain dot tld" obfuscation, and bracketed (at)/(dot)
# variants -- another real, common pattern on Polish school sites that a
# bare EMAIL_RE search would never catch since there's no literal "@".
def _decode_at_dot_obfuscation(text: str) -> str:
    text = re.sub(r"\s*[\[(]\s*at\s*[\])]\s*", "@", text, flags=re.IGNORECASE)
    text = re.sub(r"\s*[\[(]\s*dot\s*[\])]\s*", ".", text, flags=re.IGNORECASE)

    def _join(m: re.Match) -> str:
        domain = re.sub(r"\s+dot\s+", ".", m.group(2), flags=re.IGNORECASE)
        return f"{m.group(1)}@{domain}"

    # Only fires when sandwiched between token-like strings (user, then a
    # domain with at least one "dot"), so it doesn't mangle ordinary
    # sentences that happen to contain the word "at".
    return re.sub(
        r"([a-z0-9._-]{2,})\s+at\s+([a-z0-9-]{2,}(?:\s+dot\s+[a-z0-9-]{2,})+)", _join, text, flags=re.IGNORECASE
    )


# Joomla/WordPress "email address protected by spam bots" cloaking script --
# Polish phrasing. When this appears with no address recovered nearby,
# decoding would require running the page's own JS, which a plain fetch
# can't do -- worth flagging honestly rather than silently returning nothing.
EMAIL_CLOAK_RE = re.compile(
    r"(?i:adres\s+(pocztowy|e-?mail)\s+jest\s+chronion\w*\s+przed\s+(spam\w*|robotami)"
    r"|w[łl]ącz\w*\s+(w\s+przeglądarce\s+)?obs[łl]ug\w*\s+javascript"
    r"|\[?email\s*protected\]?"
    r"|javascript\s+musi\s+by[ćc]\s+w[łl][aą]czon)"
)

# An optional academic/professional title between the keyword and the
# actual name (e.g. "Dyrektor: mgr inż. Jan Kowalski") -- explicit and
# bounded, unlike a generic wildcard gap, which is what let garbage like
# "mają zajęcia" through before (any 20 characters could match, name or not).
# The title itself is matched case-insensitively via the scoped (?i:...)
# group; the name group deliberately stays case-SENSITIVE (its whole point
# is requiring real capitalization as a proper-noun signal).
_TITLE_PREFIX = r"(?:(?i:mgr|dr|inż|prof)\.?\s+){0,2}"
# Exactly two words (first name + surname), each optionally hyphenated for
# compound names ("Anna-Maria", "Kowalska-Nowak") -- deliberately NOT
# extended to a 3rd word. Allowing a 3rd word was meant to cover double
# surnames, but on a flattened staff list it just as often grabbed the
# start of the next line instead ("Teresa Adamczyk Dodatkowe", "Lucyna
# Popławska Zastępca") -- see _COMMON_POLISH_FIRST_NAMES below for how the
# remaining 2-word false positives ("Early Stage", "Zespołu Szkolno") get
# caught.
_NAME_WORD = r"[A-ZŁŚŻŹĆŃÓĘĄ][a-ząćęłńóśźż]+(?:-[A-ZŁŚŻŹĆŃÓĘĄ][a-ząćęłńóśźż]+)?"
_NAME_GROUP = rf"({_NAME_WORD}\s+{_NAME_WORD})"

# BUG FIX: the keyword itself must be matched case-insensitively -- real
# pages overwhelmingly write "Dyrektor" as a capitalized label, not the
# lowercase-only "dyrektor" this pattern required before, which meant it
# essentially never matched real pages. Scoped (?i:...) keeps that
# case-insensitivity local to the keyword, not the whole pattern -- if it
# were a trailing re.IGNORECASE flag instead, the name group's own
# [A-Z...] requirement would also go case-insensitive and start accepting
# lowercase words as "names".
DIRECTOR_RE = re.compile(
    r"(?i:dyrektor[a-zżźćńółęąś]*\s*(?:szko[lł]y)?)\s*[:\-–]?\s*" + _TITLE_PREFIX + _NAME_GROUP
)

# Real staff/subject listings write "English teacher" several different
# ways, each confirmed directly against live school pages:
#   - "język angielski" / "języka angielskiego" (full word, either case)
#   - "j. angielski" (the very common abbreviated form -- e.g. a numbered
#     BIP staff roster: "10. Agnieszka Dudkiewicz j. angielski, geografia")
#   - "nauczyciel języka angielskiego" (the full 3-word job title, common
#     on edupage.org sites, often in ALL CAPS) -- distinct from the
#     shorter "nauczyciel angielskiego", which alone doesn't cover it
#   - "anglista" (informal noun form)
_ENGLISH_KEYWORD = (
    r"(?:nauczyciel(?:ka)?\s+j(?:ę|e)zyka\s+angielski(?:ego)?"
    r"|nauczyciel(?:ka)?\s+angielskiego"
    r"|j(?:ę|e)zyk(?:a)?\s+angielski(?:ego)?"
    r"|j\.\s*angielski(?:ego)?"
    r"|anglista[a-ząćęłńóśźż]*)"
)
ENGLISH_TEACHER_RE = re.compile(
    rf"(?i:{_ENGLISH_KEYWORD})\s*[:\-–]?\s*" + _TITLE_PREFIX + _NAME_GROUP
)

# A legally-mandated BIP (Biuletyn Informacji Publicznej) staff roster is
# usually a flattened table -- "Lp. | Imię i nazwisko | przedmiot" -- where
# the NAME comes first and the role/subject follows ("Józef Gąbka Dyrektor
# szkoły"), the reverse of a prose sentence. Both orders are tried.
#
# Some staff directories put a THIRD thing between name and role --
# confirmed directly: "Agnieszka Szcześniak a.szczesniak@paderewski.lublin.pl
# dyrektorka" (name, then their own email, then the role). An email is an
# unambiguous, self-delimiting token (matched by EMAIL_RE itself, not a
# generic wildcard), so it's safe to let it optionally sit in the gap --
# unlike a free-form wildcard, it can't accidentally swallow real prose.
# Some staff lists also parenthesize the subject right after the name --
# "Kasperek Patrycja (język angielski)" -- so an optional "(" is tolerated
# too.
_NAME_TO_ROLE_CONNECTOR = rf"\s*\(?\s*(?:{EMAIL_RE.pattern}\s+)?\s*"
DIRECTOR_NAME_FIRST_RE = re.compile(
    _NAME_GROUP + _NAME_TO_ROLE_CONNECTOR + r"(?i:dyrektor[a-zżźćńółęąś]*\s*(?:szko[lł]y)?)(?![a-ząćęłńóśźż])"
)
ENGLISH_TEACHER_NAME_FIRST_RE = re.compile(
    _NAME_GROUP + _NAME_TO_ROLE_CONNECTOR + rf"(?i:{_ENGLISH_KEYWORD})"
)

# A subject/role often trails other qualifiers before it, comma-separated
# -- "Aleksandra Fronc wych. klasa 4, język angielski" or "Kornelia Żak
# nauczyciel współorganizujący kształcenie, język angielski" -- confirmed
# directly on live staff pages. The filler is bounded (max 8 words, same
# discipline as DIRECTOR_INSTITUTIONAL_RE's institutional descriptor) and
# a literal comma must directly precede the keyword -- an unanchored
# wildcard gap is exactly the "admits garbage" failure mode from before,
# so this only fires when a real comma marks where the keyword begins.
_ROLE_LIST_FILLER = r"(?:\s+[\wąćęłńóśźżĄĆĘŁŃÓŚŹŻ.\-]+){0,8}?"
ENGLISH_TEACHER_ROLE_LIST_RE = re.compile(
    _NAME_GROUP + _ROLE_LIST_FILLER + rf"\s*,\s*(?i:{_ENGLISH_KEYWORD})"
)

# A "Zespół" (multi-institution complex) BIP page names its director as
# "Dyrektor Zespołu Placówek Oświatowych - Elżbieta Kobus-Jasińska" --
# an institutional descriptor phrase (what they direct) sits between the
# keyword and the name, which DIRECTOR_RE's single optional "szkoły" can't
# cover since the descriptor varies (Zespołu Szkół, Przedszkola, Zespołu
# Placówek Oświatowych...). The separator is required here, not optional
# like in DIRECTOR_RE -- an unbounded gap with no anchor at the end is
# exactly the "wildcard admits garbage" failure mode from before, so this
# only fires when a real dash/colon marks where the descriptor ends and
# the name begins.
_INSTITUTIONAL_FILLER = r"(?:\s+[A-ZŁŚŻŹĆŃÓĘĄ][a-ząćęłńóśźż]+){1,6}"
DIRECTOR_INSTITUTIONAL_RE = re.compile(
    r"(?i:dyrektor[a-zżźćńółęąś]*)" + _INSTITUTIONAL_FILLER + r"\s*[:\-–]\s*" + _TITLE_PREFIX + _NAME_GROUP
)

# Even a tight, 2-word, both-capitalized regex still catches things that
# read as a name shape but aren't one: "Zespołu Szkolno" (a fragment of the
# institution's own name), "Early Stage" (a program's brand name), "Na
# Ostatni" (from the idiom "ostatni dzwonek"/last day of school). A
# capitalization pattern alone can't tell those apart from a real name --
# but a real Polish first name can: this is a deliberately large, boring
# reference list of common Polish given names (not exhaustive -- rare or
# very new first names will be missed, which just means "unknown", not a
# wrong answer), and the first word of any candidate must be one of them.
_COMMON_POLISH_FIRST_NAMES = frozenset(n.lower() for n in [
    "Anna", "Maria", "Katarzyna", "Małgorzata", "Agnieszka", "Barbara", "Ewa",
    "Krystyna", "Elżbieta", "Magdalena", "Joanna", "Teresa", "Danuta", "Halina",
    "Aleksandra", "Monika", "Zofia", "Jadwiga", "Irena", "Beata", "Marta",
    "Dorota", "Urszula", "Grażyna", "Bożena", "Alicja", "Justyna", "Karolina",
    "Renata", "Iwona", "Wanda", "Helena", "Jolanta", "Marzena", "Sylwia",
    "Paulina", "Natalia", "Kamila", "Weronika", "Julia", "Wiktoria", "Amelia",
    "Zuzanna", "Oliwia", "Emilia", "Klaudia", "Patrycja", "Izabela", "Agata",
    "Bogumiła", "Celina", "Diana", "Edyta", "Franciszka", "Genowefa", "Hanna",
    "Ilona", "Janina", "Kinga", "Lucyna", "Łucja", "Ada", "Sabina", "Wioletta",
    "Regina", "Stanisława", "Stefania", "Waleria", "Aniela", "Bronisława",
    "Antonina", "Gabriela", "Nina", "Nikola", "Roksana", "Angelika", "Marlena",
    "Milena", "Dominika", "Ewelina", "Wiesława", "Grazyna", "Bogusława",
    "Mariola", "Marianna", "Bernadeta", "Longina", "Czesława", "Ryszarda",
    "Bogusia", "Zdzisława", "Anastazja", "Blanka", "Estera", "Laura", "Kornelia",
    "Jan", "Andrzej", "Piotr", "Krzysztof", "Stanisław", "Tomasz", "Paweł",
    "Józef", "Marcin", "Marek", "Michał", "Grzegorz", "Jerzy", "Tadeusz",
    "Adam", "Zbigniew", "Henryk", "Ryszard", "Wojciech", "Kazimierz", "Łukasz",
    "Dariusz", "Zenon", "Mariusz", "Sławomir", "Robert", "Rafał", "Bogdan",
    "Waldemar", "Artur", "Jacek", "Roman", "Edward", "Wiesław", "Mieczysław",
    "Janusz", "Antoni", "Franciszek", "Damian", "Sebastian", "Kamil", "Maciej",
    "Bartłomiej", "Bartosz", "Wojciech", "Filip", "Karol", "Szymon", "Igor",
    "Dawid", "Patryk", "Konrad", "Norbert", "Radosław", "Przemysław",
    "Mateusz", "Jakub", "Kacper", "Aleksander", "Oskar", "Julian", "Wiktor",
    "Leon", "Ignacy", "Miłosz", "Nikodem", "Feliks", "Emil", "Bruno",
    # Confirmed directly: a real, correctly-placed English teacher name
    # ("Olha Derepa") was rejected purely because "Olha" wasn't on this
    # list -- Ukrainian teachers have been a real, growing presence in
    # Polish schools since 2022. Not exhaustive, just no longer blind to
    # the single most common transliteration of each name.
    "Olha", "Olga", "Oksana", "Iryna", "Tetiana", "Svitlana", "Kateryna",
    "Yuliia", "Nadiya", "Halyna", "Liudmyla", "Larysa", "Maryna", "Valentyna",
    "Vira", "Andrii", "Ivan", "Bohdan", "Mykola", "Vitalii", "Oleksandr",
    "Yurii", "Serhii", "Dmytro", "Taras", "Viktor",
])


def _normalize_name_order(candidate: str) -> str | None:
    """A 2-word capture isn't always First Last -- Polish staff tables are
    very often alphabetized by SURNAME and printed Last First instead
    (confirmed directly: "Wołk-Łaniewska Marta", "Kasperek Patrycja"), the
    reverse of what the capitalization-only regex assumes. Check both
    words against the first-name list; if only the second is a real first
    name, the words are swapped before returning. Neither word matching is
    still a hard reject -- the reference-list validation itself is
    unchanged, only which word gets checked."""
    words = candidate.split()
    if len(words) != 2:
        return None
    first, second = words
    first_token = re.split(r"-", first)[0].lower()
    second_token = re.split(r"-", second)[0].lower()
    if first_token in _COMMON_POLISH_FIRST_NAMES:
        return candidate
    if second_token in _COMMON_POLISH_FIRST_NAMES:
        return f"{second} {first}"
    return None


def _earliest_valid_match(text: str, patterns: tuple[re.Pattern, ...]) -> str | None:
    """Confirmed real failure mode: a flattened staff table row often reads
    "Begierska Renata Dyrektor Lenda Kamila Wicedyrektor" (surname,
    first name, role, repeated per row) -- so the keyword-first pattern
    (DIRECTOR_RE) treats "Dyrektor" as introducing the NEXT row's name
    ("Lenda Kamila", the deputy) while the name-first pattern correctly
    reads "Begierska Renata Dyrektor" as its own row. Always trying
    keyword-first before name-first (a fixed pattern-priority order) picks
    the wrong one whenever both match. Instead, collect each pattern's
    earliest match and keep whichever one starts first in the text --
    the row a role label actually belongs to is always the name
    immediately before or after it, never a further one two rows down."""
    candidates = []
    for pattern in patterns:
        match = pattern.search(text)
        if match:
            normalized = _normalize_name_order(match.group(1).strip())
            if normalized:
                candidates.append((match.start(), normalized))
    if not candidates:
        return None
    candidates.sort(key=lambda pair: pair[0])
    return candidates[0][1]


# Most Polish school names carry a patron ("... im. Stefana Batorego") -- a
# historical figure honored in the name, not a living staff member. Ported
# from a sibling tool's Polish-school scraper, which found this a real
# false-positive shape: a page mentioning the school's own name/branding
# near a role keyword otherwise reads exactly like "a name near a role".
def _patron_name_tokens(school_name: str) -> set[str]:
    m = re.search(r"\bim\.\s*(.+)$", school_name or "", re.IGNORECASE)
    if not m:
        return set()
    tail = re.split(r"\s+(?:W|WE|Z|ZE)\s+[A-ZŁŚŻŹĆŃÓĘĄ]", m.group(1))[0]
    return {w.lower() for w in re.findall(r"[A-Za-zŁŚŻŹĆŃÓĘĄłśżźćńóęą]+", tail) if len(w) > 2}


def _is_patron_name(candidate: str, patron_tokens: set[str]) -> bool:
    if not patron_tokens:
        return False
    words = [w.lower() for w in candidate.split()]
    return bool(words) and all(w in patron_tokens for w in words)


# Whether the school serves a specific special-education population, marked
# during enrichment from the school's own site (and its official name,
# which for special schools reliably says so). Each tuple is
# (English label stored/shown, Polish phrasings that actually appear on
# Polish school pages / in RSPO names). These specific disability markers
# rarely mean anything else, so they're trusted in page body text as-is.
_SPECIALTY_PATTERNS = tuple(
    (label, re.compile(pattern))
    for label, pattern in (
        (
            "Intellectual / developmental disability",
            r"niepe[łl]nosprawno\w*\s+intelektualn|niepe[łl]nosprawni\w*\s+intelektualn"
            r"|upo[śs]ledzeni\w*\s+umys[łl]ow|niepe[łl]nosprawno\w*\s+umys[łl]ow",
        ),
        ("Autism spectrum", r"autyz\w*|autystyczn\w*|zespo[łl]\w*\s+aspergera|aspergera"),
        (
            "Physical / motor disability",
            r"niepe[łl]nosprawno\w*\s+ruchow|niepe[łl]nosprawni\w*\s+ruchow|narz[aą]d\w*\s+ruchu",
        ),
        ("Hearing impairment", r"nies[łl]ysz\w*|s[łl]abos[łl]ysz\w*|niedos[łl]ysz\w*|niedos[łl]uch\w*"),
        ("Visual impairment", r"niewidom\w*|s[łl]abowidz\w*|niedowidz\w*"),
        ("Integration classes", r"integracyjn\w*"),
        ("Socio-therapy / youth care unit", r"socjoterap\w*|m[łl]odzie[żz]owy\s+o[śs]rodek"),
    )
)

# "Special-needs school" is the one label whose keyword ("specjaln") also
# appears in innocent contexts -- "oferta specjalna" (special offer), a
# technikum's "specjalność" (major), the adverb "specjalnie". In page BODY
# text it's only trusted inside an explicit school/education phrasing; in
# the school's OWN official NAME a bare "specjaln" is reliable (RSPO names
# carry no marketing copy).
_SPECIAL_SCHOOL_IN_TEXT = re.compile(
    r"szko[łl]\w*\s+specjaln|specjaln\w*\s+o[śs]rodek|o[śs]rodek\s+szkolno-?\s*wychowawcz"
    r"|kszta[łl]ceni\w*\s+specjaln|specjaln\w*\s+potrzeb\w*\s+edukacyjn|\bsosw\b"
)
_SPECIAL_SCHOOL_IN_NAME = re.compile(r"\bspecjaln|o[śs]rodek\s+szkolno-?\s*wychowawcz|\bsosw\b")


def _detect_specialties(text: str, *, is_name: bool = False) -> set[str]:
    """Labels for any special-education population the text indicates. Never
    a guess: only explicit Polish phrasing fires it, and a school with none
    stays blank like every other unknown field here. `is_name=True` widens
    only the ambiguous "specjaln" marker to a bare match, safe against an
    official name but not against free page text."""
    if not text:
        return set()
    low = text.lower()
    found = {label for label, pattern in _SPECIALTY_PATTERNS if pattern.search(low)}
    special_re = _SPECIAL_SCHOOL_IN_NAME if is_name else _SPECIAL_SCHOOL_IN_TEXT
    if special_re.search(low):
        found.add("Special-needs school")
    return found


# Same-site subpages worth following, ranked by how likely they are to
# actually name a person. BIP (Biuletyn Informacji Publicznej) comes
# first: Polish public schools are legally required (Ustawa o dostępie do
# informacji publicznej) to publish one, and it's a standardized format --
# but it's typically reached two hops out (Home -> "BIP" link -> "Rada
# Pedagogiczna"/staff roster link), not directly off the homepage, which
# is why the crawl below can follow links discovered on ANY visited page,
# not just the homepage's own.
SUBPAGE_KEYWORDS_BY_PRIORITY = (
    ("bip", "biuletyn informacji publicznej"),
    (
        # "dyrektor" (the person/title) is deliberately separate from
        # "dyrekcja" (the office/administration) -- BIP sites very often
        # link directly to a page titled just "Dyrektor szkoły", which
        # "dyrekcja" alone does not substring-match.
        "dyrektor", "dyrekcja", "grono-pedagogiczne", "grono pedagogiczne", "nauczyciele",
        "kadra", "pracownicy", "rada-pedagogiczna", "rada pedagogiczna", "dane podstawowe",
    ),
    ("kontakt", "wladze", "władze", "struktura"),
    ("o-szkole", "o-nas"),
    # "Redakcja BIP" is nominally just editorial credits for the BIP page
    # itself, but Polish BIP regulations attribute publishing
    # responsibility to someone -- often literally the director -- so this
    # page sometimes IS the one that names them (confirmed directly: one
    # school's "Redakcja BIP" page reads "Dyrektor Zespołu Placówek
    # Oświatowych - Elżbieta Kobus-Jasińska"). Worth a low-priority look,
    # never worth excluding, since the more common case is boilerplate.
    ("redakcja-bip", "redakcja bip"),
)
SUBPAGE_EXCLUDE_KEYWORDS = (
    "rodo", "polityka-prywatnosci", "polityka prywatności", "regulamin", "klauzula",
    # Pure BIP usage-instructions boilerplate -- confirmed directly (both
    # Polish text and site structure) to never contain staff/director
    # names, only "how BIP works" navigation copy. Its label contains
    # "bip" and would otherwise falsely inherit BIP's top crawl priority.
    "instrukcja-korzystania-z-bip", "instrukcja korzystania z bip",
)

# Some private/international school groups share ONE domain across several
# legally-separate schools (confirmed directly: paderewski.lublin.pl's
# homepage is a hub linking out to "Międzynarodowa Szkoła Podstawowa" and
# "Międzynarodowe Liceum Ogólnokształcące" as SEPARATE sections, neither of
# which is labeled "bip"/"kontakt"/"dyrekcja" etc, so the crawler never
# followed either -- it just gave up on the hub page itself). RSPO's
# recorded website_url often points at this shared hub, not the specific
# school's own section. A link is treated as "the entrance to THIS
# school's own section" -- and given priority above even BIP -- only when
# its visible label shares a level-type word (liceum, technikum, a
# "podstaw-" stem, etc.) with the school's OWN official name.
#
# Matching the level-word alone isn't enough, though -- confirmed directly:
# a perfectly ordinary standalone school (not part of any hub) also has
# "podstaw-" in its OWN name, and its homepage has plenty of unrelated,
# long document-title links that happen to mention "w szkole podstawowej"
# in passing ("Regulamin korzystania z posiłków w szkole podstawowej im.
# Ireny Kosmowskiej w Bieniowicach", 12 words) -- these got wrongly
# promoted to top priority, displacing the real BIP/staff links and
# exhausting the crawl budget on a lunch-fees policy document. A genuine
# hub-nav entry is short -- just the sibling school's name, nothing else
# -- so the label is also bounded to a handful of words; a long sentence
# that merely mentions the school's own type doesn't qualify.
_SCHOOL_LEVEL_STEMS = ("liceum", "technikum", "podstaw", "gimnazjum", "przedszkol")
_HUB_LINK_MAX_WORDS = 6


def _is_own_school_hub_link(label: str, school_name: str) -> bool:
    if not label or len(label.split()) > _HUB_LINK_MAX_WORDS:
        return False
    school_name_lower = school_name.lower()
    return any(stem in school_name_lower and stem in label for stem in _SCHOOL_LEVEL_STEMS)

# "bip" is short enough to collide with unrelated hyphenated slugs -- the
# Joomla-based BIP engine that many Polish schools use names its own
# editorial/pagination component "redakcja-bip", which contains "bip" as a
# bare substring. Without a boundary check, every internal CMS nav link on
# a BIP subdomain (article prev/next, admin links) would falsely count as
# a top-priority BIP match, drowning out the real "Rada Pedagogiczna"
# staff-roster link in the crawl budget. Hyphen does NOT count as a valid
# boundary here -- that's precisely how "redakcja-bip" collides.
_AMBIGUOUS_SHORT_KEYWORDS = frozenset({"bip"})

# "rodo" has the OPPOSITE problem: it's a bare substring INSIDE ordinary
# Polish words, not just hyphen-joined slugs. Confirmed directly: the
# exclude-list check rejected a school's own "Międzynarodowe Liceum"
# (international) hub link outright because "międzynaRODOwe" contains
# "rodo" mid-word. Real RODO/GDPR pages always delimit it from other
# LETTERS (a hyphenated slug like "polityka-rodo", or standalone "RODO" as
# a label) -- so hyphen must count as a valid boundary here, unlike "bip".
_MIDWORD_RISK_KEYWORDS = frozenset({"rodo"})
_PL_LETTERS = "a-ząćęłńóśźżA-ZĄĆĘŁŃÓŚŹŻ"


def _keyword_matches(keyword: str, haystack: str) -> bool:
    if keyword in _AMBIGUOUS_SHORT_KEYWORDS:
        return bool(re.search(rf"(?:^|[/.\s]){re.escape(keyword)}(?:$|[/.\s])", haystack))
    if keyword in _MIDWORD_RISK_KEYWORDS:
        return bool(re.search(rf"(?<![{_PL_LETTERS}]){re.escape(keyword)}(?![{_PL_LETTERS}])", haystack))
    return keyword in haystack


def _dedup_key(url: str) -> str:
    """Collapses http/https, www/non-www, and trailing-slash variants of
    the same page to one key so the crawl budget isn't wasted re-fetching
    a page it already has under a slightly different URL spelling."""
    parsed = urlparse(url)
    netloc = parsed.netloc.lower().removeprefix("www.")
    path = parsed.path.rstrip("/")
    return f"{netloc}{path}"


def _is_bip_url(url: str) -> bool:
    """True once a URL is already inside the BIP section (bip.school.pl,
    or school.pl/bip/...), as opposed to a link elsewhere that merely
    points into it. Every internal link on a BIP site's own pages --
    pagination, the font-size/contrast accessibility toggles, "redakcja"
    housekeeping pages -- lives under that same host/path, so testing for
    the literal keyword "bip" against them is always true and would
    promote all of that boilerplate to tier 0. The "bip" tier should only
    fire for the one link that gets you INTO the BIP site from outside."""
    parsed = urlparse(url)
    if "bip" in parsed.netloc.lower().split("."):
        return True
    return "bip" in [seg for seg in parsed.path.lower().split("/") if seg]

MAX_SAME_SITE_PAGES = 8
MAX_SEARCH_RESULTS_PER_QUERY = 3
REQUEST_DELAY_SECONDS = 0.4  # light politeness pause between fetches

# Headless-browser fallback budget -- renders are far slower than a plain
# fetch (a real browser + JS execution per page), so the JS path is kept
# tight and only ever runs when a SPA shell was actually detected.
MAX_RENDERED_PAGES = 6
RENDER_NAV_TIMEOUT_MS = 20000
RENDER_IDLE_TIMEOUT_MS = 6000
NON_HTML_EXTENSIONS = (".pdf", ".doc", ".docx", ".xls", ".xlsx", ".jpg", ".jpeg", ".png", ".gif", ".zip")

# Confirmed directly: a JS-rendered homepage (React/Vue-driven nav) can have
# ZERO <a href> tags anywhere in its raw server response, so link discovery
# finds nothing to follow at all -- even though a page like "/dyrekcja/"
# exists and returns real server-rendered content when fetched directly
# (jadwiga.lublin.pl was exactly this case). Probing common slugs directly
# is the only way to reach such a page without running the site's own JS.
# Only used as a last resort, when link discovery truly found nothing.
COMMON_PROBE_SLUGS = (
    "kontakt", "dyrekcja", "kadra", "grono-pedagogiczne", "nauczyciele",
    "pracownicy", "kadra-pedagogiczna", "nasi-nauczyciele", "o-szkole/kontakt",
)


def _normalize_url(url: str) -> str:
    return url if url.startswith(("http://", "https://")) else f"http://{url}"


def _same_organization_host(url_a: str, url_b: str) -> bool:
    """True when both URLs share a host once a leading "www." is
    stripped -- treats "primaryschool.ke.edu.pl" and
    "www.primaryschool.ke.edu.pl" as the same site (a bare string
    comparison would wrongly call these "different hosts"), while still
    telling apart genuinely distinct subdomains like
    "sp.fundacjaszkolna.edu.pl" vs. "fundacjaszkolna.edu.pl" -- a shared
    hub domain vs. one specific school's own dedicated subsite."""
    host_a = urlparse(url_a).netloc.lower().removeprefix("www.")
    host_b = urlparse(url_b).netloc.lower().removeprefix("www.")
    return host_a == host_b


def _hostname_fallback_variant(url: str) -> str | None:
    """When the exact stored hostname doesn't resolve/connect at all, this
    is the one structurally-obvious same-organization variant worth
    trying before giving up -- confirmed directly: RSPO recorded a "www."
    for a school whose real site lives under a different subdomain, and
    that exact "www." host has no DNS record at all, while the bare
    domain (a shared hub for a group of schools under that foundation)
    resolves fine. Deliberately narrow: only a www-add/www-strip swap on
    the SAME host, never a guessed subdomain or a different domain
    entirely -- that would risk landing on an unrelated site and
    mistaking it for this school's own."""
    parsed = urlparse(url)
    host = parsed.netloc
    if not host:
        return None
    if host.lower().startswith("www."):
        return url.replace(host, host[4:], 1)
    return url.replace(host, f"www.{host}", 1)


# A BIP is very commonly hosted on its own subdomain of the same
# organization (bip.szkola.pl vs. www.szkola.pl or szkola.pl) precisely
# because it's often a separate mandated system, not a page within the
# main site -- comparing the exact hostname would wrongly treat that as
# "a different site" and refuse to follow it. Comparing the registrable
# domain instead (the part actually owned/registered) still correctly
# rejects genuinely unrelated domains (Facebook, YouTube, Padlet...).
_SECOND_LEVEL_SUFFIXES = frozenset({"com", "edu", "gov", "net", "org", "biz", "info", "mil", "waw"})


def _registrable_domain(netloc: str) -> str:
    host = netloc.split(":")[0].lower().removeprefix("www.")
    parts = host.split(".")
    if len(parts) <= 2:
        return host
    if parts[-2] in _SECOND_LEVEL_SUFFIXES:
        return ".".join(parts[-3:])
    return ".".join(parts[-2:])


# A bare "Mozilla/5.0" is itself a bot-detection signal on some sites --
# a full, current browser UA string is less likely to get silently
# filtered/blocked than an obviously-fake one.
USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/126.0 Safari/537.36"
)


def fetch_page(url: str) -> str | None:
    try:
        resp = requests.get(url, timeout=15, headers={"User-Agent": USER_AGENT})
        resp.raise_for_status()
        return resp.text
    except requests.exceptions.SSLError:
        # Confirmed directly: some Polish school sites (e.g. lo2.lublin.eu)
        # serve an incomplete certificate chain (missing intermediate) --
        # the content itself is fine, browsers just cross-reference the
        # missing cert from elsewhere. This is public, read-only content
        # with no data submitted, so falling back to an unverified request
        # only when strict verification specifically fails is a reasonable
        # trade -- it's not blanket-disabling verification for every site.
        try:
            resp = requests.get(url, timeout=15, headers={"User-Agent": USER_AGENT}, verify=False)
            resp.raise_for_status()
            return resp.text
        except requests.RequestException:
            return None
    except requests.RequestException:
        return None


def _find_subpage_links(soup: BeautifulSoup, base_url: str, school_name: str = "") -> list[tuple[int, str]]:
    """Returns (priority_tier, absolute_url) pairs -- lower tier is more
    valuable to visit first. Tiers are compared globally across the whole
    crawl frontier (see scrape_school_website), not just within one page,
    so a BIP link discovered on page 3 still jumps ahead of a merely
    "kontakt"-tier link discovered on page 1."""
    base_domain = _registrable_domain(urlparse(base_url).netloc)
    # Once we're already inside the BIP section, every one of its own
    # internal links (pagination, accessibility toggles, "redakcja"
    # housekeeping) lives under that same bip host/path and would
    # otherwise all match the "bip" keyword and falsely inherit tier 0.
    tiers = SUBPAGE_KEYWORDS_BY_PRIORITY[1:] if _is_bip_url(base_url) else SUBPAGE_KEYWORDS_BY_PRIORITY
    tier_offset = len(SUBPAGE_KEYWORDS_BY_PRIORITY) - len(tiers)
    seen: set[str] = set()
    found: list[tuple[int, str]] = []

    for a in soup.select("a[href]"):
        href = a["href"]
        label = a.get_text(" ").strip().lower()
        haystack = f"{href.lower()} {label}"
        if any(_keyword_matches(kw, haystack) for kw in SUBPAGE_EXCLUDE_KEYWORDS):
            continue
        if school_name and _is_own_school_hub_link(label, school_name):
            tier = -1  # above even BIP -- this is the entrance to the right site section at all
        else:
            tier = next((i for i, kws in enumerate(tiers) if any(_keyword_matches(kw, haystack) for kw in kws)), None)
            if tier is None:
                continue
            tier += tier_offset
        full = urljoin(base_url, href)
        if _registrable_domain(urlparse(full).netloc) != base_domain:
            continue  # same organization only (subdomains OK, e.g. bip.szkola.pl)
        if full in seen or full == base_url:
            continue
        if full.lower().split("?")[0].endswith(NON_HTML_EXTENSIONS):
            continue  # skip PDFs/images/docs -- not a page worth parsing
        seen.add(full)
        found.append((tier, full))

    return found


def _collect_candidate_emails(soup: BeautifulSoup, text: str) -> list[str]:
    """Every address findable on the page, not just the first one --
    picking the single best one (personal > shared office > recruitment)
    requires seeing all of them first. Cloudflare's cipher is decoded
    first since it replaces the real address entirely (a plain
    mailto:/text search would only ever find the "[email protected]"
    placeholder, never the actual one)."""
    candidates: list[str] = []
    for el in soup.select("[data-cfemail]"):
        decoded = _decode_cf_email(el["data-cfemail"])
        if decoded and EMAIL_RE.fullmatch(decoded):
            candidates.append(decoded)
    for a in soup.select('a[href^="mailto:"]'):
        candidate = a["href"].split("mailto:")[1].split("?")[0].strip()
        if EMAIL_RE.fullmatch(candidate):
            candidates.append(candidate)
    candidates.extend(EMAIL_RE.findall(text))

    seen: set[str] = set()
    deduped: list[str] = []
    for c in candidates:
        # Trailing sentence punctuation gets swept into the match when an
        # address ends a sentence ("...@smsw.pl." / "...@smsw.pl,") -- strip
        # it so it isn't kept as a distinct, malformed duplicate.
        c = c.rstrip(".,;:)")
        key = c.lower()
        if key not in seen:
            seen.add(key)
            deduped.append(c)
    return deduped


_NAME_GROUP_RE = re.compile(_NAME_GROUP)
_ENGLISH_KEYWORD_RE = re.compile(rf"(?i:{_ENGLISH_KEYWORD})")
# A run-together staff paragraph delimits each teacher with an academic
# title ("mgr Jan Kowalski – ..."). Split just before each so one teacher's
# subject cannot bind to the NEXT teacher's name.
_TITLE_SPLIT_RE = re.compile(
    r"(?=(?<![\wąćęłńóśźżĄĆĘŁŃÓŚŹŻ])(?:mgr|dr|in[żz]|prof|lic|ks)\.?\s+[A-ZŁŚŻŹĆŃÓĘĄ])"
)


def _staff_entries(soup: BeautifulSoup) -> list[str]:
    """One text snippet per staff 'entry': a table ROW (its cells joined, so
    a name cell and its subject cell stay together), a list item / paragraph
    line (split on <br>), and each title-prefixed segment of a run-together
    paragraph. Matching a subject to a name WITHIN one entry is what stops
    the extractor from grabbing the ADJACENT teacher -- the "read the row,
    not the whole flattened column" fix."""
    entries: list[str] = []
    for tr in soup.find_all("tr"):
        row = re.sub(r"\s+", " ", tr.get_text(" ", strip=True))
        if row:
            entries.append(row)
    for el in soup.find_all(["li", "dd", "p"]):
        for line in el.get_text("\n").split("\n"):
            line = re.sub(r"\s+", " ", line).strip()
            if not line:
                continue
            parts = [p.strip() for p in _TITLE_SPLIT_RE.split(line) if p.strip()]
            entries.extend(parts if len(parts) > 1 else [line])
    return entries


def _person_name_in(entry: str, patron_tokens: set[str]) -> str | None:
    """The first real person name in a single entry -- validated against the
    first-name reference list, with the school's own patron excluded."""
    for m in _NAME_GROUP_RE.finditer(entry):
        cand = _normalize_name_order(m.group(1).strip())
        if cand and not _is_patron_name(cand, patron_tokens):
            return cand
    return None


def _english_teacher_from_entries(soup: BeautifulSoup, patron_tokens: set[str]) -> str | None:
    """The English teacher, read per-entry: find the entry that names the
    English-subject keyword and take the person named in THAT entry. Because
    each entry is one teacher, this reads "Bednarczyk Magdalena – język
    angielski" (name-first) and "j. angielski: Anna Kowalska" (keyword-first)
    correctly, and never binds "język angielski" to the next teacher listed
    right after it (confirmed real failures: a Spanish teacher and an IT
    teacher were being tagged as the English teacher)."""
    for entry in _staff_entries(soup):
        if _ENGLISH_KEYWORD_RE.search(entry):
            name = _person_name_in(entry, patron_tokens)
            if name:
                return name
    return None


def _extract(html: str, url: str, school_name: str = "") -> dict:
    soup = BeautifulSoup(html, "html.parser")
    # A <br> is a line break between staff entries; turn it into a real
    # newline so run-together teacher lines separate into distinct entries.
    for br in soup.find_all("br"):
        br.replace_with("\n")
    # &nbsp; (U+00A0) and other unicode whitespace collapse to a plain
    # space -- otherwise it can end up embedded inside a captured name.
    text = re.sub(r"\s+", " ", soup.get_text(" "))
    text = _decode_at_dot_obfuscation(text)

    # Every candidate on the page is returned, not just one "best" pick --
    # whether an address is personal can only be judged against a SPECIFIC
    # person's name, and both names might not even be known yet while this
    # one page is being read (the director could be found on a later
    # page). The actual name-matching happens once the whole crawl is
    # done, in jobs.py.
    candidate_emails = _collect_candidate_emails(soup, text)
    email_cloak_detected = not candidate_emails and bool(EMAIL_CLOAK_RE.search(text))

    # A client-rendered SPA (React/Vue) serves an almost-empty shell: a lone
    # <div id="root">/<div id="app"> mount point and a "you must enable
    # JavaScript" <noscript>, with the real staff/contact content only ever
    # painted in by JS a plain fetch can't run (confirmed directly:
    # szkolnastrona.pl and edupage.org sites). Detecting it lets enrichment
    # report *why* nothing was found instead of a silent, misleading blank.
    mount = soup.find(id="root") or soup.find(id="app")
    js_app_shell = bool(mount) and len(re.sub(r"\s+", "", text)) < 250

    phone = None
    match = PHONE_RE.search(text)
    if match:
        phone = re.sub(r"\s+", " ", match.group(1)).strip()

    patron_tokens = _patron_name_tokens(school_name)

    director_name = _earliest_valid_match(text, (DIRECTOR_RE, DIRECTOR_NAME_FIRST_RE, DIRECTOR_INSTITUTIONAL_RE))
    if director_name and _is_patron_name(director_name, patron_tokens):
        director_name = None
    # PRIMARY: read the English teacher per staff-entry (see
    # _english_teacher_from_entries) so the subject binds to its own row's
    # name, not the adjacent teacher's. This handles the dominant Polish
    # layout "Name – subjects" (one teacher per row/line), which the old
    # flattened keyword-first scan read wrong.
    english_teacher_name = _english_teacher_from_entries(soup, patron_tokens)
    # FALLBACK: the header-group layout ("Język angielski:" then a LIST of
    # names in separate elements) has the keyword and names in DIFFERENT
    # entries, so no single entry holds both. Only here is keyword-first on
    # the flattened text the right reading -- and it runs only when the
    # per-entry pass found nothing, so it can't override a correct match.
    if english_teacher_name is None:
        for pattern in (ENGLISH_TEACHER_RE, ENGLISH_TEACHER_NAME_FIRST_RE, ENGLISH_TEACHER_ROLE_LIST_RE):
            match = pattern.search(text)
            if match:
                normalized = _normalize_name_order(match.group(1).strip())
                if normalized and not _is_patron_name(normalized, patron_tokens):
                    english_teacher_name = normalized
                    break

    return {
        "director_name": director_name,
        "english_teacher_name": english_teacher_name,
        "emails": candidate_emails,
        "phone": phone,
        "source_url": url,
        "subpage_links": _find_subpage_links(soup, url, school_name),
        "email_cloak_detected": email_cloak_detected,
        # Speciality is derived from the school's official NAME only (seeded
        # in scrape_school_website), never from page body text. Scanning body
        # text produced false positives: every Polish public site carries a
        # mandatory accessibility declaration ("Deklaracja dostępności") that
        # mentions niewidomi/słabowidzący/niesłyszący/niepełnosprawni about
        # the WEBSITE, and Montessori/marketing copy trips specjaln/
        # integracyjn -- none of which mean the school serves that population.
        "specialties": set(),
        "js_app_shell": js_app_shell,
    }


def _search_duckduckgo(query: str, max_results: int = MAX_SEARCH_RESULTS_PER_QUERY) -> list[str]:
    """Free, no-key web search via DuckDuckGo's HTML endpoint -- the only
    realistic way to reach a voivodeship/powiat/gmina/local-news page
    about one specific school. This is scraping a search results page,
    not a real API: a layout change or rate limit just yields fewer or no
    links, never an exception that fails the whole enrichment."""
    try:
        resp = requests.get(
            "https://html.duckduckgo.com/html/",
            params={"q": query},
            timeout=10,
            headers={"User-Agent": USER_AGENT},
        )
        resp.raise_for_status()
    except requests.RequestException:
        return []

    soup = BeautifulSoup(resp.text, "html.parser")
    links: list[str] = []
    for a in soup.select("a.result__a"):
        href = a.get("href")
        if href and href.startswith(("http://", "https://")):
            links.append(href)
        if len(links) >= max_results:
            break
    return links


def _merge(result: dict, found: dict) -> None:
    """In-place: fills whichever of director/teacher/phone is still
    missing (first real find wins), and records the first source that
    contributed a find. Every email candidate from every page is kept
    (union, never "first/best wins") -- which one belongs to which
    person can only be judged later, once both names are known."""
    contributed = False
    for field in ("director_name", "english_teacher_name", "phone"):
        if not result.get(field) and found.get(field):
            result[field] = found[field]
            contributed = True

    new_emails = found.get("emails") or []
    if new_emails:
        before = len(result["all_emails"])
        result["all_emails"].update(new_emails)
        if len(result["all_emails"]) > before:
            contributed = True

    # Specialties accumulate (union) across every page -- a "special school"
    # marker on one page and a "visual impairment" marker on another are
    # both true of the same school. Deliberately not counted as a source
    # "contribution": it never establishes which page is the contact source.
    new_specialties = found.get("specialties")
    if new_specialties:
        result["specialties"].update(new_specialties)

    if contributed and not result.get("source_url"):
        result["source_url"] = found["source_url"]


def _is_complete(result: dict) -> bool:
    # A recruitment-tier email alone doesn't count as "done" -- it stops
    # the crawler from spending its remaining page budget looking for a
    # personal or office address that might still be a click away. Any
    # office-tier candidate (or better) is good enough to stop on, though;
    # holding out for a confirmed-personal one specifically would burn the
    # whole budget on schools where no such address exists at all (final
    # personal-vs-generic attribution happens after the crawl, in jobs.py).
    emails = result.get("all_emails") or set()
    good_enough_email = bool(emails) and min((email_priority(e) for e in emails), default=2) < 2
    return bool(result["director_name"] and result["english_teacher_name"] and good_enough_email)


def _render_page(browser, url: str, sources_checked: list[dict]) -> str | None:
    """Render one URL in the headless browser and return its post-JS HTML.
    Best-effort: any failure records the URL as unreachable (tagged
    rendered) and returns None -- it never raises into the crawl."""
    page = None
    try:
        page = browser.new_page(user_agent=USER_AGENT)
        page.goto(url, timeout=RENDER_NAV_TIMEOUT_MS, wait_until="domcontentloaded")
        try:
            # Let client-side data fetches settle; if the network never fully
            # idles (analytics/polling), just take whatever rendered so far.
            page.wait_for_load_state("networkidle", timeout=RENDER_IDLE_TIMEOUT_MS)
        except Exception:  # noqa: BLE001 -- timeout/renderer hiccup is expected, not fatal
            pass
        html = page.content()
        sources_checked.append({"url": url, "status": "ok", "rendered": True})
        return html
    except Exception:  # noqa: BLE001 -- one page failing must not sink the render pass
        sources_checked.append({"url": url, "status": "unreachable", "rendered": True})
        return None
    finally:
        if page is not None:
            try:
                page.close()
            except Exception:  # noqa: BLE001
                pass


def _scrape_with_browser(homepage: str, school_name: str, result: dict, sources_checked: list[dict]) -> bool:
    """Headless-browser fallback for client-rendered (SPA) sites the plain
    fetch can't read (edupage.org, szkolnastrona.pl, ...). Renders the
    homepage and a bounded, priority-ordered set of its own staff/contact
    subpages, extracting from the real post-JS DOM. Returns True if at least
    one page rendered. Entirely best-effort and self-contained: if Playwright
    (or its browser binary) isn't installed, or launch fails, it no-ops and
    the caller's web-search fallback still runs."""
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        return False

    rendered_any = False
    try:
        with sync_playwright() as pw:
            browser = pw.chromium.launch(headless=True)
            try:
                visited: set[str] = {_dedup_key(homepage)}
                pages_rendered = 0

                html = _render_page(browser, homepage, sources_checked)
                pages_rendered += 1
                if not html:
                    return False
                rendered_any = True
                found = _extract(html, homepage, school_name)
                _merge(result, found)
                frontier: list[tuple[int, str]] = list(found["subpage_links"])

                while frontier and pages_rendered < MAX_RENDERED_PAGES and not _is_complete(result):
                    frontier.sort(key=lambda pair: pair[0])
                    _tier, link = frontier.pop(0)
                    if _dedup_key(link) in visited:
                        continue
                    visited.add(_dedup_key(link))
                    sub_html = _render_page(browser, link, sources_checked)
                    pages_rendered += 1
                    if sub_html:
                        sub_found = _extract(sub_html, link, school_name)
                        _merge(result, sub_found)
                        frontier.extend(
                            pair for pair in sub_found["subpage_links"] if _dedup_key(pair[1]) not in visited
                        )
            finally:
                browser.close()
    except Exception:  # noqa: BLE001 -- launch/driver failure must not fail the whole enrichment
        return rendered_any
    return rendered_any


def scrape_school_website(school_name: str, city: str | None, website_url: str | None) -> dict:
    result = {
        "director_name": None,
        "english_teacher_name": None,
        # Every email candidate ever seen across the whole crawl -- which
        # one (if any) actually belongs to the director or English
        # teacher is decided afterward, in jobs.py, once both names are
        # final.
        "all_emails": set(),
        "phone": None,
        "source_url": None,
        "email_cloak_detected": False,
        # Set only when the crawl finds a better URL than the one passed
        # in -- either a same-organization host that actually resolves
        # (the stored one didn't), or the school's own dedicated subsite
        # reached via a shared hub domain. None means "what was passed in
        # is still the best known address, nothing to correct."
        "discovered_website_url": None,
        # Special-education population(s) the school serves. Seeded from the
        # official name (a special school's name reliably says so), then
        # unioned with whatever the crawled pages themselves indicate.
        "specialties": _detect_specialties(school_name, is_name=True),
        # True when the school's own site is a client-rendered SPA whose real
        # content a plain fetch can't see -- so "nothing found" is explained,
        # not mistaken for a school that simply has no info online.
        "js_app_shell": False,
        # True when the headless-browser fallback actually rendered such a
        # site, i.e. the details below were read from the real post-JS DOM.
        "js_render_used": False,
    }
    sources_checked: list[dict] = []

    def _note_cloak(found: dict) -> None:
        if not result["all_emails"] and found.get("email_cloak_detected"):
            result["email_cloak_detected"] = True

    # 1. The school's own website: homepage, then same-site subpages,
    # prioritized (BIP > staff listings > kontakt > generic "about"). This
    # can go more than one hop deep -- a BIP link is almost never on the
    # homepage's own staff roster page directly, it's "Home -> BIP ->
    # Rada Pedagogiczna" -- so newly-discovered links from ANY visited page
    # rejoin the same priority-sorted frontier, not just the homepage's.
    # A homepage that doesn't even resolve is itself a real, recorded
    # outcome, not treated differently from any other unreachable source.
    if website_url:
        homepage = _normalize_url(website_url)
        visited: set[str] = {_dedup_key(homepage)}
        frontier: list[tuple[int, str]] = []
        pages_fetched = 0
        effective_homepage = homepage
        own_school_subsite_url: str | None = None
        hub_fallback_found: dict | None = None

        html = fetch_page(homepage)
        pages_fetched += 1
        if html:
            sources_checked.append({"url": homepage, "status": "ok"})
        else:
            sources_checked.append({"url": homepage, "status": "unreachable"})
            # NOTE: deliberately NOT gated on `_dedup_key(variant) not in
            # visited` -- _dedup_key() treats www/non-www as the same page
            # (so the crawl doesn't re-fetch a page it already HAS), but
            # here the homepage fetch just failed outright, so nothing
            # was actually retrieved under that key yet. This is a single,
            # bounded retry, not part of the general "already seen" check.
            variant = _hostname_fallback_variant(homepage)
            if variant and variant != homepage and pages_fetched < MAX_SAME_SITE_PAGES:
                variant_html = fetch_page(variant)
                pages_fetched += 1
                if variant_html:
                    sources_checked.append({"url": variant, "status": "ok", "hostname_fallback": True})
                    html = variant_html
                    effective_homepage = variant
                    visited.add(_dedup_key(effective_homepage))
                else:
                    sources_checked.append({"url": variant, "status": "unreachable", "hostname_fallback": True})

        # A plain fetch that failed here is very often NOT a dead site -- a
        # transient blip in a batch, an anti-bot 403 that blocks our
        # requests UA, or a redirect quirk. Confirmed directly: 33 of 37
        # "unreachable" school sites returned HTTP 200 on a later recheck.
        # The headless-browser fallback (a real Chrome) is retried on these
        # below, exactly as for a JS shell.
        homepage_unreachable = html is None

        if html:
            found = _extract(html, effective_homepage, school_name)
            if found.get("js_app_shell"):
                result["js_app_shell"] = True
            # A tier==-1 match alone isn't enough -- an ordinary,
            # single-school site can have its own internal nav link whose
            # label happens to share a level-word with the school's own
            # name (confirmed directly: a "Kadra" link tripped this on a
            # ke.edu.pl site with no hub at all). Only a link pointing at
            # a genuinely different host is real hub-sibling evidence.
            is_hub_page = any(
                tier == -1 and not _same_organization_host(link, effective_homepage)
                for tier, link in found["subpage_links"]
            )
            if is_hub_page:
                # Some private/international school groups share ONE
                # domain across several legally-separate schools -- this
                # page's own contact info (if any) is the FOUNDATION's,
                # not necessarily this specific school's. Try to reach
                # the dedicated subsite first; only trust this page's own
                # extraction if that search comes up empty.
                hub_fallback_found = found
                frontier.extend(found["subpage_links"])
            else:
                _merge(result, found)
                _note_cloak(found)
                frontier.extend(found["subpage_links"])
                if not found["subpage_links"]:
                    base = effective_homepage.rstrip("/")
                    frontier.extend((1, f"{base}/{slug}") for slug in COMMON_PROBE_SLUGS)

        while frontier and pages_fetched < MAX_SAME_SITE_PAGES and not _is_complete(result):
            frontier.sort(key=lambda pair: pair[0])
            tier, link = frontier.pop(0)
            if _dedup_key(link) in visited:
                continue
            visited.add(_dedup_key(link))
            time.sleep(REQUEST_DELAY_SECONDS)
            sub_html = fetch_page(link)
            pages_fetched += 1
            if sub_html:
                sources_checked.append({"url": link, "status": "ok"})
                found = _extract(sub_html, link, school_name)
                _merge(result, found)
                _note_cloak(found)
                if (
                    tier == -1
                    and own_school_subsite_url is None
                    and not _same_organization_host(link, effective_homepage)
                ):
                    # A genuine sibling-school link on a shared-domain hub
                    # lives on its OWN subdomain (sp.foo.pl vs. foo.pl) --
                    # requiring a different host here is what tells that
                    # apart from a same-host page that merely happens to
                    # share a level-word with the school's own name (e.g.
                    # a "kursy maturalne" fee page mentioning "matematyka
                    # podstawowa", which isn't this school's own site at
                    # all despite matching the same tier).
                    own_school_subsite_url = link
                frontier.extend(pair for pair in found["subpage_links"] if _dedup_key(pair[1]) not in visited)
            else:
                sources_checked.append({"url": link, "status": "unreachable"})

        # Never found the school's own dedicated subsite -- the hub page
        # is the best we've got, so its contact info is used as a last
        # resort (still tagged with the hub's real, working URL, not the
        # broken one originally on file).
        if hub_fallback_found and own_school_subsite_url is None:
            _merge(result, hub_fallback_found)
            _note_cloak(hub_fallback_found)

        if own_school_subsite_url:
            result["discovered_website_url"] = own_school_subsite_url
        elif effective_homepage != homepage:
            # NOTE: a plain string comparison, not _dedup_key() -- that
            # helper deliberately treats "www.x" and "x" as the same page
            # (right for crawl-budget dedup), which would wrongly call
            # this "unchanged" even though the ORIGINAL host never
            # resolved at all and only the fallback host actually worked.
            result["discovered_website_url"] = effective_homepage

        # 1b. Headless-browser fallback -- fires when the plain crawl either
        # saw only an empty SPA shell OR couldn't reach the homepage at all
        # (a real Chrome bypasses anti-bot 403s and transient blips), and
        # only when something's still missing, so the slow browser path
        # never touches the common already-worked case.
        if (result["js_app_shell"] or homepage_unreachable) and not _is_complete(result):
            if _scrape_with_browser(effective_homepage, school_name, result, sources_checked):
                result["js_render_used"] = True

    # 2. Web search fallback -- only for whatever's still missing, so a
    # school whose own site already had everything never triggers a
    # search at all.
    queries = []
    location = f" {city}" if city else ""
    if not result["director_name"]:
        queries.append(f'"{school_name}"{location} dyrektor szkoły')
    if not result["english_teacher_name"]:
        queries.append(f'"{school_name}"{location} nauczyciel angielskiego')

    for query in queries:
        if _is_complete(result):
            break
        time.sleep(REQUEST_DELAY_SECONDS)
        links = _search_duckduckgo(query)
        if not links:
            # Visible even when the search itself came back empty (or was
            # blocked by DuckDuckGo's bot detection) -- "we searched and
            # found nothing" is a different, honest outcome from "we never
            # tried", and both must show up in sources_checked.
            sources_checked.append({"query": query, "status": "search_returned_no_results"})
            continue
        for link in links:
            if _is_complete(result):
                break
            already_checked = any(s.get("url") == link for s in sources_checked)
            if already_checked:
                continue
            time.sleep(REQUEST_DELAY_SECONDS)
            html = fetch_page(link)
            if html:
                sources_checked.append({"url": link, "status": "ok", "found_via_search": query})
                _merge(result, _extract(html, link))
            else:
                sources_checked.append({"url": link, "status": "unreachable", "found_via_search": query})

    result["sources_checked"] = sources_checked
    result["all_emails"] = sorted(result["all_emails"])
    result["specialties"] = sorted(result["specialties"])
    return result
