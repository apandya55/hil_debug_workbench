# Security Policy

## Supported Versions

| Version | Supported          |
| ------- | ------------------ |
| 0.1.x   | :white_check_mark: |

## Reporting a Vulnerability

If you discover a security vulnerability in HIL Debug Workbench, please report it privately:

1. Do not open a public issue.
2. Email arnav.pdy2024@gmail.com with vulnerability details and reproduction steps.
3. Allow up to 48 hours for an initial response before public disclosure.

## Security Considerations

### API Keys

- **Never commit API keys** to version control
- Use environment variables: `export ANTHROPIC_API_KEY=sk-ant-...`
- If using `.env` files, add them to `.gitignore`

### Serial Port Access

- On Linux, HIL Debug Workbench requires membership in the `dialout` group
- This is intentional to prevent unauthorized hardware access
- Never run with `sudo` — add your user to the group instead:
  ```bash
  sudo usermod -a -G dialout $USER
  ```

### Code Execution

- HIL Debug Workbench executes PlatformIO commands via subprocess
- It applies AI-suggested code fixes to your firmware source files
- **Review suggested fixes** before running in production environments
- Use version control and commit before running `hil heal`

### Network Exposure

- The web dashboard binds to `127.0.0.1` (localhost only) by default
- **Do not expose the dashboard port to the internet** without authentication
- WebSocket connections are unencrypted (use SSH tunnels for remote access)

### Firmware Security

- HIL Debug Workbench does not implement firmware encryption or signing
- Apply your own security measures (secure boot, flash encryption) via PlatformIO
- Be cautious when flashing firmware to production devices

## Best Practices

1. **Use version control** — Always commit before running `hil heal`
2. **Separate dev/prod boards** — Don't run self-heal on production hardware
3. **Review AI fixes** — Claude's suggestions should be reviewed, not blindly applied
4. **Limit API access** — Use API keys with appropriate rate limits
5. **Isolate test environments** — Run HIL Debug Workbench on dedicated dev machines

## Dependencies

We use automated security scanning:

- **Bandit** — Python security linter
- **Safety** — Dependency vulnerability scanner
- **GitHub Dependabot** — Automated dependency updates

Run security checks locally:

```bash
pip install bandit safety
bandit -r hil_cli dashboard tui
safety check
```

## Disclosure Policy

- We will acknowledge receipt within 48 hours
- We will provide a fix timeline within 7 days
- We will credit researchers in release notes (unless anonymity is requested)
- We follow a 90-day disclosure policy for critical vulnerabilities

---

**Last updated:** 2026-01-XX
