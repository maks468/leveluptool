"""A greeting must never name someone other than the inbox it is sent to.

Real incident: the campaign CSV emitted ONE "best_email" column beside the
teacher's name and the teacher's salutations, with nothing indicating whose
address it was. At "partial" enrichment level a teacher is NAMED but has no
address of her own, so best_email falls back to the office -- or to the
director's personal box. Merged against a letter opening "Dzien dobry Pani
Anno", every such row sent a message addressed to the teacher into somebody
else's inbox. All 249 rows of the "SP Partial Score 60+" campaign were this
shape; one addressed teacher Elzbieta Felicka-Okrzesik at
dyrektor@katolicka.edu.pl.

The fix removes the possibility rather than documenting it: the owner
travels with the address, and the greeting is derived from the OWNER.
"""

from levelup.api.v1.schools import CONTACT_TYPE_TO_OWNER
from levelup.services import salutations


def test_greeting_follows_the_owner_of_the_address_not_the_named_teacher():
    # A school with a named teacher but only an office mailbox: the letter
    # must NOT open with the teacher's name.
    cols = salutations.recipient_columns("office", "Anna Kowalska", "Beata Nowak")
    salutation, casual, who = cols
    assert who == "office"
    assert "Anna" not in salutation and "Anna" not in casual
    assert salutation == salutations.SECRETARIAT_SALUTATION


def test_the_teachers_own_address_does_get_her_name():
    salutation, casual, who = salutations.recipient_columns("teacher", "Anna Kowalska", "Beata Nowak")
    assert who == "teacher"
    assert salutation == "Szanowna Pani Anno,"
    assert casual == "Dzień dobry Pani Anno,"


def test_a_directors_address_gets_the_director_never_the_teacher():
    salutation, casual, who = salutations.recipient_columns("director", "Anna Kowalska", "Marek Nowak")
    assert who == "director"
    assert "Anno" not in salutation, "the teacher's name must not reach the director's inbox"
    assert "Dyrektor" in salutation


def test_no_address_at_all_degrades_to_the_impersonal_opener():
    salutation, casual, who = salutations.recipient_columns(None, None, None)
    assert who == "none"
    assert salutation == salutations.SECRETARIAT_SALUTATION


def test_owner_mapping_covers_every_contact_type_the_resolver_can_return():
    assert CONTACT_TYPE_TO_OWNER == {
        "english_coordinator": "teacher",
        "director": "director",
        "general": "office",
    }


def test_a_named_teacher_without_her_own_address_is_never_marked_directly_emailable():
    """The column a teacher-addressed template must filter on."""
    for owner in ("office", "director", None):
        _, _, who = salutations.recipient_columns(owner, "Anna Kowalska", "Beata Nowak")
        assert who != "teacher"
