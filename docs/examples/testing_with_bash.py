from spelaion import Bash, CommandContext, CustomCommand, RunResult, define_command

PUBLISH = """\
publish() {
  local slug="$1"
  local body="$2"
  if [ ! -s "$body" ]; then
    echo "publish: empty body" >&2
    return 2
  fi
  mkdir -p drafts
  cp "$body" "drafts/$slug.md"
  echo "published $slug"
  notify "published $slug"
}
"""


def recorder() -> tuple[list[CustomCommand], list[dict[str, object]]]:
    calls: list[dict[str, object]] = []

    def record(args: list[str], ctx: CommandContext) -> RunResult:
        calls.append({"args": args, "cwd": ctx.cwd, "stdin": ctx.stdin})
        return RunResult()

    return [define_command("notify", record)], calls


def new_shell(commands: list[CustomCommand] | None = None) -> Bash:
    bash = Bash(env={"PAGER": "cat"}, cwd="/repo", custom_commands=commands)
    bash.write_files(
        {
            "/repo/bin/publish.sh": PUBLISH,
            "/repo/draft.md": "hello world\n",
            "/repo/empty.md": "",
        }
    )
    return bash


def test_publish():
    commands, calls = recorder()
    bash = new_shell(commands)
    result = bash.run("source bin/publish.sh && publish hello draft.md")
    assert result.exit_code == 0, result.stderr
    assert result.stdout == "published hello\n"
    assert bash.file_exists("drafts/hello.md")
    assert bash.read_file("drafts/hello.md") == "hello world\n"
    assert calls == [{"args": ["published hello"], "cwd": "/repo", "stdin": ""}]


def test_empty_body():
    commands, calls = recorder()
    bash = new_shell(commands)
    result = bash.run("source bin/publish.sh && publish empty empty.md")
    assert result.exit_code == 2
    assert result.stderr == "publish: empty body\n"
    assert not bash.file_exists("drafts/empty.md")
    assert calls == []


def test_state_between_calls():
    bash = Bash(cwd="/repo")
    bash.run("LIMIT=3")
    bash.run("show() { echo $LIMIT; }")
    bash.run("mkdir -p drafts && cd drafts")
    assert isinstance(bash.run("show"), RunResult)
    assert bash.run("show").stdout == "3\n"
    assert bash.run("pwd").stdout == "/repo/drafts\n"


test_publish()
test_empty_body()
test_state_between_calls()
print("3 tests passed")
