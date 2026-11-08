# Showing the model images

Your product renders a floor plan, a chart or a screenshot, and an agent has to
check it. A model reads a message of text and images; a PNG that reaches it as a
string of characters is not a picture. spelaion does not call a model itself, so
the images it collects go to the code that does: one shell call returns its text
and the images beside it, as separate values.

## A plan the product can draw

The plan below is nine rows of nine characters: `#` is a wall, `.` a floor and
`+` a doorway. `png()` turns the rows into an RGB PNG with 24 pixels per cell,
so the image is 216 by 216 pixels. A PNG is a signature, an `IHDR` chunk with
the size, an `IDAT` chunk with the zlib-compressed rows and an `IEND` chunk, and
each chunk carries its length and a CRC32. `zlib` and `struct` are in the
standard library, so the example writes a real PNG without an imaging package.
Each raw row starts with a zero byte, the filter the format requires.

```{python export=examples/images.py}
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
```

## What cat gives the model

A `Mount` puts the product's folder at a path inside the sandbox, and the
sandbox runs the shell over it. The plan is a real file on the host, so the
agent can read it with an ordinary command:

```{python continue export=examples/images.py}
sb = Sandbox([Mount("/work", host=project)], cwd="/work")

r = sb.bash("cat plan.png")
print("exit code:", r.exit_code)
print("characters:", len(r.stdout))
print("replacement characters:", r.stdout.count("\ufffd"))
```

`cat` succeeds, and that is the problem. The shell decodes the file as UTF-8
and replaces every byte that does not decode, so the 1,379 bytes arrive as
1,322 characters, 508 of them U+FFFD. The damage is lossy: the bytes of the
image cannot be recovered from the text, and no pixel reaches the model. Sending
the file as base64 would preserve the bytes, but it would still leave the model
with a string to decode instead of an image to look at.

## The built-in show command

Every sandbox registers one host command for this purpose. `show` runs in the
host process, not in the child shell, reads each file through the mount and
attaches it to the call:

```{python continue export=examples/images.py}
r = sb.bash("show plan.png")
print("exit code:", r.exit_code)
print("stdout:", repr(r.stdout))
for a in r.attachments:
    print(a.mime, a.name, len(a.data))
```

The call printed nothing and exited 0. `Result.attachments` holds one
`Attachment` for each image: its `mime` type, its `data` bytes and its `name`.
Here the name is the sandbox path the file came from, and the data is the same
1,379 bytes on disk. `edit` and `write` return the same field, always empty,
because no host command runs in them. The book can show those bytes, because scriptorium draws
any object whose `_repr_png_` returns them:

```{python continue output=asis caption="The plan as the model receives it"}
class Shown:
    """Shows an attachment's bytes as an image in this book."""

    def __init__(self, attachment):
        self._data = attachment.data

    def _repr_png_(self):
        return self._data


Shown(r.attachments[0])
```

That block is for the book only and is not part of the program. A call can also
print text and show an image at once. stdout stays text, attachments stay
images, and the model gets both:

```{python continue export=examples/images.py}
r = sb.bash("show plan.png && echo 'first draft'")
print("stdout:", repr(r.stdout))
print("images:", len(r.attachments))
```

`show` takes any number of files, within the limits below. With no argument it
prints `show: usage: show FILE...` and exits 2.

## The bytes decide the type

The extension plays no part. Rename the image and it is still a PNG:

```{python continue export=examples/images.py}
(project / "plan.txt").write_bytes((project / "plan.png").read_bytes())
(project / "notes.txt").write_text("wall thickness: 12 cm\n")

print([(a.mime, a.name) for a in sb.bash("show plan.txt").attachments])
r = sb.bash("show notes.txt")
print(r.stderr, end="")
print("exit code:", r.exit_code)
```

spelaion reads the first bytes of the file: `\x89PNG\r\n\x1a\n` for PNG,
`\xff\xd8\xff` for JPEG, and `RIFF` with `WEBP` at offset 8 for WebP. The file
named `plan.txt` is attached as `image/png`, and its name still records where it
came from. A file that starts with none of those signatures is refused with
exit code 1.

## Images the product makes in memory

A renderer often hands back bytes and never writes them into a mounted folder.
A host command is the place to catch them. `ctx.attach` takes the bytes, finds
the type the same way and appends the image to the call:

```{python continue export=examples/images.py}
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
```

`preview 12` printed 337 bytes and returned one image named `preview-12.png`.
That name is a label, not a path: no such file exists on disk, and without a
name the attachment is called `image`. `ctx.attach` also accepts a sandbox path
instead of bytes, which is the form `show` uses for each of its arguments. A
handler can also build `Attachment(mime, data, name)` objects and put them in
`Result.attachments`, and the sandbox appends those to the call as well.

## What one call will not carry

Images take space in a model request, so spelaion bounds each image and each
call. Each failure raises `ValueError` in the handler; through the shell it
reads `show: <message>` on stderr with exit code 1.

| Limit | Value | Message |
| --- | --- | --- |
| One image | 5 MB, 5,242,880 bytes | `<name>: larger than 5 MB` |
| Images in one call | 8 | `too many images in one call` |
| All images in one call | 20 MB, 20,971,520 bytes | `images too large for one call` |
| Type | PNG, JPEG, WebP | `<name>: not a PNG, JPEG or WebP image` |

A file slightly over 5 MB is refused after it is read, before its type is checked:

```{python continue}
(project / "huge.png").write_bytes(b"\x89PNG\r\n\x1a\n" + bytes(5 * 2**20))
r = sb.bash("show huge.png")
print(r.stderr, end="")
print("exit code:", r.exit_code, "images:", len(r.attachments))
```

The ninth image of a call is refused, and the eight attached before it stay in
the result. Nothing rolls back, so an agent that ignores the exit code still
receives eight images:

```{python continue}
r = sb.bash("show " + " ".join(["plan.png"] * 9))
print(r.stderr, end="")
print("exit code:", r.exit_code, "images:", len(r.attachments))
```

The byte total counts every image already attached to the call, whichever host
command attached it. Here six images of 3 MB fit and the seventh would pass
20 MB:

```{python continue}
(project / "big.png").write_bytes(b"\x89PNG\r\n\x1a\n" + bytes(3 * 2**20))
r = sb.bash("show " + " ".join(["big.png"] * 7))
print(r.stderr, end="")
print("exit code:", r.exit_code, "images:", len(r.attachments))
```

## Handing the images to a model loop

When your own code calls the model, take the tools from `sb.tools()`. The list
is `bash`, `edit` and `write`, in that order. Each tool's function returns a
`ToolOutput`, which carries the text the model should read and the `images` list
of the same `Attachment` objects:

```{python continue export=examples/images.py}
tools = sb.tools()
out = tools[0].fn(command="show plan.png")
print("text:", repr(out.text))
print("images:", [(a.mime, a.name, len(a.data)) for a in out.images])
```

The text is empty because the call printed nothing, and the model still has an
image to look at. `(no output)` appears only when a call prints nothing and
attaches nothing. The description of `bash` ends with `show FILE... shows you
PNG, JPEG or WebP images.`, so a model that reads the tool list knows the
command exists. Over MCP the same list becomes a text content block followed by
one image content block per attachment, base64 encoded.

```{python continue export=examples/images.py}
sb.close()
```

`close()` stops the child process, and a `Sandbox` used as a context manager
does it on the way out.

## Where to go next

- [Host commands](05-host-commands.md): what a handler receives and what it may
  do with it.
- [Bounding every call](03-limits.md): the deadline, output and disk caps.
- [Your own loop](07-own-loop.md): the tool call and the model message around
  it.
- [MCP servers](08-mcp.md): serving these tools to Claude Code or OpenCode.
