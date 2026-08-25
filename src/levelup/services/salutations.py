"""Polish salutations and declension (odmiana) for CSV exports.

Turns a scraped person name ("mgr Anna Kobyłko") into everything an
outbound email tool needs to write grammatical Polish about that person:
gender, a direct-address salutation (wołacz), and ready referring phrases
in five cases with Pan/Pani baked in ("z Panią Anną Kobyłko",
"do Pana Piotra Nowaka"). Lives ONLY in the CSV export path -- nothing is
stored and nothing shows in the UI.

The contract mirrors enrichment's own: a wrong form is worse than a safe
one, so every uncertainty degrades down an explicit ladder instead of
guessing:

    full            -- Pan/Pani + first name + surname, all declined
    first_name_only -- Pan/Pani + first name declined; surname frozen in
                       nominative (common and acceptable in official mail)
                       -- also used when there is no surname at all
    undeclined      -- gender IS known (curated foreign-name table, or a
                       female -a name whose declension isn't safe) but the
                       name itself stays frozen: "z Panem Kirk Palmer" --
                       standard Polish treatment of foreign names
    role_only       -- no usable name: role phrases ("z nauczycielem
                       języka angielskiego", "z Panią Dyrektor",
                       "z dyrekcją szkoły")

Design notes, informed by an audit of the real database (8,886 name
instances, 329 distinct first names):
- FEMALE first names are almost perfectly regular (-a), so they are
  declined by rule with a consonant-alternation map; no table needed.
- MALE first names are irregular enough that only a curated table is
  trusted; a male name outside the table degrades to role_only. The
  table below covers every male name seen in the data plus the common
  national stock.
- Gender comes from the male table, a small female-exceptions set, then
  the "-a means female" rule (zero male -a names exist in the data; the
  known male exceptions are listed anyway). Anything else -- foreign
  names like Bronwen or Graham -- stays unknown and degrades, because a
  misgendered email is the one output this module must never produce.
"""

from __future__ import annotations

import re

# ---------------------------------------------------------------------------
# Name hygiene
# ---------------------------------------------------------------------------

# Honorifics seen in scraped names; stripped repeatedly ("dr hab. prof. ...").
_TITLE_RE = re.compile(
    r"^(mgr|dr|prof\.?|in[żz]\.?|hab\.?|lic\.?|ks\.?|s\.|o\.)\s+", re.IGNORECASE
)

# A "first name" that is actually a surname that slipped into first
# position ("Baranowska-Piasek Anna", bare "Fiedorowicz") -- seen in the
# audit. Any of these shapes means the name can't be trusted as parsed.
_SURNAME_SHAPED_RE = re.compile(
    r"(ska|cka|dzka|ski|cki|dzki|owicz|ewicz|ów)$", re.IGNORECASE
)


def _clean(full_name: str) -> list[str]:
    name = re.sub(r"\s+", " ", (full_name or "").strip())
    # A double-barrelled surname written with spaces or an en/em dash around
    # the join is ONE surname. Split on whitespace it became a separate
    # token, and since only parts[-1] is treated as the surname the first
    # half was silently dropped: "Bożena Zagórska - Arumińska" declined to
    # "Pani Bożenie Arumińskiej", losing Zagórska, and "Aleksandra Kurowska
    # – Susdorf" lost Kurowska. Both are real scraped names. Normalized to a
    # plain hyphen here so the existing part-wise hyphen handling applies.
    name = re.sub(r"\s*[-‐-―]\s*", "-", name)
    while _TITLE_RE.match(name):
        name = _TITLE_RE.sub("", name, count=1)
    return [p for p in name.split(" ") if p]


# ---------------------------------------------------------------------------
# Gender + first-name declension
# ---------------------------------------------------------------------------

# Male first names with all six forms: gen, dat, acc, inst, loc, voc.
# Curated by hand -- male paradigms are too irregular for rules (Piotr→
# Piotrze but Marek→Marku; Paweł→Pawle drops the ł's e). Covers every male
# name in the audited data plus the common national stock.
_MALE_FIRST = {
    "Adam": ("Adama", "Adamowi", "Adama", "Adamem", "Adamie", "Adamie"),
    "Adrian": ("Adriana", "Adrianowi", "Adriana", "Adrianem", "Adrianie", "Adrianie"),
    "Albert": ("Alberta", "Albertowi", "Alberta", "Albertem", "Albercie", "Albercie"),
    "Aleksander": ("Aleksandra", "Aleksandrowi", "Aleksandra", "Aleksandrem", "Aleksandrze", "Aleksandrze"),
    "Alfred": ("Alfreda", "Alfredowi", "Alfreda", "Alfredem", "Alfredzie", "Alfredzie"),
    "Andrzej": ("Andrzeja", "Andrzejowi", "Andrzeja", "Andrzejem", "Andrzeju", "Andrzeju"),
    "Antoni": ("Antoniego", "Antoniemu", "Antoniego", "Antonim", "Antonim", "Antoni"),
    "Arkadiusz": ("Arkadiusza", "Arkadiuszowi", "Arkadiusza", "Arkadiuszem", "Arkadiuszu", "Arkadiuszu"),
    "Artur": ("Artura", "Arturowi", "Artura", "Arturem", "Arturze", "Arturze"),
    "Bartosz": ("Bartosza", "Bartoszowi", "Bartosza", "Bartoszem", "Bartoszu", "Bartoszu"),
    "Bartłomiej": ("Bartłomieja", "Bartłomiejowi", "Bartłomieja", "Bartłomiejem", "Bartłomieju", "Bartłomieju"),
    "Bernard": ("Bernarda", "Bernardowi", "Bernarda", "Bernardem", "Bernardzie", "Bernardzie"),
    "Bogdan": ("Bogdana", "Bogdanowi", "Bogdana", "Bogdanem", "Bogdanie", "Bogdanie"),
    "Bogumił": ("Bogumiła", "Bogumiłowi", "Bogumiła", "Bogumiłem", "Bogumile", "Bogumile"),
    "Bogusław": ("Bogusława", "Bogusławowi", "Bogusława", "Bogusławem", "Bogusławie", "Bogusławie"),
    "Bronisław": ("Bronisława", "Bronisławowi", "Bronisława", "Bronisławem", "Bronisławie", "Bronisławie"),
    "Cezary": ("Cezarego", "Cezaremu", "Cezarego", "Cezarym", "Cezarym", "Cezary"),
    "Chrystian": ("Chrystiana", "Chrystianowi", "Chrystiana", "Chrystianem", "Chrystianie", "Chrystianie"),
    "Czesław": ("Czesława", "Czesławowi", "Czesława", "Czesławem", "Czesławie", "Czesławie"),
    "Damian": ("Damiana", "Damianowi", "Damiana", "Damianem", "Damianie", "Damianie"),
    "Daniel": ("Daniela", "Danielowi", "Daniela", "Danielem", "Danielu", "Danielu"),
    "Dariusz": ("Dariusza", "Dariuszowi", "Dariusza", "Dariuszem", "Dariuszu", "Dariuszu"),
    "Dawid": ("Dawida", "Dawidowi", "Dawida", "Dawidem", "Dawidzie", "Dawidzie"),
    "Dominik": ("Dominika", "Dominikowi", "Dominika", "Dominikiem", "Dominiku", "Dominiku"),
    "Edward": ("Edwarda", "Edwardowi", "Edwarda", "Edwardem", "Edwardzie", "Edwardzie"),
    "Emil": ("Emila", "Emilowi", "Emila", "Emilem", "Emilu", "Emilu"),
    "Ernest": ("Ernesta", "Ernestowi", "Ernesta", "Ernestem", "Erneście", "Erneście"),
    "Filip": ("Filipa", "Filipowi", "Filipa", "Filipem", "Filipie", "Filipie"),
    "Florian": ("Floriana", "Florianowi", "Floriana", "Florianem", "Florianie", "Florianie"),
    "Gabriel": ("Gabriela", "Gabrielowi", "Gabriela", "Gabrielem", "Gabrielu", "Gabrielu"),
    "Grzegorz": ("Grzegorza", "Grzegorzowi", "Grzegorza", "Grzegorzem", "Grzegorzu", "Grzegorzu"),
    "Henryk": ("Henryka", "Henrykowi", "Henryka", "Henrykiem", "Henryku", "Henryku"),
    "Hieronim": ("Hieronima", "Hieronimowi", "Hieronima", "Hieronimem", "Hieronimie", "Hieronimie"),
    "Hubert": ("Huberta", "Hubertowi", "Huberta", "Hubertem", "Hubercie", "Hubercie"),
    "Ireneusz": ("Ireneusza", "Ireneuszowi", "Ireneusza", "Ireneuszem", "Ireneuszu", "Ireneuszu"),
    "Iwo": ("Iwona", "Iwonowi", "Iwona", "Iwonem", "Iwonie", "Iwonie"),
    "Jacek": ("Jacka", "Jackowi", "Jacka", "Jackiem", "Jacku", "Jacku"),
    "Jakub": ("Jakuba", "Jakubowi", "Jakuba", "Jakubem", "Jakubie", "Jakubie"),
    "Jan": ("Jana", "Janowi", "Jana", "Janem", "Janie", "Janie"),
    "Kacper": ("Kacpra", "Kacprowi", "Kacpra", "Kacprem", "Kacprze", "Kacprze"),
    "Mikołaj": ("Mikołaja", "Mikołajowi", "Mikołaja", "Mikołajem", "Mikołaju", "Mikołaju"),
    "Oskar": ("Oskara", "Oskarowi", "Oskara", "Oskarem", "Oskarze", "Oskarze"),
    "Igor": ("Igora", "Igorowi", "Igora", "Igorem", "Igorze", "Igorze"),
    "Eryk": ("Eryka", "Erykowi", "Eryka", "Erykiem", "Eryku", "Eryku"),
    "Wiktor": ("Wiktora", "Wiktorowi", "Wiktora", "Wiktorem", "Wiktorze", "Wiktorze"),
    "Miłosz": ("Miłosza", "Miłoszowi", "Miłosza", "Miłoszem", "Miłoszu", "Miłoszu"),
    "Julian": ("Juliana", "Julianowi", "Juliana", "Julianem", "Julianie", "Julianie"),
    "Leon": ("Leona", "Leonowi", "Leona", "Leonem", "Leonie", "Leonie"),
    "Borys": ("Borysa", "Borysowi", "Borysa", "Borysem", "Borysie", "Borysie"),
    "Tymoteusz": ("Tymoteusza", "Tymoteuszowi", "Tymoteusza", "Tymoteuszem", "Tymoteuszu", "Tymoteuszu"),
    "Kajetan": ("Kajetana", "Kajetanowi", "Kajetana", "Kajetanem", "Kajetanie", "Kajetanie"),
    "Fabian": ("Fabiana", "Fabianowi", "Fabiana", "Fabianem", "Fabianie", "Fabianie"),
    "Ksawery": ("Ksawerego", "Ksaweremu", "Ksawerego", "Ksawerym", "Ksawerym", "Ksawery"),
    "Janusz": ("Janusza", "Januszowi", "Janusza", "Januszem", "Januszu", "Januszu"),
    "Jarosław": ("Jarosława", "Jarosławowi", "Jarosława", "Jarosławem", "Jarosławie", "Jarosławie"),
    "Jerzy": ("Jerzego", "Jerzemu", "Jerzego", "Jerzym", "Jerzym", "Jerzy"),
    "Józef": ("Józefa", "Józefowi", "Józefa", "Józefem", "Józefie", "Józefie"),
    "Kamil": ("Kamila", "Kamilowi", "Kamila", "Kamilem", "Kamilu", "Kamilu"),
    "Karol": ("Karola", "Karolowi", "Karola", "Karolem", "Karolu", "Karolu"),
    "Kazimierz": ("Kazimierza", "Kazimierzowi", "Kazimierza", "Kazimierzem", "Kazimierzu", "Kazimierzu"),
    "Konrad": ("Konrada", "Konradowi", "Konrada", "Konradem", "Konradzie", "Konradzie"),
    "Krystian": ("Krystiana", "Krystianowi", "Krystiana", "Krystianem", "Krystianie", "Krystianie"),
    "Krzysztof": ("Krzysztofa", "Krzysztofowi", "Krzysztofa", "Krzysztofem", "Krzysztofie", "Krzysztofie"),
    "Leszek": ("Leszka", "Leszkowi", "Leszka", "Leszkiem", "Leszku", "Leszku"),
    "Lech": ("Lecha", "Lechowi", "Lecha", "Lechem", "Lechu", "Lechu"),
    "Łukasz": ("Łukasza", "Łukaszowi", "Łukasza", "Łukaszem", "Łukaszu", "Łukaszu"),
    "Maciej": ("Macieja", "Maciejowi", "Macieja", "Maciejem", "Macieju", "Macieju"),
    "Marcin": ("Marcina", "Marcinowi", "Marcina", "Marcinem", "Marcinie", "Marcinie"),
    "Marek": ("Marka", "Markowi", "Marka", "Markiem", "Marku", "Marku"),
    "Mariusz": ("Mariusza", "Mariuszowi", "Mariusza", "Mariuszem", "Mariuszu", "Mariuszu"),
    "Mateusz": ("Mateusza", "Mateuszowi", "Mateusza", "Mateuszem", "Mateuszu", "Mateuszu"),
    "Michał": ("Michała", "Michałowi", "Michała", "Michałem", "Michale", "Michale"),
    "Mirosław": ("Mirosława", "Mirosławowi", "Mirosława", "Mirosławem", "Mirosławie", "Mirosławie"),
    "Norbert": ("Norberta", "Norbertowi", "Norberta", "Norbertem", "Norbercie", "Norbercie"),
    "Patryk": ("Patryka", "Patrykowi", "Patryka", "Patrykiem", "Patryku", "Patryku"),
    "Paweł": ("Pawła", "Pawłowi", "Pawła", "Pawłem", "Pawle", "Pawle"),
    "Piotr": ("Piotra", "Piotrowi", "Piotra", "Piotrem", "Piotrze", "Piotrze"),
    "Przemysław": ("Przemysława", "Przemysławowi", "Przemysława", "Przemysławem", "Przemysławie", "Przemysławie"),
    "Radosław": ("Radosława", "Radosławowi", "Radosława", "Radosławem", "Radosławie", "Radosławie"),
    "Rafał": ("Rafała", "Rafałowi", "Rafała", "Rafałem", "Rafale", "Rafale"),
    "Robert": ("Roberta", "Robertowi", "Roberta", "Robertem", "Robercie", "Robercie"),
    "Roman": ("Romana", "Romanowi", "Romana", "Romanem", "Romanie", "Romanie"),
    "Ryszard": ("Ryszarda", "Ryszardowi", "Ryszarda", "Ryszardem", "Ryszardzie", "Ryszardzie"),
    "Sebastian": ("Sebastiana", "Sebastianowi", "Sebastiana", "Sebastianem", "Sebastianie", "Sebastianie"),
    "Sławomir": ("Sławomira", "Sławomirowi", "Sławomira", "Sławomirem", "Sławomirze", "Sławomirze"),
    "Stanisław": ("Stanisława", "Stanisławowi", "Stanisława", "Stanisławem", "Stanisławie", "Stanisławie"),
    "Stefan": ("Stefana", "Stefanowi", "Stefana", "Stefanem", "Stefanie", "Stefanie"),
    "Szymon": ("Szymona", "Szymonowi", "Szymona", "Szymonem", "Szymonie", "Szymonie"),
    "Tadeusz": ("Tadeusza", "Tadeuszowi", "Tadeusza", "Tadeuszem", "Tadeuszu", "Tadeuszu"),
    "Tomasz": ("Tomasza", "Tomaszowi", "Tomasza", "Tomaszem", "Tomaszu", "Tomaszu"),
    "Waldemar": ("Waldemara", "Waldemarowi", "Waldemara", "Waldemarem", "Waldemarze", "Waldemarze"),
    "Wiesław": ("Wiesława", "Wiesławowi", "Wiesława", "Wiesławem", "Wiesławie", "Wiesławie"),
    "Witold": ("Witolda", "Witoldowi", "Witolda", "Witoldem", "Witoldzie", "Witoldzie"),
    "Wojciech": ("Wojciecha", "Wojciechowi", "Wojciecha", "Wojciechem", "Wojciechu", "Wojciechu"),
    "Zbigniew": ("Zbigniewa", "Zbigniewowi", "Zbigniewa", "Zbigniewem", "Zbigniewie", "Zbigniewie"),
    "Zdzisław": ("Zdzisława", "Zdzisławowi", "Zdzisława", "Zdzisławem", "Zdzisławie", "Zdzisławie"),
    "Zygmunt": ("Zygmunta", "Zygmuntowi", "Zygmunta", "Zygmuntem", "Zygmuncie", "Zygmuncie"),
}

# Male names ending in -a (none in the audited data, kept as a tripwire so
# the "-a means female" rule can never misfire on the classics).
_MALE_A_NAMES = {"Kuba", "Barnaba", "Kosma", "Bonawentura", "Dyzma", "Jarema"}

# Foreign first names with unambiguous gender -- these get Pan/Pani with
# the NAME LEFT ENTIRELY UNDECLINED ("z Panem Kirk Palmer"), the standard
# Polish treatment of foreign names. Curated conservatively: a name that
# could go either way (Bienn, Sam, Alex, Robin) does NOT belong here --
# unknown degrades to role phrases, which beats a misgendered email.
# Seeded from names actually observed in the database plus common
# English/Ukrainian/Arabic stock.
_FOREIGN_MALE = {
    "Kirk", "Benjamin", "Christopher", "Graham", "Andrew", "Eric", "Dan",
    "Daniel", "David", "James", "John", "Michael", "Peter", "Paul", "Mark",
    "Thomas", "Steven", "Kevin", "Brian", "Ian", "Oliver", "Liam", "Jack",
    "Harry", "George", "William", "Richard", "Matthew", "Alexander",
    "Dmytro", "Oleh", "Oleksandr", "Serhii", "Andrii", "Volodymyr", "Ihor",
    "Vasyl", "Taras", "Mahfoudh", "Mohammed", "Muhammad", "Ahmed", "Ali",
    "Omar", "Youssef", "Hassan",
}
_FOREIGN_FEMALE = {
    "Angelique", "Bronwen", "Jennifer", "Jessica", "Sarah", "Emily",
    "Sophie", "Kate", "Mary", "Elizabeth", "Nicole", "Charlotte", "Marie",
    "Ruth", "Ingrid", "Carmen", "Rachel", "Hannah", "Megan", "Chloe",
    "Catherine", "Margaret", "Helen",
}

# Consonant alternations for the dative/locative -e ending (softening).
# Ordered longest-first so digraphs win. Shared by female first names and
# noun-declining surnames; a stem whose final consonant is NOT here can't
# be confidently softened and degrades instead.
_SOFTENING = [
    ("ch", "sze"), ("st", "ście"), ("sł", "śle"), ("zd", "ździe"),
    ("t", "cie"), ("d", "dzie"), ("r", "rze"), ("ł", "le"), ("k", "ce"),
    ("g", "dze"), ("b", "bie"), ("p", "pie"), ("w", "wie"), ("f", "fie"),
    ("m", "mie"), ("n", "nie"), ("s", "sie"), ("z", "zie"),
]
# Stem-final sounds that never soften to -e in the dative: historically
# hardened ones take -y (Grażóż→...ży), while soft l/j take -i
# (Izabela→Izabeli, Kaja handled by the -ja branch).
_HARDENED_FINALS = ("ż", "sz", "cz", "rz", "c", "dz")
_SOFT_FINALS = ("l", "j")
# Diminutive-style soft endings whose vocative is -u (Kasia→Kasiu).
_SOFT_IA = ("sia", "cia", "nia", "zia", "dzia")


def _soften(stem: str) -> str | None:
    for plain, soft in _SOFTENING:
        if stem.endswith(plain):
            return stem[: -len(plain)] + soft
    return None


def _decline_female_first(name: str) -> tuple[str, str, str, str, str, str] | None:
    """Regular female -a paradigm: gen, dat, acc, inst, loc, voc.
    Female names are near-perfectly regular, which the audit confirmed --
    the alternation map plus the -ia/-ja special cases cover every female
    name in the database. Returns None when the stem can't be softened
    confidently."""
    if not name.endswith("a") or len(name) < 3:
        return None
    stem = name[:-1]
    low = name.lower()

    if any(low.endswith(s) for s in _SOFT_IA):
        base = stem[:-1]  # drop the i: Kasi-
        return (stem[:-1] + "i", stem[:-1] + "i", stem + "ę", stem + "ą", stem[:-1] + "i", base + "iu")
    if low.endswith("ia"):  # Maria, Zofia, Amelia
        return (stem + "i", stem + "i", stem + "ę", stem + "ą", stem + "i", stem + "o")
    if low.endswith("ja"):  # Alicja, Maja, Kaja
        return (stem[:-1] + "ji", stem[:-1] + "ji", stem + "ę", stem + "ą", stem[:-1] + "ji", stem + "o")

    genitive = stem + ("i" if stem.endswith(("k", "g") + _SOFT_FINALS) else "y")
    if stem.endswith(_SOFT_FINALS):
        dative = stem + "i"
    elif stem.endswith(_HARDENED_FINALS):
        dative = stem + "y"
    else:
        softened = _soften(stem)
        if softened is None:
            return None
        dative = softened
    return (genitive, dative, stem + "ę", stem + "ą", dative, stem + "o")


def _first_name_forms(name: str) -> tuple[str | None, tuple | None]:
    """(gender, six case forms or None). Gender may be known while forms
    are not (rare) -- the caller degrades accordingly."""
    canonical = name[:1].upper() + name[1:].lower() if name else name
    if canonical in _MALE_FIRST:
        return "male", _MALE_FIRST[canonical]
    if canonical in _MALE_A_NAMES:
        return "male", None  # declinable like -a nouns, but rare: stay safe
    if canonical in _FOREIGN_MALE:
        return "male", None  # gender known, name deliberately left frozen
    if canonical in _FOREIGN_FEMALE:
        return "female", None
    if canonical.endswith("a") and len(canonical) >= 3 and not _SURNAME_SHAPED_RE.search(canonical):
        return "female", _decline_female_first(canonical)
    return None, None


# ---------------------------------------------------------------------------
# Surname declension
# ---------------------------------------------------------------------------

# Male surnames that decline irregularly (vowel/consonant alternations a
# suffix rule can't see). Forms: gen, dat, acc, inst, loc.
_MALE_SURNAME_EXCEPTIONS = {
    "Gołąb": ("Gołębia", "Gołębiowi", "Gołębia", "Gołębiem", "Gołębiu"),
    "Kozioł": ("Kozła", "Kozłowi", "Kozła", "Kozłem", "Kozle"),
    "Mróz": ("Mroza", "Mrozowi", "Mroza", "Mrozem", "Mrozie"),
    "Kwiecień": ("Kwietnia", "Kwietniowi", "Kwietnia", "Kwietniem", "Kwietniu"),
    "Dudek": ("Dudka", "Dudkowi", "Dudka", "Dudkiem", "Dudku"),
}

# A male surname whose last syllable carries ą/ó or these endings very
# often alternates internally when declined (Gołąb→Gołębia). Unless it's
# in the exception table, it degrades rather than risking a wrong stem.
_RISKY_MALE_RE = re.compile(r"([ąó][^aeiouyąęó]{0,2}|eń|oł|eł|ól|ódź)$", re.IGNORECASE)


def _decline_female_surname(surname: str) -> tuple[str, str, str, str, str] | None:
    """Female surnames: adjectival -ska/-cka/-dzka decline; every other
    female surname is invariant in standard usage ("z Panią Anną Kobyłko"),
    which is a *result*, not a failure -- so this never returns None for
    a plausible surname."""
    low = surname.lower()
    if low.endswith(("ska", "cka", "dzka")):
        stem = surname[:-1]  # Kowalsk-
        return (stem + "iej", stem + "iej", stem + "ą", stem + "ą", stem + "iej")
    return (surname, surname, surname, surname, surname)


def _decline_male_surname(surname: str) -> tuple[str, str, str, str, str] | None:
    canonical = surname
    if canonical in _MALE_SURNAME_EXCEPTIONS:
        return _MALE_SURNAME_EXCEPTIONS[canonical]
    low = canonical.lower()

    if low.endswith(("ski", "cki", "dzki")):  # adjectival: Kowalski
        stem = canonical[:-1]
        return (stem + "iego", stem + "iemu", stem + "iego", stem + "im", stem + "im")
    if _RISKY_MALE_RE.search(low):
        return None
    if low.endswith("ek") and len(canonical) > 3:  # Maciejek→Maciejka (e drops)
        stem = canonical[:-2] + "k"
        return (stem + "a", stem + "owi", stem + "a", stem + "iem", stem + "u")
    if low.endswith("ec") and len(canonical) > 3:  # Malec→Malca
        stem = canonical[:-2] + "c"
        return (stem + "a", stem + "owi", stem + "a", stem + "em", stem + "u")
    if low.endswith(("a", "o")) and len(canonical) > 3:
        # Noun-style: Zaręba, Kobyłko (male) decline like female nouns.
        stem = canonical[:-1]
        genitive = stem + ("i" if stem.endswith(("k", "g") + _SOFT_FINALS) else "y")
        if stem.endswith(_SOFT_FINALS):
            dative = stem + "i"
        elif stem.endswith(_HARDENED_FINALS):
            dative = stem + "y"
        else:
            softened = _soften(stem)
            if softened is None:
                return None
            dative = softened
        return (genitive, dative, stem + "ę", stem + "ą", dative)
    if low.endswith(("e", "i", "y", "u", "ó")):  # foreign/uninflectable shape
        return None
    # Plain consonant stem: Nowak, Bień, Mickiewicz.
    inst = canonical + ("iem" if low.endswith(("k", "g")) else "em")
    if low.endswith(("k", "g", "ch", "h", "j", "l", "ń", "ś", "ć", "ź", "sz", "cz", "ż", "rz", "b", "p", "w", "m", "n", "s", "z", "c", "dz")):
        locative = canonical + "u"
    else:
        locative = _soften(canonical)
        if locative is None:
            return None
    return (canonical + "a", canonical + "owi", canonical + "a", inst, locative)


def _decline_surname(surname: str, gender: str) -> tuple[str, str, str, str, str] | None:
    """Hyphenated surnames decline part by part (Kowalska-Nowak → z Panią
    Kowalską-Nowak); one undeclinable part degrades the whole surname."""
    parts = surname.split("-")
    decliner = _decline_female_surname if gender == "female" else _decline_male_surname
    declined = [decliner(p) for p in parts if p]
    if any(d is None for d in declined) or not declined:
        return None
    return tuple("-".join(d[i] for d in declined) for i in range(5))  # type: ignore[return-value]


# ---------------------------------------------------------------------------
# Phrase assembly
# ---------------------------------------------------------------------------

# Pan/Pani through the five referring cases: gen, dat, acc, inst, loc.
_PAN = ("Pana", "Panu", "Pana", "Panem", "Panu")
_PANI = ("Pani", "Pani", "Panią", "Panią", "Pani")
_CASES = ("gen", "dat", "acc", "inst", "loc")

# Role fallbacks per case. The masculine "nauczyciel" doubles as the
# gender-unknown generic (standard Polish usage); the director fallback
# without gender is the institution itself -- always safe.
_ROLE_PHRASES = {
    ("teacher", "female"): ("nauczycielki języka angielskiego", "nauczycielce języka angielskiego",
                            "nauczycielkę języka angielskiego", "nauczycielką języka angielskiego",
                            "nauczycielce języka angielskiego"),
    ("teacher", None): ("nauczyciela języka angielskiego", "nauczycielowi języka angielskiego",
                        "nauczyciela języka angielskiego", "nauczycielem języka angielskiego",
                        "nauczycielu języka angielskiego"),
    ("director", "female"): ("Pani Dyrektor", "Pani Dyrektor", "Panią Dyrektor", "Panią Dyrektor", "Pani Dyrektor"),
    ("director", "male"): ("Pana Dyrektora", "Panu Dyrektorowi", "Pana Dyrektora", "Panem Dyrektorem", "Panu Dyrektorze"),
    ("director", None): ("dyrekcji szkoły", "dyrekcji szkoły", "dyrekcję szkoły", "dyrekcją szkoły", "dyrekcji szkoły"),
}
_ROLE_PHRASES[("teacher", "male")] = _ROLE_PHRASES[("teacher", None)]

SECRETARIAT_SALUTATION = "Dzień dobry,"


def _salutation(role: str, gender: str | None, vocative: str | None) -> str:
    """Direct-address opener, formal register ("Szanowna Pani Anno,").
    Directors get the title form -- Polish etiquette for a director you
    don't know personally -- which also needs no name declension at all.
    Teachers get the warmer first-name vocative when it's known."""
    if role == "director":
        if gender == "female":
            return "Szanowna Pani Dyrektor,"
        if gender == "male":
            return "Szanowny Panie Dyrektorze,"
        return "Szanowni Państwo,"
    if gender == "female":
        return f"Szanowna Pani {vocative}," if vocative else "Szanowna Pani,"
    if gender == "male":
        return f"Szanowny Panie {vocative}," if vocative else "Szanowny Panie,"
    return "Dzień dobry,"


def _salutation_casual(role: str, gender: str | None, vocative: str | None) -> str:
    """The same opener in the everyday register ("Dzień dobry Pani Anno,")
    -- exported alongside the formal one so a campaign can pick the tone
    per audience rather than per person. Both use the SAME vocative, so
    switching register never changes how someone's name is inflected.

    Without a name there is no casual form worth having: "Dzień dobry
    Panie," on its own reads as an unfinished sentence in Polish, so those
    rows fall back to the bare greeting rather than a broken one."""
    if role == "director":
        if gender == "female":
            return "Dzień dobry Pani Dyrektor,"
        if gender == "male":
            return "Dzień dobry Panie Dyrektorze,"
        return "Dzień dobry,"
    if vocative:
        if gender == "female":
            return f"Dzień dobry Pani {vocative},"
        if gender == "male":
            return f"Dzień dobry Panie {vocative},"
    return "Dzień dobry,"


def person_csv_columns(full_name: str | None, role: str) -> dict[str, str]:
    """The 11 export columns for one person. `role` is "teacher" or
    "director". Never raises, never guesses: every uncertainty lands on
    the documented degradation ladder."""
    parts = _clean(full_name or "")
    # Surname-first ordering ("Grochowalska Agnieszka") -- seen in real
    # scraped data. Swapped only on positive proof BOTH ways: the first
    # token is surname-shaped AND the last token is a name the gender
    # logic actually recognizes, so "Baranowska-Piasek" alone or two
    # ambiguous tokens still degrade instead of guessing.
    # Two tests, either sufficient, both requiring proof on BOTH tokens:
    # the leading token is surname-SHAPED, or it is simply not a first name
    # the gender logic recognizes while the trailing token is. The shape
    # test alone missed every surname without a Polish surname suffix --
    # "Bakiera Patrycja" was read as first name "Bakiera", giving the
    # dative "Pani Bakierze Patrycja" and the salutation "Szanowna Pani
    # Bakiero", i.e. addressing a teacher by her declined SURNAME. Two
    # ambiguous tokens, or a lone "Baranowska-Piasek", still degrade
    # rather than guess.
    if len(parts) == 2 and _first_name_forms(parts[1])[0] is not None:
        leading_is_surname_shaped = bool(_SURNAME_SHAPED_RE.search(parts[0]))
        leading_is_not_a_first_name = _first_name_forms(parts[0])[0] is None
        if leading_is_surname_shaped or leading_is_not_a_first_name:
            parts = [parts[1], parts[0]]
    gender: str | None = None
    first = last = ""
    first_forms = surname_forms = None

    if parts and not _SURNAME_SHAPED_RE.search(parts[0]) and "-" not in parts[0]:
        first = parts[0]
        last = parts[-1] if len(parts) >= 2 else ""
        gender, first_forms = _first_name_forms(first)
        if gender and last:
            surname_forms = _decline_surname(last, gender)

    pan = _PANI if gender == "female" else _PAN
    if first_forms and surname_forms:
        quality = "full"
        refs = [f"{pan[i]} {first_forms[i]} {surname_forms[i]}" for i in range(5)]
        subject_ref = f"dla {pan[0]} {surname_forms[0]}"
    elif first_forms:
        quality = "first_name_only"
        tail = f" {last}" if last else ""  # surname frozen in nominative
        refs = [f"{pan[i]} {first_forms[i]}{tail}" for i in range(5)]
        subject_ref = f"dla {pan[0]} {first_forms[0]}"
    elif gender:
        # Gender is known but the name can't be safely declined (foreign
        # name from the curated table, or a female -a name with an
        # unsoftenable stem): decline ONLY Pan/Pani and freeze the whole
        # name -- "z Panem Kirk Palmer" -- the standard Polish treatment
        # of foreign names.
        quality = "undeclined"
        frozen = f"{first} {last}".strip()
        refs = [f"{pan[i]} {frozen}" for i in range(5)]
        subject_ref = f"dla {pan[0]} {last or first}"
    else:
        quality = "role_only"
        role_forms = _ROLE_PHRASES[(role, gender if (role, gender) in _ROLE_PHRASES else None)]
        refs = list(role_forms)
        subject_ref = f"dla {role_forms[0]}"

    vocative = first_forms[5] if first_forms else None
    nominative = f"{'Pani' if gender == 'female' else 'Pan'} {first} {last}".strip() if quality != "role_only" else ""

    columns = {
        "gender": gender or "",
        "first_name": first if quality != "role_only" else "",
        "last_name": last if quality != "role_only" else "",
        "salutation": _salutation(role, gender, vocative),
        "salutation_casual": _salutation_casual(role, gender, vocative),
        "ref_nom": nominative,
        "subject_ref": subject_ref,
        "ref_quality": quality,
    }
    for case, phrase in zip(_CASES, refs):
        columns[f"ref_{case}"] = phrase
    return columns


# Fixed export ordering so all three CSVs stay column-identical.
PERSON_COLUMN_ORDER = (
    "gender", "first_name", "last_name", "salutation", "salutation_casual",
    "ref_nom", "ref_gen", "ref_dat", "ref_acc", "ref_inst", "ref_loc",
    "subject_ref", "ref_quality",
)


def csv_headers(prefix: str) -> list[str]:
    return [f"{prefix}_{name}" for name in PERSON_COLUMN_ORDER]


def csv_values(full_name: str | None, role: str) -> list[str]:
    columns = person_csv_columns(full_name, role)
    return [columns[name] for name in PERSON_COLUMN_ORDER]

# ---------------------------------------------------------------------------
# Recipient-matched greeting
# ---------------------------------------------------------------------------

RECIPIENT_COLUMNS = ("recipient_salutation", "recipient_salutation_casual", "recipient_is")


def recipient_columns(
    owner: str | None, teacher_name: str | None, director_name: str | None
) -> list[str]:
    """The greeting for whoever the outgoing address ACTUALLY belongs to.

    The export previously offered the teacher's name and the teacher's
    salutations next to a single "best_email" column that, at partial level,
    is virtually never the teacher's own address -- so a letter opening
    "Dzien dobry Pani Anno" went to the secretariat, or to the director's
    inbox under the director's name. These three columns remove the choice:
    the greeting is derived from the OWNER of the address, so name and
    recipient can never disagree.

    owner is "teacher", "director", "office", or None."""
    if owner == "teacher" and teacher_name:
        cols = person_csv_columns(teacher_name, "teacher")
        return [cols["salutation"], cols["salutation_casual"], "teacher"]
    if owner == "director" and director_name:
        cols = person_csv_columns(director_name, "director")
        return [cols["salutation"], cols["salutation_casual"], "director"]
    # An office mailbox is nobody in particular -- and a school that gave us
    # only a shared box gets the impersonal opener, which is also the right
    # register for asking a secretariat to pass a message on.
    return [SECRETARIAT_SALUTATION, SECRETARIAT_SALUTATION, "office" if owner else "none"]
