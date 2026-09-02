"""Reading a roster that only exists as a scan or a photo.

Some schools publish their staff list solely as a PDF or an image gallery,
so the text pass has nothing to read. Two defects had to be fixed before
this path could ever work, and both are pinned below by construction:

  * _run_query hardcoded max_turns=1. A call that must USE a tool cannot
    answer in one turn -- it spends the first invoking Read -- so every
    vision call ever made died on "Reached maximum number of turns (1)".
  * the downloaded file landed in the system temp dir while the SDK was
    given an isolated cwd, and Read refuses a path outside it, so the model
    was denied its own file and burned the remaining turns retrying.

The economics are the other half. _roster_media_urls returns EVERY image
and PDF on the kept pages -- measured on the live corpus, 3,397 files
across 709 teacher-less schools, of which almost none are rosters. Reading
them all costs 1,660 calls at ~127 seconds each; filtering on the filename
cuts it to 119 and keeps the real ones.
"""

from levelup.services.enrichment import llm_extract
from levelup.services.enrichment.jobs import _vision_candidates


def _page(*urls):
    """A prepared page carrying the media footer the crawler appends."""
    return {
        "url": "https://szkola.pl/kadra",
        "tier": 1,
        "third_party": False,
        "text": "Kadra pedagogiczna\nIMAGE_OR_PDF_LINKS: " + " ".join(urls),
    }


def test_real_rosters_are_kept():
    # Every one of these is an actual file from an audited school.
    urls = [
        "https://sp20.wroc.pl/images/KADRA/25_26/NAUCZYCIELE-2025.09.22.jpg",
        "http://sp9.com.pl/wp-content/uploads/2025/10/Wykaz-nauczycieli-SP9.pdf",
        "https://sp81.edu.gdansk.pl/Content/pagefoto/kadra-200876.jpg",
        "https://zso5.sosnowiec.pl/wp-content/uploads/2025/09/Wychowawcy.pdf",
        "https://cloud-e.edupage.org/cloud/grono_pedagogiczne_2025_2026.pdf?z%3AVytdYAasA",
    ]
    got = _vision_candidates([_page(*urls)], limit=5)
    assert len(got) == 5, got


def test_the_noise_that_dominates_the_corpus_is_dropped():
    # Real files from the same footers -- a GDPR notice, a classroom
    # allocation table, a supplies list, a prize-winners list, a
    # teacher-parent contact policy, a pastoral programme, a handbook.
    noise = [
        "https://domotwarty.net/INFORMACJA-O-PRZETWARZANIU-DANYCH-OSOBOWYCH.pdf",
        "http://cloud-b.edupage.org/cloud/Przydzial-sal-dla-klas-1-3.2026.jpg",
        "http://cloud-9.edupage.org/cloud/Wyprawka_kl._I.pdf",
        "https://kostka-kielce.pl/WYKAZ-LAUREATOW-i-FINALISTOW-OLIMPIAD.pdf",
        "https://cloud-3.edupage.org/cloud/Zasady_kontaktow_nauczycieli_z_rodzicami.pdf",
        "https://akademia.soward.eu/2025-2026-Program-wychowawczo-profilaktyczny.pdf",
        "https://lo11.edu.bialystok.pl/Poradnik+dla+nauczycieli_zdrowie.pdf",
        "https://sp27.edu.gdansk.pl/Content/articles/foto/pamietamy-o-bliskich.jpg",
    ]
    assert _vision_candidates([_page(*noise)], limit=3) == []


def test_non_media_and_third_party_hosts_are_dropped():
    urls = [
        "https://szkola.pl/kadra.docx",           # not an image or PDF
        "https://facebook.com/szkola/kadra.jpg",  # someone else's host
        "https://szkola.pl/kadra-nauczycieli.pdf",
    ]
    assert _vision_candidates([_page(*urls)], limit=3) == [
        "https://szkola.pl/kadra-nauczycieli.pdf"
    ]


def test_the_call_budget_is_respected():
    many = [f"https://szkola.pl/kadra-{i}.pdf" for i in range(10)]
    assert len(_vision_candidates([_page(*many)], limit=3)) == 3
    assert llm_extract.MAX_VISION_CALLS_PER_SCHOOL == 3


def test_a_tool_using_call_is_given_more_than_one_turn():
    """The defect that made every vision call return None."""
    assert llm_extract.VISION_MAX_TURNS >= 2


def test_the_file_is_staged_where_the_read_tool_can_reach_it(tmp_path):
    """The other defect: Read refuses a path outside the SDK's cwd."""
    source = tmp_path / "roster.jpg"
    source.write_bytes(b"not really a jpeg")
    staged = llm_extract._stage_for_read(str(source))
    try:
        assert staged.startswith(llm_extract._ISOLATED_CWD)
        assert open(staged, "rb").read() == b"not really a jpeg"
    finally:
        llm_extract._unstage(staged)
    # ...and it always cleans up after itself.
    import os

    assert not os.path.exists(staged)


def test_vision_confidence_is_capped_without_a_matching_email_domain():
    """A vision quote is read from a picture and cannot be span-verified
    against fetched text, so it is deliberately held to a weaker standard."""
    ex = llm_extract.SchoolExtraction(
        staff=[
            llm_extract.StaffRecord(
                name="Klaudia Froch",
                role="english_teacher",
                evidence="JĘZYK ANGIELSKI Klaudia Froch",
                source_url="https://sp20.wroc.pl/images/KADRA/NAUCZYCIELE.jpg",
                confidence="high",
            )
        ]
    )
    grounded = llm_extract.ground_vision_extraction(ex, school_website_domain="sp20.wroc.pl")
    assert grounded.staff[0].confidence == "medium"


def test_a_record_with_no_readable_evidence_is_dropped():
    ex = llm_extract.SchoolExtraction(
        staff=[
            llm_extract.StaffRecord(
                name="Nikt Nieczytelny",
                role="english_teacher",
                evidence="   ",
                source_url="https://szkola.pl/kadra.jpg",
                confidence="high",
            )
        ]
    )
    assert llm_extract.ground_vision_extraction(ex, school_website_domain="szkola.pl").staff == []


def test_the_source_url_is_filled_in_by_us_not_the_model():
    """On a real roster the model returned seven correct staff records with
    source_url null on every one, so schema validation rejected the whole
    extraction and a good read was thrown away. There is exactly one file in
    a vision call and we know its address -- asking the model to copy it back
    is a failure mode with no upside."""
    raw = {
        "staff": [
            {"name": "Klaudia Froch", "role": "english_teacher", "evidence": "JĘZYK ANGIELSKI",
             "source_url": None, "confidence": "high"},
            {"name": "Jan Kowalski", "role": "director", "evidence": "Dyrektor",
             "confidence": "high"},
        ]
    }
    stamped = llm_extract._stamp_source_url(raw, "https://sp20.wroc.pl/kadra.jpg")
    assert all(r["source_url"] == "https://sp20.wroc.pl/kadra.jpg" for r in stamped["staff"])
    assert llm_extract._validate_extraction(stamped) is not None


def test_a_url_the_model_did_supply_is_left_alone():
    raw = {"staff": [{"name": "A B", "role": "english_teacher", "evidence": "x",
                      "source_url": "https://real.pl/a.jpg", "confidence": "medium"}]}
    out = llm_extract._stamp_source_url(raw, "https://other.pl/b.jpg")
    assert out["staff"][0]["source_url"] == "https://real.pl/a.jpg"


def test_a_narrated_answer_is_still_parsed():
    """A tool-using call narrates before answering. A real vision read
    returned "I'll read the image and extract the staff information."
    immediately followed by valid JSON, which parsed as neither a fence nor
    a bare object -- so a correct seven-record extraction was discarded."""
    text = (
        "I'll read the image and extract the staff information."
        '{"staff": [{"name": "Klaudia Froch", "role": "english_teacher",'
        ' "evidence": "JĘZYK ANGIELSKI", "source_url": "https://x.pl/a.jpg",'
        ' "confidence": "high"}]}'
    )
    parsed = llm_extract._parse_json_response(text)
    assert parsed is not None
    assert parsed["staff"][0]["name"] == "Klaudia Froch"


def test_the_existing_shapes_still_parse():
    assert llm_extract._parse_json_response('{"staff": []}') == {"staff": []}
    assert llm_extract._parse_json_response('```json\n{"staff": []}\n```') == {"staff": []}
    # A brace inside a string must not end the object early.
    assert llm_extract._parse_json_response('x{"notes": "a { brace", "staff": []}')["notes"] == "a { brace"
    assert llm_extract._parse_json_response("no json here") is None


def test_a_complex_hubs_rosters_are_read_own_school_first():
    """szkolysalezjanskie.pl links five rosters -- preschool group 0,
    SP klasy 1-3, SP klasy 4-8, liceum, branżowa -- and reading them in
    document order attributed the PRESCHOOL group-0C English teacher to
    both the SP and the LICEUM. A file naming another level is read last,
    not skipped."""
    urls = [
        "https://www.szkolysalezjanskie.pl/wp-content/uploads/2025/10/KADRA-2025-2026-GRUPY-0-.pdf",
        "https://www.szkolysalezjanskie.pl/wp-content/uploads/2025/10/KADRA-2025-2026-klasy-1-3-SP.pdf",
        "https://www.szkolysalezjanskie.pl/wp-content/uploads/2025/10/KADRA-PEDAGOGICZNA-4-8.pdf",
        "https://www.szkolysalezjanskie.pl/wp-content/uploads/2024/09/KADRA-PEDAGOGICZNA-Liceum-Ogolnoksztalcace.pdf",
        "https://www.szkolysalezjanskie.pl/wp-content/uploads/2024/09/KADRA-PEDAGOGICZNA-Branzowa-Szkola-na-strone.pdf",
    ]
    page = _page(*urls)

    # The REAL SchoolLevel enum, not a string: its NAME is "PRIMARY" but
    # its VALUE is "primary", and rank comparing against the wrong one made
    # every file tie -- document order survived and the group-0 roster was
    # read first for the liceum a second time.
    from levelup.models.school import SchoolLevel

    got_sp = _vision_candidates([page], limit=3, school_level=SchoolLevel.PRIMARY)
    assert "4-8" in got_sp[0], got_sp                       # the SP reads its own 4-8 roster first
    assert all("Liceum" not in u and "Branzowa" not in u for u in got_sp[:2]), got_sp

    got_lo = _vision_candidates([page], limit=3, school_level=SchoolLevel.LICEUM)
    assert "Liceum" in got_lo[0], got_lo                    # the liceum reads ITS roster first
    assert "GRUPY-0" not in got_lo[0], got_lo

    # Without a level (or an unknown one), document order is preserved.
    got_plain = _vision_candidates([page], limit=3)
    assert got_plain[0] == urls[0]
