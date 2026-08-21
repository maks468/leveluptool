"""Competition winners are not staff (the psp.bialystok.pl failure).

Two independent defects met on one school and cost it its English teacher:

1. A prize-winners list reads exactly like a staff roster. The homepage
   said "z Wojewódzkich Konkursów Przedmiotowych uczniowie klasy VIIIa
   uzyskali następujące wyniki: Język Angielski: Karolina Brzozowska -
   tytuł laureata" -- character-for-character the shape of "Język
   angielski: <teacher>". Every name there is a PUPIL.

2. That phantom then ENDED the crawl. `_is_complete` counted the fake
   teacher, so two pages in the crawl declared itself done and never
   fetched `/teachers/` (queued at tier 1), the page that really does
   name the English teacher -- "Agnieszka Konopka Język angielski Science
   in English". The LLM was handed no page that could prove a teacher, so
   the school was recorded with none.

Regex names are never written to a school record (accuracy policy: only
an LLM record grounded in a verbatim quote is). A signal too weak to
write must not be strong enough to end the page budget -- that is what
the staff_page_pending gate pins here.
"""

from bs4 import BeautifulSoup

from levelup.services.enrichment.scraper import (
    _earliest_valid_match,
    _english_teacher_from_entries,
    _is_complete,
    _staff_page_pending,
    ENGLISH_TEACHER_NAME_FIRST_RE,
    ENGLISH_TEACHER_RE,
    ENGLISH_TEACHER_ROLE_LIST_RE,
)

TEACHER_PATTERNS = (ENGLISH_TEACHER_RE, ENGLISH_TEACHER_NAME_FIRST_RE, ENGLISH_TEACHER_ROLE_LIST_RE)

# Verbatim from the school's homepage.
PRIZE_LIST = (
    "Nasi laureaci 2023/2024 Z dumą informujemy, że z Wojewódzkich Konkursów "
    "Przedmiotowych uczniowie klasy VIIIa uzyskali następujące wyniki: "
    "Język Angielski: Karolina Brzozowska - tytuł laureata, Julia Nitkiewicz - "
    "tytuł laureata, Kaya Polak - tytuł laureata, Alek Bogdanowicz - finalista. "
    "Matematyka: Hanna Aleksiejuk - tytuł laureata. Serdecznie gratulujemy!"
)


def test_prize_winner_is_not_read_as_the_english_teacher():
    assert _earliest_valid_match(PRIZE_LIST, TEACHER_PATTERNS, achievement_guard=True) is None
    # Without the guard the pupil still matches -- proves the fixture is a
    # real trap and the guard is what rejects it, not some other filter.
    assert _earliest_valid_match(PRIZE_LIST, TEACHER_PATTERNS) == "Karolina Brzozowska"


def test_trailing_prize_marker_alone_is_enough_to_reject():
    # No "konkurs"/"laureaci" lead-in, only the per-name trail.
    text = "Język angielski: Maria Zielińska - II miejsce"
    assert _earliest_valid_match(text, TEACHER_PATTERNS, achievement_guard=True) is None


def test_a_real_staff_line_still_extracts_with_the_guard_on():
    # The guard must not cost real teachers: ordinary roster prose has no
    # achievement vocabulary anywhere near it.
    text = "Grono pedagogiczne: Język angielski: Agnieszka Konopka Matematyka: Piotr Nowak"
    assert _earliest_valid_match(text, TEACHER_PATTERNS, achievement_guard=True) == "Agnieszka Konopka"


def test_prize_list_rendered_as_list_items_is_also_rejected():
    # Same trap reaching the per-entry path instead of the flattened one.
    html = f"<ul><li>{PRIZE_LIST}</li></ul>"
    assert _english_teacher_from_entries(BeautifulSoup(html, "html.parser"), set()) is None
    # ...while a genuine roster entry still resolves.
    roster = "<ul><li>Agnieszka Konopka Język angielski Science in English</li></ul>"
    assert _english_teacher_from_entries(BeautifulSoup(roster, "html.parser"), set()) == "Agnieszka Konopka"


def _complete_result():
    """A result that satisfies every OTHER completion condition."""
    return {
        "director_name": "Agnieszka Iłendo-Milewska",
        "english_teacher_name": "Karolina Brzozowska",
        "all_emails": {"agnieszka.ilendo@psp.bialystok.pl"},
    }


def test_unread_staff_page_holds_the_crawl_open():
    result = _complete_result()
    # Baseline: without the gate this result ends the crawl.
    assert _is_complete(result) is True
    # /teachers/ is queued at tier 1 and unread -> not done yet.
    frontier = [(3, "http://x.pl/a/o-nas"), (1, "http://x.pl/teachers/")]
    assert _staff_page_pending(frontier, visited=set()) is True
    assert _is_complete(result, staff_page_pending=True) is False


def test_gate_releases_once_the_staff_pages_have_been_read():
    from levelup.services.enrichment.scraper import _dedup_key

    frontier = [(3, "http://x.pl/a/o-nas"), (1, "http://x.pl/teachers/")]
    visited = {_dedup_key("http://x.pl/teachers/")}
    assert _staff_page_pending(frontier, visited) is False
    assert _is_complete(_complete_result(), staff_page_pending=False) is True


def test_competition_news_slug_does_not_hold_the_gate():
    # sp31.bydgoszcz.pl's writing-competition write-ups earn tier 1 from the
    # "dyrektor" in their slug. Holding the crawl open for those spends the
    # budget on prize news and can push the real roster out of the LLM's
    # page window.
    news = [
        (1, "https://sp31.bydgoszcz.pl/konkurs-ortograficzny-o-pioro-dyrektora-szkoly-wyniki/"),
        (1, "https://sp31.bydgoszcz.pl/laureaci-olimpiady/"),
    ]
    assert _staff_page_pending(news, visited=set()) is False
    # The genuine roster on the same site still holds it.
    assert _staff_page_pending(news + [(1, "https://sp31.bydgoszcz.pl/grono-pedagogiczne/")], set()) is True


def test_only_staff_tier_links_hold_the_gate():
    # A queued "o nas" (tier 3) or "kontakt" (tier 2) page is not a roster
    # and must not keep the crawl burning budget.
    frontier = [(2, "http://x.pl/contact/"), (3, "http://x.pl/about/")]
    assert _staff_page_pending(frontier, visited=set()) is False
    # A hub entrance to the school's own subsite (-1) does hold it.
    assert _staff_page_pending([(-1, "http://sp.x.pl/")], visited=set()) is True
