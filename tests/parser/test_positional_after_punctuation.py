"""tree-sitter-bash splits ``$1-$2`` into ``$1-$`` and ``2``; spelaion rejoins it."""

from __future__ import annotations

import pytest

from spelaion import Bash


@pytest.mark.parametrize(
    ("script", "expected"),
    [
        ("echo $1-$2", "a-b\n"),
        ("echo $1:$2 $1.$2 $1/$2", "a:b a.b a/b\n"),
        ("echo $1-$2-$1", "a-b-a\n"),
        ("echo x-$2", "x-b\n"),
        ("echo $1-$10", "a-a0\n"),
        ("echo $1- $2", "a- b\n"),
        ("echo '$1'-$2", "$1-b\n"),
    ],
)
def test_positional_after_punctuation(script: str, expected: str) -> None:
    assert Bash().run(script, args=["a", "b"]).stdout == expected
