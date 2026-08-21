"""Budget efficiency and precision fixes from the 48-school teacher audit.

Four independent defects, each measured on real schools:

  * a bilingual site spent its whole ten-page budget on five URLs, two of
    them the /en/ mirrors of pages already held in Polish, and never
    reached the pages naming its English teachers -- and bilingual /
    international schools are exactly this tool's highest-value segment;
  * a school whose nav links out to its e-register more often than to its
    own pages was declared "migrated" to librus.pl and crawled there, even
    though its own homepage verified as a real school site -- which is how
    three schools ended up storing "sekretariat@librus.pl" as their office
    address;
  * a 34,000-char page said "angielski" thirty times in marketing copy
    before its staff table, so the role-window budget was spent before
    reaching the only part that could name a teacher;
  * the extraction prompt had no list of the things that LOOK like a
    teacher record and are not (pupils in prize lists, job adverts...).
"""

from levelup.services.enrichment.llm_extract import _TEXT_EXTRACTION_SYSTEM_PROMPT
from levelup.services.enrichment.scraper import (
    _MAX_LLM_PAGE_CHARS,
    _cap_for_llm,
    _dedup_key,
    _strip_language_prefix,
)
from levelup.services.enrichment.verifier import (
    is_non_school_email,
    is_third_party_vendor_email,
)


def test_language_mirror_does_not_cost_a_second_page_slot():
    assert _dedup_key("https://ksp.edu.pl/en/dyrekcja/") == _dedup_key("https://ksp.edu.pl/dyrekcja/")
    assert _dedup_key("https://ksp.edu.pl/en/") == _dedup_key("https://ksp.edu.pl/")
    assert _dedup_key("https://x.pl/kadra?lang=en") == _dedup_key("https://x.pl/kadra")


def test_english_only_page_keeps_its_own_key():
    # The trade-off is explicit: a mirror of a page we hold is skipped, but
    # a page that exists ONLY in the English tree must stay crawlable --
    # one audited school's only roster PDF was linked from there alone.
    assert _strip_language_prefix("/en/our-team") == "/our-team"
    assert _dedup_key("https://x.pl/en/our-team") != _dedup_key("https://x.pl/kadra")


def test_non_language_first_segment_is_untouched():
    # "es" is a language code but "escuela"/"esp" style paths are not, and
    # a real content path must never be silently rewritten.
    assert _strip_language_prefix("/kadra/nauczyciele") == "/kadra/nauczyciele"
    assert _strip_language_prefix("/education/staff") == "/education/staff"
    assert _dedup_key("https://x.pl/kontakt") != _dedup_key("https://x.pl/kadra")


def test_e_register_and_exam_authority_addresses_are_rejected():
    # Mail to these reaches a software vendor or the national examination
    # commission, never the school.
    for bad in (
        "sekretariat@librus.pl",
        "kontakt@vulcan.edu.pl",
        "sekretariat@cke.gov.pl",
        "info@edupage.org",
    ):
        assert is_third_party_vendor_email(bad), bad
        assert is_non_school_email(bad), bad


def test_school_mailboxes_on_hosting_providers_are_kept():
    # A school's REAL mailbox often lives on its host's subdomain --
    # blanketing the provider would discard 14 correct addresses to remove
    # none.
    for good in (
        "sekretariat@sp1lowicz.szkolnastrona.pl",
        "spzmigrod@superszkolna.pl",
        "szkola-37@katowice.home.pl",
        "sekretariat@sp24.nazwa.pl",
    ):
        assert not is_third_party_vendor_email(good), good


def _long_page_with_late_roster():
    marketing = "Nauka jezyka angielskiego w wymiarze rozszerzonym. " * 320  # ~16k chars, no names
    roster = "Jezyk angielski Elzbieta Dudzik-Poremska Jezyk angielski Marta Nowak "
    return marketing + roster + ("Inne tresci. " * 400)


def test_truncation_prefers_windows_that_actually_name_someone():
    text = _long_page_with_late_roster()
    assert len(text) > _MAX_LLM_PAGE_CHARS
    capped = _cap_for_llm(text)
    assert len(capped) <= _MAX_LLM_PAGE_CHARS
    # The roster is the only part that could prove a teacher -- it must survive.
    assert "Elzbieta Dudzik-Poremska" in capped
    assert "Marta Nowak" in capped


def test_short_pages_are_never_altered():
    short = "Jezyk angielski Anna Kowalska"
    assert _cap_for_llm(short) == short


def test_prompt_warns_about_the_audited_false_positive_shapes():
    prompt = _TEXT_EXTRACTION_SYSTEM_PROMPT.lower()
    # Each of these was a real "looks exactly like a teacher record" trap.
    for marker in ("laureat", "oferta pracy", "przedszkolu", "imie.nazwisko", "klasa 4a"):
        assert marker in prompt, marker
    assert "not staff" in prompt


def test_links_resolve_against_the_final_url_after_a_redirect():
    """A legacy-CMS school site 302s "/" to "/asp/pl_start.asp" and writes
    every nav link as a bare query string. Resolved against the requested
    URL, urljoin drops the script name and each link collapses back onto
    the homepage -- one audited school had three "staff pages" that were
    byte-identical copies of its front page."""
    from bs4 import BeautifulSoup

    from levelup.services.enrichment.scraper import (
        _find_subpage_links,
        _note_final_url,
        _final_url_for,
    )

    requested = "http://stociechanow.pl/"
    landed = "http://stociechanow.pl/asp/pl_start.asp?typ=14&menu=1&strona=1"
    _note_final_url(requested, landed)
    assert _final_url_for(requested) == landed

    html = '<a href="?typ=14&amp;menu=223&amp;strona=1">Kadra</a>'
    soup = BeautifulSoup(html, "html.parser")

    # Against the requested URL the query-only href loses the script path.
    naive = [u for _, u in _find_subpage_links(soup, requested, "SZKOLA PODSTAWOWA")]
    assert all("pl_start.asp" not in u for u in naive)

    # Against the landing URL it points where a browser would.
    fixed = [u for _, u in _find_subpage_links(soup, landed, "SZKOLA PODSTAWOWA")]
    assert any("pl_start.asp" in u and "menu=223" in u for u in fixed), fixed
