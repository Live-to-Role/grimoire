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
  selectable?: boolean;
  selected?: boolean;
  onSelectionChange?: (productId: number, selected: boolean) => void;
  score?: number;
  snippet?: string;
}

export function ProductCard({ product, onClick, viewMode = 'grid', selectable, selected, onSelectionChange, score, snippet }: ProductCardProps) {
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
        className="group flex items-center gap-4 rounded-md cursor-pointer transition-shadow duration-200 shadow-sm hover:shadow-md"
        style={{
          backgroundColor: 'var(--color-surface)',
          border: '1px solid var(--color-border)',
          padding: '12px 16px',
          minHeight: '84px',
        }}
        onClick={handleClick}
        role="button"
        tabIndex={0}
        onKeyDown={(e) => e.key === 'Enter' && handleClick()}
      >
        {selectable && (
          <div className="flex-shrink-0">
            <input
              type="checkbox"
              checked={selected}
              onChange={(e) => {
                e.stopPropagation();
                onSelectionChange?.(product.id, e.target.checked);
              }}
              onClick={(e) => e.stopPropagation()}
              className="h-5 w-5 rounded cursor-pointer accent-[var(--color-accent)]"
            />
          </div>
        )}
        <div
          className="flex-shrink-0 overflow-hidden rounded-md"
          style={{
            width: '64px',
            height: '84px',
            backgroundColor: 'var(--color-surface-raised)',
          }}
        >
          {product.cover_url && !coverError ? (
            <img
              src={getCoverUrl(product.id, 'thumbnail')}
              alt={`${product.title || product.file_name} cover`}
              className="h-full w-full object-cover"
              loading="lazy"
              onError={handleCoverError}
            />
          ) : (
            <div className="flex h-full w-full items-center justify-center">
              <Book size={24} style={{ color: 'var(--color-text-secondary)' }} />
            </div>
          )}
        </div>

        <div className="flex-1 min-w-0 py-1">
          <h3 className="truncate text-lg font-medium" style={{ color: 'var(--color-text-primary)' }}>
            {product.title || product.file_name}
          </h3>
          <div className="mt-1 flex items-center gap-2 text-base" style={{ color: 'var(--color-text-secondary)' }}>
            {product.publisher && <span>{product.publisher}</span>}
            {product.page_count && <span>· {product.page_count} pages</span>}
          </div>
          {snippet && (
            <p
              className="mt-1 text-xs italic line-clamp-2"
              style={{ color: 'var(--color-text-secondary)' }}
            >
              {snippet}
            </p>
          )}
        </div>

        <div className="flex items-center gap-2">
          {score != null && (
            <span
              className="inline-flex items-center rounded-full px-2 py-0.5 text-xs font-medium"
              style={{
                backgroundColor: 'var(--color-accent-light)',
                color: 'var(--color-accent)',
              }}
            >
              {Math.round(score * 100)}% match
            </span>
          )}
          {product.game_system && (
            <span
              className="badge-primary text-sm px-3 py-1"
            >
              {product.game_system}
            </span>
          )}
          {product.product_type && (
            <span className="badge-secondary text-sm px-3 py-1">
              {product.product_type}
            </span>
          )}
          {product.processing_status?.text_extracted && (
            <div
              className="rounded-full p-1"
              title="Text extracted"
              style={{ backgroundColor: 'var(--color-success)' }}
            >
              <FileText size={14} className="text-white" />
            </div>
          )}
          {needsExtraction && (
            <button
              onClick={handleQueueClick}
              disabled={queued || queueMutation.isPending}
              className="rounded-md px-3 py-2 text-sm font-medium flex items-center gap-1.5 text-white disabled:opacity-50"
              style={{
                backgroundColor: queued ? 'var(--color-success)' : 'var(--color-accent)',
                minHeight: '44px',
              }}
              title="Add to text extraction queue"
            >
              {queued ? (
                <><Check size={14} /> Queued</>
              ) : queueMutation.isPending ? (
                <Loader2 size={14} className="animate-spin" />
              ) : (
                <FileText size={14} />
              )}
            </button>
          )}
        </div>
      </article>
    );
  }

  return (
    <article
      className="group relative flex flex-col overflow-hidden rounded-md cursor-pointer transition-shadow duration-200 shadow-sm hover:shadow-md"
      style={{
        backgroundColor: 'var(--color-surface)',
        border: '1px solid var(--color-border)',
      }}
      onClick={handleClick}
      role="button"
      tabIndex={0}
      onKeyDown={(e) => e.key === 'Enter' && handleClick()}
    >
      <div
        className="aspect-[3/4] w-full overflow-hidden rounded-t-md relative"
        style={{ backgroundColor: 'var(--color-surface-raised)' }}
      >
        {selectable && (
          <div
            className={`absolute top-2 left-2 z-10 transition-opacity ${selected ? 'opacity-100' : 'opacity-0 group-hover:opacity-100'}`}
          >
            <input
              type="checkbox"
              checked={selected}
              onChange={(e) => {
                e.stopPropagation();
                onSelectionChange?.(product.id, e.target.checked);
              }}
              onClick={(e) => e.stopPropagation()}
              className="h-5 w-5 rounded cursor-pointer accent-[var(--color-accent)]"
            />
          </div>
        )}
        {product.cover_url && !coverError ? (
          <img
            src={getCoverUrl(product.id, 'thumbnail')}
            alt={`${product.title || product.file_name} cover`}
            className="h-full w-full object-cover"
            loading="lazy"
            onError={handleCoverError}
          />
        ) : (
          <div className="flex h-full w-full items-center justify-center">
            <Book size={48} style={{ color: 'var(--color-text-secondary)' }} />
          </div>
        )}

        {/* Queue button - always visible for products needing extraction */}
        {needsExtraction && (
          <button
            onClick={handleQueueClick}
            disabled={queued || queueMutation.isPending}
            className="absolute bottom-2 right-2 rounded-md px-3 py-2 text-sm font-medium shadow-lg flex items-center gap-1.5 text-white disabled:opacity-50"
            style={{
              backgroundColor: queued ? 'var(--color-success)' : 'var(--color-accent)',
              minHeight: '44px',
            }}
            title="Add to text extraction queue"
          >
            {queued ? (
              <><Check size={14} /> Queued</>
            ) : queueMutation.isPending ? (
              <><Loader2 size={14} className="animate-spin" /> Adding...</>
            ) : (
              <><FileText size={14} /> Queue</>
            )}
          </button>
        )}

        {/* Extraction status indicator */}
        {product.processing_status?.text_extracted && (
          <div
            className="absolute top-2 right-2 rounded-full p-1"
            title="Text extracted"
            style={{ backgroundColor: 'var(--color-success)' }}
          >
            <FileText size={14} className="text-white" />
          </div>
        )}

        {/* Relevance score badge */}
        {score != null && (
          <div
            className="absolute bottom-2 left-2 rounded-full px-2 py-0.5 text-xs font-medium"
            style={{
              backgroundColor: 'var(--color-surface)',
              color: 'var(--color-text-secondary)',
              border: '1px solid var(--color-border)',
              opacity: 0.9,
            }}
            title={`Relevance: ${Math.round(score * 100)}%`}
          >
            {Math.round(score * 100)}%
          </div>
        )}
      </div>

      <div className="flex flex-1 flex-col p-4">
        <h3 className="line-clamp-2 text-lg font-semibold" style={{ color: 'var(--color-text-primary)' }}>
          {product.title || product.file_name}
        </h3>

        {snippet && (
          <p
            className="mt-1 text-xs italic line-clamp-2"
            style={{ color: 'var(--color-text-secondary)' }}
          >
            {snippet}
          </p>
        )}

        {product.publisher && (
          <p className="mt-1 text-base font-medium" style={{ color: 'var(--color-text-secondary)' }}>
            {product.publisher}
          </p>
        )}

        <div className="mt-2 flex flex-wrap gap-1.5">
          {product.game_system && (
            <span className="badge-primary text-sm px-3 py-1">
              {product.game_system}
            </span>
          )}
          {product.product_type && (
            <span className="badge-secondary text-sm px-3 py-1">
              {product.product_type}
            </span>
          )}
        </div>

        {product.page_count && (
          <p className="mt-auto pt-2 text-base" style={{ color: 'var(--color-text-secondary)' }}>
            {product.page_count} pages
          </p>
        )}
      </div>
    </article>
  );
}
