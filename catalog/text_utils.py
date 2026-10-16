"""
Text partitioning, title-page parsing and script/language detection.

`text_excerpt` used to serve three incompatible purposes: reader preview,
embedding input and (implicitly) evidence. For two thirds of the catalog its
first characters are a copyright page, so summaries described copyright pages
and unrelated books looked similar to each other because their boilerplate
matched.

It is now split three ways:

* ``front_matter``   — pages 1–5, parsed positionally for evidence. Never embedded.
* ``content_sample`` — prose that starts past the TOC. Embedded and summarised.
* ``text_excerpt``   — unchanged, for the reader preview.
"""
import re
import unicodedata
from typing import Optional

from .config import (
    CONTENT_SAMPLE_MAX_CHARS,
    CONTENT_SAMPLE_MIN_PROSE_CHARS,
    FRONT_MATTER_MAX_CHARS,
    FRONT_MATTER_PAGES,
    MAX_TEXT_EXCERPT_CHARS,
)
from .names import is_person_name, is_tool_title, looks_like_tool, normalize_author

# Dot leaders ("Chapter 3 .......... 42") mark a table of contents.
_DOT_LEADER = re.compile(r"\.{4,}\s*\d+|\·{4,}\s*\d+|_{4,}\s*\d+")
_BOILERPLATE = re.compile(
    r"""copyright|all\ rights\ reserved|©|isbn|printed\ in|first\ (?:published|edition)|
        library\ of\ congress|british\ library|cataloguing|no\ part\ of\ this|
        typeset|reproduced|permission\ of\ the\ publisher|www\.|http|@|
        table\ of\ contents|contents$|acknowledg|dedication|about\ the\ author|
        # Digitisation and format-conversion notices. Scanned and EPUB-converted
        # books carry these on the title page itself, where they read as a
        # subtitle: "This book was produced in EPUB format by the Internet
        # Archive." Kept narrow — a bare "produced" is ordinary prose.
        internet\ archive|digiti[sz]ed\ by|scanned\ by|
        produced\ in\ \w+\ format|
        this\ (?:book|file|e-?book|edition)\ was\ (?:produced|created|made|
            converted|generated|digiti[sz]ed|scanned)""",
    re.IGNORECASE | re.VERBOSE,
)
_PUBLISHER_HINT = re.compile(
    r"\b(press|publish(?:er|ing|ers|ications?)?|books|editions?|verlag|"
    r"house|media|academic|university)\b",
    re.IGNORECASE,
)
_BY_LINE = re.compile(r"^\s*(?:by|written\s+by|author[:\s])\s*[:\-]?\s*(.+)$", re.I)

# Dedication openers. "My dear Hodgson" and "To my mother" read as three-token
# person names and were being harvested as authors off the dedication page.
_DEDICATION_OPENER = re.compile(r"^\s*(?:to|for|my|our|dear|dedicated)\b", re.IGNORECASE)

# Lines that are not titles even though they sit where a title sits.
_TITLE_JUNK = re.compile(
    r"uni[0-9A-Fa-f]{4}|\.(?:alt\d|isol|init|medi|fina)\b"   # broken glyph names
    r"|\bISSN\b|\bISBN\b|\bDOI\b|\bMHID\b"
    r"|\bvol\.?\s*\d|\bno\.?\s*\d|\bissue\s*\d|\bpp?\.\s*\d"  # journal furniture
    r"|\d{4}\s*[-–]\s*\d{4}"
    r"|^\W*\d+\W*$",
    re.IGNORECASE,
)
# Institutions and imprints are not people.
_INSTITUTION = re.compile(
    r"\b(college|university|institute|institution|department|faculty|school|"
    r"academy|society|foundation|centre|center|press|publish\w*|journal|"
    r"library|museum|trust|company|ltd|inc|llc|gmbh|association|council|"
    r"ministry|committee|edition|volume|series|usa|uk|"
    # places — a line naming one is an address block, not a byline
    r"united|kingdom|states|america|england|scotland|wales|ireland|canada|"
    r"australia|india|pakistan|arabia|egypt|london|york|cambridge|oxford|"
    r"street|avenue|road|city)\b",
    re.IGNORECASE,
)
# Function words that never appear inside a bare author line but are common in
# title fragments ("More than Eighty", "Ways to Make", "Perspectives on X").
_AUTHOR_STOPWORDS = {
    "a", "an", "the", "and", "or", "of", "on", "in", "at", "to", "for", "with",
    "from", "than", "more", "less", "how", "what", "why", "ways", "way",
    "make", "making", "vol", "no", "part", "chapter", "introduction", "name",
    "book", "books", "present", "publication", "edition",
}


def fold(text: str) -> str:
    """
    ASCII-fold for comparison: strips diacritics, apostrophes and case.

    Transliterations differ between the filename and the title page —
    `Aisha.pdf` versus "‘Ā’ISHA, MOTHER OF THE FAITHFUL" — and without folding
    they share no tokens at all.
    """
    decomposed = unicodedata.normalize("NFKD", text or "")
    stripped = "".join(c for c in decomposed if not unicodedata.combining(c))
    stripped = re.sub(r"[’'`´ʻʼ]", "", stripped)
    return re.sub(r"[^a-z0-9\s]", " ", stripped.lower())


def _overlap(a: str, b: str) -> int:
    """Count of shared significant word tokens between two folded strings."""
    tokens_a = {t for t in fold(a).split() if len(t) > 2}
    tokens_b = {t for t in fold(b).split() if len(t) > 2}
    return len(tokens_a & tokens_b)


def _is_plausible_title(line: str) -> bool:
    """Reject glyph junk, journal furniture and letter-spaced OCR artefacts."""
    if not line or not (3 <= len(line) <= 140):
        return False
    if _TITLE_JUNK.search(line):
        return False
    letters = sum(1 for c in line if c.isalpha())
    if letters < len(line) * 0.55:
        return False
    tokens = line.split()
    if not tokens:
        return False
    # "W hat is V e r si o n Co n tr o l?" — extraction split the words up.
    short = sum(1 for t in tokens if len(t) <= 2)
    if len(tokens) >= 4 and short > len(tokens) * 0.4:
        return False
    return True


def _is_blurb_sentence(line: str) -> bool:
    """A punctuated multi-word sentence — prose from a blurb or a notice."""
    return line.endswith((".", ",", ";")) and len(line.split()) > 8


def _is_plausible_author_line(line: str) -> bool:
    """A bare line qualifies as an author only if it reads like a name."""
    if _INSTITUTION.search(line) or _TITLE_JUNK.search(line):
        return False
    if _DEDICATION_OPENER.match(line):
        return False
    tokens = [t.strip(".,").lower() for t in line.split()]
    if not (2 <= len(tokens) <= 4):
        return False
    if any(t in _AUTHOR_STOPWORDS for t in tokens):
        return False
    # Every token of a name is a word, not a stray mark ("name ‘").
    if any(sum(1 for c in t if c.isalpha()) < 2 for t in tokens):
        return False
    return is_person_name(line)


# ── Page cleaning ───────────────────────────────────────────────────────────────

# Control characters that survive extraction — form feeds from OCR, stray
# device codes from a PDF text run. Tab (\x09) and newline (\x0a) are kept.
_CONTROL_CHARS = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f]")


def clean_page(text: str, keep_blank_lines: bool = False) -> str:
    """
    Tidy one page (PDF), spine item (EPUB) or OCR'd image.

    Collapse runs of spaces, drop lines that are only a page number, drop
    one- to three-character line noise. Anything more aggressive
    (de-hyphenation, header/footer stripping) shifts character offsets in ways
    `full_text`'s offset map has to reason about, and buys little at chunk
    scale.

    `keep_blank_lines` is for OCR, where a blank line is the only paragraph
    structure the page has left; runs of them collapse to one.
    """
    if not text:
        return ""
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    text = _CONTROL_CHARS.sub("", text)
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"^\s*\d+\s*$", "", text, flags=re.MULTILINE)

    lines: list[str] = []
    for line in text.split("\n"):
        stripped = line.strip()
        if stripped and (len(stripped) > 3 or stripped in {".", ",", ":", ";"}):
            lines.append(stripped)
        elif keep_blank_lines and lines and lines[-1] != "":
            lines.append("")
    return "\n".join(lines).strip("\n")


# ── Partitioning ────────────────────────────────────────────────────────────────

def looks_like_toc(page_text: str) -> bool:
    return bool(_DOT_LEADER.search(page_text or ""))


def prose_score(page_text: str) -> int:
    """Characters that belong to sentence-like lines (rough prose measure)."""
    if not page_text:
        return 0
    if looks_like_toc(page_text):
        return 0
    total = 0
    for line in page_text.split("\n"):
        stripped = line.strip()
        if len(stripped) < 40:
            continue
        letters = sum(1 for c in stripped if c.isalpha())
        if letters < len(stripped) * 0.6:
            continue
        total += len(stripped)
    return total


def partition_pages(pages: list[str]) -> dict:
    """
    Split a list of per-page texts into front matter, a content sample and the
    reader excerpt.
    """
    pages = [p for p in (pages or []) if p and p.strip()]
    if not pages:
        return {"front_matter": "", "content_sample": "", "text_excerpt": ""}

    front = "\n\n".join(pages[:FRONT_MATTER_PAGES])[:FRONT_MATTER_MAX_CHARS]

    start = 0
    for i, page in enumerate(pages):
        if prose_score(page) >= CONTENT_SAMPLE_MIN_PROSE_CHARS:
            start = i
            break
    else:
        start = min(len(pages) - 1, FRONT_MATTER_PAGES)

    sample_parts: list[str] = []
    length = 0
    for page in pages[start:]:
        if looks_like_toc(page):
            continue
        sample_parts.append(page.strip())
        length += len(page)
        if length >= CONTENT_SAMPLE_MAX_CHARS:
            break
    content_sample = "\n\n".join(sample_parts)[:CONTENT_SAMPLE_MAX_CHARS]

    excerpt = "\n\n".join(pages)[:MAX_TEXT_EXCERPT_CHARS]
    return {
        "front_matter": front,
        "content_sample": content_sample,
        "text_excerpt": excerpt,
    }


# ── Title-page parsing ──────────────────────────────────────────────────────────

def _candidate_lines(front_matter: str, limit: int = 25) -> list[str]:
    lines = []
    for raw in (front_matter or "").split("\n"):
        line = re.sub(r"\s+", " ", raw).strip(" \t·•|—-")
        if not line or len(line) < 2:
            continue
        lines.append(line)
        if len(lines) >= limit:
            break
    return lines


def parse_front_matter(front_matter: str, hint: str = "") -> dict:
    """
    Read a title page positionally.

    The title page carries title, subtitle, author and publisher in a reliable
    order and is better evidence than the filename. Returns whatever it can
    identify; every value is a *candidate*, to be scored, not applied blindly.

    `hint` is the filename-derived title. When a line on the page echoes it,
    that line wins — page 1 of a journal PDF carries the running header of a
    different article above the real one, and the filename is the tie-breaker.
    """
    result: dict = {"title": "", "subtitle": "", "authors": [], "publisher": "", "lines": []}
    lines = _candidate_lines(front_matter)
    if not lines:
        return result

    result["lines"] = lines[:12]

    plausible: list[tuple[int, str]] = []
    for i, line in enumerate(lines[:12]):
        if _BOILERPLATE.search(line) or is_tool_title(line):
            continue
        if _BY_LINE.match(line):
            continue
        if not _is_plausible_title(line):
            continue
        if _is_blurb_sentence(line):
            continue          # a sentence from a blurb, not a title
        if is_person_name(line) and i > 0 and not (hint and _overlap(line, hint)):
            continue          # the author line — unless the filename says otherwise
        plausible.append((i, line))

    title_idx: Optional[int] = None
    if plausible:
        title_idx, title = plausible[0]
        if hint:
            best = max(plausible, key=lambda pair: (_overlap(pair[1], hint), -pair[0]))
            if _overlap(best[1], hint) > 0:
                title_idx, title = best
        result["title"] = title

    if title_idx is not None:
        for line in lines[title_idx + 1: title_idx + 4]:
            if _BOILERPLATE.search(line) or is_person_name(line):
                continue
            if not _is_plausible_title(line):
                continue
            if _is_blurb_sentence(line):
                continue          # the same guard the title line gets
            if 4 <= len(line) <= 140 and not _PUBLISHER_HINT.search(line):
                result["subtitle"] = line
                break

    # An explicit "by …" line is authoritative; bare lines must look like names
    # and must not be institutions or title fragments ("Ways to Make", "Carthage
    # College Kenosha, Wisconsin, USA").
    for line in lines[:16]:
        m = _BY_LINE.match(line)
        if not m:
            continue
        for part in re.split(r"\s*(?:,| and | & )\s*", m.group(1)):
            name = normalize_author(part)
            if name and is_person_name(name) and name not in result["authors"]:
                result["authors"].append(name)

    if not result["authors"]:
        for i, line in enumerate(lines[:14]):
            if i == title_idx or _BOILERPLATE.search(line) or looks_like_tool(line):
                continue
            if _is_plausible_author_line(line):
                name = normalize_author(line)
                if name and name not in result["authors"]:
                    result["authors"].append(name)
            if len(result["authors"]) >= 2:
                break

    for line in lines[:20]:
        if _BOILERPLATE.search(line):
            continue
        if _PUBLISHER_HINT.search(line) and len(line) <= 60 and not is_person_name(line):
            result["publisher"] = line.strip(" .,")
            break

    return result


# ── Script & language ───────────────────────────────────────────────────────────

_SCRIPT_RANGES = [
    ("arabic", (0x0600, 0x06FF)),
    ("arabic", (0x0750, 0x077F)),
    ("arabic", (0xFB50, 0xFDFF)),
    ("arabic", (0xFE70, 0xFEFF)),
    ("devanagari", (0x0900, 0x097F)),
    ("cyrillic", (0x0400, 0x04FF)),
    ("greek", (0x0370, 0x03FF)),
    ("hebrew", (0x0590, 0x05FF)),
    ("cjk", (0x4E00, 0x9FFF)),
]

# Letters used in Urdu but not in Arabic.
_URDU_MARKERS = set("ٹڈڑںھےۓپچژگ")
_ENGLISH_STOPWORDS = {
    "the", "and", "of", "to", "in", "that", "is", "for", "with", "was", "this",
    "as", "are", "be", "by", "not", "from", "which", "have", "has",
}


def detect_script(text: str) -> str:
    """Dominant script of a text sample."""
    if not text:
        return ""
    counts: dict[str, int] = {}
    latin = 0
    for ch in text[:4000]:
        if not ch.isalpha():
            continue
        code = ord(ch)
        matched = False
        for name, (lo, hi) in _SCRIPT_RANGES:
            if lo <= code <= hi:
                counts[name] = counts.get(name, 0) + 1
                matched = True
                break
        if not matched and "LATIN" in unicodedata.name(ch, ""):
            latin += 1
    counts["latin"] = latin
    if not any(counts.values()):
        return ""
    return max(counts.items(), key=lambda kv: kv[1])[0]


def detect_language(text: str, script: str = "") -> str:
    """
    Best-effort ISO 639-1 language code.

    Uses `langdetect` when installed, otherwise a script + stop-word heuristic.
    Never guesses "en" for a non-Latin script — that was producing English
    keyword noise for the Arabic and Urdu material (§M5).
    """
    if not text or len(text.strip()) < 40:
        return ""
    script = script or detect_script(text)

    if script == "arabic":
        sample = set(text[:4000])
        return "ur" if sample & _URDU_MARKERS else "ar"
    if script in ("devanagari", "cyrillic", "greek", "hebrew", "cjk"):
        return {"devanagari": "hi", "cyrillic": "ru", "greek": "el",
                "hebrew": "he", "cjk": "zh"}[script]

    try:  # optional dependency
        from langdetect import detect, DetectorFactory  # type: ignore
        DetectorFactory.seed = 0
        return detect(text[:2000])
    except Exception:
        pass

    words = re.findall(r"[a-zA-Z']+", text[:3000].lower())
    if not words:
        return ""
    hits = sum(1 for w in words if w in _ENGLISH_STOPWORDS)
    return "en" if hits >= max(5, len(words) * 0.03) else ""


def is_mostly_boilerplate(text: str) -> bool:
    """True when a passage is dominated by copyright-page phrases."""
    if not text:
        return False
    head = text[:800]
    hits = len(_BOILERPLATE.findall(head))
    return hits >= 3
