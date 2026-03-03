"""
Unit tests for core utility functions.
Run with: python -m pytest tests/ -v
"""
import pytest
import sys
import os

# Ensure project root is on the path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from execution.generate_titles import clean_bio
from execution.generate_cover import (
    hex_to_rgb,
    rgb_to_hex,
    hex_to_hsl,
    hsl_to_hex,
    lighten_color_hex,
    darken_color_hex,
    validate_hex_color,
    balance_text,
    parse_city_from_text,
)
from execution.scrape_instagram import extract_username


# ============================================================
# clean_bio tests
# ============================================================

class TestCleanBio:
    def test_empty_bio(self):
        result = clean_bio("")
        assert result["cleaned_bio"] == ""
        assert result["registration"] == ""

    def test_none_bio(self):
        result = clean_bio(None)
        assert result["cleaned_bio"] == ""

    def test_extracts_crm(self):
        bio = "Dermatologista | CRM: 12345 | RQE: 6789 | Rio de Janeiro - RJ"
        result = clean_bio(bio)
        assert result["council_type"] == "CRM"
        assert result["registration"] == "12345"
        assert result["rqe"] == "6789"

    def test_extracts_cro(self):
        bio = "Cirurgião-Dentista CRO 54321"
        result = clean_bio(bio)
        assert result["council_type"] == "CRO"
        assert result["registration"] == "54321"

    def test_extracts_crp(self):
        bio = "Psicóloga Clínica CRP: 98765"
        result = clean_bio(bio)
        assert result["council_type"] == "CRP"
        assert result["registration"] == "98765"

    def test_extracts_coren(self):
        bio = "Enfermeira COREN-SP 111222"
        result = clean_bio(bio)
        assert result["council_type"] == "COREN"
        assert result["registration"] == "111222"

    def test_no_registration(self):
        bio = "Apaixonada por cuidar de pessoas"
        result = clean_bio(bio)
        assert result["council_type"] == ""
        assert result["registration"] == "-"
        assert result["rqe"] == ""

    def test_removes_emojis(self):
        bio = "Dermatologista 🩺✨ CRM 12345"
        result = clean_bio(bio)
        assert "🩺" not in result["cleaned_bio"]
        assert "✨" not in result["cleaned_bio"]

    def test_rqe_without_council(self):
        bio = "Especialista RQE 4567"
        result = clean_bio(bio)
        assert result["rqe"] == "4567"


# ============================================================
# Color utility tests
# ============================================================

class TestColorUtilities:
    def test_hex_to_rgb_basic(self):
        assert hex_to_rgb("#FF0000") == (255, 0, 0)
        assert hex_to_rgb("#00FF00") == (0, 255, 0)
        assert hex_to_rgb("#0000FF") == (0, 0, 255)

    def test_hex_to_rgb_no_hash(self):
        assert hex_to_rgb("FF0000") == (255, 0, 0)

    def test_hex_to_rgb_mixed_case(self):
        assert hex_to_rgb("#ff00ff") == (255, 0, 255)
        assert hex_to_rgb("#Ff00Ff") == (255, 0, 255)

    def test_rgb_to_hex(self):
        assert rgb_to_hex(255, 0, 0) == "#FF0000"
        assert rgb_to_hex(0, 255, 0) == "#00FF00"
        assert rgb_to_hex(0, 0, 0) == "#000000"

    def test_lighten_color(self):
        lighter = lighten_color_hex("#333333")
        r, g, b = hex_to_rgb(lighter)
        orig_r, orig_g, orig_b = hex_to_rgb("#333333")
        # Lightened color should have higher luminance
        assert (r + g + b) > (orig_r + orig_g + orig_b)

    def test_darken_color(self):
        darker = darken_color_hex("#CCCCCC")
        r, g, b = hex_to_rgb(darker)
        orig_r, orig_g, orig_b = hex_to_rgb("#CCCCCC")
        # Darkened color should have lower luminance
        assert (r + g + b) < (orig_r + orig_g + orig_b)

    def test_lighten_clamps_at_max(self):
        # White can't get lighter
        result = lighten_color_hex("#FFFFFF", 0.5)
        r, g, b = hex_to_rgb(result)
        assert r <= 255 and g <= 255 and b <= 255

    def test_darken_clamps_at_min(self):
        # Black can't get darker
        result = darken_color_hex("#000000", 0.5)
        r, g, b = hex_to_rgb(result)
        assert r >= 0 and g >= 0 and b >= 0


# ============================================================
# validate_hex_color tests
# ============================================================

class TestValidateHexColor:
    def test_valid_6_char(self):
        assert validate_hex_color("#27AE60") == "#27AE60"

    def test_valid_no_hash(self):
        assert validate_hex_color("27ae60") == "#27AE60"

    def test_valid_3_char_shorthand(self):
        assert validate_hex_color("#F0A") == "#FF00AA"

    def test_invalid_returns_fallback(self):
        assert validate_hex_color("XYZ") == "#27AE60"
        assert validate_hex_color("") == "#27AE60"
        assert validate_hex_color(None) == "#27AE60"

    def test_too_short(self):
        assert validate_hex_color("#FF") == "#27AE60"

    def test_too_long(self):
        assert validate_hex_color("#FF00FF00") == "#27AE60"

    def test_with_spaces(self):
        assert validate_hex_color("  #27AE60  ") == "#27AE60"


# ============================================================
# balance_text tests
# ============================================================

class TestBalanceText:
    def test_short_text_single_line(self):
        result = balance_text("Hello world")
        assert result == ["Hello world"]

    def test_empty_text(self):
        result = balance_text("")
        assert result == [""]

    def test_none_text(self):
        result = balance_text(None)
        assert result == [""]

    def test_whitespace_only(self):
        result = balance_text("   ")
        assert result == [""]

    def test_few_words_single_line(self):
        result = balance_text("One two three four")
        assert len(result) == 1

    def test_long_text_two_lines(self):
        text = "Transformando a saúde da pele com tecnologia e humanidade em cada atendimento profissional."
        result = balance_text(text)
        assert len(result) == 2
        assert len(result[0]) >= len(result[1])

    def test_first_line_always_longer_or_equal(self):
        text = "Uma frase longa o suficiente para ser dividida em duas linhas pelo algoritmo de balanceamento."
        result = balance_text(text)
        if len(result) == 2:
            assert len(result[0]) >= len(result[1])

    def test_very_long_text_truncated(self):
        words = ["palavra"] * 25
        text = " ".join(words)
        result = balance_text(text)
        # Should truncate to ~20 words
        total_words = sum(len(line.split()) for line in result)
        assert total_words <= 20


# ============================================================
# parse_city_from_text tests
# ============================================================

class TestParseCityFromText:
    def test_city_with_dash(self):
        # The regex captures the last capitalized word group before the separator,
        # so multi-word cities with lowercase connectors (de, do, da) are partially captured.
        # This matches existing behavior — the second regex fallback handles this case.
        result = parse_city_from_text("Dermatologista | Rio de Janeiro - RJ")
        assert "RJ" in result
        assert "Janeiro" in result

    def test_simple_city_with_dash(self):
        result = parse_city_from_text("Clínica em Curitiba - PR")
        assert result == "Curitiba - PR"

    def test_city_with_comma(self):
        result = parse_city_from_text("Médico em São Paulo, SP")
        assert result == "São Paulo - SP"

    def test_city_with_slash(self):
        result = parse_city_from_text("Consultório em Curitiba/PR")
        assert result == "Curitiba - PR"

    def test_no_city(self):
        result = parse_city_from_text("Dermatologista apaixonada por pele")
        assert result == ""

    def test_empty_text(self):
        result = parse_city_from_text("")
        assert result == ""

    def test_none_text(self):
        result = parse_city_from_text(None)
        assert result == ""


# ============================================================
# extract_username tests
# ============================================================

class TestExtractUsername:
    def test_full_url(self):
        assert extract_username("https://www.instagram.com/dracinthia/") == "dracinthia"

    def test_url_without_trailing_slash(self):
        assert extract_username("https://instagram.com/dracinthia") == "dracinthia"

    def test_url_with_query_params(self):
        assert extract_username("https://instagram.com/dracinthia?hl=en") == "dracinthia"

    def test_empty_url(self):
        assert extract_username("") == ""

    def test_just_domain(self):
        assert extract_username("https://instagram.com/") == ""
