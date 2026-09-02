import axios from 'axios';

const API_BASE = 'http://localhost:8000';

export async function sendMessage(message, location = '') {
  const res = await axios.post(`${API_BASE}/chat`, { message, location });
  return res.data.response;
}

export async function getWeatherByCoords(lat, lon) {
  const res = await axios.get('https://api.open-meteo.com/v1/forecast', {
    params: {
      latitude: lat,
      longitude: lon,
      current: 'temperature_2m,apparent_temperature,wind_speed_10m,precipitation,relative_humidity_2m,weathercode',
      hourly: 'temperature_2m,precipitation_probability,weathercode',
      daily: 'temperature_2m_max,temperature_2m_min,rain_sum,precipitation_probability_max,weathercode',
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
