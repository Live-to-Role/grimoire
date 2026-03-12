import { useState } from 'react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { ThemeProvider } from './contexts/ThemeContext';
import { Library } from './pages/Library';
import { Settings } from './pages/Settings';
import { Campaigns } from './pages/Campaigns';
import { Gallery } from './pages/Gallery';
import { LibraryManagement } from './pages/LibraryManagement';
import { NavRail, NavBottomBar } from './components/NavRail';
import { FilterDrawer } from './components/FilterDrawer';
import { ProcessingQueue } from './components/ProcessingQueue';
import { MaintenanceTools } from './components/MaintenanceTools';
import type { ProductFilters } from './api/products';

const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      refetchOnWindowFocus: false,
      retry: 1,
    },
  },
});

function App() {
  const [activeView, setActiveView] = useState('library');
  const [selectedCollection, setSelectedCollection] = useState<number | null>(null);
  const [selectedTag, setSelectedTag] = useState<number | null>(null);
  const [sidebarFilters, setSidebarFilters] = useState<Partial<ProductFilters>>({});
  const [filterDrawerOpen, setFilterDrawerOpen] = useState(false);

  const handleFilterChange = (filterType: keyof ProductFilters, value: string | null) => {
    setSidebarFilters(prev => {
      if (value === null) {
        const { [filterType]: _, ...rest } = prev;
        return rest;
      }
      return { ...prev, [filterType]: value };
    });
    setSelectedCollection(null);
    setSelectedTag(null);
  };

  const clearAllFilters = () => {
    setSidebarFilters({});
    setSelectedCollection(null);
    setSelectedTag(null);
  };

  const activeFilterCount = Object.keys(sidebarFilters).filter(
    k => !['page', 'per_page', 'sort', 'order'].includes(k)
  ).length + (selectedCollection ? 1 : 0) + (selectedTag ? 1 : 0);

  return (
    <QueryClientProvider client={queryClient}>
      <ThemeProvider>
        <div className="flex h-screen" style={{ backgroundColor: 'var(--color-bg)' }}>
          <NavRail activeView={activeView} onViewChange={setActiveView} />
          <main className="flex-1 overflow-hidden pb-14 lg:pb-0">
            {activeView === 'settings' ? (
              <Settings />
            ) : activeView === 'queue' ? (
              <ProcessingQueue onClose={() => setActiveView('library')} />
            ) : activeView === 'tools' ? (
              <MaintenanceTools onClose={() => setActiveView('library')} />
            ) : activeView === 'campaigns' ? (
              <Campaigns />
            ) : activeView === 'gallery' ? (
              <Gallery />
            ) : activeView === 'library-management' ? (
              <LibraryManagement />
            ) : (
              <Library
                selectedCollection={selectedCollection}
                selectedTag={selectedTag}
                sidebarFilters={sidebarFilters}
                onOpenFilters={() => setFilterDrawerOpen(true)}
                activeFilterCount={activeFilterCount}
              />
            )}
          </main>
          <NavBottomBar activeView={activeView} onViewChange={setActiveView} />
          <FilterDrawer
            isOpen={filterDrawerOpen}
            onClose={() => setFilterDrawerOpen(false)}
            onFilterChange={handleFilterChange}
            activeFilters={sidebarFilters}
            onClearFilters={clearAllFilters}
            selectedCollection={selectedCollection}
            onSelectCollection={setSelectedCollection}
            selectedTag={selectedTag}
            onSelectTag={setSelectedTag}
          />
        </div>
      </ThemeProvider>
    </QueryClientProvider>
  );
}

export default App;
