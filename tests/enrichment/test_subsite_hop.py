"""Level-named subdomain hops (the zsosto.pl failure).

A school complex's rich landing page linked its primary school's real
subsite as `<a href="https://sp.zsosto.pl/">wejdź</a>` -- no keyword in
the label, page too rich for the sparse-chooser heuristic -- so the one
link leading to per-teacher personal emails was silently dropped. These
tests pin the fix: the HOST is the signal, and only for the school's own
level.
"""

from bs4 import BeautifulSoup

from levelup.services.enrichment.scraper import (
    _find_subpage_links,
    _is_complete,
    _same_level_subsite_host,
)

PRIMARY = "SPOŁECZNA SZKOŁA PODSTAWOWA NR 1 IM. JANA NOWAKA-JEZIORAŃSKIEGO"
LICEUM = "SPOŁECZNE LICEUM OGÓLNOKSZTAŁCĄCE NR 1"


def test_level_named_subdomain_of_own_domain_matches_own_level():
    assert _same_level_subsite_host("https://sp.zsosto.pl/", "https://www.zsosto.pl", PRIMARY)
    assert _same_level_subsite_host("http://lo.zsosto.pl/x", "https://zsosto.pl", LICEUM)


def test_wrong_level_or_unhinted_subdomain_is_not_adopted():
    # A primary school's crawl must not hop into the liceum's subsite...
    assert not _same_level_subsite_host("https://lo.zsosto.pl/", "https://zsosto.pl", PRIMARY)
    # ...and a subdomain that implies no level at all stays a sibling
    # ("slojedynka" is the liceum's branding, not a level shape).
    assert not _same_level_subsite_host("https://slojedynka.zsosto.pl/", "https://zsosto.pl", PRIMARY)


def test_other_domains_and_deep_hosts_never_match():
    # Same level word, DIFFERENT registered domain -- someone else's site.
    assert not _same_level_subsite_host("https://sp.szkolna.pl/", "https://zsosto.pl", PRIMARY)
    # Multi-label subdomains are never a school-section entrance shape.
    assert not _same_level_subsite_host("https://sp.old.zsosto.pl/", "https://zsosto.pl", PRIMARY)
    # The same host isn't a hop.
    assert not _same_level_subsite_host("https://zsosto.pl/sp", "https://zsosto.pl", PRIMARY)


def test_unlabelled_subsite_link_gets_hub_tier_from_a_rich_page():
    """The exact zsosto shape: a content-rich complex homepage whose only
    path to the school's own site is an unlabelled button. It must come
    out at tier -1 (hub entrance), ahead of ordinary keyword links."""
    html = """
    <html><body>
      <p>{filler}</p>
      <h2>Szkoła Podstawowa</h2><a href="https://sp.zsosto.pl/">wejdź</a>
      <h2>Liceum</h2><a href="http://slojedynka.zsosto.pl">wejdź</a>
      <a href="/szkola-podstawowa/kontakt/">Kontakt</a>
      <a href="https://synergia.librus.pl/">E-Dziennik</a>
    </body></html>
    """.format(filler="Aktualności rekrutacja ogłoszenia " * 40)  # far past the sparse-chooser cutoff
    soup = BeautifulSoup(html, "html.parser")

    found = dict(
        (url, tier) for tier, url in _find_subpage_links(soup, "https://www.zsosto.pl", PRIMARY)
    )

    assert found.get("https://sp.zsosto.pl/") == -1
    # The liceum's subsite is a sibling, not this school's -- left out
    # entirely (its label matches no keyword and its host implies no
    # primary-school shape).
    assert "http://slojedynka.zsosto.pl" not in found
    # Ordinary keyword links still tier normally alongside the hop.
    assert found.get("https://www.zsosto.pl/szkola-podstawowa/kontakt/") is not None
    # And a genuinely external domain never sneaks in.
    assert all("librus" not in url for url in found)


def test_office_email_no_longer_ends_the_crawl_early():
    """The other half of the zsosto failure: with both names known, a bare
    sekretariat@ used to declare the crawl complete -- one page short of
    the staff page with seven personal teacher emails. Only a
    personal-candidate address (unrecognized local part) may stop it now."""
    base = {"director_name": "Anna Kowalska", "english_teacher_name": "Jan Nowak"}

    assert not _is_complete({**base, "all_emails": {"sekretariat@zsosto.pl"}})
    assert not _is_complete({**base, "all_emails": {"rekrutacja@zsosto.pl"}})
    assert not _is_complete({**base, "all_emails": set()})
    # A personal-shaped candidate ends it -- and only alongside both names.
    assert _is_complete({**base, "all_emails": {"agata.bien@zsosto.pl"}})
    assert not _is_complete(
        {"director_name": None, "english_teacher_name": "Jan Nowak", "all_emails": {"agata.bien@zsosto.pl"}}
    )
