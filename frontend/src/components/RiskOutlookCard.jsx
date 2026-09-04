import { ShieldAlert, CheckCircle2, AlertTriangle, CloudRain, Sun, Wind } from 'lucide-react'
import { Translations, formatDay, translateCondition } from '../utils/translations'

export function evaluateDayRisk(dayData, langCode = 'en') {
  const t = (key) => Translations.get(langCode, key)
  const maxTemp = dayData.max ?? 25
  const minTemp = dayData.min ?? 18
  const rainProb = dayData.rainProb ?? 0
  const rainSum = dayData.rainSum ?? 0
  const windSpeed = dayData.maxWind ?? dayData.windSpeed ?? 0
  const code = dayData.code ?? 0

  // 1. RED HAZARD CRITERIA (Extreme / High Risk)
  if (code >= 95 || rainSum >= 50 || rainProb >= 85 || maxTemp >= 44 || windSpeed >= 50) {
    let title = 'Severe Weather Hazard'
    let desc = 'Extreme weather conditions. Stay indoors and defer field activities.'
    if (code >= 95) { title = 'Severe Thunderstorm Danger'; desc = 'Lightning hazard & squalls expected.' }
    else if (maxTemp >= 44) { title = 'Extreme Severe Heatwave'; desc = 'High heat stroke risk. Do not work outdoors at midday.' }
    else if (rainSum >= 50 || rainProb >= 85) { title = 'Heavy Downpour Warning'; desc = 'Flooding risk. Stop irrigation & secure crops.' }
    else if (windSpeed >= 50) { title = 'High Wind Hazard'; desc = 'Damage to temporary structures possible.' }

    return {
      level: 'RED',
      color: '#ef4444',
      badgeBg: 'bg-rose-500/20 text-rose-300 border-rose-500/40',
      icon: ShieldAlert,
      title,
      desc,
      rainProb,
      maxTemp,
      minTemp,
    }
  }

  // 2. YELLOW RISK CRITERIA (Moderate Risk / Watch)
  if (code >= 51 || rainSum >= 15 || rainProb >= 45 || maxTemp >= 40 || windSpeed >= 30) {
    let title = 'Weather Watch'
    let desc = 'Unsettled weather. Keep track of forecasts.'
    if (maxTemp >= 40) { title = 'Heatwave Advisory'; desc = 'High temperatures. Ensure adequate hydration.' }
    else if (rainProb >= 45 || rainSum >= 15) { title = 'Rain Expected'; desc = 'Carry umbrella & delay pesticide spraying.' }
    else if (windSpeed >= 30) { title = 'Breezy Conditions'; desc = 'Moderate wind. Mind loose objects.' }

    return {
      level: 'YELLOW',
      color: '#f59e0b',
      badgeBg: 'bg-amber-500/20 text-amber-300 border-amber-500/40',
      icon: AlertTriangle,
      title,
      desc,
      rainProb,
      maxTemp,
      minTemp,
    }
  }

  // 3. GREEN SAFE CRITERIA (Normal / Low Risk)
  return {
    level: 'GREEN',
    color: '#10b981',
    badgeBg: 'bg-emerald-500/20 text-emerald-300 border-emerald-500/40',
    icon: CheckCircle2,
    title: 'Favorable Outlook',
    desc: 'Normal weather conditions. Ideal for regular activities.',
    rainProb,
    maxTemp,
    minTemp,
  }
}

export default function RiskOutlookCard({ forecast = [], langCode = 'en' }) {
  const fiveDays = forecast.slice(0, 5)

  if (fiveDays.length === 0) return null

  return (
    <div className="w-full bg-neutral-950/90 border border-white/12 rounded-xl p-3 sm:p-4 text-left">
      <div className="flex items-center justify-between mb-3 pb-2 border-b border-white/10 flex-wrap gap-1">
        <div className="flex items-center gap-2">
          <ShieldAlert size={16} className="text-amber-400" />
          <h3 className="text-xs font-bold uppercase tracking-wider text-white">
            5-Day Weather & Agricultural Risk Outlook
          </h3>
        </div>
        <span className="text-[10px] text-amber-300 font-bold bg-amber-500/20 px-2 py-0.5 rounded-full border border-amber-500/30 flex items-center gap-1">
          IMD Official Priority 1
        </span>
      </div>

      <div className="grid grid-cols-1 sm:grid-cols-5 gap-2">
        {fiveDays.map((d, index) => {
          const risk = evaluateDayRisk(d, langCode)
          const RiskIcon = risk.icon
          const dayName = index === 0 ? 'Today' : formatDay(d.date, langCode)

          return (
            <div
              key={index}
              className={`rounded-lg p-2.5 border flex flex-col justify-between transition-all ${
                risk.level === 'RED'
                  ? 'bg-rose-500/10 border-rose-500/30'
                  : risk.level === 'YELLOW'
                  ? 'bg-amber-500/10 border-amber-500/30'
                  : 'bg-white/5 border-white/10'
              }`}
            >
              <div>
                <div className="flex items-center justify-between mb-1">
                  <span className="text-xs font-bold text-white truncate">{dayName}</span>
                  <span className={`text-[9px] font-extrabold uppercase px-1.5 py-0.5 rounded border ${risk.badgeBg}`}>
                    {risk.level}
                  </span>
                </div>

                <div className="flex items-center gap-1.5 my-1 text-xs font-mono font-semibold text-white">
                  <RiskIcon size={14} style={{ color: risk.color }} />
                  <span>{Math.round(d.max)}° <span className="text-white/40 text-[10px]">/ {Math.round(d.min)}°</span></span>
                </div>

                <p className="text-[10px] font-semibold text-white/90 leading-tight truncate mt-1" style={{ color: risk.color }}>
                  {risk.title}
                </p>
                <p className="text-[9px] text-white/50 leading-tight mt-0.5 line-clamp-2">
                  {risk.desc}
                </p>
              </div>

              {d.rainProb > 0 && (
                <div className="mt-2 pt-1 border-t border-white/10 flex items-center justify-between text-[9px] text-sky-300">
                  <span className="flex items-center gap-1"><CloudRain size={10} /> Rain</span>
                  <span className="font-bold">{d.rainProb}%</span>
                </div>
              )}
            </div>
          )
        })}
      </div>
    </div>
  )
}
