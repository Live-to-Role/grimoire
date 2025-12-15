import { useState, useMemo } from 'react';
import { Search, Grid, List, RefreshCw, X } from 'lucide-react';
import { useQuery } from '@tanstack/react-query';
import { useProducts } from '../hooks/useProducts';
import { ProductGrid } from '../components/ProductGrid';
import { ProductDetail } from '../components/ProductDetail';
import { searchProducts } from '../api/search';
import type { Product } from '../types/product';
import type { ProductFilters } from '../api/products';

interface LibraryProps {
  selectedCollection?: number | null;
  selectedTag?: number | null;
  sidebarFilters?: Partial<ProductFilters>;
}

export function Library({ selectedCollection, selectedTag, sidebarFilters = {} }: LibraryProps) {
  const [filters, setFilters] = useState<ProductFilters>({
    page: 1,
    per_page: 50,
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

  const { data, isLoading, error, refetch, isFetching } = useProducts(effectiveFilters);

  // Content search query
  const {
    data: searchData,
    isLoading: searchLoading,
    error: searchError,
  } = useQuery({
    queryKey: ['search', activeSearch, searchContent],
    queryFn: () => searchProducts({ q: activeSearch, search_content: searchContent }),
    enabled: activeSearch.length > 0,
  });

  // Count active sidebar filters
  const sidebarFilterCount = Object.keys(sidebarFilters).filter(
    k => !['page', 'per_page', 'sort', 'order'].includes(k)
  ).length;

  const handleSearch = (e: React.FormEvent) => {
    e.preventDefault();
    if (searchContent) {
      setActiveSearch(searchInput);
    } else {
      setFilters((prev) => ({ ...prev, search: searchInput, page: 1 }));
      setActiveSearch('');
    }
  };

  const clearSearch = () => {
    setSearchInput('');
    setActiveSearch('');
    setFilters((prev) => ({ ...prev, search: undefined, page: 1 }));
  };

  // Determine which products to show
  const isSearching = activeSearch.length > 0;
  const displayProducts = isSearching ? (searchData?.results || []) : (data?.items || []);
  const displayLoading = isSearching ? searchLoading : isLoading;
  const displayError = isSearching ? searchError : error;

  const handleProductClick = (product: Product) => {
    setSelectedProduct(product);
  };

  return (
    <div className="flex h-full flex-col overflow-hidden">
      <header className="sticky top-0 z-10 border-b border-neutral-200 bg-white shadow-sm">
        <div className="px-4 py-4">
          <div className="flex items-center justify-between gap-4">
            <form onSubmit={handleSearch} className="flex-1 max-w-xl">
              <div className="flex items-center gap-2">
                <div className="relative flex-1">
                  <Search className="absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-neutral-400" />
                  <input
                    type="search"
                    placeholder={searchContent ? "Search in PDF content..." : "Search titles..."}
                    value={searchInput}
                    onChange={(e) => setSearchInput(e.target.value)}
                    className="w-full rounded-lg border border-neutral-300 bg-neutral-50 py-2 pl-10 pr-4 text-sm focus:border-purple-500 focus:outline-none focus:ring-1 focus:ring-purple-500"
                  />
                  {activeSearch && (
                    <button
                      type="button"
                      onClick={clearSearch}
                      className="absolute right-3 top-1/2 -translate-y-1/2 text-neutral-400 hover:text-neutral-600"
                    >
                      <X className="h-4 w-4" />
                    </button>
                  )}
                </div>
                <label className="flex items-center gap-2 text-sm text-neutral-600 whitespace-nowrap">
                  <input
                    type="checkbox"
                    checked={searchContent}
                    onChange={(e) => setSearchContent(e.target.checked)}
                    className="h-4 w-4 rounded border-neutral-300 text-purple-600 focus:ring-purple-500"
                  />
                  Search content
                </label>
              </div>
            </form>

            <div className="flex items-center gap-2">
              {sidebarFilterCount > 0 && (
                <span className="text-sm text-purple-600">
                  {sidebarFilterCount} filter{sidebarFilterCount > 1 ? 's' : ''} active
                </span>
              )}
              <button
                onClick={() => refetch()}
                disabled={isFetching}
                className="rounded-lg p-2 text-neutral-600 hover:bg-neutral-100 disabled:opacity-50"
                title="Refresh"
              >
                <RefreshCw className={`h-5 w-5 ${isFetching ? 'animate-spin' : ''}`} />
              </button>
              <div className="flex rounded-lg border border-neutral-300">
                <button
                  onClick={() => setViewMode('grid')}
                  className={`rounded-l-lg p-2 ${viewMode === 'grid' ? 'bg-purple-100 text-purple-700' : 'text-neutral-600 hover:bg-neutral-100'}`}
                  title="Grid view"
                >
                  <Grid className="h-5 w-5" />
                </button>
                <button
                  onClick={() => setViewMode('list')}
                  className={`rounded-r-lg p-2 ${viewMode === 'list' ? 'bg-purple-100 text-purple-700' : 'text-neutral-600 hover:bg-neutral-100'}`}
                  title="List view"
                >
                  <List className="h-5 w-5" />
                </button>
              </div>
            </div>
          </div>

        </div>
      </header>

      <main className="flex-1 overflow-auto px-4 py-6">
        <div className="mx-auto max-w-7xl">
          {displayLoading ? (
            <div className="flex items-center justify-center py-16">
              <div className="h-8 w-8 animate-spin rounded-full border-4 border-purple-200 border-t-purple-600" />
            </div>
          ) : displayError ? (
            <div className="rounded-lg border border-red-200 bg-red-50 p-4 text-center text-red-700">
              Error loading products. Make sure the backend is running.
            </div>
          ) : displayProducts.length > 0 || data ? (
            <>
              <div className="mb-4 flex items-center justify-between">
                <p className="text-sm text-neutral-600">
                  {isSearching ? (
                    <>
                      {displayProducts.length} result{displayProducts.length !== 1 ? 's' : ''} for "{activeSearch}"
                      {searchContent && ' (content search)'}
                    </>
                  ) : (
                    <>
                      {data?.total || 0} product{data?.total !== 1 ? 's' : ''}
                      {sidebarFilterCount > 0 && ' (filtered)'}
                    </>
                  )}
                </p>
                {isSearching && (
                  <button
                    onClick={clearSearch}
                    className="text-sm text-purple-600 hover:text-purple-700"
                  >
                    Clear search
                  </button>
                )}
              </div>
              <ProductGrid
                products={displayProducts}
                onProductClick={handleProductClick}
              />
            </>
          ) : null}
        </div>
      </main>

      {selectedProduct && (
        <ProductDetail
          product={selectedProduct}
          onClose={() => setSelectedProduct(null)}
        />
      )}
    </div>
  );
}
