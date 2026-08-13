"""Anti-hallucination gate tests for llm_extract.ground_extraction/
ground_vision_extraction -- all offline, faked SchoolExtraction outputs,
no real SDK/CLI calls. This is the code-level safety net the task
requires regardless of how good the system prompt is: a model that
ignores its own instructions must still get caught here."""

from levelup.services.enrichment.llm_extract import (
    SchoolExtraction,
    StaffRecord,
    ground_extraction,
    ground_vision_extraction,
)

PAGE_URL = "https://real.pl/kadra"
PAGES = {
    PAGE_URL: (
        "Dyrektor: Jan Kowalski. Kontakt: jan.kowalski@real.pl. "
        "Wicedyrektor Nowak Maria (surname-first). "
        # Present so the patron test below can be about the PATRON gate
        # rather than being vacuously dropped by an earlier check.
        "Dyrektor Maria Sklodowska-Curie (patron w tresci strony)."
    ),
}
SCHOOL_NAME = "Szkola Podstawowa im. Marii Sklodowskiej-Curie"


def _record(**overrides) -> StaffRecord:
    base = dict(
        name="Jan Kowalski",
        role="director",
        evidence="Dyrektor: Jan Kowalski",
        source_url=PAGE_URL,
        confidence="high",
    )
    base.update(overrides)
    return StaffRecord(**base)


def test_hallucinated_name_is_dropped():
    extraction = SchoolExtraction(staff=[_record(name="Zbigniew Fikcyjny", evidence="fake")])
    result = ground_extraction(extraction, PAGES, school_name=SCHOOL_NAME)
    assert result.staff == []


def test_email_demoted_when_evidence_does_not_tie_name_and_email_together():
    extraction = SchoolExtraction(
        staff=[
            _record(
                email="jan.kowalski@real.pl",
                email_evidence="some unrelated text that mentions neither together",
            )
        ]
    )
    result = ground_extraction(extraction, PAGES, school_name=SCHOOL_NAME)
    assert len(result.staff) == 1
    assert result.staff[0].name == "Jan Kowalski"
    assert result.staff[0].email is None
    assert "jan.kowalski@real.pl" in result.unattributed_emails


def test_wrong_source_url_is_dropped():
    extraction = SchoolExtraction(
        staff=[_record(name="Ktos Inny", evidence="x", source_url="https://not-given.pl/page")]
    )
    result = ground_extraction(extraction, PAGES, school_name=SCHOOL_NAME)
    assert result.staff == []


def test_patron_name_is_rejected():
    """Uses a writeable role AND a real role-proving quote, so the record
    reaches (and must be stopped by) the patron gate itself -- with a
    non-target role it would be dropped earlier and prove nothing."""
    extraction = SchoolExtraction(
        staff=[
            _record(
                name="Maria Sklodowska-Curie",
                evidence="Dyrektor Maria Sklodowska-Curie",
            )
        ]
    )
    result = ground_extraction(extraction, PAGES, school_name=SCHOOL_NAME)
    assert result.staff == []


def test_non_writeable_roles_are_dropped():
    """other_teacher/other_staff are accepted by the schema (so one stray
    record can't void an entire extraction) but nothing downstream can
    write them, so grounding discards them."""
    extraction = SchoolExtraction(
        staff=[_record(role="other_teacher"), _record(role="other_staff")]
    )
    result = ground_extraction(extraction, PAGES, school_name=SCHOOL_NAME)
    assert result.staff == []


def test_last_first_reversal_is_accepted():
    extraction = SchoolExtraction(
        staff=[
            _record(
                name="Maria Nowak",
                role="deputy_director",
                evidence="Wicedyrektor Nowak Maria",
            )
        ]
    )
    result = ground_extraction(extraction, PAGES, school_name=SCHOOL_NAME)
    assert len(result.staff) == 1
    assert result.staff[0].name == "Maria Nowak"


def test_fabricated_evidence_is_dropped_even_for_a_real_name():
    """A name that's genuinely on the page doesn't save a record whose
    quoted "evidence" isn't actually there -- catches a model that names
    a real person but invents plausible-sounding supporting text."""
    extraction = SchoolExtraction(
        staff=[_record(evidence="Pan Kowalski pelni funkcje dyrektora od 2015 roku")]
    )
    result = ground_extraction(extraction, PAGES, school_name=SCHOOL_NAME)
    assert result.staff == []


def test_email_not_on_page_is_stripped_not_trusted():
    extraction = SchoolExtraction(
        staff=[
            _record(
                email="fake@notreal.pl",
                email_evidence="Jan Kowalski fake@notreal.pl",
            )
        ]
    )
    result = ground_extraction(extraction, PAGES, school_name=SCHOOL_NAME)
    assert len(result.staff) == 1
    assert result.staff[0].email is None
    assert "fake@notreal.pl" in result.unattributed_emails


def test_empty_staff_list_survives_unchanged():
    extraction = SchoolExtraction(staff=[], unattributed_emails=["a@b.pl"])
    result = ground_extraction(extraction, PAGES, school_name=SCHOOL_NAME)
    assert result.staff == []
    assert result.unattributed_emails == ["a@b.pl"]


def test_vision_drops_records_with_empty_evidence():
    extraction = SchoolExtraction(
        staff=[
            StaffRecord(
                name="Jan Kowalski", role="director", evidence="   ", source_url="img://roster.jpg", confidence="high"
            )
        ]
    )
    result = ground_vision_extraction(extraction, school_website_domain="real.pl")
    assert result.staff == []


def test_vision_caps_confidence_unless_email_domain_matches_school():
    off_domain = StaffRecord(
        name="Jan Kowalski",
        role="director",
        email="jan@othersite.pl",
        evidence="Jan Kowalski, dyrektor",
        source_url="img://roster.jpg",
        confidence="high",
    )
    on_domain = StaffRecord(
        name="Maria Nowak",
        role="deputy_director",
        email="maria@real.pl",
        evidence="Maria Nowak, wicedyrektor",
        source_url="img://roster.jpg",
        confidence="high",
    )
    result = ground_vision_extraction(SchoolExtraction(staff=[off_domain, on_domain]), school_website_domain="real.pl")
    by_name = {r.name: r for r in result.staff}
    assert by_name["Jan Kowalski"].confidence == "medium"  # off-domain email -> capped
    assert by_name["Maria Nowak"].confidence == "high"  # own-domain email -> kept


def test_vision_strips_malformed_email():
    extraction = SchoolExtraction(
        staff=[
            StaffRecord(
                name="Jan Kowalski",
                role="director",
                email="not-an-email",
                evidence="Jan Kowalski",
                source_url="img://roster.jpg",
                confidence="high",
            )
        ]
    )
    result = ground_vision_extraction(extraction, school_website_domain="real.pl")
    assert result.staff[0].email is None
