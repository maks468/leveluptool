"""Regression tests for the TEB Rzeszów incident: one person's name was
written with a different person's email and stamped "verified", and the
school's website was silently re-pointed at a sibling branch in another
city. Fields must never mix across two humans; "verified" must be backed
by a check; a chain school's adopted subsite must mention its own city.
"""

from levelup.services.enrichment.jobs import _resolve_email, _same_person
from levelup.services.enrichment.llm_extract import StaffRecord
from levelup.services.enrichment.scraper import _mentions_school_city, _school_city_stem
from levelup.services.enrichment.verifier import classify_contact_quality

TEB_RZESZOW = "LICEUM OGÓLNOKSZTAŁCĄCE TEB EDUKACJA W RZESZOWIE"


def _record(name, email):
    return StaffRecord(
        name=name,
        role="director",
        email=email,
        email_evidence=f"{name}: {email}",
        evidence=f"Dyrektor: {name}",
        source_url="https://example.pl/kontakt",
        confidence="high",
    )


def test_record_email_never_attaches_to_a_different_persons_name():
    """The exact TEB failure: RSPO won the NAME (Jadwiga Kudyba), the LLM
    record described Izabela Józefowska -- her email must not ride along."""
    record = _record("Izabela Józefowska", "izabela.jozefowska@teb-edukacja.pl")
    assert _resolve_email(record, [], "Jadwiga Kudyba") is None


def test_record_email_attaches_to_the_same_person_any_word_order():
    record = _record("Izabela Józefowska", "izabela.jozefowska@teb-edukacja.pl")
    assert _resolve_email(record, [], "Izabela Józefowska") == "izabela.jozefowska@teb-edukacja.pl"
    assert _resolve_email(record, [], "Józefowska Izabela") == "izabela.jozefowska@teb-edukacja.pl"


def test_same_person_rejects_partial_overlap():
    assert not _same_person("Anna Kowalska", "Anna Nowak")
    assert not _same_person("Anna Kowalska", "Anna Kowalska-Nowak")
    assert not _same_person("Anna Kowalska", None)


def test_structural_fallback_still_validates_against_the_written_name():
    emails = ["izabela.jozefowska@teb-edukacja.pl", "j.kudyba@teb.pl"]
    assert _resolve_email(None, emails, "Jadwiga Kudyba") == "j.kudyba@teb.pl"


def test_verified_label_requires_the_email_to_match_the_person():
    """The mixed row was stamped "verified" -- the label must re-check."""
    assert classify_contact_quality("Jadwiga Kudyba", "izabela.jozefowska@teb-edukacja.pl") == "partial"
    assert classify_contact_quality("Izabela Józefowska", "izabela.jozefowska@teb-edukacja.pl") == "verified"
    assert classify_contact_quality("Jadwiga Kudyba", None) == "partial"
    assert classify_contact_quality(None, "sekretariat@teb.pl") == "failed"


def test_city_stem_survives_declension():
    assert _school_city_stem(TEB_RZESZOW) == "rzes"
    assert _school_city_stem("SZKOŁA PODSTAWOWA WE WROCŁAWIU") == "wroc"
    assert _school_city_stem("LICEUM W ŁODZI") == "lodz"
    assert _school_city_stem("PUBLICZNE LICEUM SIÓSTR PREZENTEK") is None  # no city -> no check


def test_sibling_branch_page_is_rejected_as_own_subsite():
    """The exact TEB poisoning: a /swidnica/ page adopted for a Rzeszów
    school. Neither URL nor content mentions Rzeszów -> reject."""
    swidnica_html = "<html><body>TEB Edukacja Liceum w Świdnicy, ul. Przykładowa 1</body></html>"
    assert not _mentions_school_city(TEB_RZESZOW, swidnica_html, "https://szkolasrednia.teb.pl/miasta/d/swidnica/")


def test_own_city_page_is_accepted():
    rzeszow_html = "<html><body>TEB Edukacja Liceum, Rzeszów ul. Przykładowa 2</body></html>"
    assert _mentions_school_city(TEB_RZESZOW, rzeszow_html, "https://szkolasrednia.teb.pl/miasta/p/rzeszow/")
    # URL alone is enough when the page is JS-rendered/thin
    assert _mentions_school_city(TEB_RZESZOW, "<html></html>", "https://teb.pl/miasta/rzeszow/")


def test_no_city_in_name_never_blocks():
    assert _mentions_school_city("PUBLICZNE LICEUM SIÓSTR PREZENTEK", "<html>anything</html>", "https://x.pl/")


def test_website_city_guard_is_wired_into_jobs():
    """A wiring guard, not a behaviour test: the city check is called from
    enrich_school's website-correction branch, which only executes when the
    crawl discovers a DIFFERENT url -- so a missing import there raised
    NameError at runtime for 9 real schools while every unit test passed.
    This pins the symbol's availability at import time."""
    from levelup.services.enrichment import jobs

    assert callable(jobs._mentions_school_city)


def test_hyphenated_patron_surname_is_recognised():
    """Regression: the school name's "im." clause is tokenized on every
    non-letter, so the candidate must be too -- otherwise the canonical
    Polish patron "Skłodowska-Curie" stayed one unmatched word and could be
    written as staff."""
    from levelup.services.enrichment.scraper import _is_patron_name, _patron_name_tokens

    tokens = _patron_name_tokens("SZKOŁA PODSTAWOWA IM. MARII SKŁODOWSKIEJ-CURIE W OPOLU")
    assert _is_patron_name("Maria Skłodowska-Curie", tokens)
    # Still narrow: a real staff member must match the patron on EVERY name
    # part, so sharing just the surname does not make someone the patron.
    assert not _is_patron_name("Anna Skłodowska", tokens)
    assert not _is_patron_name("Jan Nowak", tokens)
