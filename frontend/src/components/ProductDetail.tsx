import { useState } from 'react';
import { X, FileText, Book, Calendar, Users, Clock, ExternalLink, Eye } from 'lucide-react';
import type { Product } from '../types/product';
import { getProductText } from '../api/search';
import { getCoverUrl } from '../api/products';
import { PDFViewer } from './PDFViewer';

interface ProductDetailProps {
  product: Product;
  onClose: () => void;
}

export function ProductDetail({ product, onClose }: ProductDetailProps) {
  const [activeTab, setActiveTab] = useState<'info' | 'text'>('info');
  const [textContent, setTextContent] = useState<string | null>(null);
  const [textLoading, setTextLoading] = useState(false);
  const [textError, setTextError] = useState<string | null>(null);
  const [showPdfViewer, setShowPdfViewer] = useState(false);

  const loadText = async () => {
    if (textContent) return;
    setTextLoading(true);
    setTextError(null);
    try {
      const data = await getProductText(product.id);
      setTextContent(data.markdown);
    } catch {
      setTextError('Text not available for this product.');
    } finally {
      setTextLoading(false);
    }
  };

  const handleTabChange = (tab: 'info' | 'text') => {
    setActiveTab(tab);
    if (tab === 'text') {
      loadText();
    }
  };

  const openPdf = () => {
    window.open(`/api/v1/products/${product.id}/pdf`, '_blank');
  };

  return (
    <div 
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/50 p-4"
      role="dialog"
      aria-modal="true"
      aria-labelledby="product-detail-title"
      onClick={(e) => e.target === e.currentTarget && onClose()}
    >
      <div className="flex h-[90vh] w-full max-w-4xl flex-col overflow-hidden rounded-xl bg-white shadow-2xl">
        <header className="flex items-center justify-between border-b border-neutral-200 px-6 py-4">
          <h2 id="product-detail-title" className="text-xl font-semibold text-neutral-900 truncate">{product.title}</h2>
          <button
            onClick={onClose}
            aria-label="Close product details"
            className="rounded-lg p-2 text-neutral-500 hover:bg-neutral-100"
          >
            <X className="h-5 w-5" aria-hidden="true" />
          </button>
        </header>

        <div className="flex border-b border-neutral-200" role="tablist" aria-label="Product information tabs">
          <button
            onClick={() => handleTabChange('info')}
            role="tab"
            aria-selected={activeTab === 'info'}
            aria-controls="panel-info"
            id="tab-info"
            className={`px-6 py-3 text-sm font-medium ${
              activeTab === 'info'
                ? 'border-b-2 border-purple-600 text-purple-600'
                : 'text-neutral-600 hover:text-neutral-900'
            }`}
          >
            Details
          </button>
          <button
            onClick={() => handleTabChange('text')}
            role="tab"
            aria-selected={activeTab === 'text'}
            aria-controls="panel-text"
            id="tab-text"
            className={`px-6 py-3 text-sm font-medium ${
              activeTab === 'text'
                ? 'border-b-2 border-purple-600 text-purple-600'
                : 'text-neutral-600 hover:text-neutral-900'
            }`}
          >
            Extracted Text
          </button>
        </div>

        <div className="flex-1 overflow-auto">
          {activeTab === 'info' ? (
            <div
              role="tabpanel"
              id="panel-info"
              aria-labelledby="tab-info"
              className="flex flex-col gap-6 p-6 md:flex-row"
            >
              <div className="shrink-0">
                <img
                  src={getCoverUrl(product.id)}
                  alt={product.title || 'Product cover'}
                  className="h-64 w-44 rounded-lg object-cover shadow-lg"
                  onError={(e) => {
                    (e.target as HTMLImageElement).src = '/placeholder-cover.png';
                  }}
                />
              </div>

              <div className="flex-1 space-y-4">
                <div className="grid grid-cols-2 gap-4">
                  {product.game_system && (
                    <div className="flex items-center gap-2">
                      <Book className="h-4 w-4 text-neutral-400" />
                      <div>
                        <p className="text-xs text-neutral-500">Game System</p>
                        <p className="font-medium">{product.game_system}</p>
                      </div>
                    </div>
                  )}

                  {product.product_type && (
                    <div className="flex items-center gap-2">
                      <FileText className="h-4 w-4 text-neutral-400" />
                      <div>
                        <p className="text-xs text-neutral-500">Type</p>
                        <p className="font-medium">{product.product_type}</p>
                      </div>
                    </div>
                  )}

                  {product.publisher && (
                    <div className="flex items-center gap-2">
                      <Users className="h-4 w-4 text-neutral-400" />
                      <div>
                        <p className="text-xs text-neutral-500">Publisher</p>
                        <p className="font-medium">{product.publisher}</p>
                      </div>
                    </div>
                  )}

                  {product.publication_year && (
                    <div className="flex items-center gap-2">
                      <Calendar className="h-4 w-4 text-neutral-400" />
                      <div>
                        <p className="text-xs text-neutral-500">Year</p>
                        <p className="font-medium">{product.publication_year}</p>
                      </div>
                    </div>
                  )}

                  {product.page_count && (
                    <div className="flex items-center gap-2">
                      <FileText className="h-4 w-4 text-neutral-400" />
                      <div>
                        <p className="text-xs text-neutral-500">Pages</p>
                        <p className="font-medium">{product.page_count}</p>
                      </div>
                    </div>
                  )}

                  {(product.level_range_min || product.level_range_max) && (
                    <div className="flex items-center gap-2">
                      <Clock className="h-4 w-4 text-neutral-400" />
                      <div>
                        <p className="text-xs text-neutral-500">Level Range</p>
                        <p className="font-medium">
                          {product.level_range_min || '?'} - {product.level_range_max || '?'}
                        </p>
                      </div>
                    </div>
                  )}
                </div>

                {product.tags && product.tags.length > 0 && (
                  <div>
                    <p className="text-xs text-neutral-500 mb-2">Tags</p>
                    <div className="flex flex-wrap gap-2">
                      {product.tags.map((tag) => (
                        <span
                          key={tag.id}
                          className="rounded-full px-3 py-1 text-xs font-medium"
                          style={{
                            backgroundColor: tag.color ? `${tag.color}20` : '#e5e7eb',
                            color: tag.color || '#374151',
                          }}
                        >
                          {tag.name}
                        </span>
                      ))}
                    </div>
                  </div>
                )}

                <div className="flex gap-3 pt-4">
                  <button
                    onClick={() => setShowPdfViewer(true)}
                    className="inline-flex items-center gap-2 rounded-lg bg-purple-600 px-4 py-2 text-sm font-medium text-white hover:bg-purple-700"
                  >
                    <Eye className="h-4 w-4" />
                    View PDF
                  </button>
                  <button
                    onClick={openPdf}
                    className="inline-flex items-center gap-2 rounded-lg border border-neutral-300 bg-white px-4 py-2 text-sm font-medium text-neutral-700 hover:bg-neutral-50"
                  >
                    <ExternalLink className="h-4 w-4" />
                    Open in New Tab
                  </button>
                </div>
              </div>
            </div>
          ) : (
            <div 
              role="tabpanel"
              id="panel-text"
              aria-labelledby="tab-text"
              className="p-6"
            >
              {textLoading ? (
                <div className="flex items-center justify-center py-12">
                  <div className="h-8 w-8 animate-spin rounded-full border-4 border-purple-200 border-t-purple-600" />
                </div>
              ) : textError ? (
                <div className="rounded-lg border border-amber-200 bg-amber-50 p-4 text-center text-amber-700">
                  {textError}
                </div>
              ) : textContent ? (
                <div className="prose prose-sm max-w-none">
                  <pre className="whitespace-pre-wrap font-sans text-sm leading-relaxed text-neutral-700">
                    {textContent}
                  </pre>
                </div>
              ) : null}
            </div>
          )}
        </div>
      </div>

      {showPdfViewer && (
        <PDFViewer
          fileUrl={`/api/v1/products/${product.id}/pdf`}
          fileName={product.file_name || product.title || 'document.pdf'}
          onClose={() => setShowPdfViewer(false)}
        />
      )}
    </div>
  );
}
