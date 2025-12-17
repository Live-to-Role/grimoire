import { useState } from 'react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { Sparkles } from 'lucide-react';
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
      <div className="flex h-screen flex-col bg-primary-100">
        {/* Top Header Bar - Codex style */}
        <header className="flex items-center justify-between bg-codex-olive px-6 py-3 shadow-md">
          <div className="flex items-center gap-3">
            <div className="flex h-8 w-8 items-center justify-center rounded bg-codex-dark">
              <Sparkles className="h-5 w-5 text-codex-cream" />
            </div>
            <h1 className="font-display text-xl font-semibold tracking-wide text-codex-cream">Grimoire</h1>
          </div>
          <div className="text-sm text-codex-tan">Your Personal TTRPG Library</div>
        </header>
        
        <div className="flex flex-1 overflow-hidden">
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
      </div>
    </QueryClientProvider>
  );
}

export default App;
