"""The compiled module's name tells apart CPUs with different features."""

from __future__ import annotations

from spelaion.python.fetch import compiled_name, cpu_tag

AVX512 = "processor\t: 0\nflags\t\t: fpu sse2 avx2 avx512f avx512bitalg\n"
AVX2 = "processor\t: 0\nflags\t\t: fpu sse2 avx2\n"


def test_different_features_different_tags() -> None:
    assert cpu_tag("x86_64", AVX512) != cpu_tag("x86_64", AVX2)


def test_same_features_in_another_order_same_tag() -> None:
    shuffled = "processor\t: 0\nflags\t\t: avx512bitalg avx2 fpu avx512f sse2\n"
    assert cpu_tag("x86_64", AVX512) == cpu_tag("x86_64", shuffled)


def test_arm_features_line() -> None:
    a = cpu_tag("aarch64", "Features\t: fp asimd\n")
    assert a != cpu_tag("aarch64", "Features\t: fp asimd sve\n")


def test_compiled_name_carries_the_tag() -> None:
    assert compiled_name().count("-") >= 2
