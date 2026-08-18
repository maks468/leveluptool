"""Two real leaks the user caught in production exports, pinned forever.

1. SP 190: "rzarzeczna.iod@dbfomokotow.pl" -- a named data-protection
   officer at the DISTRICT bureau -- was stored as the school's contact
   because the RODO check only looked at the local part's PREFIX. An
   address that reaches anyone other than the school must never be kept:
   blank beats a misleading contact.

2. SP 350: "EMiecznikowska@eduwarszawa.pl" -- the director's own address
   in the very common concatenated initial+surname format -- could never
   be attributed to her because structural verification demanded
   separator-split tokens, so the school graded partial with the priority
   email already in hand.
"""

from levelup.services.enrichment.verifier import (
    classify_contact_quality,
    is_data_protection_email,
    is_non_school_email,
    is_personal_email_for,
)


def test_data_protection_marker_is_caught_in_any_token_position():
    # The exact leaked address: marker at the END.
    assert is_data_protection_email("rzarzeczna.iod@dbfomokotow.pl")
    assert is_non_school_email("rzarzeczna.iod@dbfomokotow.pl")
    # Other positions and separators.
    assert is_data_protection_email("iod.kowalski@szkola.pl")
    assert is_data_protection_email("jan-rodo@szkola.pl")
    assert is_data_protection_email("dane.osobowe@szkola.pl")  # prefix path still works


def test_marker_inside_a_surname_is_not_a_marker():
    # Token EQUALITY, not substring -- surnames merely containing the
    # letters must survive.
    assert not is_data_protection_email("j.miodek@szkola.pl")      # "iod" inside "miodek"
    assert not is_data_protection_email("anna.zabini@szkola.pl")   # "abi" inside "zabini"
    assert not is_data_protection_email("sekretariat@szkola.pl")


def test_concatenated_initial_plus_surname_is_personal():
    # The exact SP 350 shape.
    assert is_personal_email_for("EMiecznikowska@eduwarszawa.pl", "Ewa Miecznikowska")
    assert is_personal_email_for("annakowalska@szkola.pl", "Anna Kowalska")
    assert is_personal_email_for("kowalskaa@szkola.pl", "Anna Kowalska")  # surname+initial
    assert classify_contact_quality("Ewa Miecznikowska", "EMiecznikowska@eduwarszawa.pl") == "verified"


def test_concatenated_form_still_rejects_everyone_else():
    # The same address must NOT verify for a different person...
    assert not is_personal_email_for("EMiecznikowska@eduwarszawa.pl", "Małgorzata Martynowicz")
    # ...an institutional word never matches (the original ATUT lesson)...
    assert not is_personal_email_for("atut@fem.org.pl", "Anna Tutko")
    # ...and a short surname can't produce accidental matches.
    assert not is_personal_email_for("abak@szkola.pl", "Adam Bak")
