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

import hashlib
import os
import re
import sys
import tempfile
import threading
import time
from html import unescape as _html_unescape
from urllib.parse import parse_qsl, urlencode, urljoin, urlparse

import requests
import urllib3
from bs4 import BeautifulSoup

from levelup.services.enrichment.verifier import email_level_hint, email_priority

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
# Joomla's built-in email cloak hides EVERY address on a page behind a
# JS snippet: a placeholder <span id="cloakXX">This email address is being
# protected from spambots...</span> plus an inline script holding the real
# address as concatenated, HTML-entity-encoded string fragments
# ("var addy_textXX = 'p&#97;tryk...' + '&#64;' + 'zs&#111;st&#111;.pl'").
# A plain fetch therefore shows the LLM a teacher's name followed by a
# protection notice and no address at all -- confirmed directly:
# slojedynka.zsosto.pl/liceum/kadra cloaks 27 staff addresses this way
# (the whole reason its English teacher came back email-less), and the
# lone plain-text secretariat address on the page even suppressed the
# email_cloak_detected note. The fragments ARE the address, though, so
# they're decoded statically -- no headless browser needed -- and each
# placeholder span is REPLACED IN PLACE with the decoded address, which
# both keeps it adjacent to the person's name (what the LLM pairing needs)
# and removes the misleading protection notice from the text.
# The fragment strings themselves contain semicolons (every HTML entity
# ends with one), so the expression is matched as a sequence of whole
# quoted chunks / identifier references / "+" joiners -- never "up to the
# next ;", which would cut mid-entity.
_JOOMLA_ADDY_RE = re.compile(
    r"addy(_text)?([0-9a-f]{6,})\s*=\s*((?:'[^']*'|addy(?:_text)?[0-9a-f]+|[+\s])+);"
)
_JOOMLA_CLOAK_SPAN_RE = re.compile(
    r"<span[^>]*\bid=['\"]cloak([0-9a-f]{6,})['\"][^>]*>.*?</span>",
    re.IGNORECASE | re.DOTALL,
)


def _decode_joomla_cloaks(html: str) -> str:
    if "cloak" not in html or "addy" not in html:
        return html
    # Fragments accumulate per (id, is_text_variant) across statements --
    # the plain addy variable is often built over TWO statements
    # ("addy = '...' ; addy = addy + '...'"), while addy_text usually
    # holds the whole address in one. Kept separate so the two variants
    # never concatenate into a doubled address; either one that decodes
    # to a valid email wins.
    fragments: dict[tuple[str, bool], list[str]] = {}
    for m in _JOOMLA_ADDY_RE.finditer(html):
        key = (m.group(2), bool(m.group(1)))
        fragments.setdefault(key, []).extend(re.findall(r"'([^']*)'", m.group(3)))

    decoded: dict[str, str] = {}
    for (cloak_id, _), parts in fragments.items():
        candidate = _html_unescape("".join(parts))
        if cloak_id not in decoded and EMAIL_RE.fullmatch(candidate):
            decoded[cloak_id] = candidate

    if not decoded:
        return html
    return _JOOMLA_CLOAK_SPAN_RE.sub(
        lambda m: decoded.get(m.group(1), m.group(0)), html
    )


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
# Bilingual (IB/international) schools commonly insert the English
# translation of the role label right after the Polish one -- "Dyrektor
# Szkoły / Head of School Dominika Pogorzelec-Nierzewska" (confirmed
# directly: ekola.edu.pl). The plain optional single dash/colon separator
# below can't span that whole phrase. Bounded the same way this file's
# other fillers are (_INSTITUTIONAL_FILLER, _ROLE_LIST_FILLER): must
# start with a literal "/" so it never fires on an ordinary "Dyrektor:
# Name" line, and capped at 6 plain-ASCII words so it can't run away --
# a stray Polish (diacritic) word ends the match immediately, since
# diacritics aren't in [A-Za-z].
_BILINGUAL_TRANSLATION_FILLER = r"(?:/\s*[A-Za-z]+(?:\s+[A-Za-z]+){0,5}\s+)?"

DIRECTOR_RE = re.compile(
    r"(?i:dyrektor[a-zżźćńółęąś]*\s*(?:szko[lł]y)?)\s*"
    + _BILINGUAL_TRANSLATION_FILLER
    + r"[:\-–]?\s*"
    + _TITLE_PREFIX
    + _NAME_GROUP
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
    rf"(?i:{_ENGLISH_KEYWORD})\s*" + _BILINGUAL_TRANSLATION_FILLER + r"[:\-–]?\s*" + _TITLE_PREFIX + _NAME_GROUP
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
#
# BUG FIX: a dash/colon separator between name and role ("Anna
# Ludwikowska-Wierzchowiec - dyrektor") wasn't tolerated at all -- confirmed
# directly: on a real multi-person "Dyrekcja" listing ("... Anna
# Ludwikowska-Wierzchowiec - dyrektor mgr Danuta Macewicz - zastępca
# dyrektora ..."), the missing dash meant this name-first pattern never
# matched, leaving only the keyword-first DIRECTOR_RE -- which, exactly like
# the "Begierska Renata Dyrektor Lenda Kamila Wicedyrektor" case above,
# treated "dyrektor" as introducing the NEXT person's name instead of the
# one it actually follows. A single optional separator char is safe to add
# (not an open-ended wildcard) since a real intervening word ("zastępca")
# still blocks the match, so a deputy's line still can't be mistaken for
# the director's.
_NAME_TO_ROLE_CONNECTOR = rf"\s*\(?\s*(?:{EMAIL_RE.pattern}\s+)?\s*[:\-–]?\s*"
DIRECTOR_NAME_FIRST_RE = re.compile(
    _NAME_GROUP + _NAME_TO_ROLE_CONNECTOR + r"(?i:dyrektor[a-zżźćńółęąś]*\s*(?:szko[lł]y)?)(?![a-ząćęłńóśźż])"
)
ENGLISH_TEACHER_NAME_FIRST_RE = re.compile(
    _NAME_GROUP + _NAME_TO_ROLE_CONNECTOR + rf"(?i:{_ENGLISH_KEYWORD})"
)

# A common commercial school-website builder (confirmed directly:
# sp3prudnik.pl, footer credit "Realizacja: Superszkolna.pl") renders its
# staff directory as "<Name> Funkcja: <role>[, <role>...]" per person --
# e.g. "Ewa Jarzycka Funkcja: Dyrekcja, Nauczyciel". The role value here is
# the noun "Dyrekcja" (the directorate/leadership), never "Dyrektor" (the
# person-title DIRECTOR_RE/DIRECTOR_NAME_FIRST_RE look for), so neither
# pattern matched at all on a page that plainly does name the director --
# a real "not_enriched" outcome for a school with the info in plain text.
# Bounded to this template's own literal "Funkcja:" label (not a generic
# wildcard) so it can't misfire on unrelated "Name ... dyrekcja" prose
# elsewhere on a page; a leading role list is tolerated since "Dyrekcja"
# isn't always the first-listed role for a given person.
_FUNKCJA_ROLE_CONNECTOR = r"\s*Funkcja:\s*(?:[A-ZŁŚŻŹĆŃÓĘĄa-ząćęłńóśźż]+\s*,\s*){0,4}"
DIRECTOR_FUNKCJA_RE = re.compile(
    _NAME_GROUP + _FUNKCJA_ROLE_CONNECTOR + r"(?i:dyrekcj[a-ząćęłńóśźż]*)\b"
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
#
# BUG FIX: each filler "word" required EVERY token to be a single bare
# capitalized word -- confirmed directly against a real EduPage staff
# page: "Dyrektor Zespołu Szkolno-Przedszkolnego nr 4 w Krapkowicach -
# mgr Joanna Drescher" broke this on two counts at once, a hyphenated
# compound ("Szkolno-Przedszkolnego") and lowercase connector words +
# a bare number ("nr 4 w"), so the filler match died before ever
# reaching the real separator and the whole pattern returned no match at
# all. Widened to the same permissive-but-bounded, non-greedy style
# already used for _ROLE_LIST_FILLER below -- still requires the
# eventual real dash/colon to anchor where the descriptor ends, so it
# can't run away and swallow unrelated text.
_INSTITUTIONAL_FILLER = r"(?:\s+[\w.-]+){1,8}?"
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
    # Confirmed directly: a real, correctly-placed English teacher name
    # ("Elwira Kopczyńska") was rejected purely because "Elwira" wasn't on
    # this list -- an ordinary, if less common, Polish first name.
    "Elwira",
    # Confirmed directly: a real, correctly-placed director name ("Adrian
    # Ziółkowski") was rejected the same way -- "Adrian" is an ordinary,
    # common Polish given name that simply wasn't on this list.
    "Adrian",
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
    # Gaps that became load-bearing once this list started gating a WRITE
    # (see jobs._clean_person_name). A name missing here is read as a
    # surname, so "Judyta Miłosz" -- Judyta absent, Miłosz present -- was
    # "corrected" to "Miłosz Judyta", which the export would then address
    # as "Szanowny Panie Miłoszu": wrong name AND wrong gender. A wrong
    # swap is worse than a missed one, so the first-token short-circuit
    # needs the broader stock.
    "Judyta", "Aldona", "Aneta", "Anita", "Arleta", "Cecylia", "Dagmara",
    "Eugenia", "Felicja", "Kalina", "Lidia", "Liliana", "Ludmiła", "Malwina",
    "Marcelina", "Martyna", "Melania", "Michalina", "Mirosława", "Nadia",
    "Otylia", "Pelagia", "Rozalia", "Salomea", "Sandra", "Teodora", "Wioleta",
    "Władysława", "Żaneta", "Bogumiła", "Bogusława", "Czesława", "Stanisława",
    "Genowefa", "Lucyna", "Roksana", "Sabina", "Wiktoria", "Zdzisława",
    "Alan", "Borys", "Fabian", "Gracjan", "Iwo", "Jeremi", "Kajetan",
    "Kordian", "Ksawery", "Maksymilian", "Olaf", "Remigiusz", "Seweryn",
    "Tymoteusz", "Nikodem", "Oskar", "Leon", "Bruno", "Igor",
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


# A match whose immediately-preceding context carries a deputy marker is
# about the DEPUTY, not the director: "Wicedyrektor: Anna Kowalska" and
# "Zastępca dyrektora - Jan Nowak" both CONTAIN "dyrektor..." so every
# keyword-first pattern matches inside them. Python's fixed-width
# lookbehind can't express this, so it's checked as a window here.
_DEPUTY_CONTEXT_RE = re.compile(r"(?i:wice|zast[eę]pc|z-ca|p\.\s*o\.)[^,.;\n]{0,25}$")

# A subject label sitting next to a person's name is not always a TEACHING
# assignment -- confirmed directly: psp.bialystok.pl's homepage congratulates
# competition winners ("z Wojewódzkich Konkursów Przedmiotowych uczniowie
# klasy VIIIa uzyskali następujące wyniki: Język Angielski: Karolina
# Brzozowska - tytuł laureata, Julia Nitkiewicz - tytuł laureata"), which is
# character-for-character the shape of "Język angielski: <teacher name>".
# Every name in such a list is a STUDENT, so the match is not merely
# unhelpful -- acted on, it names a child as the school's English teacher.
# What separates the two is the achievement vocabulary wrapping the list, so
# it is checked in a window on either side of the match: results copy leads
# in ("Konkurs", "laureaci", "gratulujemy") and trails out per name
# ("- tytuł laureata", "II miejsce"). Applied to the English-teacher scan
# only -- a director legitimately appears in prize-giving prose ("Dyrektor
# Anna Kowalska wręczyła nagrody laureatom"), so guarding that path would
# lose real directors.
_ACHIEVEMENT_BEFORE_RE = re.compile(
    r"(?i:konkurs|olimpiad|laureat|finalist|gratulujemy|etap\s+(?:szkoln|rejonow|wojew)"
    r"|wyniki\s+(?:konkurs|egzamin)|osi[ąa]gni[eę]|zdoby[lł]|nagrodzon)"
)
_ACHIEVEMENT_AFTER_RE = re.compile(
    r"(?i:tytu[łl]\s+laureat|laureat|finalist|wyr[óo]?[żz]nien|[IVX]{1,4}\s+miejsce|\d+\s*miejsce)"
)
_ACHIEVEMENT_BEFORE_CHARS = 160
_ACHIEVEMENT_AFTER_CHARS = 60


def _in_achievement_context(text: str, start: int, end: int) -> bool:
    """True when a subject-plus-name match sits inside a competition-results
    or prize-winners list (see _ACHIEVEMENT_BEFORE_RE) rather than a staff
    roster -- i.e. the name belongs to a student, not a teacher."""
    before = text[max(0, start - _ACHIEVEMENT_BEFORE_CHARS) : start]
    after = text[end : end + _ACHIEVEMENT_AFTER_CHARS]
    return bool(_ACHIEVEMENT_BEFORE_RE.search(before) or _ACHIEVEMENT_AFTER_RE.search(after))


def _earliest_valid_match(
    text: str, patterns: tuple[re.Pattern, ...], *, achievement_guard: bool = False
) -> str | None:
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
    immediately before or after it, never a further one two rows down.

    Matches preceded by a deputy marker (see _DEPUTY_CONTEXT_RE) are
    skipped entirely: they are statements about the deputy. With
    achievement_guard, matches inside a competition-results list are
    skipped too (see _in_achievement_context): those names are students."""
    candidates = []
    for pattern in patterns:
        for match in pattern.finditer(text):
            window_start = max(0, match.start() - 30)
            if _DEPUTY_CONTEXT_RE.search(text[window_start : match.start()]):
                continue  # "Wicedyrektor …" / "Zastępca dyrektora …" -- not the director
            if achievement_guard and _in_achievement_context(text, match.start(), match.end()):
                continue  # "Język angielski: <name> - tytuł laureata" -- a student
            normalized = _normalize_name_order(match.group(1).strip())
            if normalized:
                candidates.append((match.start(), normalized))
            break  # only each pattern's earliest VALID match competes
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


def _declension_stem_match(a: str, b: str) -> bool:
    """True when two words are the SAME name under different Polish
    grammatical case -- the school's own "im." clause is always genitive
    ("im. Jana Kochanowskiego"), while a page's own body text about its
    patron is routinely nominative ("Jan Kochanowski"). Confirmed directly
    (caught by this module's own fixture test): a flat exact-match check
    silently let a school's patron slip through as "staff" whenever the
    two forms diverged. Polish declension either appends a case ending
    (Kochanowski -> Kochanowskiego) or swaps a same-length ending (Maria ->
    Marii, Anna -> Anny) -- comparing everything but the last character of
    the SHORTER word survives either pattern without needing to enumerate
    Polish suffix rules."""
    a, b = a.lower(), b.lower()
    if a == b:
        return True
    n = min(len(a), len(b))
    if n < 3:
        return False
    stem_len = n - 1
    return a[:stem_len] == b[:stem_len]


def _is_patron_name(candidate: str, patron_tokens: set[str]) -> bool:
    """BUG FIX: the candidate was split on WHITESPACE only, while
    _patron_name_tokens splits the school's "im." clause on every
    non-letter -- so a hyphenated patron surname never matched. Confirmed
    against the canonical Polish case: a school "im. Marii
    Sklodowskiej-Curie" yields tokens {marii, sklodowskiej, curie}, but the
    candidate "Maria Sklodowska-Curie" stayed one word
    ("sklodowska-curie") that matched no single token, so the patron passed
    the filter and could be written as staff. Tokenizing BOTH sides the
    same way closes it. Narrow by construction: every token must still
    match a patron token, so a real staff member who merely shares one
    name part with the patron is unaffected."""
    if not patron_tokens:
        return False
    words = [w.lower() for w in re.findall(r"[A-Za-zŁŚŻŹĆŃÓĘĄłśżźćńóęą]+", candidate)]
    return bool(words) and all(any(_declension_stem_match(w, token) for token in patron_tokens) for w in words)


# A school is tagged "Special-needs school" ONLY when its official name
# marks it as a DEDICATED special-education institution -- not one that
# merely accommodates disability. Deliberately EXCLUDES "z oddziałami
# integracyjnymi" (a mainstream school WITH integration classes) and any
# body-text mention of accommodation; only the authoritative RSPO name is
# used. Matches (each is an explicit "made for that" marker):
#   - "... specjalna / specjalny" as the institution type (szkoła/liceum/
#     technikum/ośrodek specjalny). Negative lookahead drops "specjalność"
#     (a course major) and "specjalnie" (adverb).
#   - a special centre: ośrodek szkolno-wychowawczy (SOSW), ośrodek
#     rewalidacyjno-wychowawczy (OREW), młodzieżowy ośrodek wychowawczy /
#     socjoterapii (MOW/MOS).
#   - a named disability population: for the deaf/blind/low-vision, autism,
#     or (intellectual/other) disability -- these words appear in a school's
#     name only when the school is dedicated to that population.
#
# BUG FIX: several real dedicated institutions carry NONE of the markers
# above at all -- confirmed directly against 5 schools a user found were
# never tagged:
#   - a school run INSIDE a chronic-illness setting -- "PRZY ZAKŁADACH
#     OPIEKI ZDROWOTNEJ" (at healthcare facilities) or "PRZY ... SZPITALU
#     REHABILITACYJNYM" (at a rehabilitation hospital) -- these two
#     schools' own names have no "specjalna" and no disability keyword at
#     all, only the facility context itself and (for one of them) "DLA
#     DZIECI PRZEWLEKLE CHORYCH" (for chronically ill children).
#   - a school run INSIDE a juvenile detention centre -- "W ZAKŁADZIE
#     POPRAWCZYM" -- a distinct, unambiguous institutional-type marker;
#     RSPO's own "specificity" field (see rspo_detail.py) does NOT cover
#     this case either (it's a justice-system classification, not an
#     education-law "specjalna" one), so this stays a name-only signal.
_SPECIAL_SCHOOL_NAME_RE = re.compile(
    r"\bspecjaln(?!o[śs]|ie)"  # specjalna/specjalny/specjalne(j) but NOT specjalność/specjalnie
    r"|o[śs]rodek\s+(?:szkolno-?\s*wychowawcz|rewalidacyjno)"
    r"|\bsosw\b|\borew\b"
    r"|m[łl]odzie[żz]owy\s+o[śs]rodek\s+(?:wychowawcz|socjoterap)"
    r"|nies[łl]ysz|s[łl]abos[łl]ysz|niedos[łl]ysz|niedos[łl]uch"
    r"|niewidom|s[łl]abowidz|niedowidz"
    r"|autyz|autystyczn|aspergera"
    r"|niepe[łl]nosprawn|upo[śs]ledz"
    r"|zak[łl]ad(?:zie|ach|em)?\s+poprawcz"
    r"|zak[łl]ad(?:ach|zie)?\s+opieki\s+zdrowotnej"
    r"|przewlekl\w*\s+chor|chorob\w*\s+przewlek"
    r"|szpital\w*\s+rehabilitacyjn"
)


def _detect_specialties(text: str, *, is_name: bool = False) -> set[str]:
    """Returns {"Special-needs school"} only when the text is the official
    NAME of a DEDICATED special-needs institution, else an empty set. Never
    fires on body text (that produced accessibility-declaration false
    positives) and never on "z oddziałami integracyjnymi" (integration
    classes are accommodation, not a dedicated special school)."""
    if not text:
        return set()
    return {"Special-needs school"} if _SPECIAL_SCHOOL_NAME_RE.search(text.lower()) else set()


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
        # Vocabulary gaps found by auditing 44 high-scoring schools that
        # reached "basic" enrichment with no teacher. Each of these is a
        # real nav label on a real school site whose roster the crawl could
        # not reach because the label used none of the words above:
        # "Nasz zespół" (private/Montessori schools overwhelmingly prefer
        # this to "Kadra"), "Nasi nauczyciele", and the ENGLISH labels that
        # international/bilingual schools use for their only staff page --
        # exactly the school profile this tool targets, so missing them is
        # expensive. "team"/"staff" are boundary-matched (see
        # _keyword_matches) so they cannot fire inside unrelated words.
        "zespol", "zespół", "nasz zespol", "nasz zespół", "nasi nauczyciele",
        "wychowawcy", "specjalisci", "specjaliści",
        "team", "staff", "teachers", "our team", "faculty",
    ),
    ("kontakt", "wladze", "władze", "struktura"),
    # BUG FIX: only the hyphenated URL-slug spelling was listed -- confirmed
    # directly: zsbratian.edupage.org's own nav label is the ordinary
    # Polish phrase "O szkole" (a space, not a hyphen, and its href is the
    # unrelated English word "/about/") -- matched neither the href nor
    # the label, so this tier never fired at all despite that exact page
    # naming the director outright ("Dyrekcja Dyrektor Adrian Ziółkowski").
    # A real label is prose, not a URL slug -- the space-separated form is
    # what a human-readable nav item actually looks like.
    ("o-szkole", "o szkole", "o-nas", "o nas"),
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
    """Level-stem-based hub-jump detection (e.g. a "Liceum Ogólnokształcące"
    nav label matching a school whose own name contains "liceum").
    Reserved for genuinely different-host hub jumps -- the call site
    additionally requires that -- since promoting a same-host link this
    way risks nothing worse than exploring one of the school's own
    pages, while a cross-domain jump could land on an entirely different
    organization's content. See _is_bare_hub_label below for the
    same-host-safe counterpart."""
    if not label or len(label.split()) > _HUB_LINK_MAX_WORDS:
        return False
    school_name_lower = school_name.lower()
    return any(stem in school_name_lower and stem in label for stem in _SCHOOL_LEVEL_STEMS)


# A "Zespół Szkolno-Przedszkolny" (combined school+kindergarten complex)
# site sometimes labels its hub-entrance links with just the bare word --
# "Szkoła" / "Przedszkole", no level qualifier like "Podstawowa" at all --
# confirmed directly: psp28.opole.pl's own nav is literally "Szkoła |
# Przedszkole | Kontakt", and "Szkoła" alone shares no level-stem with
# anything (_SCHOOL_LEVEL_STEMS is looking for "podstaw", not the bare,
# generic word "school"), so it was invisible to hub-detection entirely
# and the crawl never went one hop deeper to find the real staff page.
# NOT gated on the school's own official name mentioning "Zespół
# Szkolno-Przedszkolny" -- confirmed directly, psp28's own RSPO name is
# just an ordinary "Publiczna Szkoła Podstawowa nr 28" with no hint its
# site happens to be built this way. Gated instead on the page itself
# actually having BOTH bare labels side by side -- a real, observable
# structural signal that this is genuinely a two-section hub, not just
# one standalone school's ordinary self-link back to its own homepage
# (which would only ever have "Szkoła" alone, never paired with
# "Przedszkole"). Deliberately allowed on the SAME host, unlike the
# level-stem check above -- this link never leaves the school's own
# domain, so there's no cross-organization risk to guard against.
_BARE_HUB_LABELS = ("szkoła", "szkola", "przedszkole")


def _is_bare_hub_label(label: str, paired_bare_labels: bool) -> bool:
    return paired_bare_labels and label.strip() in _BARE_HUB_LABELS

# "bip" is short enough to collide with unrelated hyphenated slugs -- the
# Joomla-based BIP engine that many Polish schools use names its own
# editorial/pagination component "redakcja-bip", which contains "bip" as a
# bare substring. Without a boundary check, every internal CMS nav link on
# a BIP subdomain (article prev/next, admin links) would falsely count as
# a top-priority BIP match, drowning out the real "Rada Pedagogiczna"
# staff-roster link in the crawl budget. Hyphen does NOT count as a valid
# boundary here -- that's precisely how "redakcja-bip" collides.
#
# "o nas" (added alongside the existing hyphenated "o-nas" so a normal,
# space-separated nav label matches too) has the same problem in the
# opposite direction: it's a bare substring of ordinary Polish phrases
# like "dołącz do nas"/"napisz do nas" ("join us"/"write to us") that have
# nothing to do with an "About us" page. A boundary check is what tells
# "o nas" (its own phrase) apart from "d-o nas" (the tail end of "do
# nas").
_AMBIGUOUS_SHORT_KEYWORDS = frozenset({"bip", "o nas"})

# "rodo" has the OPPOSITE problem: it's a bare substring INSIDE ordinary
# Polish words, not just hyphen-joined slugs. Confirmed directly: the
# exclude-list check rejected a school's own "Międzynarodowe Liceum"
# (international) hub link outright because "międzynaRODOwe" contains
# "rodo" mid-word. Real RODO/GDPR pages always delimit it from other
# LETTERS (a hyphenated slug like "polityka-rodo", or standalone "RODO" as
# a label) -- so hyphen must count as a valid boundary here, unlike "bip".
_MIDWORD_RISK_KEYWORDS = frozenset({"rodo"})
_PL_LETTERS = "a-ząćęłńóśźżA-ZĄĆĘŁŃÓŚŹŻ"

# Short ENGLISH staff words carry the same mid-word collision risk as
# "rodo", against a much larger surface: "team" is inside "teamviewer" and
# "steam" (a STEAM-programme page is on half these schools' navs), "staff"
# inside "staffordshire", and every one of them can appear inside a longer
# URL slug. Delimited by any non-letter, so "our-team", "/team/", "Team"
# and "Nasz Team" all match while "STEAMowe ABC" does not.
_LATIN_LETTERS = "a-zA-Z"
_ENGLISH_SHORT_KEYWORDS = frozenset({"team", "staff", "teachers", "faculty", "our team"})


def _keyword_matches(keyword: str, haystack: str) -> bool:
    if keyword in _AMBIGUOUS_SHORT_KEYWORDS:
        return bool(re.search(rf"(?:^|[/.\s]){re.escape(keyword)}(?:$|[/.\s])", haystack))
    if keyword in _MIDWORD_RISK_KEYWORDS:
        return bool(re.search(rf"(?<![{_PL_LETTERS}]){re.escape(keyword)}(?![{_PL_LETTERS}])", haystack))
    if keyword in _ENGLISH_SHORT_KEYWORDS:
        return bool(
            re.search(rf"(?<![{_LATIN_LETTERS}]){re.escape(keyword)}(?![{_LATIN_LETTERS}])", haystack)
        )
    return keyword in haystack


# Parameters that identify a CAMPAIGN, not a page: two links differing only
# by these are the same page and must still collapse (see _dedup_key).
_TRACKING_QUERY_PARAMS = frozenset(
    {
        "fbclid", "gclid", "msclkid", "mc_cid", "mc_eid", "ref", "source", "yclid", "igshid",
        # Language selectors: see _strip_language_prefix for why a
        # translation of a page already in hand must not cost a page slot.
        "lang", "language", "lng", "l",
    }
)

# Locale path segments used by the multilingual plugins on Polish school
# sites (WPML, Polylang and friends).
_LANGUAGE_PATH_SEGMENTS = frozenset({"en", "pl", "de", "ua", "uk", "ru", "fr", "es", "it", "cs"})


def _strip_language_prefix(path: str) -> str:
    """Drops a leading locale segment ("/en/kadra" -> "/kadra") so a
    TRANSLATION of a page counts as that page for crawl-budget purposes.

    Confirmed directly: one bilingual school spent its entire ten-page
    budget on five URLs, two of which were the /en/ mirrors of pages it
    already held in Polish, and never reached the pages that named its
    English teachers. Bilingual and international schools are precisely
    this tool's highest-value segment, so paying twice per page there is
    the worst place to waste budget.

    Note the deliberate trade: an English page with NO Polish counterpart
    keeps its own key (nothing else maps to that path), so it is still
    crawlable -- only a mirror of a page already fetched is skipped."""
    if not path:
        return path
    head, slash, tail = path.lstrip("/").partition("/")
    if head.lower() in _LANGUAGE_PATH_SEGMENTS:
        return "/" + tail if slash else ""
    return path


def _dedup_key(url: str) -> str:
    """Collapses http/https, www/non-www, and trailing-slash variants of
    the same page to one key so the crawl budget isn't wasted re-fetching
    a page it already has under a slightly different URL spelling.

    The QUERY STRING is part of the key. It used to be discarded, which
    silently destroyed the crawl on any site whose pages are querystring
    permalinks -- confirmed directly on two audited schools: every nav
    target was "/index.php?id=..." or "/?p=...", so all of them collapsed
    to the ONE key "host/index.php" and the crawl fetched a single page and
    declared the site link-less. Tracking parameters are still stripped, so
    the variants this was originally written to collapse (a nav link
    carrying utm_* or fbclid) still collapse."""
    parsed = urlparse(url)
    netloc = parsed.netloc.lower().removeprefix("www.")
    path = _strip_language_prefix(parsed.path.rstrip("/"))
    meaningful = [
        (k, v)
        for k, v in parse_qsl(parsed.query, keep_blank_values=True)
        if k.lower() not in _TRACKING_QUERY_PARAMS and not k.lower().startswith("utm_")
    ]
    if not meaningful:
        return f"{netloc}{path}"
    return f"{netloc}{path}?{urlencode(sorted(meaningful))}"


def _fetch_failure_status(url: str) -> str:
    """The honest label for a failed fetch: a host resting after a
    confirmed throttle is "rate_limited" (recoverable -- retry later), not
    "unreachable" (dead site)."""
    return "rate_limited" if was_rate_limited(url) else "unreachable"


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

MAX_SAME_SITE_PAGES = 10
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
# One past the lowest real keyword tier (redakcja-bip) -- a blind guess
# should never outrank an actually-matched link, whenever either is found.
_GUESS_TIER = len(SUBPAGE_KEYWORDS_BY_PRIORITY)

# Some multi-school-under-one-foundation sites (confirmed directly:
# ekola.edu.pl) split the homepage into a hub of colored panels -- one per
# sibling school -- that navigate via a JS click handler with no <a href>
# at all, not even a bare onclick attribute visible in the server response.
# Link discovery (and even COMMON_PROBE_SLUGS, which only probes the
# ROOT) finds nothing, because the real content lives one level down, at
# a level-named path (ekola.edu.pl/liceum/, .../szkola-podstawowa). Tried
# BEFORE the flat COMMON_PROBE_SLUGS since landing on the right subsite
# unlocks its own real nav (kontakt/kadra/etc via ordinary link
# discovery) rather than guessing at the root. Keyed by the same level
# stems already used for hub-link labels (_SCHOOL_LEVEL_STEMS) -- only
# the stem(s) actually present in THIS school's own name are tried, never
# the full list, to keep the probe budget small.
_LEVEL_HUB_SLUGS_BY_STEM = {
    "liceum": ("liceum", "lo"),
    "technikum": ("technikum",),
    "podstaw": ("sp", "szkola-podstawowa", "podstawowa"),
    "gimnazjum": ("gimnazjum",),
    "przedszkol": ("przedszkole",),
}


def _level_hub_slugs_for(school_name: str) -> tuple[str, ...]:
    name_lower = school_name.lower()
    slugs: list[str] = []
    for stem, candidates in _LEVEL_HUB_SLUGS_BY_STEM.items():
        if stem in name_lower:
            slugs.extend(candidates)
    return tuple(slugs)


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


_REDUNDANT_PL_SUFFIX_RE = re.compile(r"\.(?:org|com|net|info|eu)\.pl$", re.IGNORECASE)


def _hostname_fallback_variants(url: str) -> list[str]:
    """When the exact stored hostname doesn't resolve/connect at all,
    these are the structurally-obvious same-organization variants worth
    trying before giving up. Deliberately narrow: never a guessed
    subdomain or a different domain entirely -- that would risk landing
    on an unrelated site and mistaking it for this school's own.
      - www-add/www-strip -- confirmed directly: RSPO recorded a "www."
        for a school whose real site lives under a different subdomain,
        and that exact "www." host has no DNS record at all, while the
        bare domain (a shared hub for a group of schools under that
        foundation) resolves fine.
      - BUG FIX: a stray, redundant ".pl" appended after an
        already-complete international domain -- confirmed directly:
        "zsbratian.edupage.org.pl" doesn't resolve at the DNS level AT
        ALL (not blocked, not slow -- genuinely no such name), while the
        real site, missing only that tacked-on ".pl", is
        "zsbratian.edupage.org" and resolves fine. edupage.org (a
        Slovak-run platform hosting many Polish schools) is never
        actually a ".pl" domain -- whoever entered this one seems to
        have assumed every Polish school's site ends in ".pl" and added
        it on top of an address that was already complete."""
    parsed = urlparse(url)
    host = parsed.netloc
    if not host:
        return []
    variants = [
        url.replace(host, host[4:], 1) if host.lower().startswith("www.") else url.replace(host, f"www.{host}", 1)
    ]
    if _REDUNDANT_PL_SUFFIX_RE.search(host):
        variants.append(url.replace(host, host[:-3], 1))
    return variants


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


# A school complex's homepage often links each member school's dedicated
# subsite under a level-named SUBDOMAIN of the same registered domain --
# confirmed directly: zsosto.pl (a rich landing page for a Warsaw STO
# complex) links its primary school's real site as
# `<a href="https://sp.zsosto.pl/">wejdź</a>`. The label ("enter") carries
# no keyword any tier recognizes, and the page is far too rich for the
# sparse-page chooser-hub heuristic (_find_hub_candidates) to fire -- so
# the one link leading to the school's own staff page (with per-teacher
# personal emails) was dropped, and enrichment stopped at the complex's
# generic pages. The HOST itself is the signal the label lacks: "sp." on
# the school's own registered domain names a szkoła podstawowa as plainly
# as a "Szkoła Podstawowa" label would. Reuses the same level-implying
# shapes as email_level_hint ("sp@smsw.pl" is the primary school's mailbox
# for exactly the same reason "sp.zsosto.pl" is its subsite), and only
# ever matches the school's OWN level -- from a primary school's crawl,
# lo.zsosto.pl stays a sibling, not a candidate.
_NAME_STEM_TO_LEVEL = (("podstawow", "primary"), ("liceum", "liceum"), ("technikum", "technikum"))


def _same_level_subsite_host(full_url: str, base_url: str, school_name: str) -> bool:
    host = urlparse(full_url).netloc.split(":")[0].lower().removeprefix("www.")
    base_host = urlparse(base_url).netloc.split(":")[0].lower().removeprefix("www.")
    if not host or host == base_host:
        return False
    domain = _registrable_domain(host)
    if domain != _registrable_domain(base_host) or not host.endswith("." + domain):
        return False
    subdomain = host[: -(len(domain) + 1)]
    if not subdomain or "." in subdomain:  # one label only -- never a guessed deep host
        return False
    implied_level = email_level_hint(f"{subdomain}@x.pl")
    if implied_level is None:
        return False
    name_lower = school_name.lower()
    return any(stem in name_lower and level == implied_level for stem, level in _NAME_STEM_TO_LEVEL)


# A bare "Mozilla/5.0" is itself a bot-detection signal on some sites --
# a full, current browser UA string is less likely to get silently
# filtered/blocked than an obviously-fake one.
USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/126.0 Safari/537.36"
)


def _decoded_text(resp: requests.Response) -> str:
    """BUG FIX: requests defaults a response's encoding to ISO-8859-1
    whenever the server's Content-Type header omits a charset (a plain
    "text/html" with nothing else) -- the HTTP spec's own fallback, but
    wrong for the overwhelming majority of real Polish sites, which serve
    actual UTF-8 bytes and just don't bother declaring it in the header.
    Confirmed directly: zpo3dzialdowo.pl's real title is "Zespół Placówek
    Oświatowych nr 3 w Działdowie" (readable, correct UTF-8 bytes), but
    resp.text silently mojibake'd it to "ZespÃ³Å PlacÃ³wek OÅwiatowych..."
    -- every Polish-diacritic-sensitive regex and keyword match in this
    file (director names, "Dyrekcja", school-vs-municipal verification,
    all of it) would silently fail against text corrupted this way, on
    any site with this same header gap. requests' own apparent_encoding
    (charset-normalizer's real content sniffing) correctly identified
    UTF-8 for this exact page -- trusted here ONLY as an override for the
    spec-default fallback, never overriding a charset the server actually
    declared, since an explicit declaration is still more reliable than a
    guess."""
    if resp.encoding and resp.encoding.lower() == "iso-8859-1" and resp.apparent_encoding:
        resp.encoding = resp.apparent_encoding
    return resp.text


# A 200 response whose BODY is a throttling notice, not the page. Confirmed
# directly: edupage.org (2,417 schools in this register -- ~13% of it) answers
# rapid crawling with HTTP 200 and an 84-byte body, "Your IP is temporarily
# blocked because of too many requests." Treated as content, that block page
# was recorded as an "ok" source AND handed to the LLM as one of the school's
# eight page slots -- so a batch of edupage schools could each be marked
# "enriched, nothing found" purely because the platform was throttling us.
# Matched on a short body (real pages are far larger) plus the notice's own
# wording, so a school page merely discussing blocked IPs can't trip it.
_BLOCK_BODY_MAX_CHARS = 400
_BLOCK_BODY_MARKERS = (
    "temporarily blocked",
    "too many requests",
    "rate limit",
    "zbyt wiele zapyta",  # PL, diacritic-safe prefix of "zapytań"
)
# Longer than the ordinary retry: a throttle needs time to clear, and this
# only ever fires on a confirmed block.
_BLOCK_RETRY_DELAY_SECONDS = 6.0


_MIN_LLM_PAGE_CHARS = 120


def _normalize_ws_text(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()


# --- Per-host throttle handling (fixes B + C) --------------------------------
# One global 0.4s pause was tuned for POLITENESS, not for platforms: 2,417
# schools in this register (~13%) live on edupage.org alone, so a batch can
# cluster dozens of requests onto one host and trip its rate limiter -- which
# answers HTTP 200 + "Your IP is temporarily blocked". Three cooperating
# pieces, all keyed by REGISTRABLE domain and shared across the batch thread
# and the auto-enrich thread:
#   - pacing: a minimum gap between requests to the SAME domain, so the
#     burst that triggers the block stops happening;
#   - cooldown: after a CONFIRMED block, the whole domain rests (doubling
#     on repeats) and further fetches to it fail fast instead of each
#     paying a request + retry against a wall;
#   - a was-throttled registry, so the crawl can record "rate_limited"
#     (a recoverable outcome) instead of "unreachable" (a dead site).
_HOST_MIN_GAP_SECONDS = 1.0
_HOST_COOLDOWN_BASE_SECONDS = 300.0
_host_lock = threading.Lock()
_host_last_request: dict[str, float] = {}
_host_cooldown_until: dict[str, float] = {}
_host_block_count: dict[str, int] = {}


def _host_key(url: str) -> str:
    return _registrable_domain(urlparse(url).netloc)


def _pace_host(url: str) -> None:
    host = _host_key(url)
    if not host:
        return
    with _host_lock:
        wait = _host_last_request.get(host, 0.0) + _HOST_MIN_GAP_SECONDS - time.monotonic()
    if wait > 0:
        time.sleep(wait)
    with _host_lock:
        _host_last_request[host] = time.monotonic()


def _host_in_cooldown(url: str) -> bool:
    with _host_lock:
        return time.monotonic() < _host_cooldown_until.get(_host_key(url), 0.0)


def _note_host_blocked(url: str) -> None:
    host = _host_key(url)
    with _host_lock:
        strikes = _host_block_count.get(host, 0) + 1
        _host_block_count[host] = strikes
        _host_cooldown_until[host] = time.monotonic() + _HOST_COOLDOWN_BASE_SECONDS * (2 ** (strikes - 1))
    print(f"scraper: {host} rate-limited us (strike {strikes}) -- cooling down", flush=True)


def was_rate_limited(url: str) -> bool:
    """True when this URL's host is (still) resting after a confirmed
    throttle -- lets callers log the honest outcome instead of
    "unreachable"."""
    return _host_in_cooldown(url)


def _is_block_page(text: str | None) -> bool:
    if not text or len(text) > _BLOCK_BODY_MAX_CHARS:
        return False
    lowered = text.lower()
    return any(marker in lowered for marker in _BLOCK_BODY_MARKERS)


_FETCH_RETRY_DELAY_SECONDS = 1.5
# Was a flat 15s. Real school hosts either answer in a couple of seconds or
# are dead; 15s just parked the (serial) crawler on hopeless hosts. Env-
# tunable so it can be raised without a code change if a slow-host pattern
# shows up in the new per-stage timings.
FETCH_TIMEOUT_SECONDS = float(os.getenv("LEVELUP_FETCH_TIMEOUT", "10"))

# Only genuinely transient statuses are worth a second attempt. A 404 (or
# any other permanent 4xx) is the single most common failure in this crawl
# -- every blind COMMON_PROBE_SLUGS guess and every dead nav link produces
# one -- and retrying it cost a second full request plus a 1.5s sleep for a
# result that cannot change.
_RETRYABLE_STATUSES = frozenset({403, 408, 425, 429, 500, 502, 503, 504})

# One pooled Session per thread: without it every fetch paid a fresh TCP +
# TLS handshake, ~5-6 times per school, all to the same host. Thread-local
# rather than module-global so a future parallel crawl can't share one
# Session's connection pool across worker threads.
_thread_state = threading.local()


def _http_session() -> requests.Session:
    session = getattr(_thread_state, "session", None)
    if session is None:
        session = requests.Session()
        session.headers.update({"User-Agent": USER_AGENT})
        _thread_state.session = session
    return session


# Where a fetch actually LANDED, keyed by the URL that was requested. A
# school site on a legacy CMS routinely 302s "/" to "/asp/pl_start.asp" and
# then writes every nav link as a bare query string ("?typ=14&menu=223").
# Resolved against the REQUESTED url, urljoin drops the script name and
# every one of those links collapses back onto the homepage -- confirmed
# directly on one audited school, where three "staff pages" were
# byte-identical copies of the front page. Resolved against the final url
# they point where a browser would. Thread-local because the crawl keeps a
# Session per thread.
def _note_final_url(requested: str, final: str) -> None:
    if not final or final == requested:
        return
    store = getattr(_thread_state, "final_urls", None)
    if store is None:
        store = {}
        _thread_state.final_urls = store
    store[_dedup_key(requested)] = final


def _final_url_for(requested: str) -> str | None:
    store = getattr(_thread_state, "final_urls", None)
    return store.get(_dedup_key(requested)) if store else None


def fetch_page(url: str) -> str | None:
    """BUG FIX: one short, bounded retry, specifically for a TIMEOUT or a
    TRANSIENT HTTP error response (403/429/5xx and friends) -- confirmed
    directly across a real batch: several schools' sites logged as
    "unreachable" turned out to be reachable again just minutes later on a
    manual recheck (already a known, accepted characteristic of this
    environment -- see the crawl's own headless-browser retry below), and
    one returned a 403 specifically, exactly the shape of a transient
    anti-bot response that often clears a couple seconds later.

    Deliberately NOT retried for: a connection/DNS failure (an address
    that flat-out doesn't resolve won't resolve differently a second later
    in the same run), nor a permanent 4xx such as 404 (see
    _RETRYABLE_STATUSES) -- both only ever added a wasted request plus a
    sleep to a result that cannot change."""
    if _host_in_cooldown(url):
        # The host told us to go away recently -- don't pay a request (and
        # a retry, and a sleep) to be told again. was_rate_limited() lets
        # the caller record this as "rate_limited", not "unreachable".
        return None
    for attempt in range(2):
        try:
            _pace_host(url)
            resp = _http_session().get(url, timeout=FETCH_TIMEOUT_SECONDS)
            resp.raise_for_status()
            text = _decoded_text(resp)
            # A throttling notice is not this page -- one in-run retry after
            # a pause; a second block puts the whole HOST into cooldown so
            # the rest of the batch stops walking into the same wall.
            if _is_block_page(text):
                if attempt == 0:
                    time.sleep(_BLOCK_RETRY_DELAY_SECONDS)
                    continue
                _note_host_blocked(url)
                return None
            _note_final_url(url, resp.url)
            return text
        except requests.exceptions.SSLError:
            # Confirmed directly: some Polish school sites (e.g. lo2.lublin.eu)
            # serve an incomplete certificate chain (missing intermediate) --
            # the content itself is fine, browsers just cross-reference the
            # missing cert from elsewhere. This is public, read-only content
            # with no data submitted, so falling back to an unverified request
            # only when strict verification specifically fails is a reasonable
            # trade -- it's not blanket-disabling verification for every site.
            try:
                resp = _http_session().get(url, timeout=FETCH_TIMEOUT_SECONDS, verify=False)
                resp.raise_for_status()
                _note_final_url(url, resp.url)
                return _decoded_text(resp)
            except requests.RequestException:
                return None
        except requests.exceptions.HTTPError as exc:
            status = exc.response.status_code if exc.response is not None else None
            if attempt == 0 and status in _RETRYABLE_STATUSES:
                time.sleep(_FETCH_RETRY_DELAY_SECONDS)
                continue
            return None
        except requests.exceptions.Timeout:
            if attempt == 0:
                time.sleep(_FETCH_RETRY_DELAY_SECONDS)
                continue
            return None
        except requests.RequestException:
            return None
    return None


_VISION_CONTENT_TYPES = {
    "image/jpeg": ".jpg",
    "image/png": ".png",
    "image/gif": ".gif",
    "application/pdf": ".pdf",
}


def download_for_vision(url: str, *, max_bytes: int = 10 * 1024 * 1024) -> str | None:
    """Downloads one staff-roster image/PDF to a temp file for the vision
    path (llm_extract.extract_from_image/_pdf) -- the SDK's Read tool
    needs a real file path, not bytes in memory. Streamed with an early
    abort once max_bytes is exceeded (never trusts a possibly-absent/
    lying Content-Length header alone), and the content-type is checked
    against what the file actually served, not just the URL's extension.
    Returns None on any failure -- the caller treats a vision call it
    can't set up as just another way this school's roster wasn't
    reachable, never a hard error. The caller owns deleting the file
    afterward."""
    try:
        resp = requests.get(url, timeout=15, headers={"User-Agent": USER_AGENT}, stream=True)
        resp.raise_for_status()
    except requests.RequestException:
        return None

    content_type = resp.headers.get("Content-Type", "").split(";")[0].strip().lower()
    suffix = _VISION_CONTENT_TYPES.get(content_type)
    if suffix is None:
        resp.close()
        return None

    fd, path = tempfile.mkstemp(suffix=suffix, prefix="levelup_vision_")
    total = 0
    try:
        with os.fdopen(fd, "wb") as f:
            for chunk in resp.iter_content(chunk_size=65536):
                total += len(chunk)
                if total > max_bytes:
                    raise ValueError("exceeded max_bytes")
                f.write(chunk)
        return path
    except Exception:  # noqa: BLE001 -- oversized/interrupted download is a normal, expected outcome here
        try:
            os.remove(path)
        except OSError:
            pass
        return None
    finally:
        resp.close()


def _image_alt_text(anchor) -> str:
    """The accessible name contributed by an anchor's images -- their alt
    and title attributes, lowercased. Empty for ordinary text links."""
    parts: list[str] = []
    for img in anchor.select("img"):
        for attr in ("alt", "title"):
            value = img.get(attr)
            if value:
                parts.append(re.sub(r"\s+", " ", value).strip().lower())
    title = anchor.get("title")
    if title:
        parts.append(re.sub(r"\s+", " ", title).strip().lower())
    return " ".join(parts)


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

    # BUG FIX: a bare .strip() only trims LEADING/TRAILING whitespace --
    # it doesn't touch a non-breaking space (U+00A0, "\xa0") sitting
    # BETWEEN two words, which real HTML uses constantly (a CMS/editor's
    # "&nbsp;" inserted to stop a short label from wrapping mid-phrase).
    # Confirmed directly: zsbratian.edupage.org's own "O szkole" nav
    # label is actually "o\xa0szkole" -- invisible to a keyword match
    # against a normal, space-separated "o szkole", so this exact link
    # (which names the director outright) never got a tier at all.
    # re.sub(r"\s+", ...) -- already used everywhere else in this file
    # for extracted text -- treats \xa0 as whitespace correctly; only
    # this label-building step had skipped that normalization.
    all_labels = {re.sub(r"\s+", " ", a.get_text(" ")).strip().lower() for a in soup.select("a[href]")}
    paired_bare_labels = ("szkoła" in all_labels or "szkola" in all_labels) and "przedszkole" in all_labels

    for a in soup.select("a[href]"):
        href = a["href"]
        # BUG FIX: a real school site's own markup sometimes forgets the
        # "mailto:" prefix on an email link -- confirmed directly:
        # zsz-gk.pl has `<a href="informatyk@zsz-gk.pl">O nas</a>` (a
        # genuine typo on the SITE's own end, not fixable there). Fed
        # into urljoin as-is, a bare address with no scheme is treated as
        # a relative path segment, producing a nonsense URL
        # ("zsz-gk.pl/contact/informatyk@zsz-gk.pl") that wastes a crawl
        # slot on a guaranteed 404/junk page. Skipped outright rather than
        # visited -- it was never a navigable link to begin with.
        if EMAIL_RE.fullmatch(href.strip()):
            continue
        label = re.sub(r"\s+", " ", a.get_text(" ")).strip().lower()
        # An IMAGE-ONLY nav link has no text at all, so label is "" and only
        # the href could ever match a keyword. Confirmed directly on an
        # audited school whose entire navigation is picture buttons: the
        # roster link's alt text read "Kadra" while its href was an opaque
        # "/index.php?id=42". The accessible name of an image link IS its
        # alt/title attribute, so it belongs in the same haystack as the
        # anchor's own text.
        haystack = f"{href.lower()} {label} {_image_alt_text(a)}"
        if any(_keyword_matches(kw, haystack) for kw in SUBPAGE_EXCLUDE_KEYWORDS):
            continue
        full = urljoin(base_url, href)
        # Tier -1 means "the entrance to a DIFFERENT section/subsite worth
        # jumping to" -- only meaningful when the link actually points
        # somewhere other than the page we're already parsing. Confirmed
        # directly: once inside a school's own correct subsite
        # (ekola.edu.pl/liceum/), that subsite's OWN internal nav labels
        # ("Klasa 1 liceum", "Zasady liceum") still contain the level word
        # and kept re-matching tier -1, outranking genuine kadra/kontakt
        # links found elsewhere and burning the crawl budget on enrollment
        # pages before ever reaching the real staff page.
        if school_name and (
            (_is_own_school_hub_link(label, school_name) and not _same_organization_host(full, base_url))
            or _is_bare_hub_label(label, paired_bare_labels)
        ):
            tier = -1
        else:
            # BUG FIX: matching "bip" against the full href+label haystack
            # meant EVERY individual document a school's own BIP section
            # publishes -- confirmed directly: a homepage's "recent BIP
            # posts" widget listed ~18 procurement/financial notices, each
            # a distinct href under /bip/... with its own specific label
            # ("Sprawozdania finansowe za rok 2025", "Plan postępowań...")
            # -- falsely inherited top (tier 0) priority purely because
            # "bip" is a substring of every one of their URLs. That
            # flooded the frontier with 18 tier-0 entries ahead of the
            # genuinely useful "Zarządzenia Dyrektora" (tier 1) and
            # "Kontakt" (tier 2) links also on the same page, burning the
            # whole crawl budget on financial reports before ever reaching
            # either. Only the LABEL is checked for this one tier -- "bip"
            # as a URL substring is nearly guaranteed on any subpage of an
            # active BIP section, so it's not a meaningful signal there,
            # while a label like "Strona główna BIP" (the actual entrance,
            # the only one of those 18 that said so) still is.
            is_bip_tier = tier_offset == 0
            tier = None
            for i, kws in enumerate(tiers):
                check_haystack = label if (is_bip_tier and i == 0) else haystack
                if any(_keyword_matches(kw, check_haystack) for kw in kws):
                    tier = i + tier_offset
                    break
            if tier is None:
                # No keyword matched -- but a level-named subdomain of the
                # school's own domain (sp.zsosto.pl behind a bare "wejdź")
                # is a hub entrance in its own right; see
                # _same_level_subsite_host. Same tier -1 as a labelled hub
                # link: adopted only after the destination itself passes
                # the city check in the crawl loop.
                if school_name and _same_level_subsite_host(full, base_url, school_name):
                    tier = -1
                else:
                    continue
        if _registrable_domain(urlparse(full).netloc) != base_domain:
            continue  # same organization only (subdomains OK, e.g. bip.szkola.pl)
        # A same-page anchor ("#kontakt") urljoins to a URL that's never
        # string-equal to base_url (the fragment is appended), but it's
        # still the exact same page -- confirmed directly: a single-page
        # site's only "subpage link" was its own "#kontakt" anchor, which
        # slipped past a literal `full == base_url` check and blocked the
        # COMMON_PROBE_SLUGS fallback from ever running (that fallback only
        # fires when subpage_links comes back empty). _dedup_key ignores
        # the fragment (and query), the same way it already collapses
        # http/https and www/non-www variants of one page.
        if full in seen or _dedup_key(full) == _dedup_key(base_url):
            continue
        if full.lower().split("?")[0].endswith(NON_HTML_EXTENSIONS):
            continue  # skip PDFs/images/docs -- not a page worth parsing
        seen.add(full)
        found.append((tier, full))

    return found


# A "chooser" hub -- a page that's just a small set of links out to each
# of its separately-hosted sub-institutions' own sites -- is invisible to
# everything above whenever those links don't carry a label the
# tier/keyword system recognizes. Confirmed directly, two different real
# shapes of this same underlying problem:
#   - zpo3dzialdowo.pl's homepage has exactly 2 links, each a bare
#     `<a href="..."><img src="Strona2.png"/></a>` with no text, no alt,
#     no title at all -- nothing for _is_own_school_hub_link or
#     _is_bare_hub_label to match against. A genuinely different
#     REGISTRABLE domain on the other end (edupage.org vs. a bespoke
#     .pl domain), so it'd also be discarded outright by
#     _find_subpage_links's own "same organization only" filter even if
#     it WERE labelled.
#   - zsplw.pl's homepage links to szkola.zsplw.pl and
#     przedszkole.zsplw.pl (the school and kindergarten, SAME
#     registrable domain, different subdomains -- so _find_subpage_links
#     itself would keep these), each labelled just "Wejście" ("Enter") --
#     a generic call-to-action, not an institution-type word, so neither
#     _is_own_school_hub_link (needs a level-stem match) nor
#     _is_bare_hub_label (needs the bare word "Szkoła"/"Przedszkole"
#     exactly) recognizes it either.
#
# Recognized here by SHAPE instead of label: a page this sparse (a
# handful of links, almost no visible text of its own) is a chooser, not
# a real content page, so every link to a different HOST -- same
# registrable domain or not -- is a candidate, trusted only once FETCHED
# and confirmed by the destination's own content (_page_matches_school),
# never by the incoming link's label. Capped at a handful of
# links/fetches so an ordinary sparse homepage that ISN'T actually a
# chooser can't run away with the crawl budget on a false match attempt.
_MAX_HUB_CANDIDATE_LINKS = 6
_MAX_HUB_CANDIDATE_FETCHES = 3


def all_candidate_links(soup: BeautifulSoup, base_url: str, limit: int = 120) -> list[tuple[str, str]]:
    """Every navigable link on a page as (label, absolute_url), in document
    order, deduplicated -- the RAW input for an LLM nav-picker (see
    scrape_school_website's staff_page_picker).

    Deliberately much wider than _find_subpage_links: no keyword tiering,
    no same-domain restriction, no exclude list. Those filters are exactly
    what hides an untiered roster (an image-only nav, an English label, a
    roster on the school's own other subdomain), so the picker has to see
    what they would have dropped. It stays cheap because it only ever
    feeds ONE model call, and the picker may only return URLs from this
    list -- nothing here is fetched on the strength of appearing in it.

    Excluded outright: same-page anchors, mailto/tel/javascript, obvious
    binaries, and the e-register/social links every Polish school site
    carries (never a staff roster, and they crowd the list)."""
    out: list[tuple[str, str]] = []
    seen: set[str] = set()
    for a in soup.select("a[href]"):
        href = (a.get("href") or "").strip()
        if not href or href.startswith(("mailto:", "tel:", "javascript:", "#")):
            continue
        if EMAIL_RE.fullmatch(href):
            continue
        full = urljoin(base_url, href).split("#")[0]
        if full.lower().endswith(NON_HTML_EXTENSIONS):
            continue
        if any(noise in full.lower() for noise in _NAV_NOISE_HOSTS):
            continue
        key = _dedup_key(full)
        if not key or key in seen or key == _dedup_key(base_url):
            continue
        seen.add(key)
        # Case preserved here (unlike the keyword-matching haystack): this
        # label is read by a model, and "Our Team" reads as a nav item
        # where "our team" reads as prose.
        label = re.sub(r"\s+", " ", a.get_text(" ")).strip()
        if not label:
            img = a.select_one("img[alt], img[title]")
            if img:
                label = re.sub(r"\s+", " ", img.get("alt") or img.get("title") or "").strip()
        out.append((label, full))
        if len(out) >= limit:
            break
    return out


# Third-party destinations on essentially every Polish school homepage.
# None can be a staff roster, and together they can fill an entire nav.
_NAV_NOISE_HOSTS = (
    "facebook.com", "instagram.com", "youtube.com", "twitter.com", "x.com", "tiktok.com",
    "linkedin.com", "librus.pl", "synergia.librus", "vulcan.edu.pl", "dziennik.", "eduvulcan",
    "gov.pl", "men.gov.pl", "ore.edu.pl", "google.com", "office.com", "microsoft.com",
    "wordpress.org", "bip.gov.pl",
)


def _find_hub_candidates(soup: BeautifulSoup, base_url: str) -> list[str]:
    base_host = urlparse(base_url).netloc.lower().removeprefix("www.")
    text_len = len(re.sub(r"\s+", "", soup.get_text()))
    links = [urljoin(base_url, a["href"]) for a in soup.select("a[href]") if a.get("href")]
    links = [link for link in links if link.startswith(("http://", "https://"))]
    if text_len > 600 or len(links) > _MAX_HUB_CANDIDATE_LINKS:
        return []
    candidates: list[str] = []
    seen: set[str] = set()
    for full in links:
        if full.lower().split("?")[0].endswith(NON_HTML_EXTENSIONS):
            continue
        host = urlparse(full).netloc.lower().removeprefix("www.")
        if host != base_host and full not in seen:
            seen.add(full)
            candidates.append(full)
    return candidates[:_MAX_HUB_CANDIDATE_FETCHES]


def _page_matches_school(html: str, school_name: str) -> bool:
    """Confirms a fetched hub-candidate page is genuinely THIS school, not
    a sibling institution sharing the same chooser hub -- checked against
    the destination's own content, never the incoming link's label/text
    (which, for the pages this exists to handle, often carries none at
    all). A patron name (see _patron_name_tokens) is the strongest signal
    available -- specific enough that a sibling kindergarten or liceum on
    the same hub essentially never shares it -- checked FIRST, but not
    exclusively: falls back to the school's own level+number
    ("podstawowa" + "nr 4"), the next most distinguishing pair its own
    name carries, whenever the patron check doesn't confirm a match.

    BUG FIX: a patron existing wrongly short-circuited straight to
    "reject" when the patron itself just isn't mentioned on THIS
    particular page -- confirmed directly: "SZKOŁA PODSTAWOWA NR 4 IM.
    JANA PAWŁA II"'s own real homepage (szkola.zsplw.pl) plainly reads
    "Szkoła Podstawowa nr 4 w Lidzbarku Warmińskim" -- a clear number+level
    match -- but never once mentions the patron "Jana Pawła II" anywhere
    on that specific page (a common real pattern: the patron's own
    biography usually lives on a separate "Patron" subpage, not the
    homepage). A school with neither signal simply can't be confirmed
    this way and the candidate is left untrusted.

    BUG FIX: the number and level checks used to run INDEPENDENTLY --
    "nr 3" anywhere on the page, AND a level stem anywhere on the page,
    treated as good enough together even when they weren't actually
    talking about the same thing. Confirmed directly: a sibling
    kindergarten sharing the Działdowo hub wrongly "matched" a school
    numbered 3 this way -- its own footer names the shared PARENT
    complex, "Zespół Placówek Oświatowych **nr 3**" (that "3" is the
    complex's number, not this school's), and separately mentions
    "podstaw**a programowa**" ("core curriculum" -- a phrase every
    school AND kindergarten site has, nothing to do with being a
    "szkoła podstawowa"). Requiring the level word to be immediately
    followed by "nr N" (as an ordinary school actually writes its own
    name -- "Szkoła Podstawowa nr 4") closes both holes at once."""
    haystack = re.sub(r"\s+", " ", BeautifulSoup(html, "html.parser").get_text(" ")).lower()
    patron_tokens = _patron_name_tokens(school_name)
    if patron_tokens:
        hits = sum(1 for token in patron_tokens if token in haystack)
        if hits >= max(1, len(patron_tokens) - 1):
            return True
    name_lower = school_name.lower()
    number_match = re.search(r"\bnr\.?\s*(\d+)\b", name_lower)
    if not number_match:
        return False
    number = number_match.group(1)
    relevant_stems = [stem for stem in _SCHOOL_LEVEL_STEMS if stem in name_lower]
    return any(re.search(rf"{re.escape(stem)}\w*\s+nr\.?\s*{number}\b", haystack) for stem in relevant_stems)


_POLISH_FOLD = str.maketrans("ąćęłńóśźż", "acelnoszz")


def _school_city_stem(school_name: str) -> str | None:
    """The trailing "w/we <City>" of a Polish school name, folded to a
    short stem that survives declension: "W RZESZOWIE" -> "rzes", which
    matches both "Rzeszów" and "Rzeszowie"; "WE WROCŁAWIU" -> "wroc".
    None when the name carries no city (nothing to check against)."""
    m = re.search(r"\bwe?\s+([a-ząćęłńóśźż][\wąćęłńóśźż-]*)\s*$", school_name.strip(), re.IGNORECASE)
    if not m:
        return None
    city = m.group(1).lower().translate(_POLISH_FOLD)
    return city[:4] if len(city) >= 4 else city


def _mentions_school_city(school_name: str, *haystacks: str | None) -> bool:
    """True when any haystack (page html, URL) mentions the city named in
    the school's own name -- or trivially when the name has no city.

    The guard that keeps a shared CHAIN domain from donating a sibling
    branch's page as this school's "own subsite". Confirmed real failure
    (TEB Rzeszów): the crawler adopted szkolasrednia.teb.pl/miasta/d/
    swidnica/ -- the Świdnica branch's page, a different city 250 km away
    -- as the Rzeszów school's website, persisted it, and every subsequent
    enrichment then read the wrong branch. A page that is genuinely this
    school's own will mention its city; one that can't clear that bar must
    never become this school's recorded website."""
    stem = _school_city_stem(school_name)
    if stem is None:
        return True
    for haystack in haystacks:
        if haystack and stem in haystack.lower().translate(_POLISH_FOLD):
            return True
    return False


# A school's site sometimes moves house entirely -- the OLD domain (often
# a legacy free host like wodip.opole.pl, from an older generation of
# Polish school hosting) is left running, but every real link on every
# one of its pages now points at the NEW domain. Confirmed directly:
# zs_baborow.wodip.opole.pl serves the exact same homepage content for
# every guessed path (no real per-page routing left at all -- a stale
# shell), and of its ~230 outbound links, 220 point to zspbaborow.edu.pl
# (the rest are the ordinary WordPress-theme social-share/credit
# boilerplate every page like this carries). That's a fundamentally
# different shape from the bare "chooser hub" case above (a handful of
# unlabeled links, almost no content of its own) -- this is a normal,
# content-rich page whose real navigation just happens to lead somewhere
# else entirely. Detected by DOMINANCE (one other domain must be a clear
# majority of all outbound links, not merely the most common one) rather
# than content-matching each candidate, since a real page this rich in
# genuine navigation is already strong evidence on its own -- checking
# every single one of 220 links individually the way the hub-candidate
# path does would be needless, slow, and redundant.
_MIN_MIGRATION_LINKS = 5
_MIGRATION_DOMINANCE_RATIO = 0.6

# The homepage's own LLM tier. It used to be merged at _merge's default
# tier 0 -- the same tier as a BIP staff roster -- which made two
# downstream tests meaningless: llm_extract.cap_pages ranked the homepage
# ahead of the school's real "kadra"/"dyrekcja" page for the prompt budget,
# and needs_escalation's "did the bundle contain a staff-bearing page?"
# check passed for literally every school. A homepage is a general page:
# ranked below bip(0), staff listings(1) and kontakt(2), alongside the
# other general "o-szkole"(3) pages.
HOMEPAGE_TIER = 3


def _detect_domain_migration(soup: BeautifulSoup, base_url: str) -> str | None:
    base_domain = _registrable_domain(urlparse(base_url).netloc)
    domain_counts: dict[str, int] = {}
    total = 0
    for a in soup.select("a[href]"):
        href = a.get("href")
        if not href or not href.startswith(("http://", "https://")):
            continue
        domain = _registrable_domain(urlparse(href).netloc)
        if domain == base_domain:
            continue
        total += 1
        domain_counts[domain] = domain_counts.get(domain, 0) + 1
    if not domain_counts:
        return None
    top_domain, top_count = max(domain_counts.items(), key=lambda kv: kv[1])
    if top_count < _MIN_MIGRATION_LINKS or top_count / total < _MIGRATION_DOMINANCE_RATIO:
        return None
    return top_domain


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
    not the whole flattened column" fix.

    BUG FIX: a real staff page can have an outer <tr> that wraps a NESTED
    table (or a malformed/duplicated markup structure) -- confirmed
    directly: its own get_text() then returns the ENTIRE staff list
    concatenated as one giant row, ahead of the genuinely-one-teacher-each
    rows in find_all("tr")'s own result order. Since the English-teacher
    scan takes the FIRST entry containing the keyword, that giant blob's
    OWN first name (the director, teaching art two rows above the actual
    English teacher) won -- a wrong-person misattribution, not just a
    missed one. The same title-prefix split already applied to <li>/<p>
    below fixes this the same way: splitting the giant blob turns it back
    into the same one-teacher-per-entry pieces the individual rows
    already provide, so even if it's scanned first, its first "mgr Name
    Subject" piece is now the row it actually corresponds to."""
    entries: list[str] = []
    for tr in soup.find_all("tr"):
        row = re.sub(r"\s+", " ", tr.get_text(" ", strip=True))
        if not row:
            continue
        parts = [p.strip() for p in _TITLE_SPLIT_RE.split(row) if p.strip()]
        entries.extend(parts if len(parts) > 1 else [row])
    # BUG FIX: confirmed directly -- a real CMS-rendered staff page put
    # its whole "Name - Subject<br>Name - Subject<br>..." list inside a
    # bare <div> with no <li>/<dd>/<p> anywhere, which this loop
    # previously never looked inside at all (found zero entries, not
    # wrong ones). <div> is otherwise the most generic, deeply-nested
    # container in HTML -- safe to add here because a large ancestor
    # <div> wrapping many unrelated elements still gets a "\n" separator
    # inserted at every tag boundary (not just literal <br>s), so it
    # splits into many small, mostly-irrelevant lines rather than one
    # giant merged blob; only a line that actually contains both a valid
    # name and the keyword ever matches anything downstream.
    for el in soup.find_all(["li", "dd", "p", "div"]):
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
        match = _ENGLISH_KEYWORD_RE.search(entry)
        if match:
            # A prize-winners list rendered as list items reaches here as an
            # ordinary "entry" ("Język Angielski: Karolina Brzozowska - tytuł
            # laureata") -- same student-not-teacher trap as the flattened
            # path below, so the same guard applies (see
            # _in_achievement_context).
            if _in_achievement_context(entry, match.start(), match.end()):
                continue
            name = _person_name_in(entry, patron_tokens)
            if name:
                return name
    return None


# Per-page cap for the LLM-ready text (see _prepare_page_for_llm) -- the
# overall per-school budget (llm_extract.cap_pages: 8 pages / ~50,000
# chars) still applies on top of this, but capping each page individually
# first means one enormous page (a whole BIP archive, say) can't by
# itself starve every other page out of the school-level budget.
_MAX_LLM_PAGE_CHARS = 8_000

# Role-aware truncation. A staff roster longer than the per-page budget used
# to be cut blind at the head, so a school listing "JEZYK ANGIELSKI" late in
# a long table had the role label removed before the model ever saw the page.
# Measured on 35 crawled staff pages of teacher-less schools: 8 exceeded the
# cap and 2 of those 8 mentioned English ONLY past the cut -- silently
# unextractable. Now the head is kept AND windows around role vocabulary
# found beyond it are appended, inside the same total budget, with a marker
# so the model can see text was elided. Pages with no role vocabulary in the
# tail keep the old contiguous behaviour exactly.
_TRUNCATION_HEAD_CHARS = 6_000
_TRUNCATION_WINDOW_CHARS = 500
_TRUNCATION_MARKER = chr(10) + "[...]" + chr(10)
_TRUNCATION_ROLE_RE = re.compile(r"angiel|dyrektor", re.IGNORECASE)
# A role LABEL ("J. angielski: Anna", "nauczyciel jezyka angielskiego"),
# as opposed to a biography mention ("ukonczyla filologie angielska",
# "czyta poezje angielskiego romantyzmu"). On a long staff page the two
# compete for the same truncation budget, and the decoys often come
# first -- Lighthouse Montessori lists its real English teachers ("J.
# angielski | Karolina Kaniowska") at char 34,000 of a 42,000-char page,
# behind several teachers who merely STUDIED English philology, so the
# 8,000-char cap kept the decoys and cut the real ones. A role label
# needs a role word ("j.", "jezyk", "nauczyciel", "lektor", "anglist")
# bound to "angielski" -- "filologia angielska" has none of those.
_TRUNCATION_STRONG_ROLE_RE = re.compile(
    r"(?:j\.\s*angielski"
    r"|j(?:ę|e)zyk\w*\s+angielski"
    r"|nauczyciel\w*\s+(?:j\.\s*|j(?:ę|e)zyk\w*\s+)?angielski"
    r"|lektor\w*\s+(?:j\.\s*|j(?:ę|e)zyk\w*\s+)?angielski"
    r"|anglist"
    r"|dyrektor)",
    re.IGNORECASE,
)


def _merge_interval(merged: list[list[int]], start: int, end: int) -> tuple[list[list[int]], int]:
    """Insert [start, end) into a sorted list of disjoint intervals.

    Returns the new list and how many characters were NOT already covered
    -- the honest cost of adding this window (see _cap_for_llm)."""
    already = sum(max(0, min(end, s_end) - max(start, s_start)) for s_start, s_end in merged)
    out: list[list[int]] = []
    lo, hi = start, end
    for s_start, s_end in merged:
        if s_end < lo or s_start > hi:
            out.append([s_start, s_end])
        else:
            lo, hi = min(lo, s_start), max(hi, s_end)
    out.append([lo, hi])
    out.sort()
    return out, (end - start) - already


def _cap_for_llm(text: str) -> str:
    if len(text) <= _MAX_LLM_PAGE_CHARS:
        return text
    head, tail = text[:_TRUNCATION_HEAD_CHARS], text[_TRUNCATION_HEAD_CHARS:]

    # A window is only USEFUL if it puts the role word next to a person's
    # NAME -- that pairing is what the extraction has to ground against.
    #
    # Windows used to be merged as they were discovered and then filled
    # first-come-first-served, which on a long page spends the entire
    # budget on whichever mentions come first: marketing prose ("nauka
    # języka angielskiego w wymiarze rozszerzonym"), never the roster.
    # Confirmed directly on a 34,000-char school page that says "angielski"
    # thirty times in its programme copy before the staff table at ~17,000
    # -- and because every one of those mentions overlaps the next, they
    # merged into ONE window so large that truncating it threw the roster
    # away regardless. So candidates are collected per match and UNMERGED,
    # ranked so name-bearing ones are taken first, and only the selected
    # ones are merged and emitted in document order. Same budget, same
    # token cost, but the part that can actually name a teacher survives.
    candidates: list[tuple[int, int, bool, bool]] = []
    for match in _TRUNCATION_ROLE_RE.finditer(tail):
        start = max(0, match.start() - _TRUNCATION_WINDOW_CHARS)
        end = min(len(tail), match.end() + _TRUNCATION_WINDOW_CHARS)
        window = tail[start:end]
        named = bool(_NAME_GROUP_RE.search(window))
        strong = bool(_TRUNCATION_STRONG_ROLE_RE.search(window))
        candidates.append((start, end, named, strong))

    if not candidates:  # nothing role-relevant later on -- old contiguous cut
        return text[:_MAX_LLM_PAGE_CHARS]

    budget = _MAX_LLM_PAGE_CHARS - len(head)
    # A window naming a person via a real role LABEL is the most valuable
    # thing on the page; a window merely naming a person is next; anything
    # else last. Ranking strong-role windows first is what lets a real "J.
    # angielski | Name" deep in the page beat shallow "filologia angielska"
    # decoys for the same budget.
    strong_named = [c for c in candidates if c[2] and c[3]]
    named = [c for c in candidates if c[2] and not c[3]]
    rest = [c for c in candidates if not c[2]]
    ordered = strong_named + named + rest

    merged: list[list[int]] = []
    used = 0
    for start, end, _named, _strong in ordered:
        if used >= budget:
            break
        # Charge only characters not already covered. Summing the overlap
        # against each previously-picked window separately double-counts it
        # whenever picks overlap each other -- on a page with 200
        # overlapping windows that drove the running total negative, so the
        # budget never tripped and every window was selected, which is the
        # very starvation this ranking exists to prevent. Coverage is
        # therefore tracked as one merged, disjoint interval set.
        merged, added = _merge_interval(merged, start, end)
        used += added

    out = head
    for start, end in merged:
        if len(out) >= _MAX_LLM_PAGE_CHARS:
            break
        out += (_TRUNCATION_MARKER + tail[start:end])[: _MAX_LLM_PAGE_CHARS - len(out)]
    return out



def _prepare_page_for_llm(html: str, url: str) -> str:
    """Structure-preserving text for the LLM extraction call (see
    llm_extract.py) -- a plain soup.get_text() (what _extract's regex path
    uses) flattens a staff TABLE into one run-on string, losing exactly
    the row structure that ties a name to its own email/subject cell. Same
    trick as _extract's own <br> handling: mutate the parse tree in place
    (table rows -> "cell | cell", list items -> "- item") BEFORE flattening,
    so get_text() can't erase structure it never gets the chance to see."""
    soup = BeautifulSoup(html, "html.parser")

    # Cloudflare's cipher replaces the real address entirely (plain text
    # only ever shows a "[email protected]" placeholder) -- decode every
    # instance IN PLACE, so the address sits exactly where the page put it
    # ("wychowawcy klasy 4a (Anna Kowalska): anna.kowalska@..."). That
    # positional adjacency is what lets the model quote a REAL contiguous
    # name+email pairing passage -- and what lets ground_extraction verify
    # that quote verbatim against this same text (a footer-only decode
    # destroyed the adjacency, making every cloaked pairing unprovable
    # under the strict email_evidence check). Done before any structural
    # flattening so the replacement lands inside its own <td>/<p>.
    decoded_cf = set()
    for el in soup.select("[data-cfemail]"):
        decoded = _decode_cf_email(el.get("data-cfemail", ""))
        if decoded and EMAIL_RE.fullmatch(decoded):
            decoded_cf.add(decoded)
            el.replace_with(decoded)

    for br in soup.find_all("br"):
        br.replace_with("\n")
    for row in soup.find_all("tr"):
        cells = [c.get_text(" ", strip=True) for c in row.find_all(["td", "th"])]
        row.replace_with("\n" + " | ".join(cells) + "\n")
    for li in soup.find_all("li"):
        li.replace_with("\n- " + li.get_text(" ", strip=True) + "\n")

    text = soup.get_text("\n")
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n[ \t]*\n+", "\n", text)
    text = _decode_at_dot_obfuscation(text).strip()

    # Footer kept as well: a summary of every decoded address in one place
    # (and the marker several tests and prompts reference).
    if decoded_cf:
        text += "\n\nDECODED_OBFUSCATED_EMAILS: " + ", ".join(sorted(decoded_cf))

    # Image/PDF/doc links never appear in flattened text at all (they're
    # hrefs, not visible text) -- listed here with their label so a human
    # (via the staff_roster_urls metadata) knows what's worth checking
    # manually. A SECOND, unmutated soup: the <tr>/<li> replacements above
    # collapsed those elements to plain strings, losing any <a href> that
    # lived inside them.
    media_soup = BeautifulSoup(html, "html.parser")
    media_links = []
    for a in media_soup.select("a[href]"):
        href = a["href"]
        if href.lower().split("?")[0].endswith(NON_HTML_EXTENSIONS):
            label = re.sub(r"\s+", " ", a.get_text(" ")).strip()
            absolute = urljoin(url, href)
            media_links.append(f"{absolute} ({label})" if label else absolute)
    if media_links:
        text += "\n\nIMAGE_OR_PDF_LINKS:\n" + "\n".join(media_links)

    return _cap_for_llm(text)


def _extract(html: str, url: str, school_name: str = "") -> dict:
    # Before anything reads this page -- the regex email collector and the
    # LLM-ready text alike -- swap Joomla's cloak placeholders for the real
    # addresses their own script fragments encode. See _decode_joomla_cloaks.
    html = _decode_joomla_cloaks(html)
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
    # A shell is not always a React/Vue mount div: ekola.edu.pl ships 127KB
    # of Elementor markup that renders 20 visible characters, with the whole
    # nav built by JS -- no id="root"/"app" anywhere. Markup that heavy with
    # text that empty cannot be a real content page either way, so it gets
    # the same treatment (and thereby the browser-rendering fallback).
    _tiny_text = len(re.sub(r"\s+", "", text)) < 250
    js_app_shell = _tiny_text and (bool(mount) or len(html) > 20000)

    # BUG FIX: the mount+near-empty check above only catches a shell with
    # almost NO content at all -- it misses the far more common real-world
    # pattern (confirmed directly: zs3wiskitki.pl) of a client-side-routed
    # site whose server response is IDENTICAL for every path, nav chrome
    # and all, just substantial enough (tens of KB) to clear the <250-char
    # bar. That pattern is invisible from a single page's own content; it
    # only shows up by comparing MULTIPLE pages, which is exactly what
    # content_fingerprint exists for -- see _merge, the one place that
    # actually sees more than one page from the same crawl. Hashed on the
    # UNCAPPED flattened text (not _prepare_page_for_llm's 8000-char-capped
    # version) so two genuinely different long pages can never collide
    # just because they share the same nav-heavy prefix.
    content_fingerprint = hashlib.md5(text.encode("utf-8", errors="ignore")).hexdigest()

    phone = None
    match = PHONE_RE.search(text)
    if match:
        phone = re.sub(r"\s+", " ", match.group(1)).strip()

    patron_tokens = _patron_name_tokens(school_name)

    director_name = _earliest_valid_match(
        text, (DIRECTOR_RE, DIRECTOR_NAME_FIRST_RE, DIRECTOR_INSTITUTIONAL_RE, DIRECTOR_FUNKCJA_RE)
    )
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
    # entries, so no single entry holds both. Runs only when the per-entry
    # pass found nothing, so it can't override a correct match. Uses the
    # SAME earliest-position arbitration as the director path -- the old
    # fixed keyword-first priority re-created exactly the bug
    # _earliest_valid_match documents: on flattened "Jan Nowak - język
    # angielski   Anna Kowalska - matematyka" the keyword-first pattern
    # binds "język angielski" to the NEXT person (Anna), while the
    # name-first pattern reads the right one; whichever match starts
    # earliest in the text is the row the keyword actually belongs to.
    if english_teacher_name is None:
        candidate = _earliest_valid_match(
            text,
            (ENGLISH_TEACHER_RE, ENGLISH_TEACHER_NAME_FIRST_RE, ENGLISH_TEACHER_ROLE_LIST_RE),
            achievement_guard=True,
        )
        if candidate and not _is_patron_name(candidate, patron_tokens):
            english_teacher_name = candidate

    return {
        "director_name": director_name,
        "english_teacher_name": english_teacher_name,
        "emails": candidate_emails,
        "phone": phone,
        "source_url": url,
        # Links resolve against where the fetch LANDED, not what was asked
        # for -- see _note_final_url. Only the link base is rebased; the
        # record's own source_url stays the requested URL so the crawl's
        # visited/dedup bookkeeping is unaffected.
        "subpage_links": _find_subpage_links(soup, _final_url_for(url) or url, school_name),
        "email_cloak_detected": email_cloak_detected,
        "content_fingerprint": content_fingerprint,
        # Speciality is derived from the school's official NAME only (seeded
        # in scrape_school_website), never from page body text. Scanning body
        # text produced false positives: every Polish public site carries a
        # mandatory accessibility declaration ("Deklaracja dostępności") that
        # mentions niewidomi/słabowidzący/niesłyszący/niepełnosprawni about
        # the WEBSITE, and Montessori/marketing copy trips specjaln/
        # integracyjn -- none of which mean the school serves that population.
        "specialties": set(),
        "js_app_shell": js_app_shell,
        # Structure-preserving text for the LLM extraction call (see
        # llm_extract.py) -- built from the SAME html this function
        # already parsed, never a second fetch.
        "llm_text": _prepare_page_for_llm(html, url),
    }


_SEARCH_BLOCK_MARKERS = ("anubis_challenge", "unusual traffic", "recaptcha", "are you a robot")

# A cooldown, NOT a permanent kill switch -- confirmed directly: a burst of
# automated requests during heavy same-day testing got this exact IP served
# an "Anubis" proof-of-work challenge page by Startpage (no result links, no
# <title>, the raw HTML containing "anubis_challenge") instead of search
# results, and every one of a whole 146-school batch's remaining schools
# then silently got "search_blocked" with no real attempt at all -- the
# process this app runs as (`--workers 1`, per the Dockerfile) is
# long-lived, with the auto-enrich background thread running in it
# continuously, so a PERMANENT-until-restart flag meant one transient block
# would silently disable search for every future auto-enrich cycle too,
# forever, until a human happened to notice and manually restart the
# container. Retrying after a cooldown window instead means the next
# school enriched after the window passes gets a real attempt again, no
# restart required.
_SEARCH_BLOCK_COOLDOWN_SECONDS = 1800
_search_blocked_until: float = 0.0


def _looks_like_search_block(html: str) -> bool:
    lowered = html.lower()
    return any(marker in lowered for marker in _SEARCH_BLOCK_MARKERS)


def _search_web(query: str, max_results: int = MAX_SEARCH_RESULTS_PER_QUERY) -> list[str] | None:
    """Free, no-key web search -- the only realistic way to reach a
    voivodeship/powiat/gmina/local-news page about one specific school.
    This is scraping a search results page, not a real API: a layout
    change or rate limit just yields fewer or no links, never an
    exception that fails the whole enrichment. Returns `None` (distinct
    from `[]`) when the response itself is an anti-bot challenge rather
    than real results -- "we got blocked" is a different, honest outcome
    from "we searched and genuinely found nothing", and conflating the two
    (as this used to) makes a systemic block look like 38 unrelated
    schools each independently having no web presence.

    BUG FIX: this used to hit DuckDuckGo's HTML endpoint
    (html.duckduckgo.com/html/), which is a genuine, permanent dead end in
    this environment -- confirmed directly (both from the host and from
    inside the container): a raw TCP connection to that host times out,
    while general internet access and DNS resolution both work fine, and
    its "lite" endpoint (a different DuckDuckGo host) is reachable but
    always serves an image CAPTCHA to a plain requests-based fetch, which
    isn't something this scraper should try to solve. Startpage's plain
    HTML results page, by contrast, is reachable and CAPTCHA-free for a
    single ordinary GET at LOW volume -- confirmed directly against
    several of the schools this same search step used to come up empty
    for (e.g. it surfaced PUBLICZNA SZKOŁA PODSTAWOWA NR 1 W PRUDNIKU's
    real site, zsp1prudnik.pl, on the first try). No account or API key
    needed -- but, confirmed directly the same day, sustained automated
    use is enough to get it to challenge-wall this IP the same way
    DuckDuckGo already does, just at a higher request-volume threshold."""
    global _search_blocked_until
    if time.time() < _search_blocked_until:
        return None
    try:
        resp = requests.get(
            "https://www.startpage.com/sp/search",
            params={"query": query},
            timeout=10,
            headers={"User-Agent": USER_AGENT},
        )
        resp.raise_for_status()
    except requests.RequestException:
        return []

    search_text = _decoded_text(resp)
    if _looks_like_search_block(search_text):
        _search_blocked_until = time.time() + _SEARCH_BLOCK_COOLDOWN_SECONDS
        return None

    soup = BeautifulSoup(search_text, "html.parser")
    links: list[str] = []
    seen: set[str] = set()
    for a in soup.select("a.result-link"):
        href = a.get("href")
        if href and href.startswith(("http://", "https://")) and href not in seen:
            seen.add(href)
            links.append(href)
        if len(links) >= max_results:
            break
    return links


def _merge(result: dict, found: dict, *, tier: int = 0, third_party: bool = False) -> None:
    """In-place: fills whichever of director/teacher/phone is still
    missing (first real find wins), and records the first source that
    contributed a find. Every email candidate from every page is kept
    (union, never "first/best wins") -- which one belongs to which
    person can only be judged later, once both names are known.

    Also the single choke point that collects each page's LLM-ready text
    (see _prepare_page_for_llm) into result["llm_pages"] -- every _merge
    call site in the crawl represents a page whose content is actually
    being kept/used, so hooking in here (rather than at each individual
    _extract call) naturally excludes a rejected hub page's content
    without needing a separate "should this count" check.

    Also where cross-page identical-content detection lives (see
    content_fingerprint in _extract) -- a client-side-routed SPA serving
    the exact same response for every URL is invisible from any ONE
    page's own content, so it can only be caught here, where more than
    one page's fingerprint is actually visible at once."""
    url = found.get("source_url")
    if url:
        seen_fingerprints: dict[str, str] = result.setdefault("_seen_fingerprints", {})
        fingerprint = found.get("content_fingerprint")
        if fingerprint:
            first_seen_url = seen_fingerprints.get(fingerprint)
            if first_seen_url and first_seen_url != url:
                result["js_app_shell"] = True
            else:
                seen_fingerprints.setdefault(fingerprint, url)

    # A page with almost no text cannot prove a name or a role, but it WOULD
    # consume one of the eight per-school LLM page slots (llm_extract.
    # cap_pages) and push out a real staff page. Cheap guard, kept small so
    # a genuinely terse contact page ("Sekretariat: ... tel ... e-mail ...")
    # still gets through.
    if found.get("llm_text") and len(_normalize_ws_text(found["llm_text"])) < _MIN_LLM_PAGE_CHARS:
        found = {**found, "llm_text": ""}

    if found.get("llm_text"):
        # Replace, don't duplicate -- a URL re-merged after the js_app_shell
        # fallback below re-fetches it via a real browser is the SAME page
        # appearing a second time, now with its REAL post-JS content. The
        # stale plain-fetch version (by definition uninformative, or this
        # fallback wouldn't have triggered) must not also survive into the
        # LLM prompt alongside it.
        result["llm_pages"] = [p for p in result["llm_pages"] if p["url"] != url] + [
            {"url": url, "text": found["llm_text"], "tier": tier, "third_party": third_party}
        ]

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


# Tiers whose pages ARE the staff roster: BIP (0), the "nauczyciele / kadra
# / grono pedagogiczne / dyrektor" tier (1), and the entrance to the
# school's own subsite on a shared hub domain (-1). See
# SUBPAGE_KEYWORDS_BY_PRIORITY.
_STAFF_PAGE_MAX_TIER = 1

# A NEWS HEADLINE that merely mentions a role word earns the staff tier from
# its slug alone -- confirmed directly: sp31.bydgoszcz.pl publishes
# "/pioro-dyrektora-szkoly/" and "/konkurs-ortograficzny-o-pioro-dyrektora-
# szkoly-wyniki/" (a writing competition named after the head teacher), which
# match the tier-1 "dyrektor" keyword. Fetching those is pre-existing
# behaviour, but they must not HOLD THE GATE below open: doing so spends the
# page budget on prize write-ups and can push the real roster out of the
# LLM's 8-page window, turning a fix for missed teachers into a cause of
# them. Competition vocabulary in a URL is a reliable tell, and it costs
# nothing if wrong -- the page is still crawled at its own tier, it just
# stops being a reason to keep crawling.
_NEWS_SLUG_RE = re.compile(r"(?i:konkurs|laureat|olimpiad|wyniki|gratulacj)")


def _staff_page_pending(frontier: list[tuple[int, str]], visited: set[str]) -> bool:
    """True while a staff-roster page is queued but still unread. Used to
    hold _is_complete open -- see its own docstring for why."""
    for tier, url in frontier:
        if tier > _STAFF_PAGE_MAX_TIER or _dedup_key(url) in visited:
            continue
        if _NEWS_SLUG_RE.search(url):
            continue
        return True
    return False


def _is_complete(result: dict, *, staff_page_pending: bool = False) -> bool:
    # Only a PERSONAL-candidate address (priority 0 -- an unrecognized
    # local part that may be someone's own box) ends the crawl early.
    # This used to stop on any office-tier address too, which directly
    # contradicted the tool's contact priority -- confirmed directly:
    # sp.zsosto.pl's /kadra/ lists seven English teachers' personal
    # emails, but the crawl declared itself complete on
    # "sekretariat@zsosto.pl" one page short of ever fetching it, with
    # half its page budget unspent. Holding out for a personal candidate
    # is bounded (MAX_SAME_SITE_PAGES caps the worst case at a few extra
    # fetches on schools that only ever publish an office box), and a
    # school that DOES publish personal addresses is exactly the school
    # worth the extra pages. (Final personal-vs-generic attribution still
    # happens after the crawl, in jobs.py.)
    #
    # The names this checks are REGEX-derived, and regex names are never
    # written to a school record -- only an LLM record grounded in a verbatim
    # page quote is (see jobs.py). So the crawl's real product is the set of
    # pages handed to the LLM, and a name too weak to write must not be
    # strong enough to end the page budget. Confirmed directly: on
    # psp.bialystok.pl the homepage's prize-winners list yielded a "teacher"
    # who was actually a pupil, which satisfied this check two pages in and
    # stopped the crawl -- so /teachers/, the page that really does name the
    # English teacher (Agnieszka Konopka, "Język angielski / Science in
    # English"), was queued at tier 1 and never fetched. The LLM then had no
    # page that could prove a teacher, and the school ended up with none.
    # Holding out while any staff-roster page is still unread is bounded
    # (MAX_SAME_SITE_PAGES caps the crawl regardless) and cheap: those pages
    # are few, and they are exactly the ones worth spending budget on.
    if staff_page_pending:
        return False
    emails = result.get("all_emails") or set()
    personal_candidate = bool(emails) and min((email_priority(e) for e in emails), default=2) < 1
    return bool(result["director_name"] and result["english_teacher_name"] and personal_candidate)


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
        sources_checked.append({"url": url, "status": _fetch_failure_status(url), "rendered": True})
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
                _merge(result, found, tier=HOMEPAGE_TIER)
                frontier: list[tuple[int, str]] = list(found["subpage_links"])

                while (
                    frontier
                    and pages_rendered < MAX_RENDERED_PAGES
                    and not _is_complete(result, staff_page_pending=_staff_page_pending(frontier, visited))
                ):
                    frontier.sort(key=lambda pair: pair[0])
                    tier, link = frontier.pop(0)
                    if _dedup_key(link) in visited:
                        continue
                    visited.add(_dedup_key(link))
                    sub_html = _render_page(browser, link, sources_checked)
                    pages_rendered += 1
                    if sub_html:
                        sub_found = _extract(sub_html, link, school_name)
                        _merge(result, sub_found, tier=tier)
                        frontier.extend(
                            pair for pair in sub_found["subpage_links"] if _dedup_key(pair[1]) not in visited
                        )
            finally:
                browser.close()
    except Exception:  # noqa: BLE001 -- launch/driver failure must not fail the whole enrichment
        return rendered_any
    return rendered_any


# RSPO's own "website" field is sometimes blank even when its "email"
# field isn't -- confirmed directly on real schools whose only remaining
# clue to a working site was their own email's domain. A shared public
# mailbox provider tells us nothing about the school's own site, so those
# are excluded up front rather than tried and predictably rejected.
_GENERIC_EMAIL_DOMAINS = frozenset({
    "gmail.com", "wp.pl", "onet.pl", "interia.pl", "o2.pl", "poczta.fm",
    "yahoo.com", "outlook.com", "hotmail.com", "op.pl", "tlen.pl", "vp.pl",
})

# A candidate domain from an email is NOT trusted blindly -- confirmed
# directly: a school's own email used its GMINA's domain (its mail is
# just hosted there), and that domain's real homepage is the town hall's
# own site ("Strona główna - Urząd Miejski w Kietrzu"), not the school's.
# Checking for a municipal-office signal (reject) vs. an actual
# school/kindergarten/education-institution signal (accept) is the same
# distinction a human glancing at the page would make.
_MUNICIPAL_TITLE_KEYWORDS = ("urząd", "urzad", "gmina", "starostwo powiatowe")
# BUG FIX: "Zespół Placówek Oświatowych" (ZPO) -- a multi-institution
# complex umbrella term as legitimate and common as "Zespół Szkół"/"Zespół
# Szkolno-Przedszkolny", just naming itself by the broader "placówek
# oświatowych" (educational institutions/facilities) rather than "szkół"
# specifically -- wasn't covered at all, confirmed directly:
# "Zespół Placówek Oświatowych nr 3 w Działdowie" (that complex's own,
# entirely genuine title) matched none of the keywords below and got
# rejected as "not a school site".
_SCHOOL_TITLE_KEYWORDS = (
    "szkoł", "szkol", "przedszkol", "zespół szkó", "zespol szko", "liceum", "technikum", "gimnazjum",
    "placówek oświatow", "placowek oswiatow",
    # International schools in Poland present themselves in their partner
    # language -- wbs.pl (Willy-Brandt-Schule, a real Warsaw SP in this
    # register) is German-first and its title says "Begegnungsschule",
    # never "szkoła", so verification rejected the school's own genuine
    # homepage and everything downstream starved.
    "school", "schule", "école", "ecole", "colegio",
)


def _verify_school_site(html: str) -> bool:
    """BUG FIX: the <title> alone is often too generic to tell anything
    from at all -- confirmed directly: a real school's own homepage had
    the bare title "Strona Główna" ("Home Page"), which matches neither
    keyword list, only failing verification here even though its own
    <meta name="keywords"> plainly named the school ("... Publiczna
    Szkoła Podstawowa nr 28 ..."). Meta description/keywords and a slice
    of the page's own visible text are checked too, for exactly the
    signal a human would find by actually reading the page rather than
    just glancing at the browser tab.

    BUG FIX: a real school's own site routinely links to its local
    "Urząd Miejski"/gmina site in its nav or footer -- an ordinary
    courtesy link, not a sign this IS the municipal site -- confirmed
    directly: a genuine "Zespół Szkolno-Przedszkolny w Bisztynku" homepage
    (title says so outright) got rejected outright purely because its own
    footer also happened to mention "Urząd Miejski w Bisztynku". The
    municipal veto below is only meant for a page that DOESN'T otherwise
    read as a school at all (e.g. a gmina homepage with no school
    keyword anywhere) -- so a school keyword found in the <title>
    specifically (a page's own clear self-description, far less noisy
    than its full nav/footer) is checked FIRST and short-circuits the
    veto entirely."""
    soup = BeautifulSoup(html, "html.parser")
    # re.sub(r"\s+", ...) also normalizes a non-breaking space (\xa0) to a
    # plain one -- needed here too since a couple of these keywords are
    # two-word phrases ("placówek oświatow", "zespół szkó") that a
    # real title could join with "&nbsp;" the same way _find_subpage_links
    # confirmed a nav label does.
    title = re.sub(r"\s+", " ", soup.title.get_text()) if soup.title else ""
    title_lower = title.lower()
    if any(kw in title_lower for kw in _SCHOOL_TITLE_KEYWORDS):
        return True
    meta_bits = [
        tag.get("content", "")
        for tag in soup.find_all("meta")
        if tag.get("name", "").lower() in ("keywords", "description")
    ]
    body_text = re.sub(r"\s+", " ", soup.get_text(" ", strip=True))[:1500]
    haystack = " ".join([title, *meta_bits, body_text]).lower()
    # A JS app shell renders almost NO text to read -- ekola.edu.pl ships
    # 127KB of markup and 20 visible characters ("Główna - Ekola Close"),
    # so a genuine school homepage failed verification and everything
    # downstream (crawl, search fallback, browser rendering) was starved.
    # When the visible text can't possibly identify the page either way,
    # judge from the markup itself: a school's shell still carries school
    # words in its meta tags, nav labels, and asset paths.
    if len(body_text) < 200:
        haystack = " ".join([haystack, html[:30000].lower()])
    if any(kw in haystack for kw in _MUNICIPAL_TITLE_KEYWORDS):
        return False
    return any(kw in haystack for kw in _SCHOOL_TITLE_KEYWORDS)


def _derive_website_from_email(email: str | None) -> str | None:
    if not email or "@" not in email:
        return None
    domain = email.rsplit("@", 1)[1].strip().lower()
    if not domain or domain in _GENERIC_EMAIL_DOMAINS:
        return None
    return f"http://{domain}"


def _picked_staff_links(
    staff_page_picker, html: str, base_url: str, school_name: str, city: str | None
) -> list[str]:
    """Run the injected LLM nav-picker over a page's raw link list.

    Injected rather than imported: llm_extract imports THIS module, so
    calling it from here directly would be a cycle -- and keeping the
    dependency inverted also means the crawler stays runnable (and
    testable) with no LLM at all, which the offline fallback path relies
    on. Any failure inside the picker is swallowed: a nav-picking miss
    must never take down a crawl that keyword tiering could still finish.
    """
    try:
        candidates = all_candidate_links(BeautifulSoup(html, "html.parser"), base_url)
        if not candidates:
            return []
        offered = {url for _, url in candidates}
        picked = staff_page_picker(candidates, school_name, city) or []
        # Enforced HERE, not only inside the LLM implementation: this is the
        # boundary where an outside-supplied callable gets to influence what
        # the crawler fetches, so the allow-list has to hold whatever the
        # picker is. Anything not offered is discarded rather than visited.
        return [url for url in picked if url in offered]
    except Exception:  # noqa: BLE001 -- see docstring; UsageLimitError is re-raised below
        if _is_usage_limit_error():
            raise
        return []


def _is_usage_limit_error() -> bool:
    """True when the exception currently being handled is the LLM
    usage-window exhaustion that run_job must stop the whole batch on --
    matched by name so this module keeps no import of llm_extract."""
    exc = sys.exc_info()[1]
    return exc is not None and type(exc).__name__ == "UsageLimitError"


def scrape_school_website(
    school_name: str,
    website_url: str | None,
    rspo_email: str | None = None,
    *,
    staff_page_picker=None,
    city: str | None = None,
) -> dict:
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
        # Structure-preserving text of every page actually kept/used during
        # the crawl (see _merge), for the single post-crawl LLM extraction
        # call in jobs.py -- never re-fetched, built from the same HTML the
        # regex path already parsed. augment_with_web_search (called
        # separately, after this function returns) appends its own pages
        # here too, tagged third_party=True.
        "llm_pages": [],
        # Internal only (leading underscore, never read by callers outside
        # _merge): content_fingerprint -> first URL that produced it, used
        # to detect a client-side-routed SPA serving identical content for
        # every path (see _merge).
        "_seen_fingerprints": {},
    }
    sources_checked: list[dict] = []

    def _note_cloak(found: dict) -> None:
        if not result["all_emails"] and found.get("email_cloak_detected"):
            result["email_cloak_detected"] = True

    # 0. No website on file anywhere (neither our own record nor RSPO's)
    # -- before falling all the way through to a web search, try the
    # school's own email domain as one last structured guess. Verified
    # before being trusted (see _verify_school_site): a wrong guess here
    # would otherwise get silently recorded as this school's own site.
    if not website_url:
        candidate = _derive_website_from_email(rspo_email)
        if candidate:
            candidate_html = fetch_page(candidate)
            if candidate_html and _verify_school_site(candidate_html):
                sources_checked.append({"url": candidate, "status": "ok", "derived_from_email": True})
                website_url = candidate
                result["discovered_website_url"] = candidate
            else:
                sources_checked.append({"url": candidate, "status": _fetch_failure_status(candidate), "derived_from_email": True})

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

        # BUG FIX: a real, non-empty website_url isn't always the
        # SCHOOL's own site -- confirmed directly: RSPO's own "website"
        # field for one school pointed at the local town's generic
        # homepage ("Urząd Miejski w Orzyszu") instead of the school's
        # own site. Every guessed "kontakt"/"dyrekcja"/"kadra" slug on
        # that domain resolved fine (200 OK, since a town site has its
        # own such pages too), silently burning the entire crawl budget
        # on the MAYOR's office rather than the school -- a wrong-site
        # false negative, not a missing-website one. The same
        # title/meta/body-text check already used for an email-derived
        # candidate (_verify_school_site) catches this just as well
        # applied to a GIVEN url; failing it here is treated exactly like
        # "no website was on file" -- falls through to the same
        # email-derived candidate this function already tries in that
        # case, rather than trusting the wrong site's own content.
        wrong_site = html is not None and not _verify_school_site(html)
        if wrong_site:
            sources_checked.append({"url": homepage, "status": "not_a_school_site"})
            html = None
            candidate = _derive_website_from_email(rspo_email)
            if candidate and _dedup_key(candidate) != _dedup_key(homepage):
                candidate_html = fetch_page(candidate)
                pages_fetched += 1
                if candidate_html and _verify_school_site(candidate_html):
                    sources_checked.append({"url": candidate, "status": "ok", "derived_from_email": True})
                    homepage = _normalize_url(candidate)
                    effective_homepage = homepage
                    visited = {_dedup_key(homepage)}
                    html = candidate_html
                    result["discovered_website_url"] = candidate
                else:
                    sources_checked.append({"url": candidate, "status": _fetch_failure_status(candidate), "derived_from_email": True})

        if html:
            if not wrong_site:
                sources_checked.append({"url": homepage, "status": "ok"})
                migrated_domain = _detect_domain_migration(BeautifulSoup(html, "html.parser"), effective_homepage)
                # A "migration" is only credible if the site we already have
                # is NOT a working school site. Confirmed directly on
                # liceum-technikum.roe.pl: its nav links out to its
                # e-register six times, which outnumbered its own-domain
                # links, so the crawl declared the school migrated to
                # librus.pl and went crawling a software vendor -- while
                # _verify_school_site(html) on the original page returned
                # True the whole time. The cost is not just five wasted
                # fetches: every address harvested over there is a vendor's,
                # and three schools in stored data ended up with
                # "sekretariat@librus.pl" as their office mailbox. A live,
                # verified school site is never abandoned on link counts
                # alone.
                if migrated_domain and _verify_school_site(html):
                    sources_checked.append(
                        {
                            "url": f"https://{migrated_domain}",
                            "status": "skipped",
                            "domain_migration": False,
                            "reason": "base site verifies as a school site",
                        }
                    )
                    migrated_domain = None
                if migrated_domain:
                    migrated_url = f"https://{migrated_domain}"
                    migrated_html = fetch_page(migrated_url)
                    pages_fetched += 1
                    if migrated_html and _verify_school_site(migrated_html):
                        sources_checked.append({"url": migrated_url, "status": "ok", "domain_migration": True})
                        homepage = _normalize_url(migrated_url)
                        effective_homepage = homepage
                        visited = {_dedup_key(homepage)}
                        html = migrated_html
                        result["discovered_website_url"] = migrated_url
                    else:
                        sources_checked.append(
                            {"url": migrated_url, "status": _fetch_failure_status(migrated_url), "domain_migration": True}
                        )
        elif not wrong_site:
            sources_checked.append({"url": homepage, "status": _fetch_failure_status(homepage)})
            # NOTE: deliberately NOT gated on `_dedup_key(variant) not in
            # visited` -- _dedup_key() treats www/non-www as the same page
            # (so the crawl doesn't re-fetch a page it already HAS), but
            # here the homepage fetch just failed outright, so nothing
            # was actually retrieved under that key yet. This is a single,
            # bounded retry, not part of the general "already seen" check.
            for variant in _hostname_fallback_variants(homepage):
                if variant == homepage or pages_fetched >= MAX_SAME_SITE_PAGES:
                    continue
                variant_html = fetch_page(variant)
                pages_fetched += 1
                # BUG FIX: a fallback hostname resolving at all doesn't
                # mean it's this school's site -- confirmed directly:
                # radzanow.edu.pl (the www-stripped fallback for a school
                # whose "www." address had lapsed) resolves to a HOSTING
                # PROVIDER'S OWN domain-parking page ("home.pl: Nr 1 w
                # Polsce. Domeny, Hosting...", served identically for
                # every path, including the guessed "/dyrekcja" and
                # "/kadra" slugs) -- a registration that expired outright,
                # not a real site under a different address. The main
                # homepage fetch already runs _verify_school_site before
                # being trusted; this fallback variant skipped that same
                # check entirely, on a guess that's if anything MORE
                # likely to land somewhere unrelated than the original.
                if variant_html and not _verify_school_site(variant_html):
                    sources_checked.append(
                        {"url": variant, "status": "not_a_school_site", "hostname_fallback": True}
                    )
                    continue
                if variant_html:
                    sources_checked.append({"url": variant, "status": "ok", "hostname_fallback": True})
                    html = variant_html
                    effective_homepage = variant
                    visited.add(_dedup_key(effective_homepage))
                    break
                sources_checked.append({"url": variant, "status": _fetch_failure_status(variant), "hostname_fallback": True})
        # else: wrong_site with no better candidate found -- already fully
        # recorded above (not_a_school_site + the failed candidate attempt,
        # if any).

        # A plain fetch that failed here is very often NOT a dead site -- a
        # transient blip in a batch, an anti-bot 403 that blocks our
        # requests UA, or a redirect quirk. Confirmed directly: 33 of 37
        # "unreachable" school sites returned HTTP 200 on a later recheck.
        # The headless-browser fallback (a real Chrome) is retried on these
        # below, exactly as for a JS shell.
        #
        # BUG FIX: that retry must NEVER fire for a CONFIRMED wrong site
        # (wrong_site True, no replacement candidate found) -- confirmed
        # directly: without this guard, `effective_homepage` still pointed
        # at the known-wrong site (an ad agency's own homepage, in one
        # real case), so the "unreachable, try a real browser" fallback
        # below re-rendered and re-extracted from that SAME wrong site
        # right after it had just been correctly rejected, defeating the
        # whole point of the check above.
        homepage_confirmed_wrong = wrong_site and html is None
        homepage_unreachable = html is None and not homepage_confirmed_wrong

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
                # not necessarily this specific school's. Only the
                # dedicated subsite (if found via the frontier below) may
                # contribute data; the hub page itself never does (see
                # the accuracy-policy note where hub_fallback_found was
                # previously merged).
                hub_fallback_found = found  # kept for the subsite search only
                frontier.extend(found["subpage_links"])
            else:
                _merge(result, found, tier=HOMEPAGE_TIER)
                _note_cloak(found)
                frontier.extend(found["subpage_links"])
                # LLM NAV-PICKER. Keyword tiering can only find a roster
                # whose label or slug happens to contain a word someone
                # listed. When it finds no staff-roster candidate at all,
                # ask the model to read the nav instead -- see
                # llm_extract.pick_staff_pages for the failure shapes this
                # covers (image-only navs, English-only labels, "?id=42"
                # permalinks, a roster on the school's own other
                # subdomain). Gated on tiering having come up empty, so the
                # majority of schools -- where a "Kadra" link exists and
                # matches -- pay nothing for it.
                picked: list[str] = []
                if staff_page_picker is not None and not _staff_page_pending(
                    found["subpage_links"], visited
                ):
                    picked = _picked_staff_links(
                        staff_page_picker, html, effective_homepage, school_name, city
                    )
                    for url in picked:
                        if _dedup_key(url) not in visited:
                            # Tier 0: a model that has read the whole nav
                            # and named this page is a stronger signal than
                            # any keyword match, and there is by definition
                            # no real staff-tier link competing for the
                            # budget here.
                            frontier.append((0, url))
                    if picked:
                        sources_checked.append(
                            {"url": effective_homepage, "status": "ok", "llm_nav_picked": picked}
                        )
                # Blind slug guessing is the last resort, so it is skipped
                # when the picker just supplied real, model-chosen targets.
                if not found["subpage_links"] and not picked:
                    base = effective_homepage.rstrip("/")
                    frontier.extend(
                        (0, f"{base}/{slug}") for slug in _level_hub_slugs_for(school_name)
                    )
                    # A blind guess must never outrank a genuinely
                    # discovered link -- confirmed directly: queuing these
                    # at the same tier as real "kadra"/"dyrektor" matches
                    # meant that once a guessed hub slug (e.g. /liceum)
                    # landed and surfaced ITS OWN real, same-tier "Kadra"
                    # link, the earlier-queued root-level guesses (tied on
                    # tier, so ordered first by insertion) got visited
                    # first and burned the whole crawl budget before the
                    # real link was ever reached. _GUESS_TIER sits below
                    # every real keyword tier so any genuine match always
                    # wins ties, no matter when it's discovered.
                    frontier.extend((_GUESS_TIER, f"{base}/{slug}") for slug in COMMON_PROBE_SLUGS)

            # Cross-domain chooser-hub check -- independent of the
            # tier/label system above, so it's worth trying regardless of
            # whether is_hub_page's own (same-registrable-domain-only)
            # detection found anything. Verified by the destination's own
            # content before being trusted, so it's safe even when the
            # label-based checks above found nothing at all to go on.
            for candidate in _find_hub_candidates(BeautifulSoup(html, "html.parser"), effective_homepage):
                if pages_fetched >= MAX_SAME_SITE_PAGES:
                    break
                time.sleep(REQUEST_DELAY_SECONDS)
                candidate_html = fetch_page(candidate)
                pages_fetched += 1
                if (
                    candidate_html
                    and _page_matches_school(candidate_html, school_name)
                    and _mentions_school_city(school_name, candidate_html, candidate)
                ):
                    sources_checked.append({"url": candidate, "status": "ok", "hub_candidate_matched": True})
                    own_school_subsite_url = candidate
                    visited.add(_dedup_key(candidate))
                    candidate_found = _extract(candidate_html, candidate, school_name)
                    _merge(result, candidate_found, tier=HOMEPAGE_TIER)  # a subsite's own homepage
                    _note_cloak(candidate_found)
                    frontier.extend(
                        pair for pair in candidate_found["subpage_links"] if _dedup_key(pair[1]) not in visited
                    )
                    break
                sources_checked.append(
                    {
                        "url": candidate,
                        "status": "ok" if candidate_html else "unreachable",
                        "hub_candidate_no_match": True,
                    }
                )

        while (
            frontier
            and pages_fetched < MAX_SAME_SITE_PAGES
            and not _is_complete(result, staff_page_pending=_staff_page_pending(frontier, visited))
        ):
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
                _merge(result, found, tier=tier)
                _note_cloak(found)
                if (
                    tier == -1
                    and own_school_subsite_url is None
                    and not _same_organization_host(link, effective_homepage)
                    and _mentions_school_city(school_name, sub_html, link)
                ):
                    # A genuine sibling-school link on a shared-domain hub
                    # lives on its OWN subdomain (sp.foo.pl vs. foo.pl) --
                    # requiring a different host here is what tells that
                    # apart from a same-host page that merely happens to
                    # share a level-word with the school's own name (e.g.
                    # a "kursy maturalne" fee page mentioning "matematyka
                    # podstawowa", which isn't this school's own site at
                    # all despite matching the same tier). The city check
                    # (_mentions_school_city) is what tells this school's
                    # OWN subsite apart from a SIBLING BRANCH of the same
                    # chain in another city (the TEB Rzeszów/Świdnica
                    # failure) -- adopting that poisons every future run.
                    own_school_subsite_url = link
                    # The dedicated subsite is strictly better ground than
                    # the complex's shared pages -- drop every queued link
                    # on another host so the remaining page budget is spent
                    # here. Confirmed directly: without this, two stale
                    # /szkola-podstawowa/* pages on the hub host were
                    # fetched ahead of the subsite's own /kadra/ (the page
                    # with the personal emails), which never got reached.
                    frontier[:] = [pair for pair in frontier if _same_organization_host(pair[1], link)]
                frontier.extend(pair for pair in found["subpage_links"] if _dedup_key(pair[1]) not in visited)
            else:
                sources_checked.append({"url": link, "status": _fetch_failure_status(link)})

        # Never found the school's own dedicated subsite. The hub page is
        # NOT used as a data source anymore (accuracy policy): a shared
        # hub describes the umbrella organization or a SIBLING school, so
        # "the first Dyrektor named on it" is routinely someone else's
        # director, and even a personal-looking email on it can belong to
        # a same-named person at another school in the group. Without a
        # confirmed own-subsite, this school contributes nothing from the
        # hub -- blank beats a neighbor's contact. (The hub's URL still
        # appears in sources_checked above, so the attempt is visible.)

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

    # A confirmed identical-content SPA (js_app_shell via the cross-page
    # fingerprint check in _merge) can still end up with several llm_pages
    # entries carrying the SAME text under different URLs even after the
    # browser fallback -- some client-side routers only react to an
    # in-app link click, never to a direct page load of the target URL,
    # so re-rendering each URL independently just reproduces the same
    # shell every time. Collapsing to one representative page here costs
    # nothing (the content is provably identical) and frees up the
    # school-level page/char budget (llm_extract.cap_pages) for whatever
    # distinct content, if any, was also found.
    if result["llm_pages"]:
        deduped_pages = []
        seen_text_hashes: set[str] = set()
        for page in result["llm_pages"]:
            text_hash = hashlib.md5(page["text"].encode("utf-8", errors="ignore")).hexdigest()
            if text_hash in seen_text_hashes:
                continue
            seen_text_hashes.add(text_hash)
            deduped_pages.append(page)
        result["llm_pages"] = deduped_pages

    result["sources_checked"] = sources_checked
    return result


def augment_with_web_search(school_name: str, city: str | None, result: dict, rspo_id: str | None = None) -> None:
    """Web search fallback -- deliberately a SEPARATE call, not a step
    inside scrape_school_website itself. Only ever invoked by jobs.py, and
    only once RSPO's own registry plus the full website crawl above still
    leave the school short of what counts as meaningfully enriched (see
    jobs.py's _would_be_enriched) -- a genuine last resort, not something
    that runs for every school by default. Mutates `result` in place,
    appending to the SAME sources_checked list the crawl already built, so
    a school whose own site already had everything never causes a single
    search request.

    The name-based query below is deliberately NOT the official RSPO name
    wrapped in exact-match quotes -- confirmed directly against several
    real schools: for "SZKOŁA PODSTAWOWA W GRĄDACH" and "SZKOŁA
    PODSTAWOWA IM. MACIEJA PŁAŻYŃSKIEGO W LIGOCIE WIELKIEJ", dropping the
    quotes surfaced each school's own real "Dyrekcja" page immediately,
    while the quoted version found nothing at all for one of them. A real
    page about a school very often phrases its name slightly differently
    than RSPO's full official form (a shorter/abbreviated name, no "im.
    <patron>", different word order) -- an exact-phrase requirement rules
    those pages out even though they're exactly what this search is for.

    The RSPO-id query is a DIFFERENT, complementary strategy -- suggested
    directly by the user, who'd had real success with it by hand on
    schools this same name-based search came up empty for. Confirmed
    directly: several third-party school directories (dzieci-edu.pl,
    szkolapodstawowa.edu.pl, dostepnemiejsce.pl, waszaedukacja.pl) key
    their own per-institution profile pages by the bare RSPO id, either
    literally in the URL or in the page's own visible text -- a precise,
    near-unique search term a fuzzy name match can miss entirely when a
    school's real site phrases its own name very differently from RSPO's
    formal register. Tried once, first, since it's aimed at finding A
    USABLE PAGE at all rather than one specific fact -- whatever it
    surfaces still goes through the same _extract() as every other search
    result, so it's harmless when the only hit is just another mirror of
    RSPO's own already-known fields."""
    sources_checked: list[dict] = result.setdefault("sources_checked", [])
    queries = []
    if rspo_id:
        queries.append(f"RSPO {rspo_id}")
    location = f" {city}" if city else ""
    if not result["director_name"]:
        queries.append(f"{school_name}{location} dyrektor szkoły")
    if not result["english_teacher_name"]:
        queries.append(f"{school_name}{location} nauczyciel angielskiego")

    for query in queries:
        if _is_complete(result):
            break
        time.sleep(REQUEST_DELAY_SECONDS)
        links = _search_web(query)
        if links is None:
            # Distinct from "search_returned_no_results" -- this means the
            # search engine itself served an anti-bot challenge page, not
            # that it genuinely has nothing on this school. Once this
            # happens, every remaining query in this SAME process would
            # hit the identical wall (see _search_blocked), so stop trying
            # more queries for THIS school rather than waste further
            # requests against a wall that isn't coming down mid-run.
            sources_checked.append({"query": query, "status": "search_blocked"})
            break
        if not links:
            # Visible even when the search itself came back genuinely
            # empty -- "we searched and found nothing" is a different,
            # honest outcome from "we never tried", and both must show up
            # in sources_checked.
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
                _merge(result, _extract(html, link), third_party=True)
            else:
                sources_checked.append({"url": link, "status": _fetch_failure_status(link), "found_via_search": query})


def finalize_scrape_result(result: dict) -> dict:
    """Call exactly once, after scrape_school_website and (if it ran)
    augment_with_web_search have both had their turn -- turns the working
    all_emails/specialties sets into the stable sorted lists the rest of
    the app expects. Kept separate from scrape_school_website itself so
    jobs.py can insert the web-search step in between without the set
    already having been flattened to a list out from under it."""
    result["all_emails"] = sorted(result["all_emails"])
    result["specialties"] = sorted(result["specialties"])
    return result
