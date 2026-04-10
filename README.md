# BuyBayBye — Анализатор стратегии беттинга на Betboom

Проект для автоматизации сбора данных о результатах игры в кости на betboom.ru и анализа беттинговой стратегии с использованием прогрессии ставок. Данные хранятся в **PostgreSQL** с возможностью импорта/экспорта в JSON.

## 📋 Описание

Проект состоит из трёх основных компонентов:

1. **main.py** — автоматизация браузера для сбора реальных данных в PostgreSQL
2. **analys.py** — симуляция беттинговой стратегии на основе данных из БД
3. **import_export.py** — импорт из JSON и экспорт в JSON файлы (по 100МБ)

## 🗄️ Упор на PostgreSQL

Данные теперь хранятся в **PostgreSQL** вместо JSON:
- ✅ Быстрые поиски и индексы
- ✅ Структурированные данные (JSONB)
- ✅ Надежность и ACID гарантии (идеально для финансвых данных)
- ✅ Автоматическое создание схемы

## 🔧 Компоненты проекта

### main.py — Сборщик данных в PostgreSQL

Использует **Patchright** для автоматизации браузера:

- Подключается к WebSocket серверу betboom.ru: `wss://ws.betboom.ru:444/api/nards_studio_ws/v1`
- Перехватывает все WebSocket сообщения
- Фильтрует сообщения со статусом `rng_values` (результаты кубиков)
- **Сохраняет данные в PostgreSQL** с UTC временными метками
- Поддерживает постоянную сессию браузера (профиль в папке `profile/`)
- Headless режим через переменную окружения `HEADLESS`

**Структура таблицы БД:**
```sql
CREATE TABLE game_results (
    id SERIAL PRIMARY KEY,
    timestamp TIMESTAMP WITH TIME ZONE,
    player_name TEXT,
    dice_results JSONB,  -- Результаты кубиков в JSON формате
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);
```

### analys.py — Анализатор стратегии из PostgreSQL

Симулирует беттинговую стратегию на реальных данных из БД:

**Параметры стратегии:**
- **Целевой результат:** красный кубик со значением 3
- **Коэффициент выплаты:** 5.7x
- **Начальный баланс:** 10,000р
- **Последовательность ставок (Martingale-подобная):**
  ```
  [10, 10, 10, 10, 10, 15, 15, 20, 25, 30, 35, 45, 55, 65, 80]
  ```

**Логика симуляции:**
1. На каждый раунд игры делается ставка по текущему шагу
2. Если выпадает красный = 3: ставка * 5.7, баланс пополняется, цикл начинается с шага 1
3. Если не выпадает: баланс уменьшается на размер ставки, переход к следующему шагу
4. После 15-го шага (если не было выигрыша): цикл рестартует

**Выведение:**
- Детальный лог каждой ставки с временем, игроком, результатом и балансом
- Статистика: побед, win rate, макс. losing streak, ROI

### import_export.py — Импорт/Экспорт данных

Двусторонний скрипт для работы с JSON:

**Импорт из JSON в PostgreSQL:**
```bash
python import_export.py import target_ws_messages.json
```
- Читает JSON файл (массив объектов с timestamp и results)
- Автоматически пропускает дубликаты
- Сохраняет в таблицу `game_results`

**Экспорт из PostgreSQL в JSON по частям (до 100МБ):**
```bash
python import_export.py export ./exports
```
- Экспортирует все данные из БД
- Разбивает на файлы: `game_data_part_001.json`, `game_data_part_002.json` и т.д.
- Каждый файл ≤ 100МБ

## 📦 Зависимости

```
patchright
psycopg2-binary
```

## 🐳 Docker (Рекомендуется)

Проект включает полную Docker конфигурацию с PostgreSQL сервером.

**docker-compose.yml:**
- **postgres** сервис: PostgreSQL 15 Alpine
- **app** сервис: Patchright приложение
- БД файлы сохраняются в `./postgres_data/` (вне контейнера)
- Автоматическое создание БД `buybaybye`

### Структура томов:
```
./profile/          → /app/profile (профиль браузера)
./postgres_data/    → /var/lib/postgresql/data (БД вне контейнера)
```

## 🚀 Использование

### Локально (с локальным PostgreSQL)

1. **Убедитесь, что PostgreSQL запущен:**
   ```bash
   # Подключение должно быть доступно на localhost:5432
   # Пользователь: postgres, пароль: postgres (или настройте переменные окружения)
   ```

2. **Установить зависимости:**
   ```bash
   pip install -r requirements.txt
   ```

3. **Запустить сборщик данных:**
   ```bash
   python main.py
   ```
   - Браузер откроется и подключится к betboom.ru
   - Данные будут сохраняться в PostgreSQL
   - Остановить: Ctrl+C

4. **Запустить анализ:**
   ```bash
   python analys.py
   ```

5. **(опционально) Экспортировать в JSON:**
   ```bash
   python import_export.py export ./exports
   ```

### Docker (Рекомендуется)

#### Запуск с Docker Compose

```bash
# Запустить PostgreSQL + приложение
docker-compose up -d

# Просмотр логов
docker-compose logs -f app

# Остановить
docker-compose down
```

#### Запуск отдельных команд в контейнере

```bash
# Запустить анализ
docker-compose exec app python analys.py

# Экспортировать в JSON
docker-compose exec app python import_export.py export ./exports

# Импортировать из JSON (если есть файл в контейнере)
docker-compose exec app python import_export.py import target_ws_messages.json
```

#### Доступ к PostgreSQL с хоста

```bash
# Подключиться напрямую к БД (требуется psql)
psql -h localhost -U postgres -d buybaybye
```

## 🔧 Переменные окружения

Для локального запуска можно переопределить:
```bash
export DB_USER=postgres
export DB_PASSWORD=postgres
export DB_HOST=localhost
export DB_PORT=5432
export DB_NAME=buybaybye
export HEADLESS=false
```

В Docker они уже установлены в `docker-compose.yml`.

## 📊 Интерпретация результатов

- **Win rate:** должен быть примерно 1/6 ≈ 16.67% (вероятность одного значения на кубике)
- **Макс. losing streak:** помогает оценить достаточность BET_SEQUENCE
- **ROI:** показывает прибыльность стратегии на исторических данных
- **min_balance:** критичный параметр — если меньше нуля, стратегия неработоспособна

## ⚠️ Важные замечания

1. **Реальные деньги:** Проект работает с реальным веб-сайтом азартных игр
2. **PostgreSQL обязателен:** Проект теперь зависит от PostgreSQL (локально или в Docker)
3. **БД файлы в проекте:** При использовании Docker `postgres_data/` находится в папке проекта
4. **.gitignore:** Исключает БД файлы, профиль браузера и JSON сообщения

## 📁 Структура проекта

```
BuyBayBye/
├── main.py                      # Сборщик WebSocket данных → PostgreSQL
├── analys.py                    # Анализатор стратегии из PostgreSQL
├── import_export.py             # Импорт/Экспорт JSON ↔ PostgreSQL
├── requirements.txt             # Python зависимости
├── Dockerfile                   # Docker образ приложения
├── docker-compose.yml           # Docker Compose: PostgreSQL + App
├── .gitignore                   # Исключения для git
├── profile/                     # Профиль браузера (gitignored)
├── postgres_data/               # БД файлы (gitignored, вне контейнера)
├── target_ws_messages.json      # (deprecated) Для импорта старых данных
└── README.md                    # Этот файл
```

## 🔄 Миграция со старого формата (JSON)

Если у вас есть старый файл `target_ws_messages.json`, импортируйте его:

```bash
# Локально
python import_export.py import target_ws_messages.json

# В Docker
docker-compose exec app python import_export.py import target_ws_messages.json
```
