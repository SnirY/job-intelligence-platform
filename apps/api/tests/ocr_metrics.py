"""How wrong a transcript is.

Two figures, both standard, both the same shape: the smallest number of edits
that turns what was read into what was true, divided by how long the truth was.

    CER = (substitutions + deletions + insertions) / characters in the truth
    WER = the same, counted in words

They are written here rather than installed because the whole of it is one
dynamic-programming loop, and a dependency for twenty lines is a dependency to
upgrade forever. It is the same reasoning `text.py` gives for reading DOCX with
the standard library.

**The instrument gets its own tests.** A quietly wrong error rate does not fail;
it reports a good number, and every measurement taken with it afterwards is
worthless in a way nobody can see. `tests/unit/test_ocr_metrics.py` checks it
against cases whose answer can be counted by hand.
"""

from __future__ import annotations

import re
from collections.abc import Sequence

_WHITESPACE = re.compile(r"\s+")


def normalise(text: str) -> str:
    """Collapse whitespace, so layout is not scored as spelling.

    An engine reconstructs line breaks and column gaps from the geometry of a
    page, and it will not reproduce the exact runs of spaces a text layer had.
    Counting those as errors would measure how the page was laid out rather
    than how well it was read.

    Case is left alone. Reading `Python` as `python` is a real error, and a
    reader would notice it.
    """
    return _WHITESPACE.sub(" ", text).strip()


def edit_distance(left: Sequence[str], right: Sequence[str]) -> int:
    """Levenshtein distance between two sequences.

    Works over characters or over words, because a word is only a token that
    happens to be longer. One rolling row rather than the full matrix: the
    algorithm never looks further back than the previous row, and a page of
    3,000 characters against another would otherwise allocate nine million
    cells to read two.
    """
    if not left:
        return len(right)
    if not right:
        return len(left)

    previous = list(range(len(right) + 1))

    for row, left_item in enumerate(left, start=1):
        current = [row]
        for column, right_item in enumerate(right, start=1):
            current.append(
                min(
                    previous[column] + 1,  # delete from left
                    current[column - 1] + 1,  # insert from right
                    previous[column - 1] + (left_item != right_item),  # substitute
                )
            )
        previous = current

    return previous[-1]


def character_error_rate(truth: str, read: str) -> float:
    """Edits per character of truth. 0.0 is perfect; above 1.0 is possible.

    Above one because insertions are counted: an engine that hallucinates a
    page of noise onto a short line can be more than 100% wrong. Capping it
    would hide exactly the failure worth seeing.
    """
    truth, read = normalise(truth), normalise(read)
    if not truth:
        return 0.0 if not read else 1.0
    return edit_distance(truth, read) / len(truth)


def word_error_rate(truth: str, read: str) -> float:
    """Edits per word of truth.

    Always at least as bad as CER on the same pair, and usually worse: one
    wrong character spoils a whole word. Reported alongside because the
    downstream reader here is a language model, and a model recovers from a
    damaged character more easily than from a word that has become a different
    word.
    """
    truth_words = normalise(truth).split()
    read_words = normalise(read).split()
    if not truth_words:
        return 0.0 if not read_words else 1.0
    return edit_distance(truth_words, read_words) / len(truth_words)
