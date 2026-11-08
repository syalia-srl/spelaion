"""Commands coding agents write, with what real bash 5 prints for them.

Each case runs with ``/project`` (read-only, ``fixtures/project``) and
``/scratch`` (writable, empty) mounted and ``/scratch`` as the working
directory. ``record.py`` runs every case under real bash on copies of the
same files and writes ``expected.json``; ``test_battery.py`` runs it through
a ``Sandbox`` and compares stdout and the exit code.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Case:
    name: str
    command: str
    # Needs python in the sandbox (CPython for WASI).
    python: bool = False
    # Why spelaion does not match bash yet; the test is an xfail.
    gap: str | None = None


CASES: list[Case] = [
    # The spike's twenty.
    Case("cat | wc", "cat /project/plan.yaml | wc -l"),
    Case("grep -n", "grep -n 'id: w' /project/plan.yaml"),
    Case(
        "sed -i",
        "cp /project/plan.yaml plan.yaml && sed -i 's/4.0/4.5/g' plan.yaml"
        " && grep -c 4.5 plan.yaml",
    ),
    Case("heredoc quoted", "cat > a.txt <<'EOF'\nhola $X\nEOF\ncat a.txt"),
    Case("for | tail -1", "for i in 1 2 3; do echo silla-$i; done | tail -1"),
    Case("$(...)", 'n=$(grep -c id /project/plan.yaml); echo "n=$n"'),
    Case(
        "awk | sort | head",
        "awk '/id:/ {print $3}' /project/plan.yaml | sort | head -1",
    ),
    Case(
        "find | xargs wc",
        "find /project -name '*.yaml' | xargs wc -l | tail -1",
    ),
    Case("if [ -f ]", "if [ -f /project/plan.yaml ]; then echo yes; else echo no; fi"),
    Case("false ||", "false || echo recovered"),
    Case(
        "diff -u",
        "cp /project/plan.yaml b.yaml && sed -i s/pb/pa/ b.yaml"
        " && diff -u /project/plan.yaml b.yaml | tail -n +3",
    ),
    Case("jq length", """echo '{"a":[1,2,3]}' | jq '.a | length'"""),
    Case("printf format", "printf '%s-%03d\\n' silla 7"),
    Case("arithmetic", "echo $(( 3 * 7 ))"),
    Case("function", 'f() { echo "got $1"; }; f x'),
    Case("2>&1 |", "cat /nope 2>&1 | head -1"),
    Case("sort | uniq -c", "sort /project/words.txt | uniq -c"),
    Case("cut | tr", "echo 'a:b:c' | cut -d: -f2 | tr a-z A-Z"),
    Case("head -n -1", "printf '1\\n2\\n3\\n' | head -n -1 | tail -1"),
    Case("ls | grep", "ls /project | grep plan"),
    # Obsolete short forms agents still write.
    Case("tail -1", "printf '1\\n2\\n' | tail -1"),
    Case("head -2", "printf '1\\n2\\n3\\n' | head -2"),
    Case(
        "wc several files",
        "cd /project && wc -l plan.yaml README.md words.txt",
    ),
    # Search and inspect.
    Case("grep -rn", "grep -rn TODO /project/src | sort"),
    Case(
        "grep -rl --include",
        "grep -rl --include='*.py' greet /project | sort",
    ),
    Case("grep -c no match", "grep -c nothing /project/plan.yaml; echo rc=$?"),
    Case("find -type f | sort", "cd /project && find . -type f | sort"),
    Case("find -name | wc", "find /project -name '*.py' | wc -l"),
    Case(
        "find -exec grep",
        "find /project/src -name '*.py' -exec grep -l import {} + | sort",
    ),
    Case(
        "sort | uniq -c | sort -rn",
        "sort /project/words.txt | uniq -c | sort -rn | head -1",
    ),
    Case("head several files", "cd /project && head -2 plan.yaml words.txt"),
    Case("tail -n +N", "tail -n +12 /project/plan.yaml"),
    Case("grep -r relative", "cd /project && grep -rn VALUE src"),
    Case("grep -r no folder", "cd /project/src && grep -rl greet | sort"),
    Case(
        "grep missing file",
        "grep -h id /project/plan.yaml /nope | wc -l; grep -q x /nope; echo rc=$?",
    ),
    Case("sort -k2n", "printf 'b 10\\na 9\\nc 100\\n' | sort -k2n"),
    Case("sort -t -k", "printf 'x,3\\ny,1\\n' | sort -t, -k2 | head -1"),
    Case("uniq -cd", "sort /project/words.txt | uniq -cd"),
    Case("cat | wc all counts", "cat /project/words.txt | wc"),
    Case("wc file", "wc /project/plan.yaml"),
    Case("ls file and folder", "ls /project/plan.yaml /project/src"),
    Case("head -n file", "head -n 3 /project/src/app.py"),
    Case("sed -n range", "sed -n '2,4p' /project/plan.yaml"),
    Case(
        "awk sum",
        "printf '3\\n4\\n5\\n' | awk '{s+=$1} END {print s}'",
    ),
    Case(
        "awk average", "printf '2\\n3\\n7\\n' | awk '{n++; t+=$1} END {print n, t/n}'"
    ),
    Case(
        "awk length()",
        "awk '{t+=length($0)} END {print t}' /project/words.txt",
        gap="awk has no built-in functions (length, substr, split, ...)",
    ),
    Case("awk -F", "awk -F': ' '/height/ {print NR, $2}' /project/plan.yaml"),
    Case("cat spaces", "cat '/project/notes with spaces.txt' | wc -l"),
    Case("jq -r .[]", "jq -r '.deps[].name' /project/data.json"),
    Case(
        "jq select",
        """jq -r '.deps[] | select(.name == "rich") | .pin' /project/data.json""",
    ),
    # Edit and build.
    Case(
        "heredoc expands",
        "NAME=w; cat > b.txt <<EOF\nhello $NAME\n$(echo sub)\nEOF\ncat b.txt",
    ),
    Case("heredoc > f", "cat <<'EOF' > f\nhola $X\nEOF\ncat f"),
    Case("heredoc | wc", "cat <<EOF | wc -l\na\nb\nEOF"),
    Case("heredoc &&", "cat <<EOF && echo after\nx\nEOF"),
    Case("heredoc >> f", "echo one > f && cat <<EOF >> f\ntwo\nEOF\ncat f"),
    Case(
        "heredoc | | && ||",
        "cat <<EOF | grep b | wc -l && echo ok || echo no\nb\na\nb\nEOF",
    ),
    Case("&& heredoc |", "false && cat <<EOF | wc -l\nx\nEOF\necho rc=$?"),
    Case("heredoc > f &&", "cat <<EOF > g && cat g\nY=$((1+1))\nEOF"),
    Case(
        "heredoc $VAR > f",
        "N=7; cat <<EOF > v.txt\nn=$N\nEOF\ncat <<'EOF' >> v.txt\nn=$N\nEOF\ncat v.txt",
    ),
    Case(
        "sed -i multiple",
        "cp /project/src/util.py u.py && sed -i -e 's/greet/salute/g' -e '/TODO/d' u.py"
        " && cat u.py",
    ),
    Case(
        "mkdir -p && echo >",
        "mkdir -p out/a/b && echo hi > out/a/b/c.txt && cat out/a/b/c.txt",
    ),
    Case("cp -r", "cp -r /project/src src2 && find src2 -type f | sort"),
    Case("cp -r into folder", "mkdir dst && cp -r /project/src dst && find dst | sort"),
    Case(
        "cp files into folder",
        "mkdir dst && cp /project/plan.yaml /project/README.md dst && ls dst",
    ),
    Case(
        "cp -r into itself",
        "mkdir -p d && cp -r d d/e; echo rc=$?; ls d",
    ),
    Case("&& then >", "echo a && echo b > f; echo --; cat f"),
    Case("| then >", "echo a | tr a b > f && cat f"),
    Case("2>/dev/null", "cat /nope 2>/dev/null; echo rc=$?"),
    Case(">/dev/null 2>&1", "ls /project >/dev/null 2>&1 && echo quiet"),
    Case("< /dev/null", "wc -l < /dev/null"),
    Case(
        "append >>",
        "echo one > log && echo two >> log && cat log",
    ),
    Case(
        "group >> and 2>&1",
        "{ echo a; echo b; } >> g; echo c >> g 2>&1; cat g",
    ),
    Case("test -d && ||", "[ -d /project/src ] && echo dir || echo none"),
    Case("test -z", 'x=""; if [ -z "$x" ]; then echo empty; fi'),
    Case("for over glob", "for f in /project/src/*.py; do basename $f; done"),
    Case("glob skips dot names", "touch .h v && echo * && echo .*"),
    Case(
        "glob ../*",
        "mkdir -p sub e && touch e/x && cd /scratch/sub && echo ../* && ls ../*",
    ),
    Case("glob ./*", "touch a b && echo ./*"),
    Case("glob src/../*", "cd /project && echo src/../*.md src/../s*"),
    Case("while read", "printf 'a b\\nc d\\n' | while read x y; do echo $y$x; done"),
    Case("$? after fail", "grep -q zzz /project/plan.yaml; echo $?"),
    Case("set -e", "set -e; false; echo unreachable"),
    Case("null builtin", ": ; echo $?"),
    Case(
        "true in while",
        "i=0; while :; do i=$((i+1)); [ $i -ge 3 ] && break; done; echo $i",
    ),
    Case("command -v", "command -v jq >/dev/null && echo has jq || echo no jq"),
    Case("command -v missing", "command -v nosuchtool || echo missing"),
    Case("case", "x=b.py; case $x in *.py) echo py;; *) echo other;; esac"),
    Case(
        "multi-file error",
        "cat /project/plan.yaml /nope | wc -l; echo rc=${PIPESTATUS[0]}",
    ),
    Case(
        "wc missing file",
        "cd /project && wc -l plan.yaml nope words.txt; echo rc=$?",
    ),
    Case("PIPESTATUS", "true | false | true; echo ${PIPESTATUS[@]}"),
    Case("sleep short", "sleep 0.1; echo slept"),
    # python with the bundled PyYAML.
    Case("python -c", "python3 -c 'print(sum(range(10)))'", python=True),
    Case(
        "python yaml",
        'python3 -c \'import yaml; d = yaml.safe_load(open("/project/plan.yaml"));'
        ' print(len(d["walls"]))\'',
        python=True,
    ),
    Case(
        "python heredoc",
        "python3 - <<'EOF'\nimport json\n"
        "print(json.load(open('/project/data.json'))['version'])\nEOF",
        python=True,
    ),
    Case(
        "python heredoc > f",
        "python3 - <<'EOF' > out.txt\nprint(2 ** 10)\nEOF\ncat out.txt",
        python=True,
    ),
    Case("python | grep", "python3 -c 'print(\"a\\nb\\nc\")' | grep -c .", python=True),
]
