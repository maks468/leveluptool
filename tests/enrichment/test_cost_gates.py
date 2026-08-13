"""The cost-reduction gates must be LOSSLESS: they may only skip work that
provably could not have produced a writeable contact. These tests pin that
property, so a future "optimization" can't quietly start dropping pages
that could have yielded a real name.
"""

from levelup.services.enrichment.llm_extract import (
    PreparedPage,
    SchoolExtraction,
    StaffRecord,
    needs_escalation,
    pages_that_could_prove,
)

ROLES = ("director", "english_teacher")


def _page(url, text, tier=1):
    return PreparedPage(url=url, text=text, tier=tier)


def test_pages_naming_a_role_are_kept():
    pages = [
        _page("https://s.pl/dyrekcja", "Dyrektor szkoły: mgr Jan Nowak"),
        _page("https://s.pl/kadra", "mgr Anna Kowalska - język angielski"),
        _page("https://s.pl/anglo", "Our English teacher is Ms Smith"),
        _page("https://s.pl/anglista", "anglista: mgr Piotr Lis"),
    ]
    assert pages_that_could_prove(pages, ROLES) == pages


def test_pages_that_cannot_prove_any_writeable_role_are_dropped():
    """A gallery/news page with no role vocabulary cannot ground a record --
    grounding requires the role's own words inside the evidence span."""
    useless = [
        _page("https://s.pl/galeria", "Zdjęcia z wycieczki do Krakowa. Rok szkolny 2025/2026."),
        _page("https://s.pl/plan", "Poniedziałek 8:00 matematyka, 9:00 historia, 10:00 biologia"),
    ]
    assert pages_that_could_prove(useless, ROLES) == []


def test_declined_polish_forms_still_count_as_provable():
    """Genitive/inflected forms must not be mistaken for "no vocabulary" --
    the same substring stems grounding uses are used here."""
    pages = [
        _page("https://s.pl/bip", "Zarządzenie Dyrektora Szkoły nr 12/2024"),
        _page("https://s.pl/przedmioty", "nauczyciele języka angielskiego w naszej szkole"),
    ]
    assert pages_that_could_prove(pages, ROLES) == pages


def test_a_page_only_holding_an_email_is_droppable():
    """Cross-page pairing was never possible: a record's name, role quote
    and email_evidence must all ground against the ONE page it cites."""
    pages = [_page("https://s.pl/kontakt-only", "sekretariat@s.pl, tel. 123456789")]
    assert pages_that_could_prove(pages, ROLES) == []


def test_no_escalation_when_the_bundle_cannot_prove_the_missing_role():
    """The expensive second opinion is pointless if the evidence isn't in
    the bundle -- this is where most of the wasted Opus calls came from."""
    extraction = SchoolExtraction(staff=[])
    pages = [_page("https://s.pl/galeria", "Zdjęcia z wycieczki", tier=1)]
    assert not needs_escalation(extraction, pages, {"english_teacher"})


def test_no_escalation_when_nothing_is_still_needed():
    extraction = SchoolExtraction(staff=[])
    pages = [_page("https://s.pl/kadra", "język angielski: mgr Anna Kowalska")]
    assert not needs_escalation(extraction, pages, set())


def test_homepage_alone_does_not_count_as_a_staff_bearing_page():
    """scraper.HOMEPAGE_TIER (3) must not satisfy the staff-page test the
    way the old default tier 0 did for every school."""
    from levelup.services.enrichment.scraper import HOMEPAGE_TIER

    extraction = SchoolExtraction(staff=[])
    homepage_only = [_page("https://s.pl/", "Witamy. Dyrektor zaprasza.", tier=HOMEPAGE_TIER)]
    assert not needs_escalation(extraction, homepage_only, {"director"})


def test_escalation_still_fires_when_it_could_actually_help():
    """A real staff page that names the role, yet the routine call grounded
    nothing for it -- the one case worth paying Opus for."""
    extraction = SchoolExtraction(staff=[])
    pages = [_page("https://s.pl/kadra", "Grono pedagogiczne: język angielski ...", tier=1)]
    assert needs_escalation(extraction, pages, {"english_teacher"})


def test_escalation_fires_when_the_only_record_is_low_confidence():
    extraction = SchoolExtraction(
        staff=[
            StaffRecord(
                name="Anna Kowalska",
                role="english_teacher",
                evidence="Anna Kowalska - język angielski",
                source_url="https://s.pl/kadra",
                confidence="low",
            )
        ]
    )
    pages = [_page("https://s.pl/kadra", "Anna Kowalska - język angielski", tier=1)]
    assert needs_escalation(extraction, pages, {"english_teacher"})
