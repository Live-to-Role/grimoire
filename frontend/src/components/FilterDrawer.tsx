import { useState, useEffect } from 'react';
import { useQuery } from '@tanstack/react-query';
import {
  X,
  ChevronDown,
  ChevronRight,
  Search,
  FolderOpen,
  Tag,
  Gamepad2,
  FileText,
  BookMarked,
  User,
  Building2,
  Calendar,
  Swords,
  Plus,
  Pencil,
} from 'lucide-react';
import { CollectionManager } from './CollectionManager';
import { TagManager } from './TagManager';
import type { Collection } from '../api/collections';
import type { Tag as TagType } from '../api/tags';
import type { ProductFilters } from '../api/products';
import apiClient from '../api/client';

interface LibraryStats {
  total_products: number;
  total_pages: number;
  total_size_bytes: number;
  by_system: Record<string, number>;
  by_type: Record<string, number>;
  by_genre: Record<string, number>;
  by_author: Record<string, number>;
  by_publisher: Record<string, number>;
}

interface FilterDrawerProps {
  isOpen: boolean;
  onClose: () => void;
  onFilterChange: (filterType: keyof ProductFilters, value: string | null) => void;
  activeFilters: Partial<ProductFilters>;
  onClearFilters: () => void;
  selectedCollection: number | null;
  onSelectCollection: (id: number | null) => void;
  selectedTag: number | null;
  onSelectTag: (id: number | null) => void;
}

// Collapsible section component
function FilterSection({
  title,
  icon: Icon,
  defaultExpanded = false,
  children,
}: {
  title: string;
  icon: React.ElementType;
  defaultExpanded?: boolean;
  children: React.ReactNode;
}) {
  const [expanded, setExpanded] = useState(defaultExpanded);

  return (
    <div className="border-b" style={{ borderColor: 'var(--color-border)' }}>
      <button
        onClick={() => setExpanded(!expanded)}
        className="flex w-full items-center gap-2 px-5 py-3 text-lg font-semibold transition-colors"
        style={{ color: 'var(--color-text-primary)' }}
      >
        {expanded ? <ChevronDown size={16} /> : <ChevronRight size={16} />}
        <Icon size={16} />
        {title}
      </button>
      {expanded && <div className="px-5 pb-4">{children}</div>}
    </div>
  );
}

// Filter item button
function FilterItem({
  label,
  count,
  active,
  onClick,
}: {
  label: string;
  count?: number;
  active: boolean;
  onClick: () => void;
}) {
  return (
    <button
      onClick={onClick}
      className="flex w-full items-center justify-between rounded-md px-3 py-2.5 text-base transition-colors"
      style={{
        backgroundColor: active ? 'var(--color-accent-light)' : 'transparent',
        color: active ? 'var(--color-accent)' : 'var(--color-text-primary)',
        fontWeight: active ? 500 : 400,
        minHeight: '44px',
      }}
      onMouseEnter={(e) => {
        if (!active) e.currentTarget.style.backgroundColor = 'var(--color-surface-raised)';
      }}
      onMouseLeave={(e) => {
        if (!active) e.currentTarget.style.backgroundColor = 'transparent';
      }}
    >
      <span className="truncate">{label}</span>
      {count != null && (
        <span className="text-sm ml-2" style={{ color: 'var(--color-text-secondary)' }}>
          {count}
        </span>
      )}
    </button>
  );
}

// Searchable filter list
function SearchableFilterList({
  entries,
  activeValue,
  onSelect,
}: {
  entries: [string, number][];
  activeValue?: string;
  onSelect: (value: string | null) => void;
}) {
  const [search, setSearch] = useState('');
  const filtered = entries
    .filter(([name]) => name.toLowerCase().includes(search.toLowerCase()))
    .sort((a, b) => b[1] - a[1]);

  return (
    <div>
      <div className="relative mb-2">
        <Search className="absolute left-3 top-1/2 -translate-y-1/2" size={14} style={{ color: 'var(--color-text-secondary)' }} />
        <input
          type="text"
          placeholder="Search..."
          value={search}
          onChange={(e) => setSearch(e.target.value)}
          className="w-full rounded-md py-2 pl-8 pr-3 text-sm"
          style={{
            backgroundColor: 'var(--color-surface-raised)',
            color: 'var(--color-text-primary)',
            border: '1px solid var(--color-border)',
          }}
        />
      </div>
      <div className="max-h-48 overflow-y-auto space-y-0.5">
        {filtered.slice(0, 50).map(([name, count]) => (
          <FilterItem
            key={name}
            label={name}
            count={count}
            active={activeValue === name}
            onClick={() => onSelect(activeValue === name ? null : name)}
          />
        ))}
      </div>
    </div>
  );
}

export function FilterDrawer({
  isOpen,
  onClose,
  onFilterChange,
  activeFilters,
  onClearFilters,
  selectedCollection,
  onSelectCollection,
  selectedTag,
  onSelectTag,
}: FilterDrawerProps) {
  // Modal states for collection/tag management
  const [showCollectionManager, setShowCollectionManager] = useState(false);
  const [editingCollection, setEditingCollection] = useState<Collection | null>(null);
  const [showTagManager, setShowTagManager] = useState(false);
  const [editingTag, setEditingTag] = useState<TagType | null>(null);

  const activeFilterCount = Object.keys(activeFilters).filter(
    (k) => !['page', 'per_page', 'sort', 'order'].includes(k)
  ).length + (selectedCollection ? 1 : 0) + (selectedTag ? 1 : 0);

  const { data: collections } = useQuery({
    queryKey: ['collections'],
    queryFn: async () => {
      const res = await apiClient.get<Collection[]>('/collections');
      return res.data;
    },
  });

  const { data: tags } = useQuery({
    queryKey: ['tags'],
    queryFn: async () => {
      const res = await apiClient.get<TagType[]>('/tags');
      return res.data;
    },
  });

  const { data: stats } = useQuery({
    queryKey: ['library-stats'],
    queryFn: async () => {
      const res = await apiClient.get<LibraryStats>('/folders/library/stats');
      return res.data;
    },
  });

  // Close on Escape
  useEffect(() => {
    const handler = (e: KeyboardEvent) => {
      if (e.key === 'Escape') onClose();
    };
    if (isOpen) {
      document.addEventListener('keydown', handler);
      return () => document.removeEventListener('keydown', handler);
    }
  }, [isOpen, onClose]);

  return (
    <>
      {/* Backdrop */}
      {isOpen && (
        <div
          className="fixed inset-0 z-40 bg-black/30 transition-opacity"
          onClick={onClose}
        />
      )}

      {/* Drawer */}
      <aside
        className="fixed top-0 right-0 z-50 h-full w-full max-w-[360px] shadow-lg flex flex-col transition-transform duration-300 ease-in-out"
        style={{
          backgroundColor: 'var(--color-surface)',
          borderLeft: '1px solid var(--color-border)',
          transform: isOpen ? 'translateX(0)' : 'translateX(100%)',
        }}
      >
        {/* Header */}
        <div
          className="flex items-center justify-between px-5 py-4 border-b"
          style={{ borderColor: 'var(--color-border)' }}
        >
          <div className="flex items-center gap-3">
            <h2 className="text-xl font-semibold" style={{ color: 'var(--color-text-primary)', fontFamily: 'var(--font-sans)' }}>
              Filters
            </h2>
            {activeFilterCount > 0 && (
              <span
                className="flex items-center justify-center min-w-[24px] h-6 rounded-full text-sm font-medium text-white px-2"
                style={{ backgroundColor: 'var(--color-accent)' }}
              >
                {activeFilterCount}
              </span>
            )}
          </div>
          <div className="flex items-center gap-2">
            {activeFilterCount > 0 && (
              <button
                onClick={() => {
                  onClearFilters();
                  onSelectCollection(null);
                  onSelectTag(null);
                }}
                className="text-sm font-medium px-3 py-1.5 rounded-md transition-colors"
                style={{ color: 'var(--color-accent)' }}
                onMouseEnter={(e) => { e.currentTarget.style.backgroundColor = 'var(--color-accent-light)'; }}
                onMouseLeave={(e) => { e.currentTarget.style.backgroundColor = 'transparent'; }}
              >
                Clear all
              </button>
            )}
            <button
              onClick={onClose}
              className="flex items-center justify-center w-10 h-10 rounded-md transition-colors"
              style={{ color: 'var(--color-text-secondary)' }}
              onMouseEnter={(e) => { e.currentTarget.style.backgroundColor = 'var(--color-surface-raised)'; }}
              onMouseLeave={(e) => { e.currentTarget.style.backgroundColor = 'transparent'; }}
              title="Close filters"
            >
              <X size={20} />
            </button>
          </div>
        </div>

        {/* Active filter chips */}
        {activeFilterCount > 0 && (
          <div className="flex flex-wrap gap-2 px-5 py-3 border-b" style={{ borderColor: 'var(--color-border)' }}>
            {selectedCollection && collections && (
              <FilterChip
                label={`Collection: ${collections.find(c => c.id === selectedCollection)?.name || '...'}`}
                onRemove={() => onSelectCollection(null)}
              />
            )}
            {selectedTag && tags && (
              <FilterChip
                label={`Tag: ${tags.find(t => t.id === selectedTag)?.name || '...'}`}
                onRemove={() => onSelectTag(null)}
              />
            )}
            {Object.entries(activeFilters)
              .filter(([k]) => !['page', 'per_page', 'sort', 'order'].includes(k))
              .map(([key, value]) => (
                <FilterChip
                  key={key}
                  label={`${formatFilterKey(key)}: ${value}`}
                  onRemove={() => onFilterChange(key as keyof ProductFilters, null)}
                />
              ))}
          </div>
        )}

        {/* Scrollable body */}
        <div className="flex-1 overflow-y-auto">
          {/* Collections */}
          <FilterSection title="Collections" icon={FolderOpen} defaultExpanded>
            <div className="space-y-0.5">
              {collections?.map((collection) => (
                <div key={collection.id} className="group relative">
                  <FilterItem
                    label={collection.name}
                    count={collection.product_count}
                    active={selectedCollection === collection.id}
                    onClick={() => {
                      onSelectCollection(selectedCollection === collection.id ? null : collection.id);
                      onSelectTag(null);
                    }}
                  />
                  <button
                    onClick={(e) => {
                      e.stopPropagation();
                      setEditingCollection(collection);
                      setShowCollectionManager(true);
                    }}
                    className="absolute right-2 top-1/2 -translate-y-1/2 hidden rounded p-1 group-hover:block transition-colors"
                    style={{ color: 'var(--color-text-secondary)' }}
                    title="Edit collection"
                  >
                    <Pencil size={14} />
                  </button>
                </div>
              ))}
              {(!collections || collections.length === 0) && (
                <p className="py-2 text-base" style={{ color: 'var(--color-text-secondary)' }}>
                  No collections yet
                </p>
              )}
              <button
                onClick={() => {
                  setEditingCollection(null);
                  setShowCollectionManager(true);
                }}
                className="flex items-center gap-2 text-sm font-medium mt-2 px-3 py-2 rounded-md transition-colors"
                style={{ color: 'var(--color-accent)' }}
                onMouseEnter={(e) => { e.currentTarget.style.backgroundColor = 'var(--color-accent-light)'; }}
                onMouseLeave={(e) => { e.currentTarget.style.backgroundColor = 'transparent'; }}
              >
                <Plus size={14} />
                New collection
              </button>
            </div>
          </FilterSection>

          {/* Tags */}
          <FilterSection title="Tags" icon={Tag}>
            <div className="space-y-0.5">
              {tags?.map((tag) => (
                <div key={tag.id} className="group relative">
                  <FilterItem
                    label={tag.name}
                    count={tag.product_count}
                    active={selectedTag === tag.id}
                    onClick={() => {
                      onSelectTag(selectedTag === tag.id ? null : tag.id);
                      onSelectCollection(null);
                    }}
                  />
                  <button
                    onClick={(e) => {
                      e.stopPropagation();
                      setEditingTag(tag);
                      setShowTagManager(true);
                    }}
                    className="absolute right-2 top-1/2 -translate-y-1/2 hidden rounded p-1 group-hover:block transition-colors"
                    style={{ color: 'var(--color-text-secondary)' }}
                    title="Edit tag"
                  >
                    <Pencil size={14} />
                  </button>
                </div>
              ))}
              {(!tags || tags.length === 0) && (
                <p className="py-2 text-base" style={{ color: 'var(--color-text-secondary)' }}>
                  No tags yet
                </p>
              )}
              <button
                onClick={() => {
                  setEditingTag(null);
                  setShowTagManager(true);
                }}
                className="flex items-center gap-2 text-sm font-medium mt-2 px-3 py-2 rounded-md transition-colors"
                style={{ color: 'var(--color-accent)' }}
                onMouseEnter={(e) => { e.currentTarget.style.backgroundColor = 'var(--color-accent-light)'; }}
                onMouseLeave={(e) => { e.currentTarget.style.backgroundColor = 'transparent'; }}
              >
                <Plus size={14} />
                New tag
              </button>
            </div>
          </FilterSection>

          {/* Game Systems */}
          <FilterSection title="Game Systems" icon={Gamepad2} defaultExpanded>
            {stats && (
              <SearchableFilterList
                entries={Object.entries(stats.by_system)}
                activeValue={activeFilters.game_system}
                onSelect={(v) => onFilterChange('game_system', v)}
              />
            )}
          </FilterSection>

          {/* Product Types */}
          <FilterSection title="Product Types" icon={FileText}>
            {stats && (
              <div className="space-y-0.5 max-h-48 overflow-y-auto">
                {Object.entries(stats.by_type)
                  .sort((a, b) => b[1] - a[1])
                  .map(([type, count]) => (
                    <FilterItem
                      key={type}
                      label={type}
                      count={count}
                      active={activeFilters.product_type === type}
                      onClick={() => onFilterChange('product_type', activeFilters.product_type === type ? null : type)}
                    />
                  ))}
              </div>
            )}
          </FilterSection>

          {/* Genres */}
          <FilterSection title="Genres" icon={BookMarked}>
            {stats && (
              <div className="space-y-0.5 max-h-48 overflow-y-auto">
                {Object.entries(stats.by_genre)
                  .sort((a, b) => b[1] - a[1])
                  .map(([genre, count]) => (
                    <FilterItem
                      key={genre}
                      label={genre}
                      count={count}
                      active={activeFilters.genre === genre}
                      onClick={() => onFilterChange('genre', activeFilters.genre === genre ? null : genre)}
                    />
                  ))}
              </div>
            )}
          </FilterSection>

          {/* Authors */}
          <FilterSection title="Authors" icon={User}>
            {stats && (
              <SearchableFilterList
                entries={Object.entries(stats.by_author)}
                activeValue={activeFilters.author}
                onSelect={(v) => onFilterChange('author', v)}
              />
            )}
          </FilterSection>

          {/* Publishers */}
          <FilterSection title="Publishers" icon={Building2}>
            {stats && (
              <SearchableFilterList
                entries={Object.entries(stats.by_publisher)}
                activeValue={activeFilters.publisher}
                onSelect={(v) => onFilterChange('publisher', v)}
              />
            )}
          </FilterSection>

          {/* Publication Year */}
          <FilterSection title="Publication Year" icon={Calendar}>
            <div className="flex items-center gap-3">
              <input
                type="number"
                placeholder="From"
                value={activeFilters.publication_year_min || ''}
                onChange={(e) => onFilterChange('publication_year_min', e.target.value || null)}
                className="input"
                style={{ height: '44px' }}
              />
              <span style={{ color: 'var(--color-text-secondary)' }}>-</span>
              <input
                type="number"
                placeholder="To"
                value={activeFilters.publication_year_max || ''}
                onChange={(e) => onFilterChange('publication_year_max', e.target.value || null)}
                className="input"
                style={{ height: '44px' }}
              />
            </div>
          </FilterSection>

          {/* Adventure Filters */}
          <FilterSection title="Adventure Filters" icon={Swords}>
            <div className="space-y-4">
              <div>
                <label className="text-base mb-2 block font-medium" style={{ color: 'var(--color-text-secondary)' }}>
                  Level Range
                </label>
                <div className="flex items-center gap-3">
                  <input
                    type="number"
                    placeholder="Min"
                    min="1"
                    max="20"
                    value={activeFilters.level_min || ''}
                    onChange={(e) => onFilterChange('level_min', e.target.value || null)}
                    className="input"
                    style={{ height: '44px' }}
                  />
                  <span style={{ color: 'var(--color-text-secondary)' }}>-</span>
                  <input
                    type="number"
                    placeholder="Max"
                    min="1"
                    max="20"
                    value={activeFilters.level_max || ''}
                    onChange={(e) => onFilterChange('level_max', e.target.value || null)}
                    className="input"
                    style={{ height: '44px' }}
                  />
                </div>
              </div>

              <div>
                <label className="text-base mb-2 block font-medium" style={{ color: 'var(--color-text-secondary)' }}>
                  Party Size
                </label>
                <div className="flex items-center gap-3">
                  <input
                    type="number"
                    placeholder="Min"
                    min="1"
                    max="10"
                    value={activeFilters.party_size_min || ''}
                    onChange={(e) => onFilterChange('party_size_min', e.target.value || null)}
                    className="input"
                    style={{ height: '44px' }}
                  />
                  <span style={{ color: 'var(--color-text-secondary)' }}>-</span>
                  <input
                    type="number"
                    placeholder="Max"
                    min="1"
                    max="10"
                    value={activeFilters.party_size_max || ''}
                    onChange={(e) => onFilterChange('party_size_max', e.target.value || null)}
                    className="input"
                    style={{ height: '44px' }}
                  />
                </div>
              </div>

              <div>
                <label className="text-base mb-2 block font-medium" style={{ color: 'var(--color-text-secondary)' }}>
                  Estimated Runtime
                </label>
                <input
                  type="text"
                  placeholder="e.g., 4-6 hours"
                  value={activeFilters.estimated_runtime || ''}
                  onChange={(e) => onFilterChange('estimated_runtime', e.target.value || null)}
                  className="input"
                  style={{ height: '44px' }}
                />
              </div>
            </div>
          </FilterSection>
        </div>
      </aside>

      {/* Collection Manager Modal */}
      {showCollectionManager && (
        <CollectionManager
          collection={editingCollection}
          onClose={() => {
            setShowCollectionManager(false);
            setEditingCollection(null);
          }}
        />
      )}

      {/* Tag Manager Modal */}
      {showTagManager && (
        <TagManager
          tag={editingTag}
          onClose={() => {
            setShowTagManager(false);
            setEditingTag(null);
          }}
        />
      )}
    </>
  );
}

function FilterChip({ label, onRemove }: { label: string; onRemove: () => void }) {
  return (
    <span
      className="inline-flex items-center gap-1.5 rounded-full px-3 py-1 text-sm"
      style={{
        backgroundColor: 'var(--color-accent-light)',
        color: 'var(--color-accent)',
      }}
    >
      {label}
      <button
        onClick={onRemove}
        className="rounded-full p-0.5 transition-colors hover:bg-white/20"
      >
        <X size={12} />
      </button>
    </span>
  );
}

function formatFilterKey(key: string): string {
  return key
    .replace(/_/g, ' ')
    .replace(/\b\w/g, (c) => c.toUpperCase())
    .replace('Min', 'min')
    .replace('Max', 'max');
}
