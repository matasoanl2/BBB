from __future__ import annotations

import importlib
import importlib.util
import os
import re
import unicodedata

_wcwidth_char = None
if importlib.util.find_spec("wcwidth") is not None:
    _wcmod = importlib.import_module("wcwidth")
    _wcwidth_char = getattr(_wcmod, "wcwidth", None)

FORCE_DOUBLE_WIDTH_EMOJI = os.getenv("FORCE_DOUBLE_WIDTH_EMOJI", "true").lower() in {"1", "true", "yes", "on"}

# Emoji / symbols used in bet logs that are rendered as 2 terminal columns
# on most modern terminals (Windows Terminal, VS Code, etc.).
# NOTE: ✓ and ✗ are 1-column wide (confirmed by wcwidth); do NOT add them here.
DOUBLE_WIDTH_EMOJI = {"❌", "✅", "🧰", "🎲", "🔄", "♻", "🔴", "🟡", "💰"}


def visible_length(s: str) -> int:
    """Получить видимую ширину строки для терминала (без ANSI кодов)."""
    text = re.sub(r'\033\[[0-9;]*m', '', s)

    width = 0
    for ch in text:
        if unicodedata.combining(ch) or ch == "\ufe0f" or ch == "\u200d":
            continue
        if FORCE_DOUBLE_WIDTH_EMOJI and ch in DOUBLE_WIDTH_EMOJI:
            width += 2
        elif _wcwidth_char is not None:
            cw = _wcwidth_char(ch)
            width += cw if cw >= 0 else 1
        elif ch in DOUBLE_WIDTH_EMOJI:
            width += 2
        elif unicodedata.east_asian_width(ch) in {"W", "F"}:
            width += 2
        else:
            width += 1
    return width


def ansi_emoji_compensation(s: str) -> int:
    """Компенсация бага терминала: ANSI-цвет + несколько emoji в одном span."""
    if '\033[' not in s:
        return 0
    text = re.sub(r'\033\[[0-9;]*m', '', s)
    emoji_count = sum(1 for ch in text if ch in DOUBLE_WIDTH_EMOJI)
    return max(0, emoji_count - 1)


def pad_width(s: str, width: int) -> str:
    """Добавить пробелы для выравнивания, учитывая ANSI коды и emoji."""
    visible = visible_length(s)
    compensation = ansi_emoji_compensation(s)
    padding = width - visible - compensation
    if padding > 0:
        return s + ' ' * padding
    return s


def pad_width_center(s: str, width: int) -> str:
    """Добавить пробелы для центрирования, учитывая ANSI коды и emoji."""
    visible = visible_length(s)
    compensation = ansi_emoji_compensation(s)
    padding = width - visible - compensation
    if padding > 0:
        left = padding // 2
        right = padding - left
        return (' ' * left) + s + (' ' * right)
    return s


def format_outcome(outcome: str, specifier: str = "") -> str:
    if outcome == "double":
        return "🎲"
    if specifier:
        return f"{outcome}({specifier})"
    return outcome


def format_combo_pretty(combo: str) -> str:
    if combo == "double":
        return "🎲"
    if combo.startswith("red_"):
        value = combo.split("_")[1]
        return f"🔴 {value}"
    if combo.startswith("yellow_"):
        value = combo.split("_")[1]
        return f"🟡 {value}"
    return combo


def format_outcome_pretty(outcome: str, specifier: str = "") -> str:
    if outcome == "double":
        return "🎲"
    if outcome == "red":
        return f"🔴 {specifier}"
    if outcome == "yellow":
        return f"🟡 {specifier}"
    return format_outcome(outcome, specifier)


def format_result_pretty(result: str) -> str:
    if result.startswith("no_"):
        return "❌"
    if result == "double":
        return "🎲"
    if "_" in result:
        return format_combo_pretty(result)
    return result


def format_rolled_dice_pretty(dice_results: list) -> str:
    if not isinstance(dice_results, list) or len(dice_results) == 0:
        return "-"

    parts = []
    for dice in dice_results[:2]:
        color = dice.get("color") if isinstance(dice, dict) else None
        value = dice.get("value") if isinstance(dice, dict) else None

        if color in {"red", "yellow"} and value is not None:
            parts.append(format_combo_pretty(f"{color}_{value}"))
        else:
            parts.append("❔")

    return " ".join(parts)


def format_round_result_pretty(dice_results: list) -> str:
    if not isinstance(dice_results, list) or len(dice_results) < 2:
        return format_rolled_dice_pretty(dice_results)

    v1 = dice_results[0].get("value") if isinstance(dice_results[0], dict) else None
    v2 = dice_results[1].get("value") if isinstance(dice_results[1], dict) else None

    if isinstance(v1, int) and isinstance(v2, int) and v1 == v2:
        return f"🎲 {v1}"

    return format_rolled_dice_pretty(dice_results)