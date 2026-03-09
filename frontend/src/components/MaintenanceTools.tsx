import { useState } from 'react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import {
  X,
  Wrench,
  RefreshCw,
  Database,
  Image,
  FileSearch,
  AlertTriangle,
  CheckCircle,
  Loader2,
  HardDrive,
  Search,
  Trash2,
} from 'lucide-react';
import api from '../api/client';

interface MaintenanceToolsProps {
  onClose: () => void;
}

interface FTSStats {
  fts_table_exists: boolean;
  fts_schema: string[] | string;
  fts_indexed_count: number;
  has_extracted_text_column: boolean;
  indexed: number;
  need_indexing: number;
  total_with_text: number;
  issue: string | null;
}

interface TextExtractionStats {
  need_extraction: number;
  extracted: number;
  total: number;
  queue_pending: number;
  queue_processing: number;
}

interface ActionResult {
  success?: boolean;
  message?: string;
  error?: string;
  [key: string]: unknown;
}

export function MaintenanceTools({ onClose }: MaintenanceToolsProps) {
  const [lastResult, setLastResult] = useState<ActionResult | null>(null);
  const queryClient = useQueryClient();

  const { data: ftsStats, isLoading: ftsLoading, refetch: refetchFts } = useQuery<FTSStats>({
    queryKey: ['fts-stats'],
    queryFn: async () => {
      const res = await api.get('/queue/fts/stats');
      return res.data;
    },
  });

  const { data: textStats, isLoading: textLoading, refetch: refetchText } = useQuery<TextExtractionStats>({
    queryKey: ['text-extraction-stats'],
    queryFn: async () => {
      const res = await api.get('/queue/text-extraction/stats');
      return res.data;
    },
  });

  const runAction = useMutation({
    mutationFn: async ({ method, url, params }: { method: 'get' | 'post' | 'delete'; url: string; params?: Record<string, unknown> }) => {
      const res = method === 'delete'
        ? await api.delete(url, { params })
        : method === 'post'
        ? await api.post(url, null, { params })
        : await api.get(url, { params });
      return res.data;
    },
    onSuccess: (data) => {
      setLastResult(data);
      queryClient.invalidateQueries({ queryKey: ['fts-stats'] });
      queryClient.invalidateQueries({ queryKey: ['text-extraction-stats'] });
      queryClient.invalidateQueries({ queryKey: ['queue-stats'] });
      queryClient.invalidateQueries({ queryKey: ['library-stats'] });
    },
    onError: (error: Error) => {
      setLastResult({ success: false, error: error.message });
    },
  });

  const ToolButton = ({
    icon: Icon,
    label,
    description,
    onClick,
    variant = 'default',
    disabled = false,
  }: {
    icon: React.ElementType;
    label: string;
    description: string;
    onClick: () => void;
    variant?: 'default' | 'warning' | 'danger';
    disabled?: boolean;
  }) => {
    const variantStyles = {
      default: '',
      warning: 'border-amber-200 hover:border-amber-400 hover:bg-amber-50',
      danger: 'border-red-200 hover:border-red-400 hover:bg-red-50',
    };

    const defaultStyle = variant === 'default' ? {
      borderColor: 'var(--color-border)',
    } : {};

    return (
      <button
        onClick={onClick}
        disabled={disabled || runAction.isPending}
        className={`flex items-start gap-3 rounded-lg border p-4 text-left transition-colors min-h-[48px] ${variantStyles[variant]} disabled:opacity-50 disabled:cursor-not-allowed`}
        style={defaultStyle}
        onMouseEnter={(e) => {
          if (variant === 'default') {
            e.currentTarget.style.borderColor = 'var(--color-accent)';
            e.currentTarget.style.backgroundColor = 'color-mix(in srgb, var(--color-accent) 8%, transparent)';
          }
        }}
        onMouseLeave={(e) => {
          if (variant === 'default') {
            e.currentTarget.style.borderColor = 'var(--color-border)';
            e.currentTarget.style.backgroundColor = '';
          }
        }}
      >
        <Icon
          className={`h-5 w-5 mt-0.5 ${variant === 'danger' ? 'text-red-500' : variant === 'warning' ? 'text-amber-500' : ''}`}
          style={variant === 'default' ? { color: 'var(--color-accent)' } : undefined}
        />
        <div className="flex-1 min-w-0">
          <div className="font-medium text-lg" style={{ color: 'var(--color-text-primary)' }}>{label}</div>
          <div className="text-base mt-0.5" style={{ color: 'var(--color-text-secondary)' }}>{description}</div>
        </div>
      </button>
    );
  };

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/50 p-4">
      <div
        className="flex h-[85vh] w-full max-w-3xl flex-col overflow-hidden rounded-xl shadow-2xl"
        style={{ backgroundColor: 'var(--color-surface)' }}
      >
        <header
          className="flex items-center justify-between border-b px-6 py-4"
          style={{ borderColor: 'var(--color-border)' }}
        >
          <div className="flex items-center gap-3">
            <Wrench className="h-6 w-6" style={{ color: 'var(--color-accent)' }} />
            <h2 className="text-xl font-semibold" style={{ color: 'var(--color-text-primary)' }}>Maintenance Tools</h2>
          </div>
          <button
            onClick={onClose}
            className="rounded-lg flex items-center justify-center"
            style={{ color: 'var(--color-text-secondary)', width: 44, height: 44 }}
          >
            <X className="h-5 w-5" />
          </button>
        </header>

        <div className="flex-1 overflow-y-auto p-6 space-y-6">
          {/* Status Cards */}
          <div className="grid grid-cols-2 gap-4">
            <div className="rounded-lg border p-4" style={{ borderColor: 'var(--color-border)' }}>
              <div className="flex items-center gap-2 text-base font-medium mb-2" style={{ color: 'var(--color-text-secondary)' }}>
                <Search className="h-4 w-4" />
                Full-Text Search Status
              </div>
              {ftsLoading ? (
                <Loader2 className="h-5 w-5 animate-spin" style={{ color: 'var(--color-text-secondary)' }} />
              ) : ftsStats ? (
                <div className="space-y-1">
                  <div className="flex items-center gap-2">
                    {ftsStats.has_extracted_text_column ? (
                      <CheckCircle className="h-4 w-4 text-green-500" />
                    ) : (
                      <AlertTriangle className="h-4 w-4 text-amber-500" />
                    )}
                    <span className="text-lg" style={{ color: 'var(--color-text-primary)' }}>
                      {ftsStats.fts_table_exists ? 'FTS5 table exists' : 'FTS5 table missing'}
                    </span>
                  </div>
                  <div className="text-lg" style={{ color: 'var(--color-text-primary)' }}>
                    {ftsStats.fts_indexed_count.toLocaleString()} indexed in FTS
                  </div>
                  <div className="text-lg" style={{ color: 'var(--color-text-primary)' }}>
                    {ftsStats.need_indexing} need indexing
                  </div>
                  {ftsStats.issue && (
                    <div className="text-base text-amber-600 mt-2">{ftsStats.issue}</div>
                  )}
                </div>
              ) : null}
            </div>

            <div className="rounded-lg border p-4" style={{ borderColor: 'var(--color-border)' }}>
              <div className="flex items-center gap-2 text-base font-medium mb-2" style={{ color: 'var(--color-text-secondary)' }}>
                <FileSearch className="h-4 w-4" />
                Text Extraction Status
              </div>
              {textLoading ? (
                <Loader2 className="h-5 w-5 animate-spin" style={{ color: 'var(--color-text-secondary)' }} />
              ) : textStats ? (
                <div className="space-y-1">
                  <div className="text-lg" style={{ color: 'var(--color-text-primary)' }}>
                    {textStats.extracted.toLocaleString()} extracted
                  </div>
                  <div className="text-lg" style={{ color: 'var(--color-text-primary)' }}>
                    {textStats.need_extraction.toLocaleString()} need extraction
                  </div>
                  <div className="text-lg" style={{ color: 'var(--color-text-primary)' }}>
                    {textStats.queue_pending} pending, {textStats.queue_processing} processing
                  </div>
                </div>
              ) : null}
            </div>
          </div>

          {/* Result Display */}
          {lastResult && (
            <div className={`rounded-lg p-4 ${lastResult.error ? 'bg-red-50 border border-red-200' : 'bg-green-50 border border-green-200'}`}>
              <div className="flex items-start gap-2">
                {lastResult.error ? (
                  <AlertTriangle className="h-5 w-5 text-red-500 mt-0.5" />
                ) : (
                  <CheckCircle className="h-5 w-5 text-green-500 mt-0.5" />
                )}
                <div className="flex-1 min-w-0">
                  <div className="font-medium text-base">
                    {lastResult.error ? 'Error' : 'Success'}
                  </div>
                  <pre className="text-sm mt-1 whitespace-pre-wrap overflow-auto max-h-32">
                    {JSON.stringify(lastResult, null, 2)}
                  </pre>
                </div>
                <button
                  onClick={() => setLastResult(null)}
                  style={{ color: 'var(--color-text-secondary)' }}
                >
                  <X className="h-4 w-4" />
                </button>
              </div>
            </div>
          )}

          {/* Loading Indicator */}
          {runAction.isPending && (
            <div className="flex items-center gap-2" style={{ color: 'var(--color-accent)' }}>
              <Loader2 className="h-5 w-5 animate-spin" />
              <span className="text-base">Running maintenance task...</span>
            </div>
          )}

          {/* FTS Tools */}
          <div>
            <h3 className="text-xl font-semibold mb-3 flex items-center gap-2" style={{ color: 'var(--color-text-primary)' }}>
              <Database className="h-4 w-4" />
              Full-Text Search
            </h3>
            <div className="grid gap-3">
              <ToolButton
                icon={RefreshCw}
                label="Rebuild FTS Index"
                description="Queue all products with extracted text for FTS indexing"
                onClick={() => runAction.mutate({ method: 'post', url: '/queue/fts/rebuild-all' })}
              />
              <ToolButton
                icon={Database}
                label="Recreate FTS Table"
                description="Drop and recreate FTS5 table with correct schema (fixes missing columns)"
                onClick={() => runAction.mutate({ method: 'post', url: '/queue/fts/recreate' })}
                variant="warning"
              />
            </div>
          </div>

          {/* Cover Image Tools */}
          <div>
            <h3 className="text-xl font-semibold mb-3 flex items-center gap-2" style={{ color: 'var(--color-text-primary)' }}>
              <Image className="h-4 w-4" />
              Cover Images
            </h3>
            <div className="grid gap-3">
              <ToolButton
                icon={Image}
                label="Extract Missing Covers"
                description="Queue cover extraction for products without covers"
                onClick={() => runAction.mutate({ method: 'post', url: '/library/maintenance/extract-covers' })}
              />
              <ToolButton
                icon={RefreshCw}
                label="Fix Missing Cover Files"
                description="Reset cover status for products with missing cover files and re-extract"
                onClick={() => runAction.mutate({ method: 'post', url: '/library/maintenance/fix-covers' })}
              />
            </div>
          </div>

          {/* File System Tools */}
          <div>
            <h3 className="text-xl font-semibold mb-3 flex items-center gap-2" style={{ color: 'var(--color-text-primary)' }}>
              <HardDrive className="h-4 w-4" />
              File System
            </h3>
            <div className="grid gap-3">
              <ToolButton
                icon={FileSearch}
                label="Mark Missing Files"
                description="Scan library and mark products whose PDF files no longer exist"
                onClick={() => runAction.mutate({ method: 'post', url: '/library/maintenance/mark-missing' })}
              />
            </div>
          </div>

          {/* Queue Tools */}
          <div>
            <h3 className="text-xl font-semibold mb-3 flex items-center gap-2" style={{ color: 'var(--color-text-primary)' }}>
              <RefreshCw className="h-4 w-4" />
              Processing Queue
            </h3>
            <div className="grid gap-3">
              <ToolButton
                icon={RefreshCw}
                label="Reset Stuck Items"
                description="Reset items stuck in 'processing' status back to pending"
                onClick={() => runAction.mutate({ method: 'post', url: '/library/maintenance/reset-stuck', params: { timeout_minutes: 5 } })}
              />
              <ToolButton
                icon={RefreshCw}
                label="Retry All Failed"
                description="Reset all failed queue items to pending for retry"
                onClick={() => runAction.mutate({ method: 'post', url: '/queue/retry-all-failed' })}
              />
              <ToolButton
                icon={Trash2}
                label="Clear Failed Items"
                description="Permanently delete all failed queue items"
                onClick={() => runAction.mutate({ method: 'delete', url: '/queue', params: { status: 'failed' } })}
                variant="danger"
              />
              <ToolButton
                icon={Trash2}
                label="Clear Completed Items"
                description="Remove completed items from the queue"
                onClick={() => runAction.mutate({ method: 'delete', url: '/queue', params: { status: 'completed' } })}
              />
            </div>
          </div>
        </div>

        <footer
          className="flex items-center justify-between border-t px-6 py-4"
          style={{ borderColor: 'var(--color-border)' }}
        >
          <button
            onClick={() => {
              refetchFts();
              refetchText();
            }}
            className="inline-flex items-center gap-2 rounded-lg px-4 py-2 text-base font-medium"
            style={{
              backgroundColor: 'var(--color-surface-alt, var(--color-border))',
              color: 'var(--color-text-primary)',
            }}
          >
            <RefreshCw className="h-4 w-4" />
            Refresh Status
          </button>
          <button
            onClick={onClose}
            className="rounded-lg px-4 py-2 text-base font-medium text-white"
            style={{ backgroundColor: 'var(--color-accent)' }}
          >
            Done
          </button>
        </footer>
      </div>
    </div>
  );
}
