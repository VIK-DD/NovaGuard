"""Tests for the Lavalink audio filter presets."""

import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import yaml  # noqa: E402

from core.music_filters import (  # noqa: E402
    FILTER_PRESETS,
    MAX_GAIN,
    MIN_GAIN,
    is_reset,
    preset_label,
    preset_names,
    required_filters,
    resolve_preset,
)

NODE_CONFIG = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "deploy",
    "lavalink",
    "application.yml",
)


class PresetCatalogueTests(unittest.TestCase):
    def test_every_preset_is_fully_described(self):
        for name, spec in FILTER_PRESETS.items():
            with self.subTest(preset=name):
                for key in ("label", "emoji", "description", "requires", "filters"):
                    self.assertIn(key, spec)
                self.assertTrue(spec["label"])
                self.assertTrue(spec["description"])

    def test_off_comes_first_and_clears_everything(self):
        self.assertEqual(preset_names()[0], "off")
        self.assertEqual(FILTER_PRESETS["off"]["filters"], {})
        self.assertEqual(required_filters("off"), ())

    def test_lookup_tolerates_case_and_whitespace(self):
        self.assertIs(resolve_preset("  NightCore "), FILTER_PRESETS["nightcore"])

    def test_an_unknown_preset_resolves_to_none(self):
        self.assertIsNone(resolve_preset("does-not-exist"))
        self.assertIsNone(resolve_preset(""))
        self.assertIsNone(resolve_preset(None))

    def test_only_off_counts_as_a_reset(self):
        self.assertTrue(is_reset("off"))
        self.assertTrue(is_reset(" OFF "))
        self.assertFalse(is_reset("bassboost"))

    def test_labels_carry_an_emoji_and_fall_back_safely(self):
        self.assertIn("Nightcore", preset_label("nightcore"))
        self.assertEqual(preset_label("nonsense"), "nonsense")


class PresetValueTests(unittest.TestCase):
    def test_equalizer_gains_stay_inside_lavalink_limits(self):
        # Outside this range Lavalink clamps or clips, so a preset that looks
        # bolder on paper just sounds broken.
        for name, spec in FILTER_PRESETS.items():
            for band in spec["filters"].get("equalizer", []):
                with self.subTest(preset=name, band=band["band"]):
                    self.assertGreaterEqual(band["gain"], MIN_GAIN)
                    self.assertLessEqual(band["gain"], MAX_GAIN)

    def test_equalizer_bands_are_valid_indexes(self):
        for name, spec in FILTER_PRESETS.items():
            for band in spec["filters"].get("equalizer", []):
                with self.subTest(preset=name):
                    self.assertIn(band["band"], range(15))

    def test_timescale_values_stay_musical(self):
        # Anything beyond roughly half or double speed stops being an effect
        # and starts being unlistenable.
        for name, spec in FILTER_PRESETS.items():
            timescale = spec["filters"].get("timescale")
            if not timescale:
                continue
            with self.subTest(preset=name):
                self.assertGreater(timescale["speed"], 0.5)
                self.assertLess(timescale["speed"], 2.0)
                self.assertGreater(timescale["pitch"], 0.5)
                self.assertLess(timescale["pitch"], 2.0)

    def test_nightcore_speeds_up_and_slowed_slows_down(self):
        self.assertGreater(FILTER_PRESETS["nightcore"]["filters"]["timescale"]["speed"], 1)
        self.assertLess(FILTER_PRESETS["slowed"]["filters"]["timescale"]["speed"], 1)

    def test_bass_boost_lifts_low_bands_only(self):
        bands = FILTER_PRESETS["bassboost"]["filters"]["equalizer"]

        self.assertTrue(all(band["band"] <= 4 for band in bands))
        self.assertTrue(all(band["gain"] > 0 for band in bands))


class NodeConfigAgreementTests(unittest.TestCase):
    """The presets are useless if the node has the filter switched off."""

    def setUp(self):
        with open(NODE_CONFIG) as handle:
            config = yaml.safe_load(handle)
        self.enabled = config["lavalink"]["server"]["filters"]

    def test_every_filter_a_preset_needs_is_enabled_on_the_node(self):
        for name in FILTER_PRESETS:
            for needed in required_filters(name):
                with self.subTest(preset=name, filter=needed):
                    self.assertTrue(
                        self.enabled.get(needed),
                        f"preset {name!r} needs the {needed!r} filter, "
                        "but deploy/lavalink/application.yml has it disabled",
                    )

    def test_volume_stays_enabled_for_the_volume_controls(self):
        self.assertTrue(self.enabled.get("volume"))


if __name__ == "__main__":
    unittest.main()
