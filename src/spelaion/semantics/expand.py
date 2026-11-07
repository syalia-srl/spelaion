"""Expansion engine for shell words — thin delegate to :mod:`exec.word_eval`.

This module preserves the legacy functional API (``expand_word``,
``expand_word_single``) used by ``redirs.py`` and tests.  All actual
expansion logic lives in :class:`~spelaion.exec.word_eval.WordEvaluator`.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from spelaion.exec.arith_eval import ArithEvaluator
from spelaion.exec.word_eval import CommandSubstitutionHook, WordEvaluator

if TYPE_CHECKING:
    from spelaion.ast.nodes import Word
    from spelaion.runtime.state import ShellState
    from spelaion.vfs.base import Filesystem

__all__ = [
    "CommandSubstitutionHook",
    "expand_word",
    "expand_word_single",
]


def expand_word(
    word: Word,
    state: ShellState,
    vfs: Filesystem,
    cmdsub_hook: CommandSubstitutionHook | None = None,
) -> list[str]:
    """Expand a Word into a list of strings (post word-splitting).

    Delegates to :meth:`WordEvaluator.eval_word`.
    """
    ev = _make_evaluator(state, vfs, cmdsub_hook)
    return ev.eval_word(word)


def expand_word_single(
    word: Word,
    state: ShellState,
    vfs: Filesystem,
    cmdsub_hook: CommandSubstitutionHook | None = None,
) -> str:
    """Expand a Word into a single string (no word splitting/globbing).

    Delegates to :meth:`WordEvaluator.eval_word_single`.
    """
    ev = _make_evaluator(state, vfs, cmdsub_hook)
    return ev.eval_word_single(word)


def _make_evaluator(
    state: ShellState,
    vfs: Filesystem,
    cmdsub_hook: CommandSubstitutionHook | None,
) -> WordEvaluator:
    """Create a temporary WordEvaluator for the functional API."""
    arith_ev = ArithEvaluator(state)
    return WordEvaluator(
        state=state,
        vfs=vfs,
        arith_ev=arith_ev,
        cmdsub_hook=cmdsub_hook,
    )
