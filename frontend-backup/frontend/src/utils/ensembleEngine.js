import axios from 'axios'

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
      name: 'Open-Meteo (ECMWF/GFS)',
      weight: 1.0,
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
      weight: 1.2,
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
      weight: 1.2,
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
      weight: 1.1,
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
async function fetchAccuWeather(lat, lon, key) {
  if (!key) return null
  try {
    // Step 1: Geoposition search for Location Key
    const locRes = await axios.get(
      'https://dataservice.accuweather.com/locations/v1/cities/geoposition/search',
      {
        params: { apikey: key, q: `${lat},${lon}` },
        timeout: 8000,
      }
    )
    const locKey = locRes.data?.Key
    if (!locKey) return null

    // Step 2: Fetch Current Conditions
    const condRes = await axios.get(
      `https://dataservice.accuweather.com/currentconditions/v1/${locKey}`,
      {
        params: { apikey: key, details: 'true' },
        timeout: 8000,
      }
    )
    const data = condRes.data?.[0]
    if (!data) return null

    return {
      name: 'AccuWeather',
      weight: 1.25,
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
    console.warn('AccuWeather fetch failed:', err.message)
    return null
  }
}

/**
 * Main Multi-Source Ensemble Fused Telemetry Aggregator
 */
export async function getEnsembleWeather(lat, lon, days = 14) {
  const keys = getProviderKeys()

  // Execute all telemetry calls in parallel
  const results = await Promise.allSettled([
    fetchOpenMeteo(lat, lon, days),
    fetchWeatherAPI(lat, lon, keys.weatherapi),
    fetchTomorrowIO(lat, lon, keys.tomorrow),
    fetchOpenWeatherMap(lat, lon, keys.openweather),
    fetchAccuWeather(lat, lon, keys.accuweather),
  ])

  const validSources = results
    .filter((r) => r.status === 'fulfilled' && r.value !== null)
    .map((r) => r.value)

  // Fallback to base OpenMeteo if all fails
  const baseOpenMeteo = validSources.find((s) => s.name.includes('Open-Meteo'))

  if (validSources.length === 0) {
    throw new Error('All weather telemetry services were unreachable.')
  }

  // Calculate Weighted Means
  let totalWeight = 0
  let weightedTemp = 0
  let weightedFeelsLike = 0
  let weightedHumidity = 0
  let weightedWindSpeed = 0
  let weightedPressure = 0
  let weightedUV = 0

  validSources.forEach((s) => {
    const w = s.weight || 1.0
    totalWeight += w
    if (s.temp != null) weightedTemp += s.temp * w
    if (s.feelsLike != null) weightedFeelsLike += s.feelsLike * w
    if (s.humidity != null) weightedHumidity += s.humidity * w
    if (s.windSpeed != null) weightedWindSpeed += s.windSpeed * w
    if (s.pressure != null) weightedPressure += s.pressure * w
    if (s.uvIndex != null && s.uvIndex > 0) weightedUV += s.uvIndex * w
  })

  const fusedTemp = totalWeight > 0 ? Math.round((weightedTemp / totalWeight) * 10) / 10 : baseOpenMeteo?.temp ?? 25
  const fusedFeelsLike = totalWeight > 0 ? Math.round((weightedFeelsLike / totalWeight) * 10) / 10 : baseOpenMeteo?.feelsLike ?? fusedTemp
  const fusedHumidity = totalWeight > 0 ? Math.round(weightedHumidity / totalWeight) : baseOpenMeteo?.humidity ?? 50
  const fusedWindSpeed = totalWeight > 0 ? Math.round(weightedWindSpeed / totalWeight) : baseOpenMeteo?.windSpeed ?? 10
  const fusedPressure = totalWeight > 0 ? Math.round(weightedPressure / totalWeight) : baseOpenMeteo?.pressure ?? 1013
  const fusedUV = totalWeight > 0 ? Math.round((weightedUV / totalWeight) * 10) / 10 : baseOpenMeteo?.uvIndex ?? 0

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
    providersUsed: validSources.map((s) => ({
      name: s.name,
      temp: Math.round(s.temp * 10) / 10,
      feelsLike: Math.round((s.feelsLike ?? s.temp) * 10) / 10,
      condition: s.condition || 'Normal',
      weight: s.weight,
    })),
  }
}
