"""A different person may only take a contact slot by proving more.

Measured on a 100-school re-run of schools that already had a named English
teacher: 19% came back with a DIFFERENT teacher and not one of them gained
an email. Both names were legitimately grounded -- a school with eight
English teachers just yields whichever one that crawl happened to reach.

The churn is not neutral. These names are exported with their Polish
declensions into prepared outreach, so a silent swap invalidates campaign
data and buys nothing. Replacement now requires strictly better evidence:
an address where there was none, higher confidence, or a grounded quote
displacing a row that never had one.
"""

import pytest

from levelup.services.enrichment.jobs import _supersedes


class Row:
    """Stand-in for the stored SchoolContact row."""

    def __init__(self, email=None, confidence=None, extraction_method=None, person_name="Anna Kowalska"):
        self.email = email
        self.confidence = confidence
        self.extraction_method = extraction_method
        self.person_name = person_name


def test_equal_evidence_leaves_the_incumbent_alone():
    incumbent = Row(confidence="high", extraction_method="llm_text")
    assert not _supersedes(
        challenger_email=None,
        challenger_confidence="high",
        challenger_method="llm_text",
        incumbent=incumbent,
    )


def test_an_address_wins_the_slot():
    # The entire point of the contact -- a reachable person beats a name.
    incumbent = Row(confidence="high", extraction_method="llm_text")
    assert _supersedes(
        challenger_email="a.nowak@szkola.pl",
        challenger_confidence="high",
        challenger_method="llm_text",
        incumbent=incumbent,
    )


def test_a_contactable_person_is_never_traded_for_an_uncontactable_one():
    incumbent = Row(email="k.stored@szkola.pl", confidence="medium", extraction_method="llm_text")
    # Even at HIGHER confidence, a nameless-address-less challenger loses.
    assert not _supersedes(
        challenger_email=None,
        challenger_confidence="high",
        challenger_method="llm_text",
        incumbent=incumbent,
    )


def test_higher_confidence_wins_when_neither_has_an_address():
    incumbent = Row(confidence="medium", extraction_method="llm_text")
    assert _supersedes(
        challenger_email=None,
        challenger_confidence="high",
        challenger_method="llm_text",
        incumbent=incumbent,
    )


def test_lower_confidence_never_wins():
    incumbent = Row(confidence="high", extraction_method="llm_text")
    assert not _supersedes(
        challenger_email=None,
        challenger_confidence="medium",
        challenger_method="llm_text",
        incumbent=incumbent,
    )


@pytest.mark.parametrize("weak_method", ["rspo", "regex", None])
def test_a_grounded_quote_displaces_an_ungrounded_row(weak_method):
    # The legitimate upgrade the old blind replacement existed for: a
    # registry-supplied or pre-overhaul name giving way to a real quote.
    incumbent = Row(confidence="high", extraction_method=weak_method)
    assert _supersedes(
        challenger_email=None,
        challenger_confidence="high",
        challenger_method="llm_text",
        incumbent=incumbent,
    )


def test_a_grounded_row_is_not_displaced_by_an_ungrounded_one():
    incumbent = Row(confidence="high", extraction_method="llm_text")
    assert not _supersedes(
        challenger_email=None,
        challenger_confidence="high",
        challenger_method="rspo",
        incumbent=incumbent,
    )


def test_unknown_confidence_ranks_below_every_known_value():
    incumbent = Row(confidence="low", extraction_method="llm_text")
    assert not _supersedes(
        challenger_email=None,
        challenger_confidence=None,
        challenger_method="llm_text",
        incumbent=incumbent,
    )
    # ...and a known value beats the unknown one.
    assert _supersedes(
        challenger_email=None,
        challenger_confidence="low",
        challenger_method="llm_text",
        incumbent=Row(confidence=None, extraction_method="llm_text"),
    )


def test_a_reordered_name_is_the_same_human_not_a_rival():
    """The churn guard compares people, not strings. Judged literally,
    "Bakiera Patrycja" and its canonical "Patrycja Bakiera" look like two
    different occupants of the slot, so the guard refused the rewrite and
    35 mis-declining names survived their own cleanup re-run."""
    from levelup.services.enrichment.jobs import _same_human

    assert _same_human("Bakiera Patrycja", "Patrycja Bakiera")
    assert _same_human("Bożena Zagórska - Arumińska", "Bożena Zagórska-Arumińska")
    assert _same_human("Aleksandra Kurowska – Susdorf", "Aleksandra Kurowska-Susdorf")
    # Genuinely different people are still different.
    assert not _same_human("Alina Piotrowska", "Joanna Jędrasik")
    assert not _same_human("Anna Kowalska", "Anna Nowak")
    assert not _same_human(None, "Anna Kowalska")


def test_undeliverable_person_addresses_are_not_attached():
    from levelup.services.enrichment.jobs import _resolve_email

    class Rec:
        name = "Maria Wlazlak-Szal"
        email = "m.wlazlak-szal@brzegdolny.edu.p"

    assert _resolve_email(Rec(), [], "Maria Wlazlak-Szal") is None
    assert _resolve_email(None, ["m.wlazlak-szal@brzegdolny.edu.p"], "Maria Wlazlak-Szal") is None
    assert (
        _resolve_email(None, ["m.wlazlak-szal@brzegdolny.edu.pl"], "Maria Wlazlak-Szal")
        == "m.wlazlak-szal@brzegdolny.edu.pl"
    )
