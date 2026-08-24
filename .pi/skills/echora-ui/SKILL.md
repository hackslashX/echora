---
name: echora-ui
description: Enforces Echora's application shell, weighted grid geometry, typography, footer, transitions, and component conventions. Use for every Echora frontend page, component, layout, visual fix, or interaction.
---

# Echora UI

Use this skill before changing any frontend UI in Echora.

## Start by reading the existing system

Read these files before implementation:

- `apps/web/components/shell/AppShell.tsx`
- `apps/web/components/shell/gridGeometry.ts`
- `apps/web/components/browse/BrowseLibrary.tsx`
- `apps/web/components/browse/BrowseLibrary.module.css`
- The closest existing page and its CSS module

Do not invent a separate layout system.

## Shell and geometry

- Use `AppShell` on every authenticated page.
- Preserve the header, footer, persistent player, backdrop, route guards, and route transitions.
- Standard application pages use `flush fullPage` and a weighted `grid` definition.
- Use `trackTemplate(weights, fixedSize)` for content geometry.
- The outer columns are always 180px. The outer rows are always 152px.
- Put primary panels in the inner tracks. The canvas may span the viewport only for explicitly immersive views such as Galaxy. Its controls must still align to the 180px boundaries.
- Add a deliberate spacer column when the design needs separation. Do not replace grid geometry with arbitrary centered max-width containers.
- Keep header and footer visible. Panels own scrolling. The document never scrolls.
- Do not show `PageGrid` lines on an immersive view unless they help the interface.

## Visual language

- Permanent dark mode.
- Use the existing aqua accent and line variables.
- Panels use near-black translucent backgrounds, one-pixel grid-aligned borders, and square corners.
- Hover and focus states may glow but must not scale or shift geometry.
- Use `Space Grotesk` for titles, `DM Mono` for labels and metadata, and `Instrument Serif` for expressive accents.
- Labels and metadata must remain readable. Use shared typography tokens and avoid text below 12px.
- Keep controls between the fixed left and right boundaries.

## Components and behavior

- Put each reusable component in its own file with a separate CSS module.
- Use real API data. Never add mock tracks, fake counts, or decorative placeholder records.
- Preserve persistent playback by using `PlayerProvider`.
- Use `CopyrightFooter` unless the page has a specific footer requirement.
- Use `TransitionLink` for shell navigation.
- Internal lists scroll. Header, actions, pagination, and footer stay fixed.

## Before finishing

Check the page against Browse and Home for geometry, not just color.

Run:

```bash
npm run typecheck
npm run lint
npm run build
```

For frontend-only deployment, run:

```bash
npm run rebuild:web
```

Do not rebuild analysis for frontend-only changes.
