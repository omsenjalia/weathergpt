import { Sun, MessageSquare, Map, Terminal, MapPin, Languages } from 'lucide-react'
import { Translations } from '../utils/translations'

const navItems = [
  { id: 'home', icon: Sun, translationKey: 'navWeather' },
  { id: 'chat', icon: MessageSquare, translationKey: 'navChat' },
  { id: 'map', icon: Map, translationKey: 'navMap' },
  { id: 'dev', icon: Terminal, translationKey: 'navDev' },
]

export default function Sidebar({
  activeView,
  onNavigate,
  location,
  onOpenLocationPicker,
  language,
  onOpenLanguagePicker,
}) {
  const langCode = language?.code || 'en'

  return (
    <aside className="w-64 lg:w-72 glass border-r border-white/10 hidden md:flex flex-col justify-between p-6 flex-shrink-0 z-30 h-full">
      <div className="flex flex-col gap-8">
        {/* Brand */}
        <div className="flex items-center gap-3 px-2">
          <div className="w-10 h-10 rounded-2xl bg-accent/20 border border-accent/40 flex items-center justify-center shadow-lg">
            <Sun className="text-accent" size={24} />
          </div>
          <div>
            <h1 className="text-white text-xl font-display font-bold tracking-tight">WeatherGPT</h1>
            <p className="text-white/40 text-xs font-medium">{Translations.get(langCode, 'multilingualWeatherAgent')}</p>
          </div>
        </div>

        {/* Navigation */}
        <nav className="flex flex-col gap-2">
          {navItems.map((item) => {
            const Icon = item.icon
            const isActive = activeView === item.id
            const label = Translations.get(langCode, item.translationKey)
            return (
              <button
                key={item.id}
                onClick={() => onNavigate(item.id)}
                className={`flex items-center gap-3.5 px-4 py-3 rounded-2xl cursor-pointer transition-all duration-200 ${
                  isActive
                    ? 'bg-accent/25 text-white border border-accent/40 shadow-md font-semibold'
                    : 'text-white/60 hover:text-white hover:bg-white/10 font-medium'
                }`}
              >
                <Icon className={isActive ? 'text-accent' : 'text-white/50'} size={20} />
                <span className="text-sm">{label}</span>
              </button>
            )
          })}
        </nav>
      </div>

      {/* Location & Language Controls */}
      <div className="flex flex-col gap-2.5">
        {location && (
          <button
            onClick={onOpenLocationPicker}
            className="glass rounded-2xl p-3 border border-white/10 flex items-center justify-between text-left hover:bg-white/10 transition-all cursor-pointer"
          >
            <div className="flex items-center gap-2">
              <MapPin size={16} className="text-accent flex-shrink-0" />
              <div>
                <p className="text-white text-xs font-bold truncate max-w-[130px]">{location.name}</p>
                <p className="text-white/40 text-[10px] truncate max-w-[130px]">{location.country || 'Active City'}</p>
              </div>
            </div>
            <span className="text-[10px] text-accent font-semibold underline">{Translations.get(langCode, 'change')}</span>
          </button>
        )}

        {language && (
          <button
            onClick={onOpenLanguagePicker}
            className="glass rounded-2xl p-3 border border-white/10 flex items-center justify-between text-left hover:bg-white/10 transition-all cursor-pointer"
          >
            <div className="flex items-center gap-2">
              <Languages size={16} className="text-accent flex-shrink-0" />
              <div>
                <p className="text-white text-xs font-bold truncate max-w-[130px]">{language.native}</p>
                <p className="text-white/40 text-[10px] truncate max-w-[130px]">{language.name}</p>
              </div>
            </div>
            <span className="text-[10px] text-accent font-semibold underline">{Translations.get(langCode, 'change')}</span>
          </button>
        )}

        <div className="glass rounded-2xl p-3 border border-white/10">
          <div className="flex items-center justify-between mb-1">
            <span className="text-accent text-[10px] font-semibold uppercase tracking-wider">{Translations.get(langCode, 'multilingualAi')}</span>
            <span className="w-2 h-2 rounded-full bg-emerald-400 animate-pulse" />
          </div>
          <p className="text-white/50 text-[11px] leading-relaxed">
            {Translations.get(langCode, 'tenLanguagesSupported')}
          </p>
        </div>
      </div>
    </aside>
  )
}
