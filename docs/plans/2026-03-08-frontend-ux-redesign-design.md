# Frontend UX Redesign Design

## Goals

- Improve readability for older users (larger fonts, higher contrast)
- Modernize the visual style (clean, flat, no medieval parchment texture)
- Better use of screen real estate (nav rail instead of fat sidebar)
- Desktop-first with tablet as a bonus
- Include dark mode

## Typography & Sizing

- **Font family:** Inter for all UI text. Keep Cinzel for app title only. Crimson Pro for long-form reading (extracted text in product detail).
- **Base font size:** 18px (1.125rem)
- **Minimum text size:** 16px (1rem) — nothing smaller anywhere except nav rail labels (14px)
- **Card titles:** 18px, semibold
- **Card metadata:** 16px
- **Headings:** 24-32px
- **Badges:** 14px minimum with generous padding (px-3 py-1)
- **Line height:** 1.5 for body text
- **Minimum click/tap target:** 44x44px (WCAG AAA)
- **Contrast:** All text meets WCAG AA (4.5:1 ratio minimum)

## Color Palette

### Light Mode

| Role           | Color     | Usage                                    |
|----------------|-----------|------------------------------------------|
| Background     | `#FAFAFA` | Main content area                        |
| Surface        | `#FFFFFF` | Cards, modals, drawers                   |
| Border         | `#E2E2E2` | Subtle dividers, card borders            |
| Text primary   | `#1A1A1A` | Headings, titles, body                   |
| Text secondary | `#555555` | Metadata, labels, counts                 |
| Accent         | `#5C6B3C` | Active states, selected filters, primary buttons |
| Accent hover   | `#4A5730` | Darker accent for hover/active           |
| Accent light   | `#EEF1E8` | Accent backgrounds                       |
| Danger         | `#C53030` | Delete, errors                           |
| Success        | `#2F855A` | Completed, extracted status              |

### Dark Mode

| Role           | Color     |
|----------------|-----------|
| Background     | `#141414` |
| Surface        | `#1E1E1E` |
| Surface raised | `#262626` |
| Border         | `#333333` |
| Text primary   | `#E8E8E8` |
| Text secondary | `#999999` |
| Accent         | `#8FA660` |
| Accent hover   | `#7A8F50` |
| Accent light   | `#2A3020` |
| Danger         | `#FC8181` |
| Success        | `#68D391` |

### Visual Style Changes

- Remove parchment texture and SVG noise filters
- Remove custom `shadow-tome` shadows, use standard `shadow-sm`/`shadow-md`
- Border radius: 6px (modern but not bubbly)
- Buttons: solid fills for primary, outlined for secondary, plain text for tertiary

## Layout & Navigation

### Nav Rail (72px wide, fixed left)

- Icon (24px) + label (14px) stacked vertically per item
- Each item: 72x64px click target
- Active item: accent-light background + accent text
- Items: Library, Campaigns, Manage, Queue, Tools, Settings
- Divider between main nav and utility (Settings)
- Dark/light mode toggle at bottom (sun/moon icon)
- App title "Grimoire" at the top, no tagline

### Search Bar (top of main content)

- Full width, 48px tall input, 18px text
- Search icon left, clear button right
- "Search content" toggle as pill/switch next to input
- Right side: filter button (with active count badge), view toggle (grid/list), refresh

### Filter Drawer (right side, 360px)

- Opens on demand from filter button
- Overlays content (does not push it)
- Sections: Collections, Tags, Game Systems, Product Types, Genres, Authors, Publishers, Year Range, Adventure Filters
- Each section collapsible with counts
- Active filters shown as removable chips at top
- "Clear all filters" button at top
- Close button (X) top-right

### Tablet Adaptation (< 1024px)

- Nav rail collapses to bottom tab bar
- Filter drawer becomes full-width overlay
- Grid drops to 2-3 columns

## Product Cards

### Grid

- Columns: 2 (< 768px), 3 (768-1023px), 4 (1024-1439px), 5 (1440px+)
- Gap: 20px
- Card padding: 16px on text section
- Image: 3:4 aspect ratio, 6px border-radius top corners
- Hover: lift with `shadow-md`, no scale transform
- Title: 18px semibold, line-clamp-2
- Publisher: 16px, secondary color
- Badges: pill-shaped, accent-light bg for system, neutral for type
- Queue/action button: always visible (not hover-only)

### List View

- Row height: 84px minimum
- Thumbnail: 64x84px
- All text 16-18px
- Badges inline on right
- 12px vertical padding

## Product Detail Modal

- Width: max-w-4xl (896px), height up to 90vh
- Border-radius: 8px
- Header: cover image (120x160) alongside title, publisher, year, page count, badges, action buttons
- Tab bar: Overview, Content, Details, Files — 18px text, 48px tall tabs
- Content tab: Crimson Pro serif, 18px, 1.6 line height, ~70 char line length
- Content tab: in-modal search bar at top
- Details tab: two-column key-value layout
- Action buttons (Add to Collection, Tag) directly in header

## Secondary Pages

### Settings

- Single column, max-width 640px centered
- 48px tall inputs, 18px text
- Toggle switches instead of checkboxes
- Folder paths in monospace 16px
- Dark/light mode toggle with three-state control (Light/Dark/System)

### Processing Queue

- Table with 56px row height
- Status: colored dot + text label
- Progress bars: 8px tall, accent colored, percentage text
- Clear action button labels

### Library Management

- Card-based sections
- Large headings, descriptive text
- Confirmation dialogs for destructive actions

### Campaigns

- Same typography/spacing upgrades applied

### Shared Patterns

- Page title: 28px, semibold, top-left
- 24px padding from edges
- Max content width: 1200px with auto centering
- Loading states: skeleton placeholders (not spinners)

## Dark Mode Implementation

- Three states: Light / Dark / System
- Stored in localStorage as `theme: "light" | "dark" | "system"`
- CSS custom properties on `:root` (light) and `.dark` class (dark)
- Tailwind `dark:` variant driven by `.dark` class on `<html>`
- `transition-colors duration-200` on `<html>` for smooth switch
- Theme class applied in `<script>` block in index.html before render (no flash)
- Toggle in nav rail + full control in Settings
