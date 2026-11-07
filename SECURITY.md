# Security Policy

## Supported Versions

| Version | Supported          |
|---------|--------------------|
| 0.1.x   | Yes                |

## Security Model

agentsh is designed to be safe by default:

- **No subprocess calls** — the shell never spawns real processes
- **No real filesystem access** — all I/O goes through the in-memory VFS
- **No network access** — no HTTP, no sockets, no DNS
- **Policy engine** — commands and paths can be allow-listed or denied

However, agentsh does **not** provide VM-level isolation. It runs in the same Python process as the caller. It is a virtual environment, not a sandbox.

## Reporting a Vulnerability

If you discover a security vulnerability, please report it responsibly:

1. **Do not** open a public GitHub issue
2. Email **opensource@mayflower.de** with:
   - Description of the vulnerability
   - Steps to reproduce
   - Potential impact
3. We will acknowledge receipt within 48 hours
4. We will provide a fix timeline within 7 days

## Scope

Security issues we care about:

- Escaping the virtual filesystem to access real files
- Executing real system commands via any code path
- Bypassing the policy engine
- Denial of service via resource exhaustion (unbounded loops, memory)

Out of scope:

- Issues that require the attacker to control the Python host process
- Performance issues that don't lead to resource exhaustion
