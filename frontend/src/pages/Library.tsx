import { useState, useMemo, useEffect, useCallback } from 'react';
import { Search, Grid, List, RefreshCw, X, SlidersHorizontal } from 'lucide-react';
import { useQuery } from '@tanstack/react-query';
import { useProducts } from '../hooks/useProducts';
import { ProductGrid } from '../components/ProductGrid';
import { ProductDetail } from '../components/ProductDetail';
import { BulkEditModal } from '../components/BulkEditModal';
import { searchProducts } from '../api/search';
import { useDebounce } from '../hooks/useDebounce';
import type { Product, ProductListResponse } from '../types/product';
import type { ProductFilters } from '../api/products';
import { pauseQueue, resumeQueue } from '../api/products';

interface LibraryProps {
  selectedCollection?: number | null;
  selectedTag?: number | null;
  sidebarFilters?: Partial<ProductFilters>;
  onOpenFilters?: () => void;
  activeFilterCount?: number;
}

export function Library({
  selectedCollection,
  selectedTag,
  sidebarFilters = {},
  onOpenFilters,
  activeFilterCount = 0,
}: LibraryProps) {
  const [filters, setFilters] = useState<ProductFilters>({
    per_page: 24,
    sort: 'title',
    order: 'asc',
  });

  // Merge collection/tag/sidebar filters with local filters
  const effectiveFilters = useMemo(() => {
    const merged: ProductFilters = { ...filters, ...sidebarFilters };
    if (selectedCollection) {
      merged.collection = selectedCollection;
    }
    if (selectedTag) {
      merged.tags = String(selectedTag);
    }
    return merged;
  }, [filters, selectedCollection, selectedTag, sidebarFilters]);
  const [searchInput, setSearchInput] = useState('');
  const [viewMode, setViewMode] = useState<'grid' | 'list'>('grid');
  const [selectedProduct, setSelectedProduct] = useState<Product | null>(null);
  const [searchContent, setSearchContent] = useState(false);
  const [activeSearch, setActiveSearch] = useState('');
  const [selectedIds, setSelectedIds] = useState<Set<number>>(new Set());
  const [showBulkEdit, setShowBulkEdit] = useState(false);
  const [queuePaused, setQueuePaused] = useState(false);

  const debouncedSearch = useDebounce(searchInput, 300);

  // Live title search: update filters when debounced input changes
  useEffect(() => {
    if (!searchContent) {
      setFilters(prev => ({ ...prev, search: debouncedSearch || undefined }));
    }
  }, [debouncedSearch, searchContent]);

  const { data, isLoading, error, refetch, isFetching, fetchNextPage, hasNextPage, isFetchingNextPage } = useProducts(effectiveFilters);

  // Content search query
  const {
    data: searchData,
    isLoading: searchLoading,
    error: searchError,
  } = useQuery({
    queryKey: ['search', activeSearch, searchContent],
    queryFn: () => searchProducts({ q: activeSearch, search_content: searchContent }),
    enabled: activeSearch.length > 0,
    staleTime: 60000,
  });

  const handleSearch = (e: React.FormEvent) => {
    e.preventDefault();
    if (searchContent) {
      setActiveSearch(searchInput);
    } else {
      setFilters((prev) => ({ ...prev, search: searchInput }));
      setActiveSearch('');
    }
  };

  const clearSearch = () => {
    setSearchInput('');
    setActiveSearch('');
    setFilters((prev) => ({ ...prev, search: undefined }));
  };

  // Flatten infinite query pages into a single array
  const allProducts = useMemo(
    () => data?.pages.flatMap((page: ProductListResponse) => page.items) ?? [],
    [data]
  );
  const totalCount = data?.pages[0]?.total ?? 0;

  // Determine which products to show
  const isSearching = activeSearch.length > 0;
  const displayProducts = isSearching ? (searchData?.results || []) : allProducts;
  const displayLoading = isSearching ? searchLoading : isLoading;
  const displayError = isSearching ? searchError : error;

  const handleProductClick = (product: Product) => {
    setSelectedProduct(product);
  };

  const handleSelectionChange = useCallback((productId: number, selected: boolean) => {
    setSelectedIds(prev => {
      const next = new Set(prev);
      if (selected) {
        next.add(productId);
      } else {
        next.delete(productId);
      }
      return next;
    });
  }, []);

  const handleSelectAll = useCallback(() => {
    if (selectedIds.size === displayProducts.length) {
      setSelectedIds(new Set());
    } else {
      setSelectedIds(new Set(displayProducts.map(p => p.id)));
    }
  }, [displayProducts, selectedIds.size]);

  const clearSelection = useCallback(() => {
    setSelectedIds(new Set());
  }, []);

  const handleTogglePause = useCallback(async () => {
    if (queuePaused) {
      await resumeQueue();
      setQueuePaused(false);
    } else {
      await pauseQueue();
      setQueuePaused(true);
    }
  }, [queuePaused]);

  return (
    <div className="flex h-full flex-col overflow-hidden">
      {/* Header / Search Bar */}
      <header
        className="sticky top-0 z-10 border-b shadow-sm"
        style={{
          backgroundColor: 'var(--color-surface)',
          borderColor: 'var(--color-border)',
        }}
      >
        <div className="px-6 py-4">
          <div className="flex items-center gap-4">
            {/* Search input */}
            <form onSubmit={handleSearch} className="flex-1 max-w-2xl">
              <div className="relative">
                <Search
                  className="absolute left-4 top-1/2 -translate-y-1/2"
                  size={20}
                  style={{ color: 'var(--color-text-secondary)' }}
                />
                <input
                  type="search"
                  placeholder={searchContent ? 'Search in PDF content...' : 'Search titles...'}
                  value={searchInput}
                  onChange={(e) => setSearchInput(e.target.value)}
                  className="input pl-12 pr-12"
                  style={{ height: '48px', fontSize: '18px' }}
                />
                {(searchInput || activeSearch) && (
                  <button
                    type="button"
                    onClick={clearSearch}
                    className="absolute right-4 top-1/2 -translate-y-1/2 rounded-md p-1 transition-colors"
                    style={{ color: 'var(--color-text-secondary)' }}
                  >
                    <X size={18} />
                  </button>
                )}
              </div>
            </form>

            {/* Search content toggle */}
            <button
              onClick={() => setSearchContent(!searchContent)}
              className="flex items-center gap-2 rounded-full px-4 py-2 text-sm font-medium whitespace-nowrap transition-colors"
              style={{
                backgroundColor: searchContent ? 'var(--color-accent-light)' : 'var(--color-surface-raised)',
                color: searchContent ? 'var(--color-accent)' : 'var(--color-text-secondary)',
                border: `1px solid ${searchContent ? 'var(--color-accent)' : 'var(--color-border)'}`,
              }}
            >
              Content
            </button>

            {/* Right controls */}
            <div className="flex items-center gap-2">
              {/* Filter button */}
              <button
                onClick={onOpenFilters}
                className="relative flex items-center gap-2 rounded-md px-3 transition-colors"
                style={{
                  height: '44px',
                  backgroundColor: activeFilterCount > 0 ? 'var(--color-accent-light)' : 'transparent',
                  color: activeFilterCount > 0 ? 'var(--color-accent)' : 'var(--color-text-secondary)',
                  border: `1px solid ${activeFilterCount > 0 ? 'var(--color-accent)' : 'var(--color-border)'}`,
                }}
                title="Open filters"
              >
                <SlidersHorizontal size={18} />
                <span className="text-sm font-medium hidden sm:inline">Filters</span>
                {activeFilterCount > 0 && (
                  <span
                    className="flex items-center justify-center min-w-[20px] h-5 rounded-full text-xs font-bold text-white"
                    style={{ backgroundColor: 'var(--color-accent)' }}
                  >
                    {activeFilterCount}
                  </span>
                )}
              </button>

              {/* View toggle */}
              <div
                className="flex rounded-md overflow-hidden"
                style={{ border: '1px solid var(--color-border)' }}
              >
                <button
                  onClick={() => setViewMode('grid')}
                  className="flex items-center justify-center transition-colors"
                  style={{
                    width: '44px',
                    height: '44px',
                    backgroundColor: viewMode === 'grid' ? 'var(--color-accent-light)' : 'transparent',
                    color: viewMode === 'grid' ? 'var(--color-accent)' : 'var(--color-text-secondary)',
                  }}
                  title="Grid view"
                >
                  <Grid size={18} />
                </button>
                <button
                  onClick={() => setViewMode('list')}
                  className="flex items-center justify-center transition-colors"
                  style={{
                    width: '44px',
                    height: '44px',
                    backgroundColor: viewMode === 'list' ? 'var(--color-accent-light)' : 'transparent',
                    color: viewMode === 'list' ? 'var(--color-accent)' : 'var(--color-text-secondary)',
                    borderLeft: '1px solid var(--color-border)',
                  }}
                  title="List view"
                >
                  <List size={18} />
                </button>
              </div>

              {/* Refresh button */}
              <button
                onClick={() => refetch()}
                disabled={isFetching}
                className="flex items-center justify-center rounded-md transition-colors disabled:opacity-50"
                style={{
                  width: '44px',
                  height: '44px',
                  color: 'var(--color-text-secondary)',
                  border: '1px solid var(--color-border)',
                }}
                title="Refresh"
              >
                <RefreshCw size={18} className={isFetching ? 'animate-spin' : ''} />
              </button>
            </div>
          </div>
        </div>
      </header>

      {/* Main content */}
      <main className="flex-1 overflow-auto px-6 py-6" style={{ backgroundColor: 'var(--color-bg)' }}>
        <div className="mx-auto max-w-7xl">
          {displayLoading ? (
            <div className="flex items-center justify-center py-16">
              <div
                className="h-8 w-8 animate-spin rounded-full border-4"
                style={{
                  borderColor: 'var(--color-border)',
                  borderTopColor: 'var(--color-accent)',
                }}
              />
            </div>
          ) : displayError ? (
            <div
              className="rounded-lg border p-4 text-center text-base"
              style={{
                borderColor: 'var(--color-danger)',
                backgroundColor: 'rgba(224, 49, 49, 0.05)',
                color: 'var(--color-danger)',
              }}
            >
              Error loading products. Make sure the backend is running.
            </div>
          ) : displayProducts.length > 0 || data ? (
            <>
              <div className="mb-4 flex items-center justify-between">
                <div className="flex items-center gap-3">
                  <input
                    type="checkbox"
                    checked={displayProducts.length > 0 && selectedIds.size === displayProducts.length}
                    ref={(el) => {
                      if (el) el.indeterminate = selectedIds.size > 0 && selectedIds.size < displayProducts.length;
                    }}
                    onChange={handleSelectAll}
                    className="h-5 w-5 rounded cursor-pointer accent-[var(--color-accent)]"
                    title="Select all"
                  />
                <p className="text-base" style={{ color: 'var(--color-text-secondary)' }}>
                  {isSearching ? (
                    <>
                      {displayProducts.length} result{displayProducts.length !== 1 ? 's' : ''} for "{activeSearch}"
                      {searchContent && ' (content search)'}
                    </>
                  ) : (
                    <>
                      {totalCount} product{totalCount !== 1 ? 's' : ''}
                      {activeFilterCount > 0 && ' (filtered)'}
                    </>
                  )}
                </p>
                </div>
                {isSearching && (
                  <button
                    onClick={clearSearch}
                    className="text-sm font-medium"
                    style={{ color: 'var(--color-accent)' }}
                  >
                    Clear search
                  </button>
                )}
              </div>
              <ProductGrid
                products={displayProducts}
                onProductClick={handleProductClick}
                viewMode={viewMode}
                hasNextPage={!isSearching && hasNextPage}
                isFetchingNextPage={isFetchingNextPage}
                fetchNextPage={fetchNextPage}
                selectable={true}
                selectedIds={selectedIds}
                onSelectionChange={handleSelectionChange}
              />
            </>
          ) : null}
        </div>
      </main>

      {/* Floating bulk action toolbar */}
      {selectedIds.size > 0 && (
        <div
          className="fixed bottom-6 left-1/2 -translate-x-1/2 z-50 flex items-center gap-4 rounded-lg px-6 py-3 shadow-xl"
          style={{
            backgroundColor: 'var(--color-surface)',
            border: '1px solid var(--color-border)',
          }}
        >
          <span className="text-base font-medium" style={{ color: 'var(--color-text-primary)' }}>
            {selectedIds.size} selected
          </span>
          <button
            onClick={handleTogglePause}
            className="rounded-md px-4 py-2 text-sm font-medium"
            style={{
              backgroundColor: queuePaused ? 'var(--color-warning)' : 'var(--color-surface-raised)',
              color: queuePaused ? 'white' : 'var(--color-text-secondary)',
              border: queuePaused ? 'none' : '1px solid var(--color-border)',
            }}
          >
            {queuePaused ? 'Queue Paused' : 'Pause Queue'}
          </button>
          <button
            onClick={() => setShowBulkEdit(true)}
            className="rounded-md px-4 py-2 text-sm font-medium text-white"
            style={{ backgroundColor: 'var(--color-accent)' }}
          >
            Edit Selected
          </button>
          <button
            onClick={clearSelection}
            className="rounded-md px-4 py-2 text-sm font-medium"
            style={{
              color: 'var(--color-text-secondary)',
              border: '1px solid var(--color-border)',
            }}
          >
            Clear
          </button>
        </div>
      )}

      {showBulkEdit && (
        <BulkEditModal
          selectedProducts={displayProducts.filter(p => selectedIds.has(p.id))}
          onClose={() => setShowBulkEdit(false)}
          onComplete={clearSelection}
        />
      )}

      {selectedProduct && (
        <ProductDetail
          product={selectedProduct}
          onClose={() => setSelectedProduct(null)}
        />
      )}
    </div>
  );
}
