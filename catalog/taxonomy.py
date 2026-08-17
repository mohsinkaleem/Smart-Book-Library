"""
Controlled category vocabulary.

`categories` used to be a bucket that four unreconciled sources wrote into —
the internal taxonomy, Google's BISAC headings, raw OpenLibrary subjects and
free-form LLM output — producing 51 labels over 120 books, 27 of them used
exactly once, with `Computers`/`Computer Science` and `Religion`/`Religion &
Philosophy`/`Islam & Islamic Studies` splitting the same facet three ways
rather than inventing one per book.

Rules now:

* `categories` may only contain labels from `CANONICAL_CATEGORIES`;
* everything external is kept verbatim in `subjects_raw` — searchable through
  FTS, never shown as a facet;
* external labels are mapped through `ALIASES` where an equivalent exists;
* subjects that are person names or bare common nouns are dropped.
"""
import re

from .names import is_person_name

# ─── Canonical vocabulary ───────────────────────────────────────────────────────
CATEGORY_KEYWORDS: dict[str, list[str]] = {
    "Computer Science": [
        "programming", "algorithm", "software", "computer", "source code", "coding",
        "python", "java", "javascript", "c++", "database", "web development",
        "data structure", "api", "framework", "linux", "terminal", "command line",
        "git", "docker", "kubernetes", "compiler", "operating system", "networking",
        "software engineering", "devops", "microservices",
    ],
    "Data Science & ML": [
        "data science", "machine learning", "deep learning", "neural network",
        "regression", "classification", "clustering", "natural language processing",
        "computer vision", "recommendation system", "time series", "feature engineering",
        "model training", "gradient descent", "kaggle", "data analysis", "data mining",
        "big data", "pandas", "numpy", "scikit-learn", "tensorflow", "pytorch",
        "causal inference", "bayesian", "reinforcement learning", "embedding",
        "artificial intelligence",
    ],
    "Mathematics & Physics": [
        "mathematics", "algebra", "calculus", "geometry", "topology", "probability",
        "statistics", "linear algebra", "matrix", "physics", "quantum", "relativity",
        "cosmology", "spacetime", "theorem", "proof", "differential equation",
        "integral", "optimization",
    ],
    "Islam & Islamic Studies": [
        "quran", "qur'an", "hadith", "sunnah", "prophet muhammad", "islamic",
        "muslim", "mosque", "salat", "fiqh", "shariah", "sharia", "tawheed",
        "aqeedah", "dawah", "ummah", "khalifah", "caliphate", "imam", "shaykh",
        "deen", "haram", "halal", "ramadan", "hajj", "zakat", "allah", "hijab",
        "fatwa", "tafsir", "sahih", "bukhari", "tajweed", "salafi", "sufi", "madhhab",
    ],
    "Religion & Philosophy": [
        "religion", "theology", "philosophy", "metaphysics", "ethics", "morality",
        "atheism", "theism", "divine", "spiritual", "secular", "belief", "faith",
        "soul", "consciousness", "existential", "phenomenology", "epistemology",
        "ontology", "scripture",
    ],
    "History": [
        "history", "historical", "ancient", "medieval", "empire", "dynasty",
        "revolution", "civilization", "colonial", "independence", "chronicle",
        "ottoman", "mughal", "crusade", "antiquity", "historiography",
    ],
    "Politics & Geopolitics": [
        "politics", "political", "democracy", "government", "nationalism",
        "imperialism", "colonialism", "capitalism", "socialism", "communism",
        "liberalism", "geopolitics", "foreign policy", "diplomacy", "lobby",
        "zionism", "palestine", "parliament", "ideology", "statecraft",
    ],
    "Economics & Finance": [
        "economics", "economy", "finance", "financial", "banking", "investment",
        "stock market", "trading", "corporate finance", "inflation", "gdp",
        "monetary", "fiscal", "startup", "entrepreneur", "wealth", "profit", "debt",
        "business",
    ],
    "Psychology & Self-Help": [
        "psychology", "psychological", "cognitive", "behaviour", "behavior",
        "emotion", "anxiety", "depression", "therapy", "self-help", "motivation",
        "habit", "mindset", "productivity", "happiness", "well-being", "confidence",
    ],
    "Literature & Fiction": [
        "novel", "fiction", "short story", "narrative", "protagonist", "literary",
        "prose", "poetry", "poem", "chapter one", "once upon", "playwright",
    ],
    "Gender & Society": [
        "gender", "feminism", "feminist", "masculinity", "sexuality", "transgender",
        "patriarchy", "women's rights", "social justice", "discrimination",
        "equality", "modesty", "sociology",
    ],
    "Security & Hacking": [
        "hacking", "penetration testing", "cybersecurity", "vulnerability", "exploit",
        "malware", "ethical hacking", "reverse engineering", "encryption", "forensic",
        "authentication", "firewall",
    ],
    "Science & Nature": [
        "biology", "chemistry", "evolution", "darwin", "genetics", "dna", "ecology",
        "environment", "climate", "astronomy", "cosmos", "species", "scientific method",
        "natural history",
    ],
    "Health & Wellness": [
        "health", "medical", "medicine", "nutrition", "diet", "exercise", "fitness",
        "healing", "herbal", "anatomy", "disease", "wellness", "mental health",
    ],
    "Language & Communication": [
        "language", "grammar", "vocabulary", "arabic language", "linguistics",
        "pronunciation", "fluency", "conversation", "rhetoric", "translation",
    ],
    "Biography & Memoir": [
        "biography", "memoir", "autobiography", "life of", "his life", "her life",
        "diaries", "letters of",
    ],
    "Education & Reference": [
        "textbook", "curriculum", "syllabus", "lecture notes", "exam", "encyclopedia",
        "dictionary", "reference guide", "study guide", "pedagogy",
    ],
}

CANONICAL_CATEGORIES: list[str] = list(CATEGORY_KEYWORDS.keys())

THEME_PATTERNS: dict[str, list[str]] = {
    "Critique of Modernity": [
        "modernity", "modern world", "secularism", "postmodern", "disenchantment",
        "materialism", "nihilism",
    ],
    "East-West Relations": [
        "east and west", "orientalism", "occidental", "clash of civilizations",
        "cultural exchange", "post-colonial", "colonial encounter",
    ],
    "Social Reform": [
        "reform", "social change", "awakening", "activism", "social movement",
    ],
    "Technology & Society": [
        "technology", "digital", "internet", "social media", "automation",
        "disruption", "innovation",
    ],
    "Ethical Living": [
        "ethics", "moral", "virtue", "character", "integrity", "manners",
        "etiquette", "righteousness",
    ],
    "Knowledge & Education": [
        "knowledge", "education", "learning", "teaching", "scholarship",
        "intellectual", "academic", "wisdom", "curriculum",
    ],
    "Identity & Belonging": [
        "identity", "belonging", "community", "tradition", "heritage",
        "diaspora", "migration",
    ],
    "Power & Resistance": [
        "resistance", "oppression", "liberation", "hegemony", "propaganda",
        "freedom", "struggle",
    ],
    "Practical Skills & Career": [
        "career", "interview", "skill", "professional", "craft", "mastery",
        "certification", "portfolio",
    ],
    "Personal Development": [
        "self-improvement", "growth", "productivity", "habits", "goal setting",
        "discipline", "mindfulness", "success",
    ],
}

# ─── External label → canonical ─────────────────────────────────────────────────
ALIASES: dict[str, str] = {
    # Google Books / BISAC headings
    "computers": "Computer Science",
    "computer science": "Computer Science",
    "computer engineering": "Computer Science",
    "programming": "Computer Science",
    "technology & engineering": "Computer Science",
    "artificial intelligence": "Data Science & ML",
    "data mining": "Data Science & ML",
    "machine learning": "Data Science & ML",
    "statistics": "Mathematics & Physics",
    "mathematics": "Mathematics & Physics",
    "science": "Science & Nature",
    "nature": "Science & Nature",
    "religion": "Religion & Philosophy",
    "philosophy": "Religion & Philosophy",
    "body, mind & spirit": "Religion & Philosophy",
    "islam": "Islam & Islamic Studies",
    "islamic studies": "Islam & Islamic Studies",
    "islam & islamic studies": "Islam & Islamic Studies",
    "muslims": "Islam & Islamic Studies",
    "koran": "Islam & Islamic Studies",
    "qur'an": "Islam & Islamic Studies",
    "business & economics": "Economics & Finance",
    "business": "Economics & Finance",
    "economics": "Economics & Finance",
    "finance": "Economics & Finance",
    "political science": "Politics & Geopolitics",
    "politics": "Politics & Geopolitics",
    "international relations": "Politics & Geopolitics",
    "history": "History",
    "psychology": "Psychology & Self-Help",
    "self-help": "Psychology & Self-Help",
    "self help": "Psychology & Self-Help",
    "fiction": "Literature & Fiction",
    "literary criticism": "Literature & Fiction",
    "literary collections": "Literature & Fiction",
    "poetry": "Literature & Fiction",
    "drama": "Literature & Fiction",
    "social science": "Gender & Society",
    "sociology": "Gender & Society",
    "social sciences": "Gender & Society",
    "women's studies": "Gender & Society",
    "gender studies": "Gender & Society",
    "computer security": "Security & Hacking",
    "computer crimes": "Security & Hacking",
    "security": "Security & Hacking",
    "health & fitness": "Health & Wellness",
    "medical": "Health & Wellness",
    "medicine": "Health & Wellness",
    "cooking": "Health & Wellness",
    "language arts & disciplines": "Language & Communication",
    "foreign language study": "Language & Communication",
    "language": "Language & Communication",
    "linguistics": "Language & Communication",
    "biography & autobiography": "Biography & Memoir",
    "biography": "Biography & Memoir",
    "autobiography": "Biography & Memoir",
    "education": "Education & Reference",
    "study aids": "Education & Reference",
    "reference": "Education & Reference",
}

# Subjects that are structurally useless as facets.
_JUNK_SUBJECT = re.compile(
    r"^(?:general|miscellaneous|other|unclassified|nonfiction|non-fiction|"
    r"electronic books?|open library staff picks|accessible book|"
    r"protected daisy|in library|internet archive wishlist|overdrive)\b",
    re.IGNORECASE,
)
# Bare common nouns carry no discriminating power on their own.
_TOO_GENERIC = {
    "life", "people", "history", "world", "man", "men", "women", "human beings",
    "society", "book", "books", "study", "studies", "thought", "work", "works",
    "faith", "god", "religion", "science", "relations", "criticism",
    "interpretation", "biography", "collections", "reading",
}


def normalize_label(label: str) -> str:
    label = re.sub(r"\s+", " ", (label or "")).strip().strip(".,;:")
    label = re.sub(r"\s*--\s*", " — ", label)
    return label


def map_to_canonical(label: str) -> str:
    """Map an external subject/category label to the controlled vocabulary."""
    if not label:
        return ""
    clean = normalize_label(label).lower().strip(" .")
    if not clean:
        return ""
    for canonical in CANONICAL_CATEGORIES:
        if clean == canonical.lower():
            return canonical
    if clean in ALIASES:
        return ALIASES[clean]
    # "Computers / Programming / General" — try the leading segment.
    head = re.split(r"\s*[/—>|]\s*", clean)[0].strip()
    if head and head != clean:
        if head in ALIASES:
            return ALIASES[head]
        for canonical in CANONICAL_CATEGORIES:
            if head == canonical.lower():
                return canonical
    return ""


def is_junk_subject(label: str) -> bool:
    """Person names, boilerplate archive tags and bare nouns are not subjects."""
    clean = normalize_label(label)
    if not clean or len(clean) < 3 or len(clean) > 80:
        return True
    if _JUNK_SUBJECT.match(clean):
        return True
    if clean.lower() in _TOO_GENERIC:
        return True
    # "Asad, Muhammad" is a person, not a topic.
    if "," in clean and is_person_name(clean):
        return True
    if not re.search(r"[^\W\d_]", clean, re.UNICODE):
        return True
    return False


def clean_subjects(subjects, limit: int = 25) -> list[str]:
    """Normalise and filter raw external subjects for `subjects_raw`."""
    out: list[str] = []
    seen: set[str] = set()
    for raw in subjects or []:
        if not isinstance(raw, str):
            continue
        label = normalize_label(raw)
        if is_junk_subject(label):
            continue
        key = label.lower()
        if key in seen:
            continue
        seen.add(key)
        out.append(label)
        if len(out) >= limit:
            break
    return out


def categories_from_subjects(subjects) -> list[str]:
    """Canonical categories implied by external subjects, in order."""
    out: list[str] = []
    for raw in subjects or []:
        canonical = map_to_canonical(raw)
        if canonical and canonical not in out:
            out.append(canonical)
    return out


def constrain_categories(labels, limit: int = 5) -> list[str]:
    """Force any list of labels into the controlled vocabulary."""
    out: list[str] = []
    for label in labels or []:
        canonical = label if label in CANONICAL_CATEGORIES else map_to_canonical(label)
        if canonical and canonical not in out:
            out.append(canonical)
        if len(out) >= limit:
            break
    return out
