"""Сравнить все betting-стратегии на исторических round data из PostgreSQL."""
from __future__ import annotations

import argparse
import os
import sys
import statistics
from datetime import datetime
from pathlib import Path

import psycopg2
import yaml
from tabulate import tabulate

# UTF-8 encoding support
if sys.stdout.encoding and sys.stdout.encoding.lower() not in ['utf-8', 'utf8']:
    try:
        sys.stdout.reconfigure(encoding='utf-8', errors='ignore')
    except Exception:
        pass

# === DATABASE CONFIG ===
DB_USER = os.getenv("DB_USER", "postgres")
DB_PASSWORD = os.getenv("DB_PASSWORD", "postgres")
DB_HOST = os.getenv("DB_HOST", "localhost")
DB_PORT = os.getenv("DB_PORT", "5432")
DB_NAME = os.getenv("DB_NAME", "buybaybye")

ROOT_DIR = Path(__file__).resolve().parents[2]
STRATEGIES_DIR = ROOT_DIR / "strategies"


# ---------------------------------------------------------------------------
# Загрузка данных
# ---------------------------------------------------------------------------

def _parse_time_filter(tf: str):
    """Преобразовать человекочитаемый time filter в SQL interval tuple."""
    import re
    if tf == "all":
        return False, None
    try:
        return True, f"{int(tf)} hours"
    except ValueError:
        pass
    m = re.match(r'^(\d+)\s*(hour|hours|day|days|week|weeks|month|months)$', tf.strip(), re.I)
    if not m:
        print(f"❌ Неверный формат периода: '{tf}'")
        sys.exit(1)
    unit = m.group(2).lower().rstrip('s')
    unit_map = {'hour': 'hours', 'day': 'days', 'week': 'weeks', 'month': 'months'}
    return True, f"{m.group(1)} {unit_map.get(unit, unit + 's')}"


def load_rounds(time_filter: str = "1day"):
    """Загрузить исторические раунды из PostgreSQL для выбранного окна времени."""

    use_filter, interval = _parse_time_filter(time_filter)
    conn = psycopg2.connect(user=DB_USER, password=DB_PASSWORD,
                            host=DB_HOST, port=DB_PORT, database=DB_NAME)
    cur = conn.cursor()
    if use_filter:
        cur.execute(
            "SELECT timestamp, player_name, dice_results FROM game_results "
            f"WHERE timestamp >= NOW() - INTERVAL '{interval}' ORDER BY timestamp"
        )
    else:
        cur.execute("SELECT timestamp, player_name, dice_results FROM game_results ORDER BY timestamp")
    rows = cur.fetchall()
    cur.close()
    conn.close()
    rounds = []
    for ts, pn, dr in rows:
        rounds.append({"results": {**dr, "player": {"name": pn}}})
    return rounds


def load_strategies():
    """Загрузить все YAML-стратегии, используемые в сравнительном отчете."""

    strats = {}
    for f in sorted(STRATEGIES_DIR.glob("*.yaml")):
        try:
            with open(f, encoding="utf-8") as fh:
                strats[f.stem] = yaml.safe_load(fh)
        except Exception as e:
            print(f"⚠️  Ошибка загрузки {f.name}: {e}")
    return strats


# ---------------------------------------------------------------------------
# Симуляция
# ---------------------------------------------------------------------------

def simulate(rounds, bet_type, bet_specifier, strategy, base_bet):
    """Прогнать одну стратегию по историческим раундам и собрать итоговые метрики."""
    coefficients = strategy["coefficients"]
    payout = strategy.get("payout_coefficient", 5.7)
    max_steps = len(coefficients)

    step = 0
    balance = 0.0
    peak_balance = 0.0
    max_drawdown = 0.0

    total_bets = 0
    total_bet_amount = 0.0
    wins = 0
    losses = 0

    streak = 0
    longest_streak = 0
    all_streaks = []          # длины всех серий проигрышей
    _in_streak = False

    balance_history = []      # для кривой баланса

    for rnd in rounds:
        dice = rnd["results"].get("dice", [])
        if len(dice) < 2:
            continue

        # Определить исход
        win = False
        if bet_type == "double":
            vals = [d.get("value") for d in dice]
            win = len(vals) == 2 and vals[0] == vals[1]
        else:
            # red / yellow
            for d in dice:
                if d.get("color") == bet_type and d.get("value") == bet_specifier:
                    win = True
                    break

        bet_amount = base_bet * coefficients[step]
        balance -= bet_amount
        total_bets += 1
        total_bet_amount += bet_amount

        if win:
            payout_amount = bet_amount * payout
            balance += payout_amount
            wins += 1
            step = 0

            if _in_streak:
                all_streaks.append(streak)
                _in_streak = False
            streak = 0
        else:
            losses += 1
            streak += 1
            longest_streak = max(longest_streak, streak)
            _in_streak = True

            step += 1
            if step >= max_steps:
                step = 0
                all_streaks.append(streak)
                streak = 0
                _in_streak = False

        # Drawdown
        if balance > peak_balance:
            peak_balance = balance
        dd = peak_balance - balance
        if dd > max_drawdown:
            max_drawdown = dd

        balance_history.append(balance)

    if _in_streak and streak > 0:
        all_streaks.append(streak)

    if total_bets == 0:
        return None

    roi = (balance / total_bet_amount * 100) if total_bet_amount else 0.0
    win_rate = (wins / total_bets * 100) if total_bets else 0.0
    avg_streak = (statistics.mean(all_streaks) if all_streaks else 0.0)
    median_streak = (statistics.median(all_streaks) if all_streaks else 0.0)

    # Максимальная ставка в цикле
    max_bet = base_bet * max(coefficients)
    total_cycle_cost = base_bet * sum(coefficients)

    return {
        "total_bets": total_bets,
        "wins": wins,
        "losses": losses,
        "win_rate": win_rate,
        "profit": balance,
        "roi": roi,
        "max_drawdown": max_drawdown,
        "longest_streak": longest_streak,
        "avg_streak": avg_streak,
        "median_streak": median_streak,
        "max_bet": max_bet,
        "total_cycle_cost": total_cycle_cost,
        "steps": max_steps,
        "balance_history": balance_history,
    }


# ---------------------------------------------------------------------------
# Отображение
# ---------------------------------------------------------------------------

def format_comparison_table(results, sort_key):
    """Сформировать основную сравнительную таблицу для всех симулированных стратегий."""

    rows = sorted(results, key=lambda r: r[sort_key], reverse=(sort_key != "max_drawdown"))

    table = []
    for i, r in enumerate(rows, 1):
        profit_str = f"{r['profit']:+.0f}р"
        roi_str = f"{r['roi']:+.2f}%"
        dd_str = f"-{r['max_drawdown']:.0f}р"
        table.append([
            i,
            r["strategy"],
            r["steps"],
            f"{r['max_bet']:.0f}р",
            f"{r['total_cycle_cost']:.0f}р",
            f"{r['win_rate']:.1f}%",
            profit_str,
            roi_str,
            dd_str,
            r["longest_streak"],
            f"{r['avg_streak']:.1f}",
        ])

    headers = [
        "#", "Стратегия", "Шаги", "Макс.\nставка", "Цена\nцикла",
        "Win%", "Профит", "ROI", "Макс.\nпросадка",
        "Макс.\nсерия", "Ср.\nсерия",
    ]

    return tabulate(table, headers=headers, tablefmt="simple_grid", stralign="right", numalign="right")


def format_top_bottom(results, n=3):
    """Сформировать сводки по лучшим, худшим и самым безопасным стратегиям."""
    lines = []
    by_roi = sorted(results, key=lambda r: r["roi"], reverse=True)

    lines.append(f"\n🏆 ТОП-{n} ПО ROI:")
    for i, r in enumerate(by_roi[:n], 1):
        lines.append(f"  {i}. {r['strategy']:30} ROI={r['roi']:+.2f}%  Профит={r['profit']:+.0f}р  Просадка=-{r['max_drawdown']:.0f}р")

    lines.append(f"\n💀 АНТИТОП-{n} ПО ROI:")
    for i, r in enumerate(reversed(by_roi[-n:]), 1):
        lines.append(f"  {i}. {r['strategy']:30} ROI={r['roi']:+.2f}%  Профит={r['profit']:+.0f}р  Просадка=-{r['max_drawdown']:.0f}р")

    # Самая безопасная (минимальная просадка)
    by_dd = sorted(results, key=lambda r: r["max_drawdown"])
    lines.append(f"\n🛡️  МИНИМАЛЬНАЯ ПРОСАДКА:")
    for i, r in enumerate(by_dd[:n], 1):
        lines.append(f"  {i}. {r['strategy']:30} Просадка=-{r['max_drawdown']:.0f}р  ROI={r['roi']:+.2f}%  Макс.серия={r['longest_streak']}")

    # Самая короткая средняя серия проигрышей
    by_streak = sorted(results, key=lambda r: r["avg_streak"])
    lines.append(f"\n⚡ SHORTEST AVG LOSING STREAK:")
    for i, r in enumerate(by_streak[:n], 1):
        lines.append(f"  {i}. {r['strategy']:30} Ср.серия={r['avg_streak']:.1f}  Макс.серия={r['longest_streak']}  ROI={r['roi']:+.2f}%")

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Генерация секции отчёта для одной комбинации ставки
# ---------------------------------------------------------------------------

def _bet_label(bet_type, specifier):
    """Собрать человекочитаемую подпись для целевой комбинации ставки."""

    if bet_type == "double":
        return "🎲 DOUBLE (любой дубль)"
    icon = "🔴" if bet_type == "red" else "🟡"
    return f"{icon} {bet_type.upper()} {specifier}"


def _run_single(rounds, strategies, bet_type, specifier, base_bet, sort_key):
    """Прогнать все стратегии для одной целевой комбинации и собрать секции отчета."""
    results = []
    for name, data in strategies.items():
        r = simulate(rounds, bet_type, specifier, data, base_bet)
        if r:
            r["strategy"] = name
            results.append(r)
    if not results:
        return None

    table_text = format_comparison_table(results, sort_key)
    top_bottom_text = format_top_bottom(results, n=3)

    best = max(results, key=lambda r: r["roi"])
    safest = min(results, key=lambda r: r["max_drawdown"])
    summary_text = (
        f"\n{'=' * 80}\n"
        f"📌 ИТОГ: Лучшая по ROI = {best['strategy']} ({best['roi']:+.2f}%)\n"
        f"📌 ИТОГ: Самая безопасная = {safest['strategy']} (просадка -{safest['max_drawdown']:.0f}р)\n"
        f"{'=' * 80}\n"
    )
    return results, table_text, top_bottom_text, summary_text


ALL_COMBOS = (
    [("red", v) for v in range(1, 7)]
    + [("yellow", v) for v in range(1, 7)]
    + [("double", 0)]
)


# ---------------------------------------------------------------------------
# Точка входа
# ---------------------------------------------------------------------------

def main():
    """CLI-точка входа для сравнительных отчетов по стратегиям."""

    parser = argparse.ArgumentParser(
        description="Сравнение всех стратегий на исторических данных из PostgreSQL"
    )
    parser.add_argument("--time-filter", default="1day",
                        help="Период: 'all', '3hours', '1day', '7days', '1week', '1month' (по умолчанию: 1day)")
    parser.add_argument("--bet", default="all", choices=["red", "yellow", "double", "all"],
                        help="Тип ставки или 'all' для всех комбинаций (по умолчанию: all)")
    parser.add_argument("--specifier", type=int, default=5,
                        help="Значение кубика 1-6 для red/yellow (по умолчанию: 5, игнорируется при --bet all)")
    parser.add_argument("--base-bet", type=float, default=10,
                        help="Базовая ставка (по умолчанию: 10)")
    parser.add_argument("--sort", default="roi",
                        choices=["roi", "profit", "max_drawdown", "win_rate", "avg_streak", "longest_streak"],
                        help="Сортировка таблицы (по умолчанию: roi)")
    args = parser.parse_args()

    is_all = args.bet == "all"
    combos = ALL_COMBOS if is_all else [(args.bet, args.specifier if args.bet != "double" else 0)]

    print("\n" + "=" * 80)
    print("📊 СРАВНЕНИЕ СТРАТЕГИЙ")
    print("=" * 80)
    if is_all:
        print(f"  Ставка:      ВСЕ КОМБИНАЦИИ ({len(combos)} шт.)")
    else:
        print(f"  Ставка:      {_bet_label(args.bet, args.specifier)}")
    print(f"  Базовая:     {args.base_bet:.0f}р")
    print(f"  Период:      {args.time_filter}")
    print(f"  Сортировка:  {args.sort}")
    print("=" * 80 + "\n")

    # Загрузка
    print("📥 Загрузка раундов из PostgreSQL...", flush=True)
    try:
        rounds = load_rounds(args.time_filter)
    except Exception as e:
        print(f"❌ Ошибка подключения к БД: {e}")
        sys.exit(1)

    if not rounds:
        print("❌ Нет данных за указанный период.")
        sys.exit(1)
    print(f"✅ Загружено {len(rounds)} раундов\n")

    strategies = load_strategies()
    if not strategies:
        print("❌ Стратегии не найдены в strategies/")
        sys.exit(1)
    print(f"✅ Загружено {len(strategies)} стратегий\n")

    # Симуляция по комбинациям
    report_parts = []      # секции отчёта для файла
    console_parts = []     # то же для консоли (без шапки)

    for idx, (bt, spec) in enumerate(combos, 1):
        label = _bet_label(bt, spec)
        progress = f"[{idx}/{len(combos)}]" if is_all else ""
        print(f"⏳ {progress} Симуляция {label}...", flush=True)

        result = _run_single(rounds, strategies, bt, spec, args.base_bet, args.sort)
        if result is None:
            print(f"  ⚠️  Нет результатов для {label}\n")
            continue

        _results, table_text, top_bottom_text, summary_text = result

        section_header = (
            f"\n{'━' * 80}\n"
            f"  {label}\n"
            f"{'━' * 80}\n"
        )

        section = section_header + "\n" + table_text + "\n" + top_bottom_text + "\n" + summary_text
        report_parts.append(section)

        # Консоль: печатаем сразу
        print(section)

    if not report_parts:
        print("❌ Ни одна комбинация не дала результатов.")
        sys.exit(1)

    # Сохранение отчёта в файл
    if is_all:
        bet_display = f"ВСЕ КОМБИНАЦИИ ({len(combos)} шт.)"
    else:
        bet_display = _bet_label(args.bet, args.specifier)

    header_text = (
        "=" * 80 + "\n"
        "📊 СРАВНЕНИЕ СТРАТЕГИЙ\n"
        + "=" * 80 + "\n"
        f"  Ставка:      {bet_display}\n"
        f"  Базовая:     {args.base_bet:.0f}р\n"
        f"  Период:      {args.time_filter}\n"
        f"  Раундов:     {len(rounds)}\n"
        f"  Стратегий:   {len(strategies)}\n"
        f"  Сортировка:  {args.sort}\n"
        f"  Дата:        {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n"
        + "=" * 80 + "\n"
    )
    report = header_text + "\n".join(report_parts)

    reports_dir = ROOT_DIR / "reports"
    reports_dir.mkdir(exist_ok=True)

    ts = datetime.now().strftime("%Y-%m-%d_%H-%M")
    if is_all:
        bet_part = "all"
    elif args.bet == "double":
        bet_part = "double"
    else:
        bet_part = f"{args.bet}{args.specifier}"
    filename = f"compare_{bet_part}_{args.time_filter}_base{args.base_bet:.0f}_{ts}.txt"
    filepath = reports_dir / filename

    filepath.write_text(report, encoding="utf-8")
    print(f"\n💾 Отчёт сохранён: {filepath}")


if __name__ == "__main__":
    main()
