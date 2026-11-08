# Security Policy

## Supported Versions

| Version | Supported          |
|---------|--------------------|
| 0.1.x   | Yes                |

## Security Model

What a `Sandbox` lets an agent reach, what stops it, and what is out of
scope is described, with a demonstration of each boundary, in the book's
chapter [The security model](https://syalia-srl.github.io/spelaion/the-security-model.html).

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
