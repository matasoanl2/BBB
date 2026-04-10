"""
Скрипт для импорта данных из JSON в PostgreSQL и экспорта в JSON по частям (до 100МБ)
"""
import json
import os
import sys
from pathlib import Path
from datetime import datetime
import psycopg2
from psycopg2.extras import Json

# PostgreSQL config
DB_USER = os.getenv("DB_USER", "postgres")
DB_PASSWORD = os.getenv("DB_PASSWORD", "postgres")
DB_HOST = os.getenv("DB_HOST", "localhost")
DB_PORT = os.getenv("DB_PORT", "5432")
DB_NAME = os.getenv("DB_NAME", "buybaybye")

MAX_FILE_SIZE = 100 * 1024 * 1024  # 100 МБ в байтах


def get_db_connection():
    """Получить подключение к PostgreSQL"""
    conn = psycopg2.connect(
        user=DB_USER,
        password=DB_PASSWORD,
        host=DB_HOST,
        port=DB_PORT,
        database=DB_NAME
    )
    return conn


def init_db():
    """Инициализировать таблицу БД"""
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


def import_from_json(json_file: str):
    """Импортировать данные из JSON файла в PostgreSQL"""
    json_path = Path(json_file)
    
    if not json_path.exists():
        print(f"❌ Файл не найден: {json_file}")
        return False
    
    try:
        print(f"📖 Чтение JSON файла: {json_file}")
        with open(json_path, "r", encoding="utf-8") as f:
            data = json.load(f)
        
        if not isinstance(data, list):
            print("❌ JSON должен содержать массив объектов")
            return False
        
        init_db()
        
        conn = get_db_connection()
        cursor = conn.cursor()
        
        # Проверка на дубликаты: получить max timestamp
        cursor.execute("SELECT MAX(timestamp) FROM game_results")
        max_timestamp = cursor.fetchone()[0]
        
        imported_count = 0
        skipped_count = 0
        
        for item in data:
            if not isinstance(item, dict):
                skipped_count += 1
                continue
            
            timestamp_str = item.get("timestamp")
            results = item.get("results")
            
            if not timestamp_str or not results:
                skipped_count += 1
                continue
            
            # Пропустить, если уже есть в БД
            try:
                timestamp = datetime.fromisoformat(timestamp_str.replace("Z", "+00:00"))
            except (ValueError, AttributeError):
                skipped_count += 1
                continue
            
            if max_timestamp and timestamp <= max_timestamp:
                skipped_count += 1
                continue
            
            try:
                player_name = results.get("player", {}).get("name", "unknown")
                cursor.execute("""
                    INSERT INTO game_results (timestamp, player_name, dice_results)
                    VALUES (%s, %s, %s)
                """, (timestamp, player_name, Json(results)))
                imported_count += 1
            except Exception as e:
                print(f"⚠️  Ошибка импорта записи: {e}")
                skipped_count += 1
        
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
    """Экспортировать данные из PostgreSQL в JSON файлы по 100МБ"""
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
        
        # Экспортировать по частям
        chunk_size = 1000  # Начальный размер чанка
        offset = 0
        file_num = 1
        current_chunk = []
        current_size = 0
        
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
                    print(f"   Сохранён файл {file_num}: {output_file.name} ({current_size / (1024*1024):.1f} МБ)")
                    
                    current_chunk = []
                    current_size = 0
                    file_num += 1
                
                current_chunk.append(item)
                current_size += item_size
            
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


def main():
    if len(sys.argv) < 2:
        print("Использование:")
        print("  python import_export.py import <json_file>     - Импортировать JSON в БД")
        print("  python import_export.py export [output_dir]    - Экспортировать БД в JSON (по 100МБ)")
        print("\nПримеры:")
        print("  python import_export.py import target_ws_messages.json")
        print("  python import_export.py export ./exports")
        sys.exit(1)
    
    command = sys.argv[1].lower()
    
    if command == "import":
        if len(sys.argv) < 3:
            print("❌ Укажите файл JSON для импорта")
            print("  python import_export.py import <json_file>")
            sys.exit(1)
        import_from_json(sys.argv[2])
    
    elif command == "export":
        output_dir = sys.argv[2] if len(sys.argv) > 2 else "."
        export_to_json_chunked(output_dir)
    
    else:
        print(f"❌ Неизвестная команда: {command}")
        sys.exit(1)


if __name__ == "__main__":
    main()
