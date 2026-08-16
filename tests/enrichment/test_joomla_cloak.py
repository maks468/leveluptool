"""Joomla email-cloak decoding (the slojedynka.zsosto.pl failure).

Joomla hides every address behind a placeholder span plus a script that
holds the real address as concatenated HTML-entity fragments. The staff
page shows the LLM a name followed by "Ten adres pocztowy jest chroniony
przed spamowaniem..." and no address -- so the liceum's English teacher
came back email-less even though her address is in the page's own source.
The snippet below is modeled 1:1 on the real page's markup.
"""

from levelup.services.enrichment.scraper import _decode_joomla_cloaks, _extract

# Two cloaked staff entries, exactly the real page's shape: addy built over
# two statements, addy_text in one, entities for letters and separators.
CLOAKED_PAGE = """
<html><body>
<p>Wychowawca klasy 4B</p>
<p>Agata Helwich</p>
<span id="cloak21e3babb53ece7d3762925a73c660bb2">Ten adres pocztowy jest chroniony przed spamowaniem.
Aby go zobaczyć, konieczne jest włączenie w przeglądarce obsługi JavaScript.</span>
<script>
    var prefix = '&#109;a' + 'i&#108;' + '&#116;o';
    var path = 'hr' + 'ef' + '=';
    var addy21e3babb53ece7d3762925a73c660bb2 = '&#97;g&#97;t&#97;.helw&#105;ch' + '&#64;';
    addy21e3babb53ece7d3762925a73c660bb2 = addy21e3babb53ece7d3762925a73c660bb2 + 'zs&#111;st&#111;' + '&#46;' + 'pl';
    var addy_text21e3babb53ece7d3762925a73c660bb2 = '&#97;g&#97;t&#97;.helw&#105;ch' + '&#64;' + 'zs&#111;st&#111;' + '&#46;' + 'pl';
    document.getElementById('cloak21e3babb53ece7d3762925a73c660bb2').innerHTML += '<a ' + path + '\\'' + prefix + ':' + addy21e3babb53ece7d3762925a73c660bb2 + '\\'>' + addy_text21e3babb53ece7d3762925a73c660bb2 + '</a>';
</script>
<p>Sekretariat</p>
<span id="cloakffffffffffffffffffffffffffffffff">Ten adres pocztowy jest chroniony przed spamowaniem.</span>
<script>
    var addy_textffffffffffffffffffffffffffffffff = 'sekret&#97;r&#105;&#97;tl&#111;' + '&#64;' + 'zs&#111;st&#111;.pl';
</script>
</body></html>
"""


def test_cloaked_addresses_are_decoded_in_place():
    decoded = _decode_joomla_cloaks(CLOAKED_PAGE)

    assert "agata.helwich@zsosto.pl" in decoded
    assert "sekretariatlo@zsosto.pl" in decoded
    # The placeholder spans -- and their misleading protection notice --
    # are gone entirely, replaced by the address at the same position.
    assert "chroniony przed spamowaniem" not in decoded
    # Adjacency preserved: the address follows the teacher's name, which
    # is what the LLM pairing relies on.
    assert decoded.index("Agata Helwich") < decoded.index("agata.helwich@zsosto.pl") < decoded.index("Sekretariat")


def test_extract_sees_the_decoded_emails_as_candidates():
    found = _extract(CLOAKED_PAGE, "http://www.slojedynka.zsosto.pl/liceum/kadra")

    assert "agata.helwich@zsosto.pl" in found["emails"]
    # With real addresses recovered, this page is no longer "cloaked with
    # nothing found" -- the flag must not fire.
    assert not found.get("email_cloak_detected")
    # And the LLM-ready text pairs name and address on adjacent lines.
    assert "Agata Helwich" in found["llm_text"] and "agata.helwich@zsosto.pl" in found["llm_text"]


def test_pages_without_cloaks_pass_through_untouched():
    plain = "<html><body><p>Kontakt: biuro@szkola.pl</p></body></html>"
    assert _decode_joomla_cloaks(plain) is plain


def test_garbage_fragments_never_produce_a_fake_address():
    broken = """
    <span id="cloakabcdef123456">chroniony przed spamowaniem</span>
    <script>var addy_textabcdef123456 = 'not' + ' an ' + 'email at all';</script>
    """
    decoded = _decode_joomla_cloaks(broken)
    # Nothing valid decoded -> the span (and its notice) stay as they were.
    assert "chroniony przed spamowaniem" in decoded
    assert "@" not in decoded
