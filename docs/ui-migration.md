# Interface migration

The approved visual reference lives in `design-lab/`. The application uses the same header and side-panel implementations in `apps/web/components/layout/`.

## Shared components

- `SidePanel` owns the secondary rail background, heading, actions, padding, and content spacing. Library filters and Settings navigation use the same component.
- `PageHeader` owns route headings and header actions. Pages must not override its typography or spacing.
- `Workspace` owns full-height content and the standard secondary rail.
- `WorkspaceBody` owns content padding and scrolling.
- `PageToolbar`, `SectionHeader`, and `EmptyState` cover repeated content patterns.
- `components/ui/` contains the source-owned shadcn/Radix controls adapted from the supplied dashboard kit. Tailwind v4 supplies their styles.

Use existing shared components before adding page-specific presentation. Specialized canvas and lyric layouts may own their geometry, but their controls use the same kit and theme.

## Appearance

- Primary navigation: black, `#000`.
- Secondary rail: `#060606`.
- Workspace: `#0b0b0b`.
- Controls: neutral dark gray, with borders around `#242424`.
- Primary actions: flat pale blue, `#a8cefa`.
- Sharp edges. No glass, backdrop blur, or navy panel backgrounds.
- No desktop top bar. Account actions live in the navigation footer.
- Desktop sidebar: 232px, reducing to 208px below 1100px. Below 768px it moves into a sheet opened from a 56px top bar.
- Player: 80px desktop, 72px mobile. Playback state remains in the root `PlayerProvider`.
- Page gutter (`--gutter`): 32px, 24px below 1100px, 16px below 768px.
- Typography scale (never set sizes ad hoc):
  - Page title (`PageHeader`): 28px, for single-column pages only.
  - Pane title (`Pane`, `SidePanel`): 18px semibold, subtitle 12px muted.
  - Section title (`PaneSection`, `SectionHeader`): 14px semibold, hint 12px muted. Sections are separated by a divider and 24px spacing.
  - Field labels, body and control text: 13px.
  - Counts, metadata, hints and section actions: 12px.
- Banners: use `Notice` (`components/ui/notice.tsx`) only for lasting caveats the reader must not miss on that screen (what will not apply, what is replaced, what may cost money) and for a panel whose data failed to load, with a Try again action. Plain field help stays a 12px hint.
- Toasts: results of an action (saved, deleted, queued, failed, connection lost) go through Sonner: `toast.success/info/warning/error(title, { description })` from `sonner`. The single `<Toaster />` (`components/ui/sonner.tsx`) is mounted in `app/layout.tsx` above the player bar. Keep the title short and put detail in `description`; pass an `id` when a control can fire repeatedly (sliders) or a condition persists (polling outages) so one toast updates instead of stacking.
- Loading: use `Spinner`/`LoadingState` (`components/ui/spinner.tsx`) for regions and `Button loading` for actions. Every fetch the user waits on shows one.
- Multi-column pages (Library, Curations) are built from `Pane` columns, and their content from `PaneSections`/`PaneSection`.
- Tabs: `segmented` (default) for 2–4 peer views, `line` for section navigation inside a panel. Settings uses a plain grouped nav, not vertical tabs.
- Scrollbars are styled once in `globals.css` (square 4px thumb, accent while dragging). Do not add per-component scrollbar styles.
- Only `WorkspaceBody` scrolls. Do not make it a flex container: `overflow` children (such as the table wrapper) would shrink and become nested scrollers.
- The fullscreen player is transparent so the audio-reactive backdrop shows through, with a light scrim for legibility.

Album artwork and audio-reactive visualizations retain their own colors. They do not change application branding tokens.

## Verification

```sh
npm run typecheck
npm run lint
npm run build
node --test apps/web/components/{browse,jobs,player,runtime,session}/*.test.mjs
```

Unauthenticated local browser reviews can use browser-only response fixtures for visual checks. These must not enter application code or be treated as proof of authenticated API or streaming behavior.

The old Metro UI skill is obsolete. It has not been rewritten as part of this migration.

## URLs

- A view someone may want to link, reload or go Back to lives in the URL, and the URL is its source of truth. Use `useSubPath(section)` and `setUrl(url, mode)` from `components/shell/urlState.ts`; Next keeps `usePathname`/`useSearchParams` in sync with the History API.
- Destinations are path segments and push history: `/settings/<section>`, `/curate/<curation id>`. They are served by `app/[section]/[[...rest]]`, which accepts one extra segment only for `settings` and `curate`.
- Refinements are query parameters and replace history: library search, filters and sort (`components/browse/libraryUrl.ts`), `/galaxy?track=<id>`, `/home?period=week|month|year|all`. Leave defaults out so plain views keep clean URLs.
- Link to the specific thing: a curation link is `/curate/<id>`, not `/curate`.
