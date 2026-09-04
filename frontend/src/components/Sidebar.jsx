import { Sun, MapPin, Languages, Plus, X } from 'lucide-react'
import { Translations } from '../utils/translations'

export default function Sidebar({
  activeView,
  onNavigate,
  location,
  onOpenLocationPicker,
  language,
  onOpenLanguagePicker,
  favorites = [],
  sidebarOpen,
  onCloseSidebar,
  farmerMode = false,
  onToggleFarmerMode,
  selectedCrop = 'Cotton',
  onSelectCrop,
}) {
  const langCode = language?.code || 'en'

  const SidebarContent = (
    <>
      <div className="flex flex-col gap-6">
        {/* Top Logo & New Chat Button */}
        <div className="flex flex-col gap-3">
          <div className="flex items-center justify-between">
            <div
              className="flex items-center gap-2 cursor-pointer"
              onClick={() => {
                onNavigate('home')
                onCloseSidebar?.()
              }}
            >
              <div className="w-5.5 h-5.5 rounded-sm bg-accent/20 border border-accent/30 flex items-center justify-center">
                <Sun size={14} className="text-accent" />
              </div>
              <span className="font-bricolage text-xl font-bold tracking-tight text-white/95">
                WeatherGPT
              </span>
            </div>
            {/* Close button — only visible in mobile drawer */}
            <button
              type="button"
              onClick={onCloseSidebar}
              className="md:hidden p-1 text-white/50 hover:text-white transition-colors cursor-pointer"
              aria-label="Close sidebar"
            >
              <X className="w-4 h-4" />
            </button>
          </div>

          {/* New Chat Button */}
          <button
            type="button"
            onClick={() => {
              onNavigate('home')
              onCloseSidebar?.()
            }}
            className="w-full flex items-center justify-between px-3 py-2 rounded-lg border border-white/[0.06] bg-white/[0.03] hover:bg-white/[0.07] hover:border-white/15 text-white text-xs font-medium transition-all group cursor-pointer"
            id="sidebar-new-chat-btn"
          >
            <span className="flex items-center gap-2">
              <Plus className="w-3.5 h-3.5 text-white/70 group-hover:text-white transition-colors" />
              <span>{Translations.get(langCode, 'newChat') || 'New chat'}</span>
            </span>
            <span className="text-[10px] text-white/30 font-mono">⌘K</span>
          </button>
        </div>

        <div className="border-t border-dashed border-white/[0.06] pt-1" />

        {/* Welcome Copy */}
        <div className="flex flex-col gap-3 text-xs text-white/60 leading-relaxed">
          <p>{Translations.get(langCode, 'sidebarWelcome1')}</p>
          <p>{Translations.get(langCode, 'sidebarWelcome2')}</p>
          <p>{Translations.get(langCode, 'sidebarWelcome3')}</p>
          <p className="mt-1 text-white/40">{Translations.get(langCode, 'sidebarWelcome4')}</p>
        </div>

        {/* Farmer Advisory Mode Toggle & Crop Selector */}
        <div className="flex flex-col gap-2 p-2.5 rounded-lg border border-amber-500/20 bg-amber-500/5">
          <div className="flex items-center justify-between">
            <span className="text-xs font-bold text-amber-300 flex items-center gap-1.5">
              <span>🌾</span> Farmer Mode
            </span>
            <button
              type="button"
              onClick={() => onToggleFarmerMode?.(!farmerMode)}
              className={`w-9 h-5 flex items-center rounded-full p-0.5 transition-colors cursor-pointer ${
                farmerMode ? 'bg-amber-500' : 'bg-white/20'
              }`}
            >
              <div
                className={`w-4 h-4 rounded-full bg-white shadow-md transform transition-transform ${
                  farmerMode ? 'translate-x-4' : 'translate-x-0'
                }`}
              />
            </button>
          </div>

          {farmerMode && (
            <div className="flex flex-col gap-1.5 mt-1 pt-1.5 border-t border-amber-500/20">
              <label className="text-[10px] text-amber-200/80 font-medium">Select Crop:</label>
              <select
                value={selectedCrop}
                onChange={(e) => onSelectCrop?.(e.target.value)}
                className="w-full bg-neutral-900 border border-amber-500/30 text-amber-200 text-xs rounded-md px-2 py-1 focus:outline-none"
              >
                <option value="Cotton">Cotton (કપાસ / कपास)</option>
                <option value="Wheat">Wheat (ઘઉં / गेहूं)</option>
                <option value="Rice">Rice / Paddy (ડાંગર / धान)</option>
                <option value="Sugarcane">Sugarcane (શેરડી / गन्ना)</option>
                <option value="Groundnut">Groundnut (મગફળી / મૂંગફલી)</option>
                <option value="Mustard">Mustard (રાઈ / सरसों)</option>
                <option value="Vegetables">Vegetables (શાકભાજી / सब्जियां)</option>
                <option value="General Crops">General Crops</option>
              </select>
            </div>
          )}
        </div>

        {/* Navigation Items */}
        <div className="flex flex-col gap-1 mt-1">
          <span className="text-[10px] text-white/30 font-semibold uppercase tracking-wider mb-1 px-1">
            {Translations.get(langCode, 'views')}
          </span>
          {[
            { id: 'home', label: Translations.get(langCode, 'navWeather') || 'Weather' },
            { id: 'imd', label: 'IMD Official Hub (28 APIs)', badge: 'Priority 1' },
            { id: 'map', label: Translations.get(langCode, 'navMap') || 'Map' },
            { id: 'architecture', label: 'Architecture Map' },
            { id: 'dev', label: Translations.get(langCode, 'navDev') || 'Developer' },
          ].map((item) => {
            const isActive = activeView === item.id
            return (
              <button
                key={item.id}
                onClick={() => {
                  onNavigate(item.id)
                  onCloseSidebar?.()
                }}
                className={`flex items-center justify-between px-2.5 py-1.5 rounded text-xs cursor-pointer transition-colors ${
                  isActive
                    ? 'bg-white/10 text-white font-medium'
                    : 'text-white/60 hover:bg-white/5 hover:text-white'
                }`}
              >
                <span className="truncate">{item.label}</span>
                {item.badge && (
                  <span className="text-[9px] font-bold bg-amber-500/20 text-amber-300 border border-amber-500/30 px-1.5 py-0.2 rounded-full">
                    {item.badge}
                  </span>
                )}
              </button>
            )
          })}
        </div>
      </div>

      {/* Bottom Section — Location & Language */}
      <div className="flex flex-col gap-2 pt-4 border-t border-white/[0.06]">
        {/* Favorites Chips */}
        {favorites.length > 0 && (
          <div className="flex flex-wrap gap-1.5 mb-2">
            {favorites.slice(0, 4).map((f, i) => (
              <span
                key={i}
                className="text-[10px] text-white/50 bg-white/5 border border-white/[0.06] px-2 py-0.5 rounded-full"
              >
                {f.name}
              </span>
            ))}
          </div>
        )}

        {/* Location Picker */}
        {location && (
          <button
            onClick={onOpenLocationPicker}
            className="w-full flex items-center gap-2 px-3 py-2 rounded-lg border border-white/[0.06] bg-white/[0.03] hover:bg-white/[0.07] hover:border-white/15 text-white text-xs transition-all cursor-pointer"
          >
            <MapPin size={14} className="text-accent flex-shrink-0" />
            <span className="truncate flex-1 text-left font-medium">{location.name}</span>
            <span className="text-[10px] text-white/40">{Translations.get(langCode, 'change') || 'change'}</span>
          </button>
        )}

        {/* Language Picker */}
        {language && (
          <button
            onClick={onOpenLanguagePicker}
            className="w-full flex items-center gap-2 px-3 py-2 rounded-lg border border-white/[0.06] bg-white/[0.03] hover:bg-white/[0.07] hover:border-white/15 text-white text-xs transition-all cursor-pointer"
          >
            <Languages size={14} className="text-accent flex-shrink-0" />
            <span className="truncate flex-1 text-left font-medium">{language.native}</span>
            <span className="text-[10px] text-white/40">{Translations.get(langCode, 'change') || 'change'}</span>
          </button>
        )}
      </div>
    </>
  )

  return (
    <>
      {/* Mobile Sidebar Overlay */}
      {sidebarOpen && (
        <div
          className="fixed inset-0 z-40 bg-black/60 backdrop-blur-sm md:hidden"
          onClick={onCloseSidebar}
          aria-hidden="true"
        />
      )}

      {/* Sidebar — desktop always-visible / mobile drawer */}
      <aside
        className={`
          fixed inset-y-0 left-0 z-50 w-64 flex flex-col justify-between p-5
          border-r border-white/10 bg-black transition-transform duration-300 ease-in-out
          md:static md:translate-x-0 md:flex md:shrink-0
          ${sidebarOpen ? 'translate-x-0' : '-translate-x-full'}
        `}
      >
        {SidebarContent}
      </aside>
    </>
  )
}
