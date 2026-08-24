# Security

Do not report vulnerabilities through a public issue. Contact the repository owner privately with the affected version, reproduction steps, and expected impact.

## Deployment requirements

- Replace every value in `configs/env.example` before starting Echora.
- Keep OIDC credentials, database credentials, `OIDC_SESSION_SECRET`, and `CREDENTIAL_ENCRYPTION_KEY` outside Git.
- Set `COOKIE_SECURE=true` behind HTTPS.
- Restrict the production database and analysis service to the cluster network.
- Back up `CREDENTIAL_ENCRYPTION_KEY`. Losing it makes stored Navidrome and Last.fm credentials unreadable.
- Review model licenses before non-personal use.

Blocking a user revokes their active Echora sessions. Revoking access at the identity provider alone does not delete an already-issued Echora session, so block the Echora account when immediate local revocation is required.
