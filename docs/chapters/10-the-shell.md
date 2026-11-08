# What the shell can do

You are about to give an agent a shell. The agent will write ordinary bash:
pipes into `head`, `sed -i`, a here-document into a file, `grep -rn`, `jq`
over a JSON file. Before you hand it over you need to know which of those
lines will run, which will do less than bash without saying so, and which
will fail. This chapter is the inventory: one interpreter, the syntax it
parses, the 128 commands and 42 builtin names, the known gaps, and the
battery that compares it with real bash. It ends with a program that runs a
short conformance check over a temporary folder.

## One interpreter, no host programs

The shell is pure Python. `tree-sitter-bash` parses the text into a tree,
`src/spelaion/parser/normalize.py` turns that tree into spelaion's own AST
(`src/spelaion/ast/`), and the evaluator in `src/spelaion/exec/` walks the
AST over the mounted filesystem. No command starts a host program: `grep`,
`sed`, `tar` and `jq` are Python functions in `src/spelaion/commands/`, and
the same child process that holds the shell runs them. The only process
spelaion starts is its own child Python.

A command name resolves in three tiers: a shell function you defined, then
a builtin or a virtual command, then a host command the product registered.
Nothing else is found, and the shell answers `spelaion: name: command not
found` with exit code 127. That is why `bash -c`, `curl` and `git` are not
here: they are host binaries, and no tier starts one. [Host
commands](giving-the-agent-powers-with-host-commands.html) add a name from the product's side, and
[Adding a command](22-adding-a-command.md) adds one to spelaion itself.

The parser accepts a fixed grammar and reports anything outside it as
`spelaion: syntax error` with exit code 2. It does not fall back to running
the text some other way.

## The syntax it parses

The parser covers assignments and quoting, parameter expansion, indexed and
associative arrays, arithmetic, `if`/`elif`/`else`, `while`, `until`, `for`
(including the C-style form), `case`, functions, subshells, brace groups,
pipelines with `!`, `&&` and `||`, redirections (`>`, `>>`, `<`, `2>&1`,
`<<<`, `<>`), here-documents, command substitution and globbing. A first
block makes the temporary folder and the sandbox that every block in this
chapter uses:

```{python export=examples/the_shell.py}
import shutil
import tempfile
from pathlib import Path

from spelaion import Mount, Sandbox

work = Path(tempfile.mkdtemp())
(work / "plan.yaml").write_text("name: demo\nwalls:\n  - 4.0\n  - 3.5\n")
(work / "words.txt").write_text("red\nblue\nred\n")
sb = Sandbox([Mount("/work", host=work)], cwd="/work")
```

One script exercises the constructs a coding agent uses most:

```{python continue}
script = '''names=(alpha beta gamma)
declare -A sizes=([small]=1 [large]=2)
echo "${names[1]} ${#names[@]} ${sizes[large]}"
file=report.txt
echo "${file%.txt} ${file#report} ${file/report/summary}"
echo $(( (3 + 4) * 2 ))
cat <<EOF
name: $file
sum: $((1 + 2))
EOF
false | true | false
echo "statuses: ${PIPESTATUS[*]}"'''
r = sb.bash(script)
print(r.stdout, end="")
print("exit code:", r.exit_code)
```

An indexed array is written `names=(alpha beta gamma)` and read with
`${names[1]}` or `${names[@]}`. `declare -a` does not make an array: it
stores the text `(alpha beta gamma)` as a scalar, so write the assignment
without it ([#9](https://github.com/syalia-srl/spelaion/issues/9)). An associative array needs `declare -A`; `${!sizes[@]}` lists
its keys.

Parameter expansion includes defaults and alternates (`${v:-x}`,
`${v:=x}`, `${v:?message}`, `${v:+x}`), length (`${#v}`), prefix and suffix
removal (`${v#pat}`, `${v##pat}`, `${v%pat}`, `${v%%pat}`), replacement
(`${v/pat/new}`, `${v//pat/new}`), a substring (`${v:offset:length}`) and
case changes (`${v^}`, `${v^^}`, `${v,}`, `${v,,}`). Arithmetic is
`$(( ))`, with the usual integer operators. The here-document expands
variables and command substitutions unless its delimiter is quoted
(`<<'EOF'`). `${PIPESTATUS[*]}` holds the status of every command in the
last pipeline, so `1 0 1` above is the two failing `false` commands around
the successful `true`. `set -o pipefail` makes a pipeline return the first
failure instead.

Process substitution parses, but a `Sandbox` does not run it. The evaluator
writes the producer's output to a path under `/dev/fd`, and no mount
provides `/dev/fd`, so the call ends with an internal error:

```{python continue}
from spelaion import Bash

print(Bash().run("cat <(printf 'from a producer\\n')").stdout, end="")
r = sb.bash("cat <(printf 'from a producer\\n')")
print(r.stderr, end="")
print("exit code:", r.exit_code)
```

The in-memory `Bash` class has a writable in-memory filesystem, so it runs
the line; [Testing with bash](testing-shell-scripts-with-bash.html) covers that class.
The sandbox failure is a bug, tracked in [#8](https://github.com/syalia-srl/spelaion/issues/8).

Brace expansion is not supported either. `echo {a,b}` prints `{a,b}`, with
no error, which is worse than a syntax error because the line looks as if
it worked ([#7](https://github.com/syalia-srl/spelaion/issues/7)).

## Commands by purpose

Every name below is a Python function in the registry. The tables are the
whole list, grouped by the job an agent reaches for. Flags are the ones
worth knowing. A flag the command does not implement may be ignored, read
as a file name, or refused, so do not rely on one that is not listed.

### Files and folders

| Name | What it does |
|---|---|
| `cat` | Write files, or stdin, to stdout. |
| `cp` | Copy files; `-r` copies folders. |
| `mv` | Rename or move. |
| `rm` | Remove files; `-r` folders, `-f` ignores a missing name. |
| `mkdir` | Create folders; `-p` creates parents. |
| `rmdir` | Remove an empty folder. |
| `touch` | Create an empty file or update its time. |
| `tee` | Write stdin to stdout and to files; `-a` appends. |
| `ls` | List a folder; `-l` long, `-a` hidden, `-R` recursive. |
| `tree` | Draw a folder as a tree. |
| `stat` | Show a file's size, type and mode. |
| `du` | Show the size of files and folders; `-s` only the total. |
| `df` | Show the file count and total size of the mounts. |
| `chmod` | Set a mode; `ls -l` still prints a fixed one. |
| `chown` | Set an owner, stored but not enforced. |
| `chgrp` | Set a group, stored but not enforced. |
| `ln` | Fails: links are not supported in the sandbox. |
| `link` | Copies the file; it is not a hard link. |
| `readlink` | Print the resolved path; it is the same function as `realpath`. |
| `realpath` | Print the resolved absolute path. |
| `basename` | The last part of a path. |
| `dirname` | The parent part of a path. |
| `install` | Copy a file and set its mode; `-d` makes folders. |
| `shred` | Overwrite a file and remove it with `-u`. |
| `dd` | Copy blocks with `if=`, `of=`, `bs=` and `count=`. |
| `mkfifo` | Creates an empty file, not a pipe. |
| `mktemp` | A fresh name; the default `/tmp` is not mounted, so pass a parent with `-p`. |
| `file` | Guess a file's type from its bytes. |

### Text

| Name | What it does |
|---|---|
| `head` | The first lines; `-n N`, `-N`, and `-n -N` for all but the last. |
| `tail` | The last lines; `-n N`, `-N`, and `-n +N` from line N. |
| `wc` | Count lines (`-l`), words (`-w`) and bytes (`-c`). |
| `sort` | Sort lines; `-r`, `-n`, `-u`, `-k` and `-t`. |
| `uniq` | Collapse adjacent repeats; `-c` counts, `-d` only repeats, `-u` only singles. |
| `cut` | Select fields (`-d`, `-f`) or characters (`-c`). |
| `tr` | Translate characters, `-d` delete, `-s` squeeze. |
| `rev` | Reverse each line. |
| `nl` | Number lines. |
| `paste` | Join files side by side. |
| `fold` | Wrap lines at a width. |
| `expand` | Turn tabs into spaces; `-t` sets the tab stop. |
| `fmt` | Refill paragraphs to a width; `-w` sets it. |
| `column` | Align columns with `-t`; `-s` sets the separator. |
| `tac` | Reverse the order of lines. |
| `split` | Split a file; `-l` sets lines per part. |
| `comm` | Compare two sorted files, column by column. |
| `cmp` | Compare two files byte by byte; exit code 1 on a difference. |
| `tsort` | Topological sort of dependency pairs. |
| `strings` | Printable runs from a binary file. |
| `od` | Dump a file as octal words. |
| `hd` | Hex dump with an ASCII column. |
| `hexdump` | Hex dump; `-C` gives the canonical layout. |
| `xxd` | Hex dump with offsets. |
| `base64` | Encode or decode with `-d`. |
| `md5sum` | MD5 of files. |
| `sha1sum` | SHA-1 of files. |
| `sha256sum` | SHA-256 of files. |
| `cksum` | CRC checksum and size. |
| `diff` | Compare files; `-u` gives a unified diff and exit code 1 on a difference. |
| `patch` | Apply a unified diff from stdin or a file. |
| `envsubst` | Replace `$NAME` and `${NAME}` from the environment. |
| `sed` | Substitution, delete, print and quit, with line and regex addresses; `-n`, `-i`, `-e`. |
| `awk` | Patterns, `print`, `printf`, assignments and arithmetic; `-F` and `-v`. |

`sed` does not have the hold space, labels or the `a`, `i`, `c` and `y`
commands. `awk` is a subset: the next section shows what that costs.

### Search

| Name | What it does |
|---|---|
| `grep` | Regex search; `-i`, `-v`, `-c`, `-l`, `-n`, `-r`, `-E`, `-F`, `-w`, `-q`, `-o`, `-A`, `-B`, `-C`, `--include`, `--exclude`. |
| `egrep` | `grep -E`. |
| `fgrep` | `grep -F`. |
| `rg` | Recursive search with ripgrep's defaults: line numbers, hidden files skipped, `-t`, `-g`, `-l`, `-c`. |
| `find` | Walk a tree; `-name`, `-type`, `-path`, `-maxdepth`, `-mindepth`, `-exec ... ;`. |
| `fd` | Find by regex; `-t`, `-e`, `-H`, `-d`, `-x`. |
| `xargs` | Build commands from stdin; `-I`, `-n`, `-d`, `-0`. |

### Structured data

| Name | What it does |
|---|---|
| `jq` | JSON filters: field and index access, `.[]`, pipes, object and array construction, `if`, `map`, `select`, `sort_by`, `group_by`, `length` and the common builtins; `-r`, `-c`, `-e`, `-s`, `-n`, `--arg`, `--argjson`. |
| `yq` | The same filter language over YAML, TOML and JSON; `-o` and `-p` set the output and input format, `-i` edits in place. |

### Archives and compression

| Name | What it does |
|---|---|
| `tar` | Create, list and extract an uncompressed tar archive with `c`, `x`, `t`, `-f` and `-C`. |
| `gzip` | Compress a file, or stdin with `-c`; `-d` decompresses, `-k` keeps the input. |
| `gunzip` | `gzip -d`. |
| `bzip2` | Compress with bzip2. |
| `bunzip2` | Decompress bzip2. |
| `zcat` | Decompress gzip to stdout. |
| `bzcat` | Decompress bzip2 to stdout. |
| `lzcat` | A pass-through: there is no lzma, so it copies its input. |
| `zip` | Create a zip archive; `-r` folders, `-j` drops paths. |
| `unzip` | List with `-l` or extract, into `-d`. |
| `cpio` | Copy files in and out with `-o` and `-i`, in tar format. |
| `ar` | Create, list and extract an `ar` archive with `r`, `t` and `x`. |

`tar` does not compress. `tar czf` accepts the `z` and writes an
uncompressed archive, so compress it afterwards with `gzip`, or use `zip`.

### Numbers and identifiers

| Name | What it does |
|---|---|
| `expr` | Integer arithmetic, comparisons, `substr` and `match`; `expr length` prints `length`. |
| `bc` | Decimal arithmetic from stdin: `+`, `-`, `*`, `/`, `^` and parentheses. |
| `factor` | Prime factors of an integer. |
| `seq` | A sequence of numbers; `-s` sets the separator, `-w` pads. |
| `shuf` | Shuffle lines, or the arguments of `-e`. |
| `yes` | Repeat its arguments, capped at 10 000 lines. |
| `uuidgen` | A random UUID. |

### System information

These report fixed virtual values, not the host's:

| Name | What it does |
|---|---|
| `uname` | `VirtualOS spelaion 1.0.0 virtual`; `-a`, `-s`, `-n`, `-r`, `-m`. |
| `hostname` | `spelaion`. |
| `arch` | `x86_64`. |
| `whoami` | The `USER` variable, or `root`. |
| `id` | A `uid=`/`gid=` line for that user. |
| `groups` | The user's groups. |
| `logname` | The login name. |
| `users` | The logged-in users. |
| `w` | A session table. |
| `who` | The sessions, one per line. |
| `last` | Ten fixed login records. |
| `uptime` | The virtual uptime and load. |
| `free` | Fixed memory totals. |
| `nproc` | Four processors. |
| `ps` | One process, `spelaion`. |
| `top` | The same one-process table. |
| `date` | The host clock; `+FORMAT` uses `strftime`. |
| `tty` | `not a tty`, exit code 1. |

### Environment, time and processes

| Name | What it does |
|---|---|
| `printenv` | Print exported variables, or the named ones. |
| `env` | Print the exported environment; `-u` removes a name. |
| `which` | Say what a name is; there is no path to print. |
| `getopt` | Parse options with `-o OPTSTRING -- ARGS`. |
| `clear` | Nothing; the output is not a terminal. |
| `time` | Run a command and print fixed zero timings on stderr. |
| `timeout` | Stop a command at the next check after a duration; status 124. |
| `sleep` | Sleep, within the call's deadline; `s`, `m`, `h`, `d` units. |
| `usleep` | Sleep for microseconds. |
| `nice` | Run a command; the niceness is virtual. |
| `renice` | Change a niceness; virtual. |
| `chrt` | Change a scheduling policy; virtual. |
| `ionice` | Change an I/O class; virtual. |
| `nohup` | Run a command; there is no hangup to ignore. |
| `flock` | Run a command; the lock is virtual. |
| `sync` | Nothing; files are already in the mounts. |
| `fsync` | Nothing, for the same reason. |
| `kill` | Nothing; there are no processes to signal. |

### Python

| Name | What it does |
|---|---|
| `python` | CPython for WASI, when the sandbox was made with `python=True`. |
| `python3` | The same interpreter. |

Without `python=True`, both answer `<name>: not available in this sandbox`
with exit code 127. [Python](running-python-in-the-sandbox.html) covers what the guest can
reach.

## Builtins

A builtin runs inside the evaluator, not as a command. Forty-two names
resolve this way. `help` lists the thirty-nine that have a dispatch entry,
and `help .` and `help source` answer from their own lines; `[[` is an
extended test and has no help. `type` knows only the dispatch table, so
`type .`, `type source` and `type [[` all say `not found`.

| Group | Names |
|---|---|
| Variables and parameters | `export`, `unset`, `declare`, `local`, `readonly`, `set`, `read`, `shift`, `getopts`, `let`, `umask`, `ulimit` |
| Shell state and dispatch | `eval`, `source`, `.`, `exec`, `command`, `type`, `hash`, `alias`, `unalias`, `trap`, `help`, `times` |
| Navigation and output | `cd`, `pwd`, `echo`, `printf` |
| Tests and control flow | `test`, `[`, `[[`, `true`, `false`, `:`, `exit`, `return`, `break`, `continue` |
| Jobs | `wait`, `jobs`, `bg`, `fg` |

`set` handles `-e`, `-u`, `-x`, `-f` and `-o pipefail`; with no arguments
it prints the variables. `declare -A` makes an associative array and
`declare -a` does not make an indexed one. `read` splits a line on `IFS`.
`getopts` fills `OPTARG` and `OPTIND`. `command -v` prints a name and
`command -V` says what it is; `type` says the same for a function,
builtin or command. `eval` parses and runs its arguments in the current
shell. `source` and `.` run a file in the current shell, so their
variables survive. `trap`, `ulimit`, `umask`, `hash` and `times` keep
their state or print fixed values but change nothing real. `wait`, `jobs`,
`bg` and `fg` return success and do nothing: there are no background jobs.
`exit` ends the call with its status, and `return`, `break` and `continue`
unwind a function or loop.

## A conformance check

The rest of the program runs one representative line per area and prints
the label, the exit code and the first line of output. The last row is
deliberate: a host program the shell cannot find.

```{python continue export=examples/the_shell.py}
probes = [
    ("arrays", 'names=(a b c); echo "${names[1]} ${#names[@]}"'),
    ("parameter expansion", 'f=plan.yaml; echo "${f%.yaml}"'),
    ("arithmetic", "echo $(( (3 + 4) * 2 ))"),
    ("here-document", "cat <<EOF\nvalue: $((1 + 1))\nEOF"),
    ("PIPESTATUS", "false | true | false; echo ${PIPESTATUS[*]}"),
    ("text", "sort words.txt | uniq -c | sort -rn | head -1"),
    ("search", "grep -c red words.txt"),
    ("structured", "yq '.walls | length' plan.yaml"),
    ("archive", "tar cf out.tar plan.yaml && tar tf out.tar"),
    ("host program", "git status"),
]
for label, command in probes:
    r = sb.bash(command)
    lines = (r.stdout or r.stderr).strip().splitlines()
    print(f"{label:20} {r.exit_code:3}  {lines[0] if lines else ''}")
```

A zero means the line ran. A 127 means the name is not in the shell. The
`yq` row also shows that the YAML was read and the filter found two
walls.

## Known gaps

These are the places where a line parses and then does less than bash, or
fails where bash would not. Each block shows today's output.

### awk is a subset

`awk` understands patterns, `print`, `printf`, assignments, arithmetic and
`BEGIN`/`END`. It has no built-in functions and no `if`, `for` or `while`
inside an action. A function call is printed as text and a control-flow
statement is dropped, both without an error:

```{python continue}
r = sb.bash("printf 'abc\\nde\\n' | awk '{ print length($0) }'")
print(r.stdout, end="")
r = sb.bash("printf 'a\\n' | awk '{ if ($0 == \"a\") print \"yes\" }'")
print("if:", repr(r.stdout), "exit:", r.exit_code)
```

The first command prints the text `length($0)` for each line, because the
interpreter treats the call as a variable name. The second prints nothing
and still exits 0.

### A here-document followed by a semicolon

A `;` or `&` after the heredoc marker, or on its own line after the
terminator, is a syntax error. Put the next command on the following line,
or use `>`, `|`, `&&` or `||` on the marker or terminator line:

```{python continue}
r = sb.bash("cat <<EOF\nhi\nEOF\n; echo next")
print(r.stderr, end="")
print("exit code:", r.exit_code)
```

### /dev/null outside a redirection

Redirections to `/dev/null` work. A command that opens it as a file does
not, because `/dev` is not one of the mounts:

```{python continue}
r = sb.bash("echo hidden > /dev/null; echo ok")
print(r.stdout, end="")
r = sb.bash("cat /dev/null")
print(r.stderr, end="")
print("exit code:", r.exit_code)
```

### cmd & runs in the foreground

There are no background processes and no job control. `cmd &` waits for
`cmd`, so the next command sees its effect:

```{python continue}
r = sb.bash("rm -f out.txt; { sleep 0.15; echo late > out.txt; } & echo next; cat out.txt")
print(r.stdout, end="")
```

Bash would print `next` and then fail to read `out.txt`; here `late` is
already in the file.

### timeout checks at command boundaries

`timeout N cmd` stops `cmd` with status 124 at the next command it runs or
inside `sleep`. One long command runs on until the call's deadline:

```{python continue}
r = sb.bash("timeout 0.1 sleep 5; echo \"sleep: $?\"")
print(r.stdout, end="")
r = sb.bash("timeout 0.1 seq 1 200000 | wc -l")
print(r.stdout, end="")
```

`sleep` is interrupted and reports 124. `seq` produces all 200000 lines,
because the deadline is checked between commands and not inside `seq`.
[Limits](bounding-every-call.html) covers the call's own deadline.

### bash -c and sh -c are not commands

There is no host shell to hand the text to. A function does the same job:

```{python continue}
r = sb.bash("bash -c 'echo hi'; echo \"bash: $?\"")
print(r.stderr, end="")
print(r.stdout, end="")
r = sb.bash("sh -c 'echo hi'")
print(r.stderr, end="")
print("exit code:", r.exit_code)
```

### No links, and grep -r follows one

`ln` fails, for a symbolic or a hard link. `link` copies the file. A
symlink that already exists inside a mount is followed by `grep -r`, where
GNU grep skips it during recursion:

```{python continue}
r = sb.bash("ln plan.yaml hard.yaml")
print(r.stderr, end="")
(work / "alias.yaml").symlink_to("plan.yaml")
r = sb.bash("grep -r --include='*.yaml' demo .")
print(r.stdout, end="")
```

The second command prints both `./alias.yaml` and `./plan.yaml`. GNU grep
would print only the real file.

### ls -l and which

`ls -l` prints a fixed mode for every file, a real size, and no owner or
date. `which` has no path to print, so it says what the name is:

```{python continue}
r = sb.bash("ls -l words.txt")
print(r.stdout, end="")
r = sb.bash("which grep")
print(r.stdout, end="")
```

### Pipes carry text

A pipe carries UTF-8 text, so a command that writes compressed or other
binary bytes to stdout has them re-encoded on the way. Writing the bytes
straight to a file works:

```{python continue}
r = sb.bash("printf 'abc' | gzip -c | gunzip; echo \"pipe: $?\"")
print(r.stderr, end="")
print(r.stdout, end="")
r = sb.bash("printf 'abc' > raw.txt; gzip raw.txt; gunzip raw.txt.gz; cat raw.txt")
print(r.stdout, end="")
```

### No network and no host programs

`curl`, `pip` and `git` are host programs, and the shell has no tier that
starts one:

```{python continue}
for name in ("curl", "pip", "git"):
    r = sb.bash(name + " --version")
    print(r.stderr, end="")
```

All three answer `command not found` with exit code 127. The network is
absent by design, not by a missing command. [Security](the-security-model.html)
explains what the child can reach.

## The battery

`tests/battery` is the regression suite for exactly this question.
`cases.py` holds 104 commands coding agents write: pipes into `head` and
`tail`, `sed -i`, here-documents, `find | xargs`, `$(...)`, `diff -u`,
`grep -rn`, `jq`, and `python -c` with YAML. Five cases need
`python=True`; one case is marked as a known gap, the missing `length` in
`awk`.

`record.py` runs every case under real bash 5. It refuses another major
version, copies `fixtures/project` to `/project` and makes an empty
`/scratch` for each case, rewrites those paths, and writes stdout and the
exit code to `expected.json`. `test_battery.py` builds a `Sandbox` with
the same two mounts, the first read-only, runs each case, and compares
stdout and the exit code exactly. A case with a `gap` is an
`xfail(strict=True)`, so the suite fails if the gap closes without the
case being updated.

```bash
uv run python tests/battery/record.py   # re-record under bash 5
uv run pytest tests/battery
```

## The finished program

The file the chapter tangled is the check itself: it makes the folder,
runs the probes, and closes the sandbox. The last block stops the child
and removes the temporary folder:

```{python continue export=examples/the_shell.py}
sb.close()
shutil.rmtree(work)
```

A row with 0 says the line ran. A row with 127 says the agent will not
find that name, and the gaps above say what a line does when it parses but
does less than bash. [Testing with bash](testing-shell-scripts-with-bash.html) turns
this kind of check into a test, and [Bounding every call](bounding-every-call.html)
sets the deadline and the output cap the shell runs under.
