import { useState, useCallback } from 'react';
import { Book, FileText, Loader2, Check } from 'lucide-react';
import { useMutation } from '@tanstack/react-query';
import type { Product } from '../types/product';
import { getCoverUrl } from '../api/products';
import apiClient from '../api/client';

interface ProductCardProps {
  product: Product;
  onClick?: (product: Product) => void;
  viewMode?: 'grid' | 'list';
}

export function ProductCard({ product, onClick, viewMode = 'grid' }: ProductCardProps) {
  const [queued, setQueued] = useState(false);
  const [coverError, setCoverError] = useState(false);

  const handleCoverError = useCallback(() => {
    setCoverError(true);
  }, []);

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

  if (viewMode === 'list') {
    return (
      <article
        className="group flex items-center gap-4 rounded-sm border-l-4 border-l-codex-olive border border-codex-tan bg-codex-cream p-3 shadow-tome transition-all duration-200 hover:shadow-tome-lg hover:border-codex-olive hover:bg-primary-50 hover:-translate-y-0.5 cursor-pointer"
        onClick={handleClick}
        role="button"
        tabIndex={0}
        onKeyDown={(e) => e.key === 'Enter' && handleClick()}
      >
        <div className="h-16 w-12 flex-shrink-0 overflow-hidden rounded-sm bg-primary-200 relative">
          {product.cover_url && !coverError ? (
            <img
              src={getCoverUrl(product.id)}
              alt={`${product.title || product.file_name} cover`}
              className="h-full w-full object-cover"
              loading="lazy"
              onError={handleCoverError}
            />
          ) : (
            <div className="flex h-full w-full items-center justify-center bg-primary-200">
              <Book className="h-6 w-6 text-primary-400" />
            </div>
          )}
        </div>

        <div className="flex-1 min-w-0">
          <h3 className="truncate text-sm font-medium text-primary-800">
            {product.title || product.file_name}
          </h3>
          <div className="mt-1 flex items-center gap-2 text-xs text-primary-600">
            {product.publisher && <span className="text-codex-brown">{product.publisher}</span>}
            {product.page_count && <span>• {product.page_count} pages</span>}
          </div>
        </div>

        <div className="flex items-center gap-2">
          {product.game_system && (
            <span className="inline-flex items-center rounded-sm bg-codex-olive px-2 py-0.5 text-xs font-medium text-codex-cream">
              {product.game_system}
            </span>
          )}
          {product.product_type && (
            <span className="inline-flex items-center rounded-sm bg-codex-dark px-2 py-0.5 text-xs font-medium text-codex-cream">
              {product.product_type}
            </span>
          )}
          {product.processing_status?.text_extracted && (
            <div className="rounded-full bg-green-500 p-1" title="Text extracted">
              <FileText className="h-3 w-3 text-white" />
            </div>
          )}
          {needsExtraction && (
            <button
              onClick={handleQueueClick}
              disabled={queued || queueMutation.isPending}
              className={`rounded-lg px-2 py-1.5 text-xs font-medium flex items-center gap-1 ${
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
                </>
              ) : (
                <FileText className="h-3 w-3" />
              )}
            </button>
          )}
        </div>
      </article>
    );
  }

  return (
    <article
      className="group relative flex flex-col overflow-hidden rounded-sm border-l-4 border-l-codex-olive border border-codex-tan bg-codex-cream shadow-tome transition-all duration-200 hover:shadow-tome-lg hover:border-codex-olive hover:-translate-y-1 cursor-pointer"
      onClick={handleClick}
      role="button"
      tabIndex={0}
      onKeyDown={(e) => e.key === 'Enter' && handleClick()}
    >
      <div className="aspect-[3/4] w-full overflow-hidden bg-primary-200 relative">
        {product.cover_url && !coverError ? (
          <img
            src={getCoverUrl(product.id)}
            alt={`${product.title || product.file_name} cover`}
            className="h-full w-full object-cover transition-transform group-hover:scale-105"
            loading="lazy"
            onError={handleCoverError}
          />
        ) : (
          <div className="flex h-full w-full items-center justify-center bg-primary-200">
            <Book className="h-12 w-12 text-primary-400" />
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
        <h3 className="line-clamp-2 text-sm font-medium text-primary-800">
          {product.title || product.file_name}
        </h3>

        {product.publisher && (
          <p className="mt-1 text-xs text-codex-brown font-medium">{product.publisher}</p>
        )}

        <div className="mt-2 flex flex-wrap gap-1">
          {product.game_system && (
            <span className="inline-flex items-center rounded-sm bg-codex-olive px-2 py-0.5 text-xs font-medium text-codex-cream">
              {product.game_system}
            </span>
          )}
          {product.product_type && (
            <span className="inline-flex items-center rounded-sm bg-codex-dark px-2 py-0.5 text-xs font-medium text-codex-cream">
              {product.product_type}
            </span>
          )}
        </div>

        {product.page_count && (
          <p className="mt-auto pt-2 text-xs text-primary-600">
            {product.page_count} pages
          </p>
        )}
      </div>
    </article>
  );
}
