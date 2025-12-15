import { ProductCard } from './ProductCard';
import type { Product } from '../types/product';

interface ProductGridProps {
  products: Product[];
  onProductClick?: (product: Product) => void;
  viewMode?: 'grid' | 'list';
}

export function ProductGrid({ products, onProductClick, viewMode = 'grid' }: ProductGridProps) {
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

  return (
    <div className={viewMode === 'grid' 
      ? "grid grid-cols-2 gap-4 sm:grid-cols-3 md:grid-cols-4 lg:grid-cols-5 xl:grid-cols-6"
      : "flex flex-col gap-2"
    }>
      {products.map((product) => (
        <ProductCard
          key={product.id}
          product={product}
          onClick={onProductClick}
          viewMode={viewMode}
        />
      ))}
    </div>
  );
}
