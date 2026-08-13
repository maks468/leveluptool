""""Szkoła w Chmurze" (the online-school network) must never enter the
library: user-confirmed exclusion, 2026-08-04."""

from levelup.services.import_service.exclusion_rules import classify, is_online_school


def _row(name):
    return {
        "Czy szkoła": "1",
        "Typ podmiotu": "Liceum ogólnokształcące",
        "Nazwa placówki": name,
        "Kategoria uczniów": "Dzieci lub młodzież",
        "Specyfika szkoły": None,
        "ucz_ogolem": "100",
    }


def test_w_chmurze_branches_are_excluded_in_every_naming_variant():
    for name in (
        'LICEUM OGÓLNOKSZTAŁCĄCE "LICEUM W CHMURZE" W TORUNIU',
        "I LICEUM W CHMURZE",
        "SZKOŁA PODSTAWOWA „SZKOŁA W CHMURZE” W NYSIE",
        "NIEPUBLICZNA SZKOŁA PODSTAWOWA W CHMURZE W WARSZAWIE",
    ):
        assert is_online_school(_row(name)), name
        assert classify(_row(name)) == "exclude_online_school", name


def test_ordinary_schools_are_not_swept_up():
    for name in (
        "LICEUM OGÓLNOKSZTAŁCĄCE IM. JANA KOCHANOWSKIEGO W CHEŁMIE",
        "SZKOŁA PODSTAWOWA NR 5 W CHMIELNIKU",  # city starts with 'Chm' but isn't the brand
    ):
        assert not is_online_school(_row(name)), name
        assert classify(_row(name)) == "import", name
