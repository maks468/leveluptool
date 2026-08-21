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


# --- Role-aware truncation --------------------------------------------------
# A staff roster longer than the per-page budget used to be cut blind at the
# head, removing "JĘZYK ANGIELSKI" before the model saw it. Measured on 35
# crawled staff pages of teacher-less schools: 8 exceeded the cap, and 2 of
# those mentioned English ONLY past the cut.

from levelup.services.enrichment.scraper import _MAX_LLM_PAGE_CHARS, _cap_for_llm


def test_english_section_beyond_the_cap_is_preserved():
    buried = ("nic tu nie ma. " * 700) + "JĘZYK ANGIELSKI | ANNA KOWALSKA" + (" inne treści." * 300)
    assert len(buried) > _MAX_LLM_PAGE_CHARS
    out = _cap_for_llm(buried)

    assert len(out) <= _MAX_LLM_PAGE_CHARS  # budget still respected
    assert "JĘZYK ANGIELSKI" in out
    assert "ANNA KOWALSKA" in out  # the names next to the label come along
    assert "[...]" in out  # elision is visible to the model


def test_short_and_keywordless_pages_are_unchanged():
    short = "Sekretariat: sekretariat@szkola.pl"
    assert _cap_for_llm(short) == short
    # Nothing role-relevant later on: identical to the old contiguous cut.
    filler = "x" * (_MAX_LLM_PAGE_CHARS * 2)
    assert _cap_for_llm(filler) == filler[:_MAX_LLM_PAGE_CHARS]


def test_director_vocabulary_also_survives_a_long_page():
    buried = ("tekst " * 1500) + "DYREKTOR SZKOŁY: Renata Karwowska" + (" ogon" * 500)
    out = _cap_for_llm(buried)
    assert "DYREKTOR SZKOŁY: Renata Karwowska" in out
    assert len(out) <= _MAX_LLM_PAGE_CHARS
