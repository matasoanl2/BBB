"""Импортировать JSON game data в PostgreSQL и экспортировать обратно по частям."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from datetime import datetime
from psycopg2.extras import Json

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from scripts.common.offline_support import connect_postgres, load_database_settings

try:
    from tqdm import tqdm
except ImportError:
    raise RuntimeError("Для import/export требуется установленная библиотека tqdm.")

DB_SETTINGS = load_database_settings()

MAX_FILE_SIZE = 100 * 1024 * 1024  # 100 МБ в байтах


def get_db_connection():
    """Вернуть подключение к PostgreSQL для операций импорта и экспорта."""

    return connect_postgres(DB_SETTINGS)


def init_db():
    """Убедиться, что минимальная game-results schema существует перед импортом."""

    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS game_results (
            id SERIAL PRIMARY KEY,
            timestamp TIMESTAMP WITH TIME ZONE,
            player_name TEXT,
            dice_results JSONB,
            created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
        )
    """)
    cursor.execute("""
        CREATE INDEX IF NOT EXISTS idx_timestamp ON game_results(timestamp)
    """)
    cursor.execute("""
        CREATE INDEX IF NOT EXISTS idx_player ON game_results(player_name)
    """)
    conn.commit()
    cursor.close()
    conn.close()


def import_from_json(json_file: str, skip_duplicates_check: bool = True):
    """Импортировать game results из JSON-файла в PostgreSQL."""
    json_path = Path(json_file)
    
    if not json_path.exists():
        print(f"❌ Файл не найден: {json_file}")
        return False
    
    try:
        print(f"📖 Чтение JSON файла: {json_file}")
        if not skip_duplicates_check:
            print("⚠️  Проверка дубликатов ОТКЛЮЧЕНА")
        
        with open(json_path, "r", encoding="utf-8") as f:
            data = json.load(f)
        
        if not isinstance(data, list):
            print("❌ JSON должен содержать массив объектов")
            return False
        
        init_db()
        
        conn = get_db_connection()
        cursor = conn.cursor()
        
        # Проверка на дубликаты: получить max timestamp (если включена проверка)
        max_timestamp = None
        if skip_duplicates_check:
            cursor.execute("SELECT MAX(timestamp) FROM game_results")
            max_timestamp = cursor.fetchone()[0]
        
        imported_count = 0
        skipped_count = 0
        
        # Прогресс-бар для импорта
        with tqdm(total=len(data), desc="📥 Импорт записей", unit="запись") as pbar:
            for item in data:
                if not isinstance(item, dict):
                    skipped_count += 1
                    pbar.update(1)
                    continue
                
                timestamp_str = item.get("timestamp")
                results = item.get("results")
                
                if not timestamp_str or not results:
                    skipped_count += 1
                    pbar.update(1)
                    continue
                
                # Пропустить, если уже есть в БД (если проверка включена)
                try:
                    timestamp = datetime.fromisoformat(timestamp_str.replace("Z", "+00:00"))
                except (ValueError, AttributeError):
                    skipped_count += 1
                    pbar.update(1)
                    continue
                
                if skip_duplicates_check and max_timestamp and timestamp <= max_timestamp:
                    skipped_count += 1
                    pbar.update(1)
                    continue
                
                try:
                    player_name = results.get("player", {}).get("name", "unknown")
                    cursor.execute("""
                        INSERT INTO game_results (timestamp, player_name, dice_results)
                        VALUES (%s, %s, %s)
                    """, (timestamp, player_name, Json(results)))
                    imported_count += 1
                except Exception as e:
                    print(f"\n⚠️  Ошибка импорта записи: {e}")
                    skipped_count += 1
                
                pbar.update(1)
        
        conn.commit()
        cursor.close()
        conn.close()
        
        print(f"✅ Импорт завершён!")
        print(f"   Импортировано: {imported_count}")
        print(f"   Пропущено (дубликаты/ошибки): {skipped_count}")
        return True
        
    except json.JSONDecodeError as e:
        print(f"❌ Ошибка чтения JSON: {e}")
        return False
    except Exception as e:
        print(f"❌ Ошибка импорта: {e}")
        return False


def export_to_json_chunked(output_dir: str = "."):
    """Экспортировать game results из PostgreSQL в chunked JSON-файлы до 100 МБ."""

    output_path = Path(output_dir)
    output_path.mkdir(parents=True, exist_ok=True)
    
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        
        # Получить общее количество записей
        cursor.execute("SELECT COUNT(*) FROM game_results")
        total_count = cursor.fetchone()[0]
        
        if total_count == 0:
            print("❌ В БД нет данных для экспорта")
            conn.close()
            return False
        
        print(f"📊 Экспорт {total_count} записей из БД")
        
        # Экспортировать по частям с прогресс-баром
        chunk_size = 1000  # Начальный размер чанка
        offset = 0
        file_num = 1
        current_chunk = []
        current_size = 0
        
        with tqdm(total=total_count, desc="📤 Экспорт записей", unit="запись") as pbar:
            while offset <= total_count:
                cursor.execute("""
                    SELECT timestamp, player_name, dice_results 
                    FROM game_results 
                    ORDER BY timestamp ASC
                    LIMIT %s OFFSET %s
                """, (chunk_size, offset))
                
                rows = cursor.fetchall()
                if not rows:
                    break
                
                for row in rows:
                    timestamp, player_name, dice_results = row
                    item = {
                        "timestamp": timestamp.isoformat() if isinstance(timestamp, datetime) else str(timestamp),
                        "results": {
                            **dice_results,
                            "player": {"name": player_name}
                        }
                    }
                    
                    item_json = json.dumps(item, ensure_ascii=False)
                    item_size = len(item_json.encode("utf-8"))
                    
                    # Если добавление этого элемента превысит лимит, сохранить текущий файл
                    if current_size + item_size > MAX_FILE_SIZE and current_chunk:
                        output_file = output_path / f"game_data_part_{file_num:03d}.json"
                        with open(output_file, "w", encoding="utf-8") as f:
                            json.dump(current_chunk, f, ensure_ascii=False, indent=2)
                        pbar.write(f"   Сохранён файл {file_num}: {output_file.name} ({current_size / (1024*1024):.1f} МБ)")
                        
                        current_chunk = []
                        current_size = 0
                        file_num += 1
                    
                    current_chunk.append(item)
                    current_size += item_size
                    pbar.update(1)
                
                offset += chunk_size
        
        # Сохранить последний файл
        if current_chunk:
            output_file = output_path / f"game_data_part_{file_num:03d}.json"
            with open(output_file, "w", encoding="utf-8") as f:
                json.dump(current_chunk, f, ensure_ascii=False, indent=2)
            print(f"   Сохранён файл {file_num}: {output_file.name} ({current_size / (1024*1024):.1f} МБ)")
        
        cursor.close()
        conn.close()
        
        print(f"✅ Экспорт завершён! Файлы сохранены в: {output_path}")
        return True
        
    except Exception as e:
        print(f"❌ Ошибка экспорта: {e}")
        return False


def main(argv: list[str] | None = None):
    """CLI-точка входа для сценария импорта и экспорта JSON."""

    parser = argparse.ArgumentParser(description="Импорт и экспорт game_results между JSON и PostgreSQL")
    subparsers = parser.add_subparsers(dest="command", required=True)

    import_parser = subparsers.add_parser("import", help="Импортировать JSON в PostgreSQL")
    import_parser.add_argument("json_file", help="Путь к JSON-файлу")
    import_parser.add_argument(
        "--skip-duplicates",
        action="store_true",
        help="Не делать coarse timestamp-проверку дубликатов, пытаться импортировать все записи",
    )

    export_parser = subparsers.add_parser("export", help="Экспортировать PostgreSQL в chunked JSON")
    export_parser.add_argument("output_dir", nargs="?", default=".", help="Директория для файлов экспорта")

    args = parser.parse_args(argv)

    if args.command == "import":
        import_from_json(args.json_file, skip_duplicates_check=not args.skip_duplicates)
        return

    if args.command == "export":
        export_to_json_chunked(args.output_dir)
        return


if __name__ == "__main__":
    main()
