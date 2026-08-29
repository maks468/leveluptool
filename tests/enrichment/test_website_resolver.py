"""Finding a school's real website by web search, for when RSPO is wrong.

RSPO's website field is frequently blank or wrong -- school 4625 was stored
as "szkolylso.edupage.pl" (dead) when the live site is
"szkolylso.edupage.org", and school 874 had no website at all while its
real site is "swrodzina.legnica.pl". The scraped-search path
(Startpage/DuckDuckGo) is CAPTCHA-walled in this environment, so the
resolver uses the model's own WebSearch tool. The URL it returns is only a
candidate -- the crawl re-verifies it with _verify_school_site before
trusting anything on it.

These tests cover the parsing/budget contract without making a live call;
the end-to-end search is exercised manually (874 -> swrodzina.legnica.pl).
"""

from levelup.services.enrichment import llm_extract


def test_a_web_search_gets_more_turns_than_a_single_file_read():
    # A search often needs several turns (search, refine, answer); 4 ran out
    # mid-search on a school with same-named siblings.
    assert llm_extract.WEBSITE_SEARCH_MAX_TURNS > llm_extract.VISION_MAX_TURNS


def test_the_finder_exists_and_is_gated_on_the_sdk(monkeypatch):
    # With no SDK, it must return None rather than raise into the crawl.
    monkeypatch.setattr(llm_extract, "SDK_AVAILABLE", False)
    assert llm_extract.find_school_website("SZKOŁA PODSTAWOWA NR 1", "Kraków") is None


def test_a_bare_url_answer_is_extracted_and_a_none_answer_yields_none(monkeypatch):
    calls = {}

    def fake_run(prompt, *, system_prompt, model, allowed_tools, max_turns):
        calls["tools"] = allowed_tools
        return calls["reply"], {}

    monkeypatch.setattr(llm_extract, "SDK_AVAILABLE", True)
    monkeypatch.setattr(llm_extract, "_run_sync", lambda coro: coro)  # pass the tuple straight through
    monkeypatch.setattr(llm_extract, "_run_query", fake_run)

    calls["reply"] = "https://swrodzina.legnica.pl/szkola-katolicka"
    assert llm_extract.find_school_website("X", "Legnica") == "https://swrodzina.legnica.pl/szkola-katolicka"
    assert calls["tools"] == ["WebSearch"]

    # Trailing narration/punctuation is trimmed to the bare URL.
    calls["reply"] = "The official site is https://sp1.krakow.pl/."
    assert llm_extract.find_school_website("X", "Kraków") == "https://sp1.krakow.pl/"

    # An explicit NONE (no confident match) yields None, not a bogus URL.
    calls["reply"] = "NONE"
    assert llm_extract.find_school_website("X", "Y") is None
