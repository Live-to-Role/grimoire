# Frontend UX Redesign Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Modernize the Grimoire frontend with larger fonts, cleaner design, nav rail layout, filter drawer, and dark mode support.

**Architecture:** Replace the 256px sidebar with a 72px nav rail + on-demand filter drawer. Swap medieval Codex theme for a clean, high-contrast design with CSS custom properties enabling dark mode. All colors via CSS variables, Tailwind `dark:` class variant.

**Tech Stack:** React 18, TypeScript, Tailwind CSS 4.x, Inter font (new), Cinzel (keep for title), Crimson Pro (keep for reading), lucide-react icons.

---

### Task 1: Theme Foundation — CSS Custom Properties & Font Setup

**Files:**
- Modify: `frontend/src/index.css` (full rewrite of theme section, lines 1-238)
- Modify: `frontend/index.html` (lines 9-11, swap font imports)

**Step 1: Update index.html font imports**

Replace the Google Fonts links (lines 9-11) with:

```html
<script>
  // Apply theme before render to prevent flash
  (function() {
    const theme = localStorage.getItem('grimoire-theme') || 'system';
    const prefersDark = window.matchMedia('(prefers-color-scheme: dark)').matches;
    if (theme === 'dark' || (theme === 'system' && prefersDark)) {
      document.documentElement.classList.add('dark');
    }
  })();
</script>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=Cinzel:wght@600;700&family=Crimson+Pro:ital,wght@0,400;0,600;1,400&family=Inter:wght@400;500;600;700&display=swap" rel="stylesheet">
```

**Step 2: Rewrite index.css theme section**

Replace the entire `@theme` block (lines 4-39) and base styles (lines 42-78) with new CSS custom properties. Keep the component classes structure but update all color references.

New theme must define:
- `--color-bg`, `--color-surface`, `--color-surface-raised`, `--color-border`
- `--color-text-primary`, `--color-text-secondary`
- `--color-accent`, `--color-accent-hover`, `--color-accent-light`
- `--color-danger`, `--color-success`
- Light values on `:root`, dark values on `.dark`
- `--font-sans: "Inter"`, `--font-serif: "Crimson Pro"`, `--font-display: "Cinzel"`
- Remove all `codex-*` color references
- Remove parchment texture SVG filters
- Remove `shadow-tome` custom shadows
- Base font-size: 18px on html
- Set `border-radius` default to 6px for components
- `transition-colors duration-200` on html element

**Step 3: Update component classes**

Update all `@layer components` classes to use the new CSS variables:
- `.btn` → use `--color-*` variables, 18px text, 48px min-height
- `.btn-primary` → `--color-accent` bg, white text
- `.btn-secondary` → outlined style with `--color-border`
- `.btn-ghost` → transparent, `--color-text-secondary`
- `.input` → `--color-surface` bg, `--color-border` border, 48px height, 18px text
- `.card` → `--color-surface` bg, `--color-border` border, `shadow-sm`, 6px radius
- `.badge` → 14px min text, `px-3 py-1`, 6px radius
- `.select` → same as `.input` updates
- Remove `.sidebar`, `.sidebar-item`, `.sidebar-item-active` (will be replaced by nav rail)
- Remove `.parchment-bg`, `.parchment-main` classes
- Remove `.divider` gradient class (replace with simple border)

**Step 4: Verify the app still loads**

Run: `cd frontend && npm run dev`
Expected: App loads (will look broken due to removed classes — that's fine at this stage)

**Step 5: Commit**

```bash
git add frontend/src/index.css frontend/index.html
git commit -m "feat: replace Codex theme with clean design system and dark mode CSS variables"
```

---

### Task 2: Theme Context & Dark Mode Toggle Hook

**Files:**
- Create: `frontend/src/hooks/useTheme.ts`
- Create: `frontend/src/contexts/ThemeContext.tsx`

**Step 1: Create useTheme hook**

```typescript
import { useState, useEffect, useCallback } from 'react';

type Theme = 'light' | 'dark' | 'system';

function getEffectiveTheme(theme: Theme): 'light' | 'dark' {
  if (theme === 'system') {
    return window.matchMedia('(prefers-color-scheme: dark)').matches ? 'dark' : 'light';
  }
  return theme;
}

function applyTheme(theme: Theme) {
  const effective = getEffectiveTheme(theme);
  document.documentElement.classList.toggle('dark', effective === 'dark');
}

export function useTheme() {
  const [theme, setThemeState] = useState<Theme>(() => {
    return (localStorage.getItem('grimoire-theme') as Theme) || 'system';
  });

  const setTheme = useCallback((newTheme: Theme) => {
    setThemeState(newTheme);
    localStorage.setItem('grimoire-theme', newTheme);
    applyTheme(newTheme);
  }, []);

  const toggleTheme = useCallback(() => {
    const effective = getEffectiveTheme(theme);
    setTheme(effective === 'light' ? 'dark' : 'light');
  }, [theme, setTheme]);

  useEffect(() => {
    applyTheme(theme);
    if (theme === 'system') {
      const mq = window.matchMedia('(prefers-color-scheme: dark)');
      const handler = () => applyTheme('system');
      mq.addEventListener('change', handler);
      return () => mq.removeEventListener('change', handler);
    }
  }, [theme]);

  return { theme, setTheme, toggleTheme, effectiveTheme: getEffectiveTheme(theme) };
}
```

**Step 2: Create ThemeContext**

```typescript
import { createContext, useContext, type ReactNode } from 'react';
import { useTheme } from '../hooks/useTheme';

type ThemeContextType = ReturnType<typeof useTheme>;

const ThemeContext = createContext<ThemeContextType | null>(null);

export function ThemeProvider({ children }: { children: ReactNode }) {
  const theme = useTheme();
  return <ThemeContext.Provider value={theme}>{children}</ThemeContext.Provider>;
}

export function useThemeContext() {
  const ctx = useContext(ThemeContext);
  if (!ctx) throw new Error('useThemeContext must be used within ThemeProvider');
  return ctx;
}
```

**Step 3: Commit**

```bash
git add frontend/src/hooks/useTheme.ts frontend/src/contexts/ThemeContext.tsx
git commit -m "feat: add theme context and useTheme hook with light/dark/system support"
```

---

### Task 3: Nav Rail Component

**Files:**
- Create: `frontend/src/components/NavRail.tsx`

**Step 1: Build the NavRail component**

Props interface:
```typescript
interface NavRailProps {
  activeView: string;
  onViewChange: (view: string) => void;
  queueCount?: number;  // badge on queue icon
}
```

Structure:
- 72px wide, full height, fixed left
- `--color-surface` background, right border
- Top: "Grimoire" text in Cinzel, 14px
- Navigation items stacked vertically, each 72x64px:
  - Library (Library icon)
  - Campaigns (BookOpen icon)
  - Manage (FolderOpen icon)
  - Queue (HardDrive icon) — with optional count badge
  - Tools (Wrench icon)
- Divider line
- Settings (Settings icon)
- Bottom: dark/light toggle button (Sun/Moon icon) using `useThemeContext`
- Each item: icon (24px) + label (14px) centered vertically
- Active state: `--color-accent-light` bg, `--color-accent` text
- Hover state: slight bg change

**Step 2: Commit**

```bash
git add frontend/src/components/NavRail.tsx
git commit -m "feat: add NavRail component with theme toggle"
```

---

### Task 4: Filter Drawer Component

**Files:**
- Create: `frontend/src/components/FilterDrawer.tsx`

**Step 1: Build FilterDrawer component**

This extracts filter functionality from `frontend/src/components/Sidebar.tsx` (lines 297-678) into a slide-out drawer.

Props interface:
```typescript
interface FilterDrawerProps {
  isOpen: boolean;
  onClose: () => void;
  filters: ProductFilters;
  onFilterChange: (filters: ProductFilters) => void;
  // Collection/tag selection
  selectedCollection: number | null;
  onSelectCollection: (id: number | null) => void;
  selectedTag: number | null;
  onSelectTag: (id: number | null) => void;
  // For managing collections/tags
  onCreateCollection: () => void;
  onCreateTag: () => void;
}
```

Structure:
- Fixed position, right side, 360px wide, full height
- `--color-surface` background with left border and `shadow-md`
- Slide-in animation from right (translate-x transition)
- Backdrop overlay (click to close)
- Header: "Filters" title + active filter count + "Clear all" button + close (X) button
- Active filters shown as removable chips below header
- Scrollable body with collapsible sections:
  1. Collections (from Sidebar lines 158-228)
  2. Tags (from Sidebar lines 230-295)
  3. Game Systems (from Sidebar lines 316-367)
  4. Product Types (from Sidebar lines 370-406)
  5. Genres (from Sidebar lines 409-445)
  6. Authors (from Sidebar lines 448-500)
  7. Publishers (from Sidebar lines 503-555)
  8. Publication Year (from Sidebar lines 558-595)
  9. Adventure Filters (from Sidebar lines 598-678)
- All filter items: minimum 44px tall touch targets
- Text: 16px minimum throughout
- Section headers: 18px semibold

**Step 2: Commit**

```bash
git add frontend/src/components/FilterDrawer.tsx
git commit -m "feat: add FilterDrawer component with all filter sections"
```

---

### Task 5: Refactor App.tsx — New Layout with Nav Rail

**Files:**
- Modify: `frontend/src/App.tsx` (lines 1-97)

**Step 1: Update App.tsx layout**

Key changes:
- Wrap app in `ThemeProvider` (from Task 2)
- Replace `<aside>` sidebar (currently rendered inline) with `<NavRail>`
- Add `FilterDrawer` component with open/close state
- Move filter state management (currently lines 26-44) to work with FilterDrawer
- Pass filter button state to Library page header

New layout structure:
```tsx
<ThemeProvider>
  <div className="flex h-screen bg-[var(--color-bg)]">
    <NavRail activeView={activeView} onViewChange={setActiveView} />
    <main className="flex-1 overflow-hidden">
      {/* Active view content */}
    </main>
    <FilterDrawer isOpen={filterDrawerOpen} onClose={...} filters={...} ... />
  </div>
</ThemeProvider>
```

- Remove the old header bar with "Grimoire" branding (lines 49-58) — nav rail now has the title
- Remove `<Sidebar>` usage entirely
- Add `filterDrawerOpen` state and toggle function
- Pass `onOpenFilters` callback to Library page

**Step 2: Verify app loads with new layout**

Run: `cd frontend && npm run dev`
Expected: Nav rail on left, content area fills remaining space, filter drawer toggles open/close

**Step 3: Commit**

```bash
git add frontend/src/App.tsx
git commit -m "feat: replace sidebar layout with nav rail and filter drawer"
```

---

### Task 6: Update Library Page — Search Bar & Controls

**Files:**
- Modify: `frontend/src/pages/Library.tsx` (lines 1-233)

**Step 1: Update Library header/search bar**

Replace the current header section (lines 105-175) with:
- Full-width search bar, 48px tall, 18px placeholder text
- Search icon (20px) left-aligned inside input
- Clear button (X) right side of input when text present
- "Search content" as a toggle pill/switch next to the search input (not a checkbox)
- Right controls group:
  - Filter button with funnel icon + active filter count badge — calls `onOpenFilters()`
  - View toggle: Grid/List as segmented button group, 44px tall
  - Refresh button, 44px square

Update the header container:
- `--color-surface` background
- Sticky top, border-bottom with `--color-border`
- `shadow-sm`
- Padding: 16px 24px

**Step 2: Update grid column classes**

Replace grid classes (line ~80):
- From: `grid-cols-2 sm:grid-cols-3 md:grid-cols-4 lg:grid-cols-5 xl:grid-cols-6`
- To: `grid-cols-2 md:grid-cols-3 lg:grid-cols-4 2xl:grid-cols-5`
- Gap: `gap-5` (20px)
- Padding: `px-6 py-6`
- Max width: `max-w-7xl`

**Step 3: Commit**

```bash
git add frontend/src/pages/Library.tsx
git commit -m "feat: update Library page with larger search bar and reduced grid columns"
```

---

### Task 7: Update ProductCard — Larger, More Readable

**Files:**
- Modify: `frontend/src/components/ProductCard.tsx` (lines 1-225)

**Step 1: Update grid view card**

Changes to grid view (lines 131-224):
- Card padding: `p-4` on text section (was `p-3`)
- Title: `text-lg font-semibold` (18px, was `text-sm`)
- Publisher: `text-base` (16px, was `text-xs`)
- Badges: `text-sm px-3 py-1` (14px with more padding, was `text-xs px-2.5 py-0.5`)
- Badge colors: accent-light bg for system badge, neutral gray for type badge
- Page count: `text-base` (16px, was `text-xs`)
- Queue button: always visible, not hover-only. 44px min touch target
- Image: `rounded-t-md` (6px top corners)
- Card: `rounded-md` (6px), `shadow-sm` hover `shadow-md`
- Hover: remove `scale` transform, just shadow change
- Remove all `codex-*` color references, use CSS variables

**Step 2: Update list view card**

Changes to list view (lines 48-128):
- Row height: min 84px
- Thumbnail: 64x84px (was `h-16 w-12`)
- Title: `text-lg` (18px)
- Metadata: `text-base` (16px)
- Vertical padding: `py-3` (12px)
- Badges: same updates as grid view
- All text colors: `--color-text-primary` and `--color-text-secondary`

**Step 3: Commit**

```bash
git add frontend/src/components/ProductCard.tsx
git commit -m "feat: increase ProductCard font sizes and touch targets"
```

---

### Task 8: Update ProductGrid — Responsive & Empty State

**Files:**
- Modify: `frontend/src/components/ProductGrid.tsx` (lines 1-99)

**Step 1: Update grid and empty state**

- Empty state icon: 48px (was smaller)
- Empty state heading: `text-xl` (20px, was `text-lg`)
- Empty state description: `text-lg` (18px, was `text-sm`)
- All text colors: use CSS variables
- Ensure infinite scroll sentinel works with new layout

**Step 2: Commit**

```bash
git add frontend/src/components/ProductGrid.tsx
git commit -m "feat: update ProductGrid empty state for readability"
```

---

### Task 9: Update ProductDetail Modal

**Files:**
- Modify: `frontend/src/components/ProductDetail.tsx` (lines 1-1996)

**Step 1: Update modal container**

- Width: `max-w-4xl` (896px)
- Max height: `max-h-[90vh]`
- Border-radius: 8px (`rounded-lg`)
- Background: `--color-surface`
- Backdrop: `bg-black/50`

**Step 2: Update header layout**

- Cover image: 120x160px alongside metadata (not above it)
- Title: `text-2xl font-semibold` (24px)
- Publisher/year/pages: `text-lg` (18px), `--color-text-secondary`
- Badges: same updated styling as ProductCard
- Action buttons (Collection, Tag): directly in header, `btn-secondary` style
- Close button: 44px touch target, top-right

**Step 3: Update tab bar**

- Tab text: `text-lg` (18px)
- Tab height: 48px
- Active tab: accent underline, `--color-accent` text
- Inactive: `--color-text-secondary`

**Step 4: Update tab content**

- All body text: 18px minimum
- Content/text tab: `font-serif` (Crimson Pro), `text-lg`, `leading-relaxed` (1.6 line height), `max-w-prose` (~70ch)
- Details tab: two-column grid for key-value pairs, labels in `--color-text-secondary`
- Form inputs in edit mode: 48px height, 18px text
- Error messages: red banner, 16px text, clear contrast

**Step 5: Commit**

```bash
git add frontend/src/components/ProductDetail.tsx
git commit -m "feat: redesign ProductDetail modal with larger text and improved layout"
```

---

### Task 10: Update Settings Page

**Files:**
- Modify: `frontend/src/pages/Settings.tsx` (lines 1-722)

**Step 1: Update layout and form elements**

- Page container: single column, `max-w-2xl mx-auto`, `px-6 py-6`
- Page title: `text-2xl font-semibold` (28px)
- Section headings: `text-xl font-semibold` (24px)
- Section dividers: simple `border-b` with `--color-border`
- All inputs: 48px height, 18px text (use `.input` class which is already updated)
- Replace checkboxes with toggle switches (can use a simple styled checkbox that looks like a switch, or a small ToggleSwitch component)
- Folder paths: `font-mono text-base` (16px monospace)
- Labels: `text-lg` (18px)
- Helper text: `text-base` (16px), `--color-text-secondary`
- Add dark mode three-state selector: Light / Dark / System segmented control using `useThemeContext`
- All buttons: 44px min height

**Step 2: Commit**

```bash
git add frontend/src/pages/Settings.tsx
git commit -m "feat: update Settings page with larger inputs and theme selector"
```

---

### Task 11: Update ProcessingQueue

**Files:**
- Modify: `frontend/src/components/ProcessingQueue.tsx` (lines 1-415)

**Step 1: Update queue display**

- Modal: use `--color-surface` bg, `rounded-lg`, proper dark mode colors
- Table rows: 56px min height
- Status column: colored dot (12px) + text label, `text-base` (16px)
- Product name: `text-lg` (18px)
- Task type, attempts, time: `text-base` (16px)
- Progress bars: 8px height, `--color-accent` fill, percentage text next to bar
- Action buttons: clearly labeled text + icon, 44px min height
- Filter buttons in stats bar: `text-base`, 44px min height
- Replace all `codex-*` colors with CSS variables

**Step 2: Commit**

```bash
git add frontend/src/components/ProcessingQueue.tsx
git commit -m "feat: update ProcessingQueue with larger text and better contrast"
```

---

### Task 12: Update MaintenanceTools

**Files:**
- Modify: `frontend/src/components/MaintenanceTools.tsx` (lines 1-353)

**Step 1: Update maintenance tools display**

- Modal: `--color-surface` bg, `rounded-lg`
- Section headings: `text-xl` (24px)
- Status cards: `text-base` (16px) for stats, `text-lg` (18px) for values
- Tool buttons: 48px height, `text-base`, clear labels
- Result messages: `text-base` (16px), colored banners
- All spacing increased: `gap-4`, `p-6`
- Replace all `codex-*` colors with CSS variables

**Step 2: Commit**

```bash
git add frontend/src/components/MaintenanceTools.tsx
git commit -m "feat: update MaintenanceTools with larger text and modern styling"
```

---

### Task 13: Update Campaigns Page

**Files:**
- Modify: `frontend/src/pages/Campaigns.tsx` (lines 1-1052)

**Step 1: Update campaigns display**

- Page title: `text-2xl font-semibold`
- Campaign list cards: `text-lg` titles, `text-base` metadata
- Two-column layout: maintain but use CSS variables for all colors
- Session entries: `text-base` minimum
- Form inputs in modals: 48px height, 18px text
- Buttons: 44px min height, `text-base`
- All spacing: comfortable `p-4`/`p-6` padding
- Replace all `codex-*` colors with CSS variables

**Step 2: Commit**

```bash
git add frontend/src/pages/Campaigns.tsx
git commit -m "feat: update Campaigns page with larger text and modern styling"
```

---

### Task 14: Update LibraryManagement Page

**Files:**
- Modify: `frontend/src/pages/LibraryManagement.tsx` (lines 1-1980)

**Step 1: Update library management display**

- Modal container: `--color-surface` bg, `rounded-lg`
- Tab bar: `text-lg` (18px), 48px height
- Stats dashboard: larger numbers, `text-2xl` for key metrics
- Table rows: 56px min height, `text-base`
- Form elements: 48px inputs, 18px text
- Confirmation dialogs: `text-lg` body text, red danger button clearly labeled
- All spacing increased
- Replace all `codex-*` colors with CSS variables

**Step 2: Commit**

```bash
git add frontend/src/pages/LibraryManagement.tsx
git commit -m "feat: update LibraryManagement with larger text and modern styling"
```

---

### Task 15: Clean Up Old Sidebar & Remaining References

**Files:**
- Modify: `frontend/src/components/Sidebar.tsx` — can be deleted or kept as reference
- Grep all files for `codex-` color references and replace

**Step 1: Search for remaining old references**

Run: `grep -rn "codex-\|parchment\|shadow-tome\|Crimson Pro" frontend/src/ --include="*.tsx" --include="*.ts" --include="*.css"`

Fix any remaining references to old theme classes.

**Step 2: Remove Sidebar.tsx if no longer imported**

Check if Sidebar is still imported anywhere. If not, delete `frontend/src/components/Sidebar.tsx`.

**Step 3: Commit**

```bash
git add -A frontend/src/
git commit -m "chore: remove old Codex theme references and unused Sidebar component"
```

---

### Task 16: Tablet Responsiveness

**Files:**
- Modify: `frontend/src/components/NavRail.tsx`
- Modify: `frontend/src/components/FilterDrawer.tsx`
- Potentially modify: `frontend/src/App.tsx`

**Step 1: Add tablet breakpoint to NavRail**

Below 1024px (`lg` breakpoint):
- Nav rail switches to bottom tab bar
- Horizontal layout, icons + labels side by side
- Fixed bottom, full width, 56px height
- Settings and theme toggle move to a "more" menu or stay inline

**Step 2: Update FilterDrawer for tablet**

Below 1024px:
- Drawer becomes full-width overlay
- Slightly larger touch targets

**Step 3: Test at tablet widths**

Resize browser to 768px and 1024px, verify layout works.

**Step 4: Commit**

```bash
git add frontend/src/components/NavRail.tsx frontend/src/components/FilterDrawer.tsx
git commit -m "feat: add tablet-responsive bottom tab bar and full-width filter drawer"
```

---

### Task 17: Visual QA & Polish

**Files:**
- Any files needing touch-up

**Step 1: Full visual review**

Check each page at 1440px desktop width:
- Library grid view
- Library list view
- Product detail modal (all tabs)
- Settings page
- Campaigns page
- Library Management modal
- Processing Queue modal
- Maintenance Tools modal
- Filter drawer open/closed
- Dark mode on all of the above

**Step 2: Fix any spacing, color, or contrast issues found**

**Step 3: Test dark mode toggle**

- Toggle between light/dark/system
- Verify no flash on page reload
- Verify system preference detection works

**Step 4: Final commit**

```bash
git add -A frontend/src/
git commit -m "fix: visual polish and dark mode consistency fixes"
```
