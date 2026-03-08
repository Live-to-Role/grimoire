import { useState, useRef, useEffect } from 'react';
import { ChevronDown, Plus, Check } from 'lucide-react';

interface ComboboxWithAddProps {
  value: string;
  onChange: (value: string) => void;
  options: string[];
  placeholder?: string;
  label?: string;
  className?: string;
}

export function ComboboxWithAdd({
  value,
  onChange,
  options,
  placeholder = 'Select or type...',
  className = '',
}: ComboboxWithAddProps) {
  const [isOpen, setIsOpen] = useState(false);
  const [search, setSearch] = useState('');
  const [highlightedIndex, setHighlightedIndex] = useState(-1);
  const containerRef = useRef<HTMLDivElement>(null);
  const inputRef = useRef<HTMLInputElement>(null);

  const filteredOptions = options.filter((opt) =>
    opt.toLowerCase().includes(search.toLowerCase())
  );

  const showAddOption =
    search.trim() !== '' &&
    !options.some((opt) => opt.toLowerCase() === search.toLowerCase().trim());

  const allOptions = showAddOption
    ? [{ type: 'add' as const, value: search.trim() }, ...filteredOptions.map(o => ({ type: 'existing' as const, value: o }))]
    : filteredOptions.map(o => ({ type: 'existing' as const, value: o }));

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

  const handleSelect = (selectedValue: string) => {
    onChange(selectedValue);
    setIsOpen(false);
    setSearch('');
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
        setHighlightedIndex((prev) =>
          prev < allOptions.length - 1 ? prev + 1 : prev
        );
        break;
      case 'ArrowUp':
        e.preventDefault();
        setHighlightedIndex((prev) => (prev > 0 ? prev - 1 : prev));
        break;
      case 'Enter':
        e.preventDefault();
        if (highlightedIndex >= 0 && allOptions[highlightedIndex]) {
          handleSelect(allOptions[highlightedIndex].value);
        } else if (showAddOption) {
          handleSelect(search.trim());
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
        className="flex items-center gap-1 rounded-sm border border-codex-tan bg-white px-3 py-2 text-sm focus-within:border-codex-olive focus-within:ring-1 focus-within:ring-codex-olive cursor-text"
        onClick={() => {
          setIsOpen(true);
          inputRef.current?.focus();
        }}
      >
        <input
          ref={inputRef}
          type="text"
          value={isOpen ? search : value}
          onChange={(e) => {
            setSearch(e.target.value);
            if (!isOpen) setIsOpen(true);
          }}
          onFocus={() => setIsOpen(true)}
          onKeyDown={handleKeyDown}
          placeholder={value || placeholder}
          className="flex-1 outline-none bg-transparent min-w-0"
        />
        <ChevronDown
          className={`h-4 w-4 text-primary-400 shrink-0 transition-transform ${isOpen ? 'rotate-180' : ''}`}
        />
      </div>

      {isOpen && (
        <div className="absolute z-50 mt-1 w-full rounded-sm border border-codex-tan bg-white shadow-lg max-h-60 overflow-auto">
          {allOptions.length === 0 && !showAddOption ? (
            <div className="px-3 py-2 text-sm text-primary-500">
              No options found
            </div>
          ) : (
            <ul role="listbox">
              {allOptions.map((option, index) => (
                <li
                  key={option.type === 'add' ? `add-${option.value}` : option.value}
                  role="option"
                  aria-selected={value === option.value}
                  className={`flex items-center gap-2 px-3 py-2 text-sm cursor-pointer ${
                    highlightedIndex === index
                      ? 'bg-codex-olive/20'
                      : 'hover:bg-primary-100'
                  } ${value === option.value ? 'font-medium' : ''}`}
                  onClick={() => handleSelect(option.value)}
                  onMouseEnter={() => setHighlightedIndex(index)}
                >
                  {option.type === 'add' ? (
                    <>
                      <Plus className="h-4 w-4 text-codex-olive" />
                      <span>
                        Add "<span className="font-medium">{option.value}</span>"
                      </span>
                    </>
                  ) : (
                    <>
                      {value === option.value ? (
                        <Check className="h-4 w-4 text-codex-olive" />
                      ) : (
                        <span className="w-4" />
                      )}
                      <span>{option.value}</span>
                    </>
                  )}
                </li>
              ))}
            </ul>
          )}
        </div>
      )}
    </div>
  );
}
