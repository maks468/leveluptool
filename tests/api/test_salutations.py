"""Polish salutation/declension module -- the use-case matrix and the
linguistic traps.

Every expected string here was written (and should only ever be edited)
by checking the actual Polish, not the code -- these tests are the
grammar's source of truth. The five scenarios from the feature spec:
teacher direct, teacher indirect, director direct, director indirect,
and no name at all.
"""

from levelup.services.salutations import (
    SECRETARIAT_SALUTATION,
    csv_headers,
    csv_values,
    person_csv_columns,
)


def cols(name, role="teacher"):
    return person_csv_columns(name, role)


# --- the five use cases ------------------------------------------------------

def test_teacher_direct_email_salutation():
    assert cols("Agata Bień")["salutation"] == "Szanowna Pani Agato,"
    assert cols("Piotr Nowak")["salutation"] == "Szanowny Panie Piotrze,"


def test_teacher_indirect_via_secretariat():
    c = cols("Anna Kobyłko")
    assert c["ref_inst"] == "Panią Anną Kobyłko"       # skontaktować się z ...
    assert c["ref_gen"] == "Pani Anny Kobyłko"         # do / w sprawie ...
    assert c["ref_dat"] == "Pani Annie Kobyłko"        # przekazać ...
    assert c["ref_acc"] == "Panią Annę Kobyłko"        # prosić / zapytać o ...
    assert c["ref_quality"] == "full"
    assert SECRETARIAT_SALUTATION == "Dzień dobry,"


def test_director_direct_uses_title_not_name():
    assert cols("Izabela Piaskowska", "director")["salutation"] == "Szanowna Pani Dyrektor,"
    assert cols("Marek Zieliński", "director")["salutation"] == "Szanowny Panie Dyrektorze,"


def test_director_indirect_full_declension():
    c = cols("Marek Zieliński", "director")
    assert c["ref_inst"] == "Panem Markiem Zielińskim"
    assert c["ref_gen"] == "Pana Marka Zielińskiego"
    assert c["ref_dat"] == "Panu Markowi Zielińskiemu"
    assert c["subject_ref"] == "dla Pana Zielińskiego"


def test_no_name_at_all_gets_safe_role_phrases():
    teacher, director = cols(None), cols("", "director")
    assert teacher["ref_quality"] == director["ref_quality"] == "role_only"
    assert teacher["ref_inst"] == "nauczycielem języka angielskiego"
    assert director["ref_inst"] == "dyrekcją szkoły"
    assert teacher["salutation"] == "Dzień dobry,"
    assert director["salutation"] == "Szanowni Państwo,"
    assert teacher["gender"] == "" and teacher["first_name"] == ""


# --- declension traps --------------------------------------------------------

def test_female_surnames_decline_only_when_adjectival():
    # -ska declines...
    assert cols("Izabela Piaskowska")["ref_gen"] == "Pani Izabeli Piaskowskiej"
    # ...everything else stays frozen -- the user's own canonical example.
    assert cols("Anna Kobyłko")["ref_inst"] == "Panią Anną Kobyłko"
    assert cols("Agata Bień")["ref_dat"] == "Pani Agacie Bień"


def test_female_first_name_alternations():
    assert cols("Małgorzata Nowak")["ref_dat"] == "Pani Małgorzacie Nowak"   # t→cie
    assert cols("Agnieszka Nowak")["ref_dat"] == "Pani Agnieszce Nowak"      # k→ce
    assert cols("Barbara Nowak")["ref_dat"] == "Pani Barbarze Nowak"         # r→rze
    assert cols("Maria Nowak")["ref_gen"] == "Pani Marii Nowak"              # -ia→-ii
    assert cols("Alicja Nowak")["ref_dat"] == "Pani Alicji Nowak"            # -ja→-ji
    assert cols("Kasia Nowak")["salutation"] == "Szanowna Pani Kasiu,"       # -sia→-siu


def test_male_surname_classes():
    assert cols("Jan Kowalski")["ref_inst"] == "Panem Janem Kowalskim"       # adjectival
    assert cols("Piotr Nowak")["ref_loc"] == "Panu Piotrze Nowaku"           # k→loc -u
    assert cols("Adam Malec")["ref_gen"] == "Pana Adama Malca"               # -ec e-drop
    assert cols("Jan Zaręba")["ref_inst"] == "Panem Janem Zarębą"            # -a noun-style
    assert cols("Jan Gołąb")["ref_gen"] == "Pana Jana Gołębia"               # exception table


def test_risky_male_surname_degrades_not_guesses():
    c = cols("Piotr Wróbelór")  # fabricated ó-stem not in the exception table
    assert c["ref_quality"] == "first_name_only"
    assert c["ref_inst"] == "Panem Piotrem Wróbelór"  # declined first name, frozen surname


def test_hyphenated_female_surname_declines_partwise():
    c = cols("Anna Kowalska-Nowak")
    assert c["ref_inst"] == "Panią Anną Kowalską-Nowak"
    assert c["ref_gen"] == "Pani Anny Kowalskiej-Nowak"


# --- hygiene and fallbacks ---------------------------------------------------

def test_titles_are_stripped():
    c = cols("mgr Anna Kobyłko")
    assert c["first_name"] == "Anna" and c["ref_quality"] == "full"
    assert cols("dr hab. Piotr Nowak")["first_name"] == "Piotr"


def test_known_foreign_names_get_pan_pani_with_the_name_frozen():
    """The user's rule for foreign names: establish gender, decline ONLY
    Pan/Pani, leave the name untouched -- standard Polish treatment."""
    kirk = cols("Kirk Palmer")
    assert kirk["ref_quality"] == "undeclined"
    assert kirk["gender"] == "male"
    assert kirk["ref_inst"] == "Panem Kirk Palmer"
    assert kirk["ref_gen"] == "Pana Kirk Palmer"
    assert kirk["salutation"] == "Szanowny Panie,"
    assert kirk["subject_ref"] == "dla Pana Palmer"

    bronwen = cols("Bronwen Hughes")
    assert bronwen["ref_quality"] == "undeclined"
    assert bronwen["ref_inst"] == "Panią Bronwen Hughes"
    assert bronwen["salutation"] == "Szanowna Pani,"

    # Single foreign token still works.
    assert cols("Christopher")["ref_inst"] == "Panem Christopher"


def test_ambiguous_or_unparseable_names_still_degrade_to_role():
    # "Bienn" isn't in any table -- gender stays unknown, never guessed.
    for name in ("Bienn Marie Bautista", "Baranowska-Piasek", "Fiedorowicz"):
        c = cols(name)
        assert c["ref_quality"] == "role_only", name
        assert c["gender"] == "", name


def test_surname_first_ordering_is_swapped_on_positive_proof():
    """"Grochowalska Agnieszka" (real scraped shape) must resolve as
    Agnieszka Grochowalska -- but only when the last token is a
    recognized first name; two ambiguous tokens still degrade."""
    c = cols("Grochowalska Agnieszka")
    assert c["ref_quality"] == "full"
    assert c["ref_inst"] == "Panią Agnieszką Grochowalską"
    assert cols("Baranowska-Piasek")["ref_quality"] == "role_only"


def test_modern_male_names_added_from_campaign_gaps():
    assert cols("Mikołaj Rudnicki")["ref_dat"] == "Panu Mikołajowi Rudnickiemu"
    assert cols("Kacper Kłosowicz")["ref_inst"] == "Panem Kacprem Kłosowiczem"
    assert cols("Kacper Kłosowicz")["salutation"] == "Szanowny Panie Kacprze,"


def test_single_token_known_first_name():
    c = cols("Agata")
    assert c["ref_quality"] == "first_name_only"
    assert c["ref_inst"] == "Panią Agatą"
    assert c["subject_ref"] == "dla Pani Agaty"


def test_ukrainian_name_in_foreign_table_goes_undeclined():
    c = cols("Dmytro Kovalenko")
    assert c["ref_quality"] == "undeclined"
    assert c["ref_dat"] == "Panu Dmytro Kovalenko"


def test_csv_helpers_stay_aligned():
    headers = csv_headers("teacher")
    values = csv_values("Agata Bień", "teacher")
    assert len(headers) == len(values) == 12
    assert headers[0] == "teacher_gender"
    assert dict(zip(headers, values))["teacher_ref_inst"] == "Panią Agatą Bień"
