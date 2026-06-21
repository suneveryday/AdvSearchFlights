# Security Policy

## Secrets

Do not commit `.env`, API keys, access tokens, client secrets, cookies, or real user data.

Use `.env.example` as the public template and provide real credentials through environment variables.

Local search history, application settings, diagnostic logs, build artifacts, and HTTP archive files must not be committed. The repository `.gitignore` excludes common forms of these files.

Before publishing, scan tracked files for secrets and personal paths:

```bash
git grep -n -I -E '(phc_[A-Za-z0-9]{20,}|sk-[A-Za-z0-9_-]{16,}|AIza[0-9A-Za-z_-]{20,}|AKIA[0-9A-Z]{16}|/Users/[^/]+|PRIVATE KEY)'
```

Expected matches must be limited to placeholders, test-only dummy values, or this documented scan pattern. Review every match manually.

## Reporting a vulnerability

Open a private report or contact the maintainer directly before publishing exploit details.

Please include:

- affected version or commit
- reproduction steps
- expected impact
- suggested fix, if available
