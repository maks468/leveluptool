"""Staff-roster discovery beyond keyword tiering.

Pins the fixes from auditing 44 high-scoring schools that reached "basic"
enrichment (director + office email, no English teacher). 26 of them DID
publish a findable English teacher; the roster was simply unreachable. The
recurring shapes, each covered below:

  * a roster labelled with a word nobody had listed -- "Nasz zespol" on
    private/Montessori sites, and the ENGLISH labels ("Our Team", "Staff")
    that bilingual and international schools use, which is exactly the
    school profile this tool targets;
  * an IMAGE-ONLY nav, where the roster link has no text at all and its
    accessible name lives in the <img alt>;
  * QUERYSTRING PERMALINKS ("/index.php?id=42"), where every nav target
    collapsed to one dedup key so the crawl fetched a single page and
    concluded the site had no links;
  * everything else -- an untiered, unlabelled or off-subdomain roster --
    handed to an LLM nav-picker, which only runs when keyword tiering
    found no staff link at all.
"""

from bs4 import BeautifulSoup

from levelup.services.enrichment.scraper import (
    _dedup_key,
    _keyword_matches,
    _picked_staff_links,
    _staff_page_pending,
    all_candidate_links,
    _find_subpage_links,
)

SCHOOL = "PRYWATNA SZKOŁA PODSTAWOWA NR 1"


def _tier_of(html, url, label_url):
    links = dict((u, t) for t, u in _find_subpage_links(BeautifulSoup(html, "html.parser"), url, SCHOOL))
    return links.get(label_url)


def test_polish_and_english_staff_labels_now_reach_the_staff_tier():
    html = """
      <a href="/nasz-zespol">Nasz zespół</a>
      <a href="/team">Our Team</a>
      <a href="/en/staff">Staff</a>
      <a href="/nasi-nauczyciele">Nasi nauczyciele</a>
    """
    for target in ("http://x.pl/nasz-zespol", "http://x.pl/team", "http://x.pl/en/staff", "http://x.pl/nasi-nauczyciele"):
        tier = _tier_of(html, "http://x.pl/", target)
        assert tier is not None and tier <= 1, f"{target} got tier {tier}"


def test_short_english_keywords_are_boundary_matched():
    # A STEAM programme page is on half these schools' navs and must not
    # look like a staff page just because "steam" contains "team".
    assert _keyword_matches("team", "/our-team/")
    assert _keyword_matches("team", "nasz team")
    assert not _keyword_matches("team", "/steamowe-abc/")
    assert not _keyword_matches("staff", "staffordshire-exchange")


def test_image_only_nav_link_is_tiered_from_its_alt_text():
    # Opaque URL, no anchor text -- the label lives in the image's alt.
    html = '<a href="/index.php?id=42"><img src="/b.png" alt="Kadra"></a>'
    assert _tier_of(html, "http://x.pl/", "http://x.pl/index.php?id=42") == 1


def test_querystring_permalinks_no_longer_collapse_to_one_page():
    a = _dedup_key("http://x.pl/index.php?id=42")
    b = _dedup_key("http://x.pl/index.php?id=77")
    assert a != b, "distinct pages must not share a dedup key"
    # Same page reached with different capitalisation/slash/scheme still collapses.
    assert _dedup_key("https://WWW.x.pl/kadra/") == _dedup_key("http://x.pl/kadra")
    # Tracking-only differences still collapse.
    assert _dedup_key("http://x.pl/kadra?utm_source=fb&fbclid=9") == _dedup_key("http://x.pl/kadra")
    # Parameter ORDER must not change the key.
    assert _dedup_key("http://x.pl/a?b=1&c=2") == _dedup_key("http://x.pl/a?c=2&b=1")


def test_all_candidate_links_is_wide_but_drops_known_noise():
    html = """
      <a href="/kadra">Kadra</a>
      <a href="https://sp.innadomena.pl/nauczyciele">wejdź</a>
      <a href="https://facebook.com/szkola">FB</a>
      <a href="https://synergia.librus.pl/loguj">Librus</a>
      <a href="mailto:a@b.pl">mail</a>
      <a href="/plik.pdf">PDF</a>
      <a href="#top">góra</a>
      <a href="/foto"><img alt="Galeria zdjęć"></a>
    """
    got = all_candidate_links(BeautifulSoup(html, "html.parser"), "http://x.pl/")
    urls = [u for _, u in got]
    # Cross-domain kept: the picker is what judges whether it is this school.
    assert "https://sp.innadomena.pl/nauczyciele" in urls
    assert "http://x.pl/kadra" in urls
    # Noise dropped.
    assert not any("facebook" in u or "librus" in u or u.endswith(".pdf") for u in urls)
    assert not any(u.startswith("mailto") for u in urls)
    # An image-only link still carries a usable label.
    assert ("Galeria zdjęć", "http://x.pl/foto") in got


def test_picker_runs_only_when_tiering_found_no_staff_page():
    # With a real "Kadra" link queued, the gate says a staff page is
    # pending -- which is the same condition that suppresses the picker.
    assert _staff_page_pending([(1, "http://x.pl/kadra")], visited=set()) is True
    # With only low-value links, nothing staff-ish is pending.
    assert _staff_page_pending([(2, "http://x.pl/kontakt"), (3, "http://x.pl/o-nas")], set()) is False


def test_picker_result_is_restricted_to_offered_urls():
    html = '<a href="/zespol-dydaktyczny">Zespół</a><a href="/aktualnosci">Aktualności</a>'
    # A picker that hallucinates a URL must not steer the crawl.
    def liar(candidates, school_name, city):
        return ["http://evil.example/inject", "http://x.pl/zespol-dydaktyczny"]

    got = _picked_staff_links(liar, html, "http://x.pl/", SCHOOL, "Warszawa")
    assert got == ["http://x.pl/zespol-dydaktyczny"]


def test_picker_failure_never_breaks_the_crawl():
    html = '<a href="/kadra">Kadra</a>'

    def boom(candidates, school_name, city):
        raise RuntimeError("CLI exploded")

    assert _picked_staff_links(boom, html, "http://x.pl/", SCHOOL, None) == []


def test_usage_limit_from_picker_still_propagates():
    # A usage-window exhaustion must stop the whole batch, not be quietly
    # swallowed as "this school had no nav links" (see jobs.run_job).
    class UsageLimitError(Exception):
        pass

    html = '<a href="/kadra">Kadra</a>'

    def limited(candidates, school_name, city):
        raise UsageLimitError("window exhausted")

    try:
        _picked_staff_links(limited, html, "http://x.pl/", SCHOOL, None)
    except UsageLimitError:
        return
    raise AssertionError("UsageLimitError must propagate out of the picker")


def test_a_complex_splash_that_tiles_its_schools_as_paths_is_followed():
    """lauder-morasha.edu.pl's homepage is a three-tile splash: Przedszkole
    -> /przedszkole/, Szkoła Podstawowa -> /szkola, Liceum -> external. The
    hub rule only recognized a member school on a DIFFERENT host, so the
    SP's own tile got no tier, the crawl fell back to guessing slugs that
    don't exist, and the teacher (on /szkola/grono-pedagogiczne/) stayed
    invisible. From the domain root, a same-host level tile is followed."""
    from bs4 import BeautifulSoup
    from levelup.services.enrichment.scraper import _find_subpage_links

    splash = BeautifulSoup(
        '<a href="/przedszkole/">Przedszkole</a>'
        '<a href="/szkola">Szkoła Podstawowa Lauder-Morasha</a>'
        '<a href="https://ginczanka.edu.pl/">Liceum</a>',
        "html.parser",
    )
    got = _find_subpage_links(splash, "http://www.lauder-morasha.edu.pl", 'PRYWATNA SZKOŁA PODSTAWOWA NR 94 "LAUDER MORASHA"')
    assert ("http://www.lauder-morasha.edu.pl/szkola" in dict((u, t) for t, u in got)), got

    # ...but the same label DEEP inside a subsite must not re-match (the
    # ekola.edu.pl/liceum/ budget burn the different-host rule prevents).
    deep = BeautifulSoup('<a href="/liceum/zasady">Zasady liceum</a>', "html.parser")
    got_deep = _find_subpage_links(deep, "https://ekola.edu.pl/liceum/", "LICEUM EKOLA")
    assert all(t != 0 for t, _ in got_deep), got_deep
