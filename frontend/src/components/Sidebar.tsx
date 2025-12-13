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
} from 'lucide-react';
import apiClient from '../api/client';

interface Collection {
  id: number;
  name: string;
  description: string | null;
  color: string | null;
  icon: string | null;
  product_count: number;
}

interface Tag {
  id: number;
  name: string;
  category: string | null;
  color: string | null;
  product_count: number;
}

interface LibraryStats {
  total_products: number;
  total_pages: number;
  total_size_bytes: number;
  by_system: Record<string, number>;
  by_type: Record<string, number>;
}

interface SidebarProps {
  activeView: string;
  onViewChange: (view: string) => void;
  onCollectionSelect: (id: number | null) => void;
  onTagSelect: (id: number | null) => void;
  selectedCollection: number | null;
  selectedTag: number | null;
}

export function Sidebar({
  activeView,
  onViewChange,
  onCollectionSelect,
  onTagSelect,
  selectedCollection,
  selectedTag,
}: SidebarProps) {
  const [collectionsExpanded, setCollectionsExpanded] = useState(true);
  const [tagsExpanded, setTagsExpanded] = useState(false);
  const [systemsExpanded, setSystemsExpanded] = useState(false);

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
      const res = await apiClient.get<Tag[]>('/tags');
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
          <button
            onClick={() => setCollectionsExpanded(!collectionsExpanded)}
            aria-expanded={collectionsExpanded}
            aria-controls="collections-list"
            className="flex w-full items-center gap-2 px-3 py-1.5 text-xs font-semibold uppercase tracking-wider text-neutral-500"
          >
            {collectionsExpanded ? (
              <ChevronDown className="h-3 w-3" />
            ) : (
              <ChevronRight className="h-3 w-3" />
            )}
            Collections
          </button>

          {collectionsExpanded && (
            <div id="collections-list" className="mt-1 space-y-0.5" role="list">
              {collections?.map((collection) => (
                <button
                  key={collection.id}
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
                    className="h-4 w-4"
                    style={{ color: collection.color || undefined }}
                  />
                  <span className="truncate">{collection.name}</span>
                  <span className="ml-auto text-xs text-neutral-500">
                    {collection.product_count}
                  </span>
                </button>
              ))}
              {(!collections || collections.length === 0) && (
                <p className="px-3 py-2 text-xs text-neutral-400">No collections yet</p>
              )}
            </div>
          )}
        </div>

        <div className="mt-4">
          <button
            onClick={() => setTagsExpanded(!tagsExpanded)}
            aria-expanded={tagsExpanded}
            aria-controls="tags-list"
            className="flex w-full items-center gap-2 px-3 py-1.5 text-xs font-semibold uppercase tracking-wider text-neutral-500"
          >
            {tagsExpanded ? (
              <ChevronDown className="h-3 w-3" />
            ) : (
              <ChevronRight className="h-3 w-3" />
            )}
            Tags
          </button>

          {tagsExpanded && (
            <div id="tags-list" className="mt-1 space-y-0.5" role="list">
              {tags?.map((tag) => (
                <button
                  key={tag.id}
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
                  <Tag className="h-4 w-4" style={{ color: tag.color || undefined }} />
                  <span className="truncate">{tag.name}</span>
                  <span className="ml-auto text-xs text-neutral-500">{tag.product_count}</span>
                </button>
              ))}
              {(!tags || tags.length === 0) && (
                <p className="px-3 py-2 text-xs text-neutral-400">No tags yet</p>
              )}
            </div>
          )}
        </div>

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
            Game Systems
          </button>

          {systemsExpanded && stats && (
            <div id="systems-list" className="mt-1 space-y-0.5" role="list">
              {Object.entries(stats.by_system)
                .sort((a, b) => b[1] - a[1])
                .map(([system, count]) => (
                  <div
                    key={system}
                    className="flex items-center justify-between px-3 py-1.5 text-sm text-neutral-600"
                  >
                    <span className="truncate">{system}</span>
                    <span className="text-xs text-neutral-500">{count}</span>
                  </div>
                ))}
            </div>
          )}
        </div>
      </nav>

      <div className="border-t border-neutral-200 p-2 space-y-1">
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
    </aside>
  );
}
