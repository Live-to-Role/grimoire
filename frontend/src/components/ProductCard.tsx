import { Book } from 'lucide-react';
import type { Product } from '../types/product';
import { getCoverUrl } from '../api/products';

interface ProductCardProps {
  product: Product;
  onClick?: (product: Product) => void;
}

export function ProductCard({ product, onClick }: ProductCardProps) {
  const handleClick = () => {
    onClick?.(product);
  };

  return (
    <article
      className="group relative flex flex-col overflow-hidden rounded-lg border border-neutral-200 bg-white shadow-sm transition-all hover:shadow-md hover:border-purple-300 cursor-pointer"
      onClick={handleClick}
      role="button"
      tabIndex={0}
      onKeyDown={(e) => e.key === 'Enter' && handleClick()}
    >
      <div className="aspect-[3/4] w-full overflow-hidden bg-neutral-100">
        {product.cover_url ? (
          <img
            src={getCoverUrl(product.id)}
            alt={`${product.title || product.file_name} cover`}
            className="h-full w-full object-cover transition-transform group-hover:scale-105"
            loading="lazy"
          />
        ) : (
          <div className="flex h-full w-full items-center justify-center bg-neutral-200">
            <Book className="h-12 w-12 text-neutral-400" />
          </div>
        )}
      </div>

      <div className="flex flex-1 flex-col p-3">
        <h3 className="line-clamp-2 text-sm font-medium text-neutral-900">
          {product.title || product.file_name}
        </h3>

        {product.publisher && (
          <p className="mt-1 text-xs text-neutral-500">{product.publisher}</p>
        )}

        <div className="mt-2 flex flex-wrap gap-1">
          {product.game_system && (
            <span className="inline-flex items-center rounded-full bg-purple-100 px-2 py-0.5 text-xs font-medium text-purple-700">
              {product.game_system}
            </span>
          )}
          {product.product_type && (
            <span className="inline-flex items-center rounded-full bg-neutral-100 px-2 py-0.5 text-xs font-medium text-neutral-600">
              {product.product_type}
            </span>
          )}
        </div>

        {product.page_count && (
          <p className="mt-auto pt-2 text-xs text-neutral-500">
            {product.page_count} pages
          </p>
        )}
      </div>
    </article>
  );
}
