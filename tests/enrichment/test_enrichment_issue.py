"""schools.enrichment_issue -- the searchable answer to "where did
enrichment stop short?". One value per school, rewritten on every run,
derived from the same signals the run itself logged. Grew out of a manual
audit: seven hand-checked failures turned out to be five different failure
stages, none of which was visible anywhere a filter could reach."""

from levelup.services.enrichment.jobs import ENRICHMENT_ISSUES, _derive_enrichment_issue


def _issue(**kw):
    base = dict(sources_checked=[], llm_pages=[], teacher_name=None, teacher_email=None, website_url=None)
    base.update(kw)
    return _derive_enrichment_issue(**base)


def test_nothing_failed_when_the_teachers_own_email_was_found():
    assert _issue(teacher_name="Anna Nowak", teacher_email="a.nowak@sp.pl") is None


def test_a_named_teacher_without_an_address_is_the_last_remaining_gap():
    assert _issue(teacher_name="Anna Nowak") == "teacher_email_not_published"


def test_no_website_anywhere():
    assert _issue() == "website_missing"


def test_a_site_on_file_that_never_answered():
    assert _issue(
        website_url="www.gloszp.pl",
        sources_checked=[{"url": "http://www.gloszp.pl", "status": "unreachable"}],
    ) == "website_unreachable"


def test_a_page_that_answered_but_is_not_this_school():
    assert _issue(
        website_url="naukazfunandplay.pl",
        sources_checked=[{"url": "http://naukazfunandplay.pl", "status": "not_a_school_site"}],
    ) == "website_rejected"


def test_a_reached_site_with_no_provable_staff_page():
    assert _issue(
        website_url="sp.pl",
        sources_checked=[{"url": "http://sp.pl", "status": "ok"}],
        llm_pages=[],
    ) == "no_staff_page_found"


def test_staff_pages_read_but_no_teacher_named_on_them():
    assert _issue(
        website_url="sp.pl",
        sources_checked=[{"url": "http://sp.pl/kadra", "status": "ok"}],
        llm_pages=[{"url": "http://sp.pl/kadra"}],
    ) == "teacher_not_published"


def test_rspo_alone_never_counts_as_a_reached_site():
    assert _issue(
        sources_checked=[{"url": "https://rspo.gov.pl/api/Institution/1", "status": "ok"}],
    ) == "website_missing"


def test_every_derivable_value_is_in_the_published_vocabulary():
    cases = [
        _issue(teacher_name="A B"),
        _issue(),
        _issue(website_url="x.pl", sources_checked=[{"url": "http://x.pl", "status": "unreachable"}]),
        _issue(website_url="x.pl", sources_checked=[{"url": "http://x.pl", "status": "not_a_school_site"}]),
        _issue(website_url="x.pl", sources_checked=[{"url": "http://x.pl", "status": "ok"}]),
        _issue(website_url="x.pl", sources_checked=[{"url": "http://x.pl", "status": "ok"}], llm_pages=[1]),
    ]
    assert all(c in ENRICHMENT_ISSUES for c in cases)
