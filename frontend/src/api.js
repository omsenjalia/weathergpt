import axios from 'axios';

// Falls back to localhost for local development. Set VITE_API_URL in .env for
// staging / production deployments.
const API_BASE = import.meta.env.VITE_API_URL || 'http://localhost:8888';

export async function sendMessage(message, location = '') {
  const res = await axios.post(`${API_BASE}/chat`, { message, location });
  return res.data.response;
}

export async function getWeatherByCoords(lat, lon) {
  const res = await axios.get('https://api.open-meteo.com/v1/forecast', {
    params: {
      latitude: lat,
      longitude: lon,
      // Use the current Open-Meteo variable name (previously 'weathercode')
      current: 'temperature_2m,apparent_temperature,wind_speed_10m,precipitation,relative_humidity_2m,weather_code',
      hourly: 'temperature_2m,precipitation_probability,weather_code',
      daily: 'temperature_2m_max,temperature_2m_min,rain_sum,precipitation_probability_max,weather_code',
      forecast_days: 7,
      timezone: 'auto',
    }
  });
  return res.data;
}

export async function geocodeCity(city) {
  const res = await axios.get('https://geocoding-api.open-meteo.com/v1/search', {
    params: { name: city, count: 1, language: 'en' }
  });
  return res.data.results?.[0] || null;
}
