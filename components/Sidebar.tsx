'use client';


import { 
  LayoutGrid, 
  BarChart3, 
  Wallet, 
  CalendarDays, 
  Settings,
  Instagram,
  Facebook,
  Globe
} from 'lucide-react';

interface SidebarProps {
  activeView: string;
  onSelectView: (view: string) => void;
  onOpenEngineModal?: () => void;
}

export function Sidebar({ activeView, onSelectView, onOpenEngineModal }: SidebarProps) {
  const navItems = [
    { id: 'discover', label: 'Discover', icon: LayoutGrid },
    { id: 'assets', label: 'Assets', icon: BarChart3 },
    { id: 'funds', label: 'Funds', icon: Wallet },
    { id: 'calendar', label: 'Economic Calendar', icon: CalendarDays },
    { id: 'settings', label: 'Settings', icon: Settings },
  ];

  return (
    <aside className="w-full md:w-48 lg:w-44 flex flex-col justify-between shrink-0 space-y-4">
      
      {/* Top Nav items */}
      <div className="space-y-1">
        {navItems.map((item) => {
          const Icon = item.icon;
          const isActive = activeView === item.id;
          return (
            <button
              key={item.id}
              onClick={() => onSelectView(item.id)}
              className={`w-full flex items-center space-x-2.5 px-3 py-2.5 rounded-xl text-xs font-medium transition-all ${
                isActive
                  ? 'bg-[#111a16] text-white border border-[#1a2922] shadow-sm font-semibold'
                  : 'text-[#7f9389] hover:text-white hover:bg-[#111a16]/50'
              }`}
            >
              <Icon className={`w-3.5 h-3.5 shrink-0 ${isActive ? 'text-[#b5f542]' : 'text-[#7f9389]'}`} />
              <span className="truncate">{item.label}</span>
            </button>
          );
        })}
      </div>

      {/* Bottom Social Links */}
      <div className="pt-2">
        {/* Social Icons row */}
        <div className="flex items-center space-x-3 px-1 text-[#7f9389]">
          <button className="hover:text-white transition-colors" title="Instagram">
            <Instagram className="w-3.5 h-3.5" />
          </button>
          <button className="hover:text-white transition-colors" title="Discord">
            <Globe className="w-3.5 h-3.5" />
          </button>
          <button className="hover:text-white transition-colors" title="Social">
            <Facebook className="w-3.5 h-3.5" />
          </button>
        </div>
      </div>

    </aside>
  );
}
