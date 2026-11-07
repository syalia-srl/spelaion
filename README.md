# spelaion

[![CI](https://github.com/syalia-srl/spelaion/actions/workflows/ci.yml/badge.svg)](https://github.com/syalia-srl/spelaion/actions/workflows/ci.yml)
[![License: MIT](https://img.shields.io/badge/license-MIT-blue.svg)](LICENSE)

A bash for agents, run from Python, with nothing real behind it.

spelaion is a Python library that gives an agent a shell that looks like bash and a python with the full standard library, while it sees only the folders the host mounts and reaches nothing else: no network, no other agent's files, no host binaries. The host extends it with commands written in Python, which run with the host's power and decide what the agent may do.

The name is Plato's cave (σπήλαιον, Republic VII): the prisoners see only the shadows someone casts on the wall. The agent sees only what the host mounts.

spelaion began as a copy of agentsh by Mayflower GmbH (MIT); see LICENSES/agentsh-MIT.txt.

```python
from spelaion import Bash

bash = Bash()
bash.run('echo "Hello" > greeting.txt')
result = bash.run("cat greeting.txt")
print(result.stdout)    # Hello\n
print(result.exit_code) # 0
```

**166 commands** including coreutils, text processing, archives, structured data (jq, yq, patch), modern search (rg, fd), and 40 shell builtins. Filesystem is shared across calls. State persists.

## Install

```bash
uv add git+https://github.com/syalia-srl/spelaion
```

## Quick Start

```python
from spelaion import Bash

bash = Bash()

# Files persist across calls
bash.run('echo "world" > /tmp/name.txt')
result = bash.run('echo "Hello, $(cat /tmp/name.txt)"')
print(result.stdout)  # Hello, world\n

# Variables persist
bash.run('COUNT=0')
bash.run('COUNT=$(( COUNT + 1 ))')
result = bash.run('echo $COUNT')
print(result.stdout)  # 1\n

# Functions persist
bash.run('greet() { echo "Hi, $1!"; }')
result = bash.run('greet Alice')
print(result.stdout)  # Hi, Alice!\n
```

## Configuration

```python
from spelaion import Bash, Limits

bash = Bash(
    # Pre-populate the virtual filesystem
    files={
        "/data/users.json": '[{"name": "Alice"}, {"name": "Bob"}]',
        "/app/config.yaml": "debug: true\nport: 8080",
    },
    # Set environment variables
    env={
        "APP_ENV": "production",
        "API_KEY": "sk-...",
    },
    # Working directory
    cwd="/app",
    # Safety limits
    limits=Limits(
        max_call_depth=100,
        max_loop_iterations=10_000,
    ),
)
```

### Per-call overrides

```python
# Override env for one call
bash.run("echo $TEMP", env={"TEMP": "/tmp"})

# Override working directory
bash.run("ls", cwd="/data")

# Provide stdin
bash.run("cat | tr a-z A-Z", stdin="hello\n")

# Set positional parameters
bash.run('echo "First: $1, Second: $2"', args=["foo", "bar"])
```

## Custom Commands

Extend the shell with Python-implemented commands:

```python
from spelaion import Bash, define_command, RunResult, CommandContext

def handle_upper(args: list[str], ctx: CommandContext) -> RunResult:
    return RunResult(stdout=ctx.stdin.upper())

def handle_hello(args: list[str], ctx: CommandContext) -> RunResult:
    name = args[0] if args else "world"
    return RunResult(stdout=f"Hello, {name}!\n")

bash = Bash(custom_commands=[
    define_command("upper", handle_upper),
    define_command("hello", handle_hello),
])

bash.run("hello Alice")              # Hello, Alice!\n
bash.run("echo whisper | upper")     # WHISPER\n
```

Custom commands receive a `CommandContext` with:

| Field | Type | Description |
|-------|------|-------------|
| `args` | `list[str]` | Command arguments |
| `stdin` | `str` | Piped input |
| `cwd` | `str` | Current working directory |
| `env` | `dict[str, str]` | Environment variables |
| `fs` | `VirtualFilesystem` | Direct filesystem access |

## Filesystem Access

```python
bash = Bash()

# Write files programmatically
bash.write_file("/data/input.csv", "name,age\nAlice,30\nBob,25\n")
bash.write_files({
    "/app/main.py": "print('hello')",
    "/app/test.py": "assert True",
})

# Read files back
content = bash.read_file("/data/input.csv")

# Check existence
if bash.file_exists("/data/input.csv"):
    bash.run("wc -l /data/input.csv")
```

## RunResult

Every `bash.run()` returns a `RunResult`:

```python
@dataclass
class RunResult:
    stdout: str = ""
    stderr: str = ""
    exit_code: int = 0
```

```python
result = bash.run("grep pattern /nonexistent")
if result.exit_code != 0:
    print(f"Error: {result.stderr}")
```

## Command Support

### Shell Builtins (40)

`[` `[[` `alias` `bg` `break` `cd` `continue` `declare` `echo` `eval` `exec` `exit` `export` `false` `fg` `getopts` `hash` `help` `jobs` `let` `local` `printf` `pwd` `read` `readonly` `return` `set` `shift` `source` `.` `test` `times` `trap` `true` `type` `ulimit` `umask` `unalias` `unset` `wait`

### Search (5)

`fd` `find` `grep` `rg` `xargs`

### Structured Data (3)

`jq` `patch` `yq`

### File Operations (21)

`cat` `cp` `dd` `file` `head` `install` `link` `ln` `ls` `mkdir` `mkfifo` `mktemp` `mv` `rm` `rmdir` `shred` `stat` `tail` `tee` `touch` `tree`

### Text Processing (31)

`awk` `cmp` `column` `comm` `cut` `diff` `egrep` `envsubst` `expand` `factor` `fgrep` `fmt` `fold` `hd` `nl` `od` `paste` `rev` `sed` `sort` `split` `strings` `tac` `tr` `tsort` `uniq` `wc` `xxd`

### Archive & Compression (12)

`ar` `bunzip2` `bzcat` `bzip2` `cpio` `gunzip` `gzip` `lzcat` `tar` `unzip` `zcat` `zip`

### Encoding & Checksums (7)

`base64` `cksum` `hexdump` `md5sum` `sha1sum` `sha256sum` `xxd`

### Math & Data (6)

`bc` `expr` `factor` `seq` `shuf` `uuidgen`

### System Info & Utilities (30)

`arch` `chmod` `chgrp` `chown` `clear` `date` `df` `du` `env` `free` `getopt` `hostname` `id` `kill` `logname` `nproc` `printenv` `ps` `sleep` `time` `timeout` `top` `tty` `uname` `uptime` `users` `w` `which` `who` `whoami`

### Virtual No-ops (12)

Commands accepted for compatibility but with no real effect in the virtual environment:

`bg` `chrt` `fg` `flock` `fsync` `ionice` `jobs` `nice` `nohup` `renice` `sync` `usleep`

## Shell Syntax Support

Full bash syntax parsing via tree-sitter:

- **Variables**: `$VAR`, `${VAR}`, `${VAR:-default}`, `${VAR##pattern}`, `${#VAR}`, `${VAR:0:3}`, `${VAR/pat/repl}`, `${VAR^^}`, `${VAR,,}`, `$?`, `$#`, `$@`
- **Arrays**: indexed `arr=(a b c)`, `${arr[0]}`, `${arr[@]}`, `${#arr[@]}` and associative `declare -A`, `${!arr[@]}`
- **Quoting**: single quotes, double quotes, backslash escapes
- **Expansion**: tilde, parameter, command substitution `$(...)`, arithmetic `$(( ))`, process substitution `<(cmd)`
- **Control flow**: `if`/`elif`/`else`/`fi`, `while`, `until`, `for`, `for (( ))`, `case`/`esac`, `break`, `continue`
- **Tests**: `[ ... ]` POSIX test, `[[ ... ]]` extended test with glob `==`, regex `=~`, `&&`/`||`
- **Operators**: `&&`, `||`, `;`, `|` (pipelines)
- **Redirections**: `>`, `>>`, `<`, `2>`, `2>&1`, `<<` (here-doc), `<<<` (here-string)
- **Arithmetic**: `+`, `-`, `*`, `/`, `%`, `**`, `<`, `>`, `==`, `!=`, `&&`, `||`, `!`, `?:` (ternary), bitwise, `++`/`--`
- **Functions**: definition, local variables, positional params, return values, recursion
- **Subshells**: `( ... )` with isolated state, shared filesystem
- **Groups**: `{ ...; }` in current shell context

## Architecture

```
                    ┌─────────────┐
                    │   Bash API  │  ← you are here
                    └──────┬──────┘
                           │
                    ┌──────▼──────┐
                    │ ShellEngine │  parse / plan / run
                    └──────┬──────┘
                           │
              ┌────────────┼────────────┐
              │            │            │
      ┌───────▼──┐  ┌──────▼──┐  ┌─────▼────┐
      │  Parser  │  │ Planner │  │ Executor │
      │tree-sitter│  │         │  │          │
      └───────┬──┘  └─────────┘  └────┬─────┘
              │                        │
      ┌───────▼──┐            ┌────────▼────────┐
      │   AST    │            │ Split Evaluators │
      │ (owned)  │            │ cmd/word/arith/  │
      └──────────┘            │ bool/pipeline    │
                              └────────┬────────┘
                                       │
                    ┌──────────────┬────▼───┬──────────┐
                    │              │        │          │
               ┌────▼───┐  ┌──────▼──┐  ┌──▼───┐  ┌──▼────┐
               │Builtins│  │Commands │  │ VFS  │  │Policy │
               │  (40)  │  │  (126)  │  │in-mem│  │engine │
               └────────┘  └─────────┘  └──────┘  └───────┘
```

- **100% virtual** — no `subprocess`, no `os.*` file I/O in production paths
- **In-memory VFS** — all filesystem operations go through `VirtualFilesystem`
- **Three-tier resolution** — function → builtin → virtual command (no external binaries)
- **Policy engine** — allow/deny/warn rules for commands and paths
- **tree-sitter parsing** — real bash grammar, not regex hacks

## Security Model

spelaion runs entirely in-memory with no access to the host system:

- No subprocess calls, ever
- No real filesystem access — all I/O goes through the virtual filesystem
- No network access
- Policy engine can deny specific commands or paths
- Configurable recursion and loop limits

This makes it safe for AI agent tool-use loops where the agent generates and executes bash scripts.

## Development

```bash
uv sync                          # Install dependencies
uv run pytest tests/ -q          # Run 2100+ tests
uv run ruff check .              # Lint
uv run ruff format .             # Format
uv run pyright                   # Type check (strict)
uv run tach check                # Architecture boundaries
uv run pre-commit run --all      # All hooks
```

## License

MIT, see [LICENSE](LICENSE).
