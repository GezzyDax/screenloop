# Screenloop

[English](README.md) | **Русский**

Screenloop — лёгкая self-hosted панель управления цикличным воспроизведением видео-плейлистов на телевизорах и информационных экранах в локальной сети.

Это современная open-source замена устаревшему сценарию с Home Media Server: один раз загрузил видео — Screenloop сам подготовит совместимые с ТВ копии, назначит плейлисты телевизорам Samsung/LG/DLNA и покажет состояние воспроизведения в защищённой веб-панели. А с нодовым режимом одна панель управляет телевизорами и в удалённых сетях — филиалы, другие этажи, другие площадки — без проброса портов на удалённой стороне.

## Зачем

Во многих офисах, клиниках, магазинах и домашних лабораториях видео на ТВ до сих пор крутят через самодельные медиасерверы, флешки или старые DLNA-утилиты. Это ручная конвертация файлов, непонятный статус телевизоров, отсутствие плейлистов и контроля доступа.

Screenloop решает это, объединяя:

- Воспроизведение на ТВ по DLNA/UPnP внутри локальной сети.
- Плейлисты и профили на каждый ТВ: Samsung, LG и generic DLNA.
- Автоматическую подготовку MP4/H.264/AAC для совместимости с ТВ.
- Веб-панель с пользователями, ролями, CSRF-защитой, журналом аудита и подписанными stream-URL.
- Ноды для удалённых площадок с исходящим подключением к центральному контроллеру.
- Деплой через Docker/GHCR (amd64 и arm64) для небольших LAN и корпоративных сред.

## Что уже работает

- Загрузка видео с прогрессом и проверкой дубликатов; транскодирование в ТВ-совместимые MP4 под каждый профиль.
- Упорядоченные плейлисты (сортировка drag-and-drop) с автоматическим зацикливанием.
- Несколько телевизоров с разными профилями и плейлистами; сканирование сети на DLNA MediaRenderer.
- Мониторинг доступности ТВ, готовности DLNA/SOAP, текущего и следующего видео, прогресса воспроизведения.
- Управление воспроизведением: следующий ролик, стоп, плейлист сначала, без звука, повторный поиск.
- Удалённые площадки через ноды: только исходящее подключение, локальный кэш медиа, автономная работа при потере связи ([docs/nodes.md](docs/nodes.md)).
- Локальные пользователи с ролями (`viewer` < `operator` < `admin`), самостоятельная смена пароля, управление сессиями, журнал security-аудита.
- Локализованный интерфейс (русский/английский), светлая и тёмная темы.
- API `/api/v1` для Vue-панели и интеграций.

## Быстрый старт

### Установка последней стабильной версии

```bash
sh -c 'curl -fsSL https://raw.githubusercontent.com/GezzyDax/screenloop/main/install.sh -o /tmp/screenloop-install.sh && bash /tmp/screenloop-install.sh'
```

Открой:

```text
http://<ip-сервера>:8098
```

Установщик спросит порт backend, порт веб-панели, логин/пароль первого администратора и сетевые интерфейсы для телевизоров.
Если Docker или плагин Docker Compose не установлены — предложит установить, спросив разрешение.

### Установка dev-сборки

Для тестирования ещё не выпущенных изменений:

```bash
sh -c 'curl -fsSL https://raw.githubusercontent.com/GezzyDax/screenloop/dev/install.sh -o /tmp/screenloop-install.sh && bash /tmp/screenloop-install.sh --dev'
```

Если установка идёт в `/opt/screenloop` без root, установщик перезапустит себя через `sudo` и спросит пароль. Если это заблокировано, запусти с явным sudo:

```bash
sh -c 'curl -fsSL https://raw.githubusercontent.com/GezzyDax/screenloop/dev/install.sh -o /tmp/screenloop-install.sh && sudo bash /tmp/screenloop-install.sh --dev'
```

### Установка удалённой ноды

На хосте в удалённой сети, предварительно создав токен подключения в панели (**Ноды → Создать ноду**):

```bash
sh -c 'curl -fsSL https://raw.githubusercontent.com/GezzyDax/screenloop/main/install.sh -o /tmp/screenloop-install.sh && bash /tmp/screenloop-install.sh --node http://<ip-контроллера>:8099'
```

Архитектура и подробности — в [docs/nodes.md](docs/nodes.md).

## Docker Compose

### Запуск из исходников

```bash
git clone https://github.com/GezzyDax/screenloop.git
cd screenloop
cp .env.example .env
# задай SCREENLOOP_BOOTSTRAP_PASSWORD и SCREENLOOP_SECRET_KEY (openssl rand -hex 32)
docker compose up --build -d
```

### Запуск стабильного образа с GHCR

```bash
mkdir -p screenloop && cd screenloop
curl -fsSL https://raw.githubusercontent.com/GezzyDax/screenloop/main/docker-compose.ghcr.yml -o docker-compose.yml
curl -fsSL https://raw.githubusercontent.com/GezzyDax/screenloop/main/.env.example -o .env
# отредактируй .env
docker compose up -d
```

### Запуск dev-образа с GHCR

```bash
mkdir -p screenloop && cd screenloop
curl -fsSL https://raw.githubusercontent.com/GezzyDax/screenloop/dev/docker-compose.ghcr.yml -o docker-compose.yml
curl -fsSL https://raw.githubusercontent.com/GezzyDax/screenloop/dev/.env.example -o .env
printf "\nSCREENLOOP_IMAGE='ghcr.io/gezzydax/screenloop:dev'\n" >> .env
# отредактируй .env
docker compose up -d
```

`network_mode: host` — намеренно: SSDP-обнаружение и доступ телевизоров к stream-URL в host-сети работают значительно надёжнее.
Docker Compose поднимает два контейнера: `screenloop` (backend/API/DLNA) и `screenloop-ui` (Vue-панель). Третий образ, `screenloop-node`, — лёгкий агент для удалённых площадок. Образы публикуются под amd64 и arm64.

## Обновления

### Обновление стабильной установки

```bash
cd /opt/screenloop
./update.sh
```

Или скачать свежий апдейтер:

```bash
cd /opt/screenloop
sh -c 'curl -fsSL https://raw.githubusercontent.com/GezzyDax/screenloop/main/update.sh -o /tmp/screenloop-update.sh && bash /tmp/screenloop-update.sh'
```

### Обновление на dev-сборку

```bash
cd /opt/screenloop
./update.sh -dev
```

### Возврат на стабильную

```bash
cd /opt/screenloop
./update.sh --main
```

### Откат на выпущенную версию

```bash
cd /opt/screenloop
./update.sh --rollback 1.5.0
```

Обе картинки пинуются на указанный релиз и сервис перезапускается; том с данными не затрагивается.

## Результат за 5 минут

1. Установи Screenloop и открой веб-панель.
2. Загрузи короткое видео `.mp4`, `.mkv` или `.avi` на странице «Видео».
3. Дождись, пока статус транскодирования станет «готово».
4. Создай плейлист и добавь видео.
5. Добавь или найди сканированием ТВ, назначь плейлист и нажми «Следующее».

Телевизор запросит подписанный URL `/stream/...` у Screenloop и начнёт воспроизведение.

## Конфигурация

Основные переменные окружения:

- `SCREENLOOP_BOOTSTRAP_USER` / `SCREENLOOP_BOOTSTRAP_PASSWORD` — первый администратор, создаётся при пустой таблице пользователей. После первого входа удали пароль из `.env`.
- `SCREENLOOP_SECRET_KEY` — обязателен для CSRF и подписи stream-URL. Генерация: `openssl rand -hex 32`; плейсхолдеры отклоняются при старте.
- `SCREENLOOP_HTTP_PORT` — порт backend API и медиа-стрима, по умолчанию `8099`.
- `SCREENLOOP_UI_PORT` — порт Vue-панели, по умолчанию `8098`.
- `SCREENLOOP_ADVERTISE_HOSTS` — IP сервера, которые сообщаются телевизорам (для хостов в нескольких подсетях), через запятую.
- `SCREENLOOP_ALLOWED_TV_CIDRS` — необязательный allowlist сетей ТВ, например `192.0.2.0/24,198.51.100.0/24`.
- `SCREENLOOP_TRUSTED_PROXY_CIDRS` — адреса reverse-proxy, которым разрешено передавать `X-Forwarded-For`.
- `SCREENLOOP_COOKIE_SECURE` — `true`, если панель отдаётся через HTTPS.
- `SCREENLOOP_SESSION_MAX_LIFETIME_SECONDS` — абсолютный потолок жизни сессии при скользящем продлении, по умолчанию 30 дней.
- `SCREENLOOP_MAX_UPLOAD_BYTES` — лимит загрузки, по умолчанию 2 GiB; проверяется по ходу приёма файла и в UI-прокси.
- `SCREENLOOP_MIN_FREE_DISK_BYTES` — отказ в загрузке, если свободного места меньше порога, по умолчанию 1 GiB.
- `SCREENLOOP_STREAM_TOKEN_TTL_SECONDS` — время жизни подписанных stream-URL, по умолчанию 6 часов. Токены привязаны к адресу ТВ.
- `SCREENLOOP_TRANSCODE_TIMEOUT_SECONDS` — жёсткий таймаут ffmpeg на задачу, по умолчанию 2 часа.
- `SCREENLOOP_FFPROBE_TIMEOUT_SECONDS` — таймаут ffprobe при загрузке и определении длительности, по умолчанию 30.
- `SCREENLOOP_ACCESS_LOG` — `false`, чтобы уменьшить шум HTTP-логов.
- `SCREENLOOP_LOG_LEVEL` — уровень логирования приложения, по умолчанию `INFO`.
- `SCREENLOOP_API_DOCS` — `false`, чтобы отключить `/docs`, `/redoc` и `/openapi.json` в продакшене.
- `SCREENLOOP_UPDATE_CHECK` — опциональная проверка релизов на GitHub, по умолчанию `false`.
- `SCREENLOOP_POLL_LOOP_INTERVAL` — интервал цикла воркера в секундах, по умолчанию `1`.
- `SCREENLOOP_PING_POLL` — интервал быстрой проверки доступности хоста, по умолчанию `2`.
- `SCREENLOOP_OFFLINE_POLL` — интервал повторного DLNA-поиска для доступных, но не готовых ТВ, по умолчанию `3`.
- `SCREENLOOP_ONLINE_POLL` — интервал полного DLNA/SOAP-опроса онлайн-ТВ, по умолчанию `5`.
- `SCREENLOOP_SSDP_TIMEOUT` — таймаут SSDP-поиска на цель в секундах, по умолчанию `2`.
- `SCREENLOOP_SOAP_TIMEOUT` — таймаут UPnP/DLNA-команд, по умолчанию `20` секунд.
- `SCREENLOOP_SOAP_NEXT_TIMEOUT` — короткий таймаут для предзагрузки следующего ролика, по умолчанию `3` секунды.
- `SCREENLOOP_PRELOAD_NEXT_URI` — best-effort предзагрузка `SetNextAVTransportURI` для ТВ, которые её поддерживают, по умолчанию `true`.
- `SCREENLOOP_AUTO_ADVANCE_END_GRACE` — сколько секунд после известной длительности подождать, прежде чем пушить следующий ролик, если ТВ продолжает отвечать `PLAYING`, по умолчанию `5`.

Переменные агента ноды (`SCREENLOOP_NODE_*`) описаны в [docs/nodes.md](docs/nodes.md).

Устаревшие переменные `GEZZDLNA_*` пока работают как fallback. Новые установки должны использовать `SCREENLOOP_*`.

## Безопасность

Screenloop рассчитан на доверенную локальную сеть. Не выставляй его напрямую в публичный интернет.

Текущий базис:

- Отказ старта с плейсхолдерными или публично известными секретами.
- Локальные пользователи с ролями `viewer` < `operator` < `admin`; последнего активного администратора нельзя понизить или отключить.
- HttpOnly cookie-сессии со скользящим продлением и абсолютным потолком; каждый пользователь видит и отзывает свои сессии.
- CSRF-защита всех небезопасных действий.
- Rate-limit логина по IP и по имени пользователя; лимиты на загрузки, stream-токены и команды ТВ.
- Подписанные stream-URL, привязанные к адресу ТВ, с настраиваемым временем жизни.
- Security-аудит хранится отдельно от общего потока событий и скрыт от роли viewer.
- Опциональный allowlist сетей ТВ; control-URL телевизоров валидируются по нему.
- Доступ нод — одноразовые enrollment-токены и хэшированные постоянные токены; отзыв срабатывает мгновенно.

Для удалённого доступа ставь Screenloop за reverse-proxy с TLS, сильной аутентификацией и сетевыми ограничениями.

Гайды для продакшена:

- [docs/deployment.md](docs/deployment.md) — архитектура, порты, reverse-proxy с TLS, обновление и откат.
- [docs/hardening.md](docs/hardening.md) — чеклист усиления безопасности (firewall backend-порта, секреты, роли).
- [docs/backup.md](docs/backup.md) — резервное копирование и восстановление тома данных.
- [docs/nodes.md](docs/nodes.md) — ноды удалённых площадок: архитектура, установка, модель безопасности.

## API

Screenloop предоставляет JSON API `/api/v1` для Vue-панели и интеграций.

- `POST /api/v1/auth/login` возвращает текущего пользователя и `csrf_token`.
- `GET /api/v1/session` возвращает пользователя, роли и свежий `csrf_token`.
- Небезопасные методы требуют заголовок `X-CSRF-Token`.
- `GET /api/v1/status` — live-состояние дашборда; `GET /api/v1/stream/events` — то же по SSE.
- `GET /api/v1/version` — версия сборки, ревизия и состояние обновлений.
- `GET /api/v1/diagnostics` — диагностика без секретов, только для админов.

Модель безопасности API, группы эндпоинтов и правила фронтенда — в [docs/API.md](docs/API.md).

Интерактивная документация: `/docs`, `/redoc`, `/openapi.json` (в продакшене отключается через `SCREENLOOP_API_DOCS=false`).

## Данные

Docker хранит данные в томе `screenloop-data`:

- `/data/db/screenloop.sqlite3` — состояние SQLite.
- `/data/media` — загруженные оригиналы.
- `/data/transcoded` — ТВ-совместимые MP4-копии.

Резервное копирование и восстановление: [docs/backup.md](docs/backup.md).

## Разработка

```bash
python3 -m venv .venv
. .venv/bin/activate
pip install -r requirements.txt
export SCREENLOOP_SECRET_KEY="$(openssl rand -hex 32)"
export SCREENLOOP_BOOTSTRAP_PASSWORD="dev-$(openssl rand -hex 4)"
echo "bootstrap admin password: $SCREENLOOP_BOOTSTRAP_PASSWORD"
python -m screenloop
```

Проверки (те же гоняет CI):

```bash
python3 -m ruff check screenloop tests
python3 -m mypy screenloop
python3 -m unittest discover -s tests
docker compose build
```

Dev-сервер фронтенда (проксирует `/api` и `/stream` на `127.0.0.1:8099`):

```bash
cd frontend
npm install
npm run dev
```

## Процесс релизов

Разработка идёт через ветку `dev`. Изменения сначала проверяются там; для интеграционных проверок используется `ghcr.io/gezzydax/screenloop:dev`.

`main` защищена и публикует тег образа `main`. Версионные GitHub-релизы публикуют semver-теги GHCR: `1.5.0`, `1.5`, `latest`. Образы публикуются только после прохождения линта, проверки типов и тестов.

Release Please собирает релизы из Conventional Commits, попавших в `main`:

- `fix:` — patch-релиз.
- `feat:` — minor-релиз.
- `feat!:` или `BREAKING CHANGE:` — major-релиз.

## Роадмап

Сделано:

- Панель управления для одной LAN: пользователи, плейлисты, профили ТВ, API, установщик, обновления, GHCR-образы.
- Страница диагностики: хранилище, воркеры, сеть, ffmpeg/docker, безопасная конфигурация.
- Стабильный контракт `/api/v1`; Vue/Vite как единственная веб-панель, тёмная тема, локализация RU/EN.
- Нодовый режим: центральный контроллер + лёгкие ноды с исходящим подключением, локальным кэшем медиа и автономной работой.
- CI с линтом и типами, сканированием зависимостей и образов, multi-arch сборками и гейтом публикации.

Планируется:

- Headless/CLI-редакция для автоматизации: `screenloopctl upload`, `screenloopctl playlist assign` и т.п.
- Тонкая настройка профилей под конкретные модели ТВ: битрейт, разрешение, звук, DLNA-заголовки, стратегии повтора.
- Плейлисты по расписанию (dayparting) и расписания на каждый ТВ.
- Скриншоты и демо-GIF в README.

## Сообщество

Issues и pull request'ы приветствуются. Особенно полезны:

- Отчёты о совместимости с реальными телевизорами.
- Тюнинг профилей для моделей Samsung/LG.
- Примеры Docker, reverse-proxy и деплоя.
- Документация, скриншоты и GIF-демо.
- Ревью безопасности и тесты контракта API.

## Устаревший CLI

Отдельная утилита `dlna_push.py` удалена. Поддерживаемые интерфейсы — веб-демон и `/api/v1`; последняя версия CLI доступна в истории git релизов до 1.5.x.
