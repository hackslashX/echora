# Echora design lab

Isolated UI preview. No imports from `apps/web`, no API requests, and no account or library mutations. Controls come from the local shadcn dashboard kit. The preview uses the repository's installed Next, React, Radix and Tailwind dependencies.

Run from this directory:

```sh
../node_modules/.bin/next dev --hostname 127.0.0.1 --port 3100
```

Library and Settings demonstrate the proposed layout. Filters and form values are local preview state. No music records are fabricated. Navigation for pages outside this review displays a preview explanation.

Design constraints:

- Black navigation and near-black content, with no navy background.
- Square geometry and straight dividers.
- Flat blue primary actions. Neutral selected navigation states, with no glass, gradients, or blur.
- No desktop top bar. Account menu at the sidebar bottom.
- Full-height content, darker filter/section rail, persistent player area.

Review the desktop and mobile preview before migrating any layouts to the application.
