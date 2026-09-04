import axios from 'axios'

/**
 * Reverse geocode latitude and longitude to human-readable city/region name.
 * Uses BigDataCloud client API with Nominatim fallback.
 */
export async function reverseGeocode(lat, lon) {
  // Try 1: BigDataCloud client API (Free, CORS friendly, works reliably in browser)
  try {
    const res = await axios.get(
      `https://api.bigdatacloud.net/data/reverse-geocode-client?latitude=${lat}&longitude=${lon}&localityLanguage=en`,
      { timeout: 5000 }
    )
    const data = res.data
    const mainCity =
      data.city ||
      data.locality ||
      data.principalSubdivision ||
      'My Location'
    const subLocality = data.localityInfo?.administrative?.find(
      (a) => a.order >= 10 && a.name && a.name !== mainCity
    )?.name
    const name =
      subLocality && subLocality.toLowerCase() !== mainCity.toLowerCase()
        ? `${subLocality}, ${mainCity}`
        : mainCity
    const country = data.countryName || 'India'
    return { name, country, lat, lon }
  } catch (err) {
    console.warn('BigDataCloud reverse geocode failed, trying fallback:', err)
  }

  // Try 2: Nominatim OpenStreetMap fallback
  try {
    const res = await fetch(
      `https://nominatim.openstreetmap.org/reverse?lat=${lat}&lon=${lon}&format=json`
    )
    const data = await res.json()
    if (data && data.address) {
      const address = data.address
      const subLocality =
        address.suburb ||
        address.neighbourhood ||
        address.residential ||
        address.district ||
        address.city_district ||
        ''
      const mainCity =
        address.city ||
        address.town ||
        address.village ||
        address.county ||
        'My Location'
      const name =
        subLocality && subLocality.toLowerCase() !== mainCity.toLowerCase()
          ? `${subLocality}, ${mainCity}`
          : mainCity
      const country = address.country || 'India'
      return { name, country, lat, lon }
    }
  } catch (err) {
    console.warn('Nominatim reverse geocode failed:', err)
  }

  return { name: 'My Location', country: 'India', lat, lon }
}

/**
 * Detect approximate user location via IP address fallback.
 */
export async function detectLocationFromIP() {
  try {
    const res = await axios.get('https://ipapi.co/json/', { timeout: 5000 })
    const data = res.data
    if (data && data.latitude && data.longitude) {
      return {
        name: data.city ? `${data.city}` : 'My Location',
        country: data.country_name || 'India',
        lat: data.latitude,
        lon: data.longitude,
      }
    }
  } catch (err) {
    console.warn('IP location detection failed:', err)
  }

  return null
}

/**
 * Auto-detect user location on app load.
 * 1. Checks localStorage for saved location.
 * 2. Tries browser GPS (with 15s timeout).
 * 3. Falls back to IP-based location if GPS is denied, unavailable, or times out.
 * 4. Persists the detected location into localStorage.
 */
export function autoDetectUserLocation() {
  return new Promise((resolve) => {
    // 1. Check saved location in localStorage
    try {
      const savedLoc = localStorage.getItem('weathergpt_location')
      if (savedLoc) {
        const parsed = JSON.parse(savedLoc)
        if (parsed?.lat && parsed?.lon && parsed?.name) {
          resolve(parsed)
          return
        }
      }
    } catch {
      // Ignore storage parse error
    }

    // 2. Check navigator.geolocation support
    if (!navigator.geolocation) {
      detectLocationFromIP().then((ipLoc) => {
        if (ipLoc) {
          try {
            localStorage.setItem('weathergpt_location', JSON.stringify(ipLoc))
          } catch {}
          resolve(ipLoc)
        } else {
          resolve(null)
        }
      })
      return
    }

    let isResolved = false

    const handleSuccess = async (pos) => {
      if (isResolved) return
      isResolved = true
      const { latitude: lat, longitude: lon } = pos.coords
      const loc = await reverseGeocode(lat, lon)
      try {
        localStorage.setItem('weathergpt_location', JSON.stringify(loc))
      } catch {}
      resolve(loc)
    }

    const handleError = async (err) => {
      if (isResolved) return
      isResolved = true
      console.warn('GPS failed or timed out, attempting IP location fallback:', err)
      const ipLoc = await detectLocationFromIP()
      if (ipLoc) {
        try {
          localStorage.setItem('weathergpt_location', JSON.stringify(ipLoc))
        } catch {}
        resolve(ipLoc)
      } else {
        resolve(null)
      }
    }

    // Call getCurrentPosition with high accuracy false for speed and longer 15s timeout
    navigator.geolocation.getCurrentPosition(handleSuccess, handleError, {
      enableHighAccuracy: false,
      timeout: 15000,
      maximumAge: 300000,
    })
  })
}
