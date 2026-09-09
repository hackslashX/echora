# Echora desktop and mobile UI audit

## Scope and limits

Reviewed the running application at localhost:3000 with the frontend-design and Echora UI skills. Inspected Home, Browse, Curate, Settings, Sync, Galaxy, and fullscreen playback with real library data. Desktop screenshots use 1440 × 900, with an additional Browse and player check at 1280 × 800. Mobile screenshots use 390 × 844 and landscape checks use 844 × 390.

This was a review, not an implementation. No settings were saved, curations created, processing jobs started, migrations applied, or containers restarted. A track was briefly played and paused to inspect playback. Review screenshots were removed to keep account and library information out of the repository.

The running application is an older build than the working tree. The new waveform implementation has not been deployed and was not visually verified here. Setup and artist-profile observations below are code-only. I did not reset onboarding to access setup. Phone checks use browser viewport sizes, not physical devices, so safe areas and software-keyboard behavior still need device testing.

## Overall judgment

The dark palette and grid give Echora a consistent identity. The main problem is allocation of space, not a lack of visual polish. Desktop views reserve large areas for background while forms and lists scroll inside narrow panels. Mobile removes those margins, but landscape puts secondary panels back beside primary work at equal width.

Do not solve this by shrinking text. Give the main task more room and remove duplicate headings or controls before reducing spacing inside readable rows.

## Priority 1, fix functional and navigation problems

### Mobile account access is off-screen

Confirmed in Browse at 390px wide. The profile button starts at x=397 and is 38px wide, entirely outside the viewport. The header clips overflow. Landscape explicitly hides the profile control.

Source: `apps/web/components/shell/AppHeader.module.css`, `.profile` inside the compact and landscape rules.

Proposal: position the account button within the header's right padding and keep it available in landscape. Preserve a 44px touch target. Test opening, Escape dismissal, focus return, and logout access without actually logging out during visual tests.

### Fullscreen playback does not dismiss with Escape

Confirmed by opening the mobile player and pressing Escape. The dialog remained open. The source also lacks focus trapping, initial focus, and restoration. Desktop previous, play, next, and mute icon buttons have no accessible labels, unlike the mobile equivalents.

Source: `apps/web/components/player/FullscreenPlayer.tsx`.

Proposal: shared dialog behavior with Escape, initial focus on the close control, contained keyboard focus, inert background content, and focus restoration. Give desktop controls the same accessible names as mobile. Audit the curation deletion dialog against the same requirements.

### Galaxy obscures its own primary interaction on mobile

The concept lens opens by default and occupies 260px of a 390px-wide viewport. It covers most of the usable map below the toolbar. Users arrive in a control panel rather than an exploration view.

Source: `apps/web/components/map/MusicGalaxy.tsx` and `.module.css`.

Proposal: start with the lens collapsed on phones. Open it as a dismissible sheet, with a compact selection summary in the toolbar. Keep search available when the sheet is closed. Do not hide the map behind multiple simultaneous overlays.

## Priority 2, reclaim space for the main task

### Desktop outer geometry is expensive on ordinary laptops

The standard content rectangle reserves 180px on either side and 152px above and below. At 1440 × 900, this leaves 1080 × 596, about 50% of the viewport, before panel gaps, headings, search, and padding. At 1280 × 800 it leaves 920 × 496, about 45%. The screenshots show roughly seven track rows at the larger size and five at the smaller size.

Sources: `apps/web/components/shell/gridGeometry.ts`, `BrowseLibrary.tsx`, `AppShell.module.css`.

Proposal within the existing contract: reduce repeated headings and internal top padding, make filters collapsible, and allocate a larger share of the inner grid to tracks. Keep text and row targets readable.

Larger improvement, requiring approval: introduce a compact desktop shell with smaller outer tracks at laptop sizes. The current Echora UI skill explicitly mandates 180px outer columns and 152px outer rows, so this is a design-system change, not a one-page CSS patch. Update that contract first if approved.

### Landscape gives half the page to secondary content

At 844 × 390, Settings reserves 422px for navigation. Browse gives half the width to filters and shows only about three track rows. Sync gives half the screen to its tutorial while the processing controls wrap tightly on the right.

Sources: landscape rules in `SettingsView.module.css`, `BrowseLibrary.module.css`, and `SyncLibrary.module.css`.

Proposal: use a narrow settings rail or compact section selector. Keep Browse filters in a toggleable panel. Keep Sync's explanation behind “How it works” in landscape too. Orientation alone is not a reason to force equal-width columns.

### Curate prioritizes general settings over defining the playlist

Desktop starts with a long, narrow form beside a large empty saved-curations panel. In the mobile initial view, the name, listening mix, refresh settings, and aspect tabs consume the screen before the meaningful sound/theme inputs. Preview and Save + Sync start around y=1006 in an 844px-high viewport.

Sources: `CurateLibrary.tsx`, `.commonSettings`, `.recipe`, `.actions` in `CurateLibrary.module.css`.

Proposal: put the playlist-defining inputs first. Group refresh style, scheduling, and listening-history tuning under optional settings. Keep Preview and Save in a fixed action row outside the form's scroll area. When there are no saved curations, offer the editor more of the inner grid rather than allocating the larger panel to an empty message.

### Mobile Browse repeats context before showing music

The page spends 264px before the first track: brand/breadcrumb header, tracks/filter tabs, another Tracks heading and count, search, then a full-width sort row. The count appears twice.

Proposal: one title/count row, a wide search field, and compact filter/sort actions. Put hum search behind a clearly labelled compact control without making the search input too narrow. Aim to recover 60–90px through consolidation, not smaller track rows.

### Settings navigation is difficult to discover on phones

The 72px-high horizontal tab strip shows only the first few sections and hides its scrollbar. Models, Appearance, Timezone, and Account require sideways scrolling without a clear overflow cue.

Source: `.tabs nav` in `SettingsView.module.css`, visually checked at 390 × 844.

Proposal: show an overflow affordance or use an explicit section selector. Reduce the strip height while keeping 44px touch targets. Keep the current section visible after selection.

## Priority 3, improve consistency and discoverability

### Home is a sparse launcher rather than a useful starting page

Desktop fills five of fifteen inner grid cells. This composition is deliberate but sends users through a large menu between routine tasks. Mobile stretches five links across nearly the whole available screen, including a full-width Settings tile.

Proposal: retain the staggered composition only if it is an intentional brand priority. For a utility-first direction, use adjacent weighted-grid tiles and direct navigation between core sections. Do not invent recent-listening records to fill the gaps. Only add a resume or recent-curation section if real data supports it.

### The mini-player needs a clearer path to the full player

Only the artwork opens fullscreen. The track title is not an opening control. Mobile removes next/previous controls but keeps mute, so skipping a queued track requires opening the player through the small artwork. The current compact seek target is only around 10–12px high.

Sources: `MusicWidget.tsx`, `MusicWidget.module.css`. The new `WaveformSeek.module.css` also retains a 12px mobile compact target, so the pending waveform change does not solve this.

Proposal: make the identity area open the full player, preserve play/pause as a separate action, and consider next-track over mute for the compact queue experience. Enlarge the seek hit area without overlapping adjacent controls. Review the new waveform at actual rendered sizes before deployment.

### Fullscreen mobile whitespace is less urgent than Browse or Curate

The player intentionally separates lyrics, artwork, and transport. That breathing room is reasonable for listening, unlike wasted space in a form. The portrait screenshot does show considerable separation between the lyric line and artwork.

Proposal: keep the calm layout, but test short screens, long lyrics, missing artwork, and absent lyrics. Cap artwork by available height rather than only width. Prioritize readable lyrics and reachable controls over filling every blank area.

### Sync describes the workflow more clearly on desktop than mobile

The compact breakpoint hides the explanation under each processing mode. “Entire Library” versus “New Tracks Only” therefore loses the important distinction between filling missing analysis and processing new tracks. The zero-new-tracks empty state can also look inconsistent beside an enabled full-library processing button.

Source: `.mode small` in `SyncLibrary.module.css`.

Proposal: show a short explanation for the selected mode, such as “Fill missing analysis for existing and new tracks.” Keep processing availability distinct from the new-track count. Do not imply that zero new tracks means all analysis is complete.

## Code-only risks to verify later

- Artist profiles use two full-width horizontal snap panels on mobile without a visible tab control in the reviewed CSS. Similar artists may be undiscoverable. Check with a real artist route and provide explicit Profile / Similar navigation.
- Mobile curation cards reserve three 42px action columns plus an 82px status badge. Little width remains for the name. The account has no saved curations, so this state was not visually tested. Move secondary actions into a menu and the status below the name.
- Setup still uses global wizard styling with large fixed paddings and a fixed-height document. Test connection, selection, errors, and the software keyboard with an onboarding account. Do not reset an existing account just for screenshots.
- The shared compact breakpoint is width below 1200px OR height below 720px. A wide but short desktop window therefore receives the same layout family as a phone. Test around 1199/1200px and 719/720px before changing it.
- Several CSS modules contain successive overrides of the same mobile layout, especially fullscreen playback. Consolidate superseded rules during implementation rather than adding another layer of overrides.

## Proposed implementation order

1. Account access, dialog keyboard behavior, accessible control labels.
2. Landscape panel allocation and the default mobile Galaxy lens state.
3. Curate action placement and input order, then Browse header/search consolidation.
4. Settings section navigation and mini-player touch targets.
5. Decide whether to revise the fixed desktop shell geometry and Home composition.

Keep the current dark base, aqua or artwork-derived accent, and shared typography tokens. No palette redesign is needed. Acceptance should include real-data screenshots, keyboard checks, no clipped controls, long names, empty states, and portrait/landscape phone tests. Physical-device keyboard and safe-area checks remain necessary.
