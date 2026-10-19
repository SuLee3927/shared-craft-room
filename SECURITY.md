# Security

- Treat every room URL and MCP URL as a password-bearing link.
- Set a long random `CRAFT_ADMIN_KEY` and never commit it.
- Deploy behind HTTPS and keep access logs disabled or redact URL paths.
- Persist and back up `CRAFT_DATA_DIR` privately; it contains participant identities and artwork.
- Rotate a participant key if its URL is exposed.

Please report vulnerabilities privately to the repository owner rather than opening a public issue with secrets or private artwork.
