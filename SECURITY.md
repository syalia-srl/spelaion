# Security Policy

## Supported Versions

| Version | Supported          |
|---------|--------------------|
| 0.1.x   | Yes                |

## Security Model

A `Sandbox` gives an agent the folders it mounts, the standard library and
PyYAML for python, and the host commands the product registers, and nothing
else:

- **Files:** every path, from the shell, `edit`, `write`, python and
  `ctx.path()`, resolves through one mount table. Paths outside every mount do
  not exist; a symlink that leaves its mount is refused; read-only mounts
  refuse writes.
- **Processes and network:** the shell is pure Python and never starts a
  program. python is CPython for WASI under wasmtime, which has no sockets or
  processes to grant.
- **The child process:** each sandbox runs its shell and python in a child
  Python process. A call past its deadline kills it, an rlimit caps its
  memory, and caps bound each call's output and the writable mounts' size,
  so a runaway command does not take the product down.
- **Out of scope:** an escape through a bug in wasmtime or in CPython's WASI
  build, and anything a host command does: host commands are the product's
  own trusted code and run with its permissions.

The child is not a kernel sandbox: it runs as the product's user, and the
resolver, the WASI preopens and the absence of any way to start a process
are what keep the agent inside. The in-memory `Bash` class is a test tool
with none of these limits.

## Reporting a Vulnerability

If you discover a security vulnerability, please report it responsibly:

1. **Do not** open a public GitHub issue
2. Open a private report at <https://github.com/syalia-srl/spelaion/security/advisories/new> with:
   - Description of the vulnerability
   - Steps to reproduce
   - Potential impact
3. We will acknowledge receipt within 48 hours
4. We will provide a fix timeline within 7 days

## Scope

Security issues we care about:

- Reading or writing a host file outside the mounts, or writing a read-only
  mount, through any entry point
- Starting a host program or opening a network connection from inside
- A call that outlives its deadline, or exceeds the memory, output or disk
  caps, without being stopped
- A host path appearing in what the agent sees

Out of scope:

- Issues that require the attacker to control the Python host process
- What a host command does with the power the product gives it
- Performance issues that don't lead to resource exhaustion
