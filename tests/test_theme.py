"""Tests for the embed footer every command in the bot shares, and for the
one colour that is deliberately never the same twice."""

import os
import random
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import discord  # noqa: E402

from core.config import github_config  # noqa: E402
from core.theme import BRAND_ICON_URL, brand_footer, rainbow_color  # noqa: E402


def channels(color):
    return (color >> 16) & 0xFF, (color >> 8) & 0xFF, color & 0xFF


def test_the_footer_always_carries_the_brand_and_its_icon():
    embed = brand_footer(discord.Embed())

    assert embed.footer.text == github_config.brand_name
    assert embed.footer.icon_url == BRAND_ICON_URL


def test_a_label_no_longer_changes_what_is_shown():
    # 205 call sites across the bot each picked their own text - a category,
    # a joke, sometimes live data. The brand name is the one thing every
    # embed should say the same way, so a label must not still leak through.
    plain = brand_footer(discord.Embed())
    labelled = brand_footer(discord.Embed(), "Economy")
    dynamic = brand_footer(discord.Embed(), "Balance: 5000 coins")

    assert plain.footer.text == labelled.footer.text == dynamic.footer.text


def test_the_footer_is_returned_for_chaining():
    embed = discord.Embed()

    assert brand_footer(embed) is embed


def test_the_colour_is_a_value_discord_accepts():
    color = rainbow_color()

    assert 0 <= color <= 0xFFFFFF
    assert discord.Color(color).value == color


def test_it_roams_the_whole_spectrum_rather_than_repeating_one_hue():
    # "Random" that lands on twelve shades of blue is not a rainbow. Only the
    # hue varies, so a wide spread of distinct values is the observable proof
    # that it is the hue doing the varying.
    colors = {rainbow_color() for _ in range(60)}

    assert len(colors) > 40


def test_every_colour_is_vivid_rather_than_washed_out_or_muddy():
    # A colour picked with no floor lands on near-black often enough to look
    # broken, and a fully saturated one glares on Discord's light theme. The
    # band is fixed, so every draw has one bright channel and one dim one.
    for _ in range(100):
        low, high = min(channels(rainbow_color())), max(channels(rainbow_color()))

        assert high >= 200, f"too dark: {high}"
        assert low <= 120, f"too washed out: {low}"


def test_the_same_seed_gives_the_same_colour():
    # Callers that need a reproducible card - a test, a preview - can pass
    # their own generator instead of reaching into the global one.
    assert rainbow_color(random.Random(7)) == rainbow_color(random.Random(7))
    assert rainbow_color(random.Random(7)) != rainbow_color(random.Random(8))
