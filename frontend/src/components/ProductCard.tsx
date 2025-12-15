import { useState } from 'react';
import { Book, FileText, Loader2, Check } from 'lucide-react';
import { useMutation } from '@tanstack/react-query';
import type { Product } from '../types/product';
import { getCoverUrl } from '../api/products';
import apiClient from '../api/client';

interface ProductCardProps {
  product: Product;
  onClick?: (product: Product) => void;
}

export function ProductCard({ product, onClick }: ProductCardProps) {
  const [queued, setQueued] = useState(false);

  const queueMutation = useMutation({
    mutationFn: async () => {
      await apiClient.post('/queue', {
        product_id: product.id,
        task_type: 'text',
        priority: 5,
      });
    },
    onSuccess: () => {
      setQueued(true);
    },
  });

  const handleClick = () => {
    onClick?.(product);
  };

  const handleQueueClick = (e: React.MouseEvent) => {
    e.stopPropagation();
    if (!queued && !queueMutation.isPending) {
      queueMutation.mutate();
    }
  };

  const needsExtraction = !product.processing_status?.text_extracted;

  return (
    <article
      className="group relative flex flex-col overflow-hidden rounded-lg border border-neutral-200 bg-white shadow-sm transition-all hover:shadow-md hover:border-purple-300 cursor-pointer"
      onClick={handleClick}
      role="button"
      tabIndex={0}
      onKeyDown={(e) => e.key === 'Enter' && handleClick()}
    >
      <div className="aspect-[3/4] w-full overflow-hidden bg-neutral-100 relative">
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
        
        {/* Queue button - shows on hover for products needing extraction */}
        {needsExtraction && (
          <button
            onClick={handleQueueClick}
            disabled={queued || queueMutation.isPending}
            className={`absolute bottom-2 right-2 opacity-0 group-hover:opacity-100 transition-opacity rounded-lg px-2 py-1.5 text-xs font-medium shadow-lg flex items-center gap-1 ${
              queued
                ? 'bg-green-600 text-white'
                : queueMutation.isPending
                ? 'bg-blue-500 text-white'
                : 'bg-blue-600 text-white hover:bg-blue-700'
            }`}
            title="Add to text extraction queue"
          >
            {queued ? (
              <>
                <Check className="h-3 w-3" />
                Queued
              </>
            ) : queueMutation.isPending ? (
              <>
                <Loader2 className="h-3 w-3 animate-spin" />
                Adding...
              </>
            ) : (
              <>
                <FileText className="h-3 w-3" />
                Queue
              </>
            )}
          </button>
        )}
        
        {/* Extraction status indicator */}
        {product.processing_status?.text_extracted && (
          <div className="absolute top-2 right-2 rounded-full bg-green-500 p-1" title="Text extracted">
            <FileText className="h-3 w-3 text-white" />
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
