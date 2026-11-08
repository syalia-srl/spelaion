# spelaion

[![CI](https://github.com/syalia-srl/spelaion/actions/workflows/ci.yml/badge.svg)](https://github.com/syalia-srl/spelaion/actions/workflows/ci.yml)
[![Docs](https://github.com/syalia-srl/spelaion/actions/workflows/docs.yml/badge.svg)](https://syalia-srl.github.io/spelaion/)
[![License: MIT](https://img.shields.io/badge/license-MIT-blue.svg)](LICENSE)

A bash for agents, run from Python, with nothing real behind it.

spelaion is a Python library that gives an agent a shell that looks like bash and a python with the full standard library, while it sees only the folders the host mounts and reaches nothing else: no network, no other agent's files, no host binaries. The host extends it with commands written in Python, which run with the host's power and decide what the agent may do.

The name is Plato's cave (σπήλαιον, Republic VII): the prisoners see only the shadows someone casts on the wall. The agent sees only what the host mounts.

spelaion began as a copy of agentsh by Mayflower GmbH (MIT); see [LICENSES/agentsh-MIT.txt](LICENSES/agentsh-MIT.txt).

## Install

```bash
uv add git+https://github.com/syalia-srl/spelaion@v0.1.0
```

It needs Python 3.11 or later and is tested on Linux. `python` inside a sandbox runs CPython compiled to WASI, which is not in the wheel: the first sandbox made with `python=True` downloads it (about 14 MB, pinned by sha256) and prepares it in a cache folder (`$SPELAION_CACHE`, else `$XDG_CACHE_HOME/spelaion`, else `~/.cache/spelaion`). `spelaion fetch-python` does the same ahead of time.

## Documentation

The book at <https://syalia-srl.github.io/spelaion/> ([PDF](https://syalia-srl.github.io/spelaion/spelaion.pdf)) starts with a [Quick Start](https://syalia-srl.github.io/spelaion/quick-start.html) and takes one job per chapter: mounting folders, bounding calls, python, host commands, images, your own agent loop, MCP, running Claude Code or OpenCode, what the shell can and cannot do, and testing scripts with `Bash`. Its Developer Guide covers the architecture, the [security model](https://syalia-srl.github.io/spelaion/the-security-model.html) and adding a command. Every code block in it runs when the book is built, and its sources are in [`docs/`](docs/).

## Development

```bash
uv sync
uv run ruff check .
uv run ruff format --check .
uv run pyright
uv run tach check
uv run pytest -q                 # -m "not wasi" skips the tests that need python
uv run python tests/battery/record.py   # re-record the battery under bash 5
make docs-check                  # render the book, run its blocks and examples, check coverage
```

[AGENTS.md](AGENTS.md) has the constraints and the layout.

## License

MIT, see [LICENSE](LICENSE). spelaion began as a copy of agentsh by Mayflower GmbH, MIT-licensed; their license is kept in [LICENSES/agentsh-MIT.txt](LICENSES/agentsh-MIT.txt).
