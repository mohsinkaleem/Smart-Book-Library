"""
Person-name predicate and author normalisation.

One rejection predicate is applied to *every* author candidate from *every*
source. PDF producer/creator strings such as
"Adobe InDesign CS5.5 (7.5)" used to become authors and were then concatenated
into API queries, which is the direct cause of the worst mismatches in the
catalog.
"""
import re
import unicodedata

# Tool names, version strings, emails, URLs and bare numbers are never people.
_NOT_A_PERSON = re.compile(
    r"""
    \b(?:indesign|quark|framemaker|pagemaker|pagestream|acrobat|distiller|
        ghostscript|gpl\ ghostscript|pdftk|pdfsharp|itext|itextsharp|fpdf|tcpdf|
        latex|pdflatex|xelatex|lualatex|pdftex|tex\ live|miktex|dvips|hyperref|
        calibre|sigil|wkhtmltopdf|prince|princexml|reportlab|weasyprint|
        microsoft|word|excel|powerpoint|libreoffice|openoffice|writer|impress|
        scanner|scansnap|canon|epson|ricoh|xerox|kodak|fujitsu|brother|
        printer|preview|quartz|pdfcreator|nitro|foxit|pdf24|docutils|pandoc|
        abbyy|finereader|omnipage|readiris|paperport|imagemagick|photoshop|
        illustrator|coreldraw|publisher|antenna\ house|xmpie|
        unknown|untitled|administrator|admin|user|owner|guest|default)\b
  | \bpdf\b
  | \bocr\b
  | \bv?\d+\.\d+                      # version numbers: 2.02, v00.06.02, CS5.5
  | ^\S+@\S+$                          # bare email address
  | (?:www\.|https?://|\.com|\.org|\.info|\.net|\.co\.uk|\.pdf|\.doc)
  | ^\d+$                              # pure digits
  | ^[\W_]+$                           # punctuation only
    """,
    re.IGNORECASE | re.VERBOSE,
)

# Words that mark a string as a title fragment rather than a person.
_TITLE_WORDS = {
    "the", "a", "an", "and", "or", "of", "in", "on", "for", "with", "from",
    "how", "what", "why", "when", "introduction", "guide", "handbook",
    "learning", "programming", "building", "understanding", "mastering",
    "complete", "essential", "practical", "beginners", "beginner", "edition",
    "volume", "vol", "part", "chapter", "book", "books", "notes", "lecture",
    "manual", "tutorial", "course", "series", "study", "studies", "islam",
    "quran", "hadith", "history", "science", "data", "machine", "deep",
}

# Characters that appear in titles and publisher lines but not in person names.
# Apostrophes, periods and hyphens are allowed: O'Brien, Thomas S. Kuhn, Al-Ghazali.
_NOT_NAME_CHARS = re.compile(r"[&:;!?\"“”/\\|@#%*+=<>\[\]{}()]")

_HONORIFICS = {
    "dr", "dr.", "prof", "prof.", "professor", "mr", "mr.", "mrs", "mrs.",
    "ms", "ms.", "sir", "shaykh", "sheikh", "shaikh", "imam", "mufti",
    "maulana", "mawlana", "hafiz", "qari", "ustadh", "ustaz", "st", "st.",
}


def _has_cased_letters(s: str) -> bool:
    """True for scripts that distinguish case (Latin, Cyrillic, Greek …)."""
    return any(c.isalpha() and (c.isupper() or c.lower() != c) for c in s)


def _is_non_latin(s: str) -> bool:
    letters = [c for c in s if c.isalpha()]
    if not letters:
        return False
    non_latin = sum(1 for c in letters if "LATIN" not in unicodedata.name(c, ""))
    return non_latin > len(letters) / 2


def looks_like_tool(s: str) -> bool:
    """True if the string names software, a scanner, a URL or a version."""
    return bool(_NOT_A_PERSON.search(s or ""))


def is_person_name(s: str) -> bool:
    """
    Conservative test for "this string is a human name".

    Requires 2–5 tokens (which also kills the single-token authors produced by
    the old filename splitter), at least 5 characters, no tool/URL/version
    markers, and at least one capitalised token for cased scripts.
    """
    if not s:
        return False
    s = s.strip().strip(",;:")
    if len(s) < 5 or len(s) > 80:
        return False
    if looks_like_tool(s) or _NOT_NAME_CHARS.search(s):
        return False

    # "Khalidi, Rashid" is one name, not two tokens of a list.
    normalised = s.replace(",", " ")
    tokens = [t for t in re.split(r"\s+", normalised) if t]
    if not (2 <= len(tokens) <= 5):
        return False

    lowered = [t.lower().strip(".") for t in tokens]
    if sum(1 for t in lowered if t in _TITLE_WORDS) >= 2:
        return False
    # A name is mostly letters; reject "10th Anniversary Edition" style strings.
    if sum(1 for t in tokens if any(c.isdigit() for c in t)) > 0:
        return False

    meaningful = [t for t in lowered if t not in _HONORIFICS]
    if len(meaningful) < 1:
        return False

    if _is_non_latin(s):
        return True
    if _has_cased_letters(s) and not any(t[:1].isupper() for t in tokens):
        return False
    return True


def normalize_author(s: str) -> str:
    """Tidy an author string; flip "Last, First" into "First Last"."""
    if not s:
        return ""
    s = re.sub(r"\s+", " ", s).strip().strip(",;:").strip()
    s = re.sub(r"\s*\(.*?\)\s*$", "", s)          # trailing "(ed.)", "(2020)"
    s = re.sub(r"\b(ed|eds|editor|editors|trans|translator)\.?$", "", s, flags=re.I).strip(" ,")
    parts = [p.strip() for p in s.split(",")]
    if len(parts) == 2 and parts[0] and parts[1] and " " not in parts[0]:
        # "Khalidi, Rashid" → "Rashid Khalidi"
        return f"{parts[1]} {parts[0]}".strip()
    return s


def split_authors(raw: str) -> list[str]:
    """
    Split a raw author string into individual names.

    Handles ';', ' and ', ' & ', '/', and commas — but only splits on commas
    when the result does not look like a single "Last, First" name.
    """
    if not raw:
        return []
    raw = re.sub(r"\s+", " ", raw).strip()

    for delim in [";", " and ", " & ", " AND ", "|", "/"]:
        if delim in raw:
            parts = [p for p in (x.strip() for x in raw.split(delim)) if p]
            out: list[str] = []
            for p in parts:
                out.extend(split_authors(p))
            return out

    if raw.count(",") >= 2:
        return [p.strip() for p in raw.split(",") if p.strip()]
    if raw.count(",") == 1:
        left, right = (p.strip() for p in raw.split(","))
        # "Kuhn, Thomas S." is one person; "Marx, Engels" is two.
        if left and right and (" " in right or len(right.split()) == 1 and len(right) <= 20):
            return [normalize_author(raw)]
        return [left, right]
    return [raw]


def clean_authors(candidates, limit: int = 5) -> list[str]:
    """Normalise, validate and de-duplicate a list of author candidates."""
    out: list[str] = []
    seen: set[str] = set()
    for raw in candidates or []:
        if not isinstance(raw, str):
            continue
        for part in split_authors(raw):
            name = normalize_author(part)
            if not is_person_name(name):
                continue
            key = re.sub(r"[^a-z]", "", name.lower())
            if key and key not in seen:
                seen.add(key)
                out.append(name)
            if len(out) >= limit:
                return out
    return out
