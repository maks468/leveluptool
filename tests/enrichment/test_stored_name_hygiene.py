"""Names are canonicalised before storage, because the export declines them.

Both shapes below came out of a 500-school re-run and both produce
embarrassing Polish in a real letter, which is the whole point of the
declension engine:

  * "Bakiera Patrycja" -- surname first. Female first names are recognised
    by the "-a" ending rule, so an -a SURNAME also looks like a first name;
    the export declined the surname as the given name and addressed the
    teacher as "Szanowna Pani Bakiero".
  * "Bożena Zagórska - Arumińska" and "Aleksandra Kurowska – Susdorf" --
    a double-barrelled surname written with spaces or an en dash. Split on
    whitespace, only the last token counted as the surname, so the first
    half was silently dropped ("Pani Bożenie Arumińskiej").
"""

from levelup.services import salutations
from levelup.services.enrichment.jobs import _clean_person_name


def _cols(name):
    return dict(zip(salutations.csv_headers("teacher"), salutations.csv_values(name, "teacher")))


def test_surname_first_is_reordered_before_storage():
    assert _clean_person_name("Bakiera Patrycja") == "Patrycja Bakiera"
    cols = _cols(_clean_person_name("Bakiera Patrycja"))
    assert cols["teacher_salutation"] == "Szanowna Pani Patrycjo,"
    assert cols["teacher_ref_dat"].startswith("Pani Patrycji")


def test_spaced_and_en_dashed_surnames_keep_both_halves():
    assert _clean_person_name("Bożena Zagórska - Arumińska") == "Bożena Zagórska-Arumińska"
    assert _clean_person_name("Aleksandra Kurowska – Susdorf") == "Aleksandra Kurowska-Susdorf"
    dat = _cols("Bożena Zagórska - Arumińska")["teacher_ref_dat"]
    assert "Zagórskiej" in dat and "Arumińskiej" in dat, dat


def test_already_correct_names_are_left_alone():
    for name in (
        "Patrycja Bakiera",
        "Anna Dobrzyńska-Wojciechowska",
        "Bartłomiej Dominik",
        "Purnima Jana",
        "Agata Kumorkiewicz",
    ):
        assert _clean_person_name(name) == name


def test_a_consonant_surname_written_first_is_also_reordered():
    # The old shape test only knew Polish surname suffixes (-ska/-cki/...),
    # so it could not see "Nowak Jan" either.
    assert _clean_person_name("Nowak Jan") == "Jan Nowak"


def test_ambiguous_pairs_are_never_guessed_at():
    # A lone hyphenated surname must degrade, not be read as a first name.
    cols = _cols("Baranowska-Piasek")
    assert cols["teacher_ref_quality"] == "role_only"
    assert cols["teacher_salutation"] == "Dzień dobry,"


def test_blank_and_none_survive():
    assert _clean_person_name(None) is None
    assert _clean_person_name("") == ""


def test_a_forename_that_is_also_a_surname_is_not_swapped():
    """"Judyta Miłosz" is correct as written. Miłosz is on the first-name
    list and Judyta was not, so the reorder fired and produced "Miłosz
    Judyta" -- which the export addresses as "Szanowny Panie Miłoszu":
    wrong name and wrong gender. A wrong swap is worse than a missed one,
    so the first-token short-circuit has to know the broader name stock."""
    assert _clean_person_name("Judyta Miłosz") == "Judyta Miłosz"
    cols = _cols("Judyta Miłosz")
    assert cols["teacher_gender"] == "female"
    assert cols["teacher_salutation"] == "Szanowna Pani Judyto,"


def test_the_names_added_to_close_that_gap_all_short_circuit():
    # Each of these, written FIRST, must stop the reorder.
    for first in ("Aneta", "Martyna", "Sandra", "Żaneta", "Wiktoria", "Kajetan", "Olaf"):
        assert _clean_person_name(f"{first} Miłosz") == f"{first} Miłosz"


def test_genuine_surname_first_still_reorders_after_the_additions():
    for stored, want in (
        ("Zimirska Agnieszka", "Agnieszka Zimirska"),
        ("Grochowalska Agnieszka", "Agnieszka Grochowalska"),
        ("Baranowska-Piasek Monika", "Monika Baranowska-Piasek"),
        ("Bakiera Patrycja", "Patrycja Bakiera"),
    ):
        assert _clean_person_name(stored) == want
