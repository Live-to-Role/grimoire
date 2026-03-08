import { useState, useEffect, useCallback } from 'react';
import { useQuery } from '@tanstack/react-query';
import { FolderOpen, ChevronUp, X } from 'lucide-react';
import apiClient from '../api/client';

interface DirectoryEntry {
  name: string;
  path: string;
}

interface BrowseResponse {
  current_path: string;
  parent_path: string | null;
  directories: DirectoryEntry[];
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

  const { data, isLoading, error } = useQuery({
    queryKey: ['browse-directories', currentPath],
    queryFn: async () => {
      const params = currentPath ? { path: currentPath } : {};
      const res = await apiClient.get<BrowseResponse>('/folders/browse', { params });
      return res.data;
    },
    enabled: isOpen,
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
            {data?.current_path || 'Loading...'}
          </p>
        </div>

        {/* Directory listing */}
        <div className="flex-1 overflow-auto p-2">
          {isLoading && (
            <div className="py-8 text-center text-sm text-neutral-500">Loading...</div>
          )}
          {error && (
            <div className="py-8 text-center text-sm text-red-500">
              Failed to load directory. Check that the path is accessible.
            </div>
          )}
          {data && data.directories.length === 0 && (
            <div className="py-8 text-center text-sm text-neutral-500">
              No subdirectories found
            </div>
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
