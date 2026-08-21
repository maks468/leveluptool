"""Deep audit probe for one or more schools. READ-ONLY: never writes the DB.

Usage (inside the container):
    python /app/scripts/audit_school_probe.py 8733 15063 ...

Prints, per school:

  A. WHAT PRODUCTION DID -- the real crawler's result: names, emails, and
     every page it kept for the LLM, with tier.
  B. STAFF PAGES, VERBATIM -- the text of every page whose link/label looks
     like a staff roster, so "is a teacher findable here?" is answerable by
     reading. Marked with whether production kept it.
  C. NAMED ENGLISH MENTIONS -- windows around "angiel" that also contain a
     person-shaped name (the bare word appears in every language-switcher
     widget, so a name is required to make the hit meaningful).
  D. GAP -- staff-looking links production never fetched.
"""

import re
import sys
import sqlite3
from urllib.parse import urljoin, urlparse

from bs4 import BeautifulSoup

from levelup.services.enrichment import scraper

MAX_SWEEP_PAGES = 22
STAFF_DUMP_CHARS = 2600

# Polish subject naming only. "English" alone is useless -- every site with a
# translate widget lists it dozens of times.
ANGIEL_RE = re.compile(r"angiel", re.IGNORECASE)
NAME_RE = re.compile(
    r"[A-ZŁŚŻŹĆŃÓĘĄ][a-ząćęłńóśźż]{2,}\s+[A-ZŁŚŻŹĆŃÓĘĄ][a-ząćęłńóśźż]{2,}"
)
STAFF_HINT_RE = re.compile(
    r"nauczyciel|kadra|grono|pracownic|rada.?pedagog|zespol|zespół|team|staff|teacher|"
    r"wychowawc|specjalis|nasi.?ludzie|o.?nas|about",
    re.IGNORECASE,
)
NON_HTML = (".pdf", ".doc", ".docx", ".xls", ".xlsx", ".jpg", ".jpeg", ".png", ".gif", ".zip", ".mp4")


def _links(soup, base):
    out, seen = [], set()
    for a in soup.find_all("a", href=True):
        href = a["href"].strip()
        if href.startswith(("mailto:", "tel:", "javascript:", "#")):
            continue
        url = urljoin(base, href).split("#")[0]
        if urlparse(url).netloc != urlparse(base).netloc:
            continue
        if url.lower().endswith(NON_HTML) or url in seen:
            continue
        seen.add(url)
        out.append((re.sub(r"\s+", " ", a.get_text(" ", strip=True))[:60], url))
    return out


def _boilerplate_shingles(texts, threshold=0.6):
    """Substrings present on most pages are nav/footer chrome. Used to keep
    the reported windows free of translate-widget noise."""
    if len(texts) < 3:
        return set()
    counts = {}
    for t in texts:
        for sh in {t[i : i + 40] for i in range(0, max(1, len(t) - 40), 40)}:
            counts[sh] = counts.get(sh, 0) + 1
    cutoff = len(texts) * threshold
    return {sh for sh, n in counts.items() if n >= cutoff}


# Site-wide translate widgets ("English Deutsch Español ... 日本語 简体中文") put
# the word English on every page and defeat any frequency-based boilerplate
# filter, because the list renders at a different offset per page. Its
# signature is unmistakable: several foreign endonyms, or non-Latin script,
# inside one window.
_LANG_WIDGET_WORDS = (
    "deutsch", "español", "français", "italiano", "nederlands", "svenska", "português",
    "čeština", "magyar", "polski", "dansk", "suomi", "türkçe", "român", "slovenč",
)
_NON_LATIN_RE = re.compile(r"[Ѐ-ӿͰ-Ͽ一-鿿぀-ヿ가-힯؀-ۿ]")


def _is_translate_widget(window):
    low = window.lower()
    return sum(w in low for w in _LANG_WIDGET_WORDS) >= 2 or bool(_NON_LATIN_RE.search(window))


def _named_angiel_windows(text, boiler, width=230, limit=6):
    hits, start = [], 0
    low = text.lower()
    while len(hits) < limit:
        i = low.find("angiel", start)
        if i < 0:
            break
        start = i + 6
        w = text[max(0, i - width) : i + width]
        if not NAME_RE.search(w):
            continue  # a bare subject/language mention, nobody named
        if _is_translate_widget(w):
            continue  # a language-switcher list, not prose about a person
        if any(sh and sh in w for sh in boiler):
            continue  # inside nav/footer chrome
        hits.append(re.sub(r"\s+", " ", w))
    return hits


def probe(school_id, conn):
    row = conn.execute(
        "select name, city, website_url, director_name, english_teacher_name from schools where id=?",
        (school_id,),
    ).fetchone()
    if not row:
        print(f"### school {school_id}: NOT FOUND")
        return
    name, city, site, director, teacher = row
    print("=" * 100)
    print(f"### SCHOOL {school_id} | {name}")
    print(f"### {city} | site={site} | db_director={director!r} | db_teacher={teacher!r}")
    print("=" * 100)

    print("\n--- A. PRODUCTION CRAWLER ---")
    try:
        res = scraper.scrape_school_website(name, site, None)
    except Exception as exc:  # noqa: BLE001
        print(f"  CRAWL RAISED {type(exc).__name__}: {exc}")
        res = {}
    prod = {p["url"]: p for p in (res.get("llm_pages") or [])}
    print(f"  regex director : {res.get('director_name')!r}")
    print(f"  regex teacher  : {res.get('english_teacher_name')!r}")
    print(f"  emails         : {sorted(res.get('all_emails') or [])}")
    print(f"  js_app_shell={res.get('js_app_shell')} js_render_used={res.get('js_render_used')} "
          f"discovered={res.get('discovered_website_url')!r}")
    print(f"  pages kept for LLM ({len(prod)}):")
    for u, p in prod.items():
        t = p.get("text") or ""
        flag = "ANGIEL" if ANGIEL_RE.search(t) else "      "
        print(f"    [{flag}] tier={p.get('tier')} len={len(t)} {u}")

    start_url = res.get("discovered_website_url") or site or ""
    if start_url and not start_url.startswith("http"):
        start_url = "http://" + start_url
    home = scraper.fetch_page(start_url) if start_url else None
    if not home:
        for variant in scraper._hostname_fallback_variants(start_url):
            home = scraper.fetch_page(variant)
            if home:
                start_url = variant
                break
    if not home:
        print(f"\n  HOMEPAGE UNREACHABLE ({start_url}) -- site may be dead or blocking\n")
        return

    soup = BeautifulSoup(home, "html.parser")
    all_links = _links(soup, start_url)
    ranked = sorted(all_links, key=lambda p: 0 if STAFF_HINT_RE.search(p[0] + " " + p[1]) else 1)
    pages = {start_url: home}
    for lbl, u in ranked:
        if len(pages) >= MAX_SWEEP_PAGES:
            break
        if u in pages:
            continue
        html = scraper.fetch_page(u)
        if html:
            pages[u] = html
    texts = {u: BeautifulSoup(h, "html.parser").get_text(" ", strip=True) for u, h in pages.items()}
    boiler = _boilerplate_shingles(list(texts.values()))
    print(f"\n  (wide sweep: {len(all_links)} same-site links on homepage, {len(pages)} fetched)")

    print("\n--- B. STAFF PAGES, VERBATIM ---")
    label_by_url = {u: lbl for lbl, u in all_links}
    staff_urls = [u for u in texts if STAFF_HINT_RE.search((label_by_url.get(u, "") + " " + u))]
    if not staff_urls:
        print("  (no staff-looking page found on this site)")
    for u in staff_urls[:5]:
        t = texts[u]
        mark = "KEPT BY PRODUCTION" if u in prod else ">>> PRODUCTION NEVER KEPT <<<"
        emails = sorted(set(scraper.EMAIL_RE.findall(t)))
        print(f"\n  [{u}]  ({label_by_url.get(u, '')!r})  {mark}")
        print(f"    len={len(t)} angiel={'YES' if ANGIEL_RE.search(t) else 'no'} emails={emails[:10]}")
        print("    TEXT: " + re.sub(r"\s+", " ", t)[:STAFF_DUMP_CHARS])

    print("\n--- C. NAMED ENGLISH MENTIONS (whole sweep) ---")
    any_hit = False
    for u, t in texts.items():
        for w in _named_angiel_windows(t, boiler):
            any_hit = True
            mark = "kept" if u in prod else "NOT KEPT"
            print(f"\n  [{mark}] {u}")
            print(f"    ...{w}")
    if not any_hit:
        print("  (no page pairs a person-shaped name with an English mention)")

    print("\n--- D. GAP: staff-looking links production never fetched ---")
    gap = [(lbl, u) for lbl, u in all_links if STAFF_HINT_RE.search(lbl + " " + u) and u not in prod]
    if not gap:
        print("  (none)")
    for lbl, u in gap[:12]:
        print(f"    {lbl!r} -> {u}")
    print()


def main():
    conn = sqlite3.connect("file:/app/data/levelup.db?mode=ro", uri=True)
    for a in sys.argv[1:]:
        try:
            probe(int(a), conn)
        except Exception as exc:  # noqa: BLE001
            print(f"### school {a} PROBE FAILED: {type(exc).__name__}: {exc}")


if __name__ == "__main__":
    main()
