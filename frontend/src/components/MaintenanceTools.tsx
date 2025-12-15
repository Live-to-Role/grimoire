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
      default: 'border-neutral-200 hover:border-purple-300 hover:bg-purple-50',
      warning: 'border-amber-200 hover:border-amber-400 hover:bg-amber-50',
      danger: 'border-red-200 hover:border-red-400 hover:bg-red-50',
    };

    return (
      <button
        onClick={onClick}
        disabled={disabled || runAction.isPending}
        className={`flex items-start gap-3 rounded-lg border p-4 text-left transition-colors ${variantStyles[variant]} disabled:opacity-50 disabled:cursor-not-allowed`}
      >
        <Icon className={`h-5 w-5 mt-0.5 ${variant === 'danger' ? 'text-red-500' : variant === 'warning' ? 'text-amber-500' : 'text-purple-600'}`} />
        <div className="flex-1 min-w-0">
          <div className="font-medium text-neutral-900">{label}</div>
          <div className="text-sm text-neutral-500 mt-0.5">{description}</div>
        </div>
      </button>
    );
  };

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/50 p-4">
      <div className="flex h-[85vh] w-full max-w-3xl flex-col overflow-hidden rounded-xl bg-white shadow-2xl">
        <header className="flex items-center justify-between border-b border-neutral-200 px-6 py-4">
          <div className="flex items-center gap-3">
            <Wrench className="h-6 w-6 text-purple-600" />
            <h2 className="text-xl font-semibold text-neutral-900">Maintenance Tools</h2>
          </div>
          <button
            onClick={onClose}
            className="rounded-lg p-2 text-neutral-500 hover:bg-neutral-100"
          >
            <X className="h-5 w-5" />
          </button>
        </header>

        <div className="flex-1 overflow-y-auto p-6 space-y-6">
          {/* Status Cards */}
          <div className="grid grid-cols-2 gap-4">
            <div className="rounded-lg border border-neutral-200 p-4">
              <div className="flex items-center gap-2 text-sm font-medium text-neutral-500 mb-2">
                <Search className="h-4 w-4" />
                Full-Text Search Status
              </div>
              {ftsLoading ? (
                <Loader2 className="h-5 w-5 animate-spin text-neutral-400" />
              ) : ftsStats ? (
                <div className="space-y-1">
                  <div className="flex items-center gap-2">
                    {ftsStats.has_extracted_text_column ? (
                      <CheckCircle className="h-4 w-4 text-green-500" />
                    ) : (
                      <AlertTriangle className="h-4 w-4 text-amber-500" />
                    )}
                    <span className="text-sm">
                      {ftsStats.fts_table_exists ? 'FTS5 table exists' : 'FTS5 table missing'}
                    </span>
                  </div>
                  <div className="text-sm text-neutral-600">
                    {ftsStats.fts_indexed_count.toLocaleString()} indexed in FTS
                  </div>
                  <div className="text-sm text-neutral-600">
                    {ftsStats.need_indexing} need indexing
                  </div>
                  {ftsStats.issue && (
                    <div className="text-xs text-amber-600 mt-2">{ftsStats.issue}</div>
                  )}
                </div>
              ) : null}
            </div>

            <div className="rounded-lg border border-neutral-200 p-4">
              <div className="flex items-center gap-2 text-sm font-medium text-neutral-500 mb-2">
                <FileSearch className="h-4 w-4" />
                Text Extraction Status
              </div>
              {textLoading ? (
                <Loader2 className="h-5 w-5 animate-spin text-neutral-400" />
              ) : textStats ? (
                <div className="space-y-1">
                  <div className="text-sm text-neutral-600">
                    {textStats.extracted.toLocaleString()} extracted
                  </div>
                  <div className="text-sm text-neutral-600">
                    {textStats.need_extraction.toLocaleString()} need extraction
                  </div>
                  <div className="text-sm text-neutral-600">
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
                  <div className="font-medium text-sm">
                    {lastResult.error ? 'Error' : 'Success'}
                  </div>
                  <pre className="text-xs mt-1 whitespace-pre-wrap overflow-auto max-h-32">
                    {JSON.stringify(lastResult, null, 2)}
                  </pre>
                </div>
                <button
                  onClick={() => setLastResult(null)}
                  className="text-neutral-400 hover:text-neutral-600"
                >
                  <X className="h-4 w-4" />
                </button>
              </div>
            </div>
          )}

          {/* Loading Indicator */}
          {runAction.isPending && (
            <div className="flex items-center gap-2 text-purple-600">
              <Loader2 className="h-5 w-5 animate-spin" />
              <span className="text-sm">Running maintenance task...</span>
            </div>
          )}

          {/* FTS Tools */}
          <div>
            <h3 className="text-sm font-semibold text-neutral-700 mb-3 flex items-center gap-2">
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
            <h3 className="text-sm font-semibold text-neutral-700 mb-3 flex items-center gap-2">
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
            <h3 className="text-sm font-semibold text-neutral-700 mb-3 flex items-center gap-2">
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
            <h3 className="text-sm font-semibold text-neutral-700 mb-3 flex items-center gap-2">
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

        <footer className="flex items-center justify-between border-t border-neutral-200 px-6 py-4">
          <button
            onClick={() => {
              refetchFts();
              refetchText();
            }}
            className="inline-flex items-center gap-2 rounded-lg bg-neutral-100 px-4 py-2 text-sm font-medium text-neutral-700 hover:bg-neutral-200"
          >
            <RefreshCw className="h-4 w-4" />
            Refresh Status
          </button>
          <button
            onClick={onClose}
            className="rounded-lg bg-purple-600 px-4 py-2 text-sm font-medium text-white hover:bg-purple-700"
          >
            Done
          </button>
        </footer>
      </div>
    </div>
  );
}
