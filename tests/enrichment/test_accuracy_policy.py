"""Regression tests for the accuracy policy: a contact is written only when
the cited page LITERALLY proves it (owner requirement: never guess, never
substitute -- blank beats wrong). Each test pins one of the policy's
grounding guarantees in ground_extraction; the write-path guarantees
(deputy never in the director slot, regex never written, replace-don't-
append) live in jobs.py and are covered by the checks below only insofar
as grounding feeds them -- see also test_fixture_pipeline.py.
"""

from levelup.services.enrichment.llm_extract import (
    SchoolExtraction,
    StaffRecord,
    ground_extraction,
)

PAGE = "https://szkola.example.pl/kadra"

STAFF_PAGE_TEXT = """Kadra pedagogiczna
mgr Jan Nowak | Dyrektor szkoły
mgr Anna Kowalska | język angielski
mgr Piotr Zieliński | matematyka
Wicedyrektor: mgr Maria Wiśniewska
Sekretariat: sekretariat@szkola.example.pl
"""


def _ground(records, pages=None, third_party=frozenset()):
    extraction = SchoolExtraction(staff=records)
    return ground_extraction(
        extraction, pages or {PAGE: STAFF_PAGE_TEXT}, school_name="Szkoła Podstawowa w Przykładowie",
        third_party_urls=third_party,
    )


def test_any_name_plus_any_role_no_longer_passes():
    """THE core bug: name-somewhere + quote-somewhere let any person on a
    staff page be paired with any role. The evidence quote must now be
    ABOUT the named person."""
    result = _ground([
        StaffRecord(
            name="Piotr Zieliński",  # real person on the page...
            role="english_teacher",  # ...but the quote names someone else's row
            evidence="mgr Anna Kowalska | język angielski",
            source_url=PAGE,
            confidence="high",
        )
    ])
    assert result.staff == []


def test_evidence_must_state_the_claimed_role():
    result = _ground([
        StaffRecord(
            name="Piotr Zieliński",
            role="english_teacher",
            evidence="mgr Piotr Zieliński | matematyka",  # his real row -- but no English in it
            source_url=PAGE,
            confidence="high",
        )
    ])
    assert result.staff == []


def test_correctly_bound_records_survive():
    result = _ground([
        StaffRecord(
            name="Jan Nowak",
            role="director",
            evidence="mgr Jan Nowak | Dyrektor szkoły",
            source_url=PAGE,
            confidence="high",
        ),
        StaffRecord(
            name="Anna Kowalska",
            role="english_teacher",
            evidence="mgr Anna Kowalska | język angielski",
            source_url=PAGE,
            confidence="high",
        ),
    ])
    assert {r.name for r in result.staff} == {"Jan Nowak", "Anna Kowalska"}


def test_deputy_evidence_cannot_prove_director():
    """"Wicedyrektor: X" contains the substring "dyrektor" but proves the
    OPPOSITE of role="director"."""
    result = _ground([
        StaffRecord(
            name="Maria Wiśniewska",
            role="director",
            evidence="Wicedyrektor: mgr Maria Wiśniewska",
            source_url=PAGE,
            confidence="high",
        )
    ])
    assert result.staff == []


def test_deputy_correctly_labeled_as_deputy_survives():
    result = _ground([
        StaffRecord(
            name="Maria Wiśniewska",
            role="deputy_director",
            evidence="Wicedyrektor: mgr Maria Wiśniewska",
            source_url=PAGE,
            confidence="high",
        )
    ])
    assert [r.role for r in result.staff] == ["deputy_director"]


def test_third_party_pages_never_originate_staff():
    third_party_url = "https://katalog-szkol.example.com/wyniki"
    pages = {
        PAGE: STAFF_PAGE_TEXT,
        third_party_url: "Dyrektor szkoły: mgr Adam Obcy -- katalog szkół",
    }
    result = _ground(
        [
            StaffRecord(
                name="Adam Obcy",
                role="director",
                evidence="Dyrektor szkoły: mgr Adam Obcy",
                source_url=third_party_url,
                confidence="high",
            )
        ],
        pages=pages,
        third_party=frozenset({third_party_url}),
    )
    assert result.staff == []


def test_fabricated_email_evidence_is_demoted_even_when_email_is_on_page():
    """The pairing quote itself must be verbatim page text -- a fabricated
    "Surname: email" quote must not attach the office mailbox to a person."""
    result = _ground([
        StaffRecord(
            name="Anna Kowalska",
            role="english_teacher",
            email="sekretariat@szkola.example.pl",  # real address, on the page
            email_evidence="Anna Kowalska: sekretariat@szkola.example.pl",  # nowhere on the page
            evidence="mgr Anna Kowalska | język angielski",
            source_url=PAGE,
            confidence="high",
        )
    ])
    assert len(result.staff) == 1
    assert result.staff[0].email is None
    assert "sekretariat@szkola.example.pl" in result.unattributed_emails
