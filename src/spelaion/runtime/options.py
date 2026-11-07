"""Shell option flags (mirrors ``set -o`` options)."""

from dataclasses import dataclass


@dataclass
class ShellOptions:
    """Boolean flags corresponding to common ``set`` options."""

    errexit: bool = False  # set -e
    nounset: bool = False  # set -u
    pipefail: bool = False  # set -o pipefail
    xtrace: bool = False  # set -x
    noglob: bool = False  # set -f
