import { useState, useMemo, useEffect, useCallback } from 'react';
import { Search, Grid, List, RefreshCw, X, SlidersHorizontal } from 'lucide-react';
import { useQuery, useMutation } from '@tanstack/react-query';
import { useProducts } from '../hooks/useProducts';
import { ProductGrid } from '../components/ProductGrid';
import { ProductDetail } from '../components/ProductDetail';
import { BulkEditModal } from '../components/BulkEditModal';
import { searchProducts } from '../api/search';
import { getSemanticSearchStatus, semanticSearch } from '../api/semantic';
import { useDebounce } from '../hooks/useDebounce';
import type { Product, ProductListResponse } from '../types/product';
import type { ProductFilters } from '../api/products';
import { pauseQueue, resumeQueue, contributeProduct } from '../api/products';

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
  const [searchSemantic, setSearchSemantic] = useState(false);
  const [activeSearch, setActiveSearch] = useState('');
  const [selectedIds, setSelectedIds] = useState<Set<number>>(new Set());
  const [showBulkEdit, setShowBulkEdit] = useState(false);
  const [queuePaused, setQueuePaused] = useState(false);
  // When the user removes an interpretation chip, we re-issue the search with
  // interpret=false plus the remaining interpreted filters made explicit.
  const [interpretDisabled, setInterpretDisabled] = useState(false);
  const [chipFilters, setChipFilters] = useState<Partial<ProductFilters>>({});

  const debouncedSearch = useDebounce(searchInput, 300);

  // Live title search: update filters when debounced input changes
  useEffect(() => {
    if (!searchContent && !searchSemantic) {
      setFilters(prev => ({ ...prev, search: debouncedSearch || undefined }));
    }
  }, [debouncedSearch, searchContent, searchSemantic]);

  const { data, isLoading, error, refetch, isFetching, fetchNextPage, hasNextPage, isFetchingNextPage } = useProducts(effectiveFilters);

  // Content search query
  const {
    data: searchData,
    isLoading: searchLoading,
    error: searchError,
  } = useQuery({
    queryKey: ['search', activeSearch, searchContent],
    queryFn: () => searchProducts({ q: activeSearch, search_content: searchContent }),
    enabled: activeSearch.length > 0 && !searchSemantic,
    staleTime: 60000,
  });

  // Semantic search status
  const { data: semanticStatus } = useQuery({
    queryKey: ['semantic-search-status'],
    queryFn: getSemanticSearchStatus,
    staleTime: 300000,
  });

  // Number of semantic results to request (adjustable via the Show selector + Load more)
  const [resultLimit, setResultLimit] = useState(50);

  // Semantic search query
  const {
    data: semanticData,
    isLoading: semanticLoading,
    isFetching: semanticFetching,
    error: semanticError,
  } = useQuery({
    queryKey: ['semantic-search', activeSearch, effectiveFilters, chipFilters, interpretDisabled, resultLimit],
    queryFn: () =>
      semanticSearch(activeSearch, resultLimit, { ...effectiveFilters, ...chipFilters }, { interpret: !interpretDisabled }),
    enabled: activeSearch.length > 0 && searchSemantic,
    staleTime: 60000,
  });

  // Build score map from semantic results
  const scoreMap = useMemo(() => {
    if (!semanticData?.results) return undefined;
    const map: Record<number, number> = {};
    for (const r of semanticData.results) {
      map[r.id] = r.score;
    }
    return map;
  }, [semanticData]);

  // Build snippet map (page-prefixed) from semantic results
  const snippetMap = useMemo(() => {
    if (!semanticData?.results) return undefined;
    const map: Record<number, string> = {};
    for (const r of semanticData.results) {
      if (r.snippet) {
        map[r.id] = r.matched_page ? `p. ${r.matched_page}: ${r.snippet}` : r.snippet;
      }
    }
    return map;
  }, [semanticData]);

  const handleContentToggle = () => {
    setSearchContent(!searchContent);
    setSearchSemantic(false);
  };

  const handleSemanticToggle = () => {
    setSearchSemantic(!searchSemantic);
    setSearchContent(false);
  };

  const handleSearch = (e: React.FormEvent) => {
    e.preventDefault();
    setInterpretDisabled(false);
    setChipFilters({});
    setResultLimit(50);
    if (searchContent || searchSemantic) {
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
    setInterpretDisabled(false);
    setChipFilters({});
    setResultLimit(50);
  };

  // Flatten infinite query pages into a single array
  const allProducts = useMemo(
    () => data?.pages.flatMap((page: ProductListResponse) => page.items) ?? [],
    [data]
  );
  const totalCount = data?.pages[0]?.total ?? 0;

  // Determine which products to show
  const isSearching = activeSearch.length > 0;
  const displayProducts = isSearching
    ? (searchSemantic ? (semanticData?.results || []) : (searchData?.results || []))
    : allProducts;
  const displayLoading = isSearching
    ? (searchSemantic ? semanticLoading : searchLoading)
    : isLoading;
  const displayError = isSearching
    ? (searchSemantic ? semanticError : searchError)
    : error;

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

  const contributeMutation = useMutation({
    mutationFn: async (productIds: number[]) => {
      const results = await Promise.allSettled(
        productIds.map(id => contributeProduct(id))
      );
      const succeeded = results.filter(r => r.status === 'fulfilled').length;
      const failed = results.length - succeeded;
      return { succeeded, failed };
    },
    onSuccess: ({ succeeded, failed }) => {
      clearSelection();
      if (failed > 0) {
        console.warn(`Codex: ${succeeded} sent, ${failed} failed`);
      }
    },
  });

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
                  placeholder={searchSemantic ? 'Describe what you\'re looking for, e.g. "undead adventure for level 3 characters"' : searchContent ? 'Search in PDF content...' : 'Search titles...'}
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
              onClick={handleContentToggle}
              className="flex items-center gap-2 rounded-full px-4 py-2 text-sm font-medium whitespace-nowrap transition-colors"
              style={{
                backgroundColor: searchContent ? 'var(--color-accent-light)' : 'var(--color-surface-raised)',
                color: searchContent ? 'var(--color-accent)' : 'var(--color-text-secondary)',
                border: `1px solid ${searchContent ? 'var(--color-accent)' : 'var(--color-border)'}`,
              }}
            >
              Content
            </button>

            {/* Semantic search toggle */}
            <button
              onClick={handleSemanticToggle}
              disabled={!semanticStatus?.enabled}
              className="flex items-center gap-2 rounded-full px-4 py-2 text-sm font-medium whitespace-nowrap transition-colors disabled:opacity-40 disabled:cursor-not-allowed"
              style={{
                backgroundColor: searchSemantic ? 'var(--color-accent-light)' : 'var(--color-surface-raised)',
                color: searchSemantic ? 'var(--color-accent)' : 'var(--color-text-secondary)',
                border: `1px solid ${searchSemantic ? 'var(--color-accent)' : 'var(--color-border)'}`,
              }}
              title={!semanticStatus?.enabled ? 'Configure a search provider in Settings to enable semantic search' : 'Search with AI embeddings'}
            >
              Semantic
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
                      {searchSemantic && ' (semantic search)'}
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
                  <div className="flex items-center gap-3">
                    {searchSemantic && (
                      <label
                        className="flex items-center gap-1.5 text-sm"
                        style={{ color: 'var(--color-text-secondary)' }}
                      >
                        Show
                        <select
                          value={resultLimit}
                          onChange={(e) => setResultLimit(Number(e.target.value))}
                          className="rounded px-1.5 py-0.5 text-sm cursor-pointer"
                          style={{
                            backgroundColor: 'var(--color-surface-raised)',
                            color: 'var(--color-text-primary)',
                            border: '1px solid var(--color-border)',
                          }}
                        >
                          {Array.from(new Set([20, 50, 100, 200, resultLimit]))
                            .sort((a, b) => a - b)
                            .map((n) => (
                              <option key={n} value={n}>
                                {n}
                              </option>
                            ))}
                        </select>
                      </label>
                    )}
                    <button
                      onClick={clearSearch}
                      className="text-sm font-medium"
                      style={{ color: 'var(--color-accent)' }}
                    >
                      Clear search
                    </button>
                  </div>
                )}
              </div>
              {searchSemantic && semanticData?.interpretation && !interpretDisabled && (() => {
                const interp = semanticData.interpretation;
                // System/type are auto-applied as lenient filters and removable.
                const chips: { key: string; label: string; asFilters: Partial<ProductFilters> }[] = [];
                if (interp.game_system) {
                  chips.push({ key: 'system', label: `System: ${interp.game_system}`, asFilters: { game_system: interp.game_system } });
                }
                if (interp.product_type) {
                  chips.push({ key: 'type', label: `Type: ${interp.product_type}`, asFilters: { product_type: interp.product_type } });
                }
                // Level is detected but NOT auto-applied (only ~16% of the library
                // has level data, so filtering on it wrongly drops good matches).
                // Offer it as a one-click opt-in filter instead.
                const hasLevel = interp.level_min !== null || interp.level_max !== null;
                const levelAlreadyApplied = Boolean(effectiveFilters.level_min || effectiveFilters.level_max);
                const showLevel = hasLevel && !levelAlreadyApplied;
                const levelLabel = interp.level_min === interp.level_max
                  ? `Level ${interp.level_min}`
                  : `Levels ${interp.level_min ?? '?'}–${interp.level_max ?? '?'}`;
                if (chips.length === 0 && !showLevel) return null;
                const removeChip = (removedKey: string) => {
                  const remaining = chips.filter((c) => c.key !== removedKey);
                  setChipFilters(Object.assign({}, ...remaining.map((c) => c.asFilters)));
                  setInterpretDisabled(true);
                };
                const applyLevel = () => {
                  setFilters((prev) => ({
                    ...prev,
                    level_min: interp.level_min != null ? String(interp.level_min) : undefined,
                    level_max: interp.level_max != null ? String(interp.level_max) : undefined,
                  }));
                };
                return (
                  <div className="mb-3 flex flex-wrap items-center gap-2">
                    <span className="text-xs" style={{ color: 'var(--color-text-secondary)' }}>
                      Interpreted:
                    </span>
                    {chips.map((chip) => (
                      <button
                        key={chip.key}
                        onClick={() => removeChip(chip.key)}
                        className="flex items-center gap-1 rounded-full px-2.5 py-0.5 text-xs"
                        style={{
                          backgroundColor: 'var(--color-surface-raised)',
                          color: 'var(--color-text-primary)',
                          border: '1px solid var(--color-border)',
                        }}
                        title="Remove this filter and search again"
                      >
                        {chip.label}
                        <span aria-hidden>×</span>
                      </button>
                    ))}
                    {showLevel && (
                      <button
                        onClick={applyLevel}
                        className="flex items-center gap-1 rounded-full px-2.5 py-0.5 text-xs"
                        style={{
                          backgroundColor: 'transparent',
                          color: 'var(--color-accent)',
                          border: '1px dashed var(--color-accent)',
                        }}
                        title="Detected in your query — click to add it as a level filter"
                      >
                        <span aria-hidden>+</span>
                        {levelLabel}
                      </button>
                    )}
                  </div>
                );
              })()}
              {searchSemantic && semanticData && semanticData.total_matches < 3 && activeSearch && (
                <div
                  className="mb-4 rounded-lg p-3 text-sm"
                  style={{
                    backgroundColor: 'var(--color-surface-raised)',
                    color: 'var(--color-text-secondary)',
                    border: '1px solid var(--color-border)',
                  }}
                >
                  <p className="font-medium" style={{ color: 'var(--color-text-primary)' }}>
                    Few results found. Try:
                  </p>
                  <ul className="mt-1 ml-4 list-disc space-y-0.5">
                    <li>Describing the content differently (e.g., "horror themed dungeon with zombies")</li>
                    <li>Using the filter drawer to narrow by game system first, then searching</li>
                    <li>Switching to Content search for exact phrase matching</li>
                  </ul>
                </div>
              )}
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
                scoreMap={searchSemantic ? scoreMap : undefined}
                snippetMap={searchSemantic ? snippetMap : undefined}
              />
              {searchSemantic &&
                semanticData &&
                semanticData.results.length >= resultLimit &&
                resultLimit < 200 && (
                  <div className="mt-4 flex justify-center">
                    <button
                      onClick={() => setResultLimit((n) => Math.min(n + 50, 200))}
                      disabled={semanticFetching}
                      className="rounded-lg px-4 py-2 text-sm font-medium disabled:opacity-50"
                      style={{
                        backgroundColor: 'var(--color-surface-raised)',
                        color: 'var(--color-text-primary)',
                        border: '1px solid var(--color-border)',
                      }}
                    >
                      {semanticFetching ? 'Loading…' : 'Load more'}
                    </button>
                  </div>
                )}
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
            onClick={() => contributeMutation.mutate(Array.from(selectedIds))}
            disabled={contributeMutation.isPending}
            className="rounded-md px-4 py-2 text-sm font-medium text-white disabled:opacity-50"
            style={{ backgroundColor: 'var(--color-success)' }}
            title="Send selected products to the Codex community database"
          >
            {contributeMutation.isPending ? 'Sending...' : 'Send to Codex'}
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
          onClose={() => {
            setShowBulkEdit(false);
            if (queuePaused) {
              resumeQueue();
              setQueuePaused(false);
            }
          }}
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
