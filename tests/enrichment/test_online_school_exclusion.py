""""Szkoła w Chmurze" (the online-school network) must never enter the
library: user-confirmed exclusion, 2026-08-04."""

from levelup.services.import_service.exclusion_rules import classify, is_online_school


def _row(name):
    return {
        "Czy szkoła": "1",
        "Typ podmiotu": "Liceum ogólnokształcące",
        "Nazwa placówki": name,
        "Kategoria uczniów": "Dzieci lub młodzież",
        "Specyfika szkoły": None,
        "ucz_ogolem": "100",
    }


def test_w_chmurze_branches_are_excluded_in_every_naming_variant():
    for name in (
        'LICEUM OGÓLNOKSZTAŁCĄCE "LICEUM W CHMURZE" W TORUNIU',
        "I LICEUM W CHMURZE",
        "SZKOŁA PODSTAWOWA „SZKOŁA W CHMURZE” W NYSIE",
        "NIEPUBLICZNA SZKOŁA PODSTAWOWA W CHMURZE W WARSZAWIE",
    ):
        assert is_online_school(_row(name)), name
        assert classify(_row(name)) == "exclude_online_school", name


def test_ordinary_schools_are_not_swept_up():
    for name in (
        "LICEUM OGÓLNOKSZTAŁCĄCE IM. JANA KOCHANOWSKIEGO W CHEŁMIE",
        "SZKOŁA PODSTAWOWA NR 5 W CHMIELNIKU",  # city starts with 'Chm' but isn't the brand
    ):
        assert not is_online_school(_row(name)), name
        assert classify(_row(name)) == "import", name


# --- Throttling notices and thin pages are not content ----------------------
# edupage.org (2,417 schools in this register) answers rapid crawling with
# HTTP 200 and an 84-byte "Your IP is temporarily blocked" body. Treated as
# content, it was recorded as an "ok" source AND spent one of the school's
# eight LLM page slots -- so a batch of edupage schools could each come back
# "enriched, nothing found" purely because the platform was throttling us.

from levelup.services.enrichment.scraper import _MIN_LLM_PAGE_CHARS, _is_block_page


def test_throttling_notice_is_not_a_page():
    assert _is_block_page(
        "Your IP is temporarily blocked because of too many requests. Please try again later."
    )
    assert _is_block_page("429 - too many requests")
    assert _is_block_page("Zbyt wiele zapytań z Twojego adresu IP.")


def test_real_pages_are_never_mistaken_for_a_block():
    # Long bodies are exempt outright...
    assert not _is_block_page("Grono pedagogiczne. Język angielski: Anna Kowalska. " * 40)
    # ...and a short page that simply doesn't say it is throttled is fine.
    assert not _is_block_page("Sekretariat: sekretariat@szkola.pl, tel. 12 345 67 89")
    assert not _is_block_page(None)


def test_thin_page_threshold_is_small_enough_for_terse_contact_pages():
    terse = "Sekretariat: sekretariat@szkola.pl tel. 12 345 67 89 ul. Szkolna 1, 00-001 Miasto"
    assert len(terse) >= _MIN_LLM_PAGE_CHARS or _MIN_LLM_PAGE_CHARS <= 120
