from weathergpt.alerts import imd_district, sachet
from weathergpt.alerts.service import get_alerts
from weathergpt.farm import advisory
from weathergpt.weather.models import HourPoint
from datetime import datetime, timezone


def test_sachet_polygon_match(upstreams):
    alerts = sachet.alerts_for(23.02, 72.57)
    assert [a["id"] for a in alerts] == ["sachet:111"]
    assert alerts[0]["match"] == "polygon" and alerts[0]["severity"] == "orange"
    # Near the centroid radius but outside the polygon -> excluded.
    assert sachet.alerts_for(23.5, 72.6) == []


def test_sachet_expired_alerts_are_dropped(upstreams):
    upstreams.sachet[0]["effective_end_time"] = "Mon Jan 01 10:00:00 IST 2024"
    assert sachet.alerts_for(23.02, 72.57) == []


def test_sachet_time_parsing():
    dt = sachet.parse_time("Mon Sep 28 12:10:00 IST 2026")
    assert dt == datetime(2026, 9, 28, 6, 40, tzinfo=timezone.utc)


def test_district_warning_colours_are_inverted_vs_nowcast():
    row = {"Obj_id": "1", "Date": "2026-09-28", "District": "X", "Day_1": "9", "Day1_Color": "1",
           "Day_2": "2", "Day2_Color": "4"}
    warnings = imd_district.district_warnings(row)
    assert len(warnings) == 1 and warnings[0]["severity"] == "red" and warnings[0]["hazards"] == ["Heat wave"]
    assert imd_district.nowcast_alert({"color": "1", "Cat1": "1"}) is None           # 1 = green here
    assert imd_district.nowcast_alert({"color": "4", "Cat12": "12"})["severity"] == "red"


def test_city_station_warnings_and_real_nowcast_shape():
    row = {"Date": "2026-09-28", "Station_Code": "42647", "Station_Name": "Ahmedabad",
           "Day_1_Warning": "No warning", "Day_1_Warning_Color": "green",
           "Day_2_Warning": "Heavy Rain", "Day_2_Warning_Color": "orange"}
    w = imd_district.city_warnings(row)
    assert [(a["date"], a["severity"], a["event"]) for a in w] == [("2026-09-29", "orange", "Heavy Rain")]
    now = imd_district.nowcast_alert({"Obj_id": "2", "State_District": "EAST KHASI HILLS", "Date": "2026-09-28",
                                      "cat1": "0", "cat2": "2", "cat4": "4", "cat16": "", "toi": "1600",
                                      "vupto": "1900", "color": "2"})
    assert now["area"] == "EAST KHASI HILLS" and now["valid_until_ist"] == "1900"
    assert now["hazards"] == ["Light rain", "Light thunderstorm"]


def test_district_name_matching_handles_imd_spellings():
    rows = [{"District": "AHMADABAD"}, {"District": "BANAS KANTHA"}]
    assert imd_district.match_district("Ahmedabad", rows)["District"] == "AHMADABAD"
    assert imd_district.match_district("Banaskantha District", rows)["District"] == "BANAS KANTHA"
    assert imd_district.match_district("Pune", rows) is None


def test_combined_alerts_with_imd(upstreams, imd_keys):
    result = get_alerts(23.02, 72.57)
    assert result["status"] == "ok"
    assert result["district"]["name"] == "AHMADABAD"
    ids = [a["id"] for a in result["alerts"]]
    assert any(i.startswith("imd:district_warning") for i in ids) and "sachet:111" in ids
    assert result["alerts"][0]["severity"] == "orange"


def test_unreachable_channels_mean_unknown_not_none(upstreams):
    upstreams.fail.add("sachet")
    result = get_alerts(23.02, 72.57)
    assert result["status"] == "unknown" and result["alerts"] == []
    assert "not 'no alerts'" in result["note"]


def _hour(**kw):
    base = dict(time_utc=datetime.now(timezone.utc), temperature_c=28, precipitation_probability=5,
                precipitation_mm=0.0, wind_speed_kmh=5)
    base.update(kw)
    return HourPoint(**base)


def test_hour_bands():
    assert advisory.hour_band("spraying", _hour()) == "good"
    assert advisory.hour_band("spraying", _hour(wind_speed_kmh=18)) == "caution"
    assert advisory.hour_band("spraying", _hour(weather_code=95)) == "avoid"
    assert advisory.hour_band("irrigation", _hour(weather_code=95)) == "good"
    assert advisory.hour_band("field_work", _hour(wind_speed_kmh=None)) == "avoid"   # unknown wind is not safe


def test_best_window_is_computed_from_hours():
    cells = [{"local_hour": h, "suitability": "good" if 6 <= h < 10 else "avoid"} for h in range(24)]
    assert advisory.best_window(cells) == "Best: 6 AM–10 AM"
    assert advisory.best_window([{"local_hour": h, "suitability": "avoid"} for h in range(24)]) == "Indoor / planning tasks"


def test_advisory_endpoint_applies_official_warnings(client, upstreams, imd_keys):
    r = client.get("/advisory", params={"lat": 23.03, "lon": 72.58, "crop": "Cotton", "days": 3})
    assert r.status_code == 200, r.text
    body = r.json()
    today = body["windows"][0]
    assert body["source"] == "imd"
    assert today["suitability"] == "caution"                      # orange IMD warning today
    assert any(x.startswith("official_warning") for x in today["reasons"])
    assert set(today["hourly"]) == {"irrigation", "spraying", "field_work"}
    assert "hourly" not in body["windows"][2]
    assert body["ai"]["enabled"] is False


def test_advisory_insufficient_data_is_neutral(client, upstreams):
    upstreams.open_meteo["daily"]["precipitation_probability_max"] = [None] * 8
    upstreams.open_meteo["daily"]["precipitation_sum"] = [None] * 8
    body = client.get("/advisory", params={"lat": 51.5, "lon": -0.1, "days": 2}).json()
    assert body["windows"][0]["suitability"] == "neutral"
    assert body["windows"][0]["reasons"] == ["insufficient_data"]


def test_overlay_only_tightens_and_uses_per_day_verdicts():
    windows = [{"date": "2026-09-28", "suitability": "good", "summary": "", "reasons": []},
               {"date": "2026-09-29", "suitability": "caution", "summary": "", "reasons": []}]
    answers = {"d0_overall": {"choice": "avoid", "confidence": 0.9},
               "d1_overall": {"choice": "good", "confidence": 0.99},
               "d0_spray": {"score": 7, "confidence": 0.9}}                  # out of range -> ignored
    meta = advisory.apply_overlay(windows, answers, min_confidence=0.55, model="jev")
    assert windows[0]["suitability"] == "poor" and windows[1]["suitability"] == "caution"
    assert windows[1]["ai"]["overall"]["choice"] == "good"
    assert meta["overall_verdict"] == "avoid" and "spray" not in windows[0]["ai"]
