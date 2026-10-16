"""Cross-source places and activity / time zone estimate."""

from unittest.mock import patch

from factories import insights


def res(profile=None, timeline=None, raw=None):
    return [
        {"module": "m"},
        {"param": "p"},
        {"raw": raw or {}},
        {"graphic": []},
        {"profile": profile or []},
        {"timeline": timeline or []},
    ]


def test_places_merge_geo_points_and_geocode_text(monkeypatch):
    monkeypatch.setenv("VEILED_GEOCODE", "1")
    monkeypatch.setenv("VEILED_GEOCODE_MAX", "2")
    collected = {
        ("instagram", "t"): res(
            profile=[
                {
                    "geo": {
                        "Latitude": 41.02,
                        "Longitude": 28.97,
                        "Name": "Galata",
                        "Accessibility": "post location",
                    }
                }
            ]
        ),
        ("github", "t"): res(
            profile=[
                {"location": "Izmir, Turkey"},
                {"geo": {"Latitude": 41.02, "Longitude": 28.97, "Name": "dup"}},
            ]
        ),
        ("phone", "+90"): res(profile=[{"location": "Izmir, Turkey"}]),
    }
    with patch(
        "factories.helpers.location_geo",
        return_value={"Latitude": 38.42, "Longitude": 27.14, "Caption": "Izmir"},
    ):
        places = insights.places(collected)
    names = {p["name"]: p for p in places}
    assert set(names) == {"Galata", "Izmir, Turkey"}
    assert names["Izmir, Turkey"]["source"] == "github, phone"
    assert names["Izmir, Turkey"]["kind"] == "stated location"


def test_geocoding_can_be_disabled(monkeypatch):
    monkeypatch.setenv("VEILED_GEOCODE", "0")
    with patch("factories.helpers.location_geo", side_effect=AssertionError):
        assert insights.places({("x", "y"): res(profile=[{"location": "Paris"}])}) == []


def test_activity_estimates_offset_from_hours():
    # someone active 18:00-23:00 local at UTC+3 -> 15:00-20:00 UTC
    timeline = [
        {"date": f"2024-05-0{d} {h:02d}:12:00"}
        for d in range(1, 4)
        for h in range(15, 21)
    ]
    timeline.append({"date": "2024/05/01 00:00:00"})  # date-only: ignored
    out = insights.activity({("reddit", "x"): res(timeline=timeline)})
    assert out["samples"] == 18
    assert out["estimate"] in {"UTC+03:00", "UTC+02:00", "UTC+04:00", "UTC+01:00"}


def test_commit_offsets_win():
    raw = {"deep": {"timezones": {"UTC+03:00": 4}}}
    out = insights.activity({("github", "x"): res(raw=raw)})
    assert out["estimate"] == "UTC+03:00" and "commit" in out["basis"]


def test_parse_time_formats():
    assert insights.parse_time("2024-05-01T10:30:00Z").hour == 10
    assert insights.parse_time("2024-05-01T10:30:00+03:00").hour == 7
    assert insights.parse_time("2024/05/01 10:30:00").minute == 30
    assert insights.parse_time("2024-05-01") is None


def test_username_candidates_handle_turkish_names():
    c = insights.username_candidates(
        "\u00c7a\u011fr\u0131 I\u015f\u0131k"
    )  # a Turkish name
    assert c[:3] == ["cagriisik", "cagri.isik", "cagri_isik"]
    assert insights.username_candidates("Madonna") == []


def test_reverse_image_links_encode_url():
    links = insights.reverse_image_links("https://cdn/x.jpg?a=1&b=2")
    assert "https%3A%2F%2Fcdn%2Fx.jpg%3Fa%3D1%26b%3D2" in links["Yandex"]
