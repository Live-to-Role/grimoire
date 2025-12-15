import { useState } from 'react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { Library } from './pages/Library';
import { Settings } from './pages/Settings';
import { Campaigns } from './pages/Campaigns';
import { LibraryManagement } from './pages/LibraryManagement';
import { Sidebar } from './components/Sidebar';
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

  return (
    <QueryClientProvider client={queryClient}>
      <div className="flex h-screen bg-neutral-50">
        <Sidebar
          activeView={activeView}
          onViewChange={setActiveView}
          onCollectionSelect={setSelectedCollection}
          onTagSelect={setSelectedTag}
          selectedCollection={selectedCollection}
          selectedTag={selectedTag}
          onFilterChange={handleFilterChange}
          activeFilters={sidebarFilters}
          onClearFilters={clearAllFilters}
        />
        <main className="flex-1 overflow-hidden">
          {activeView === 'settings' ? (
            <Settings />
          ) : activeView === 'queue' ? (
            <ProcessingQueue onClose={() => setActiveView('library')} />
          ) : activeView === 'tools' ? (
            <MaintenanceTools onClose={() => setActiveView('library')} />
          ) : activeView === 'campaigns' ? (
            <Campaigns />
          ) : activeView === 'library-management' ? (
            <LibraryManagement />
          ) : (
            <Library
              selectedCollection={selectedCollection}
              selectedTag={selectedTag}
              sidebarFilters={sidebarFilters}
            />
          )}
        </main>
      </div>
    </QueryClientProvider>
  );
}

export default App;
