"""
Title parser - cleans and normalizes book titles extracted from filenames.

Handles common patterns from library genesis, dokumen.pub, z-lib, etc.
"""
import re
import logging

logger = logging.getLogger(__name__)

# Patterns to strip from filenames (order matters)
STRIP_PATTERNS = [
    # Source site prefixes
    r"^dokumen\.pub_",
    r"^ebin\.pub_",
    r"^vdoc\.pub_",
    r"^kupdf\.net_",
    r"^pdfcoffee\.com_",
    r"^toaz\.info-",
    r"^noor-book\.com\s+",
    r"^\[\]\s*",
    # Libgen suffix
    r"\s*-\s*libgen\.li$",
    # Z-lib suffix
    r"\s*\(z-lib\.org\)$",
    r"\s*\(z-lib\.org\)\s*$",
    # PDFDrive suffix
    r"\s*\(\s*PDFDrive(?:\.com)?\s*\)$",
    # book-drive.com suffix
    r"\s*\(book-drive\.com\)$",
    # Internet Archive identifiers
    r"_[a-z0-9]+goog$",       # e.g. indianmusalmans02huntgoog
    # ISBN patterns in filename
    r"\b\d{10,13}\b",
    # Trailing copy/duplicate markers
    r"\s*\(\d+\)$",           # e.g. (1) at end
    r"\s+copy$",
    r"\s+copy\s+\d*$",
    # Random hash-like prefixes
    r"^[0-9a-f]{20,}_",
    # Numeric prefixes like "10. "
    r"^\d+\.\s+",
    # Underscores to spaces
]

# Publisher patterns commonly in filenames
PUBLISHER_PATTERNS = [
    r"-\s*O'Reilly\s+Media(?:,\s*Inc\.?)?\s*\(\d{4}\)",
    r"-\s*Packt\s+Publishing(?:\s+Ltd)?\s*\(\d{4}\)",
    r"-\s*Manning(?:\s+Publications?)?\s*\(\d{4}\)",
    r"-\s*Springer(?:\s+International)?\s*\(\d{4}\)",
    r"-\s*(?:Prentice\s+Hall|Wiley|McGraw.Hill|Cambridge|Oxford|Harvard)\s*\(\d{4}\)",
    r"-\s*[A-Z][a-z]+(?:\s+[A-Z][a-z]+)*\s+(?:Press|Publishing|Publications|Books)\s*\(\d{4}\)",
]

# Year extraction pattern
YEAR_PATTERN = re.compile(r"\((\d{4})(?:[,_/]\s*[^)]+)?\)")
# Author - Title pattern (common in libgen downloads)
AUTHOR_TITLE_PATTERN = re.compile(
    r"^([A-Z][a-zA-Z\s.,]+?)\s*-\s*(.+)$"
)
# Author, First - Title pattern
AUTHOR_COMMA_PATTERN = re.compile(
    r"^([A-Z][a-zA-Z]+),\s*([A-Z][a-zA-Z\s.]+?)\s*-\s*(.+)$"
)


def extract_year_from_filename(filename: str) -> int | None:
    """Extract publication year from filename."""
    matches = YEAR_PATTERN.findall(filename)
    for year_str in matches:
        year = int(year_str) if isinstance(year_str, str) else int(year_str)
        if 1800 <= year <= 2030:
            return year
    return None


def extract_author_from_filename(filename: str) -> list[str]:
    """Try to extract author names from filename."""
    # Pattern: "Last, First - Title"
    m = AUTHOR_COMMA_PATTERN.match(filename)
    if m:
        last, first, _ = m.groups()
        return [f"{first.strip()} {last.strip()}"]

    # Pattern: "Author Name - Title"
    m = AUTHOR_TITLE_PATTERN.match(filename)
    if m:
        author_part = m.group(1).strip()
        # Validate: author names shouldn't be too long or contain certain words
        if len(author_part.split()) <= 5 and not any(
            w in author_part.lower()
            for w in ["the", "how", "what", "why", "introduction", "guide",
                       "handbook", "learning", "programming", "building"]
        ):
            return [author_part]
    return []


def extract_publisher_from_filename(filename: str) -> str:
    """Try to extract publisher from filename."""
    # Common publisher patterns in parentheses
    pub_pattern = re.compile(
        r"[-_]\s*(O'Reilly Media|Packt Publishing|Manning Publications?|"
        r"Springer|Prentice Hall|Wiley|McGraw.Hill|Cambridge University Press|"
        r"Oxford University Press|Harvard University Press|Grove Press|"
        r"Penguin Books?|Random House|Free Press|Columbia University Press|"
        r"Oneworld Publications?|FT Publishing|Independently Published|"
        r"Equilibra Press|The Book Foundation|Bayt Al-Hikma Press|"
        r"Turath Publishing|Rigel Publishing|University of Chicago Press|"
        r"Farrar,?\s*Straus.*?Giroux|Citadel Press|American Trust Publications|"
        r"Hurst|Brill|For Dummies)",
        re.IGNORECASE,
    )
    m = pub_pattern.search(filename)
    return m.group(1).strip() if m else ""


def clean_title(filename: str) -> str:
    """
    Clean a book filename into a human-readable title.

    Steps:
    1. Remove file extension
    2. Strip source-site prefixes/suffixes
    3. Remove publisher and year info (captured separately)
    4. Separate author from title if present
    5. Clean up whitespace and special chars
    """
    # Remove extension
    name = re.sub(r"\.\w{2,5}$", "", filename)

    # Apply strip patterns
    for pattern in STRIP_PATTERNS:
        name = re.sub(pattern, "", name, flags=re.IGNORECASE)

    # Remove publisher patterns
    for pattern in PUBLISHER_PATTERNS:
        name = re.sub(pattern, "", name, flags=re.IGNORECASE)

    # Remove year+publisher combos like "(2019, Equilibra Press)"
    name = re.sub(r"\(\d{4},?\s*[^)]*\)", "", name)
    # Remove standalone years in parens like "(2022)"
    name = re.sub(r"\(\d{4}\)", "", name)

    # Try to separate author from title
    m = AUTHOR_COMMA_PATTERN.match(name)
    if m:
        _, _, title = m.groups()
        name = title
    else:
        m = AUTHOR_TITLE_PATTERN.match(name)
        if m:
            author_part = m.group(1).strip()
            title_part = m.group(2).strip()
            # Only treat as author-title if author looks like a name
            if len(author_part.split()) <= 5 and not any(
                w in author_part.lower()
                for w in ["the", "how", "what", "why", "introduction", "guide",
                           "handbook", "learning", "building", "data", "machine"]
            ):
                name = title_part

    # Clean up underscores, hyphens used as spaces
    name = name.replace("_", " ")
    # Replace multiple hyphens with single
    name = re.sub(r"\s*-\s*-\s*", " - ", name)

    # Remove leading/trailing hyphens and whitespace
    name = name.strip(" -_.,;:")

    # Collapse multiple spaces
    name = re.sub(r"\s+", " ", name)

    # Remove trailing " - " fragments
    name = re.sub(r"\s*-\s*$", "", name)

    # Title case if all lowercase or all uppercase
    if name == name.lower() or name == name.upper():
        # Smart title case - keep small words lowercase except at start
        words = name.split()
        small_words = {"a", "an", "the", "and", "or", "but", "in", "on", "at",
                        "to", "for", "of", "with", "by", "from", "vs", "vs."}
        result = []
        for i, word in enumerate(words):
            if i == 0 or word.lower() not in small_words:
                result.append(word.capitalize())
            else:
                result.append(word.lower())
        name = " ".join(result)

    return name.strip()


def parse_filename(filename: str) -> dict:
    """
    Parse a book filename and extract all available metadata.

    Returns dict with: title, authors, publisher, publication_year
    """
    result = {
        "title": clean_title(filename),
        "authors": extract_author_from_filename(
            re.sub(r"\.\w{2,5}$", "", filename)
        ),
        "publisher": extract_publisher_from_filename(filename),
        "publication_year": extract_year_from_filename(filename),
    }

    logger.debug(f"Parsed '{filename}' -> {result}")
    return result
