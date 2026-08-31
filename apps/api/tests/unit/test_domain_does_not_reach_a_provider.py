"""The domain layer does not import the AI package.

`docs/04-system-architecture.md` puts the layers in one order — API, then
Application, then Domain, then Infrastructure — and `docs/05-ai-and-matching.md`
adds the rule this file exists for: **AI interprets, domain logic decides.** The
matcher takes a profile snapshot and a list of requirements, and returns the
same verdicts every time. It can only keep doing that while nothing underneath
it can reach a model.

That held by discipline and nothing else. Written after the README claimed the
boundary was enforced and a check found that no linter, test or packaging rule
was enforcing anything — it was simply true so far. A boundary nobody checks is
a boundary until the first hurried afternoon.

Deliberately narrower than an import linter, and cheaper: one question, asked of
the layer where the answer matters, in a suite that already runs everywhere.
"""

from __future__ import annotations

import ast
import pathlib

import pytest

DOMAIN = pathlib.Path(__file__).resolve().parents[2] / "src" / "jip_api" / "domain"

FORBIDDEN = ("jip_ai", "jip_prompts", "anthropic", "openai")
"""Provider SDKs, and the packages that wrap them.

`jip_prompts` is here for the same reason as `jip_ai`: a domain module reaching
for a prompt is a domain module about to call something.
"""


def _imported_modules(source: str) -> set[str]:
    """Every module named by an `import` or `from ... import`, as written."""
    tree = ast.parse(source)
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
            names.add(node.module)
    return names


def _domain_files() -> list[pathlib.Path]:
    return sorted(p for p in DOMAIN.rglob("*.py") if "__pycache__" not in p.parts)


def test_the_domain_tree_is_where_this_thinks_it_is() -> None:
    """A moved package would make every assertion below vacuously true."""
    files = _domain_files()

    assert DOMAIN.is_dir(), f"{DOMAIN} does not exist"
    assert len(files) > 20, f"only {len(files)} files under {DOMAIN}; has it moved?"


@pytest.mark.parametrize("path", _domain_files(), ids=lambda p: p.name)
def test_no_domain_module_imports_a_provider(path: pathlib.Path) -> None:
    """Read as source, not imported: this must hold for modules that fail to
    import for unrelated reasons, and it must name the file rather than the
    first thing that broke."""
    imported = _imported_modules(path.read_text(encoding="utf-8"))

    offending = {
        name
        for name in imported
        for forbidden in FORBIDDEN
        if name == forbidden or name.startswith(f"{forbidden}.")
    }

    assert not offending, (
        f"{path.relative_to(DOMAIN.parent)} imports {sorted(offending)}. "
        "The domain decides; it does not interpret. If this module genuinely "
        "needs model output, it belongs in the application layer, which is "
        "where the review tables are cleared."
    )
