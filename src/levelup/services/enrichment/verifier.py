import re

_DIACRITIC_MAP = str.maketrans("ąćęłńóśźżĄĆĘŁŃÓŚŹŻ", "acelnoszzACELNOSZZ")


def _strip_diacritics(s: str) -> str:
    return s.translate(_DIACRITIC_MAP).lower()


def is_personal_email_for(email: str | None, person_name: str | None) -> bool:
    """Positive structural proof that an email belongs to THIS specific
    person -- e.g. "anna.wojda@szkola.pl" or "a.wojda@szkola.pl" for
    "Anna Wojda". Deliberately NOT a denylist ("personal unless it matches
    a known-generic word") -- a blocklist can never cover every
    institutional mailbox (confirmed directly: "atut@fem.org.pl" for a
    school literally named "ATUT" isn't on any generic-word list, so a
    blocklist-only check wrongly treated it as personal and attached it to
    the director). Requires the local-part to split into 2+ name-shaped
    tokens where one matches the person's first name (or its initial) and
    a DIFFERENT one matches their surname -- a single unseparated word
    can't be verified this way and is never called personal, even if it
    happens to contain the right letters."""
    if not email or not person_name:
        return False
    local = email.split("@", 1)[0]
    tokens = [t for t in re.split(r"[._-]", local) if t]
    if len(tokens) < 2:
        return False

    name_words = [w for w in re.split(r"[\s-]+", person_name) if w]
    if len(name_words) < 2:
        return False
    first_name = _strip_diacritics(name_words[0])
    last_name = _strip_diacritics(name_words[-1])
    norm_tokens = [_strip_diacritics(t) for t in tokens]

    def matches(token: str, name: str) -> bool:
        return token == name or (len(token) == 1 and name.startswith(token))

    for i, tok_a in enumerate(norm_tokens):
        for j, tok_b in enumerate(norm_tokens):
            if i == j:
                continue
            if matches(tok_a, first_name) and matches(tok_b, last_name):
                return True
    return False


def classify_contact_quality(person_name: str | None, email: str | None) -> str:
    """Three-tier outcome for a single contact-finding attempt:
    - "failed": no named person found -- an unnamed office mailbox isn't
      a contact, even if an email address was captured elsewhere
    - "partial": a named person was found, but no email STRUCTURALLY
      PROVEN to be their own
    - "verified": a named person AND an email whose shape matches that
      exact person (is_personal_email_for)

    "verified" re-checks the pairing itself instead of trusting the
    caller: the old trust-the-caller contract was violated in production
    (TEB Rzeszów -- one person's name written with another person's email,
    stamped "verified"). A label users read as "this was checked" must be
    backed by a check HERE. An LLM-paired email that is real but not
    name-shaped (e.g. dyrektor@szkola.pl proven by a page quote) therefore
    caps at "partial" -- acceptable: "verified" is reserved for the
    strongest, independently re-checkable proof."""
    if person_name and email and is_personal_email_for(email, person_name):
        return "verified"
    if person_name:
        return "partial"
    return "failed"


# A school's own general/office mailbox is still worth recording -- just
# never attached to a specific person unless it's personal-verified for
# them. Used to pick the single best "general" address to keep when
# several non-personal candidates were found on the site (prefer a real
# office/reception line over a recruitment-only one).
GENERIC_OFFICE_LOCAL_PARTS = frozenset(
    {
        "info",
        "kontakt",
        "biuro",
        "sekretariat",
        "dyrekcja",
        "office",
        "contact",
        "szkola",
        "poczta",
        "administracja",
        # A group-level admin mailbox (confirmed directly:
        # "administrator@e-teb.pl" reused as the "contact" for four TEB
        # schools). Office-tier, so a school-specific address always wins.
        "administrator",
    }
)
LAST_RESORT_LOCAL_PARTS = frozenset(
    {
        "rekrutacja",
        "rekrutacje",
        "nabor",
        "przyjecia",
        "zapisy",
    }
)

# The RODO/GDPR data-protection channel -- almost never the right outreach
# contact. It reaches the Inspektor Ochrony Danych (very often an EXTERNAL
# compliance firm, confirmed directly: "inspektor@coreconsulting.pl" on a
# Wrocław special school), strictly for data-protection requests, never the
# secretariat or a teacher. A plain info@/sekretariat@ is always a better
# contact, so these rank below even recruitment -- and jobs.py drops them
# from contact attribution entirely (blank beats a misleading contact).
# Matched on the separator-stripped local part so "dane.osobowe" and
# "iod-sp1" are caught too.
DATA_PROTECTION_LOCAL_PARTS = (
    "iod",
    "inspektor",
    "rodo",
    "abi",
    "dpo",
    "gdpr",
    "daneosobowe",
    "ochronadanych",
    "administratordanych",
)


def is_data_protection_email(email: str | None) -> bool:
    if not email:
        return False
    local_norm = re.sub(r"[._+-]", "", email.split("@")[0].lower())
    return any(local_norm == p or local_norm.startswith(p) for p in DATA_PROTECTION_LOCAL_PARTS)


# Known third-party compliance / IT / legal firms schools outsource RODO or
# admin to. Their address reaches the VENDOR, never the school -- and the
# same one recurs across many unrelated schools (confirmed directly:
# "madamaszek@zontekiwspolnicy.pl" was the scraped "contact" for four
# unrelated Wrocław primary schools; "inspektor@coreconsulting.pl" for a
# dozen more). A local-part denylist can't catch these (the local part is a
# person's name), so they're matched by domain. Curated and extensible --
# these recur, so each one added fixes many schools at once.
THIRD_PARTY_VENDOR_DOMAINS = (
    "coreconsulting.pl",
    "adametronics.pl",
    "perfectinfo.pl",
    "zontekiwspolnicy.pl",
)


def is_third_party_vendor_email(email: str | None) -> bool:
    if not email or "@" not in email:
        return False
    domain = email.rsplit("@", 1)[1].lower().strip().rstrip(".")
    return any(domain == v or domain.endswith("." + v) for v in THIRD_PARTY_VENDOR_DOMAINS)


def is_non_school_email(email: str | None) -> bool:
    """An address that reaches something OTHER than the school itself -- its
    data-protection officer or an outsourced compliance/IT/legal vendor. Such
    an address is never attached to a person or kept as the school's contact;
    a blank beats a misleading one."""
    return is_data_protection_email(email) or is_third_party_vendor_email(email)


def email_priority(email: str) -> int:
    """Ranks non-personal candidates only -- 0 = an unrecognized/other
    address, 1 = a known shared office mailbox, 2 = recruitment/admissions
    (real, but meant for prospective students, not for reaching staff),
    3 = a RODO/data-protection mailbox (worst -- see
    DATA_PROTECTION_LOCAL_PARTS). Lower is better. This is NOT a
    personal-vs-generic decision by itself -- see is_personal_email_for for
    that; this only orders the leftover candidates once none of them
    qualify as personal."""
    local = email.split("@")[0].lower()
    if is_non_school_email(email):
        return 3
    if any(local == p or local.startswith(p) for p in LAST_RESORT_LOCAL_PARTS):
        return 2
    if any(local == p or local.startswith(p) for p in GENERIC_OFFICE_LOCAL_PARTS):
        return 1
    return 0


def campaign_email_tier(email: str | None) -> int:
    """How well a NON-personal address serves as the target of an outreach
    email campaign (lower = better):
      0 = a monitored office/secretariat inbox -- the canonical place
          external mail to a school actually lands and gets routed;
      1 = some other/unlabelled address (could be a department, could be
          anything -- less certain to be read);
      2 = recruitment-only (meant for prospective students, not staff);
      3 = a non-school address (RODO/vendor) -- never.
    This is the campaign-facing counterpart to email_priority(): that ranks
    "how likely personal" (an unlabelled address might be someone's own box,
    so it scores it BEST); for a bulk campaign the opposite is true -- the
    secretariat is the surest general target, so office outranks an
    unlabelled address here. Personal addresses are matched separately
    (is_personal_email_for) and always preferred over any of these."""
    if not email:
        return 3
    if is_non_school_email(email):
        return 3
    local = email.split("@")[0].lower()
    if any(local == p or local.startswith(p) for p in LAST_RESORT_LOCAL_PARTS):
        return 2
    if any(local == p or local.startswith(p) for p in GENERIC_OFFICE_LOCAL_PARTS):
        return 0
    return 1


# A short section-abbreviation mailbox implies which school it belongs to:
# "sp@smsw.pl" is the PRIMARY school's box, "lo@..." the liceum's,
# "technikum@..." the technikum's. This matters only on a SHARED domain
# hosting several schools of a sports/complex group -- without it, the
# liceum's enrichment grabs the primary school's "sp@" address (confirmed
# directly: LO Mistrzostwa Sportowego got "sp@smsw.pl" instead of the
# correct "sekretariat@smsw.pl"). Each pattern is anchored to the WHOLE
# local part, so a surname like "spiewak"/"lolek" is never mistaken for a
# section code. Returns a level key aligned with SchoolLevel values, or
# None when no level is implied (an ordinary office/personal address).
_EMAIL_LEVEL_HINTS = (
    ("primary", re.compile(r"^p?sp[-_]?\d*$")),
    ("liceum", re.compile(r"^(x?lo|liceum)[-_]?\d*$")),
    ("technikum", re.compile(r"^(technikum|tech)[-_]?\d*$")),
)


def email_level_hint(email: str | None) -> str | None:
    if not email:
        return None
    local = email.split("@")[0].lower()
    for level, pattern in _EMAIL_LEVEL_HINTS:
        if pattern.match(local):
            return level
    return None
