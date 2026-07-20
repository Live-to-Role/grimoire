import { useState, useRef, useEffect } from 'react';
import { ChevronDown, Check, X } from 'lucide-react';

export interface MultiComboboxOption {
  id: number;
  label: string;
  count?: number;
}

interface MultiComboboxProps {
  options: MultiComboboxOption[];
  selectedIds: number[];
  onChange: (ids: number[]) => void;
  placeholder?: string;
  emptyLabel?: string;
  className?: string;
}

/**
 * Searchable multi-select. Sibling of ComboboxWithAdd rather than a mode of
 * it: the value type, trigger rendering, close-on-pick behaviour and add-new
 * path all differ, and ComboboxWithAdd is load-bearing in ProductDetail.
 */
export function MultiCombobox({
  options,
  selectedIds,
  onChange,
  placeholder = 'Search...',
  emptyLabel = 'All',
  className = '',
}: MultiComboboxProps) {
  const [isOpen, setIsOpen] = useState(false);
  const [search, setSearch] = useState('');
  const [highlightedIndex, setHighlightedIndex] = useState(-1);
  const containerRef = useRef<HTMLDivElement>(null);
  const inputRef = useRef<HTMLInputElement>(null);

  const filtered = options.filter((o) =>
    o.label.toLowerCase().includes(search.toLowerCase())
  );
  const selected = options.filter((o) => selectedIds.includes(o.id));

  useEffect(() => {
    const handleClickOutside = (e: MouseEvent) => {
      if (containerRef.current && !containerRef.current.contains(e.target as Node)) {
        setIsOpen(false);
        setSearch('');
      }
    };
    document.addEventListener('mousedown', handleClickOutside);
    return () => document.removeEventListener('mousedown', handleClickOutside);
  }, []);

  useEffect(() => {
    setHighlightedIndex(-1);
  }, [search, isOpen]);

  const toggle = (id: number) => {
    // Stays open: picking several books in a row is the normal case.
    onChange(selectedIds.includes(id) ? selectedIds.filter((x) => x !== id) : [...selectedIds, id]);
  };

  const handleKeyDown = (e: React.KeyboardEvent) => {
    if (!isOpen) {
      if (e.key === 'ArrowDown' || e.key === 'Enter') {
        setIsOpen(true);
        e.preventDefault();
      }
      return;
    }
    switch (e.key) {
      case 'ArrowDown':
        e.preventDefault();
        setHighlightedIndex((prev) => (prev < filtered.length - 1 ? prev + 1 : prev));
        break;
      case 'ArrowUp':
        e.preventDefault();
        setHighlightedIndex((prev) => (prev > 0 ? prev - 1 : prev));
        break;
      case 'Enter':
        e.preventDefault();
        if (highlightedIndex >= 0 && filtered[highlightedIndex]) {
          toggle(filtered[highlightedIndex].id);
        }
        break;
      case 'Backspace':
        // Only when the box is empty, so it never eats a character mid-search.
        if (search === '' && selectedIds.length > 0) {
          onChange(selectedIds.slice(0, -1));
        }
        break;
      case 'Escape':
        setIsOpen(false);
        setSearch('');
        break;
    }
  };

  return (
    <div ref={containerRef} className={`relative ${className}`}>
      <div
        className="flex items-center gap-1 flex-wrap rounded-md px-2 py-1 text-sm cursor-text"
        style={{
          backgroundColor: 'var(--color-surface)',
          border: '1px solid var(--color-border)',
          minHeight: '34px',
        }}
        onClick={() => {
          setIsOpen(true);
          inputRef.current?.focus();
        }}
      >
        {selected.map((option) => (
          <span
            key={option.id}
            className="inline-flex items-center gap-1 px-1.5 rounded text-xs"
            style={{ border: '1px solid var(--color-border)', color: 'var(--color-text-primary)' }}
          >
            {option.label}
            <button
              type="button"
              aria-label={`Remove ${option.label}`}
              onClick={(e) => {
                e.stopPropagation();
                onChange(selectedIds.filter((x) => x !== option.id));
              }}
            >
              <X size={12} />
            </button>
          </span>
        ))}
        <input
          ref={inputRef}
          type="text"
          value={search}
          onChange={(e) => {
            setSearch(e.target.value);
            if (!isOpen) setIsOpen(true);
          }}
          onFocus={() => setIsOpen(true)}
          onKeyDown={handleKeyDown}
          placeholder={selected.length === 0 ? emptyLabel : placeholder}
          className="flex-1 outline-none bg-transparent min-w-[80px]"
          style={{ color: 'var(--color-text-primary)' }}
        />
        <ChevronDown
          className={`shrink-0 transition-transform ${isOpen ? 'rotate-180' : ''}`}
          size={14}
          style={{ color: 'var(--color-text-secondary)' }}
        />
      </div>

      {isOpen && (
        <div
          className="absolute z-50 mt-1 w-full rounded-md shadow-lg max-h-60 overflow-auto"
          style={{
            backgroundColor: 'var(--color-surface)',
            border: '1px solid var(--color-border)',
          }}
        >
          {filtered.length === 0 ? (
            <div className="px-3 py-2 text-sm" style={{ color: 'var(--color-text-secondary)' }}>
              No matches
            </div>
          ) : (
            <ul role="listbox" aria-multiselectable="true">
              {filtered.map((option, index) => {
                const isSelected = selectedIds.includes(option.id);
                return (
                  <li
                    key={option.id}
                    role="option"
                    aria-selected={isSelected}
                    className="flex items-center gap-2 px-3 py-1.5 text-sm cursor-pointer"
                    style={{
                      backgroundColor:
                        highlightedIndex === index ? 'var(--color-accent-light)' : 'transparent',
                      color: 'var(--color-text-primary)',
                    }}
                    onClick={() => toggle(option.id)}
                    onMouseEnter={() => setHighlightedIndex(index)}
                  >
                    {isSelected ? (
                      <Check size={14} style={{ color: 'var(--color-accent)' }} />
                    ) : (
                      <span className="w-[14px]" />
                    )}
                    <span className="flex-1">{option.label}</span>
                    {option.count !== undefined && (
                      <span className="text-xs" style={{ color: 'var(--color-text-secondary)' }}>
                        {option.count}
                      </span>
                    )}
                  </li>
                );
              })}
            </ul>
          )}
        </div>
      )}
    </div>
  );
}
