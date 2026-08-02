"""grow the canonical skill catalogue

DEV-032. The first seed said it was "a starting point that grows from real job
descriptions in Phase 5, not an attempt to enumerate a taxonomy up front". This
is that growth, and the measurement that prompted it:

Across two real postings the parser named **seventeen** distinct skills. The
thirty-row catalogue resolved **three** — Linux, SQL and AWS. It did not know
C++, TCP/IP, AI/ML, Algorithms, Data structures, Object-oriented design,
Multi-threading, Design Patterns, or Version control.

Everything keyed on ``skill_id`` was therefore running at about a fifth of its
coverage, silently, because an unresolved skill is not an error — it is a null
column:

- Phase 10 demand counts by skill, so a C++ role reported asking for Linux;
- Phase 6 matching falls back to a weaker normalised-name comparison;
- DEV-025's deduplication keys on ``skill_id`` and so could not merge two
  mentions of an uncatalogued skill;
- DEV-026's apparent instability is substantially this — "C++" and "C/C++" are
  one requirement that counts as two.

Still not a taxonomy. This covers what software job postings actually name,
which is a different and much smaller set than "all skills", and it is chosen
from postings rather than from imagination.

**"C/C++" is an alias for C++, deliberately.** It means "C or C++" and the two
are different languages, so this is lossy. It is the reading a person gives it —
a posting writing "C/C++" is asking for C++ and will accept C — and the
alternative is the pair failing to merge, which is the defect being fixed.

Revision ID: c4d7e1f9ab32
Revises: 13500f1d6067
Create Date: 2026-08-02
"""

from __future__ import annotations

import re
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "c4d7e1f9ab32"
down_revision: str | None = "13500f1d6067"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_NON_ALNUM = re.compile(r"[^a-z0-9+#]+")


def _normalize(raw: str) -> str:
    """Mirrors ``jip_api.domain.career.skills.normalize_skill_name``.

    Duplicated on purpose, for the reason the first seed gives: a migration has
    to keep producing the rows it produced when it first ran, even if the
    application's rule later changes.
    """
    return _NON_ALNUM.sub(" ", raw.strip().lower()).strip().replace(" ", "-")


# (canonical name, category, [aliases])
SEED: list[tuple[str, str, list[str]]] = [
    # --- languages ---------------------------------------------------------
    ("C++", "LANGUAGE", ["CPP", "C/C++", "C plus plus"]),
    ("C#", "LANGUAGE", ["CSharp", "C Sharp", ".NET C#"]),
    ("Java", "LANGUAGE", []),
    ("Go", "LANGUAGE", ["Golang"]),
    ("Rust", "LANGUAGE", []),
    ("Ruby", "LANGUAGE", []),
    ("PHP", "LANGUAGE", []),
    ("Swift", "LANGUAGE", []),
    ("Kotlin", "LANGUAGE", []),
    ("Scala", "LANGUAGE", []),
    ("Bash", "LANGUAGE", ["Shell scripting", "Shell"]),
    ("MATLAB", "LANGUAGE", []),
    ("R", "LANGUAGE", []),
    ("Objective-C", "LANGUAGE", []),
    ("Assembly", "LANGUAGE", []),
    ("VHDL", "LANGUAGE", []),
    ("Verilog", "LANGUAGE", ["SystemVerilog"]),
    # --- frameworks --------------------------------------------------------
    ("Django", "FRAMEWORK", []),
    ("Flask", "FRAMEWORK", []),
    ("Spring Boot", "FRAMEWORK", ["Spring"]),
    ("Angular", "FRAMEWORK", ["AngularJS"]),
    ("Vue.js", "FRAMEWORK", ["Vue", "VueJS"]),
    ("Next.js", "FRAMEWORK", ["NextJS"]),
    ("Express.js", "FRAMEWORK", ["Express", "ExpressJS"]),
    (".NET", "FRAMEWORK", ["dotnet", "ASP.NET", ".NET Core"]),
    ("Ruby on Rails", "FRAMEWORK", ["Rails"]),
    ("PyTorch", "FRAMEWORK", ["Torch"]),
    ("Qt", "FRAMEWORK", []),
    ("Boost", "FRAMEWORK", []),
    # --- databases ---------------------------------------------------------
    ("MySQL", "DATABASE", []),
    ("MongoDB", "DATABASE", ["Mongo"]),
    ("Redis", "DATABASE", []),
    ("Elasticsearch", "DATABASE", ["ElasticSearch", "ELK"]),
    ("SQLite", "DATABASE", []),
    ("Oracle Database", "DATABASE", ["Oracle DB"]),
    ("Microsoft SQL Server", "DATABASE", ["MSSQL", "SQL Server"]),
    ("Cassandra", "DATABASE", []),
    ("DynamoDB", "DATABASE", []),
    # SQL is not in the first seed. It existed in the development database only
    # because a resume import created it there, which is exactly how a
    # migration referencing it passes locally and fails on a fresh database.
    ("SQL", "LANGUAGE", ["Structured Query Language"]),
    ("NoSQL", "DATABASE", ["NoSQL databases"]),
    # --- platforms and tools -----------------------------------------------
    ("Microsoft Azure", "PLATFORM", ["Azure"]),
    ("Google Cloud Platform", "PLATFORM", ["GCP", "Google Cloud"]),
    ("Terraform", "TOOL", []),
    ("Jenkins", "TOOL", []),
    ("GitLab", "TOOL", ["GitLab CI"]),
    ("GitHub Actions", "TOOL", []),
    ("Ansible", "TOOL", []),
    ("Grafana", "TOOL", []),
    ("Prometheus", "TOOL", []),
    ("Kafka", "PLATFORM", ["Apache Kafka"]),
    ("RabbitMQ", "PLATFORM", []),
    ("Nginx", "TOOL", []),
    ("Jira", "TOOL", []),
    ("Wireshark", "TOOL", []),
    ("Valgrind", "TOOL", []),
    ("CMake", "TOOL", []),
    # Linux, like SQL, was never seeded. Both existed in the development
    # database because a resume import created them, which made the original
    # catalogue look like it resolved three of seventeen observed names. On a
    # genuinely fresh database it resolved one: AWS.
    ("Linux", "PLATFORM", ["GNU/Linux"]),
    ("Linux Kernel", "PLATFORM", []),
    ("Windows", "PLATFORM", []),
    ("macOS", "PLATFORM", []),
    ("Android", "PLATFORM", []),
    ("iOS", "PLATFORM", []),
    ("Embedded Linux", "PLATFORM", []),
    ("Unix", "PLATFORM", []),
    # --- practices ---------------------------------------------------------
    # The cluster the measurement found repeatedly and could not resolve.
    ("Version Control", "PRACTICE", ["Version control systems", "Source control", "SCM"]),
    ("Data Structures", "PRACTICE", ["Data structures and algorithms"]),
    ("Algorithms", "PRACTICE", ["Algorithm design", "Algorithm development"]),
    ("Object-Oriented Design", "PRACTICE", ["OOD", "OOP", "Object-oriented programming"]),
    ("Design Patterns", "PRACTICE", []),
    ("Multi-threading", "PRACTICE", ["Multithreading", "Concurrency", "Concurrent programming"]),
    ("Debugging", "PRACTICE", ["Troubleshooting", "Debugging and troubleshooting"]),
    ("CI/CD", "PRACTICE", ["Continuous delivery", "Continuous deployment"]),
    ("Test-Driven Development", "PRACTICE", ["TDD"]),
    ("Unit Testing", "PRACTICE", ["Unit tests"]),
    ("Code Review", "PRACTICE", []),
    ("Agile", "PRACTICE", ["Agile methodologies", "Scrum"]),
    ("Microservices", "PRACTICE", ["Microservice architecture", "Microservices architecture"]),
    ("System Design", "PRACTICE", ["Systems design"]),
    ("Performance Optimization", "PRACTICE", ["Performance tuning", "Performance optimisation"]),
    ("Software Development Lifecycle", "PRACTICE", ["SDLC"]),
    ("Containerization", "PRACTICE", ["Containerisation", "Containers"]),
    ("Infrastructure as Code", "PRACTICE", ["IaC"]),
    ("Open Source", "PRACTICE", ["Open-source contributions"]),
    # --- networking and domains --------------------------------------------
    ("TCP/IP", "DOMAIN", ["TCP", "TCP IP", "Networking protocols"]),
    ("Networking", "DOMAIN", ["Computer networking", "Network engineering"]),
    ("HTTP", "DOMAIN", ["HTTPS"]),
    ("gRPC", "DOMAIN", []),
    ("GraphQL", "DOMAIN", []),
    ("WebSockets", "DOMAIN", ["WebSocket"]),
    ("DOCSIS", "DOMAIN", []),
    ("Cellular Protocols", "DOMAIN", ["Cellular", "5G", "LTE"]),
    ("Telecommunications", "DOMAIN", ["Telecom"]),
    ("Cybersecurity", "DOMAIN", ["Information security", "InfoSec", "Security"]),
    ("Distributed Systems", "DOMAIN", []),
    ("Operating Systems", "DOMAIN", []),
    ("Embedded Systems", "DOMAIN", ["Embedded development"]),
    ("Real-Time Systems", "DOMAIN", ["Real-time"]),
    ("Artificial Intelligence", "DOMAIN", ["AI", "AI/ML", "AI tools", "AI development tools"]),
    ("Deep Learning", "DOMAIN", ["DL", "Neural networks"]),
    ("Natural Language Processing", "DOMAIN", ["NLP"]),
    ("Data Engineering", "DOMAIN", ["Data pipelines", "ETL"]),
    ("Data Analysis", "DOMAIN", ["Data analytics"]),
    ("Cloud Computing", "DOMAIN", ["Cloud", "Cloud platforms"]),
    ("DevOps", "DOMAIN", []),
    ("Site Reliability Engineering", "DOMAIN", ["SRE"]),
    ("Mobile Development", "DOMAIN", ["Mobile app development"]),
    ("Frontend Development", "DOMAIN", ["Front-end development"]),
    ("Backend Development", "DOMAIN", ["Back-end development", "Server-side development"]),
    ("Quality Assurance", "DOMAIN", ["QA"]),
    # --- soft skills -------------------------------------------------------
    # Present so that a posting asking for them resolves to *something* shared
    # rather than to a per-user row. They are still SOFT_SKILL, which the
    # matcher treats as unassessable (DEV-030).
    ("Communication", "SOFT_SKILL", ["Communication skills", "Written and verbal communication"]),
    ("Problem Solving", "SOFT_SKILL", ["Problem-solving", "Analytical thinking"]),
    ("Teamwork", "SOFT_SKILL", ["Collaboration"]),
    ("Leadership", "SOFT_SKILL", []),
    ("Mentoring", "SOFT_SKILL", ["Mentorship"]),
    ("Independence", "SOFT_SKILL", ["Self-driven", "Works independently"]),
]

# Compound names the parser actually produced, joined with a slash or an "and".
#
# Kept apart from SEED because they are a different kind of entry: not another
# way of writing one skill, but several skills written as one requirement. Each
# resolves to the first skill named, which is the reading a person gives — a
# posting asking for "SQL/NoSQL databases" is asking about databases, and
# filing it under SQL is closer than filing it nowhere.
#
# Every one of these was observed in a real reading. None is invented, because
# the space of possible compounds is unbounded and guessing at it is how a
# catalogue becomes a taxonomy.
COMPOUND_ALIASES: list[tuple[str, str]] = [
    ("Debugging/troubleshooting", "Debugging"),
    ("Debugging and troubleshooting complex systems", "Debugging"),
    ("SQL/NoSQL databases", "SQL"),
    ("SQL and NoSQL databases", "SQL"),
    ("Data structures / algorithms / OOD", "Data Structures"),
    ("Data structures / algorithms / OOP design", "Data Structures"),
    ("AI tools for development", "Artificial Intelligence"),
    ("Microservices/cloud-native architecture", "Microservices"),
]

# Deliberately left unresolved, because they are not skills:
#
#   "General-purpose programming language"                  a category
#   "Java/Python/C++/C#/Go/Rust/TypeScript (at least one)"  an any-of list
#   "performance-critical software"                         a property of code
#
# Each would have to resolve to something arbitrary, and a wrong canonical skill
# is worse than none: it would put a candidate's Python against a requirement
# that never asked for Python.


def upgrade() -> None:
    connection = op.get_bind()

    for canonical, category, aliases in SEED:
        skill_id = connection.execute(
            sa.text(
                """
                INSERT INTO skills (canonical_name, normalized_name, category)
                VALUES (:canonical, :normalized, :category)
                ON CONFLICT (normalized_name) DO UPDATE SET canonical_name = EXCLUDED.canonical_name
                RETURNING id
                """
            ),
            {"canonical": canonical, "normalized": _normalize(canonical), "category": category},
        ).scalar_one()

        for alias in aliases:
            normalized_alias = _normalize(alias)
            # An alias must never equal its own canonical name, or resolution
            # would depend on which lookup ran first.
            if normalized_alias == _normalize(canonical):
                continue
            connection.execute(
                sa.text(
                    """
                    INSERT INTO skill_aliases (skill_id, alias, normalized_alias)
                    VALUES (:skill_id, :alias, :normalized_alias)
                    ON CONFLICT (normalized_alias) DO NOTHING
                    """
                ),
                {"skill_id": skill_id, "alias": alias, "normalized_alias": normalized_alias},
            )

    for alias, canonical in COMPOUND_ALIASES:
        skill_id = connection.execute(
            sa.text("SELECT id FROM skills WHERE normalized_name = :normalized"),
            {"normalized": _normalize(canonical)},
        ).scalar_one()

        connection.execute(
            sa.text(
                """
                INSERT INTO skill_aliases (skill_id, alias, normalized_alias)
                VALUES (:skill_id, :alias, :normalized_alias)
                ON CONFLICT (normalized_alias) DO NOTHING
                """
            ),
            {"skill_id": skill_id, "alias": alias, "normalized_alias": _normalize(alias)},
        )


def downgrade() -> None:
    """Remove only what nobody has claimed, exactly as the first seed does.

    A user whose profile points at "C++" would otherwise lose the row their
    skill depends on. Aliases go; a skill in use stays.
    """
    connection = op.get_bind()

    for alias, _canonical in COMPOUND_ALIASES:
        connection.execute(
            sa.text("DELETE FROM skill_aliases WHERE normalized_alias = :normalized"),
            {"normalized": _normalize(alias)},
        )

    for canonical, _category, aliases in SEED:
        for alias in aliases:
            connection.execute(
                sa.text("DELETE FROM skill_aliases WHERE normalized_alias = :normalized"),
                {"normalized": _normalize(alias)},
            )

        connection.execute(
            sa.text(
                """
                DELETE FROM skills
                WHERE normalized_name = :normalized
                  AND NOT EXISTS (SELECT 1 FROM user_skills WHERE skill_id = skills.id)
                  AND NOT EXISTS (SELECT 1 FROM project_skills WHERE skill_id = skills.id)
                  AND NOT EXISTS (SELECT 1 FROM experience_skills WHERE skill_id = skills.id)
                  AND NOT EXISTS (SELECT 1 FROM job_requirements WHERE skill_id = skills.id)
                """
            ),
            {"normalized": _normalize(canonical)},
        )
