import { useState } from 'react';
import { useQuery } from '@tanstack/react-query';
import { Image, Search, X, ChevronLeft, ChevronRight, Grid3X3, Loader2 } from 'lucide-react';
import { getGalleryProducts, getProductImages, getImageUrl } from '../api/gallery';
import { getTags } from '../api/tags';
import { getCollections } from '../api/collections';
import { getThumbnailUrl } from '../api/products';
import type { GalleryFilters, GalleryProduct, ProductImage } from '../api/gallery';

export function Gallery() {
  const [filters, setFilters] = useState<GalleryFilters>({ page: 1, page_size: 24 });
  const [searchInput, setSearchInput] = useState('');
  const [expandedProduct, setExpandedProduct] = useState<GalleryProduct | null>(null);

  const { data: gallery, isLoading } = useQuery({
    queryKey: ['gallery', filters],
    queryFn: () => getGalleryProducts(filters),
  });

  const { data: tags } = useQuery({
    queryKey: ['tags'],
    queryFn: () => getTags(),
  });

  const { data: collections } = useQuery({
    queryKey: ['collections'],
    queryFn: () => getCollections(),
  });

  const builtinTags = tags?.filter(t => t.is_builtin) || [];

  const handleSearch = () => {
    setFilters(prev => ({ ...prev, search: searchInput || undefined, page: 1 }));
  };

  const handleTagFilter = (tagId: number | undefined) => {
    setFilters(prev => ({ ...prev, tag_id: tagId, page: 1 }));
  };

  const handleCollectionFilter = (collectionId: number | undefined) => {
    setFilters(prev => ({ ...prev, collection_id: collectionId, page: 1 }));
  };

  return (
    <div className="flex h-full">
      {/* Sidebar filters */}
      <div
        className="w-64 flex-shrink-0 overflow-y-auto border-r p-4"
        style={{
          backgroundColor: 'var(--color-surface)',
          borderColor: 'var(--color-border)',
        }}
      >
        {/* Search */}
        <div className="mb-6">
          <label className="mb-2 block text-sm font-medium" style={{ color: 'var(--color-text-primary)' }}>Search</label>
          <div className="flex gap-1">
            <input
              type="text"
              value={searchInput}
              onChange={e => setSearchInput(e.target.value)}
              onKeyDown={e => e.key === 'Enter' && handleSearch()}
              placeholder="Search gallery..."
              className="flex-1 rounded border px-2 py-1 text-sm"
              style={{
                borderColor: 'var(--color-border)',
                backgroundColor: 'var(--color-bg)',
                color: 'var(--color-text-primary)',
              }}
            />
            <button
              onClick={handleSearch}
              className="rounded p-1"
              style={{ backgroundColor: 'var(--color-accent)', color: 'var(--color-accent-text)' }}
            >
              <Search className="h-4 w-4" />
            </button>
          </div>
        </div>

        {/* Content type tags */}
        <div className="mb-6">
          <label className="mb-2 block text-sm font-medium" style={{ color: 'var(--color-text-primary)' }}>Content Type</label>
          <div className="flex flex-col gap-1">
            <button
              onClick={() => handleTagFilter(undefined)}
              className="rounded px-2 py-1 text-left text-sm transition-colors"
              style={{
                backgroundColor: !filters.tag_id ? 'var(--color-accent)' : 'transparent',
                color: !filters.tag_id ? 'var(--color-accent-text)' : 'var(--color-text-primary)',
              }}
            >
              All
            </button>
            {builtinTags.map(tag => (
              <button
                key={tag.id}
                onClick={() => handleTagFilter(tag.id)}
                className="rounded px-2 py-1 text-left text-sm transition-colors"
                style={{
                  backgroundColor: filters.tag_id === tag.id ? 'var(--color-accent)' : 'transparent',
                  color: filters.tag_id === tag.id ? 'var(--color-accent-text)' : 'var(--color-text-primary)',
                }}
              >
                <span
                  className="mr-2 inline-block h-2 w-2 rounded-full"
                  style={{ backgroundColor: tag.color || '#888' }}
                />
                {tag.name}
                {tag.product_count > 0 && (
                  <span className="ml-1 text-xs opacity-60">({tag.product_count})</span>
                )}
              </button>
            ))}
          </div>
        </div>

        {/* Collections */}
        {collections && collections.length > 0 && (
          <div className="mb-6">
            <label className="mb-2 block text-sm font-medium" style={{ color: 'var(--color-text-primary)' }}>Collections</label>
            <div className="flex flex-col gap-1">
              <button
                onClick={() => handleCollectionFilter(undefined)}
                className="rounded px-2 py-1 text-left text-sm transition-colors"
                style={{
                  backgroundColor: !filters.collection_id ? 'var(--color-accent)' : 'transparent',
                  color: !filters.collection_id ? 'var(--color-accent-text)' : 'var(--color-text-primary)',
                }}
              >
                All
              </button>
              {collections.map(col => (
                <button
                  key={col.id}
                  onClick={() => handleCollectionFilter(col.id)}
                  className="rounded px-2 py-1 text-left text-sm transition-colors"
                  style={{
                    backgroundColor: filters.collection_id === col.id ? 'var(--color-accent)' : 'transparent',
                    color: filters.collection_id === col.id ? 'var(--color-accent-text)' : 'var(--color-text-primary)',
                  }}
                >
                  {col.name}
                  {col.product_count > 0 && (
                    <span className="ml-1 text-xs opacity-60">({col.product_count})</span>
                  )}
                </button>
              ))}
            </div>
          </div>
        )}

        {/* Sort */}
        <div>
          <label className="mb-2 block text-sm font-medium" style={{ color: 'var(--color-text-primary)' }}>Sort By</label>
          <select
            value={`${filters.sort || 'created_at'}-${filters.order || 'desc'}`}
            onChange={e => {
              const [sort, order] = e.target.value.split('-');
              setFilters(prev => ({ ...prev, sort: sort as any, order: order as any }));
            }}
            className="w-full rounded border px-2 py-1 text-sm"
            style={{
              borderColor: 'var(--color-border)',
              backgroundColor: 'var(--color-bg)',
              color: 'var(--color-text-primary)',
            }}
          >
            <option value="created_at-desc">Newest First</option>
            <option value="created_at-asc">Oldest First</option>
            <option value="title-asc">Title A-Z</option>
            <option value="title-desc">Title Z-A</option>
            <option value="image_count-desc">Most Images</option>
          </select>
        </div>
      </div>

      {/* Main grid */}
      <div className="flex-1 overflow-y-auto p-6">
        {isLoading ? (
          <div className="flex h-full items-center justify-center">
            <Loader2 className="h-8 w-8 animate-spin" style={{ color: 'var(--color-text-secondary)' }} />
          </div>
        ) : !gallery || gallery.items.length === 0 ? (
          <div className="flex h-full flex-col items-center justify-center" style={{ color: 'var(--color-text-secondary)' }}>
            <Image className="mb-4 h-16 w-16 opacity-50" />
            <p className="text-lg">No image content found</p>
            <p className="text-sm">Maps and stock art PDFs will appear here after scanning</p>
          </div>
        ) : (
          <>
            <div className="mb-4 text-sm" style={{ color: 'var(--color-text-secondary)' }}>
              {gallery.total} product{gallery.total !== 1 ? 's' : ''} found
            </div>
            <div className="grid grid-cols-2 gap-4 sm:grid-cols-3 md:grid-cols-4 lg:grid-cols-5 xl:grid-cols-6">
              {gallery.items.map(product => (
                <GalleryCard
                  key={product.id}
                  product={product}
                  onClick={() => setExpandedProduct(product)}
                />
              ))}
            </div>
            {/* Pagination */}
            {gallery.total_pages > 1 && (
              <div className="mt-6 flex items-center justify-center gap-2">
                <button
                  onClick={() => setFilters(prev => ({ ...prev, page: (prev.page || 1) - 1 }))}
                  disabled={gallery.page <= 1}
                  className="rounded p-2 disabled:opacity-50"
                  style={{ backgroundColor: 'var(--color-surface-raised)', color: 'var(--color-text-primary)' }}
                >
                  <ChevronLeft className="h-4 w-4" />
                </button>
                <span className="text-sm" style={{ color: 'var(--color-text-secondary)' }}>
                  Page {gallery.page} of {gallery.total_pages}
                </span>
                <button
                  onClick={() => setFilters(prev => ({ ...prev, page: (prev.page || 1) + 1 }))}
                  disabled={gallery.page >= gallery.total_pages}
                  className="rounded p-2 disabled:opacity-50"
                  style={{ backgroundColor: 'var(--color-surface-raised)', color: 'var(--color-text-primary)' }}
                >
                  <ChevronRight className="h-4 w-4" />
                </button>
              </div>
            )}
          </>
        )}
      </div>

      {/* Expanded product modal */}
      {expandedProduct && (
        <ProductImageModal
          product={expandedProduct}
          onClose={() => setExpandedProduct(null)}
        />
      )}
    </div>
  );
}


function GalleryCard({ product, onClick }: { product: GalleryProduct; onClick: () => void }) {
  return (
    <button
      onClick={onClick}
      className="group overflow-hidden rounded-lg border text-left transition-shadow hover:shadow-lg"
      style={{
        borderColor: 'var(--color-border)',
        backgroundColor: 'var(--color-surface)',
      }}
    >
      <div className="aspect-[3/4] overflow-hidden" style={{ backgroundColor: 'var(--color-surface-raised)' }}>
        {product.cover_extracted ? (
          <img
            src={getThumbnailUrl(product.id)}
            alt={product.title}
            className="h-full w-full object-cover transition-transform group-hover:scale-105"
            loading="lazy"
          />
        ) : (
          <div className="flex h-full items-center justify-center">
            <Image className="h-12 w-12" style={{ color: 'var(--color-text-secondary)' }} />
          </div>
        )}
      </div>
      <div className="p-2">
        <p className="truncate text-sm font-medium" style={{ color: 'var(--color-text-primary)' }}>{product.title}</p>
        <div className="mt-1 flex items-center gap-1">
          {product.tags.slice(0, 2).map(tag => (
            <span
              key={tag.id}
              className="rounded px-1.5 py-0.5 text-xs text-white"
              style={{ backgroundColor: tag.color || '#888' }}
            >
              {tag.name}
            </span>
          ))}
          {product.image_count > 0 && (
            <span className="ml-auto flex items-center gap-0.5 text-xs" style={{ color: 'var(--color-text-secondary)' }}>
              <Grid3X3 className="h-3 w-3" />
              {product.image_count}
            </span>
          )}
        </div>
      </div>
    </button>
  );
}


function ProductImageModal({ product, onClose }: { product: GalleryProduct; onClose: () => void }) {
  const { data: imagesData, isLoading } = useQuery({
    queryKey: ['product-images', product.id],
    queryFn: () => getProductImages(product.id),
  });

  return (
    <div className="fixed inset-0 z-50 flex items-start justify-center overflow-y-auto bg-black/70 p-8" onClick={onClose}>
      <div
        className="w-full max-w-6xl rounded-lg shadow-2xl"
        style={{ backgroundColor: 'var(--color-bg)' }}
        onClick={e => e.stopPropagation()}
      >
        {/* Header */}
        <div className="flex items-center justify-between border-b px-6 py-4" style={{ borderColor: 'var(--color-border)' }}>
          <div>
            <h2 className="text-lg font-semibold" style={{ color: 'var(--color-text-primary)' }}>{product.title}</h2>
            {product.publisher && (
              <p className="text-sm" style={{ color: 'var(--color-text-secondary)' }}>{product.publisher}</p>
            )}
          </div>
          <button
            onClick={onClose}
            className="rounded p-1 transition-colors"
            style={{ color: 'var(--color-text-secondary)' }}
          >
            <X className="h-5 w-5" />
          </button>
        </div>

        {/* Images grid */}
        <div className="p-6">
          {isLoading ? (
            <div className="flex justify-center py-12">
              <Loader2 className="h-8 w-8 animate-spin" style={{ color: 'var(--color-text-secondary)' }} />
            </div>
          ) : !imagesData || imagesData.images.length === 0 ? (
            <div className="py-12 text-center" style={{ color: 'var(--color-text-secondary)' }}>
              <p>No images extracted yet</p>
              <p className="mt-1 text-sm">Images will appear after processing completes</p>
            </div>
          ) : (
            <div className="grid grid-cols-2 gap-4 sm:grid-cols-3 md:grid-cols-4">
              {imagesData.images.map((img, i) => (
                <ImageTile key={i} image={img} productId={product.id} />
              ))}
            </div>
          )}
        </div>
      </div>
    </div>
  );
}


function ImageTile({ image, productId }: { image: ProductImage; productId: number }) {
  const [fullscreen, setFullscreen] = useState(false);
  const url = getImageUrl(productId, image.filename);

  return (
    <>
      <button
        onClick={() => setFullscreen(true)}
        className="group overflow-hidden rounded border"
        style={{
          borderColor: 'var(--color-border)',
          backgroundColor: 'var(--color-surface)',
        }}
      >
        <img
          src={url}
          alt={`Page ${image.page}`}
          className="w-full transition-transform group-hover:scale-105"
          loading="lazy"
        />
        <div className="px-2 py-1 text-xs" style={{ color: 'var(--color-text-secondary)' }}>
          Page {image.page} &middot; {image.width}x{image.height}
        </div>
      </button>

      {fullscreen && (
        <div
          className="fixed inset-0 z-[60] flex items-center justify-center bg-black/90 p-4"
          onClick={() => setFullscreen(false)}
        >
          <img
            src={url}
            alt={`Page ${image.page}`}
            className="max-h-full max-w-full object-contain"
          />
        </div>
      )}
    </>
  );
}
