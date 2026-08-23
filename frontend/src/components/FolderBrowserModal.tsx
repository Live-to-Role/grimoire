import { useState, useEffect, useCallback } from 'react';
import { useQuery } from '@tanstack/react-query';
import { FolderOpen, ChevronUp, X } from 'lucide-react';
import { AxiosError } from 'axios';
import apiClient from '../api/client';

interface DirectoryEntry {
  name: string;
  path: string;
}

interface QuickLocation {
  name: string;
  path: string;
}

interface BrowseResponse {
  current_path: string;
  parent_path: string | null;
  directories: DirectoryEntry[];
  locations?: QuickLocation[];
  skipped?: number;
}

/**
 * Turn a failed browse into something the user (or a bug report) can act on.
 * "Failed to load directory" alone never distinguished a missing path from an
 * unreadable one from a backend that had not finished starting.
 */
function describeBrowseError(error: unknown): string {
  const axiosError = error as AxiosError<{ detail?: string }>;

  if (axiosError?.response) {
    const detail = axiosError.response.data?.detail;
    if (detail) return detail;
    return `The server returned ${axiosError.response.status} ${axiosError.response.statusText}.`;
  }

  if (axiosError?.request) {
    return (
      'No response from the Grimoire API. It may still be starting up — ' +
      'wait a few seconds and try again.'
    );
  }

  return axiosError?.message || 'Could not load the directory.';
}

interface FolderBrowserModalProps {
  isOpen: boolean;
  onClose: () => void;
  onSelect: (path: string) => void;
}

export function FolderBrowserModal({ isOpen, onClose, onSelect }: FolderBrowserModalProps) {
  const [currentPath, setCurrentPath] = useState<string | undefined>(undefined);

  // Reset to home directory each time modal opens
  useEffect(() => {
    if (isOpen) {
      setCurrentPath(undefined);
    }
  }, [isOpen]);

  // Close on Escape key
  const handleKeyDown = useCallback((e: KeyboardEvent) => {
    if (e.key === 'Escape') onClose();
  }, [onClose]);

  useEffect(() => {
    if (isOpen) {
      document.addEventListener('keydown', handleKeyDown);
      return () => document.removeEventListener('keydown', handleKeyDown);
    }
  }, [isOpen, handleKeyDown]);

  const { data, isLoading, error, refetch, isFetching } = useQuery({
    queryKey: ['browse-directories', currentPath],
    queryFn: async () => {
      const params = currentPath ? { path: currentPath } : {};
      const res = await apiClient.get<BrowseResponse>('/folders/browse', { params });
      return res.data;
    },
    enabled: isOpen,
    // A missing or unreadable path is a settled answer; only retry transport
    // failures, which is what a still-starting backend looks like.
    retry: (failureCount, err) => failureCount < 2 && !(err as AxiosError).response,
  });

  if (!isOpen) return null;

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/50" onClick={onClose}>
      <div className="mx-4 flex max-h-[70vh] w-full max-w-lg flex-col overflow-hidden rounded-xl bg-white shadow-xl" onClick={(e) => e.stopPropagation()}>
        {/* Header */}
        <div className="flex items-center justify-between border-b border-neutral-200 px-4 py-3">
          <h2 className="text-lg font-semibold text-neutral-900">Select Folder</h2>
          <button
            onClick={onClose}
            className="p-1 text-neutral-400 hover:text-neutral-600"
          >
            <X className="h-5 w-5" />
          </button>
        </div>

        {/* Current path */}
        <div className="flex items-center gap-2 border-b border-neutral-100 bg-neutral-50 px-4 py-2">
          {data?.parent_path && (
            <button
              onClick={() => setCurrentPath(data.parent_path!)}
              className="rounded p-1 text-neutral-500 hover:bg-neutral-200 hover:text-neutral-700"
              title="Go to parent directory"
            >
              <ChevronUp className="h-4 w-4" />
            </button>
          )}
          <p className="min-w-0 flex-1 truncate text-sm text-neutral-600">
            {data?.current_path || (error ? 'Not loaded' : 'Loading...')}
          </p>
        </div>

        {/* Quick locations — in Docker these are the only paths that exist */}
        {!!data?.locations?.length && (
          <div className="flex flex-wrap gap-1.5 border-b border-neutral-100 px-4 py-2">
            {data.locations.map((loc) => (
              <button
                key={loc.path}
                onClick={() => setCurrentPath(loc.path)}
                title={loc.path}
                className="rounded-full border border-neutral-200 px-2.5 py-1 text-xs text-neutral-600 hover:border-purple-300 hover:bg-purple-50 hover:text-purple-700"
              >
                {loc.name}
              </button>
            ))}
          </div>
        )}

        {/* Directory listing */}
        <div className="flex-1 overflow-auto p-2">
          {isLoading && (
            <div className="py-8 text-center text-sm text-neutral-500">Loading...</div>
          )}
          {error && (
            <div className="px-4 py-8 text-center text-sm">
              <p className="font-medium text-red-600">Could not open this folder</p>
              <p className="mt-1 break-words text-neutral-600">{describeBrowseError(error)}</p>
              <button
                onClick={() => void refetch()}
                disabled={isFetching}
                className="mt-3 rounded-lg border border-neutral-300 px-3 py-1.5 text-xs font-medium text-neutral-700 hover:bg-neutral-50 disabled:opacity-50"
              >
                {isFetching ? 'Retrying…' : 'Try again'}
              </button>
            </div>
          )}
          {data && data.directories.length === 0 && (
            <div className="py-8 text-center text-sm text-neutral-500">
              No subdirectories found
            </div>
          )}
          {!!data?.skipped && (
            <p className="px-3 py-2 text-xs text-neutral-500">
              {data.skipped} item{data.skipped === 1 ? '' : 's'} skipped — the server could not
              read them.
            </p>
          )}
          {data?.directories.map((dir) => (
            <button
              key={dir.path}
              onClick={() => setCurrentPath(dir.path)}
              className="flex w-full items-center gap-2 rounded-lg px-3 py-2 text-left text-sm text-neutral-700 hover:bg-purple-50 hover:text-purple-700"
            >
              <FolderOpen className="h-4 w-4 flex-shrink-0 text-amber-500" />
              <span className="truncate">{dir.name}</span>
            </button>
          ))}
        </div>

        {/* Footer */}
        <div className="flex items-center justify-end gap-3 border-t border-neutral-200 px-4 py-3">
          <button
            onClick={onClose}
            className="rounded-lg border border-neutral-300 px-4 py-2 text-sm font-medium text-neutral-700 hover:bg-neutral-50"
          >
            Cancel
          </button>
          <button
            onClick={() => {
              if (data?.current_path) {
                onSelect(data.current_path);
                onClose();
              }
            }}
            disabled={!data?.current_path}
            className="rounded-lg bg-purple-600 px-4 py-2 text-sm font-medium text-white hover:bg-purple-700 disabled:opacity-50"
          >
            Select This Folder
          </button>
        </div>
      </div>
    </div>
  );
}
