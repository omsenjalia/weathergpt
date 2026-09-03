import axios from 'axios';
import { getEnsembleWeather } from './utils/ensembleEngine';

// Falls back to localhost for local development. Set VITE_API_URL in .env for
// staging / production deployments.
const API_BASE = (import.meta.env.VITE_API_URL || 'http://localhost:8888').replace(/\/+$/, '');

export async function sendMessage(messagesPayload, location = '', language = 'English') {
  const formattedMessages = Array.isArray(messagesPayload)
    ? messagesPayload.map((m) => ({
        role: m.role || (m.isUser ? 'user' : 'assistant'),
        content: m.content || m.text || '',
      }))
    : [{ role: 'user', content: messagesPayload }];

  const res = await axios.post(`${API_BASE}/chat`, {
    message: typeof messagesPayload === 'string' ? messagesPayload : '',
    messages: formattedMessages,
    location,
    language,
  });
  return res.data.response;
}

export async function getDevDiagnostics() {
  try {
    const res = await axios.get(`${API_BASE}/dev`, { timeout: 15000 });
    return res.data;
  } catch (err) {
    // Retry once to allow Vercel serverless cold-start warmup
    const res = await axios.get(`${API_BASE}/dev`, { timeout: 15000 });
    return res.data;
  }
}

export async function runSandboxPrompt(prompt, location = 'New Delhi', language = 'English') {
  const res = await axios.post(`${API_BASE}/dev/sandbox`, { prompt, location, language }, { timeout: 30000 });
  return res.data;
}

export async function getWeatherByCoords(lat, lon, days = 14) {
  const ensemble = await getEnsembleWeather(lat, lon, days);
  const raw = ensemble.rawOpenMeteo || {};

  // Fuse current weather metrics
  const current = {
    ...(raw.current || {}),
    temperature_2m: ensemble.fused.temp,
    apparent_temperature: ensemble.fused.feelsLike,
    relative_humidity_2m: ensemble.fused.humidity,
    wind_speed_10m: ensemble.fused.windSpeed,
    wind_direction_10m: ensemble.fused.windDirection,
    surface_pressure: ensemble.fused.pressure,
    uv_index: ensemble.fused.uvIndex,
    weather_code: ensemble.fused.code,
  };

  return {
    ...raw,
    current,
    providersUsed: ensemble.providersUsed,
  };
}

export function getIMDAlertBulletin(currentWeather, dailyForecast) {
  if (!currentWeather) return null

  const temp = currentWeather.temp ?? 25
  const wind = currentWeather.windSpeed ?? 0
  const rainProb = dailyForecast?.[0]?.rainProb ?? 0
  const rainSum = dailyForecast?.[0]?.rainSum ?? 0
  const code = currentWeather.code ?? 0
  const uv = currentWeather.uvIndex ?? 0
  const aqi = currentWeather.aqi ?? 0

  let level = 'GREEN'
  let title = 'IMD GREEN: Normal Weather Outlook'
  let color = '#10b981'
  let advisory = 'No severe weather warnings active for this region.'
  let action = 'Regular daily activities can continue normally.'

  // RED ALERT CRITERIA (Take Action)
  if (code >= 95 || rainSum >= 65 || wind >= 50 || temp >= 44 || aqi >= 300) {
    level = 'RED'
    color = '#ef4444'
    title = code >= 95 ? '🔴 IMD RED ALERT: Severe Thunderstorm & Lightning Warning' : temp >= 44 ? '🔴 IMD RED ALERT: Severe Heatwave Warning' : '🔴 IMD RED ALERT: Extremely Heavy Rainfall Warning'
    advisory = 'Severe hazard imminent! Remain indoors, avoid unnecessary travel, and monitor civil defense advisories.'
    action = 'TAKE ACTION: Seek sturdy shelter immediately.'
  }
  // ORANGE ALERT CRITERIA (Be Prepared)
  else if (code >= 80 || rainProb >= 70 || wind >= 35 || temp >= 40 || uv >= 9 || aqi >= 200) {
    level = 'ORANGE'
    color = '#f97316'
    title = rainProb >= 70 ? '🟠 IMD ORANGE ALERT: Heavy Rainfall Expected' : temp >= 40 ? '🟠 IMD ORANGE ALERT: Severe Heatwave Conditions' : '🟠 IMD ORANGE ALERT: Squally Winds & Convective Storms'
    advisory = 'Potentially dangerous weather conditions. Localized waterlogging or transit delays likely.'
    action = 'BE PREPARED: Keep rainwear handy and allow extra travel time.'
  }
  // YELLOW ALERT CRITERIA (Be Aware)
  else if (code >= 51 || rainProb >= 40 || wind >= 25 || temp >= 37 || uv >= 7 || aqi >= 100) {
    level = 'YELLOW'
    color = '#f59e0b'
    title = '🟡 IMD YELLOW ALERT: Watch Weather Updates'
    advisory = 'Unsettled weather conditions present. Minor disruptions possible.'
    action = 'BE AWARE: Keep track of local weather forecasts.'
  }

  return { level, title, color, advisory, action }
}

export async function getAirQualityByCoords(lat, lon) {
  try {
    const res = await axios.get('https://air-quality-api.open-meteo.com/v1/air-quality', {
      params: {
        latitude: lat,
        longitude: lon,
        current: 'us_aqi,pm10,pm2_5,carbon_monoxide,nitrogen_dioxide,sulphur_dioxide,ozone',
        timezone: 'auto',
      }
    });
    return res.data;
  } catch (err) {
    console.error('Air Quality fetch failed:', err);
    return null;
  }
}

export async function geocodeCity(city) {
  const res = await axios.get('https://geocoding-api.open-meteo.com/v1/search', {
    params: { name: city, count: 1, language: 'en' }
  });
  return res.data.results?.[0] || null;
}
