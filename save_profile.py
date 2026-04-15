"""Утилита для резервного копирования, восстановления и обслуживания профиля браузера."""

import os
import shutil
import json
import sys
from pathlib import Path
from datetime import datetime
import tarfile
import argparse


PROFILE_DIR = Path(__file__).resolve().parent / "profile"
BACKUPS_DIR = Path(__file__).resolve().parent / "profile_backups"


def get_profile_info() -> dict:
    """Вернуть краткую информацию о текущем профиле браузера."""
    if not PROFILE_DIR.exists():
        return {"status": "no_profile", "message": "Профиль не существует"}
    
    # Получить размер профиля
    total_size = 0
    file_count = 0
    for dirpath, dirnames, filenames in os.walk(PROFILE_DIR):
        for filename in filenames:
            filepath = os.path.join(dirpath, filename)
            total_size += os.path.getsize(filepath)
            file_count += 1
    
    # Получить время последней модификации
    try:
        mtime = os.path.getmtime(PROFILE_DIR)
        mtime_str = datetime.fromtimestamp(mtime).strftime("%Y-%m-%d %H:%M:%S")
    except:
        mtime_str = "unknown"
    
    return {
        "status": "exists",
        "path": str(PROFILE_DIR),
        "size_bytes": total_size,
        "size_mb": round(total_size / (1024 * 1024), 2),
        "files": file_count,
        "last_modified": mtime_str
    }


def save_profile(output_path: str = None) -> bool:
    """Сохранить текущий профиль браузера в сжатый архив."""
    if not PROFILE_DIR.exists():
        print("[ERROR] Профиль браузера не найден:", PROFILE_DIR)
        return False
    
    # Создать директорию для резервных копий
    BACKUPS_DIR.mkdir(parents=True, exist_ok=True)
    
    # Если не указан output_path, использовать timestamp
    if output_path is None:
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        output_path = BACKUPS_DIR / f"profile_backup_{timestamp}.tar.gz"
    else:
        output_path = Path(output_path)
    
    try:
        print(f"[SAVE] Сохранение профиля в: {output_path}")
        
        # Создать архив
        with tarfile.open(output_path, "w:gz") as tar:
            tar.add(PROFILE_DIR, arcname="profile")
        
        # Получить размер архива
        archive_size = os.path.getsize(output_path)
        archive_size_mb = round(archive_size / (1024 * 1024), 2)
        
        print(f"[OK] Профиль успешно сохранён!")
        print(f"  - Файл: {output_path}")
        print(f"  - Размер: {archive_size_mb} МБ")
        print(f"  - Время: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        
        return True
        
    except Exception as e:
        print(f"[ERROR] Ошибка при сохранении профиля: {e}")
        return False


def restore_profile(backup_path: str) -> bool:
    """Восстановить профиль браузера из резервной копии."""
    backup_path = Path(backup_path)
    
    if not backup_path.exists():
        print(f"[ERROR] Файл резервной копии не найден: {backup_path}")
        return False
    
    try:
        print(f"[RESTORE] Восстановление профиля из: {backup_path}")
        
        # Создать backup текущего профиля (если существует)
        if PROFILE_DIR.exists():
            print("[INFO] Текущий профиль сохранён как резервную копию...")
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            backup_current = BACKUPS_DIR / f"profile_backup_before_restore_{timestamp}.tar.gz"
            with tarfile.open(backup_current, "w:gz") as tar:
                tar.add(PROFILE_DIR, arcname="profile")
            print(f"[OK] Резервная копия сохранена: {backup_current}")
            
            # Удалить текущий профиль
            shutil.rmtree(PROFILE_DIR)
        
        # Распаковать новый профиль
        with tarfile.open(backup_path, "r:gz") as tar:
            tar.extractall(PROFILE_DIR.parent)
        
        print(f"[OK] Профиль успешно восстановлен!")
        print(f"  - Из файла: {backup_path}")
        print(f"  - Путь: {PROFILE_DIR}")
        print(f"  - Время: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        
        return True
        
    except Exception as e:
        print(f"[ERROR] Ошибка при восстановлении профиля: {e}")
        return False


def list_backups() -> None:
    """Вывести все доступные архивы резервных копий профиля с базовыми метаданными."""

    if not BACKUPS_DIR.exists():
        print("[INFO] Резервные копии не найдены")
        return
    
    backups = sorted(BACKUPS_DIR.glob("*.tar.gz"), reverse=True)
    
    if not backups:
        print("[INFO] Резервные копии не найдены")
        return
    
    print("\n[BACKUPS] Список доступных резервных копий:\n")
    
    for i, backup in enumerate(backups, 1):
        size_mb = round(os.path.getsize(backup) / (1024 * 1024), 2)
        mtime = os.path.getmtime(backup)
        mtime_str = datetime.fromtimestamp(mtime).strftime("%Y-%m-%d %H:%M:%S")
        
        print(f"{i}. {backup.name}")
        print(f"   Размер: {size_mb} МБ")
        print(f"   Дата: {mtime_str}")
        print()


def clean_old_backups(keep_count: int = 5) -> None:
    """Удалить старые архивы резервных копий, оставив только последние ``keep_count`` файлов."""

    if not BACKUPS_DIR.exists():
        print("[INFO] Резервные копии не найдены")
        return
    
    backups = sorted(BACKUPS_DIR.glob("*.tar.gz"), reverse=True)
    
    if len(backups) <= keep_count:
        print(f"[INFO] Резервных копий {len(backups)}, удалять не нужно")
        return
    
    print(f"[CLEAN] Удаление старых резервных копий (оставить: {keep_count})...\n")
    
    for backup in backups[keep_count:]:
        try:
            size_mb = round(os.path.getsize(backup) / (1024 * 1024), 2)
            os.remove(backup)
            print(f"[REMOVED] {backup.name} ({size_mb} МБ)")
        except Exception as e:
            print(f"[ERROR] Ошибка при удалении {backup.name}: {e}")
    
    print(f"\n[OK] Очистка завершена")


def main():
    """CLI-точка входа для операций резервного копирования и восстановления профиля браузера."""

    parser = argparse.ArgumentParser(
        description="Утилита для сохранения, восстановления и управления профилем браузера Patchright"
    )
    
    subparsers = parser.add_subparsers(dest="command", help="Команда для выполнения")
    
    # Команда info
    subparsers.add_parser("info", help="Показать информацию о текущем профиле")
    
    # Команда save
    save_parser = subparsers.add_parser("save", help="Сохранить профиль в архив")
    save_parser.add_argument("-o", "--output", help="Путь для сохранения архива (опционально)")
    
    # Команда restore
    restore_parser = subparsers.add_parser("restore", help="Восстановить профиль из архива")
    restore_parser.add_argument("backup", help="Путь к архиву резервной копии")
    
    # Команда list
    subparsers.add_parser("list", help="Показать список всех резервных копий")
    
    # Команда clean
    clean_parser = subparsers.add_parser("clean", help="Удалить старые резервные копии")
    clean_parser.add_argument("-k", "--keep", type=int, default=5, 
                             help="Количество последних резервных копий для сохранения (по умолчанию: 5)")
    
    args = parser.parse_args()
    
    if not args.command:
        parser.print_help()
        return
    
    # Выполнить команду
    if args.command == "info":
        info = get_profile_info()
        print("[PROFILE INFO]")
        for key, value in info.items():
            print(f"  {key}: {value}")
    
    elif args.command == "save":
        success = save_profile(args.output)
        sys.exit(0 if success else 1)
    
    elif args.command == "restore":
        success = restore_profile(args.backup)
        sys.exit(0 if success else 1)
    
    elif args.command == "list":
        list_backups()
    
    elif args.command == "clean":
        clean_old_backups(args.keep)


if __name__ == "__main__":
    main()
