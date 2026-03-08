import { useRef, useMemo, useState, useEffect } from 'react';
import { useVirtualizer } from '@tanstack/react-virtual';
import { ProductCard } from './ProductCard';
import type { Product } from '../types/product';

interface ProductGridProps {
  products: Product[];
  onProductClick?: (product: Product) => void;
  viewMode?: 'grid' | 'list';
}

export function ProductGrid({ products, onProductClick, viewMode = 'grid' }: ProductGridProps) {
  const parentRef = useRef<HTMLDivElement>(null);
  
  const [windowWidth, setWindowWidth] = useState(
    typeof window !== 'undefined' ? window.innerWidth : 1920
  );

  useEffect(() => {
    const handleResize = () => setWindowWidth(window.innerWidth);
    window.addEventListener('resize', handleResize);
    return () => window.removeEventListener('resize', handleResize);
  }, []);

  // Calculate columns based on viewport width
  const columns = useMemo(() => {
    if (viewMode === 'list') return 1;
    if (windowWidth < 640) return 2;
    if (windowWidth < 768) return 3;
    if (windowWidth < 1024) return 4;
    if (windowWidth < 1280) return 5;
    return 6;
  }, [viewMode, windowWidth]);
  
  // Calculate row count
  const rowCount = Math.ceil(products.length / columns);
  
  // Estimate item sizes
  const estimateSize = useMemo(() => {
    if (viewMode === 'list') return 80; // List item height
    return 320; // Grid item height (aspect ratio 3:4 + padding)
  }, [viewMode]);
  
  const virtualizer = useVirtualizer({
    count: rowCount,
    getScrollElement: () => parentRef.current,
    estimateSize: () => estimateSize,
    overscan: 3, // Render 3 extra rows above/below viewport
  });
  
  if (products.length === 0) {
    return (
      <div className="flex flex-col items-center justify-center py-16 text-center">
        <div className="rounded-full bg-neutral-100 p-4">
          <svg
            className="h-12 w-12 text-neutral-400"
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
        <h3 className="mt-4 text-lg font-medium text-neutral-900">No products found</h3>
        <p className="mt-1 text-sm text-neutral-500">
          Add a folder to watch or adjust your filters.
        </p>
      </div>
    );
  }

  const virtualItems = virtualizer.getVirtualItems();

  return (
    <div ref={parentRef} className="h-full overflow-auto">
      <div
        style={{
          height: `${virtualizer.getTotalSize()}px`,
          width: '100%',
          position: 'relative',
        }}
      >
        {virtualItems.map((virtualRow: { key: React.Key; index: number; start: number }) => {
          const startIndex = virtualRow.index * columns;
          const rowProducts = products.slice(startIndex, startIndex + columns);
          
          return (
            <div
              key={virtualRow.key}
              style={{
                position: 'absolute',
                top: 0,
                left: 0,
                width: '100%',
                transform: `translateY(${virtualRow.start}px)`,
              }}
            >
              <div className={viewMode === 'grid' 
                ? "grid grid-cols-2 gap-4 sm:grid-cols-3 md:grid-cols-4 lg:grid-cols-5 xl:grid-cols-6"
                : "flex flex-col gap-2"
              }>
                {rowProducts.map((product) => (
                  <ProductCard
                    key={product.id}
                    product={product}
                    onClick={onProductClick}
                    viewMode={viewMode}
                  />
                ))}
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
}
