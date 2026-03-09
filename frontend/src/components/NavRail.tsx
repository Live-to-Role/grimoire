import {
  Library,
  BookOpen,
  FolderOpen,
  HardDrive,
  Wrench,
  Settings,
  Sun,
  Moon,
} from 'lucide-react';
import { useThemeContext } from '../contexts/ThemeContext';

interface NavRailProps {
  activeView: string;
  onViewChange: (view: string) => void;
  queueCount?: number;
}

const navItems = [
  { id: 'library', label: 'Library', icon: Library },
  { id: 'campaigns', label: 'Campaigns', icon: BookOpen },
  { id: 'library-management', label: 'Manage', icon: FolderOpen },
  { id: 'queue', label: 'Queue', icon: HardDrive },
  { id: 'tools', label: 'Tools', icon: Wrench },
];

export function NavRail({ activeView, onViewChange, queueCount }: NavRailProps) {
  const { effectiveTheme, toggleTheme } = useThemeContext();

  return (
    <nav
      className="hidden lg:flex flex-col items-center w-[72px] min-w-[72px] h-full border-r py-4"
      style={{
        backgroundColor: 'var(--color-surface)',
        borderColor: 'var(--color-border)',
      }}
    >
      {/* Title */}
      <div
        className="font-display text-sm font-semibold tracking-wider mb-4 select-none"
        style={{ color: 'var(--color-text-primary)' }}
      >
        G
      </div>

      {/* Nav items */}
      <div className="flex flex-col items-center gap-1 flex-1">
        {navItems.map((item) => {
          const isActive = activeView === item.id;
          const Icon = item.icon;
          return (
            <button
              key={item.id}
              onClick={() => onViewChange(item.id)}
              className="relative flex flex-col items-center justify-center w-16 h-16 rounded-lg transition-colors duration-150"
              style={{
                backgroundColor: isActive ? 'var(--color-accent-light)' : 'transparent',
                color: isActive ? 'var(--color-accent)' : 'var(--color-text-secondary)',
              }}
              onMouseEnter={(e) => {
                if (!isActive) e.currentTarget.style.backgroundColor = 'var(--color-surface-raised)';
              }}
              onMouseLeave={(e) => {
                if (!isActive) e.currentTarget.style.backgroundColor = 'transparent';
              }}
              title={item.label}
            >
              <Icon size={24} />
              <span className="text-[11px] mt-1 font-medium leading-none">{item.label}</span>
              {item.id === 'queue' && queueCount != null && queueCount > 0 && (
                <span
                  className="absolute top-1 right-1 flex items-center justify-center min-w-[18px] h-[18px] text-[10px] font-bold rounded-full text-white"
                  style={{ backgroundColor: 'var(--color-accent)' }}
                >
                  {queueCount > 99 ? '99+' : queueCount}
                </span>
              )}
            </button>
          );
        })}
      </div>

      {/* Divider */}
      <div
        className="w-10 h-px my-2"
        style={{ backgroundColor: 'var(--color-border)' }}
      />

      {/* Settings */}
      <button
        onClick={() => onViewChange('settings')}
        className="flex flex-col items-center justify-center w-16 h-16 rounded-lg transition-colors duration-150 mb-1"
        style={{
          backgroundColor: activeView === 'settings' ? 'var(--color-accent-light)' : 'transparent',
          color: activeView === 'settings' ? 'var(--color-accent)' : 'var(--color-text-secondary)',
        }}
        onMouseEnter={(e) => {
          if (activeView !== 'settings') e.currentTarget.style.backgroundColor = 'var(--color-surface-raised)';
        }}
        onMouseLeave={(e) => {
          if (activeView !== 'settings') e.currentTarget.style.backgroundColor = 'transparent';
        }}
        title="Settings"
      >
        <Settings size={24} />
        <span className="text-[11px] mt-1 font-medium leading-none">Settings</span>
      </button>

      {/* Theme toggle */}
      <button
        onClick={toggleTheme}
        className="flex items-center justify-center w-10 h-10 rounded-lg transition-colors duration-150"
        style={{ color: 'var(--color-text-secondary)' }}
        onMouseEnter={(e) => {
          e.currentTarget.style.backgroundColor = 'var(--color-surface-raised)';
        }}
        onMouseLeave={(e) => {
          e.currentTarget.style.backgroundColor = 'transparent';
        }}
        title={`Switch to ${effectiveTheme === 'light' ? 'dark' : 'light'} mode`}
      >
        {effectiveTheme === 'light' ? <Moon size={20} /> : <Sun size={20} />}
      </button>

      {/* Bottom tab bar for tablet (below lg) */}
    </nav>
  );
}

/** Bottom tab bar for tablet/mobile viewports */
export function NavBottomBar({ activeView, onViewChange, queueCount }: NavRailProps) {
  const { effectiveTheme, toggleTheme } = useThemeContext();

  const bottomItems = [
    ...navItems,
    { id: 'settings', label: 'Settings', icon: Settings },
  ];

  return (
    <nav
      className="lg:hidden fixed bottom-0 left-0 right-0 z-50 flex items-center justify-around h-14 border-t"
      style={{
        backgroundColor: 'var(--color-surface)',
        borderColor: 'var(--color-border)',
      }}
    >
      {bottomItems.map((item) => {
        const isActive = activeView === item.id;
        const Icon = item.icon;
        return (
          <button
            key={item.id}
            onClick={() => onViewChange(item.id)}
            className="relative flex flex-col items-center justify-center flex-1 h-full transition-colors duration-150"
            style={{
              color: isActive ? 'var(--color-accent)' : 'var(--color-text-secondary)',
            }}
            title={item.label}
          >
            <Icon size={20} />
            <span className="text-[10px] mt-0.5 font-medium">{item.label}</span>
            {item.id === 'queue' && queueCount != null && queueCount > 0 && (
              <span
                className="absolute top-1 right-1/4 flex items-center justify-center min-w-[16px] h-[16px] text-[9px] font-bold rounded-full text-white"
                style={{ backgroundColor: 'var(--color-accent)' }}
              >
                {queueCount > 99 ? '99+' : queueCount}
              </span>
            )}
          </button>
        );
      })}
      <button
        onClick={toggleTheme}
        className="flex flex-col items-center justify-center flex-1 h-full"
        style={{ color: 'var(--color-text-secondary)' }}
        title="Toggle theme"
      >
        {effectiveTheme === 'light' ? <Moon size={20} /> : <Sun size={20} />}
        <span className="text-[10px] mt-0.5 font-medium">Theme</span>
      </button>
    </nav>
  );
}
