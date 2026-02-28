"""
Theme analyzer - extracts themes, categories, and keywords from book text content.

Uses heuristic and keyword-based analysis to identify:
- Broad categories (Computer Science, Religion, etc.)
- Higher-level themes 
- Keywords for search
"""
import logging
import re
from collections import Counter
from typing import Optional

from .models import BookRecord

logger = logging.getLogger(__name__)

# ─── Category Taxonomy ──────────────────────────────────────────────────────────
# Maps keyword patterns to broad categories
CATEGORY_KEYWORDS = {
    "Computer Science": [
        "programming", "algorithm", "software", "computer", "code", "coding",
        "python", "java", "javascript", "c++", "database", "web development",
        "machine learning", "deep learning", "artificial intelligence", "data structure",
        "api", "framework", "linux", "terminal", "command line", "git",
        "neural network", "tensorflow", "pytorch", "docker", "cloud",
        "compiler", "operating system", "networking", "cybersecurity",
    ],
    "Data Science & ML": [
        "data science", "machine learning", "deep learning", "neural network",
        "statistics", "regression", "classification", "clustering",
        "natural language processing", "nlp", "computer vision",
        "recommendation system", "time series", "feature engineering",
        "model training", "gradient", "optimization", "kaggle",
        "data analysis", "data mining", "big data", "pandas", "numpy",
        "scikit-learn", "tensorflow", "pytorch", "causal inference",
        "bayesian", "reinforcement learning", "embedding",
    ],
    "Mathematics & Physics": [
        "mathematics", "algebra", "calculus", "geometry", "topology",
        "probability", "statistics", "linear algebra", "matrix",
        "physics", "quantum", "relativity", "cosmology", "spacetime",
        "theorem", "proof", "equation", "differential", "integral",
    ],
    "Islam & Islamic Studies": [
        "quran", "hadith", "sunnah", "prophet muhammad", "islamic",
        "muslim", "mosque", "salat", "prayer", "fiqh", "shariah",
        "tawheed", "aqeedah", "dawah", "ummah", "khalifah", "caliphate",
        "imam", "sheikh", "deen", "haram", "halal", "ramadan", "hajj",
        "zakat", "din", "allah", "hijab", "fatwa", "ibn", "tafsir",
        "sahih", "bukhari", "tajweed", "nikah", "salafi", "sufi",
    ],
    "Religion & Philosophy": [
        "religion", "theology", "philosophy", "metaphysics", "ethics",
        "morality", "atheism", "theism", "god", "divine", "spiritual",
        "secular", "belief", "faith", "soul", "consciousness",
        "existential", "phenomenology", "epistemology", "ontology",
    ],
    "History": [
        "history", "historical", "ancient", "medieval", "modern",
        "empire", "dynasty", "war", "revolution", "civilization",
        "colonial", "independence", "century", "era", "chronicle",
        "ottoman", "mughal", "british", "roman", "persian",
    ],
    "Politics & Geopolitics": [
        "politics", "political", "democracy", "government", "state",
        "nationalism", "imperialism", "colonialism", "capitalism",
        "socialism", "communism", "liberalism", "geopolitics",
        "foreign policy", "diplomacy", "lobby", "zionism", "palestine",
        "israel", "congress", "parliament", "ideology",
    ],
    "Economics & Finance": [
        "economics", "economy", "finance", "financial", "banking",
        "investment", "stock", "market", "trading", "corporate",
        "inflation", "gdp", "monetary", "fiscal", "startup",
        "business", "entrepreneur", "wealth", "profit", "debt",
    ],
    "Psychology & Self-Help": [
        "psychology", "psychological", "mental", "brain", "cognitive",
        "behavior", "emotion", "anxiety", "depression", "therapy",
        "self-help", "motivation", "habit", "mindset", "productivity",
        "happiness", "well-being", "confidence", "relationship",
    ],
    "Literature & Fiction": [
        "novel", "fiction", "story", "narrative", "character",
        "protagonist", "literary", "prose", "poetry", "poem",
        "chapter one", "once upon", "he said", "she said",
    ],
    "Gender & Society": [
        "gender", "feminism", "feminist", "masculinity", "sexuality",
        "transgender", "lgbtq", "patriarchy", "women's rights",
        "social justice", "discrimination", "equality", "modesty",
    ],
    "Security & Hacking": [
        "hacking", "hack", "security", "vulnerability", "exploit",
        "penetration testing", "cybersecurity", "malware", "virus",
        "ethical hacking", "reverse engineering", "encryption",
        "forensic", "password", "authentication",
    ],
    "Science & Nature": [
        "science", "scientific", "biology", "chemistry", "evolution",
        "darwin", "genetics", "dna", "ecology", "environment",
        "climate", "universe", "astronomy", "cosmos", "species",
    ],
    "Health & Wellness": [
        "health", "medical", "medicine", "nutrition", "diet",
        "exercise", "fitness", "healing", "herbal", "natural remedy",
        "anatomy", "disease", "wellness", "organic",
    ],
    "Language & Communication": [
        "language", "grammar", "vocabulary", "english", "arabic",
        "writing", "communication", "speech", "linguistics",
        "pronunciation", "fluency", "conversation",
    ],
}

# Theme extraction patterns - broader conceptual themes
THEME_PATTERNS = {
    "Critique of Modernity": [
        "modernity", "modern world", "crisis", "secular", "postmodern",
        "disenchantment", "materialism", "nihilism",
    ],
    "East-West Relations": [
        "east and west", "orient", "occidental", "clash of civilizations",
        "cultural exchange", "colonialism", "post-colonial",
    ],
    "Social Reform": [
        "reform", "social change", "revolution", "awakening",
        "activism", "social movement", "justice",
    ],
    "Technology & Society": [
        "technology", "digital", "internet", "social media",
        "automation", "disruption", "innovation",
    ],
    "Ethical Living": [
        "ethics", "moral", "virtue", "character", "integrity",
        "manners", "etiquette", "righteousness",
    ],
    "Knowledge & Education": [
        "knowledge", "education", "learning", "teaching", "scholarship",
        "intellectual", "academic", "wisdom", "curriculum",
    ],
    "Identity & Belonging": [
        "identity", "belonging", "community", "culture", "tradition",
        "heritage", "diaspora", "migration",
    ],
    "Power & Resistance": [
        "power", "resistance", "oppression", "liberation", "hegemony",
        "propaganda", "control", "freedom", "struggle",
    ],
    "Practical Skills & Career": [
        "career", "interview", "job", "skill", "practice", "professional",
        "craft", "mastery", "certification", "portfolio",
    ],
    "Personal Development": [
        "self-improvement", "growth", "productivity", "habits",
        "goal setting", "discipline", "mindfulness", "success",
    ],
}


def analyze_themes(record: BookRecord) -> BookRecord:
    """
    Analyze a book's text excerpt, title, and metadata to determine
    categories, themes, and keywords.
    """
    # Build a text corpus from all available data
    corpus = _build_corpus(record)
    corpus_lower = corpus.lower()

    # ── Categories ───────────────────────────────────────────────────────
    if not record.categories:
        categories = _detect_categories(corpus_lower)
        record.categories = categories[:5]

    # ── Themes ───────────────────────────────────────────────────────────
    if not record.themes:
        themes = _detect_themes(corpus_lower)
        record.themes = themes[:5]

    # ── Keywords ─────────────────────────────────────────────────────────
    if not record.keywords:
        keywords = _extract_keywords(corpus_lower, record.categories)
        record.keywords = keywords[:15]

    # ── Summary (if we have text but no summary) ────────────────────────
    if not record.summary and record.text_excerpt:
        record.summary = _generate_simple_summary(record)

    return record


def _build_corpus(record: BookRecord) -> str:
    """Build a text corpus from all available record data."""
    parts = [
        record.title or "",
        record.original_title_meta or "",
        record.description or "",
        record.text_excerpt or "",
        " ".join(record.authors),
        record.publisher or "",
        " ".join(record.categories),
        " ".join(record.keywords),
    ]
    return " ".join(p for p in parts if p)


def _detect_categories(corpus: str) -> list[str]:
    """Detect broad categories based on keyword matching."""
    scores = {}
    for category, keywords in CATEGORY_KEYWORDS.items():
        score = 0
        for kw in keywords:
            # Count occurrences (weighted by specificity)
            count = len(re.findall(r"\b" + re.escape(kw) + r"\b", corpus))
            if count > 0:
                # More specific (longer) keywords get higher weight
                weight = 1 + (len(kw.split()) - 1) * 0.5
                score += count * weight
        if score > 0:
            scores[category] = score

    # Sort by score and return top categories
    sorted_cats = sorted(scores.items(), key=lambda x: x[1], reverse=True)
    return [cat for cat, _ in sorted_cats]


def _detect_themes(corpus: str) -> list[str]:
    """Detect higher-level themes based on pattern matching."""
    scores = {}
    for theme, keywords in THEME_PATTERNS.items():
        score = 0
        for kw in keywords:
            count = len(re.findall(r"\b" + re.escape(kw) + r"\b", corpus))
            if count > 0:
                weight = 1 + (len(kw.split()) - 1) * 0.5
                score += count * weight
        if score > 0:
            scores[theme] = score

    sorted_themes = sorted(scores.items(), key=lambda x: x[1], reverse=True)
    return [theme for theme, _ in sorted_themes]


def _extract_keywords(corpus: str, categories: list[str]) -> list[str]:
    """Extract specific searchable keywords from the corpus."""
    # Combine all category keywords for reference
    all_kw_patterns = set()
    for cat_keywords in CATEGORY_KEYWORDS.values():
        all_kw_patterns.update(cat_keywords)

    found_keywords = []
    for kw in all_kw_patterns:
        if re.search(r"\b" + re.escape(kw) + r"\b", corpus):
            found_keywords.append(kw)

    # Also extract capitalized multi-word terms (likely proper nouns / concepts)
    proper_terms = re.findall(r"\b[A-Z][a-z]+(?:\s+[A-Z][a-z]+)+\b", corpus[:3000])
    term_counts = Counter(proper_terms)
    for term, count in term_counts.most_common(10):
        if count > 1 and term.lower() not in {kw.lower() for kw in found_keywords}:
            found_keywords.append(term)

    return found_keywords[:15]


def _generate_simple_summary(record: BookRecord) -> str:
    """Generate a simple summary from available data."""
    parts = []

    if record.description:
        # Use first two sentences of description
        sentences = re.split(r"(?<=[.!?])\s+", record.description)
        parts.append(" ".join(sentences[:2]))
    elif record.text_excerpt:
        # Use first meaningful paragraph
        paragraphs = record.text_excerpt.split("\n\n")
        for para in paragraphs:
            para = para.strip()
            if len(para) > 50:
                # Truncate to ~2 sentences
                sentences = re.split(r"(?<=[.!?])\s+", para)
                parts.append(" ".join(sentences[:3]))
                break

    summary = " ".join(parts)
    return summary[:500] if summary else ""
