import { useRef, useEffect } from 'react';
import { ProductCard } from './ProductCard';
import type { Product } from '../types/product';

interface ProductGridProps {
  products: Product[];
  onProductClick?: (product: Product) => void;
  viewMode?: 'grid' | 'list';
  hasNextPage?: boolean;
  isFetchingNextPage?: boolean;
  fetchNextPage?: () => void;
  selectable?: boolean;
  selectedIds?: Set<number>;
  onSelectionChange?: (productId: number, selected: boolean) => void;
}

export function ProductGrid({ products, onProductClick, viewMode = 'grid', hasNextPage, isFetchingNextPage, fetchNextPage, selectable, selectedIds, onSelectionChange }: ProductGridProps) {
  const sentinelRef = useRef<HTMLDivElement>(null);

  // Trigger fetch when the sentinel becomes visible in the nearest scrollable ancestor
  useEffect(() => {
    const node = sentinelRef.current;
    if (!node || !hasNextPage || isFetchingNextPage || !fetchNextPage) return;

    // Find the nearest scrollable ancestor to use as root
    let scrollParent: HTMLElement | null = node.parentElement;
    while (scrollParent) {
      const style = getComputedStyle(scrollParent);
      if (style.overflow === 'auto' || style.overflow === 'scroll' ||
          style.overflowY === 'auto' || style.overflowY === 'scroll') {
        break;
      }
      scrollParent = scrollParent.parentElement;
    }

    const observer = new IntersectionObserver(
      (entries) => {
        if (entries[0].isIntersecting) {
          fetchNextPage();
        }
      },
      { root: scrollParent, rootMargin: '400px' }
    );
    observer.observe(node);
    return () => observer.disconnect();
  }, [hasNextPage, isFetchingNextPage, fetchNextPage, products.length]);

  if (products.length === 0) {
    return (
      <div className="flex flex-col items-center justify-center py-16 text-center">
        <div
          className="rounded-full p-4"
          style={{ backgroundColor: 'var(--color-surface-raised)' }}
        >
          <svg
            className="h-12 w-12"
            style={{ color: 'var(--color-text-secondary)' }}
            fill="none"
            viewBox="0 0 24 24"
            stroke="currentColor"
          >
            <path
              strokeLinecap="round"
              strokeLinejoin="round"
              strokeWidth={1.5}
              d="M12 6.253v13m0-13C10.832 5.477 9.246 5 7.5 5S4.168 5.477 3 6.253v13C4.168 18.477 5.754 18 7.5 18s3.332.477 4.5 1.253m0-13C13.168 5.477 14.754 5 16.5 5c1.747 0 3.332.477 4.5 1.253v13C19.832 18.477 18.247 18 16.5 18c-1.746 0-3.332.477-4.5 1.253"
            />
          </svg>
        </div>
        <h3
          className="mt-4 text-xl font-medium"
          style={{ color: 'var(--color-text-primary)' }}
        >
          No products found
        </h3>
        <p
          className="mt-1 text-lg"
          style={{ color: 'var(--color-text-secondary)' }}
        >
          Add a folder to watch or adjust your filters.
        </p>
      </div>
    );
  }

  return (
    <div>
      <div className={viewMode === 'grid'
        ? "grid grid-cols-2 gap-5 md:grid-cols-3 lg:grid-cols-4 2xl:grid-cols-5"
        : "flex flex-col gap-2"
      }>
        {products.map((product) => (
          <ProductCard
            key={product.id}
            product={product}
            onClick={onProductClick}
            viewMode={viewMode}
            selectable={selectable}
            selected={selectedIds?.has(product.id)}
            onSelectionChange={onSelectionChange}
          />
        ))}
      </div>

      {/* Sentinel for infinite scroll */}
      {hasNextPage && (
        <div ref={sentinelRef} className="py-4">
          {isFetchingNextPage && (
            <div className="flex items-center justify-center py-4">
              <div
                className="h-6 w-6 animate-spin rounded-full border-4"
                style={{
                  borderColor: 'var(--color-border)',
                  borderTopColor: 'var(--color-accent)',
                }}
              />
            </div>
          )}
        </div>
      )}
    </div>
  );
}
