"""Запуск Chromium напрямую из Docker-контейнера для авторизации на betboom.ru.

Использование:
    docker compose run --rm -p 9222:9222 app python scripts/profile/docker_auth.py

Затем откройте в Chrome на хосте:
    chrome://inspect/#devices  ->  Configure  ->  localhost:9222
    Нажмите 'inspect' рядом с вкладкой — откроется DevTools с живой страницей.

Браузер работает на виртуальном дисплее Xvfb. Chromium запускается напрямую
(не через Playwright), чтобы CDP-порт работал корректно.

Примечание: Playwright-сборка Chromium игнорирует --remote-debugging-address=0.0.0.0
и слушает только на 127.0.0.1. Поэтому Chrome слушает на 127.0.0.1:INTERNAL_PORT,
а Python TCP-прокси слушает на 0.0.0.0:CDP_PORT и пробрасывает трафик.
"""

from __future__ import annotations

import glob
import os
import signal
import socket
import subprocess
import sys
import threading
import time


PROFILE_DIR = "/app/profile"
TARGET_URL = "https://betboom.ru/game/nardsgame"
CDP_PORT = 9222          # внешний порт (0.0.0.0) — для Docker-проброса
INTERNAL_PORT = 9223     # внутренний порт Chrome (127.0.0.1)

# Путь к Chromium, установленному через patchright
CHROME_PATHS = [
    "/root/.cache/ms-playwright/chromium-*/chrome-linux64/chrome",
    "/root/.cache/patchright/chromium/chrome",
]


def find_chrome() -> str:
    """Найти исполняемый файл Chromium."""
    for pattern in CHROME_PATHS:
        matches = glob.glob(pattern)
        if matches:
            return matches[0]
    try:
        for root, _dirs, files in os.walk("/root/.cache"):
            if "chrome" in files:
                candidate = os.path.join(root, "chrome")
                if os.access(candidate, os.X_OK):
                    return candidate
    except Exception:
        pass
    print("[ERROR] Chromium не найден. Убедитесь что выполнена команда: patchright install chromium", flush=True)
    sys.exit(1)


# ─── TCP-прокси 0.0.0.0:CDP_PORT → 127.0.0.1:INTERNAL_PORT ───

def _pipe(src: socket.socket, dst: socket.socket) -> None:
    """Копировать данные из src в dst до закрытия."""
    try:
        while True:
            data = src.recv(65536)
            if not data:
                break
            dst.sendall(data)
    except OSError:
        pass
    finally:
        try:
            dst.shutdown(socket.SHUT_WR)
        except OSError:
            pass


def _handle_client(client: socket.socket) -> None:
    upstream = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        upstream.connect(("127.0.0.1", INTERNAL_PORT))
    except OSError:
        client.close()
        return
    t1 = threading.Thread(target=_pipe, args=(client, upstream), daemon=True)
    t2 = threading.Thread(target=_pipe, args=(upstream, client), daemon=True)
    t1.start()
    t2.start()
    t1.join()
    t2.join()
    client.close()
    upstream.close()


def start_proxy() -> socket.socket:
    """Запустить TCP-прокси в фоновых потоках. Возвращает серверный сокет."""
    server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    server.bind(("0.0.0.0", CDP_PORT))
    server.listen(8)

    def accept_loop():
        while True:
            try:
                client, _ = server.accept()
                threading.Thread(target=_handle_client, args=(client,), daemon=True).start()
            except OSError:
                break

    threading.Thread(target=accept_loop, daemon=True).start()
    return server


# ─── main ───

def main() -> None:
    chrome_bin = find_chrome()
    print("🚀 Запуск Chromium для авторизации...", flush=True)
    print(f"   Chrome: {chrome_bin}", flush=True)
    print(f"   Профиль: {PROFILE_DIR}", flush=True)
    print(f"   URL: {TARGET_URL}", flush=True)

    # В headed-режиме нужен Xvfb
    xvfb = None
    display = os.environ.get("DISPLAY", "")
    if not display:
        print("   Запуск Xvfb (виртуальный дисплей)...", flush=True)
        xvfb = subprocess.Popen(
            ["Xvfb", ":99", "-screen", "0", "1280x720x24", "-ac"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        os.environ["DISPLAY"] = ":99"
        time.sleep(0.5)

    # Удаляем lock-файлы от предыдущих запусков
    for lock_name in ("SingletonLock", "SingletonSocket", "SingletonCookie"):
        lock_path = os.path.join(PROFILE_DIR, lock_name)
        try:
            os.unlink(lock_path)
            print(f"   Удалён lock: {lock_name}", flush=True)
        except FileNotFoundError:
            pass
        except OSError:
            pass
    # Удаляем временные файлы Chromium
    for tmp in glob.glob(os.path.join(PROFILE_DIR, ".org.chromium.Chromium.*")):
        try:
            os.remove(tmp)
        except OSError:
            pass

    # Chrome слушает на 127.0.0.1:INTERNAL_PORT (Playwright-сборка игнорирует --remote-debugging-address)
    chrome_args = [
        chrome_bin,
        f"--user-data-dir={PROFILE_DIR}",
        f"--remote-debugging-port={INTERNAL_PORT}",
        "--remote-allow-origins=*",
        "--no-sandbox",
        "--disable-dev-shm-usage",
        "--disable-gpu",
        "--no-first-run",
        "--disable-notifications",
        "--password-store=basic",
        "--disable-blink-features=AutomationControlled",
        TARGET_URL,
    ]

    print(f"\n   Запуск Chrome на 127.0.0.1:{INTERNAL_PORT} ...", flush=True)
    chrome_proc = subprocess.Popen(
        chrome_args,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )

    time.sleep(2)
    if chrome_proc.poll() is not None:
        print(f"[ERROR] Chromium завершился с кодом {chrome_proc.returncode}", flush=True)
        if xvfb:
            xvfb.terminate()
        sys.exit(1)

    # Запускаем TCP-прокси: 0.0.0.0:CDP_PORT → 127.0.0.1:INTERNAL_PORT
    proxy_server = start_proxy()
    print(f"   TCP-прокси: 0.0.0.0:{CDP_PORT} → 127.0.0.1:{INTERNAL_PORT}", flush=True)

    print(f"\n✅ Chromium запущен (PID {chrome_proc.pid}).", flush=True)
    print(f"", flush=True)
    print(f"   Для авторизации откройте в Chrome на хосте:", flush=True)
    print(f"   chrome://inspect/#devices", flush=True)
    print(f"   Нажмите 'Configure' и добавьте: localhost:{CDP_PORT}", flush=True)
    print(f"   Затем нажмите 'inspect' рядом с вкладкой betboom.ru", flush=True)
    print(f"", flush=True)
    print(f"   После авторизации нажмите Ctrl+C для сохранения профиля.", flush=True)

    def shutdown(signum, frame):
        print("\n   Завершение...", flush=True)
        proxy_server.close()
        chrome_proc.terminate()
        try:
            chrome_proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            chrome_proc.kill()
        if xvfb:
            xvfb.terminate()
        print("✅ Профиль сохранён. Теперь контейнер может работать в headless-режиме.", flush=True)
        sys.exit(0)

    signal.signal(signal.SIGINT, shutdown)
    signal.signal(signal.SIGTERM, shutdown)

    # Ждём завершения Chromium
    chrome_proc.wait()
    proxy_server.close()
    if xvfb:
        xvfb.terminate()
    print("✅ Профиль сохранён. Теперь контейнер может работать в headless-режиме.", flush=True)


if __name__ == "__main__":
    main()
