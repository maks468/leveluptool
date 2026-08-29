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


def test_one_persons_mailbox_never_wins_the_office_slot():
    """Two real regressions: "i.kurowska@zsp1mm.pl" beat the school's own
    "zsp1mm@zsp1mm.pl" on a tie, and "AKolakowska@eduwarszawa.pl" beat
    "sekretariat.zsp7@eduwarszawa.pl" outright. Outreach for those schools
    would have landed in one teacher's personal inbox."""
    from levelup.services.enrichment.jobs import pick_general_email

    assert pick_general_email(
        ["i.kurowska@zsp1mm.pl", "zsp1mm@zsp1mm.pl"], "PRIMARY",
        "ZESPÓŁ SZKOLNO-PRZEDSZKOLNY NR 1", None,
    ) == "zsp1mm@zsp1mm.pl"
    assert pick_general_email(
        ["AKolakowska@eduwarszawa.pl", "sekretariat.zsp7@eduwarszawa.pl"], "PRIMARY",
        "SZKOŁA PODSTAWOWA NR 321", None,
    ) == "sekretariat.zsp7@eduwarszawa.pl"


def test_school_abbreviation_plus_city_is_not_a_personal_mailbox():
    """<word>.<word> is ALSO the shape of a real office box. Demoting these
    would throw away correct addresses to fix nothing."""
    from levelup.services.enrichment.jobs import _looks_like_one_persons_mailbox as personal

    for office in (
        "nsp.lubsko@wp.pl", "ksp.mlociny@fnrr.pl", "ssp.zary@op.pl",
        "technikum.gdansk@teb-edukacja.pl", "szk.nazaretanek@o2.pl",
        "sekretariat.zsp7@eduwarszawa.pl", "edukacja.domowa@montessori.gda.pl",
    ):
        assert not personal(office), office
    for private in ("i.kurowska@zsp1mm.pl", "a.hermann@x.pl", "adam.orlikowski@legia.pl"):
        assert personal(private), private


def test_an_undeliverable_address_is_not_chosen():
    """Three stored addresses ended in a one-letter TLD, e.g.
    "biuro@zoltylatawiec.p" -- nothing can be sent to them."""
    from levelup.services.enrichment.jobs import pick_general_email

    got = pick_general_email(
        ["biuro@zoltylatawiec.p", "fundacja@zoltylatawiec.pl"], "PRIMARY", "SZKOŁA", None
    )
    assert got == "fundacja@zoltylatawiec.pl"


def test_an_undeliverable_only_candidate_is_still_returned_over_nothing():
    """The filter must not empty the candidate list -- a malformed address
    is still the only lead a human could correct."""
    from levelup.services.enrichment.jobs import pick_general_email

    assert pick_general_email(["biuro@zoltylatawiec.p"], "PRIMARY", "SZKOŁA", None) == "biuro@zoltylatawiec.p"


def test_a_multi_campus_group_email_matches_the_schools_own_campus():
    """TE VIZJA is one domain (tevizja.pl) with per-campus office boxes
    (wawer@, mokotow@, ochota@, gdansk@) plus a central centrum@. The
    picker saw them as tied and chose arbitrarily -- a Wola primary got
    mokotow@, a different campus. Now a school whose district matches a
    campus box gets it; one with no matching campus falls back to the HQ
    box, never to some OTHER campus."""
    from levelup.services.enrichment.jobs import pick_general_email

    emails = ["centrum@tevizja.pl", "gdansk@tevizja.pl", "mokotow@tevizja.pl",
              "ochota@tevizja.pl", "wawer@tevizja.pl", "przedszkole@tevizja.pl"]

    # A Wawer school gets its own campus box.
    assert pick_general_email(emails, "PRIMARY", "SP TE VIZJA", None, ["wawer"]) == "wawer@tevizja.pl"
    # A Wola school -- no wola@ box exists -- gets the HQ box, NOT another campus.
    assert pick_general_email(emails, "PRIMARY", "SP TE VIZJA", None, ["wola", "okopowa"]) == "centrum@tevizja.pl"
    # A Włochy school likewise falls back to HQ, never to mokotow@/ochota@.
    got = pick_general_email(emails, "LICEUM", "LO TE VIZJA", None, ["wlochy"])
    assert got == "centrum@tevizja.pl"


def test_location_awareness_does_not_disturb_a_single_school_email():
    """The common case -- one ordinary school, one office box -- must be
    unaffected whether or not a location is supplied."""
    from levelup.services.enrichment.jobs import pick_general_email

    assert pick_general_email(["sekretariat@sp7.gizycko.pl"], "PRIMARY", "SP NR 7", None, ["gizycko"]) \
        == "sekretariat@sp7.gizycko.pl"
    assert pick_general_email(["sekretariat@sp7.gizycko.pl"], "PRIMARY", "SP NR 7", None, None) \
        == "sekretariat@sp7.gizycko.pl"


def test_an_office_box_on_the_schools_own_domain_beats_a_siblings():
    """A crawl that touches a sibling institution's page picks up that
    sibling's office box -- one school on plomien.edu.pl was stored with
    info@wegielek.edu.pl, the Węgiełek institution's inbox. With the
    school's own domain known, an own-domain candidate must win; the
    Polish public suffixes (.edu.pl) must not collapse both to "edu.pl"."""
    from levelup.services.enrichment.jobs import pick_general_email

    got = pick_general_email(
        ["info@wegielek.edu.pl", "sekretariat@plomien.edu.pl"],
        "PRIMARY", "SP DLA DZIEWCZĄT PŁOMIEŃ", None, None, "plomien.edu.pl",
    )
    assert got == "sekretariat@plomien.edu.pl"
    # Preference, not veto: with no own-domain candidate, off-domain still wins.
    assert pick_general_email(
        ["info@wegielek.edu.pl"], "PRIMARY", "SP PŁOMIEŃ", None, None, "plomien.edu.pl"
    ) == "info@wegielek.edu.pl"
    # Campus match still outranks plain domain match on a shared domain.
    assert pick_general_email(
        ["centrum@tevizja.pl", "wawer@tevizja.pl"], "LICEUM", "LO TE VIZJA",
        None, ["wawer"], "tevizja.pl",
    ) == "wawer@tevizja.pl"
