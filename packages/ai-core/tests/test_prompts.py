"""The prompt registry.

Versioning is the point: a stored ``AIRun`` names a prompt version, and that
name has to keep identifying the same text.
"""

from __future__ import annotations

import pytest

from jip_ai.prompts import PromptRegistry, PromptTemplate


def template(name: str = "demo_v1") -> PromptTemplate:
    return PromptTemplate(
        name=name,
        system="You extract things.",
        user_template="Read this: $body",
        variables=frozenset({"body"}),
    )


def test_version_comes_from_the_name() -> None:
    assert template("demo_v3").version == 3


def test_a_name_without_a_version_is_rejected() -> None:
    unversioned = template("demo")

    with pytest.raises(ValueError, match="version suffix"):
        _ = unversioned.version


def test_renders_variables() -> None:
    assert template().render(body="a resume") == "Read this: a resume"


def test_a_missing_variable_fails_before_the_call() -> None:
    """Otherwise the literal text ``$body`` reaches the model, and the failure
    shows up as a strange answer rather than as an error."""
    with pytest.raises(ValueError, match="missing: body"):
        template().render()


def test_braces_in_the_input_survive() -> None:
    """Resume text and JSON examples are full of braces. ``string.Template``
    rather than ``str.format`` is what makes that safe."""
    rendered = template().render(body='{"skills": ["C++"]}')

    assert '{"skills": ["C++"]}' in rendered


def test_registry_returns_what_was_registered() -> None:
    registry = PromptRegistry()
    registry.register(template())

    assert registry.get("demo_v1").system == "You extract things."


def test_registering_a_name_twice_is_an_error() -> None:
    """Two versions under one identifier would make every stored reference to
    it ambiguous."""
    registry = PromptRegistry()
    registry.register(template())

    with pytest.raises(ValueError, match="already registered"):
        registry.register(template())


def test_unknown_prompt_raises() -> None:
    with pytest.raises(KeyError, match="No prompt registered"):
        PromptRegistry().get("nope_v1")


def test_an_unversioned_prompt_cannot_be_registered() -> None:
    with pytest.raises(ValueError, match="version suffix"):
        PromptRegistry().register(template("demo"))
