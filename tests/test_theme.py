"""Paletas: mesmas chaves nos dois temas, identidade da equipe e contraste legível."""

import pytest

from theme import PALETTES, THEME_CHOICES, contrast_ratio, resolve_theme

TEXT_ROLES = ("text", "muted", "ok", "warn", "err", "accent_text")


def test_both_palettes_have_the_same_roles():
    assert set(PALETTES["escuro"]) == set(PALETTES["claro"])


def test_team_red_is_kept_in_both_themes():
    assert PALETTES["escuro"]["primary"] == PALETTES["claro"]["primary"] == "#E4002B"


@pytest.mark.parametrize("name", sorted(PALETTES))
@pytest.mark.parametrize("role", TEXT_ROLES)
@pytest.mark.parametrize("surface", ["bg", "surface", "surface2"])
def test_text_colors_meet_wcag_aa_on_every_surface(name, role, surface):
    p = PALETTES[name]
    assert contrast_ratio(p[role], p[surface]) >= 4.5


@pytest.mark.parametrize("name", sorted(PALETTES))
def test_text_on_primary_buttons_is_readable(name):
    p = PALETTES[name]
    assert contrast_ratio(p["on_primary"], p["primary"]) >= 4.5


@pytest.mark.parametrize("choice, dark, expected", [
    ("escuro", False, "escuro"), ("claro", True, "claro"),
    ("sistema", True, "escuro"), ("sistema", False, "claro"), ("??", True, "escuro"),
])
def test_resolve_theme(choice, dark, expected):
    assert resolve_theme(choice, dark) == expected


def test_contrast_ratio_reference_values():
    assert contrast_ratio("#000000", "#FFFFFF") == pytest.approx(21)
    assert contrast_ratio("#777777", "#777777") == pytest.approx(1)
    assert set(THEME_CHOICES) == {"sistema", "escuro", "claro"}


@pytest.mark.parametrize("name", sorted(PALETTES))
@pytest.mark.parametrize("role", ["ok", "err", "warn", "primary"])
def test_on_color_gives_readable_text_on_status_backgrounds(name, role):
    from theme import on_color
    bg = PALETTES[name][role]
    assert contrast_ratio(on_color(bg), bg) >= 4.5
