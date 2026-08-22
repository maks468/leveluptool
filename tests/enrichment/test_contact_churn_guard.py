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
