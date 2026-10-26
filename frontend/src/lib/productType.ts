// The Codex product_type enum, mirrored from the backend
// (grimoire/services/classification/enum.py). The column holds these values;
// labels are for display only, so filters and saves use the raw value.
export const PRODUCT_TYPES = [
  'adventure',
  'sourcebook',
  'supplement',
  'bestiary',
  'tools',
  'magazine',
  'core_rulebook',
  'setting',
  'character_options',
  'gm_tools',
  'map',
  'zine',
  'screen',
  'other',
] as const;

// Every periodical in this library is a zine, so the edit dropdown leaves
// `magazine` out; a product that already holds it still shows its value.
export const SELECTABLE_PRODUCT_TYPES = PRODUCT_TYPES.filter((t) => t !== 'magazine');

const titleCase = (value: string) =>
  value.split('_').map((w) => w.charAt(0).toUpperCase() + w.slice(1)).join(' ');

export const PRODUCT_TYPE_LABELS: Record<string, string> = {
  ...Object.fromEntries(PRODUCT_TYPES.map((t) => [t, titleCase(t)])),
  core_rulebook: 'Core Rulebook',
  gm_tools: 'GM Tools',
  character_options: 'Character Options',
};

export function productTypeLabel(value: string | null | undefined): string {
  if (!value) return '';
  return PRODUCT_TYPE_LABELS[value] ?? value;
}
