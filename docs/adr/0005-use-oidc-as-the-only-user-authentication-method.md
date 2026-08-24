# ADR 0005: Use OIDC as the only user authentication method

## Status

Accepted

## Context

Maintaining local passwords duplicates controls already provided by the operator's identity provider. Echora still needs its own authorization state for administrators, blocked users, provisioning policy, library visibility, and preferences.

## Decision

Echora authenticates users only through an environment-configured OpenID Connect provider using discovery and the authorization-code flow. Provider credentials, redirect URLs, scopes, the bootstrap administrator email, and email-verification policy remain container environment settings. The application never exposes or edits them.

The normalized OIDC email claim is the immutable Echora username. Display name remains editable. Echora links the account to the provider subject claim and rejects a conflicting subject.

`OIDC_REQUIRE_VERIFIED_EMAIL` defaults to false. When false, Echora accepts an explicit `email_verified=false` claim. Operators who require provider-verified email set it to true.

Before an administrator exists, only `OIDC_BOOTSTRAP_ADMIN_EMAIL` may provision. That first account becomes administrator. Afterward, new identities provision automatically by default. Administrators may disable automatic provisioning and approve individual email addresses. Approval creates no user until the matching OIDC login.

Administrators may promote, demote, block, and unblock users. Blocking immediately revokes all Echora sessions. Echora prevents self-demotion, self-blocking, and removal of the last active administrator.

## Consequences

Echora stores no usable local passwords and offers no password login or password reset. Identity recovery and email changes belong to the OIDC provider. Changing a user's provider email creates an identity mismatch unless an administrator handles the migration explicitly.

A bad or missing bootstrap administrator email prevents initial provisioning. This is intentional because allowing the first arbitrary visitor to become administrator is unsafe.
