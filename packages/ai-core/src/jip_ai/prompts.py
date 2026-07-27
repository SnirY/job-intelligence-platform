"""Versioned prompts.

``docs/05-ai-and-matching.md`` requires prompts to be centrally managed and
versioned, and ``docs/09-mvp-roadmap.md`` gates every AI feature on a prompt
version. The version is recorded on each ``AIRun`` and on each extraction, so a
result can always be traced to the exact instructions that produced it — and a
prompt change becomes a new version rather than a silent rewrite of history.

The registry lives here; the prompts themselves live in ``packages/prompts``.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from string import Template

_VERSION_SUFFIX = re.compile(r"_v(\d+)$")


@dataclass(frozen=True, slots=True)
class PromptTemplate:
    """One version of one prompt.

    Frozen: a prompt that can be mutated at runtime makes the version recorded
    on an ``AIRun`` a lie.
    """

    name: str
    """Versioned identifier, e.g. ``resume_parser_v1``."""

    system: str
    user_template: str
    """``string.Template`` syntax — ``$name`` and ``${name}``.

    Not ``str.format``: resume text and JSON examples are full of braces, and
    every one of them would have to be escaped.
    """

    variables: frozenset[str] = frozenset()
    """Names ``render`` requires. Declared so a missing variable fails here
    rather than reaching the model as the literal text ``$resume_text``."""

    @property
    def version(self) -> int:
        """Trailing version number from the name."""
        match = _VERSION_SUFFIX.search(self.name)
        if match is None:
            raise ValueError(f"Prompt name {self.name!r} does not end in a version suffix.")
        return int(match.group(1))

    def render(self, **values: str) -> str:
        """Substitute ``values`` into the user template."""
        missing = self.variables - values.keys()
        if missing:
            raise ValueError(f"Prompt {self.name} is missing: {', '.join(sorted(missing))}")
        return Template(self.user_template).substitute(**values)


class PromptRegistry:
    """The set of prompts a process knows about."""

    def __init__(self) -> None:
        self._prompts: dict[str, PromptTemplate] = {}

    def register(self, prompt: PromptTemplate) -> PromptTemplate:
        """Add a prompt. Re-registering a name is an error.

        Overwriting would let two versions share an identifier, and the version
        stored on past runs would no longer identify anything.
        """
        if prompt.name in self._prompts:
            raise ValueError(f"Prompt {prompt.name!r} is already registered.")
        prompt.version  # noqa: B018 - validates the name carries a version
        self._prompts[prompt.name] = prompt
        return prompt

    def get(self, name: str) -> PromptTemplate:
        try:
            return self._prompts[name]
        except KeyError as exc:
            raise KeyError(f"No prompt registered as {name!r}.") from exc

    def names(self) -> frozenset[str]:
        return frozenset(self._prompts)
