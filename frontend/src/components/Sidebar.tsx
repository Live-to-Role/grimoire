import { useState } from 'react';
import { useQuery } from '@tanstack/react-query';
import {
  Library,
  FolderOpen,
  Tag,
  ChevronDown,
  ChevronRight,
  Sparkles,
  Settings,
  ListTodo,
  BookOpen,
  HardDrive,
  Gamepad2,
  BookMarked,
  User,
  Building2,
  X,
  Search,
  FileText,
  Calendar,
  Swords,
  Wrench,
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

interface SidebarProps {
  activeView: string;
  onViewChange: (view: string) => void;
  onCollectionSelect: (id: number | null) => void;
  onTagSelect: (id: number | null) => void;
  selectedCollection: number | null;
  selectedTag: number | null;
  onFilterChange: (filterType: keyof ProductFilters, value: string | null) => void;
  activeFilters: Partial<ProductFilters>;
  onClearFilters: () => void;
}

export function Sidebar({
  activeView,
  onViewChange,
  onCollectionSelect,
  onTagSelect,
  selectedCollection,
  selectedTag,
  onFilterChange,
  activeFilters,
  onClearFilters,
}: SidebarProps) {
  const [collectionsExpanded, setCollectionsExpanded] = useState(true);
  const [tagsExpanded, setTagsExpanded] = useState(false);
  const [systemsExpanded, setSystemsExpanded] = useState(true);
  const [typesExpanded, setTypesExpanded] = useState(false);
  const [genresExpanded, setGenresExpanded] = useState(false);
  const [authorsExpanded, setAuthorsExpanded] = useState(false);
  const [publishersExpanded, setPublishersExpanded] = useState(false);
  const [yearExpanded, setYearExpanded] = useState(false);
  const [adventureExpanded, setAdventureExpanded] = useState(false);

  // Modal states for collection/tag management
  const [showCollectionManager, setShowCollectionManager] = useState(false);
  const [editingCollection, setEditingCollection] = useState<Collection | null>(null);
  const [showTagManager, setShowTagManager] = useState(false);
  const [editingTag, setEditingTag] = useState<TagType | null>(null);

  // Search states for high-cardinality filters
  const [systemSearch, setSystemSearch] = useState('');
  const [authorSearch, setAuthorSearch] = useState('');
  const [publisherSearch, setPublisherSearch] = useState('');

  const activeFilterCount = Object.keys(activeFilters).filter(
    k => !['page', 'per_page', 'sort', 'order'].includes(k)
  ).length;

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

  const handleEditCollection = (collection: Collection, e: React.MouseEvent) => {
    e.stopPropagation();
    setEditingCollection(collection);
    setShowCollectionManager(true);
  };

  const handleEditTag = (tag: TagType, e: React.MouseEvent) => {
    e.stopPropagation();
    setEditingTag(tag);
    setShowTagManager(true);
  };

  const { data: stats } = useQuery({
    queryKey: ['library-stats'],
    queryFn: async () => {
      const res = await apiClient.get<LibraryStats>('/folders/library/stats');
      return res.data;
    },
  });

  const formatBytes = (bytes: number) => {
    if (bytes < 1024) return `${bytes} B`;
    if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
    if (bytes < 1024 * 1024 * 1024) return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
    return `${(bytes / (1024 * 1024 * 1024)).toFixed(1)} GB`;
  };

  return (
    <aside className="flex h-full w-64 flex-col border-r border-neutral-200 bg-white">
      <div className="flex items-center gap-2 border-b border-neutral-200 px-4 py-4">
        <Sparkles className="h-6 w-6 text-purple-600" />
        <h1 className="text-xl font-bold text-purple-700">Grimoire</h1>
      </div>

      <nav className="flex-1 overflow-y-auto p-2">
        <button
          onClick={() => {
            onViewChange('library');
            onCollectionSelect(null);
            onTagSelect(null);
          }}
          aria-current={activeView === 'library' && !selectedCollection && !selectedTag ? 'page' : undefined}
          className={`flex w-full items-center gap-3 rounded-lg px-3 py-2 text-left text-sm font-medium ${
            activeView === 'library' && !selectedCollection && !selectedTag
              ? 'bg-purple-100 text-purple-700'
              : 'text-neutral-700 hover:bg-neutral-100'
          }`}
        >
          <Library className="h-4 w-4" />
          All Products
          {stats && (
            <span className="ml-auto text-xs text-neutral-500">{stats.total_products}</span>
          )}
        </button>

        <div className="mt-4">
          <div className="flex items-center justify-between px-3 py-1.5">
            <button
              onClick={() => setCollectionsExpanded(!collectionsExpanded)}
              aria-expanded={collectionsExpanded}
              aria-controls="collections-list"
              className="flex items-center gap-2 text-xs font-semibold uppercase tracking-wider text-neutral-500"
            >
              {collectionsExpanded ? (
                <ChevronDown className="h-3 w-3" />
              ) : (
                <ChevronRight className="h-3 w-3" />
              )}
              Collections
            </button>
            <button
              onClick={() => {
                setEditingCollection(null);
                setShowCollectionManager(true);
              }}
              className="rounded p-1 text-neutral-400 hover:bg-neutral-100 hover:text-neutral-600"
              aria-label="Create collection"
              title="Create collection"
            >
              <Plus className="h-3.5 w-3.5" />
            </button>
          </div>

          {collectionsExpanded && (
            <div id="collections-list" className="mt-1 space-y-0.5" role="list">
              {collections?.map((collection) => (
                <div
                  key={collection.id}
                  className="group relative"
                >
                  <button
                    onClick={() => {
                      onCollectionSelect(collection.id);
                      onTagSelect(null);
                    }}
                    className={`flex w-full items-center gap-3 rounded-lg px-3 py-2 text-left text-sm ${
                      selectedCollection === collection.id
                        ? 'bg-purple-100 text-purple-700'
                        : 'text-neutral-700 hover:bg-neutral-100'
                    }`}
                  >
                    <FolderOpen
                      className="h-4 w-4 shrink-0"
                      style={{ color: collection.color || undefined }}
                    />
                    <span className="truncate flex-1">{collection.name}</span>
                    <span className="text-xs text-neutral-500 group-hover:hidden">
                      {collection.product_count}
                    </span>
                    <button
                      onClick={(e) => handleEditCollection(collection, e)}
                      className="hidden rounded p-1 text-neutral-400 hover:bg-neutral-200 hover:text-neutral-600 group-hover:block"
                      aria-label={`Edit ${collection.name}`}
                      title="Edit collection"
                    >
                      <Pencil className="h-3 w-3" />
                    </button>
                  </button>
                </div>
              ))}
              {(!collections || collections.length === 0) && (
                <p className="px-3 py-2 text-xs text-neutral-500">No collections yet</p>
              )}
            </div>
          )}
        </div>

        <div className="mt-4">
          <div className="flex items-center justify-between px-3 py-1.5">
            <button
              onClick={() => setTagsExpanded(!tagsExpanded)}
              aria-expanded={tagsExpanded}
              aria-controls="tags-list"
              className="flex items-center gap-2 text-xs font-semibold uppercase tracking-wider text-neutral-500"
            >
              {tagsExpanded ? (
                <ChevronDown className="h-3 w-3" />
              ) : (
                <ChevronRight className="h-3 w-3" />
              )}
              Tags
            </button>
            <button
              onClick={() => {
                setEditingTag(null);
                setShowTagManager(true);
              }}
              className="rounded p-1 text-neutral-400 hover:bg-neutral-100 hover:text-neutral-600"
              aria-label="Create tag"
              title="Create tag"
            >
              <Plus className="h-3.5 w-3.5" />
            </button>
          </div>

          {tagsExpanded && (
            <div id="tags-list" className="mt-1 space-y-0.5" role="list">
              {tags?.map((tag) => (
                <div
                  key={tag.id}
                  className="group relative"
                >
                  <button
                    onClick={() => {
                      onTagSelect(tag.id);
                      onCollectionSelect(null);
                    }}
                    className={`flex w-full items-center gap-3 rounded-lg px-3 py-2 text-left text-sm ${
                      selectedTag === tag.id
                        ? 'bg-purple-100 text-purple-700'
                        : 'text-neutral-700 hover:bg-neutral-100'
                    }`}
                  >
                    <Tag className="h-4 w-4 shrink-0" style={{ color: tag.color || undefined }} />
                    <span className="truncate flex-1">{tag.name}</span>
                    <span className="text-xs text-neutral-500 group-hover:hidden">{tag.product_count}</span>
                    <button
                      onClick={(e) => handleEditTag(tag, e)}
                      className="hidden rounded p-1 text-neutral-400 hover:bg-neutral-200 hover:text-neutral-600 group-hover:block"
                      aria-label={`Edit ${tag.name}`}
                      title="Edit tag"
                    >
                      <Pencil className="h-3 w-3" />
                    </button>
                  </button>
                </div>
              ))}
              {(!tags || tags.length === 0) && (
                <p className="px-3 py-2 text-xs text-neutral-500">No tags yet</p>
              )}
            </div>
          )}
        </div>

        {/* Active Filters Indicator */}
        {activeFilterCount > 0 && (
          <div className="mt-4 mx-2 p-2 bg-purple-50 rounded-lg">
            <div className="flex items-center justify-between">
              <span className="text-xs font-medium text-purple-700">
                {activeFilterCount} filter{activeFilterCount > 1 ? 's' : ''} active
              </span>
              <button
                onClick={onClearFilters}
                className="text-xs text-purple-600 hover:text-purple-800 flex items-center gap-1"
              >
                <X className="h-3 w-3" />
                Clear
              </button>
            </div>
          </div>
        )}

        {/* Game Systems Filter */}
        <div className="mt-4">
          <button
            onClick={() => setSystemsExpanded(!systemsExpanded)}
            aria-expanded={systemsExpanded}
            aria-controls="systems-list"
            className="flex w-full items-center gap-2 px-3 py-1.5 text-xs font-semibold uppercase tracking-wider text-neutral-500"
          >
            {systemsExpanded ? (
              <ChevronDown className="h-3 w-3" />
            ) : (
              <ChevronRight className="h-3 w-3" />
            )}
            <Gamepad2 className="h-3 w-3" />
            Game Systems
          </button>

          {systemsExpanded && stats && (
            <div id="systems-list" className="mt-1" role="list">
              <div className="px-2 pb-2">
                <div className="relative">
                  <Search className="absolute left-2 top-1/2 h-3 w-3 -translate-y-1/2 text-neutral-400" />
                  <input
                    type="text"
                    placeholder="Search..."
                    value={systemSearch}
                    onChange={(e) => setSystemSearch(e.target.value)}
                    className="w-full rounded border border-neutral-200 bg-neutral-50 py-1 pl-7 pr-2 text-xs focus:border-purple-400 focus:outline-none"
                  />
                </div>
              </div>
              <div className="space-y-0.5 max-h-40 overflow-y-auto">
                {Object.entries(stats.by_system)
                  .filter(([system]) => system.toLowerCase().includes(systemSearch.toLowerCase()))
                  .sort((a, b) => b[1] - a[1])
                  .map(([system, count]) => (
                    <button
                      key={system}
                      onClick={() => onFilterChange('game_system', activeFilters.game_system === system ? null : system)}
                      className={`flex w-full items-center justify-between px-3 py-1.5 text-sm rounded-md ${
                        activeFilters.game_system === system
                          ? 'bg-purple-100 text-purple-700'
                          : 'text-neutral-600 hover:bg-neutral-100'
                      }`}
                    >
                      <span className="truncate">{system}</span>
                      <span className="text-xs text-neutral-500">{count}</span>
                    </button>
                  ))}
              </div>
            </div>
          )}
        </div>

        {/* Product Types Filter */}
        <div className="mt-4">
          <button
            onClick={() => setTypesExpanded(!typesExpanded)}
            aria-expanded={typesExpanded}
            aria-controls="types-list"
            className="flex w-full items-center gap-2 px-3 py-1.5 text-xs font-semibold uppercase tracking-wider text-neutral-500"
          >
            {typesExpanded ? (
              <ChevronDown className="h-3 w-3" />
            ) : (
              <ChevronRight className="h-3 w-3" />
            )}
            <FileText className="h-3 w-3" />
            Product Types
          </button>

          {typesExpanded && stats && (
            <div id="types-list" className="mt-1 space-y-0.5 max-h-48 overflow-y-auto" role="list">
              {Object.entries(stats.by_type)
                .sort((a, b) => b[1] - a[1])
                .map(([type, count]) => (
                  <button
                    key={type}
                    onClick={() => onFilterChange('product_type', activeFilters.product_type === type ? null : type)}
                    className={`flex w-full items-center justify-between px-3 py-1.5 text-sm rounded-md ${
                      activeFilters.product_type === type
                        ? 'bg-purple-100 text-purple-700'
                        : 'text-neutral-600 hover:bg-neutral-100'
                    }`}
                  >
                    <span className="truncate">{type}</span>
                    <span className="text-xs text-neutral-500">{count}</span>
                  </button>
                ))}
            </div>
          )}
        </div>

        {/* Genres Filter */}
        <div className="mt-4">
          <button
            onClick={() => setGenresExpanded(!genresExpanded)}
            aria-expanded={genresExpanded}
            aria-controls="genres-list"
            className="flex w-full items-center gap-2 px-3 py-1.5 text-xs font-semibold uppercase tracking-wider text-neutral-500"
          >
            {genresExpanded ? (
              <ChevronDown className="h-3 w-3" />
            ) : (
              <ChevronRight className="h-3 w-3" />
            )}
            <BookMarked className="h-3 w-3" />
            Genres
          </button>

          {genresExpanded && stats && (
            <div id="genres-list" className="mt-1 space-y-0.5 max-h-48 overflow-y-auto" role="list">
              {Object.entries(stats.by_genre)
                .sort((a, b) => b[1] - a[1])
                .map(([genre, count]) => (
                  <button
                    key={genre}
                    onClick={() => onFilterChange('genre', activeFilters.genre === genre ? null : genre)}
                    className={`flex w-full items-center justify-between px-3 py-1.5 text-sm rounded-md ${
                      activeFilters.genre === genre
                        ? 'bg-purple-100 text-purple-700'
                        : 'text-neutral-600 hover:bg-neutral-100'
                    }`}
                  >
                    <span className="truncate">{genre}</span>
                    <span className="text-xs text-neutral-500">{count}</span>
                  </button>
                ))}
            </div>
          )}
        </div>

        {/* Authors Filter */}
        <div className="mt-4">
          <button
            onClick={() => setAuthorsExpanded(!authorsExpanded)}
            aria-expanded={authorsExpanded}
            aria-controls="authors-list"
            className="flex w-full items-center gap-2 px-3 py-1.5 text-xs font-semibold uppercase tracking-wider text-neutral-500"
          >
            {authorsExpanded ? (
              <ChevronDown className="h-3 w-3" />
            ) : (
              <ChevronRight className="h-3 w-3" />
            )}
            <User className="h-3 w-3" />
            Authors
          </button>

          {authorsExpanded && stats && (
            <div id="authors-list" className="mt-1" role="list">
              <div className="px-2 pb-2">
                <div className="relative">
                  <Search className="absolute left-2 top-1/2 h-3 w-3 -translate-y-1/2 text-neutral-400" />
                  <input
                    type="text"
                    placeholder="Search..."
                    value={authorSearch}
                    onChange={(e) => setAuthorSearch(e.target.value)}
                    className="w-full rounded border border-neutral-200 bg-neutral-50 py-1 pl-7 pr-2 text-xs focus:border-purple-400 focus:outline-none"
                  />
                </div>
              </div>
              <div className="space-y-0.5 max-h-40 overflow-y-auto">
                {Object.entries(stats.by_author)
                  .filter(([author]) => author.toLowerCase().includes(authorSearch.toLowerCase()))
                  .sort((a, b) => b[1] - a[1])
                  .slice(0, 50)
                  .map(([author, count]) => (
                    <button
                      key={author}
                      onClick={() => onFilterChange('author', activeFilters.author === author ? null : author)}
                      className={`flex w-full items-center justify-between px-3 py-1.5 text-sm rounded-md ${
                        activeFilters.author === author
                          ? 'bg-purple-100 text-purple-700'
                          : 'text-neutral-600 hover:bg-neutral-100'
                      }`}
                    >
                      <span className="truncate">{author}</span>
                      <span className="text-xs text-neutral-500">{count}</span>
                    </button>
                  ))}
              </div>
            </div>
          )}
        </div>

        {/* Publishers Filter */}
        <div className="mt-4">
          <button
            onClick={() => setPublishersExpanded(!publishersExpanded)}
            aria-expanded={publishersExpanded}
            aria-controls="publishers-list"
            className="flex w-full items-center gap-2 px-3 py-1.5 text-xs font-semibold uppercase tracking-wider text-neutral-500"
          >
            {publishersExpanded ? (
              <ChevronDown className="h-3 w-3" />
            ) : (
              <ChevronRight className="h-3 w-3" />
            )}
            <Building2 className="h-3 w-3" />
            Publishers
          </button>

          {publishersExpanded && stats && (
            <div id="publishers-list" className="mt-1" role="list">
              <div className="px-2 pb-2">
                <div className="relative">
                  <Search className="absolute left-2 top-1/2 h-3 w-3 -translate-y-1/2 text-neutral-400" />
                  <input
                    type="text"
                    placeholder="Search..."
                    value={publisherSearch}
                    onChange={(e) => setPublisherSearch(e.target.value)}
                    className="w-full rounded border border-neutral-200 bg-neutral-50 py-1 pl-7 pr-2 text-xs focus:border-purple-400 focus:outline-none"
                  />
                </div>
              </div>
              <div className="space-y-0.5 max-h-40 overflow-y-auto">
                {Object.entries(stats.by_publisher)
                  .filter(([publisher]) => publisher.toLowerCase().includes(publisherSearch.toLowerCase()))
                  .sort((a, b) => b[1] - a[1])
                  .slice(0, 50)
                  .map(([publisher, count]) => (
                    <button
                      key={publisher}
                      onClick={() => onFilterChange('publisher', activeFilters.publisher === publisher ? null : publisher)}
                      className={`flex w-full items-center justify-between px-3 py-1.5 text-sm rounded-md ${
                        activeFilters.publisher === publisher
                          ? 'bg-purple-100 text-purple-700'
                          : 'text-neutral-600 hover:bg-neutral-100'
                      }`}
                    >
                      <span className="truncate">{publisher}</span>
                      <span className="text-xs text-neutral-500">{count}</span>
                    </button>
                  ))}
              </div>
            </div>
          )}
        </div>

        {/* Publication Year Filter */}
        <div className="mt-4">
          <button
            onClick={() => setYearExpanded(!yearExpanded)}
            aria-expanded={yearExpanded}
            aria-controls="year-filter"
            className="flex w-full items-center gap-2 px-3 py-1.5 text-xs font-semibold uppercase tracking-wider text-neutral-500"
          >
            {yearExpanded ? (
              <ChevronDown className="h-3 w-3" />
            ) : (
              <ChevronRight className="h-3 w-3" />
            )}
            <Calendar className="h-3 w-3" />
            Publication Year
          </button>

          {yearExpanded && (
            <div id="year-filter" className="mt-2 px-3 space-y-2">
              <div className="flex items-center gap-2">
                <input
                  type="number"
                  placeholder="From"
                  value={activeFilters.publication_year_min || ''}
                  onChange={(e) => onFilterChange('publication_year_min', e.target.value || null)}
                  className="w-full rounded border border-neutral-200 bg-neutral-50 px-2 py-1 text-xs focus:border-purple-400 focus:outline-none"
                />
                <span className="text-neutral-400">-</span>
                <input
                  type="number"
                  placeholder="To"
                  value={activeFilters.publication_year_max || ''}
                  onChange={(e) => onFilterChange('publication_year_max', e.target.value || null)}
                  className="w-full rounded border border-neutral-200 bg-neutral-50 px-2 py-1 text-xs focus:border-purple-400 focus:outline-none"
                />
              </div>
            </div>
          )}
        </div>

        {/* Adventure Filters */}
        <div className="mt-4">
          <button
            onClick={() => setAdventureExpanded(!adventureExpanded)}
            aria-expanded={adventureExpanded}
            aria-controls="adventure-filters"
            className="flex w-full items-center gap-2 px-3 py-1.5 text-xs font-semibold uppercase tracking-wider text-neutral-500"
          >
            {adventureExpanded ? (
              <ChevronDown className="h-3 w-3" />
            ) : (
              <ChevronRight className="h-3 w-3" />
            )}
            <Swords className="h-3 w-3" />
            Adventure Filters
          </button>

          {adventureExpanded && (
            <div id="adventure-filters" className="mt-2 px-3 space-y-3">
              <div>
                <label className="text-xs text-neutral-500 mb-1 block">Level Range</label>
                <div className="flex items-center gap-2">
                  <input
                    type="number"
                    placeholder="Min"
                    min="1"
                    max="20"
                    value={activeFilters.level_min || ''}
                    onChange={(e) => onFilterChange('level_min', e.target.value || null)}
                    className="w-full rounded border border-neutral-200 bg-neutral-50 px-2 py-1 text-xs focus:border-purple-400 focus:outline-none"
                  />
                  <span className="text-neutral-400">-</span>
                  <input
                    type="number"
                    placeholder="Max"
                    min="1"
                    max="20"
                    value={activeFilters.level_max || ''}
                    onChange={(e) => onFilterChange('level_max', e.target.value || null)}
                    className="w-full rounded border border-neutral-200 bg-neutral-50 px-2 py-1 text-xs focus:border-purple-400 focus:outline-none"
                  />
                </div>
              </div>

              <div>
                <label className="text-xs text-neutral-500 mb-1 block">Party Size</label>
                <div className="flex items-center gap-2">
                  <input
                    type="number"
                    placeholder="Min"
                    min="1"
                    max="10"
                    value={activeFilters.party_size_min || ''}
                    onChange={(e) => onFilterChange('party_size_min', e.target.value || null)}
                    className="w-full rounded border border-neutral-200 bg-neutral-50 px-2 py-1 text-xs focus:border-purple-400 focus:outline-none"
                  />
                  <span className="text-neutral-400">-</span>
                  <input
                    type="number"
                    placeholder="Max"
                    min="1"
                    max="10"
                    value={activeFilters.party_size_max || ''}
                    onChange={(e) => onFilterChange('party_size_max', e.target.value || null)}
                    className="w-full rounded border border-neutral-200 bg-neutral-50 px-2 py-1 text-xs focus:border-purple-400 focus:outline-none"
                  />
                </div>
              </div>

              <div>
                <label className="text-xs text-neutral-500 mb-1 block">Estimated Runtime</label>
                <input
                  type="text"
                  placeholder="e.g., 4-6 hours"
                  value={activeFilters.estimated_runtime || ''}
                  onChange={(e) => onFilterChange('estimated_runtime', e.target.value || null)}
                  className="w-full rounded border border-neutral-200 bg-neutral-50 px-2 py-1 text-xs focus:border-purple-400 focus:outline-none"
                />
              </div>
            </div>
          )}
        </div>
      </nav>

      <div className="border-t border-neutral-200 p-2 space-y-1">
        <button
          onClick={() => onViewChange('campaigns')}
          aria-current={activeView === 'campaigns' ? 'page' : undefined}
          className={`flex w-full items-center gap-3 rounded-lg px-3 py-2 text-left text-sm ${
            activeView === 'campaigns'
              ? 'bg-purple-100 text-purple-700'
              : 'text-neutral-700 hover:bg-neutral-100'
          }`}
        >
          <BookOpen className="h-4 w-4" aria-hidden="true" />
          Campaigns
        </button>
        <button
          onClick={() => onViewChange('library-management')}
          aria-current={activeView === 'library-management' ? 'page' : undefined}
          className={`flex w-full items-center gap-3 rounded-lg px-3 py-2 text-left text-sm ${
            activeView === 'library-management'
              ? 'bg-purple-100 text-purple-700'
              : 'text-neutral-700 hover:bg-neutral-100'
          }`}
        >
          <HardDrive className="h-4 w-4" aria-hidden="true" />
          Library Management
        </button>
        <button
          onClick={() => onViewChange('queue')}
          aria-current={activeView === 'queue' ? 'page' : undefined}
          className={`flex w-full items-center gap-3 rounded-lg px-3 py-2 text-left text-sm ${
            activeView === 'queue'
              ? 'bg-purple-100 text-purple-700'
              : 'text-neutral-700 hover:bg-neutral-100'
          }`}
        >
          <ListTodo className="h-4 w-4" aria-hidden="true" />
          Processing Queue
        </button>
        <button
          onClick={() => onViewChange('tools')}
          aria-current={activeView === 'tools' ? 'page' : undefined}
          className={`flex w-full items-center gap-3 rounded-lg px-3 py-2 text-left text-sm ${
            activeView === 'tools'
              ? 'bg-purple-100 text-purple-700'
              : 'text-neutral-700 hover:bg-neutral-100'
          }`}
        >
          <Wrench className="h-4 w-4" aria-hidden="true" />
          Tools
        </button>
        <button
          onClick={() => onViewChange('settings')}
          aria-current={activeView === 'settings' ? 'page' : undefined}
          className={`flex w-full items-center gap-3 rounded-lg px-3 py-2 text-left text-sm ${
            activeView === 'settings'
              ? 'bg-purple-100 text-purple-700'
              : 'text-neutral-700 hover:bg-neutral-100'
          }`}
        >
          <Settings className="h-4 w-4" aria-hidden="true" />
          Settings
        </button>
      </div>

      <div className="border-t border-neutral-200 p-4">
        {stats && (
          <div className="space-y-1 text-xs text-neutral-500">
            <p>{stats.total_products} products</p>
            <p>{stats.total_pages.toLocaleString()} pages</p>
            <p>{formatBytes(stats.total_size_bytes)}</p>
          </div>
        )}
      </div>

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
    </aside>
  );
}
