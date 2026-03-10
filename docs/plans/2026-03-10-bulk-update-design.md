# Bulk Product Update System Design

## Problem
Auto-detected game systems and other metadata fields are often wrong. Users need a way to select multiple products and apply corrections in bulk.

## Workflow
1. User browses products in the existing grid/list view
2. Selects products via checkboxes on ProductCards
3. Clicks "Edit Selected" in a floating toolbar
4. Fills in fields to change in a bulk edit modal
5. Previews changes before confirming
6. Applies updates to all selected products

## Selection UX

- **Checkbox on ProductCard**: visible on hover (grid view) or always visible (list view), top-left corner
- **Select All**: checkbox in the grid header area, selects/deselects all currently loaded products
- **Selection state**: stored as a Set of product IDs in React state, persists across infinite scroll loads
- **Floating toolbar**: fixed to bottom of screen, appears when 1+ products selected
  - Shows "X products selected"
  - "Edit Selected" button
  - "Clear Selection" button

## Bulk Edit Modal

- **Title**: "Edit X Products"
- **Two-column layout**:
  - Left: game_system, product_type, genre, publisher, author
  - Right: publication_year, setting, series, estimated_runtime, format
- **Each field has 3 states**:
  - Empty/untouched — skipped, no change applied
  - Value entered — set on all selected products
  - Explicitly cleared — "clear" toggle per field sets value to null
- **Footer**: "Preview Changes" button, "Cancel" button

## Preview & Confirm Step

- Replaces the form content in the same modal (not a second modal)
- Summary of changes: e.g., "Set game_system to 'D&D 5e'" / "Clear genre"
- Only shows fields that will actually change
- "Apply to X products" count
- Scrollable list of affected product titles for spot-checking
- Footer: "Back" (return to form), "Apply Changes", "Cancel"

## Backend Changes

- **Extend `BulkUpdateRequest`** to include all 10 fields:
  - game_system, product_type, genre, publisher, author
  - publication_year, setting, series, estimated_runtime, format
- All fields are Optional — only provided fields get updated
- Support explicit null to distinguish "don't change" (absent) from "clear field" (null)
- Extend existing `/api/v1/bulk/update` endpoint (no new endpoints)
- Cache invalidation already triggers for filter-relevant fields
- Response returns count of updated products

## No New Endpoints

The existing product list endpoint (with filters) + extended bulk update endpoint cover all needs. No new API surface required.
