"""Archive and compression commands.

tar, gzip, gunzip, bzip2, bunzip2, zcat, bzcat, lzcat, unzip, cpio, ar.
"""

from __future__ import annotations

import bz2
import io as _io
import posixpath
import tarfile
import zipfile
from typing import TYPE_CHECKING

from agentsh.commands._io import read_binary_inputs
from agentsh.commands._registry import command
from agentsh.runtime.result import CommandResult

if TYPE_CHECKING:
    from agentsh.exec.redirs import IOContext
    from agentsh.runtime.state import ShellState
    from agentsh.vfs.filesystem import VirtualFilesystem


# ---------------------------------------------------------------------------
# tar
# ---------------------------------------------------------------------------


@command("tar")
def cmd_tar(  # noqa: C901
    args: list[str], state: ShellState, vfs: VirtualFilesystem, io: IOContext
) -> CommandResult:
    mode: str | None = None  # "c", "x", "t"
    archive: str | None = None
    extract_dir: str | None = None
    files: list[str] = []

    i = 0
    while i < len(args):
        a = args[i]
        if a in ("cf", "xf", "tf"):
            mode = a[0]
            if i + 1 < len(args):
                i += 1
                archive = args[i]
        elif a in ("-c", "--create"):
            mode = "c"
        elif a in ("-x", "--extract"):
            mode = "x"
        elif a in ("-t", "--list"):
            mode = "t"
        elif a in ("-f", "--file") and i + 1 < len(args):
            i += 1
            archive = args[i]
        elif a == "-C" and i + 1 < len(args):
            i += 1
            extract_dir = args[i]
        elif not a.startswith("-"):
            # Could be a combined flag like "czf" or a file argument
            if mode is None and len(a) >= 2 and a[0] in "cxt":
                mode = a[0]
                if "f" in a[1:] and i + 1 < len(args):
                    i += 1
                    archive = args[i]
            else:
                files.append(a)
        i += 1

    if mode is None:
        io.stderr.write("tar: missing operation flag (c/x/t)\n")
        return CommandResult(exit_code=1)

    if archive is None:
        io.stderr.write("tar: missing archive name (-f)\n")
        return CommandResult(exit_code=1)

    if mode == "c":
        return _tar_create(archive, files, state, vfs, io)
    elif mode == "x":
        return _tar_extract(archive, extract_dir, state, vfs, io)
    else:  # mode == "t"
        return _tar_list(archive, state, vfs, io)


def _tar_create(
    archive: str,
    files: list[str],
    state: ShellState,
    vfs: VirtualFilesystem,
    io: IOContext,
) -> CommandResult:
    buf = _io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w") as tf:
        for f in files:
            abs_path = vfs.resolve(f, state.cwd)
            if vfs.is_dir(abs_path):
                # Add directory recursively
                for dirpath, _dirs, fnames in vfs.walk(abs_path):
                    for fname in fnames:
                        full = dirpath.rstrip("/") + "/" + fname
                        # Compute relative name within the tar
                        rel = f.rstrip("/") + full[len(abs_path) :]
                        data = vfs.read(full)
                        info = tarfile.TarInfo(name=rel)
                        info.size = len(data)
                        tf.addfile(info, _io.BytesIO(data))
            elif vfs.is_file(abs_path):
                data = vfs.read(abs_path)
                info = tarfile.TarInfo(name=f)
                info.size = len(data)
                tf.addfile(info, _io.BytesIO(data))
            else:
                io.stderr.write(f"tar: {f}: No such file or directory\n")
                return CommandResult(exit_code=1)

    archive_path = vfs.resolve(archive, state.cwd)
    vfs.write(archive_path, buf.getvalue())
    return CommandResult(exit_code=0)


def _tar_extract(
    archive: str,
    extract_dir: str | None,
    state: ShellState,
    vfs: VirtualFilesystem,
    io: IOContext,
) -> CommandResult:
    archive_path = vfs.resolve(archive, state.cwd)
    try:
        data = vfs.read(archive_path)
    except FileNotFoundError:
        io.stderr.write(f"tar: {archive}: No such file or directory\n")
        return CommandResult(exit_code=1)

    target_dir = state.cwd
    if extract_dir:
        target_dir = vfs.resolve(extract_dir, state.cwd)
        if not vfs.is_dir(target_dir):
            vfs.mkdir(target_dir, parents=True)

    buf = _io.BytesIO(data)
    try:
        with tarfile.open(fileobj=buf, mode="r:*") as tf:
            for member in tf.getmembers():
                if member.isfile():
                    f = tf.extractfile(member)
                    if f is not None:
                        content = f.read()
                        out_path = vfs.resolve(member.name, target_dir)
                        vfs.write(out_path, content)
    except tarfile.TarError as e:
        io.stderr.write(f"tar: error reading archive: {e}\n")
        return CommandResult(exit_code=1)

    return CommandResult(exit_code=0)


def _tar_list(
    archive: str,
    state: ShellState,
    vfs: VirtualFilesystem,
    io: IOContext,
) -> CommandResult:
    archive_path = vfs.resolve(archive, state.cwd)
    try:
        data = vfs.read(archive_path)
    except FileNotFoundError:
        io.stderr.write(f"tar: {archive}: No such file or directory\n")
        return CommandResult(exit_code=1)

    buf = _io.BytesIO(data)
    try:
        with tarfile.open(fileobj=buf, mode="r:*") as tf:
            for member in tf.getmembers():
                io.stdout.write(member.name + "\n")
    except tarfile.TarError as e:
        io.stderr.write(f"tar: error reading archive: {e}\n")
        return CommandResult(exit_code=1)

    return CommandResult(exit_code=0)


# ---------------------------------------------------------------------------
# gzip / gunzip
# ---------------------------------------------------------------------------


def _gzip_compress(data: bytes) -> bytes:
    """Compress data using gzip format (zlib with gzip wrapper)."""
    return _gzip_encode(data)


def _gzip_encode(data: bytes) -> bytes:
    """Produce a minimal gzip stream."""
    # Use Python's gzip module via BytesIO
    import gzip as _gzip_mod

    buf = _io.BytesIO()
    with _gzip_mod.GzipFile(fileobj=buf, mode="wb") as gz:
        gz.write(data)
    return buf.getvalue()


def _gzip_decode(data: bytes) -> bytes:
    """Decompress a gzip stream."""
    import gzip as _gzip_mod

    buf = _io.BytesIO(data)
    with _gzip_mod.GzipFile(fileobj=buf, mode="rb") as gz:
        return gz.read()


@command("gzip")
def cmd_gzip(
    args: list[str], state: ShellState, vfs: VirtualFilesystem, io: IOContext
) -> CommandResult:
    decompress = False
    keep = False
    to_stdout = False
    files: list[str] = []

    for a in args:
        if a in ("-d", "--decompress"):
            decompress = True
        elif a in ("-k", "--keep"):
            keep = True
        elif a in ("-c", "--stdout"):
            to_stdout = True
        elif not a.startswith("-"):
            files.append(a)

    if not files:
        return _gzip_stdio(decompress, io)

    for f in files:
        result = _gzip_file(f, decompress, keep, to_stdout, state, vfs, io)
        if result is not None:
            return result

    return CommandResult(exit_code=0)


def _gzip_stdio(decompress: bool, io: IOContext) -> CommandResult:
    """Handle gzip on stdin/stdout."""
    raw = io.stdin.read().encode("utf-8")
    if decompress:
        try:
            result = _gzip_decode(raw)
        except Exception:
            io.stderr.write("gzip: stdin: not in gzip format\n")
            return CommandResult(exit_code=1)
        io.stdout.write(result.decode("utf-8", errors="replace"))
    else:
        compressed = _gzip_encode(raw)
        io.stdout.write(compressed.decode("latin-1"))
    return CommandResult(exit_code=0)


def _gzip_file(
    f: str,
    decompress: bool,
    keep: bool,
    to_stdout: bool,
    state: ShellState,
    vfs: VirtualFilesystem,
    io: IOContext,
) -> CommandResult | None:
    """Process a single file for gzip. Returns result on error, else None."""
    abs_path = vfs.resolve(f, state.cwd)
    try:
        data = vfs.read(abs_path)
    except FileNotFoundError:
        io.stderr.write(f"gzip: {f}: No such file or directory\n")
        return CommandResult(exit_code=1)

    if decompress:
        if not f.endswith(".gz"):
            io.stderr.write(f"gzip: {f}: unknown suffix -- ignored\n")
            return None
        try:
            result_data = _gzip_decode(data)
        except Exception:
            io.stderr.write(f"gzip: {f}: not in gzip format\n")
            return CommandResult(exit_code=1)
        if to_stdout:
            io.stdout.write(result_data.decode("utf-8", errors="replace"))
        else:
            out_path = vfs.resolve(f[:-3], state.cwd)
            vfs.write(out_path, result_data)
            if not keep:
                vfs.unlink(abs_path)
    else:
        compressed = _gzip_encode(data)
        if to_stdout:
            io.stdout.write(compressed.decode("latin-1"))
        else:
            out_path = vfs.resolve(f + ".gz", state.cwd)
            vfs.write(out_path, compressed)
            if not keep:
                vfs.unlink(abs_path)
    return None


@command("gunzip")
def cmd_gunzip(
    args: list[str], state: ShellState, vfs: VirtualFilesystem, io: IOContext
) -> CommandResult:
    return cmd_gzip(["-d", *args], state, vfs, io)


# ---------------------------------------------------------------------------
# bzip2 / bunzip2
# ---------------------------------------------------------------------------


@command("bzip2")
def cmd_bzip2(
    args: list[str], state: ShellState, vfs: VirtualFilesystem, io: IOContext
) -> CommandResult:
    decompress = False
    keep = False
    to_stdout = False
    files: list[str] = []

    for a in args:
        if a in ("-d", "--decompress"):
            decompress = True
        elif a in ("-k", "--keep"):
            keep = True
        elif a in ("-c", "--stdout"):
            to_stdout = True
        elif not a.startswith("-"):
            files.append(a)

    if not files:
        return _bz2_stdio(decompress, io)

    for f in files:
        result = _bz2_file(f, decompress, keep, to_stdout, state, vfs, io)
        if result is not None:
            return result

    return CommandResult(exit_code=0)


def _bz2_stdio(decompress: bool, io: IOContext) -> CommandResult:
    """Handle bzip2 on stdin/stdout."""
    raw = io.stdin.read().encode("utf-8")
    if decompress:
        try:
            result = bz2.decompress(raw)
        except Exception:
            io.stderr.write("bzip2: stdin: not in bzip2 format\n")
            return CommandResult(exit_code=1)
        io.stdout.write(result.decode("utf-8", errors="replace"))
    else:
        compressed = bz2.compress(raw)
        io.stdout.write(compressed.decode("latin-1"))
    return CommandResult(exit_code=0)


def _bz2_file(
    f: str,
    decompress: bool,
    keep: bool,
    to_stdout: bool,
    state: ShellState,
    vfs: VirtualFilesystem,
    io: IOContext,
) -> CommandResult | None:
    """Process a single file for bzip2. Returns result on error."""
    abs_path = vfs.resolve(f, state.cwd)
    try:
        data = vfs.read(abs_path)
    except FileNotFoundError:
        io.stderr.write(f"bzip2: {f}: No such file or directory\n")
        return CommandResult(exit_code=1)

    if decompress:
        if not f.endswith(".bz2"):
            io.stderr.write(f"bzip2: {f}: unknown suffix -- ignored\n")
            return None
        try:
            result_data = bz2.decompress(data)
        except Exception:
            io.stderr.write(f"bzip2: {f}: not in bzip2 format\n")
            return CommandResult(exit_code=1)
        if to_stdout:
            io.stdout.write(result_data.decode("utf-8", errors="replace"))
        else:
            out_path = vfs.resolve(f[:-4], state.cwd)
            vfs.write(out_path, result_data)
            if not keep:
                vfs.unlink(abs_path)
    else:
        compressed = bz2.compress(data)
        if to_stdout:
            io.stdout.write(compressed.decode("latin-1"))
        else:
            out_path = vfs.resolve(f + ".bz2", state.cwd)
            vfs.write(out_path, compressed)
            if not keep:
                vfs.unlink(abs_path)
    return None


@command("bunzip2")
def cmd_bunzip2(
    args: list[str], state: ShellState, vfs: VirtualFilesystem, io: IOContext
) -> CommandResult:
    return cmd_bzip2(["-d", *args], state, vfs, io)


# ---------------------------------------------------------------------------
# zcat / bzcat / lzcat
# ---------------------------------------------------------------------------


@command("zcat")
def cmd_zcat(
    args: list[str], state: ShellState, vfs: VirtualFilesystem, io: IOContext
) -> CommandResult:
    return cmd_gzip(["-d", "-c", *args], state, vfs, io)


@command("bzcat")
def cmd_bzcat(
    args: list[str], state: ShellState, vfs: VirtualFilesystem, io: IOContext
) -> CommandResult:
    return cmd_bzip2(["-d", "-c", *args], state, vfs, io)


@command("lzcat")
def cmd_lzcat(
    args: list[str], state: ShellState, vfs: VirtualFilesystem, io: IOContext
) -> CommandResult:
    """Pass-through: no lzma in virtual shell, just cat the input."""
    files = [a for a in args if not a.startswith("-")]
    for _fname, data in read_binary_inputs(files, state, vfs, io, "lzcat"):
        if data is not None:
            io.stdout.write(data.decode("utf-8", errors="replace"))
    return CommandResult(exit_code=0)


# ---------------------------------------------------------------------------
# unzip
# ---------------------------------------------------------------------------


@command("unzip")
def cmd_unzip(
    args: list[str], state: ShellState, vfs: VirtualFilesystem, io: IOContext
) -> CommandResult:
    list_only = False
    dest_dir: str | None = None
    zippath: str | None = None

    i = 0
    while i < len(args):
        a = args[i]
        if a == "-l":
            list_only = True
        elif a == "-d" and i + 1 < len(args):
            i += 1
            dest_dir = args[i]
        elif not a.startswith("-"):
            zippath = a
        i += 1

    if zippath is None:
        io.stderr.write("unzip: missing zipfile argument\n")
        return CommandResult(exit_code=1)

    abs_zip = vfs.resolve(zippath, state.cwd)
    try:
        data = vfs.read(abs_zip)
    except FileNotFoundError:
        io.stderr.write(f"unzip: cannot find {zippath}\n")
        return CommandResult(exit_code=1)

    buf = _io.BytesIO(data)
    try:
        with zipfile.ZipFile(buf, "r") as zf:
            if list_only:
                hdr = (
                    "  Length      Date    Time    Name\n"
                    "---------  ---------- -----   ----\n"
                )
                io.stdout.write(hdr)
                total = 0
                for info in zf.infolist():
                    dt = info.date_time
                    date_s = f"{dt[0]:04d}-{dt[1]:02d}-{dt[2]:02d}"
                    time_s = f"{dt[3]:02d}:{dt[4]:02d}"
                    io.stdout.write(
                        f"{info.file_size:>9d}  {date_s} {time_s}   {info.filename}\n"
                    )
                    total += info.file_size
                n_files = len(zf.infolist())
                ftr = (
                    "---------                     -------\n"
                    f"{total:>9d}                     "
                    f"{n_files} file(s)\n"
                )
                io.stdout.write(ftr)
            else:
                target = state.cwd
                if dest_dir:
                    target = vfs.resolve(dest_dir, state.cwd)
                    if not vfs.is_dir(target):
                        vfs.mkdir(target, parents=True)

                for info in zf.infolist():
                    if info.is_dir():
                        dir_path = vfs.resolve(info.filename, target)
                        if not vfs.is_dir(dir_path):
                            vfs.mkdir(dir_path, parents=True)
                    else:
                        content = zf.read(info.filename)
                        out_path = vfs.resolve(info.filename, target)
                        vfs.write(out_path, content)
                        io.stdout.write(f"  extracting: {info.filename}\n")
    except zipfile.BadZipFile:
        io.stderr.write(f"unzip: {zippath}: not a valid zip file\n")
        return CommandResult(exit_code=1)

    return CommandResult(exit_code=0)


# ---------------------------------------------------------------------------
# cpio
# ---------------------------------------------------------------------------


@command("cpio")
def cmd_cpio(
    args: list[str], state: ShellState, vfs: VirtualFilesystem, io: IOContext
) -> CommandResult:
    copy_out = False  # -o
    copy_in = False  # -i
    create_dirs = False  # -d

    for a in args:
        if a == "-o":
            copy_out = True
        elif a == "-i":
            copy_in = True
        elif a == "-d":
            create_dirs = True
        elif a in ("-id", "-di"):
            copy_in = True
            create_dirs = True

    if copy_out:
        return _cpio_out(state, vfs, io)
    elif copy_in:
        return _cpio_in(state, vfs, io, create_dirs)
    else:
        io.stderr.write("cpio: missing operation flag (-o or -i)\n")
        return CommandResult(exit_code=1)


def _cpio_out(
    state: ShellState, vfs: VirtualFilesystem, io: IOContext
) -> CommandResult:
    """Copy-out: read filenames from stdin, create tar archive to stdout."""
    text = io.stdin.read()
    filenames = [f for f in text.splitlines() if f.strip()]

    buf = _io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w") as tf:
        for fname in filenames:
            abs_path = vfs.resolve(fname.strip(), state.cwd)
            if not vfs.is_file(abs_path):
                io.stderr.write(f"cpio: {fname}: No such file or directory\n")
                continue
            data = vfs.read(abs_path)
            info = tarfile.TarInfo(name=fname.strip())
            info.size = len(data)
            tf.addfile(info, _io.BytesIO(data))

    io.stdout.write(buf.getvalue().decode("latin-1"))
    return CommandResult(exit_code=0)


def _cpio_in(
    state: ShellState,
    vfs: VirtualFilesystem,
    io: IOContext,
    create_dirs: bool,
) -> CommandResult:
    """Copy-in: read tar archive from stdin, extract files."""
    raw = io.stdin.read().encode("latin-1")
    buf = _io.BytesIO(raw)

    try:
        with tarfile.open(fileobj=buf, mode="r:*") as tf:
            for member in tf.getmembers():
                if member.isfile():
                    f = tf.extractfile(member)
                    if f is not None:
                        content = f.read()
                        out_path = vfs.resolve(member.name, state.cwd)
                        # Ensure parent directory exists if -d
                        if create_dirs:
                            parent = posixpath.dirname(out_path)
                            if parent and parent != "/" and not vfs.is_dir(parent):
                                vfs.mkdir(parent, parents=True)
                        vfs.write(out_path, content)
    except tarfile.TarError as e:
        io.stderr.write(f"cpio: error reading archive: {e}\n")
        return CommandResult(exit_code=1)

    return CommandResult(exit_code=0)


# ---------------------------------------------------------------------------
# ar
# ---------------------------------------------------------------------------

_AR_MAGIC = b"!<arch>\n"
_AR_HEADER_FMT = "16s12s6s6s8s10s2s"  # name, mtime, uid, gid, mode, size, fmag
_AR_HEADER_SIZE = 60


@command("ar")
def cmd_ar(
    args: list[str], state: ShellState, vfs: VirtualFilesystem, io: IOContext
) -> CommandResult:
    if not args:
        io.stderr.write("ar: missing operation\n")
        return CommandResult(exit_code=1)

    op = args[0]
    if len(args) < 2:
        io.stderr.write("ar: missing archive name\n")
        return CommandResult(exit_code=1)

    archive_name = args[1]
    member_files = args[2:]

    if "r" in op:
        return _ar_replace(archive_name, member_files, state, vfs, io)
    elif "t" in op:
        return _ar_list(archive_name, state, vfs, io)
    elif "x" in op:
        return _ar_extract(archive_name, member_files, state, vfs, io)
    else:
        io.stderr.write(f"ar: unknown operation '{op}'\n")
        return CommandResult(exit_code=1)


def _ar_replace(
    archive_name: str,
    member_files: list[str],
    state: ShellState,
    vfs: VirtualFilesystem,
    io: IOContext,
) -> CommandResult:
    """Create or update an ar archive with the given files."""
    archive_path = vfs.resolve(archive_name, state.cwd)

    # Read existing members if archive exists
    members: dict[str, bytes] = {}
    if vfs.exists(archive_path):
        members = _ar_read_members(vfs.read(archive_path))

    for f in member_files:
        abs_path = vfs.resolve(f, state.cwd)
        try:
            data = vfs.read(abs_path)
        except FileNotFoundError:
            io.stderr.write(f"ar: {f}: No such file or directory\n")
            return CommandResult(exit_code=1)
        basename = posixpath.basename(f)
        members[basename] = data

    # Write archive
    buf = _io.BytesIO()
    buf.write(_AR_MAGIC)
    for name, data in members.items():
        _ar_write_member(buf, name, data)

    vfs.write(archive_path, buf.getvalue())
    return CommandResult(exit_code=0)


def _ar_list(
    archive_name: str,
    state: ShellState,
    vfs: VirtualFilesystem,
    io: IOContext,
) -> CommandResult:
    """List members of an ar archive."""
    archive_path = vfs.resolve(archive_name, state.cwd)
    try:
        data = vfs.read(archive_path)
    except FileNotFoundError:
        io.stderr.write(f"ar: {archive_name}: No such file or directory\n")
        return CommandResult(exit_code=1)

    members = _ar_read_members(data)
    for name in members:
        io.stdout.write(name + "\n")
    return CommandResult(exit_code=0)


def _ar_extract(
    archive_name: str,
    member_files: list[str],
    state: ShellState,
    vfs: VirtualFilesystem,
    io: IOContext,
) -> CommandResult:
    """Extract members from an ar archive."""
    archive_path = vfs.resolve(archive_name, state.cwd)
    try:
        data = vfs.read(archive_path)
    except FileNotFoundError:
        io.stderr.write(f"ar: {archive_name}: No such file or directory\n")
        return CommandResult(exit_code=1)

    members = _ar_read_members(data)
    to_extract = member_files if member_files else list(members.keys())

    for name in to_extract:
        if name not in members:
            io.stderr.write(f"ar: {name}: not found in archive\n")
            continue
        out_path = vfs.resolve(name, state.cwd)
        vfs.write(out_path, members[name])

    return CommandResult(exit_code=0)


def _ar_write_member(buf: _io.BytesIO, name: str, data: bytes) -> None:
    """Write a single member to an ar archive buffer."""
    # Pad name to 16 chars with trailing /
    ar_name = (name + "/").ljust(16).encode("ascii")[:16]
    size_str = str(len(data)).ljust(10).encode("ascii")[:10]
    header = (
        ar_name
        + b"0           "  # mtime (12 bytes)
        + b"0     "  # uid (6 bytes)
        + b"0     "  # gid (6 bytes)
        + b"100644  "  # mode (8 bytes)
        + size_str  # size (10 bytes)
        + b"`\n"  # fmag (2 bytes)
    )
    buf.write(header)
    buf.write(data)
    # Pad to even byte boundary
    if len(data) % 2 != 0:
        buf.write(b"\n")


def _ar_read_members(data: bytes) -> dict[str, bytes]:
    """Parse an ar archive and return {name: content} dict."""
    members: dict[str, bytes] = {}
    if not data.startswith(_AR_MAGIC):
        return members

    offset = len(_AR_MAGIC)
    while offset + _AR_HEADER_SIZE <= len(data):
        header = data[offset : offset + _AR_HEADER_SIZE]
        name_raw = header[:16].decode("ascii", errors="replace").strip()
        # Remove trailing /
        if name_raw.endswith("/"):
            name_raw = name_raw[:-1]
        size_raw = header[48:58].decode("ascii", errors="replace").strip()
        try:
            size = int(size_raw)
        except ValueError:
            break

        offset += _AR_HEADER_SIZE
        member_data = data[offset : offset + size]
        members[name_raw] = member_data
        offset += size
        # Skip padding byte
        if size % 2 != 0:
            offset += 1

    return members
