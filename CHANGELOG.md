# Changelog

## 0.1.0 — 2026-11-08

First release. spelaion starts from a copy of an MIT-licensed shell by
Mayflower GmbH (commit 1abc7c3, license in `LICENSES/`), renamed and rebuilt
around a sandbox.

### Added

- `Sandbox`: the `bash`, `edit` and `write` tools over host folders the
  caller mounts (`MountFs`). Every path goes through one resolver,
  `MountFs.host_path()`.
- The shell runs in a child process with a hard deadline and a memory cap.
  The parent restarts the child after a timeout or a crash.
- `python` and `python3`: CPython 3.14 for WASI under wasmtime, with the full
  standard library and PyYAML, and with no sockets or processes.
- Host commands written in Python, with `ctx`, attachments and `show`.
- `tools()` for in-process agent loops, and an MCP server that offers the
  same three tools.
- Builtins `:` and `command`, `PIPESTATUS`, and `timeout` (status 124).
- A recipe for running Claude Code and OpenCode on spelaion, with a
  standalone Claude Code example and its test.
- A battery of agent commands checked against real bash 5.
- The book, at <https://syalia-srl.github.io/spelaion/> and as a PDF: a
  Quick Start, a User Guide with one job per chapter and a Developer Guide.
  Every block runs when it is built, and `make docs-check` gates it.

### Fixed

- Parser: byte offsets in UTF-8 source, a trailing redirection, the rest of
  a here-document line, `!` over a whole pipeline, and `$1-$2` (it printed
  `a-$ 2`).
- A prefix assignment (`FOO=bar cmd`) is in the command's environment, so
  `env`, `python3` and host commands see it.
- `head -c N` and `tail -c N` count bytes.
- Two mounts at the same sandbox path are refused.
- python works from a cache shared by machines with different CPUs: the
  compiled module's name carries a hash of the CPU's features.
- Redirections: `/dev/null`, a missing `<` file, each buffer written once,
  and stderr kept for every pipeline stage.
- Globs match one path component at a time and keep leading folders as
  written.
- Commands: `awk`, `grep --include`, `cp -r`, `head`, `tail`, `ls`, `sort`
  keys, `wc` widths and `sleep` now behave as their GNU versions do.
- The sandbox rejects bad limits, a relative cwd and text that is not
  UTF-8, bounds what host commands and the child send, and reports a slow
  host command as a timeout.
- `MountFs` rename never follows a link out of a mount, and a write never
  recreates a deleted mount folder.

### Removed

- The LangChain tools and the PyPI publish job. This release is a GitHub
  tag only.
