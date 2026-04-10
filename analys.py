import os
import psycopg2
from datetime import datetime, timezone

# === НАСТРОЙКИ ===
STAKAN = 3           # число 3 — наименьший avg gap (4.79) и max gap (32), частота 17.25%
COEFF = 5.7
START_BALANCE = 10000
DICE_COLOR = "red"

# "Умная" прогрессия: каждая ставка при выигрыше (x5.7) покрывает все предыдущие потери + профит
# bet * (5.7 - 1) >= sum(prev_bets) + min_profit  =>  bet >= (sum_prev + profit) / 4.7
BET_SEQUENCE = [10, 10, 10, 10, 10, 15, 15, 20, 25, 30, 35, 45, 55, 65, 80]

# === DATABASE CONFIG ===
DB_USER = os.getenv("DB_USER", "postgres")
DB_PASSWORD = os.getenv("DB_PASSWORD", "postgres")
DB_HOST = os.getenv("DB_HOST", "localhost")
DB_PORT = os.getenv("DB_PORT", "5432")
DB_NAME = os.getenv("DB_NAME", "buybaybye")


def get_rounds_from_db():
    """Получить раунды из PostgreSQL в формате совместимом с анализатором"""
    try:
        conn = psycopg2.connect(
            user=DB_USER,
            password=DB_PASSWORD,
            host=DB_HOST,
            port=DB_PORT,
            database=DB_NAME
        )
        cursor = conn.cursor()
        cursor.execute("""
            SELECT timestamp, player_name, dice_results 
            FROM game_results 
            ORDER BY timestamp ASC
        """)
        
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
        print(f"Ошибка подключения к БД: {e}")
        print("Убедитесь, что PostgreSQL запущен и доступен.")
        exit(1)


# === ЗАГРУЗКА ДАННЫХ ===
print("Подключение к PostgreSQL...", flush=True)
rounds = get_rounds_from_db()

if not rounds:
    print("ОШИБКА: Нет данных в базе данных. Запустите main.py для сбора данных.")
    exit(1)

print(f"Загружено {len(rounds)} раундов из БД", flush=True)

# === СИМУЛЯЦИЯ ===
balance = START_BALANCE
step = 0
total_bets = 0
total_wins = 0
total_losses = 0
total_bet_amount = 0
total_win_amount = 0
max_balance = START_BALANCE
min_balance = START_BALANCE
cycle_count = 1
longest_losing_streak = 0
current_losing_streak = 0

print(f"{'='*80}")
print(f"АНАЛИЗ ТАКТИКИ")
print(f"Стакан (ставим на): {STAKAN} | Коэффициент: {COEFF} | Старт: {START_BALANCE}р")
print(f"Последовательность ставок: {BET_SEQUENCE}")
print(f"{'='*80}\n")

for i, rnd in enumerate(rounds):
    red_dice = None
    for d in rnd["results"]["dice"]:
        if d["color"] == DICE_COLOR:
            red_dice = d["value"]
            break

    bet = BET_SEQUENCE[step]
    player = rnd["results"]["player"]["name"]
    ts = rnd["timestamp"][11:19]

    balance -= bet
    total_bets += 1
    total_bet_amount += bet

    win = red_dice == STAKAN

    if win:
        payout = bet * COEFF
        balance += payout
        total_wins += 1
        total_win_amount += payout
        current_losing_streak = 0
        status = f"WIN  +{payout:.0f}р"
        step_info = f"шаг {step+1}/{len(BET_SEQUENCE)} -> СБРОС"
        step = 0
        cycle_count += 1
    else:
        total_losses += 1
        current_losing_streak += 1
        longest_losing_streak = max(longest_losing_streak, current_losing_streak)
        status = f"LOSS -{bet}р"
        step += 1
        if step >= len(BET_SEQUENCE):
            step_info = f"шаг 15/15 -> РЕСТАРТ ЦИКЛА"
            step = 0
            cycle_count += 1
        else:
            step_info = f"шаг {step}/{len(BET_SEQUENCE)} -> след. ставка {BET_SEQUENCE[step]}р"

    max_balance = max(max_balance, balance)
    min_balance = min(min_balance, balance)

    print(
        f"#{i+1:3d} | {ts} | {player:20s} | "
        f"красный={red_dice} | ставка={bet:4d}р | {status:16s} | "
        f"баланс={balance:8.0f}р | {step_info}"
    )

# === ИТОГИ ===
profit = balance - START_BALANCE
win_rate = (total_wins / total_bets * 100) if total_bets else 0
roi = (profit / total_bet_amount * 100) if total_bet_amount else 0

print(f"\n{'='*80}")
print(f"ИТОГИ")
print(f"{'='*80}")
print(f"Всего ходов:           {total_bets}")
print(f"Побед:                 {total_wins} ({win_rate:.1f}%)")
print(f"Поражений:             {total_losses}")
print(f"Макс. серия без побед: {longest_losing_streak}")
print(f"Циклов алгоритма:      {cycle_count}")
print(f"{'-'*40}")
print(f"Сумма ставок:          {total_bet_amount}р")
print(f"Сумма выплат:          {total_win_amount:.0f}р")
print(f"{'-'*40}")
print(f"Стартовый баланс:      {START_BALANCE}р")
print(f"Финальный баланс:      {balance:.0f}р")
print(f"Профит:                {profit:+.0f}р")
print(f"ROI:                   {roi:+.1f}%")
print(f"Макс. баланс:          {max_balance:.0f}р")
print(f"Мин. баланс:           {min_balance:.0f}р")
print(f"{'='*80}")
