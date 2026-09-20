import axios from 'axios'

// Provider trust weights — MUST mirror backend/services/fusion.py PROVIDER_WEIGHTS.
// Priority: Open-Meteo (ECMWF/IMD NWP) > AccuWeather > WeatherAPI / Tomorrow.io / OpenWeatherMap
export const PROVIDER_WEIGHTS = {
  'Open-Meteo (ECMWF)': 2.0,
  AccuWeather: 1.5,
  'WeatherAPI.com': 1.2,
  'Tomorrow.io': 1.2,
  OpenWeatherMap: 1.1,
}

// Providers whose temperature deviates from Open-Meteo by more than this are excluded
// from the weighted mean (mirrors FUSION_OUTLIER_DELTA_C on the backend).
export const OUTLIER_TEMP_DELTA_C = 7

// Helper to retrieve keys from env or localStorage
export function getProviderKeys() {
  return {
    weatherapi:
      import.meta.env.VITE_WEATHERAPI_KEY ||
      localStorage.getItem('weathergpt_weatherapi_key') ||
      '',
    tomorrow:
      import.meta.env.VITE_TOMORROW_KEY ||
      localStorage.getItem('weathergpt_tomorrow_key') ||
      '',
    openweather:
      import.meta.env.VITE_OPENWEATHER_KEY ||
      localStorage.getItem('weathergpt_openweather_key') ||
      '',
    accuweather:
      import.meta.env.VITE_ACCUWEATHER_KEY ||
      localStorage.getItem('weathergpt_accuweather_key') ||
      '',
  }
}

// Fetch Open-Meteo Data (Free, Base Model Engine)
async function fetchOpenMeteo(lat, lon, days = 14) {
  try {
    const res = await axios.get('https://api.open-meteo.com/v1/forecast', {
      params: {
        latitude: lat,
        longitude: lon,
        current:
          'temperature_2m,apparent_temperature,wind_speed_10m,wind_direction_10m,precipitation,relative_humidity_2m,weather_code,surface_pressure,uv_index',
        hourly:
          'temperature_2m,apparent_temperature,precipitation_probability,weather_code,wind_speed_10m,wind_direction_10m,relative_humidity_2m,uv_index',
        daily:
          'temperature_2m_max,temperature_2m_min,rain_sum,precipitation_probability_max,weather_code,sunrise,sunset,uv_index_max',
        forecast_days: days,
        alerts: true,
        timezone: 'auto',
      },
      timeout: 8000,
    })

    const current = res.data.current
    return {
      name: 'Open-Meteo (ECMWF)',
      weight: PROVIDER_WEIGHTS['Open-Meteo (ECMWF)'],
      temp: current.temperature_2m,
      feelsLike: current.apparent_temperature,
      humidity: current.relative_humidity_2m,
      windSpeed: current.wind_speed_10m,
      windDirection: current.wind_direction_10m ?? 0,
      pressure: current.surface_pressure ?? 1013,
      uvIndex: current.uv_index ?? 0,
      code: current.weather_code ?? current.weathercode ?? 0,
      raw: res.data,
    }
  } catch (err) {
    console.warn('Open-Meteo fetch failed:', err.message)
    return null
  }
}

// Fetch WeatherAPI.com Data
async function fetchWeatherAPI(lat, lon, key) {
  if (!key) return null
  try {
    const res = await axios.get('https://api.weatherapi.com/v1/forecast.json', {
      params: { key, q: `${lat},${lon}`, days: 7, aqi: 'yes', alerts: 'yes' },
      timeout: 8000,
    })
    const current = res.data.current
    return {
      name: 'WeatherAPI.com',
      weight: PROVIDER_WEIGHTS['WeatherAPI.com'],
      temp: current.temp_c,
      feelsLike: current.feelslike_c,
      humidity: current.humidity,
      windSpeed: current.wind_kph,
      windDirection: current.wind_degree ?? 0,
      pressure: current.pressure_mb,
      uvIndex: current.uv ?? 0,
      condition: current.condition?.text,
      aqi: current.air_quality?.['us-epa-index'] ? current.air_quality['us-epa-index'] * 25 : null,
      pm25: current.air_quality?.pm2_5 ?? null,
      pm10: current.air_quality?.pm10 ?? null,
      raw: res.data,
    }
  } catch (err) {
    console.warn('WeatherAPI fetch failed:', err.message)
    return null
  }
}

// Fetch Tomorrow.io Data
async function fetchTomorrowIO(lat, lon, key) {
  if (!key) return null
  try {
    const res = await axios.get('https://api.tomorrow.io/v4/weather/realtime', {
      params: { location: `${lat},${lon}`, apikey: key },
      timeout: 8000,
    })
    const values = res.data.data?.values
    if (!values) return null
    return {
      name: 'Tomorrow.io',
      weight: PROVIDER_WEIGHTS['Tomorrow.io'],
      temp: values.temperature,
      feelsLike: values.temperatureApparent ?? values.temperature,
      humidity: values.humidity,
      windSpeed: values.windSpeed ? values.windSpeed * 3.6 : 0, // m/s to km/h
      windDirection: values.windDirection ?? 0,
      pressure: values.pressureSurfaceLevel ?? 1013,
      uvIndex: values.uvIndex ?? 0,
      raw: res.data,
    }
  } catch (err) {
    console.warn('Tomorrow.io fetch failed:', err.message)
    return null
  }
}

// Fetch OpenWeatherMap Data
async function fetchOpenWeatherMap(lat, lon, key) {
  if (!key) return null
  try {
    const res = await axios.get('https://api.openweathermap.org/data/2.5/weather', {
      params: { lat, lon, appid: key, units: 'metric' },
      timeout: 8000,
    })
    const main = res.data.main
    const wind = res.data.wind
    return {
      name: 'OpenWeatherMap',
      weight: PROVIDER_WEIGHTS.OpenWeatherMap,
      temp: main.temp,
      feelsLike: main.feels_like,
      humidity: main.humidity,
      windSpeed: wind ? wind.speed * 3.6 : 0, // m/s to km/h
      windDirection: wind?.deg ?? 0,
      pressure: main.pressure,
      uvIndex: 0,
      condition: res.data.weather?.[0]?.description,
      raw: res.data,
    }
  } catch (err) {
    console.warn('OpenWeatherMap fetch failed:', err.message)
    return null
  }
}

// Fetch AccuWeather Data
//
// AccuWeather relaunched its developer portal on 2025-09-09: every legacy API key
// was retired and authentication moved to `Authorization: Bearer <key>` (the old
// `?apikey=` query parameter now returns 401 "API authorization failed"). There is
// no free tier any more — a 14-day trial, then the paid Starter plan.
//
// Two caveats for this browser-side path:
//   1. A key placed in VITE_ACCUWEATHER_KEY ships inside the public bundle. AccuWeather's
//      own guidance is to keep keys server-side and proxy from the backend, which is what
//      backend/services/fusion.py does (GET /fusion). Prefer that for production.
//   2. dataservice.accuweather.com does not send CORS headers for every plan, so the
//      browser may block the call outright. The failure is reported through
//      `providerErrors` on the ensemble result instead of being swallowed.
async function fetchAccuWeather(lat, lon, key) {
  if (!key) return null
  const authHeaders = {
    Authorization: `Bearer ${key}`,
    Accept: 'application/json',
  }
  try {
    // Step 1: Geoposition search for Location Key
    const locRes = await axios.get(
      'https://dataservice.accuweather.com/locations/v1/cities/geoposition/search',
      {
        params: { q: `${lat},${lon}` },
        headers: authHeaders,
        timeout: 8000,
      }
    )
    const locKey = locRes.data?.Key
    if (!locKey) return null

    // Step 2: Fetch Current Conditions
    const condRes = await axios.get(
      `https://dataservice.accuweather.com/currentconditions/v1/${locKey}`,
      {
        params: { details: 'true' },
        headers: authHeaders,
        timeout: 8000,
      }
    )
    const data = condRes.data?.[0]
    if (!data) return null

    return {
      name: 'AccuWeather',
      weight: PROVIDER_WEIGHTS.AccuWeather,
      temp: data.Temperature?.Metric?.Value,
      feelsLike: data.RealFeelTemperature?.Metric?.Value ?? data.Temperature?.Metric?.Value,
      humidity: data.RelativeHumidity,
      windSpeed: data.Wind?.Speed?.Metric?.Value,
      windDirection: data.Wind?.Direction?.Degrees ?? 0,
      pressure: data.Pressure?.Metric?.Value,
      uvIndex: data.UVIndex ?? 0,
      condition: data.WeatherText,
      raw: condRes.data,
    }
  } catch (err) {
    const status = err?.response?.status
    const upstream = err?.response?.data?.Message || err?.response?.data?.message
    if (status === 401) {
      throw new Error(
        'AccuWeather rejected the API key (401). Keys from the legacy developer portal were ' +
          'retired on 2025-09-09 — issue a new one at developer.accuweather.com ' +
          (upstream ? `(${upstream})` : '')
      )
    }
    if (status === 403) {
      throw new Error(`AccuWeather plan does not include this endpoint (403)${upstream ? `: ${upstream}` : ''}`)
    }
    if (status === 429) {
      throw new Error(`AccuWeather quota exceeded (429)${upstream ? `: ${upstream}` : ''}`)
    }
    if (!err?.response) {
      throw new Error(
        'AccuWeather request never reached the API (CORS or network). The browser blocks ' +
          'dataservice.accuweather.com unless the plan allows it — proxy it through the backend ' +
          '(GET /fusion) instead of embedding the key in the client.'
      )
    }
    throw new Error(`AccuWeather fetch failed (HTTP ${status})${upstream ? `: ${upstream}` : ''}`)
  }
}

/**
 * Main Multi-Source Ensemble Fused Telemetry Aggregator
 */
export async function getEnsembleWeather(lat, lon, days = 14) {
  const keys = getProviderKeys()

  // Execute all telemetry calls in parallel. A provider that hard-fails (expired
  // key, missing subscription, CORS block) rejects instead of returning null so
  // the reason can be reported rather than silently shrinking the ensemble.
  const providers = [
    { name: 'Open-Meteo (ECMWF)', run: () => fetchOpenMeteo(lat, lon, days) },
    { name: 'WeatherAPI.com', run: () => fetchWeatherAPI(lat, lon, keys.weatherapi) },
    { name: 'Tomorrow.io', run: () => fetchTomorrowIO(lat, lon, keys.tomorrow) },
    { name: 'OpenWeatherMap', run: () => fetchOpenWeatherMap(lat, lon, keys.openweather) },
    { name: 'AccuWeather', run: () => fetchAccuWeather(lat, lon, keys.accuweather) },
  ]
  const results = await Promise.allSettled(providers.map((p) => p.run()))

  const providerErrors = {}
  results.forEach((r, i) => {
    if (r.status === 'rejected') {
      const message = r.reason?.message || String(r.reason)
      providerErrors[providers[i].name] = message
      console.warn(`${providers[i].name} dropped from the ensemble:`, message)
    }
  })

  const allSources = results
    .filter((r) => r.status === 'fulfilled' && r.value !== null)
    .map((r) => r.value)
    .sort((a, b) => (b.weight || 0) - (a.weight || 0))

  if (allSources.length === 0) {
    throw new Error('All weather telemetry services were unreachable.')
  }

  // Open-Meteo is the trusted baseline: flag vendors that disagree wildly with it.
  const baseOpenMeteo = allSources.find((s) => s.name.includes('Open-Meteo'))
  allSources.forEach((s) => {
    s.outlier =
      !!baseOpenMeteo &&
      s !== baseOpenMeteo &&
      s.temp != null &&
      Math.abs(s.temp - baseOpenMeteo.temp) > OUTLIER_TEMP_DELTA_C
  })
  const validSources = allSources.filter((s) => !s.outlier)

  // Calculate Weighted Means
  let totalWeight = 0

  // Weighted mean per metric over the providers that actually reported it — a provider
  // missing e.g. humidity does not drag the humidity mean towards zero.
  const weightedMean = (key, { positiveOnly = false } = {}) => {
    let sum = 0
    let wsum = 0
    validSources.forEach((s) => {
      const v = s[key]
      if (v == null || Number.isNaN(v) || (positiveOnly && v <= 0)) return
      const w = s.weight || 1.0
      sum += v * w
      wsum += w
    })
    return wsum > 0 ? sum / wsum : null
  }
  const round1 = (v) => Math.round(v * 10) / 10

  validSources.forEach((s) => {
    totalWeight += s.weight || 1.0
  })

  const meanTemp = weightedMean('temp')
  const fusedTemp = meanTemp != null ? round1(meanTemp) : baseOpenMeteo?.temp ?? 25
  const meanFeels = weightedMean('feelsLike')
  const fusedFeelsLike = meanFeels != null ? round1(meanFeels) : baseOpenMeteo?.feelsLike ?? fusedTemp
  const meanHum = weightedMean('humidity')
  const fusedHumidity = meanHum != null ? Math.round(meanHum) : baseOpenMeteo?.humidity ?? 50
  const meanWind = weightedMean('windSpeed')
  const fusedWindSpeed = meanWind != null ? Math.round(meanWind) : baseOpenMeteo?.windSpeed ?? 10
  const meanPressure = weightedMean('pressure')
  const fusedPressure = meanPressure != null ? Math.round(meanPressure) : baseOpenMeteo?.pressure ?? 1013
  const meanUV = weightedMean('uvIndex', { positiveOnly: true })
  const fusedUV = meanUV != null ? round1(meanUV) : baseOpenMeteo?.uvIndex ?? 0

  const temps = validSources.map((s) => s.temp).filter((t) => t != null)
  const tempSpread = temps.length > 1 ? round1(Math.max(...temps) - Math.min(...temps)) : 0
  const confidence =
    validSources.length === 1 ? 'single-source' : tempSpread <= 1.5 ? 'high' : tempSpread <= 3.5 ? 'medium' : 'low'

  // Air Quality: Pick first provider that supplies valid AQI telemetry
  const aqiProvider = validSources.find((s) => s.aqi != null)
  const pm25Provider = validSources.find((s) => s.pm25 != null)
  const pm10Provider = validSources.find((s) => s.pm10 != null)

  return {
    fused: {
      temp: fusedTemp,
      feelsLike: fusedFeelsLike,
      humidity: fusedHumidity,
      windSpeed: fusedWindSpeed,
      windDirection: baseOpenMeteo?.windDirection ?? 0,
      pressure: fusedPressure,
      uvIndex: fusedUV > 0 ? fusedUV : baseOpenMeteo?.uvIndex ?? 0,
      code: baseOpenMeteo?.code ?? 0,
      aqi: aqiProvider?.aqi ?? null,
      pm25: pm25Provider?.pm25 ?? null,
      pm10: pm10Provider?.pm10 ?? null,
    },
    rawOpenMeteo: baseOpenMeteo?.raw || null,
    confidence,
    tempSpread,
    totalWeight,
    providersUsed: allSources.map((s) => ({
      name: s.name,
      temp: Math.round(s.temp * 10) / 10,
      feelsLike: Math.round((s.feelsLike ?? s.temp) * 10) / 10,
      condition: s.condition || 'Normal',
      weight: s.weight,
      outlier: !!s.outlier,
    })),
    // Vendors that were configured but failed, with the upstream reason.
    // Mirrors `provider_errors` from the backend fusion engine.
    providerErrors,
  }
}
