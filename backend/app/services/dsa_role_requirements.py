import re
from typing import Any
from sqlalchemy.orm import Session

from app.models.dsa_problem import DSAProblem
from app.models.dsa_progress import DSAProgress
from app.models.leetcode_state import LeetCodeState


# Pre-configured per-role DSA requirement tabs
ROLE_REQUIREMENTS_TABS: dict[str, dict[str, Any]] = {
    "Software Engineer": {
        "title": "Software Engineer",
        "description": "Core software engineering, algorithms, and scalable system structures.",
        "required_topics": [
            {"topic": "Arrays & Hashing", "weight": 1.2, "target_problems": 5},
            {"topic": "Two Pointers", "weight": 1.0, "target_problems": 4},
            {"topic": "Trees", "weight": 1.2, "target_problems": 4},
            {"topic": "Graphs", "weight": 1.0, "target_problems": 3},
            {"topic": "Dynamic Programming", "weight": 1.1, "target_problems": 4},
            {"topic": "Design / Linked List", "weight": 0.9, "target_problems": 3},
        ],
        "aliases": ["sde", "software development engineer", "software engineer", "swe", "software developer", "sde intern", "software engineer intern"],
    },
    "ML Engineer": {
        "title": "ML Engineer",
        "description": "Machine learning engineering, mathematical structures, tree models, and algorithmic efficiency.",
        "required_topics": [
            {"topic": "Arrays & Hashing", "weight": 1.1, "target_problems": 5},
            {"topic": "Math & Linear Algebra", "weight": 1.2, "target_problems": 4},
            {"topic": "Trees", "weight": 1.1, "target_problems": 4},
            {"topic": "Dynamic Programming", "weight": 1.0, "target_problems": 3},
            {"topic": "Strings", "weight": 0.8, "target_problems": 3},
        ],
        "aliases": ["ml engineer", "machine learning engineer", "ai engineer", "data scientist", "machine learning", "ai/ml intern", "ml intern"],
    },
    "Data Analyst": {
        "title": "Data Analyst",
        "description": "Data manipulation, hashing, tabular querying, arrays, and statistics.",
        "required_topics": [
            {"topic": "Arrays & Hashing", "weight": 1.2, "target_problems": 5},
            {"topic": "SQL & Databases", "weight": 1.3, "target_problems": 5},
            {"topic": "Strings", "weight": 1.0, "target_problems": 3},
            {"topic": "Statistics & Math", "weight": 1.0, "target_problems": 3},
        ],
        "aliases": ["data analyst", "business analyst", "analytics engineer", "bi engineer", "data analytics intern"],
    },
    "Backend Developer": {
        "title": "Backend Developer",
        "description": "High-throughput API services, caching, data structures, and database querying.",
        "required_topics": [
            {"topic": "Arrays & Hashing", "weight": 1.2, "target_problems": 5},
            {"topic": "Design / Linked List", "weight": 1.2, "target_problems": 4},
            {"topic": "Two Pointers", "weight": 1.0, "target_problems": 3},
            {"topic": "Sliding Window", "weight": 1.0, "target_problems": 3},
            {"topic": "Graphs", "weight": 1.0, "target_problems": 3},
        ],
        "aliases": ["backend developer", "backend engineer", "api engineer", "server engineer", "backend intern"],
    },
    "Full-Stack Developer": {
        "title": "Full-Stack Developer",
        "description": "Full-stack web application development, end-to-end data manipulation, and UI algorithms.",
        "required_topics": [
            {"topic": "Arrays & Hashing", "weight": 1.1, "target_problems": 4},
            {"topic": "Strings", "weight": 1.0, "target_problems": 4},
            {"topic": "Trees", "weight": 0.9, "target_problems": 3},
            {"topic": "Two Pointers", "weight": 0.9, "target_problems": 3},
        ],
        "aliases": ["full-stack developer", "full stack engineer", "full-stack engineer", "web developer", "full stack intern"],
    },
}

# Generic fallback topic set when role is not recognized
GENERIC_DEFAULT_TOPICS = [
    {"topic": "Arrays & Hashing", "weight": 1.0, "target_problems": 4},
    {"topic": "Strings", "weight": 1.0, "target_problems": 3},
    {"topic": "Trees", "weight": 1.0, "target_problems": 3},
    {"topic": "Two Pointers", "weight": 1.0, "target_problems": 3},
]

NON_TECHNICAL_ROLE_TERMS = (
    "chef", "cook", "culinary", "kitchen", "restaurant", "hospitality",
    "marketing", "finance", "accountant", "accounting", "sales", "recruiter",
    "human resources", "hr manager", "legal", "lawyer", "nurse", "teacher",
)

TECHNICAL_ROLE_TERMS = (
    "software", "developer", "programmer", "backend", "back-end", "frontend",
    "front-end", "full stack", "full-stack", "web developer", "data analyst",
    "data scientist", "machine learning", "ml engineer", "ai engineer", "devops",
    "sre", "qa automation", "test automation", "api engineer", "database engineer",
)

TECHNICAL_SKILL_TERMS = (
    "python", "java", "javascript", "typescript", "c++", "c#", "golang", "rust",
    "sql", "api", "database", "programming", "coding", "software development",
    "algorithms", "data structures", "react", "node.js", "docker", "kubernetes",
)


def is_technical_job(
    role_title: str,
    job_description: str,
    required_skills: list[str] | None = None,
    company: str | None = None,
) -> bool:
    """Require evidence in the posting; a technical student profile is not evidence."""
    title = (role_title or "").lower()
    text = " ".join((company or "", job_description or "", *(required_skills or []))).lower()
    if any(term in title for term in NON_TECHNICAL_ROLE_TERMS):
        return False
    has_technical_evidence = any(term in title for term in TECHNICAL_ROLE_TERMS) or any(term in text for term in TECHNICAL_SKILL_TERMS)
    has_nontechnical_context = any(term in text for term in NON_TECHNICAL_ROLE_TERMS)
    return has_technical_evidence and not (has_nontechnical_context and not any(term in text for term in TECHNICAL_SKILL_TERMS))


def has_role_context_mismatch(
    role_title: str,
    company: str | None,
    job_description: str,
    required_skills: list[str] | None = None,
) -> bool:
    """Reject role matching unless the posting itself provides technical evidence."""
    text = " ".join((company or "", job_description or "", *(required_skills or []))).lower()
    return not is_technical_job(role_title, job_description, required_skills, company) or (
        any(term in text for term in NON_TECHNICAL_ROLE_TERMS)
        and not any(term in text for term in TECHNICAL_SKILL_TERMS)
    )


def match_role_tab(role_title: str) -> tuple[str, str, list[dict[str, Any]]]:
    """
    Fuzzy-match role title to known role requirement tabs.
    Returns:
        (matched_role_name, match_type, required_topics)
        where match_type is 'exact', 'fuzzy', or 'inferred'.
    """
    cleaned = re.sub(r"[^a-zA-Z0-9\s/]", " ", role_title).strip().lower()

    if any(term in cleaned for term in NON_TECHNICAL_ROLE_TERMS):
        return "Non-technical Role", "not_applicable", []

    # 1. Exact or alias match
    for role_name, data in ROLE_REQUIREMENTS_TABS.items():
        if cleaned == role_name.lower():
            return role_name, "exact", data["required_topics"]
        for alias in data.get("aliases", []):
            if cleaned == alias.lower():
                return role_name, "exact", data["required_topics"]

    # 2. Domain keyword priority matching (specific disciplines take precedence over generic 'engineer' / 'intern')
    domain_priorities = [
        ("ML Engineer", ["ml", "machine learning", "ai", "artificial intelligence", "deep learning", "nlp", "computer vision"]),
        ("Data Analyst", ["data analyst", "analytics", "bi", "business intelligence", "data analysis"]),
        ("Backend Developer", ["backend", "server", "api engineer", "distributed systems"]),
        ("Full-Stack Developer", ["full stack", "fullstack", "web developer", "frontend"]),
        ("Software Engineer", ["software", "sde", "swe", "software developer"]),
    ]

    for role_name, keywords in domain_priorities:
        for kw in keywords:
            # Word boundary check for short terms like 'ai', 'ml'
            pattern = rf"\b{re.escape(kw)}\b"
            if re.search(pattern, cleaned):
                return role_name, "fuzzy", ROLE_REQUIREMENTS_TABS[role_name]["required_topics"]

    # 3. Substring / token overlap fallback
    words = set(cleaned.split()) - {"intern", "junior", "senior", "lead", "engineer", "specialist"}
    best_match = None
    max_overlap = 0

    for role_name, data in ROLE_REQUIREMENTS_TABS.items():
        for alias in data.get("aliases", []):
            alias_words = set(alias.lower().split()) - {"intern", "junior", "senior", "lead", "engineer", "specialist"}
            overlap = len(words & alias_words)
            if overlap > max_overlap:
                max_overlap = overlap
                best_match = role_name

    if best_match and max_overlap >= 1:
        return best_match, "fuzzy", ROLE_REQUIREMENTS_TABS[best_match]["required_topics"]

    # 4. Fallback to generic default topic set
    return "General Tech Role", "inferred", GENERIC_DEFAULT_TOPICS


def get_student_topic_confidence(db: Session, user_id: int) -> dict[str, float]:
    """
    Calculates student confidence score (0.0 to 1.0) for every DSA topic
    based on actual solved problems in dsa_problems, progress counts, and revision state.
    """
    problems = db.query(DSAProblem).filter(DSAProblem.user_id == user_id).all()
    progress_rows = db.query(DSAProgress).filter(DSAProgress.user_id == user_id).all()

    # Aggregate counts and needs_revision by topic
    topic_counts: dict[str, int] = {}
    topic_revisions: dict[str, int] = {}

    for p in problems:
        t = _normalize_topic_name(p.topic)
        topic_counts[t] = topic_counts.get(t, 0) + 1
        if p.needs_revision:
            topic_revisions[t] = topic_revisions.get(t, 0) + 1

    for pr in progress_rows:
        t = _normalize_topic_name(pr.topic)
        if pr.solved_count > topic_counts.get(t, 0):
            topic_counts[t] = pr.solved_count
        if pr.revision_count > topic_revisions.get(t, 0):
            topic_revisions[t] = pr.revision_count

    # Confidence calculation formula:
    # 4+ solved problems with 0 revision = 1.0 confidence
    # Solved ratio capped at 1.0, penalized up to 20% if high revision needed
    confidences: dict[str, float] = {}
    for topic, solved in topic_counts.items():
        base_confidence = min(1.0, solved / 4.0)
        revisions = topic_revisions.get(topic, 0)
        penalty = min(0.25, (revisions / max(1, solved)) * 0.25)
        confidences[topic] = round(max(0.1, base_confidence - penalty), 2)

    return confidences


def _normalize_topic_name(topic: str) -> str:
    """Helper to harmonize common variations in topic naming."""
    t = topic.strip().lower()
    if "array" in t or "hash" in t:
        return "Arrays & Hashing"
    if "tree" in t:
        return "Trees"
    if "graph" in t:
        return "Graphs"
    if "dynamic" in t or "dp" in t:
        return "Dynamic Programming"
    if "two pointer" in t or "pointer" in t:
        return "Two Pointers"
    if "window" in t:
        return "Sliding Window"
    if "linked" in t or "design" in t:
        return "Design / Linked List"
    if "math" in t or "algebra" in t:
        return "Math & Linear Algebra"
    if "string" in t:
        return "Strings"
    if "sql" in t or "database" in t:
        return "SQL & Databases"
    if "stat" in t:
        return "Statistics & Math"
    return topic.strip().title()


def compute_role_readiness(
    db: Session,
    user_id: int,
    role_title: str,
) -> dict[str, Any]:
    """
    Computes technical readiness by comparing the student's dsa_topic_confidence
    against the matched role's required topics.

    Readiness Formula:
        Weighted average of (confidence(topic) / target_confidence) capped at 1.0,
        scaled to 100.
    """
    matched_role, role_match_type, required_topics = match_role_tab(role_title)
    confidences = get_student_topic_confidence(db, user_id)

    total_weight = 0.0
    weighted_score = 0.0

    strengths = []
    developing = []
    topic_breakdown = []

    for req in required_topics:
        topic_name = req["topic"]
        weight = req.get("weight", 1.0)
        norm_topic = _normalize_topic_name(topic_name)

        confidence = confidences.get(norm_topic, 0.0)
        # If not found directly, check substring matching
        if confidence == 0.0:
            for c_name, c_val in confidences.items():
                if norm_topic.lower() in c_name.lower() or c_name.lower() in norm_topic.lower():
                    confidence = c_val
                    break

        total_weight += weight
        weighted_score += min(1.0, confidence) * weight

        topic_info = {
            "topic": topic_name,
            "confidence": confidence,
            "status": "strong" if confidence >= 0.6 else "developing" if confidence > 0.2 else "gap",
            "weight": weight,
        }
        topic_breakdown.append(topic_info)

        if confidence >= 0.6:
            strengths.append(topic_name)
        else:
            developing.append(topic_name)

    readiness_percentage = round((weighted_score / total_weight) * 100, 1) if total_weight > 0 else 0.0

    return {
        "matched_role": matched_role,
        "role_match": role_match_type,
        "readiness_score": readiness_percentage,
        "technical_strengths": strengths,
        "developing_topics": developing,
        "topic_breakdown": topic_breakdown,
    }
