# Screenloop

**Русский** | [English](README.en.md)

[![CI](https://github.com/GezzyDax/screenloop/actions/workflows/ci.yml/badge.svg)](https://github.com/GezzyDax/screenloop/actions/workflows/ci.yml)
[![Релиз](https://img.shields.io/github/v/release/GezzyDax/screenloop?label=релиз)](https://github.com/GezzyDax/screenloop/releases)
[![GHCR](https://img.shields.io/badge/GHCR-screenloop-2496ED?logo=docker&logoColor=white)](https://github.com/GezzyDax/screenloop/pkgs/container/screenloop)

**Видео на телевизорах в вашей сети — по расписанию плейлиста и без флешек.**

Screenloop загружает ваши ролики, сам готовит из них копии, которые телевизор точно проиграет, и крутит плейлисты на экранах по DLNA. Всё видно и управляется из веб-панели: что сейчас идёт, что следующее, какой экран отвалился.

Работает внутри локальной сети. Одна панель тянет и удалённые площадки — филиалы, другие этажи — через ноды, которым не нужны входящие порты.

---

## Кому это

Офисы, клиники, магазины, производство, домашние лаборатории — везде, где на экранах крутят ролики и это до сих пор делается флешками, самодельным медиасервером или старыми DLNA-утилитами. Ручная конвертация под каждый телевизор, непонятно кто из экранов жив, никакого контроля доступа — Screenloop закрывает ровно это.

## Что умеет

| Задача | Как решается |
|---|---|
| Видео не проигрывается на телевизоре | Автоматическое перекодирование в MP4/H.264/AAC под профиль конкретного ТВ |
| Нужен другой ролик на каждом экране | Свой плейлист и свой профиль на каждый телевизор |
| Непонятно, что происходит на экранах | Живой мониторинг: доступность, готовность DLNA, текущий и следующий ролик, прогресс |
| Ролик завис или нужно переключить | Команды из панели: следующий, стоп, плейлист сначала, без звука, переподключение |
| Телевизоры в другой сети | Ноды: подключаются к панели сами, кэшируют медиа, продолжают играть при обрыве связи |
| Телевизора нет в списке поддерживаемых | Шаблоны: описываете модель в `.toml` — без правки кода и без ожидания релиза |
| Доступ должен быть разграничен | Роли `viewer` < `operator` < `admin`, журнал аудита, подписанные ссылки на видео |
| Экраны работают круглые сутки и выгорают | Часы работы: вне окна Screenloop ничего не отправляет, а выключенный пультом телевизор больше не включается обратно |

Плюс: поиск телевизоров сканированием сети, drag-and-drop в плейлистах, проверка дубликатов при загрузке, тёмная тема, русский и английский интерфейс, JSON API `/api/v1` для интеграций.

---

## Быстрый старт

Установка на сервер в вашей сети — одной командой:

```bash
sh -c 'curl -fsSL https://raw.githubusercontent.com/GezzyDax/screenloop/main/install.sh -o /tmp/screenloop-install.sh && bash /tmp/screenloop-install.sh'
```

Установщик спросит порты, логин и пароль первого администратора и сетевые интерфейсы, по которым телевизоры будут забирать видео. Если Docker или плагин Compose не установлены — предложит поставить.

Дальше откройте `http://<ip-сервера>:8098` и за пять шагов получите картинку на экране:

1. Загрузите короткое видео (`.mp4`, `.mkv`, `.avi`) на странице **Видео**.
2. Дождитесь статуса «готово» — Screenloop перекодирует файл под ваши телевизоры.
3. Создайте плейлист и добавьте в него ролик.
4. На странице **Телевизоры** нажмите поиск или добавьте ТВ вручную по IP.
5. Назначьте плейлист и нажмите **Следующее**.

Телевизор запросит у Screenloop подписанную ссылку `/stream/...` и начнёт воспроизведение.

<details>
<summary><b>Другие способы установки</b></summary>

### Dev-сборка

Для проверки ещё не выпущенных изменений:

```bash
sh -c 'curl -fsSL https://raw.githubusercontent.com/GezzyDax/screenloop/dev/install.sh -o /tmp/screenloop-install.sh && bash /tmp/screenloop-install.sh --dev'
```

Установка в `/opt/screenloop` требует root. Установщик перезапустит себя через `sudo` сам; если это заблокировано — запустите с явным sudo:

```bash
sh -c 'curl -fsSL https://raw.githubusercontent.com/GezzyDax/screenloop/dev/install.sh -o /tmp/screenloop-install.sh && sudo bash /tmp/screenloop-install.sh --dev'
```

### Удалённая нода

Сначала создайте токен подключения в панели (**Ноды → Создать ноду**), затем на хосте в удалённой сети:

```bash
sh -c 'curl -fsSL https://raw.githubusercontent.com/GezzyDax/screenloop/main/install.sh -o /tmp/screenloop-install.sh && bash /tmp/screenloop-install.sh --node http://<ip-контроллера>:8099'
```

Архитектура и модель безопасности — [docs/nodes.md](docs/nodes.md).

### Docker Compose вручную

Стабильный образ с GHCR:

```bash
mkdir -p screenloop && cd screenloop
curl -fsSL https://raw.githubusercontent.com/GezzyDax/screenloop/main/docker-compose.ghcr.yml -o docker-compose.yml
curl -fsSL https://raw.githubusercontent.com/GezzyDax/screenloop/main/.env.example -o .env
# задайте SCREENLOOP_SECRET_KEY и SCREENLOOP_BOOTSTRAP_PASSWORD
docker compose up -d
```

Из исходников:

```bash
git clone https://github.com/GezzyDax/screenloop.git
cd screenloop
cp .env.example .env
# задайте SCREENLOOP_BOOTSTRAP_PASSWORD и SCREENLOOP_SECRET_KEY (openssl rand -hex 32)
docker compose up --build -d
```

Поднимаются два контейнера: `screenloop` (backend, API, DLNA) и `screenloop-ui` (веб-панель). Третий образ, `screenloop-node`, — агент для удалённых площадок. Собираются под amd64 и arm64.

`network_mode: host` стоит намеренно: SSDP-обнаружение и доступ телевизоров к stream-URL в host-сети работают заметно надёжнее.

</details>

## Обновление и откат

```bash
cd /opt/screenloop
./update.sh                  # на последнюю стабильную
./update.sh -dev             # на dev-сборку
./update.sh --main           # вернуться на стабильную
./update.sh --rollback 1.5.0 # откатиться на конкретный релиз
```

Откат пинует оба образа на указанную версию и перезапускает сервис. Том с данными не затрагивается.

---

## Шаблоны телевизоров

DLNA-рендереров сотни, и у каждого свои потолки по битрейту, разрешению и профилю H.264. Проверить их все мейнтейнеры не могут — телевизор есть только у того, кто им пользуется.

Поэтому профиль ТВ — это обычный `.toml`-файл, а не код. Чтобы добавить свою модель, ничего пересобирать не нужно:

- **Своими руками** — положите файл в `<data_dir>/profiles/` или загрузите через **Шаблоны → Добавить шаблон** в панели. Работает сразу, без перезапуска.
- **Из каталога сообщества** — включите `SCREENLOOP_COMMUNITY_CATALOG_CHECK=true`, и в панели появятся шаблоны, присланные другими пользователями. По умолчанию выключено: без флага Screenloop не делает ни одного исходящего запроса.

Формат, полный список полей и как подобрать настройки под свой телевизор — [docs/tv-templates.ru.md](docs/tv-templates.ru.md).

Пять шаблонов идут из коробки: generic DLNA, LG webOS, LG NetCast, Samsung Tizen, Samsung Legacy.

---

## Часы работы

DLNA не умеет выключать телевизор. Более того, стандарт UPnP обязывает рендерер выйти из standby, чтобы обработать `Play` — поэтому телевизор, которому шлют видео, включится сам, сколько его пультом ни выключай.

Отсюда единственный рычаг: не отправлять ничего.

- **Расписание.** В настройках задаются общие дни и часы работы; вне окна Screenloop один раз шлёт `Stop` и больше телевизор не трогает. По умолчанию выключено — обновление не должно само гасить чужие экраны. Группе можно назначить своё окно для всего филиала, этажа или зоны, а отдельному ТВ — переопределить его либо работать всегда. Приоритет: **ТВ → ближайшая группа со своим режимом → родительские группы → общее расписание**. Перенос группы сразу меняет унаследованное расписание всех вложенных экранов, включая ТВ на удалённых нодах.
- **Выключение вручную.** Если телевизор несколько опросов подряд отвечает `NO_MEDIA_PRESENT`, хотя ролик назначен, — значит, его выключили на месте: Samsung и LG в standby сбрасывают AVTransport. Screenloop приостанавливает воспроизведение и не будит экран до начала следующего окна или до кнопки «Возобновить» в панели.

Часовой пояс задаётся через `SCREENLOOP_TIMEZONE` — контейнер по умолчанию живёт в UTC, а расписание читают по настенным часам.

## Настройка

Достаточно этих переменных, остальные имеют разумные значения по умолчанию:

| Переменная | Зачем |
|---|---|
| `SCREENLOOP_SECRET_KEY` | Обязательна. Подпись CSRF и ссылок на видео: `openssl rand -hex 32` |
| `SCREENLOOP_BOOTSTRAP_USER` / `SCREENLOOP_BOOTSTRAP_PASSWORD` | Первый администратор. После входа удалите пароль из `.env` |
| `SCREENLOOP_HTTP_PORT` / `SCREENLOOP_UI_PORT` | Порты backend (`8099`) и панели (`8098`) |
| `SCREENLOOP_ADVERTISE_HOSTS` | IP сервера для телевизоров — если хост в нескольких подсетях |
| `SCREENLOOP_ALLOWED_TV_CIDRS` | Ограничить, в какие сети Screenloop вообще ходит |
| `SCREENLOOP_COOKIE_SECURE` | `true`, если панель за HTTPS |
| `SCREENLOOP_MAX_UPLOAD_BYTES` | Лимит загрузки, по умолчанию 2 GiB |

Полный справочник всех переменных — [docs/configuration.ru.md](docs/configuration.ru.md).

## Безопасность

Screenloop рассчитан на доверенную локальную сеть. **Не выставляйте его напрямую в интернет** — для удалённого доступа ставьте reverse-proxy с TLS и сетевыми ограничениями.

- Приложение не стартует с пустым, коротким или плейсхолдерным секретом.
- Сессии в HttpOnly-cookie, CSRF на всех небезопасных действиях, rate-limit на вход, загрузки и команды.
- Ссылки на видео подписаны и привязаны к адресу телевизора, живут ограниченное время.
- Роли `viewer` < `operator` < `admin`; последнего активного администратора нельзя отключить.
- Отдельный журнал security-аудита, скрытый от роли viewer.
- Ноды подключаются по одноразовым enrollment-токенам, постоянные токены хранятся хэшированными, отзыв мгновенный.

Подробнее: [деплой](docs/deployment.md) · [чеклист хардненинга](docs/hardening.md) · [бэкапы](docs/backup.md) · [ноды](docs/nodes.md)

## Данные

Docker хранит всё в томе `screenloop-data`:

- `/data/db/screenloop.sqlite3` — состояние.
- `/data/media` — загруженные оригиналы.
- `/data/transcoded` — перекодированные копии.
- `/data/profiles` — свои шаблоны телевизоров.

Резервное копирование и восстановление — [docs/backup.md](docs/backup.md).

## API

JSON API `/api/v1` — то же, чем пользуется сама панель. Небезопасные методы требуют заголовок `X-CSRF-Token`.

- `POST /api/v1/auth/login` — вход, возвращает пользователя и `csrf_token`.
- `GET /api/v1/status` — состояние дашборда; `GET /api/v1/stream/events` — то же по SSE.
- `GET /api/v1/profiles` — установленные шаблоны телевизоров.
- `GET /api/v1/diagnostics` — диагностика без секретов, только для админов.

Полный контракт, матрица ролей и правила фронтенда — [docs/API.md](docs/API.md). Интерактивная документация: `/docs`, `/redoc`, `/openapi.json` (отключается через `SCREENLOOP_API_DOCS=false`).

## Разработка

```bash
python3 -m venv .venv
. .venv/bin/activate
pip install -r requirements.txt
export SCREENLOOP_SECRET_KEY="$(openssl rand -hex 32)"
export SCREENLOOP_BOOTSTRAP_PASSWORD="dev-$(openssl rand -hex 4)"
echo "пароль администратора: $SCREENLOOP_BOOTSTRAP_PASSWORD"
python -m screenloop
```

Фронтенд отдельно (проксирует `/api` и `/stream` на `127.0.0.1:8099`):

```bash
cd frontend && npm install && npm run dev
```

Проверки перед PR — те же, что гоняет CI:

```bash
python3 -m ruff check screenloop tests scripts
python3 -m mypy screenloop
python3 -m unittest discover -s tests
docker compose build
./scripts/smoke.sh all   # поднимает образы и проверяет API целиком
```

Изменения собираются в `dev`, релизы выходят из `main`: ветка `feat/…` или `fix/…` → pull request в `dev` → merge, когда CI зелёный. Образ `ghcr.io/gezzydax/screenloop:dev` пересобирается с каждого коммита в `dev` — его и стоит гонять на стенде.

Когда стенд подтвердил, что всё работает, открывается pull request `dev` → `main` и мержится через **Rebase and merge**. Этот мерж и есть точка выпуска: Release Please считает версию по Conventional Commits (`fix:` → patch, `feat:` → minor, `feat!:` или `BREAKING CHANGE:` → major), а тег, GitHub-релиз, `latest` и версионные теги GHCR выходят дальше сами. Ветку `dev` обратно на `main` перебазирует отдельный workflow — руками синхронизировать не нужно. Подробности — в [CONTRIBUTING.md](CONTRIBUTING.md).

## Что дальше

- Headless/CLI-редакция для автоматизации: `screenloopctl upload`, `screenloopctl playlist assign`.
- Плейлисты по расписанию (dayparting).
- Скриншоты и демо в этом README.

## Как помочь

Issues и pull request'ы приветствуются. Особенно полезны:

- **Шаблоны реальных телевизоров** — самое ценное, что можно прислать. Ваша модель есть только у вас.
- Отчёты о совместимости: что заработало, что нет, на какой прошивке.
- Примеры Docker, reverse-proxy и деплоя.
- Скриншоты, демо, документация.
- Ревью безопасности и тесты контракта API.

## Устаревший CLI

Отдельная утилита `dlna_push.py` удалена. Поддерживаемые интерфейсы — веб-панель и `/api/v1`; последняя версия CLI осталась в истории git до релиза 1.5.x.
