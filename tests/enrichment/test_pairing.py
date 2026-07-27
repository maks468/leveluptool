"""Attribution priority tests -- which staff record wins per role
(_pick_best_staff) and which email gets attached to a person
(_resolve_email). All offline, no DB session and no real SDK calls: these
are pure functions extracted from jobs.py's enrich_school specifically so
this priority logic is unit-testable on its own."""

from levelup.services.enrichment.jobs import _pick_best_staff, _resolve_email
from levelup.services.enrichment.llm_extract import StaffRecord


def _staff(name, role, confidence, source_url="https://a.pl/kadra"):
    return StaffRecord(name=name, role=role, evidence="x", source_url=source_url, confidence=confidence)


def test_director_role_preferred_over_deputy_regardless_of_confidence():
    staff = [
        _staff("Deputy Person", "deputy_director", "high"),
        _staff("Director Person", "director", "low"),
    ]
    best = _pick_best_staff(staff, ("director", "deputy_director"), {})
    assert best.name == "Director Person"


def test_higher_confidence_wins_within_same_role():
    staff = [
        _staff("Low Conf", "english_teacher", "low"),
        _staff("High Conf", "english_teacher", "high"),
        _staff("Medium Conf", "english_teacher", "medium"),
    ]
    best = _pick_best_staff(staff, ("english_teacher",), {})
    assert best.name == "High Conf"


def test_staff_tier_source_breaks_confidence_ties():
    staff = [
        _staff("From Homepage", "english_teacher", "high", source_url="https://a.pl/"),
        _staff("From Kadra Page", "english_teacher", "high", source_url="https://a.pl/kadra"),
    ]
    url_to_tier = {"https://a.pl/": 5, "https://a.pl/kadra": 0}
    best = _pick_best_staff(staff, ("english_teacher",), url_to_tier)
    assert best.name == "From Kadra Page"


def test_no_matching_role_returns_none():
    staff = [_staff("Someone", "other_staff", "high")]
    assert _pick_best_staff(staff, ("director", "deputy_director"), {}) is None


def test_resolve_email_prefers_llm_pairing_over_structural_fallback():
    record = _staff("Jan Kowalski", "director", "high")
    record = record.model_copy(update={"email": "jan.llm-paired@school.pl"})
    all_emails = ["jan.kowalski@school.pl", "sekretariat@school.pl"]
    # The structural matcher would normally pick jan.kowalski@school.pl
    # (matches the surname) -- LLM pairing must win regardless.
    email = _resolve_email(record, all_emails, "Jan Kowalski")
    assert email == "jan.llm-paired@school.pl"


def test_resolve_email_falls_back_to_structural_match_when_llm_found_none(monkeypatch):
    import levelup.services.enrichment.jobs as jobs_module

    monkeypatch.setattr(
        jobs_module, "is_personal_email_for", lambda email, name: email == "jan.kowalski@school.pl"
    )
    record = _staff("Jan Kowalski", "director", "high")  # email is None
    all_emails = ["jan.kowalski@school.pl", "sekretariat@school.pl"]
    email = _resolve_email(record, all_emails, "Jan Kowalski")
    assert email == "jan.kowalski@school.pl"


def test_resolve_email_with_no_record_at_all_still_uses_structural_fallback(monkeypatch):
    import levelup.services.enrichment.jobs as jobs_module

    monkeypatch.setattr(
        jobs_module, "is_personal_email_for", lambda email, name: email == "regex.match@school.pl"
    )
    all_emails = ["regex.match@school.pl", "other@school.pl"]
    email = _resolve_email(None, all_emails, "Some Name")
    assert email == "regex.match@school.pl"


def test_resolve_email_returns_none_when_nothing_matches(monkeypatch):
    import levelup.services.enrichment.jobs as jobs_module

    monkeypatch.setattr(jobs_module, "is_personal_email_for", lambda email, name: False)
    assert _resolve_email(None, ["a@b.pl"], "Nobody") is None
