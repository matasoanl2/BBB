"""
Полный анализ всех комбинаций red/yellow (1-6) со всеми стратегиями
Выводит результаты по каждой комбинации и стратегии, затем ТОП-5 по выигрышам
"""
import os
import sys
import psycopg2
import yaml
import argparse
import statistics
from datetime import datetime, timezone, timedelta
from pathlib import Path
from itertools import product
from tabulate import tabulate

# UTF-8 encoding support
if sys.stdout.encoding.lower() not in ['utf-8', 'utf8']:
    try:
        sys.stdout.reconfigure(encoding='utf-8', errors='ignore')
    except:
        pass

# === SETTINGS ===
START_BALANCE = 10000
COEFF = 5.7
DICE_NUMBERS = [1, 2, 3, 4, 5, 6]
DICE_COLORS = ["red", "yellow"]
DICE_DOUBLES = [1, 2, 3, 4, 5, 6]  # Дубли (оба кубика одинакового значения)

# === DATABASE CONFIG ===
DB_USER = os.getenv("DB_USER", "postgres")
DB_PASSWORD = os.getenv("DB_PASSWORD", "postgres")
DB_HOST = os.getenv("DB_HOST", "localhost")
DB_PORT = os.getenv("DB_PORT", "5432")
DB_NAME = os.getenv("DB_NAME", "buybaybye")

# === PATHS ===
STRATEGIES_DIR = Path(__file__).resolve().parent / "strategies"


def parse_time_period(time_filter):
    """Парсер гибких периодов времени
    
    Поддерживаемые форматы:
    - "all"               -> нет фильтра (все данные)
    - "1hour", "2hours"   -> часы
    - "1day", "7days"     -> дни
    - "1week", "2weeks"   -> недели
    - "1month", "3months" -> месяцы
    - Число (e.g., "3")   -> часы (для обратной совместимости)
    
    Returns:
        tuple: (use_filter: bool, interval_str: str for SQL)
            или None если 'all'
    """
    import re
    
    if time_filter == "all":
        return (False, None)
    
    # Пытаемся распарсить как регулярное число (часы для обратной совместимости)
    try:
        hours = int(time_filter)
        return (True, f"{hours} hours")
    except ValueError:
        pass
    
    # Ищем шаблон "number + unit"
    match = re.match(r'^(\d+)\s*(hour|hours|day|days|week|weeks|month|months)$', time_filter.strip(), re.IGNORECASE)
    
    if not match:
        raise ValueError(
            f"❌ Неверный формат периода: '{time_filter}'\n"
            f"Поддерживаемые форматы:\n"
            f"  - 'all' (все данные)\n"
            f"  - '3' или '3hours' (последние 3 часа)\n"
            f"  - '1day', '7days' (дни)\n"
            f"  - '1week', '2weeks' (недели)\n"
            f"  - '1month', '3months' (месяцы)\n"
            f"Пример: --time-filter 6hours или --time-filter 1day"
        )
    
    number = match.group(1)
    unit = match.group(2).lower().rstrip('s')  # Приводим "hours" -> "hour", "days" -> "day"
    
    # Нормализуем единицы для SQL
    unit_map = {
        'hour': 'hours',
        'day': 'days',
        'week': 'weeks',
        'month': 'months'
    }
    
    sql_unit = unit_map.get(unit, unit + 's')
    interval_str = f"{number} {sql_unit}"
    
    return (True, interval_str)


def get_rounds_from_db(time_filter="all"):
    """Получить раунды из PostgreSQL
    
    Args:
        time_filter: Строка с периодом времени (см. parse_time_period для поддерживаемых форматов)
    """
    try:
        # Парсим время фильтра
        try:
            use_filter, interval_str = parse_time_period(time_filter)
        except ValueError as e:
            print(str(e))
            exit(1)
        
        conn = psycopg2.connect(
            user=DB_USER,
            password=DB_PASSWORD,
            host=DB_HOST,
            port=DB_PORT,
            database=DB_NAME
        )
        cursor = conn.cursor()
        
        # SQL запрос с опциональным фильтром времени
        if not use_filter:
            query = """
                SELECT timestamp, player_name, dice_results 
                FROM game_results 
                ORDER BY timestamp ASC
            """
        else:
            query = f"""
                SELECT timestamp, player_name, dice_results 
                FROM game_results 
                WHERE timestamp >= NOW() - INTERVAL '{interval_str}'
                ORDER BY timestamp ASC
            """
        
        cursor.execute(query)
        rows = cursor.fetchall()
        cursor.close()
        conn.close()
        
        rounds = []
        for row in rows:
            timestamp, player_name, dice_results = row
            rounds.append({
                "timestamp": timestamp.isoformat() if isinstance(timestamp, datetime) else str(timestamp),
                "results": {
                    **dice_results,
                    "player": {"name": player_name}
                }
            })
        
        return rounds
    except Exception as e:
        print(f"❌ Ошибка подключения к БД: {e}")
        print("Убедитесь, что PostgreSQL запущен и доступен.")
        exit(1)


def load_strategies():
    """Загружает все стратегии из папки strategies"""
    strategies = {}
    
    if not STRATEGIES_DIR.exists():
        print(f"❌ Папка стратегий не найдена: {STRATEGIES_DIR}")
        return strategies
    
    for strategy_file in sorted(STRATEGIES_DIR.glob("*.yaml")):
        try:
            with open(strategy_file, "r", encoding="utf-8") as f:
                strategy = yaml.safe_load(f)
                strategy_name = strategy_file.stem
                strategies[strategy_name] = strategy
        except Exception as e:
            print(f"⚠️  Ошибка загрузки стратегии {strategy_file.name}: {e}")
    
    return strategies


def calculate_periodicity(rounds, bet_type, bet_value):
    """
    Расчитывает периодичность выпадения ставки (период в КОЛИЧЕСТВЕ ХОДОВ/РАУНДОВ)
    
    Args:
        rounds: список раундов из БД
        bet_type: тип ставки - "color", "double", "any_double"
        bet_value: значение ставки
    
    Returns:
        dict с периодичностью:
        - occurrences: количество выпадений
        - min_period: минимум ходов между выпадениями
        - max_period: максимум ходов между выпадениями
        - avg_period: среднее количество ходов между выпадениями
        - median_period: медиана ходов между выпадениями
    """
    
    win_rounds = []
    
    for idx, rnd in enumerate(rounds):
        win = False
        
        if bet_type == "color":
            dice_color, dice_number = bet_value
            for d in rnd["results"]["dice"]:
                if d["color"] == dice_color and d["value"] == dice_number:
                    win = True
                    break
        elif bet_type == "double":
            double_value = bet_value
            dice_values = [d["value"] for d in rnd["results"]["dice"]]
            if len(dice_values) == 2 and all(v == double_value for v in dice_values):
                win = True
        elif bet_type == "any_double":
            dice_values = [d["value"] for d in rnd["results"]["dice"]]
            if len(dice_values) == 2 and dice_values[0] == dice_values[1]:
                win = True
        
        if win:
            win_rounds.append(idx)
    
    # Вычислить интервалы между выпадениями
    intervals = []
    for i in range(1, len(win_rounds)):
        interval = win_rounds[i] - win_rounds[i-1]
        intervals.append(interval)
    
    # Если нет интервалов (0 или 1 выпадение), возвращаем None
    if not intervals:
        return {
            "occurrences": len(win_rounds),
            "min_period": None,
            "max_period": None,
            "avg_period": None,
            "median_period": None,
        }
    
    # Вычислить статистику
    min_period = min(intervals)
    max_period = max(intervals)
    avg_period = sum(intervals) / len(intervals)
    median_period = statistics.median(intervals)
    
    return {
        "occurrences": len(win_rounds),
        "min_period": min_period,
        "max_period": max_period,
        "avg_period": avg_period,
        "median_period": median_period,
    }


def analyze_combination(rounds, bet_type, bet_value, strategy_name, strategy_data, base_bet=10, start_step=0):
    """
    Анализирует результаты для конкретной комбинации и стратегии, начиная с указанного шага
    
    Args:
        rounds: список раундов из БД
        bet_type: тип ставки - "color" (красный/чёрный), "double" (конкретный дубль), или "any_double" (любой дубль)
        bet_value: значение (для color: (color, number) tuple, для double: число 1-6, для any_double: "any")
        strategy_name: название стратегии
        strategy_data: данные стратегии (coefficients, payout_coefficient)
        base_bet: базовая ставка
        start_step: начальный шаг прогрессии (для вычисления вариаций)
    
    Returns:
        dict с результатами анализа
    """
    
    bet_sequence = [base_bet * coeff for coeff in strategy_data["coefficients"]]
    payout_coeff = strategy_data["payout_coefficient"]
    
    balance = START_BALANCE
    step = start_step
    total_bets = 0
    total_wins = 0
    total_losses = 0
    total_bet_amount = 0
    total_win_amount = 0
    current_losing_streak = 0
    longest_losing_streak = 0
    
    for rnd in rounds:
        # Проверяем результат в зависимости от типа ставки
        win = False
        
        if bet_type == "color":
            # Ставка на красный/чёрный кубик
            dice_color, dice_number = bet_value
            for d in rnd["results"]["dice"]:
                if d["color"] == dice_color and d["value"] == dice_number:
                    win = True
                    break
        elif bet_type == "double":
            # Ставка на дубль конкретного значения (оба кубика одинакового значения)
            double_value = bet_value
            dice_values = [d["value"] for d in rnd["results"]["dice"]]
            # Проверяем что оба кубика установленного значения
            if len(dice_values) == 2 and all(v == double_value for v in dice_values):
                win = True
        elif bet_type == "any_double":
            # Ставка на ЛЮБОй дубль (оба кубика одинакового значения)
            dice_values = [d["value"] for d in rnd["results"]["dice"]]
            # Проверяем что оба кубика имеют одинаковое значение (не важно какое)
            if len(dice_values) == 2 and dice_values[0] == dice_values[1]:
                win = True
        
        bet = bet_sequence[step]
        balance -= bet
        total_bets += 1
        total_bet_amount += bet
        
        if win:
            payout = bet * payout_coeff
            balance += payout
            total_wins += 1
            total_win_amount += payout
            current_losing_streak = 0
            step = 0
        else:
            total_losses += 1
            current_losing_streak += 1
            longest_losing_streak = max(longest_losing_streak, current_losing_streak)
            step += 1
            if step >= len(bet_sequence):
                step = 0
    
    profit = balance - START_BALANCE
    win_rate = (total_wins / total_bets * 100) if total_bets else 0
    roi = (profit / total_bet_amount * 100) if total_bet_amount else 0
    final_balance = balance
    
    # Формируем название комбинации
    if bet_type == "color":
        combination_name = f"{bet_value[0].upper()}{bet_value[1]}"
    elif bet_type == "double":
        combination_name = f"DOUBLE_{bet_value}"
    elif bet_type == "any_double":
        combination_name = "DOUBLE"
    else:
        combination_name = "UNKNOWN"
    
    return {
        "combination": combination_name,
        "strategy": strategy_name,
        "total_bets": total_bets,
        "total_wins": total_wins,
        "total_losses": total_losses,
        "win_rate": win_rate,
        "longest_streak": longest_losing_streak,
        "total_bet_amount": total_bet_amount,
        "total_win_amount": total_win_amount,
        "start_balance": START_BALANCE,
        "final_balance": final_balance,
        "profit": profit,
        "roi": roi,
    }


def analyze_combination_averaged(rounds, bet_type, bet_value, strategy_name, strategy_data, base_bet=10):
    """
    Анализирует комбинацию со ВСЕМИ вариациями и возвращает УСРЕДНЁННЫЕ результаты
    
    Проводит анализ для каждого возможного начального шага прогрессии
    (количество вариаций = количество коэффициентов в стратегии)
    и усредняет результаты.
    
    Args:
        rounds: список раундов из БД
        bet_type: тип ставки
        bet_value: значение ставки
        strategy_name: название стратегии
        strategy_data: данные стратегии
        base_bet: базовая ставка
    
    Returns:
        dict с усреднёнными результатами по всем вариациям
    """
    
    num_variations = len(strategy_data["coefficients"])
    
    # Собрать результаты для каждой вариации (каждого стартового шага)
    variations_results = []
    for start_step in range(num_variations):
        result = analyze_combination(
            rounds, bet_type, bet_value, strategy_name, strategy_data, base_bet, start_step
        )
        variations_results.append(result)
    
    # Усреднить результаты по всем вариациям
    avg_total_bets = sum(r["total_bets"] for r in variations_results) / num_variations
    avg_total_wins = sum(r["total_wins"] for r in variations_results) / num_variations
    avg_total_losses = sum(r["total_losses"] for r in variations_results) / num_variations
    avg_win_rate = sum(r["win_rate"] for r in variations_results) / num_variations
    avg_longest_streak = sum(r["longest_streak"] for r in variations_results) / num_variations
    avg_bet_amount = sum(r["total_bet_amount"] for r in variations_results) / num_variations
    avg_win_amount = sum(r["total_win_amount"] for r in variations_results) / num_variations
    avg_profit = sum(r["profit"] for r in variations_results) / num_variations
    avg_final_balance = sum(r["final_balance"] for r in variations_results) / num_variations
    avg_roi = (avg_profit / avg_bet_amount * 100) if avg_bet_amount else 0
    
    # Формируем название комбинации
    if bet_type == "color":
        combination_name = f"{bet_value[0].upper()}{bet_value[1]}"
    elif bet_type == "double":
        combination_name = f"DOUBLE_{bet_value}"
    elif bet_type == "any_double":
        combination_name = "DOUBLE"
    else:
        combination_name = "UNKNOWN"
    
    # Вычислить периодичность выпадения
    periodicity = calculate_periodicity(rounds, bet_type, bet_value)
    
    return {
        "combination": combination_name,
        "strategy": strategy_name,
        "num_variations": num_variations,
        "total_bets": avg_total_bets,
        "total_wins": avg_total_wins,
        "total_losses": avg_total_losses,
        "win_rate": avg_win_rate,
        "longest_streak": avg_longest_streak,
        "total_bet_amount": avg_bet_amount,
        "total_win_amount": avg_win_amount,
        "start_balance": START_BALANCE,
        "final_balance": avg_final_balance,
        "profit": avg_profit,
        "roi": avg_roi,
        "periodicity": periodicity,
    }


def main():
    # Парсинг аргументов командной строки
    parser = argparse.ArgumentParser(description="Полный анализ всех комбинаций и стратегий")
    parser.add_argument(
        "--mode",
        type=str,
        default="full",
        choices=["full", "periodicity", "combined"],
        help="Режим анализа (full=полный, periodicity=только периодичность, combined=полный+периодичность)"
    )
    parser.add_argument(
        "--time-filter",
        type=str,
        default="all",
        help="Гибкий фильтр времени: 'all' (все), '3' или '3hours', '1day', '7days', '1week', '1month'. Примеры: --time-filter all | --time-filter 3hours | --time-filter 1day"
    )
    
    args = parser.parse_args()
    
    # Переопределить TIME_FILTER если передан аргумент
    time_mode = args.time_filter
    analysis_mode = args.mode
    
    output_file = Path(__file__).resolve().parent / "analys_comprehensive_results.txt"
    
    print("\n" + "="*100)
    print("🔍 ПОЛНЫЙ АНАЛИЗ ВСЕХ КОМБИНАЦИЙ (RED/YELLOW и DOUBLE) СО ВСЕМИ СТРАТЕГИЯМИ")
    print("🎲 Методология: УСРЕДНЕНИЕ ПО ВАРИАЦИЯМ (кол-во вариаций = элементы в коэффициентах)")
    print(f"📊 Режим анализа: {analysis_mode.upper()}")
    print("="*100 + "\n")
    
    # Determine time filter mode
    if time_mode == "3hours":
        print("⏰ РЕЖИМ: Анализ последних 3 часов\n", flush=True)
    else:
        print("📊 РЕЖИМ: Анализ ВСЕ данных из БД\n", flush=True)
    
    # Load data
    print("📥 Подключение к PostgreSQL...", flush=True)
    rounds = get_rounds_from_db(time_filter=time_mode)
    
    if not rounds:
        print("❌ ОШИБКА: Нет данных в базе данных. Запустите main.py первым.")
        exit(1)
    
    print(f"✅ Загружено {len(rounds)} раундов из БД\n")
    
    # Load strategies
    print("📋 Загрузка стратегий...", flush=True)
    strategies = load_strategies()
    
    if not strategies:
        print("❌ ОШИБКА: Стратегии не найдены.")
        exit(1)
    
    print(f"✅ Загружено {len(strategies)} стратегий\n")
    
    # Generate all combinations (red/yellow + any_double)
    color_combinations = list(product(DICE_COLORS, DICE_NUMBERS))  # red/yellow combinations
    double_combinations = [('double', 'any')]                       # any_double combination (unified event)
    
    total_combinations = color_combinations + double_combinations
    
    print(f"🎲 Цветных комбинаций: {len(color_combinations)} (RED/YELLOW 1-6)")
    print(f"🔱 Дублей: {len(double_combinations)} (DOUBLE - любой дубль)")
    print(f"📊 Стратегий: {len(strategies)}")
    print(f"🔢 Общее количество анализов: {len(total_combinations) * len(strategies)}\n")
    
    # === ANALYZE ALL COMBINATIONS AND STRATEGIES ===
    print("⏳ Анализ в процессе...\n")
    
    results = []
    analysis_count = 0
    total_analyses = len(total_combinations) * len(strategies)
    
    # Analyze color combinations
    for color, number in color_combinations:
        for strategy_name, strategy_data in strategies.items():
            result = analyze_combination_averaged(
                rounds, "color", (color, number), strategy_name, strategy_data
            )
            results.append(result)
            
            analysis_count += 1
            if analysis_count % 36 == 0:
                print(f"   {analysis_count}/{total_analyses} анализов готово...")
    
    # Analyze any_double combination
    for _, _ in double_combinations:
        for strategy_name, strategy_data in strategies.items():
            result = analyze_combination_averaged(
                rounds, "any_double", "any", strategy_name, strategy_data
            )
            results.append(result)
            
            analysis_count += 1
            if analysis_count % 36 == 0:
                print(f"   {analysis_count}/{total_analyses} анализов готово...")
    
    print(f"✅ Все {total_analyses} анализов выполнены!\n")
    
    # Sort results
    results_sorted_profit = sorted(results, key=lambda x: x["profit"], reverse=True)
    results_sorted_roi = sorted(results, key=lambda x: x["roi"], reverse=True)
    
    # Open output file for writing
    with open(output_file, "w", encoding="utf-8") as f:
        # === ALL RESULTS BY COMBINATIONS ===
        time_mode_str = "Последние 3 часа" if time_mode == "3hours" else "Все данные"
        
        f.write("\n" + "="*120 + "\n")
        f.write(f"ВСЕ РЕЗУЛЬТАТЫ (ОТСОРТИРОВАНЫ ПО ПРОФИТУ) - Режим: {time_mode_str}\n")
        f.write("="*120 + "\n\n")
        
        print(f"📊 ВСЕ РЕЗУЛЬТАТЫ (отсортированы по ПРОФИТУ) - {time_mode_str}")
        
        # Group by combinations
        combinations_results = {}
        for result in results_sorted_profit:
            combo = result["combination"]
            if combo not in combinations_results:
                combinations_results[combo] = []
            combinations_results[combo].append(result)
        
        # Separate color and double combinations for better readability
        color_combos = {k: v for k, v in combinations_results.items() if not k.startswith("DOUBLE")}  # RED/YELLOW
        double_combos = {k: v for k, v in combinations_results.items() if k.startswith("DOUBLE")}  # DOUBLE"}
        
        # Output results for each combination
        # Print COLOR combinations first
        f.write("\n🔴 ЦВЕТНЫЕ КОМБИНАЦИИ (RED/YELLOW 1-6)\n\n")
        for combo in sorted(color_combos.keys()):
            f.write(f"\n🎲 КОМБИНАЦИЯ: {combo}\n")
            f.write("-" * 120 + "\n\n")
            
            table_data = []
            for result in color_combos[combo]:
                row = [
                    result["strategy"],
                    result.get("num_variations", "?"),
                    f"{result['total_bets']:.0f}",
                    f"{result['total_wins']:.0f}",
                    f"{result['win_rate']:.1f}%",
                    f"{result['longest_streak']:.0f}",
                    f"{result['total_bet_amount']:.0f}р",
                    f"{result['total_win_amount']:.0f}р",
                    f"{result['profit']:+.0f}р",
                    f"{result['roi']:+.2f}%",
                    f"{result['final_balance']:.0f}р"
                ]
                
                # Добавить периодичность если режим требует
                if analysis_mode in ["periodicity", "combined"]:
                    per = result["periodicity"]
                    if per["min_period"] is not None:
                        row.extend([
                            f"{per['occurrences']}",
                            f"{per['min_period']}",
                            f"{per['max_period']}",
                            f"{per['avg_period']:.1f}",
                            f"{per['median_period']:.1f}"
                        ])
                    else:
                        row.extend(["0", "-", "-", "-", "-"])
                
                table_data.append(row)
            
            headers = [
                "Стратегия",
                "Вариаций",
                "Ставок",
                "Побед",
                "Win%",
                "МаксСерия",
                "СуммаСтавок",
                "СуммаВыплат",
                "Профит",
                "ROI%",
                "Баланс"
            ]
            
            if analysis_mode in ["periodicity", "combined"]:
                headers.extend([
                    "Выпадений",
                    "Мин период (ходов)",
                    "Макс период (ходов)",
                    "Сред период (ходов)",
                    "Медиана период (ходов)"
                ])
            
            table_str = tabulate(table_data, headers=headers, tablefmt="grid")
            f.write(table_str)
            print(f"  ✅ {combo} обработана")
        
        # Print DOUBLE combinations
        if double_combos:
            f.write("\n\n" + "="*120 + "\n")
            f.write("🔱 ДУБЛИ (DOUBLE - ЛЮБОЙ ДУБЛЬ)\n\n")
            for combo in sorted(double_combos.keys()):
                f.write(f"\n🎲 КОМБИНАЦИЯ: {combo}\n")
                f.write("-" * 120 + "\n\n")
                
                table_data = []
                for res in double_combos[combo]:
                    row = [
                        res["strategy"],
                        res.get("num_variations", "?"),
                        f"{res['total_bets']:.0f}",
                        f"{res['total_wins']:.0f}",
                        f"{res['win_rate']:.1f}%",
                        f"{res['longest_streak']:.0f}",
                        f"{res['total_bet_amount']:.0f}р",
                        f"{res['total_win_amount']:.0f}р",
                        f"{res['profit']:+.0f}р",
                        f"{res['roi']:+.2f}%",
                        f"{res['final_balance']:.0f}р",
                    ]
                    
                    # Добавить периодичность если режим требует
                    if analysis_mode in ["periodicity", "combined"]:
                        per = res["periodicity"]
                        if per["min_period"] is not None:
                            row.extend([
                                f"{per['occurrences']}",
                                f"{per['min_period']}",
                                f"{per['max_period']}",
                                f"{per['avg_period']:.1f}",
                                f"{per['median_period']:.1f}"
                            ])
                        else:
                            row.extend(["0", "-", "-", "-", "-"])
                    
                    table_data.append(row)
                
                headers = [
                    "Стратегия",
                    "Вариаций",
                    "Ставок",
                    "Побед",
                    "Win%",
                    "МаксСерия",
                    "СуммаСтавок",
                    "СуммаВыплат",
                    "Профит",
                    "ROI%",
                    "Баланс"
                ]
                
                if analysis_mode in ["periodicity", "combined"]:
                    headers.extend([
                        "Выпадений",
                        "Мин период (ходов)",
                        "Макс период (ходов)",
                        "Сред период (ходов)",
                        "Медиана период (ходов)"
                    ])
                
                table_str = tabulate(table_data, headers=headers, tablefmt="grid")
                f.write(table_str + "\n")
                print(f"  ✅ {combo} обработана")
        
        # === TOP 5 BY PROFIT ===
        f.write("\n\n" + "="*120 + "\n")
        f.write("ТОП-5 РЕЗУЛЬТАТОВ ПО ПРОФИТУ (ВЫИГРЫШУ)\n")
        f.write("="*120 + "\n\n")
        
        print("🏆 ТОП-5 ПО ПРОФИТУ\n")
        
        top5_profit = results_sorted_profit[:5]
        table_data = []
        for idx, res in enumerate(top5_profit, 1):
            table_data.append([
                f"#{idx}",
                res["combination"],
                res["strategy"],
                res.get("num_variations", "?"),
                f"{res['total_bets']:.0f}",
                f"{res['total_wins']:.0f}",
                f"{res['win_rate']:.1f}%",
                f"{res['longest_streak']:.0f}",
                f"{res['profit']:+.0f}р",
                f"{res['roi']:+.2f}%",
                f"{res['final_balance']:.0f}р",
            ])
        
        headers = ["Место", "Комбо", "Стратегия", "Вариаций", "Ставок", "Побед", "Win%", "МаксСерия", "Профит", "ROI%", "Баланс"]
        table_str = tabulate(table_data, headers=headers, tablefmt="grid")
        f.write(table_str + "\n")
        print("\n" + table_str)
        
        # === TOP 5 BY ROI ===
        f.write("\n\n" + "="*120 + "\n")
        f.write("ТОП-5 РЕЗУЛЬТАТОВ ПО ROI (ПРОЦЕНТ ВОЗВРАТА)\n")
        f.write("="*120 + "\n\n")
        
        print("\n📈 ТОП-5 ПО ROI\n")
        
        top5_roi = results_sorted_roi[:5]
        table_data = []
        for idx, res in enumerate(top5_roi, 1):
            table_data.append([
                f"#{idx}",
                res["combination"],
                res["strategy"],
                res.get("num_variations", "?"),
                f"{res['total_bets']:.0f}",
                f"{res['total_wins']:.0f}",
                f"{res['win_rate']:.1f}%",
                f"{res['longest_streak']:.0f}",
                f"{res['profit']:+.0f}р",
                f"{res['roi']:+.2f}%",
                f"{res['final_balance']:.0f}р",
            ])
        
        table_str = tabulate(table_data, headers=headers, tablefmt="grid")
        f.write(table_str + "\n")
        print("\n" + table_str)
        
        # === PERIODICITY STATISTICS BY COMBINATION ===
        f.write("\n\n" + "="*120 + "\n")
        f.write("СТАТИСТИКА ВЫПАДЕНИЙ ПО КОМБИНАЦИЯМ\n")
        f.write("="*120 + "\n\n")
        
        print("\n📊 СТАТИСТИКА ВЫПАДЕНИЙ ПО КОМБИНАЦИЯМ\n")
        
        # Группируем периодичность по комбинациям
        periodicity_by_combo = {}
        for res in results:
            combo = res["combination"]
            per = res["periodicity"]
            
            if combo not in periodicity_by_combo:
                periodicity_by_combo[combo] = {
                    "occurrences_list": [],
                    "min_periods": [],
                    "max_periods": [],
                    "avg_periods": [],
                    "median_periods": [],
                }
            
            if per["min_period"] is not None:
                periodicity_by_combo[combo]["occurrences_list"].append(per["occurrences"])
                periodicity_by_combo[combo]["min_periods"].append(per["min_period"])
                periodicity_by_combo[combo]["max_periods"].append(per["max_period"])
                periodicity_by_combo[combo]["avg_periods"].append(per["avg_period"])
                periodicity_by_combo[combo]["median_periods"].append(per["median_period"])
        
        # Выводим таблицу с статистикой
        periodicity_table_data = []
        for combo in sorted(periodicity_by_combo.keys()):
            data = periodicity_by_combo[combo]
            
            if data["min_periods"]:  # Если есть данные
                periodicity_table_data.append([
                    combo,
                    f"{sum(data['occurrences_list']):.0f}",
                    f"{min(data['min_periods']):.0f}",
                    f"{max(data['min_periods']):.0f}",
                    f"{statistics.mean(data['min_periods']):.1f}",
                    f"{statistics.median(data['min_periods']):.1f}",
                    f"{min(data['max_periods']):.0f}",
                    f"{max(data['max_periods']):.0f}",
                    f"{statistics.mean(data['max_periods']):.1f}",
                    f"{statistics.median(data['max_periods']):.1f}",
                    f"{statistics.mean(data['avg_periods']):.1f}",
                    f"{statistics.median(data['median_periods']):.1f}",
                ])
            else:
                periodicity_table_data.append([
                    combo,
                    "0", "-", "-", "-", "-", "-", "-", "-", "-", "-", "-"
                ])
        
        if periodicity_table_data:
            periodicity_headers = [
                "Комбинация",
                "Всего выпадений",
                "Мин период (ходов)",
                "Мин период (макс)",
                "Мин период (среднее)",
                "Мин период (медиана)",
                "Макс период (ходов)",
                "Макс период (макс)",
                "Макс период (среднее)",
                "Макс период (медиана)",
                "Среднее период (ходов)",
                "Медиана период (ходов)",
            ]
            
            periodicity_table_str = tabulate(periodicity_table_data, headers=periodicity_headers, tablefmt="grid")
            f.write(periodicity_table_str + "\n")
            print(periodicity_table_str)
        
        # === SUMMARY STATISTICS ===
        f.write("\n\n" + "="*120 + "\n")
        f.write("СВОДНАЯ СТАТИСТИКА\n")
        f.write("="*120 + "\n\n")
        
        print("\n📊 СВОДНАЯ СТАТИСТИКА\n")
        
        profitable = sum(1 for r in results if r["profit"] > 0)
        breakeven = sum(1 for r in results if r["profit"] == 0)
        loss = sum(1 for r in results if r["profit"] < 0)
        
        avg_profit = sum(r["profit"] for r in results) / len(results)
        avg_roi = sum(r["roi"] for r in results) / len(results)
        max_profit = max(r["profit"] for r in results)
        min_profit = min(r["profit"] for r in results)
        
        stats = [
            ["Total analyses", f"{len(results)}"],
            ["Profitable", f"{profitable} ({profitable/len(results)*100:.1f}%)"],
            ["Breakeven", f"{breakeven}"],
            ["Loss-making", f"{loss} ({loss/len(results)*100:.1f}%)"],
            ["", ""],
            ["Average profit", f"{avg_profit:.0f}"],
            ["Average ROI", f"{avg_roi:.2f}%"],
            ["Max profit", f"{max_profit:.0f}"],
            ["Max loss", f"{min_profit:.0f}"],
        ]
        
        table_str = tabulate(stats, tablefmt="simple")
        f.write(table_str + "\n\n")
        print(table_str)
        
        f.write("\n" + "="*120 + "\n")
    
    print(f"\n✅ Результаты сохранены в: {output_file}")
    print("="*100 + "\n")
    print(f"📂 Откройте файл: {output_file.resolve()}")


if __name__ == "__main__":
    main()
