"""Explicit transferability groups.

``docs/05-ai-and-matching.md`` is blunt about the danger this module exists to
avoid:

```text
Django ≠ Spring Boot
```

...but Django experience *may* support a transferable backend-framework match.
Both halves matter. A matcher that treats them as equivalent overstates the
candidate; one that ignores the relationship entirely reports a gap against
someone who would pick the framework up in a fortnight.

So transferability is an explicit, curated relation rather than a similarity
score. Two skills transfer when a human has said they belong to the same group,
and the result is always :class:`MatchStatus.TRANSFERABLE_MATCH` — never MATCH.
There is no path in this module that can produce a direct match, which is what
makes "semantic similarity is not equivalence" a property of the code rather
than a rule someone has to remember.

The groups are deliberately narrow. Membership means "someone fluent in one
could become productive in another quickly, in the same problem space" — not
"both are software". Python and Java are both languages and are *not* in a
group together: the ecosystems, idioms, and hiring expectations differ enough
that calling them transferable would mislead.
"""

from __future__ import annotations

from dataclasses import dataclass

from jip_api.domain.career.skills import normalize_skill_name


@dataclass(frozen=True, slots=True)
class TransferGroup:
    """One set of mutually transferable skills."""

    key: str
    label: str
    members: frozenset[str]
    """Normalized skill names. Normalized at import so lookup is a set hit."""

    strength: int = 50
    """0-100, how well membership transfers. Feeds the item's confidence, never
    its score — the score comes from the status, and the status is fixed."""


def _group(key: str, label: str, names: list[str], strength: int = 50) -> TransferGroup:
    return TransferGroup(
        key=key,
        label=label,
        members=frozenset(normalize_skill_name(n) for n in names),
        strength=strength,
    )


TRANSFER_GROUPS: tuple[TransferGroup, ...] = (
    _group(
        "backend-web-framework",
        "server-side web frameworks",
        [
            "FastAPI",
            "Django",
            "Flask",
            "Spring Boot",
            "Spring",
            "Ruby on Rails",
            "Rails",
            "Express",
            "Express.js",
            "NestJS",
            "ASP.NET Core",
            "Laravel",
            "Phoenix",
            "Gin",
        ],
        strength=55,
    ),
    _group(
        "frontend-framework",
        "component-based frontend frameworks",
        ["React", "Vue", "Vue.js", "Angular", "Svelte", "SolidJS", "Preact", "Ember.js"],
        strength=55,
    ),
    _group(
        "relational-database",
        "relational databases",
        [
            "PostgreSQL",
            "MySQL",
            "MariaDB",
            "SQL Server",
            "Oracle Database",
            "SQLite",
            "Amazon Aurora",
            "CockroachDB",
        ],
        strength=65,
    ),
    _group(
        "document-database",
        "document databases",
        ["MongoDB", "CouchDB", "DynamoDB", "Firestore", "DocumentDB"],
        strength=55,
    ),
    _group(
        "cloud-platform",
        "cloud platforms",
        [
            "Amazon Web Services",
            "AWS",
            "Microsoft Azure",
            "Azure",
            "Google Cloud Platform",
            "GCP",
            "DigitalOcean",
            "Hetzner Cloud",
        ],
        strength=50,
    ),
    _group(
        "container-orchestration",
        "container orchestration",
        ["Kubernetes", "Amazon ECS", "Nomad", "Docker Swarm", "OpenShift"],
        strength=50,
    ),
    _group(
        "infrastructure-as-code",
        "infrastructure as code",
        ["Terraform", "Pulumi", "AWS CloudFormation", "CloudFormation", "Ansible", "Bicep"],
        strength=55,
    ),
    _group(
        "ci-system",
        "CI systems",
        [
            "GitHub Actions",
            "GitLab CI",
            "Jenkins",
            "CircleCI",
            "Travis CI",
            "Buildkite",
            "TeamCity",
            "Azure Pipelines",
        ],
        strength=70,
    ),
    _group(
        "message-queue",
        "message queues and streaming",
        [
            "Apache Kafka",
            "Kafka",
            "RabbitMQ",
            "Amazon SQS",
            "NATS",
            "Apache Pulsar",
            "Redis Streams",
            "Google Pub/Sub",
        ],
        strength=50,
    ),
    _group(
        "ml-framework",
        "deep learning frameworks",
        ["PyTorch", "TensorFlow", "JAX", "Keras", "MXNet"],
        strength=55,
    ),
    _group(
        "data-processing",
        "large-scale data processing",
        ["Apache Spark", "Spark", "Apache Flink", "Flink", "Apache Beam", "Dask", "Hadoop"],
        strength=50,
    ),
    _group(
        "frontend-styling",
        "CSS tooling",
        [
            "Tailwind CSS",
            "Tailwind",
            "Bootstrap",
            "Sass",
            "SCSS",
            "styled-components",
            "CSS Modules",
            "Emotion",
        ],
        strength=65,
    ),
    _group(
        "typed-js",
        "JavaScript and TypeScript",
        ["JavaScript", "TypeScript"],
        strength=75,
    ),
    _group(
        "jvm-language",
        "JVM languages",
        ["Java", "Kotlin", "Scala", "Groovy"],
        strength=55,
    ),
    _group(
        "dotnet-language",
        ".NET languages",
        ["C#", "F#", "Visual Basic .NET"],
        strength=55,
    ),
    _group(
        "systems-language",
        "systems languages",
        ["C", "C++", "Rust", "Zig"],
        strength=45,
    ),
    _group(
        "observability",
        "observability tooling",
        [
            "Prometheus",
            "Grafana",
            "Datadog",
            "New Relic",
            "OpenTelemetry",
            "Splunk",
            "Elastic Stack",
            "ELK",
        ],
        strength=60,
    ),
)

# Python is deliberately absent from every group. It sits in no group with Java
# or Go: the ecosystems and the work differ enough that a transferable claim
# would be a stretch rather than a kindness. Adding it later is a rules change
# and therefore an engine version bump, which is the correct amount of friction.


_BY_MEMBER: dict[str, tuple[TransferGroup, ...]] = {}
for _group_ in TRANSFER_GROUPS:
    for _member in _group_.members:
        _BY_MEMBER[_member] = (*_BY_MEMBER.get(_member, ()), _group_)


def groups_for(skill_name: str) -> tuple[TransferGroup, ...]:
    """Every group a skill belongs to. Empty when it transfers to nothing."""
    return _BY_MEMBER.get(normalize_skill_name(skill_name), ())


def find_transfer(required: str, held: list[str]) -> tuple[str, TransferGroup] | None:
    """The best held skill that transfers to ``required``, if any.

    Returns the held skill and the group linking them, so the explanation can
    name both — "Django is a server-side web framework, like Spring Boot" is
    checkable in a way that "similar experience" is not.

    Deterministic on ties: groups are scanned in declaration order and held
    skills in the order given, so the same inputs always name the same pair.
    The caller sorts ``held`` before calling.
    """
    required_groups = groups_for(required)
    if not required_groups:
        return None

    required_key = normalize_skill_name(required)

    best: tuple[str, TransferGroup] | None = None
    for candidate in held:
        candidate_key = normalize_skill_name(candidate)
        if candidate_key == required_key:
            # The same skill. That is a direct match, and it is not this
            # module's business to report it.
            continue
        for group in required_groups:
            if candidate_key in group.members:
                if best is None or group.strength > best[1].strength:
                    best = (candidate, group)
                break
    return best
