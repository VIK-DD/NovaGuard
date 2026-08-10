"""Tests for the embed footer every command in the bot shares."""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import discord  # noqa: E402

from core.config import github_config  # noqa: E402
from core.theme import BRAND_ICON_URL, brand_footer  # noqa: E402


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
