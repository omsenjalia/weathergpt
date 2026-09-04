import axios from 'axios';
import { getEnsembleWeather } from './utils/ensembleEngine';

// Falls back to localhost for local development. Set VITE_API_URL in .env for
// staging / production deployments.
const API_BASE = (import.meta.env.VITE_API_URL || 'http://localhost:8888').replace(/\/+$/, '');

export async function sendMessage(messagesPayload, location = '', language = 'English', farmerMode = false, crop = '') {
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
    farmer_mode: farmerMode,
    crop,
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

export function getIMDAlertBulletin(currentWeather, dailyForecast, officialAlert = null) {
  // Do not guess alerts locally. Only issue alert if official IMD alert is provided.
  if (officialAlert && officialAlert.level && officialAlert.level !== 'GREEN') {
    return officialAlert
  }
  return null
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

export async function getIMDFeatures() {
  try {
    const res = await axios.get(`${API_BASE}/api/imd/features`, { timeout: 10000 });
    return res.data;
  } catch (err) {
    console.error('IMD features fetch error:', err);
    return { status: 'error', features: [] };
  }
}

export async function queryIMDAPI(apiId = 'api-1', params = {}) {
  try {
    const res = await axios.post(`${API_BASE}/api/imd/query`, { api_id: apiId, params }, { timeout: 15000 });
    return res.data;
  } catch (err) {
    console.error('IMD API query error:', err);
    return { status: 500, error: err.message };
  }
}

