import { useState } from 'react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { Library } from './pages/Library';
import { Settings } from './pages/Settings';
import { Campaigns } from './pages/Campaigns';
import { LibraryManagement } from './pages/LibraryManagement';
import { Sidebar } from './components/Sidebar';
import { ProcessingQueue } from './components/ProcessingQueue';

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
        />
        <main className="flex-1 overflow-hidden">
          {activeView === 'settings' ? (
            <Settings />
          ) : activeView === 'queue' ? (
            <ProcessingQueue onClose={() => setActiveView('library')} />
          ) : activeView === 'campaigns' ? (
            <Campaigns />
          ) : activeView === 'library-management' ? (
            <LibraryManagement />
          ) : (
            <Library
              selectedCollection={selectedCollection}
              selectedTag={selectedTag}
            />
          )}
        </main>
      </div>
    </QueryClientProvider>
  );
}

export default App;
