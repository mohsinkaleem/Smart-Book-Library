"""
Language code normalisation.

The extractors write whatever the file's metadata claimed, and a lot of it is
not ISO-639-1: the live catalog holds `po`, `sp` and `ge` alongside `en`, `ar`
and `fr`, plus 25 empty strings. Those junk codes were offered as filter
options in the sidebar, where picking one returned a single book.

The rule here is deliberately conservative: normalise the *shape* of a code
(case, region suffix, the `eng`/`ger` three-letter forms) and validate the
result against ISO-639-1. Anything that does not survive that becomes
`UNKNOWN` rather than being guessed at — the books tagged `po` are *Brave New
World* and *Thinking, Fast and Slow*, and the one tagged `ge` is Kuhn's
*Structure of Scientific Revolutions*. All three are English. Mapping `po` to
Portuguese would not clean the data up, it would only make a bad value look
like a good one.
"""
from typing import Optional

UNKNOWN = "unknown"

# ISO 639-1, the two-letter set. Kept whole so validation is a membership test
# rather than a guess about which codes this particular catalog might hold.
ISO_639_1 = frozenset("""
aa ab ae af ak am an ar as av ay az ba be bg bh bi bm bn bo br bs ca ce ch co
cr cs cu cv cy da de dv dz ee el en eo es et eu fa ff fi fj fo fr fy ga gd gl
gn gu gv ha he hi ho hr ht hu hy hz ia id ie ig ii ik io is it iu ja jv ka kg
ki kj kk kl km kn ko kr ks ku kv kw ky la lb lg li ln lo lt lu lv mg mh mi mk
ml mn mr ms mt my na nb nd ne ng nl nn no nr nv ny oc oj om or os pa pi pl ps
pt qu rm rn ro ru rw sa sc sd se sg si sk sl sm sn so sq sr ss st su sv sw ta
te tg th ti tk tl tn to tr ts tt tw ty ug uk ur uz ve vi vo wa wo xh yi yo za
zh zu
""".split())

# ISO 639-2/T and the handful of three-letter forms PDF and EPUB metadata
# actually emits. Only unambiguous mappings belong here.
_THREE_LETTER = {
    "ara": "ar", "chi": "zh", "cze": "cs", "dan": "da", "dut": "nl",
    "eng": "en", "fin": "fi", "fre": "fr", "fra": "fr", "ger": "de",
    "deu": "de", "gre": "el", "heb": "he", "hin": "hi", "hun": "hu",
    "ind": "id", "ita": "it", "jpn": "ja", "kor": "ko", "lat": "la",
    "nor": "no", "per": "fa", "fas": "fa", "pol": "pl", "por": "pt",
    "rus": "ru", "spa": "es", "swe": "sv", "tur": "tr", "ukr": "uk",
    "urd": "ur", "vie": "vi",
}


def normalise_language(raw: Optional[str]) -> str:
    """
    Fold a stored language value to an ISO-639-1 code, or `UNKNOWN`.

    Handles the shapes that actually occur: `EN`, `en-US`, `en_GB`, `eng`.
    Anything else — including `''`, `po`, `sp` and `ge` — is `UNKNOWN`.
    """
    if not raw:
        return UNKNOWN
    code = str(raw).strip().lower().replace("_", "-").split("-")[0]
    if code in ISO_639_1:
        return code
    if code in _THREE_LETTER:
        return _THREE_LETTER[code]
    return UNKNOWN


def is_unknown(raw: Optional[str]) -> bool:
    return normalise_language(raw) == UNKNOWN
