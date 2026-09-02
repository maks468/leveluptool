

def test_both_registers_are_exported_side_by_side():
    """Formal and everyday openers ship as separate columns so a campaign
    picks its tone per audience, not per person."""
    from levelup.services import salutations as s

    cols = dict(zip(s.csv_headers("teacher"), s.csv_values("Anna Kowalska", "teacher")))
    assert cols["teacher_salutation"] == "Szanowna Pani Anno,"
    assert cols["teacher_salutation_casual"] == "Dzień dobry Pani Anno,"

    male = dict(zip(s.csv_headers("teacher"), s.csv_values("Marek Nowak", "teacher")))
    assert male["teacher_salutation"] == "Szanowny Panie Marku,"
    assert male["teacher_salutation_casual"] == "Dzień dobry Panie Marku,"


def test_both_registers_use_the_same_vocative():
    """Switching tone must never change how a name is inflected."""
    from levelup.services import salutations as s

    for name in ("Katarzyna Duda-Wójcik", "Bartłomiej Dominik", "Agnieszka Zgierska"):
        cols = dict(zip(s.csv_headers("teacher"), s.csv_values(name, "teacher")))
        formal = cols["teacher_salutation"].rstrip(",").split()[-1]
        casual = cols["teacher_salutation_casual"].rstrip(",").split()[-1]
        assert formal == casual, (name, formal, casual)


def test_the_casual_director_form_greets_the_person_by_first_name():
    from levelup.services import salutations as s

    female = dict(zip(s.csv_headers("director"), s.csv_values("Agnieszka Iłendo", "director")))
    assert female["director_salutation_casual"] == "Dzień dobry Pani Agnieszko,"
    male = dict(zip(s.csv_headers("director"), s.csv_values("Paweł Wójcik", "director")))
    assert male["director_salutation_casual"] == "Dzień dobry Panie Pawle,"

    # A director with no usable first name keeps the TITLE form -- for this
    # one role it reads better than a bare "Dzień dobry Panie,".
    nameless = dict(zip(s.csv_headers("director"), s.csv_values("Iłendo", "director")))
    assert nameless["director_salutation_casual"] in ("Dzień dobry Pani Dyrektor,", "Dzień dobry,")


def test_a_nameless_row_falls_back_to_the_bare_greeting():
    """"Dzień dobry Panie," on its own reads as an unfinished sentence, so
    a row with no usable first name gets the plain greeting instead."""
    from levelup.services import salutations as s

    for name in ("Kirk Palmer", "Baranowska-Piasek", None, ""):
        cols = dict(zip(s.csv_headers("teacher"), s.csv_values(name, "teacher")))
        assert cols["teacher_salutation_casual"] == "Dzień dobry,", name


def test_every_person_column_is_present_for_every_row():
    """Headers and values are built from one ordering, so all three CSV
    exports stay column-identical."""
    from levelup.services import salutations as s

    assert "salutation_casual" in s.PERSON_COLUMN_ORDER
    for name in ("Anna Kowalska", "Kirk Palmer", None):
        assert len(s.csv_values(name, "teacher")) == len(s.csv_headers("teacher"))
