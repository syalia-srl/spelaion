import struct
import tempfile
import zlib
from pathlib import Path

from spelaion import Mount, Result, Sandbox

PLAN = [
    "#########",
    "#...#...#",
    "#...#...#",
    "#...+...#",
    "#...#...#",
    "##++#++##",
    "#...#...#",
    "#...#...#",
    "#########",
]
COLORS = {"#": (40, 42, 54), ".": (240, 240, 232), "+": (150, 152, 168)}


def png(rows: list[str], scale: int = 24) -> bytes:
    """An RGB PNG of rows of characters, each one a block of *scale* pixels."""
    width, height = len(rows[0]) * scale, len(rows) * scale
    raw = [
        b"\x00" + b"".join(bytes(COLORS[c]) * scale for c in row)
        for row in rows
        for _ in range(scale)
    ]

    def chunk(tag: bytes, data: bytes) -> bytes:
        return (
            struct.pack(">I", len(data))
            + tag
            + data
            + struct.pack(">I", zlib.crc32(tag + data))
        )

    header = struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)
    return (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", header)
        + chunk(b"IDAT", zlib.compress(b"".join(raw)))
        + chunk(b"IEND", b"")
    )


project = Path(tempfile.mkdtemp())
plan = png(PLAN)
(project / "plan.png").write_bytes(plan)
print(len(plan), "bytes")
sb = Sandbox([Mount("/work", host=project)], cwd="/work")

r = sb.bash("cat plan.png")
print("exit code:", r.exit_code)
print("characters:", len(r.stdout))
print("replacement characters:", r.stdout.count("\ufffd"))
r = sb.bash("show plan.png")
print("exit code:", r.exit_code)
print("stdout:", repr(r.stdout))
for a in r.attachments:
    print(a.mime, a.name, len(a.data))
r = sb.bash("show plan.png && echo 'first draft'")
print("stdout:", repr(r.stdout))
print("images:", len(r.attachments))
(project / "plan.txt").write_bytes((project / "plan.png").read_bytes())
(project / "notes.txt").write_text("wall thickness: 12 cm\n")

print([(a.mime, a.name) for a in sb.bash("show plan.txt").attachments])
r = sb.bash("show notes.txt")
print(r.stderr, end="")
print("exit code:", r.exit_code)
SCALE_MIN, SCALE_MAX = 4, 48


@sb.command
def preview(ctx, args):
    """Attach the plan with cells of SCALE pixels."""
    if not args or not args[0].isdigit() or not SCALE_MIN <= int(args[0]) <= SCALE_MAX:
        return Result(stderr="preview: usage: preview SCALE (4 to 48)\n", exit_code=2)
    data = png(PLAN, int(args[0]))
    ctx.attach(data, name=f"preview-{args[0]}.png")
    return Result(stdout=f"{len(data)} bytes\n")


r = sb.bash("preview 12")
print(r.stdout, end="")
print([(a.mime, a.name, len(a.data)) for a in r.attachments])
tools = sb.tools()
out = tools[0].fn(command="show plan.png")
print("text:", repr(out.text))
print("images:", [(a.mime, a.name, len(a.data)) for a in out.images])
sb.close()
