import { useState, useCallback } from 'react';
import { Document, Page, pdfjs } from 'react-pdf';
import {
  X,
  ChevronLeft,
  ChevronRight,
  ZoomIn,
  ZoomOut,
  Download,
  RotateCw,
} from 'lucide-react';

import 'react-pdf/dist/Page/AnnotationLayer.css';
import 'react-pdf/dist/Page/TextLayer.css';

pdfjs.GlobalWorkerOptions.workerSrc = `//unpkg.com/pdfjs-dist@${pdfjs.version}/build/pdf.worker.min.mjs`;

interface PDFViewerProps {
  fileUrl: string;
  fileName: string;
  onClose: () => void;
}

export function PDFViewer({ fileUrl, fileName, onClose }: PDFViewerProps) {
  const [numPages, setNumPages] = useState<number>(0);
  const [pageNumber, setPageNumber] = useState<number>(1);
  const [scale, setScale] = useState<number>(1.0);
  const [rotation, setRotation] = useState<number>(0);
  const [isLoading, setIsLoading] = useState<boolean>(true);
  const [error, setError] = useState<string | null>(null);

  const onDocumentLoadSuccess = useCallback(({ numPages }: { numPages: number }) => {
    setNumPages(numPages);
    setIsLoading(false);
    setError(null);
  }, []);

  const onDocumentLoadError = useCallback((err: Error) => {
    setError(err.message);
    setIsLoading(false);
  }, []);

  const goToPrevPage = () => {
    setPageNumber((prev) => Math.max(prev - 1, 1));
  };

  const goToNextPage = () => {
    setPageNumber((prev) => Math.min(prev + 1, numPages));
  };

  const zoomIn = () => {
    setScale((prev) => Math.min(prev + 0.25, 3.0));
  };

  const zoomOut = () => {
    setScale((prev) => Math.max(prev - 0.25, 0.5));
  };

  const rotate = () => {
    setRotation((prev) => (prev + 90) % 360);
  };

  const handlePageInput = (e: React.ChangeEvent<HTMLInputElement>) => {
    const value = parseInt(e.target.value, 10);
    if (!isNaN(value) && value >= 1 && value <= numPages) {
      setPageNumber(value);
    }
  };

  const handleKeyDown = useCallback(
    (e: React.KeyboardEvent) => {
      if (e.key === 'ArrowLeft' || e.key === 'PageUp') {
        goToPrevPage();
      } else if (e.key === 'ArrowRight' || e.key === 'PageDown') {
        goToNextPage();
      } else if (e.key === 'Escape') {
        onClose();
      } else if (e.key === '+' || e.key === '=') {
        zoomIn();
      } else if (e.key === '-') {
        zoomOut();
      }
    },
    [numPages, onClose]
  );

  return (
    <div
      className="fixed inset-0 z-50 flex flex-col bg-neutral-900"
      onKeyDown={handleKeyDown}
      tabIndex={0}
    >
      {/* Header */}
      <header className="flex items-center justify-between border-b border-neutral-700 bg-neutral-800 px-4 py-2">
        <div className="flex items-center gap-4">
          <button
            onClick={onClose}
            className="rounded-lg p-2 text-neutral-400 hover:bg-neutral-700 hover:text-white"
            title="Close (Esc)"
          >
            <X className="h-5 w-5" />
          </button>
          <h1 className="max-w-md truncate text-sm font-medium text-white">{fileName}</h1>
        </div>

        {/* Controls */}
        <div className="flex items-center gap-2">
          {/* Zoom controls */}
          <div className="flex items-center gap-1 rounded-lg bg-neutral-700 px-2 py-1">
            <button
              onClick={zoomOut}
              disabled={scale <= 0.5}
              className="rounded p-1 text-neutral-300 hover:bg-neutral-600 hover:text-white disabled:opacity-50"
              title="Zoom out (-)"
            >
              <ZoomOut className="h-4 w-4" />
            </button>
            <span className="min-w-[4rem] text-center text-sm text-neutral-300">
              {Math.round(scale * 100)}%
            </span>
            <button
              onClick={zoomIn}
              disabled={scale >= 3.0}
              className="rounded p-1 text-neutral-300 hover:bg-neutral-600 hover:text-white disabled:opacity-50"
              title="Zoom in (+)"
            >
              <ZoomIn className="h-4 w-4" />
            </button>
          </div>

          {/* Rotate */}
          <button
            onClick={rotate}
            className="rounded-lg bg-neutral-700 p-2 text-neutral-300 hover:bg-neutral-600 hover:text-white"
            title="Rotate"
          >
            <RotateCw className="h-4 w-4" />
          </button>

          {/* Download */}
          <a
            href={fileUrl}
            download={fileName}
            className="rounded-lg bg-neutral-700 p-2 text-neutral-300 hover:bg-neutral-600 hover:text-white"
            title="Download"
          >
            <Download className="h-4 w-4" />
          </a>
        </div>
      </header>

      {/* PDF Content */}
      <div className="flex-1 overflow-auto bg-neutral-900">
        {isLoading && (
          <div className="flex h-full items-center justify-center">
            <div className="text-neutral-400">Loading PDF...</div>
          </div>
        )}

        {error && (
          <div className="flex h-full flex-col items-center justify-center gap-4">
            <div className="text-red-400">Failed to load PDF</div>
            <div className="text-sm text-neutral-500">{error}</div>
          </div>
        )}

        <div className="flex justify-center p-4">
          <Document
            file={fileUrl}
            onLoadSuccess={onDocumentLoadSuccess}
            onLoadError={onDocumentLoadError}
            loading={null}
            className="shadow-2xl"
          >
            <Page
              pageNumber={pageNumber}
              scale={scale}
              rotate={rotation}
              renderTextLayer={true}
              renderAnnotationLayer={true}
              className="bg-white"
            />
          </Document>
        </div>
      </div>

      {/* Footer - Page navigation */}
      <footer className="flex items-center justify-center gap-4 border-t border-neutral-700 bg-neutral-800 px-4 py-3">
        <button
          onClick={goToPrevPage}
          disabled={pageNumber <= 1}
          className="rounded-lg bg-neutral-700 p-2 text-neutral-300 hover:bg-neutral-600 hover:text-white disabled:opacity-50"
          title="Previous page (←)"
        >
          <ChevronLeft className="h-5 w-5" />
        </button>

        <div className="flex items-center gap-2 text-sm text-neutral-300">
          <span>Page</span>
          <input
            type="number"
            min={1}
            max={numPages}
            value={pageNumber}
            onChange={handlePageInput}
            className="w-16 rounded border border-neutral-600 bg-neutral-700 px-2 py-1 text-center text-white focus:border-purple-500 focus:outline-none"
          />
          <span>of {numPages}</span>
        </div>

        <button
          onClick={goToNextPage}
          disabled={pageNumber >= numPages}
          className="rounded-lg bg-neutral-700 p-2 text-neutral-300 hover:bg-neutral-600 hover:text-white disabled:opacity-50"
          title="Next page (→)"
        >
          <ChevronRight className="h-5 w-5" />
        </button>
      </footer>
    </div>
  );
}
