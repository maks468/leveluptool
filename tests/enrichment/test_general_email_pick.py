"""Choosing the general office box on shared multi-school domains.

The SSP 11 Białystok failure: an STO complex hosts a primary school and a
liceum on one site publishing three addresses -- 1slo@ (the liceum's),
ssp11@ (the primary's own), slosto@ (the shared secretariat, and the one
RSPO registers for every school in the complex). The primary school got
the shared box because "ssp11" carried no recognized level code and RSPO
won the hintless tie. The school's own level-coded address must win.
"""

from levelup.services.enrichment.jobs import pick_general_email
from levelup.services.enrichment.verifier import email_level_hint

BIALYSTOK = ["slosto@slosto.biaman.pl", "1slo@slosto.biaman.pl", "ssp11@slosto.biaman.pl"]


def test_new_level_hints_recognize_ssp_and_ordinal_slo():
    assert email_level_hint("ssp11@slosto.biaman.pl") == "primary"
    assert email_level_hint("1slo@slosto.biaman.pl") == "liceum"
    assert email_level_hint("psp2@szkola.pl") == "primary"
    assert email_level_hint("nsp.starysacz@wp.pl") is None  # dot splits the code -- fine
    # No false hints on ordinary words.
    assert email_level_hint("sekretariat@szkola.pl") is None
    assert email_level_hint("oslo@szkola.pl") is None


def test_own_level_coded_box_beats_the_shared_and_sibling_boxes():
    picked = pick_general_email(BIALYSTOK, "primary", "SPOŁECZNA SZKOŁA PODSTAWOWA NR 11 W BIAŁYMSTOKU",
                                rspo_email="slosto@slosto.biaman.pl")
    assert picked == "ssp11@slosto.biaman.pl"
    # The sister liceum on the same domain must pick ITS box.
    picked = pick_general_email(BIALYSTOK, "liceum", "I SPOŁECZNE LICEUM OGÓLNOKSZTAŁCĄCE W BIAŁYMSTOKU",
                                rspo_email="slosto@slosto.biaman.pl")
    assert picked == "1slo@slosto.biaman.pl"


def test_rspo_still_wins_genuinely_hintless_ties():
    picked = pick_general_email(["biuro@szkola.pl", "kontakt@szkola.pl"], "primary",
                                "SZKOŁA PODSTAWOWA W GÓRKACH", rspo_email="kontakt@szkola.pl")
    assert picked == "kontakt@szkola.pl"


def test_wrong_school_number_is_demoted_outright():
    # sp84's box leaking onto sp350's shared platform page can never win --
    # even against a mere recruitment address.
    picked = pick_general_email(["sp84@eduwarszawa.pl", "rekrutacja.sp350@eduwarszawa.pl"], "primary",
                                "SZKOŁA PODSTAWOWA NR 350 IM. ARMII KRAJOWEJ", rspo_email=None)
    assert picked == "rekrutacja.sp350@eduwarszawa.pl"
    # A matching number sails through (leading zeros tolerated).
    picked = pick_general_email(["sp084@eduwarszawa.pl", "biuro@inna.pl"], "primary",
                                "SZKOŁA PODSTAWOWA NR 84", rspo_email=None)
    assert picked == "sp084@eduwarszawa.pl"


def test_empty_candidates_pick_nothing():
    assert pick_general_email([], "primary", "SZKOŁA", None) is None


def test_complex_number_is_not_a_school_number_conflict():
    """"SZKOŁA PODSTAWOWA NR 321" sits inside "Zespół Szkolno-Przedszkolny
    nr 7", whose secretariat address is sekretariat.zsp7@eduwarszawa.pl.
    Read as a school number, that 7 contradicted 321, so the school's real
    office mailbox was demoted below an unlabelled personal address on the
    same domain -- which then became the stored office contact."""
    from levelup.services.enrichment.jobs import pick_general_email

    candidates = ["AKolakowska@eduwarszawa.pl", "sekretariat.zsp7@eduwarszawa.pl"]
    got = pick_general_email(candidates, "PRIMARY", "SZKOŁA PODSTAWOWA NR 321", None)
    assert got == "sekretariat.zsp7@eduwarszawa.pl"


def test_a_bare_conflicting_school_number_is_still_demoted():
    """The rule the strip must not break: sp84@ can never win for nr 350."""
    from levelup.services.enrichment.jobs import pick_general_email

    candidates = ["sp84@wspolna.pl", "sp350@wspolna.pl"]
    got = pick_general_email(candidates, "PRIMARY", "SZKOŁA PODSTAWOWA NR 350", None)
    assert got == "sp350@wspolna.pl"


def test_complex_markers_do_not_swallow_a_real_school_code():
    r"""Stripping "zs\d+" must not also eat a genuine own-number code."""
    from levelup.services.enrichment.jobs import _strip_complex_number

    assert _strip_complex_number("sekretariat.zsp7") == "sekretariat."
    assert _strip_complex_number("zso12.kontakt") == ".kontakt"
    assert _strip_complex_number("sp350") == "sp350"
    assert _strip_complex_number("ssp11") == "ssp11"
