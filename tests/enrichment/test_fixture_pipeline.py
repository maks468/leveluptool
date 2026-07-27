"""Offline, fixture-based test of the preprocessing + grounding pipeline
against REAL (if synthetic) HTML markup -- the piece the synthetic-string
tests in test_grounding.py don't exercise: table-row serialization,
Cloudflare-cloaked email decoding, and image/PDF link listing, all inside
_prepare_page_for_llm. No real SDK/CLI call: a hand-authored
SchoolExtraction stands in for what the LLM would produce (a fake
transport), then runs through the same ground_extraction the real pipeline
uses. If a bug is ever introduced in _prepare_page_for_llm's table/email/
link handling, this is the test that catches it -- test_grounding.py's
synthetic strings can't."""

from pathlib import Path

from levelup.services.enrichment.llm_extract import SchoolExtraction, StaffRecord, ground_extraction
from levelup.services.enrichment.scraper import _prepare_page_for_llm

FIXTURES_DIR = Path(__file__).resolve().parent.parent / "fixtures" / "enrichment"
PAGE_URL = "https://sptestowo.pl/kadra"


def _load_prepared_text() -> str:
    html = (FIXTURES_DIR / "staff_table.html").read_text(encoding="utf-8")
    return _prepare_page_for_llm(html, PAGE_URL)


def test_table_rows_are_serialized_with_pipe_separators():
    text = _load_prepared_text()
    assert "mgr Kowalska Anna | język angielski" in text
    assert "mgr Nowak Piotr | Dyrektor, matematyka" in text


def test_cloudflare_cloaked_email_is_decoded_into_footer():
    text = _load_prepared_text()
    assert "DECODED_OBFUSCATED_EMAILS:" in text
    assert "anna.kowalska@sptestowo.pl" in text


def test_image_or_pdf_links_are_listed_with_absolute_urls():
    text = _load_prepared_text()
    assert "IMAGE_OR_PDF_LINKS:" in text
    assert "https://sptestowo.pl/pliki/grono_pedagogiczne_2026.pdf" in text


def test_full_pipeline_grounds_a_correct_extraction_against_the_fixture():
    """A hand-authored "what the LLM should say" extraction for this exact
    fixture, run through the real ground_extraction -- every record here
    is genuinely on the page, so all three should survive."""
    text = _load_prepared_text()
    pages_by_url = {PAGE_URL: text}

    extraction = SchoolExtraction(
        staff=[
            StaffRecord(
                name="Piotr Nowak",  # Last-First on the page, reversed here
                role="director",
                evidence="mgr Nowak Piotr | Dyrektor, matematyka",
                source_url=PAGE_URL,
                confidence="high",
            ),
            StaffRecord(
                name="Anna Kowalska",
                role="english_teacher",
                subjects=["język angielski"],
                email="anna.kowalska@sptestowo.pl",
                email_evidence="Anna Kowalska): anna.kowalska@sptestowo.pl",
                evidence="mgr Kowalska Anna | język angielski",
                source_url=PAGE_URL,
                confidence="high",
            ),
            StaffRecord(
                name="Tomasz Wiśniewski",
                role="other_teacher",
                evidence="mgr Wiśniewski Tomasz | wychowanie fizyczne",
                source_url=PAGE_URL,
                confidence="high",
            ),
        ],
        unattributed_emails=["sekretariat@sptestowo.pl"],
    )

    result = ground_extraction(extraction, pages_by_url, school_name="Szkoła Podstawowa im. Jana Kochanowskiego w Testowie")
    names = {r.name for r in result.staff}
    assert names == {"Piotr Nowak", "Anna Kowalska", "Tomasz Wiśniewski"}
    kowalska = next(r for r in result.staff if r.name == "Anna Kowalska")
    assert kowalska.email == "anna.kowalska@sptestowo.pl"


def test_full_pipeline_rejects_the_patron_and_a_hallucinated_email_evidence_mismatch():
    """A model that (wrongly) tags the school's patron as staff, and one
    that pairs a real email to the wrong person (evidence doesn't tie
    them together), against the SAME real fixture text."""
    text = _load_prepared_text()
    pages_by_url = {PAGE_URL: text}

    extraction = SchoolExtraction(
        staff=[
            StaffRecord(
                name="Jan Kochanowski",  # the school's own patron -- never staff
                role="other_staff",
                evidence="Patronem naszej szkoły jest Jan Kochanowski",
                source_url=PAGE_URL,
                confidence="high",
            ),
            StaffRecord(
                name="Tomasz Wiśniewski",
                role="other_teacher",
                email="anna.kowalska@sptestowo.pl",  # a real email, but NOT this person's
                email_evidence="mgr Wiśniewski Tomasz",  # doesn't contain the email at all
                evidence="mgr Wiśniewski Tomasz | wychowanie fizyczne",
                source_url=PAGE_URL,
                confidence="high",
            ),
        ]
    )

    result = ground_extraction(extraction, pages_by_url, school_name="Szkoła Podstawowa im. Jana Kochanowskiego w Testowie")
    assert len(result.staff) == 1
    assert result.staff[0].name == "Tomasz Wiśniewski"
    assert result.staff[0].email is None  # wrongly-paired email stripped, person kept
