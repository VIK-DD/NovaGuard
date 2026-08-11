"""Tests for the settings shared by the yt-dlp and Lavalink music cogs."""

from core.music_settings import MUSIC_DEFAULTS, queue_room, resolve_music, validate_music


def test_defaults_are_safe_and_bounded():
    assert resolve_music({}) == MUSIC_DEFAULTS
    assert MUSIC_DEFAULTS["default_volume"] <= MUSIC_DEFAULTS["max_volume"]
    assert MUSIC_DEFAULTS["max_queue_tracks"] <= 500


def test_invalid_saved_values_fall_back_without_crashing():
    resolved = resolve_music(
        {
            "music": {
                "enabled": "yes",
                "default_volume": 500,
                "max_volume": 30,
                "max_queue_tracks": -2,
            }
        }
    )
    assert resolved["enabled"] is True
    assert resolved["default_volume"] == 30
    assert resolved["max_volume"] == 30
    assert resolved["max_queue_tracks"] == 1


def test_validation_rejects_unknown_and_cross_field_errors():
    current = resolve_music({})
    _, errors = validate_music(
        {"default_volume": 90, "max_volume": 40, "surprise": True}, current
    )
    assert "music.surprise: unknown setting" in errors
    assert "music.default_volume: cannot be greater than max_volume" in errors


def test_partial_patch_is_validated_against_current_values():
    current = resolve_music({"music": {"default_volume": 20, "max_volume": 40}})
    saved, errors = validate_music({"max_volume": 60}, current)
    assert errors == []
    assert saved["default_volume"] == 20
    assert saved["max_volume"] == 60


def test_queue_room_never_goes_negative():
    settings = {**MUSIC_DEFAULTS, "max_queue_tracks": 3}
    assert queue_room(settings, 1) == 2
    assert queue_room(settings, 8) == 0
