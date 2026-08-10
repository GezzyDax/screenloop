# Screenloop Architecture Document Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Создать самодостаточный русскоязычный HTML-документ с тремя векторными схемами, который подробно и достоверно описывает центральную и Node-архитектуру Screenloop и печатается в PDF формата A4.

**Architecture:** Один переносимый HTML-файл содержит семантическую разметку, встроенные стили экрана и печати и встроенные SVG. Контрактный `unittest` проверяет структуру, автономность, обязательные факты и печатные правила; Chromium используется для фактического рендеринга страницы и PDF.

**Tech Stack:** HTML5, CSS3, inline SVG, Python 3 `unittest` и `html.parser`, headless Chromium.

## Global Constraints

- Итоговый документ: `docs/screenloop-architecture.ru.html`.
- Язык документа — русский; аудитория — руководитель и технический специалист.
- Обновление означает только загрузку и доставку медиаконтента, изменение плейлистов и конфигурации воспроизведения; обновление контейнеров и приложения не включать.
- Обязательно описать центральный контроллер, локальные телевизоры и полный функционал Screenloop Node.
- Все CSS, SVG и графические элементы встроены в HTML; внешние шрифты, скрипты, стили и изображения запрещены.
- Обязательны три самостоятельные схемы: общая топология, жизненный цикл медиаконтента и автономность Node.
- Управляющий трафик, медиатрафик, телеметрия и хранение различаются цветом, подписью и типом линии.
- Печатная версия рассчитана на A4, не разрывает схемы и таблицы и не обрезает широкие элементы.
- Фактические утверждения сверяются с `README.md`, `docs/deployment.md`, `docs/nodes.md`, `docs/configuration.ru.md`, `screenloop/web.py`, `screenloop/worker.py` и `screenloop/node_agent.py`.
- Не изменять незавершённые пользовательские правки в `screenloop/permissions.py`, `screenloop/store.py`, `screenloop/web.py` и `tests/test_scopes.py`.

---

## File Structure

- Create `docs/screenloop-architecture.ru.html`: весь публикуемый архитектурный документ, включая CSS и SVG.
- Create `tests/test_architecture_document.py`: структурный контракт документа без сторонних Python-зависимостей.
- Use `/tmp/screenloop-architecture.pdf` and `/tmp/screenloop-architecture-*.png`: временные результаты рендеринга, не добавляемые в git.

### Task 1: Контракт и самодостаточный HTML-документ

**Files:**

- Create: `tests/test_architecture_document.py`
- Create: `docs/screenloop-architecture.ru.html`

**Interfaces:**

- Consumes: требования из `docs/superpowers/specs/2026-08-10-screenloop-architecture-document-design.md` и факты из текущего репозитория.
- Produces: автономный HTML-файл с якорями разделов `summary`, `topology`, `controller`, `local-site`, `node-site`, `content-flow`, `playback`, `network`, `security`, `failures`, `operations`; минимум три inline `<svg>`; CSS для экранного и печатного режима.

- [ ] **Step 1: Написать контрактный тест, который сначала падает из-за отсутствующего HTML**

Создать `tests/test_architecture_document.py`:

```python
import re
import unittest
from html.parser import HTMLParser
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DOCUMENT = ROOT / "docs" / "screenloop-architecture.ru.html"


class DocumentParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.ids: set[str] = set()
        self.svg_count = 0
        self.external_resources: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        values = dict(attrs)
        if values.get("id"):
            self.ids.add(str(values["id"]))
        if tag == "svg":
            self.svg_count += 1
        if tag in {"script", "img", "link"}:
            source = values.get("src") or values.get("href") or ""
            if source and not source.startswith("#") and not source.startswith("data:"):
                self.external_resources.append(source)


class ArchitectureDocumentTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.html = DOCUMENT.read_text(encoding="utf-8")
        cls.parser = DocumentParser()
        cls.parser.feed(cls.html)

    def test_has_complete_section_structure(self) -> None:
        expected = {
            "summary", "topology", "controller", "local-site", "node-site",
            "content-flow", "playback", "network", "security", "failures",
            "operations",
        }
        self.assertTrue(expected.issubset(self.parser.ids))
        self.assertGreaterEqual(self.parser.svg_count, 3)

    def test_is_self_contained(self) -> None:
        self.assertEqual([], self.parser.external_resources)
        self.assertNotRegex(self.html, r"https?://[^<\s]+\.(?:css|js|woff2?|png|jpe?g)")

    def test_contains_required_architecture_facts(self) -> None:
        required = (
            "8098", "8099", "FastAPI", "SQLite", "ffmpeg", "ffprobe",
            "SSDP", "SOAP", "HTTP Range", "WebSocket", "LRU",
            "NO_MEDIA_PRESENT", "SCREENLOOP_ALLOWED_TV_CIDRS",
            "/data/media", "/data/transcoded", "/data/profiles",
        )
        for fact in required:
            with self.subTest(fact=fact):
                self.assertIn(fact, self.html)

    def test_print_css_targets_a4_and_protects_figures(self) -> None:
        self.assertRegex(self.html, r"@page\s*\{[^}]*size:\s*A4")
        self.assertIn("break-inside: avoid", self.html)
        self.assertIn("print-color-adjust: exact", self.html)


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Запустить тест и подтвердить ожидаемое падение**

Run:

```bash
python3 -m unittest tests.test_architecture_document -v
```

Expected: `ERROR` в `setUpClass` с `FileNotFoundError` для `docs/screenloop-architecture.ru.html`.

- [ ] **Step 3: Создать семантический каркас и встроенную систему стилей**

Создать `docs/screenloop-architecture.ru.html` с такой верхнеуровневой структурой:

```html
<!doctype html>
<html lang="ru">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Архитектура системы Screenloop</title>
  <style>
    :root {
      --ink: #14213d;
      --muted: #526078;
      --paper: #ffffff;
      --canvas: #eef3f8;
      --control: #1d5fd1;
      --media: #138a61;
      --telemetry: #b66a00;
      --storage: #7651b4;
      --line: #cbd5e1;
    }
    * { box-sizing: border-box; }
    html { scroll-behavior: smooth; }
    body { margin: 0; color: var(--ink); background: var(--canvas); font-family: Inter, ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif; line-height: 1.55; }
    main { width: min(1180px, calc(100% - 32px)); margin: 32px auto; }
    .page { background: var(--paper); border: 1px solid var(--line); border-radius: 20px; margin: 0 0 24px; padding: clamp(24px, 5vw, 64px); box-shadow: 0 18px 60px rgba(20, 33, 61, .08); }
    .figure, table, .card, .callout { break-inside: avoid; page-break-inside: avoid; }
    svg { display: block; width: 100%; height: auto; }
    @media print {
      @page { size: A4; margin: 13mm 12mm 15mm; }
      * { -webkit-print-color-adjust: exact; print-color-adjust: exact; }
      body { background: #fff; font-size: 9.5pt; }
      main { width: auto; margin: 0; }
      .page { border: 0; border-radius: 0; box-shadow: none; margin: 0; padding: 0; break-before: page; }
      .page:first-child { break-before: auto; }
      .figure, table, .card, .callout { break-inside: avoid; page-break-inside: avoid; }
    }
  </style>
</head>
<body>
  <main>
    <section class="page cover"><h1>Архитектура системы Screenloop</h1><p>Сервер, сеть, телевизоры и доставка медиаконтента</p></section>
    <section class="page" id="summary"><h2>Система в одном развороте</h2><nav aria-label="Оглавление"></nav></section>
    <section class="page" id="topology"><h2>Общая архитектура</h2><figure class="figure"></figure></section>
    <section class="page" id="controller"><h2>Центральный контроллер</h2></section>
    <section class="page" id="local-site"><h2>Локальная площадка</h2></section>
    <section class="page" id="node-site"><h2>Удалённая площадка и Screenloop Node</h2><figure class="figure"></figure></section>
    <section class="page" id="content-flow"><h2>Жизненный цикл медиаконтента</h2><figure class="figure"></figure></section>
    <section class="page" id="playback"><h2>Управление воспроизведением</h2></section>
    <section class="page" id="network"><h2>Сеть, порты и направления соединений</h2></section>
    <section class="page" id="security"><h2>Безопасность и доверительные границы</h2></section>
    <section class="page" id="failures"><h2>Отказные сценарии и восстановление</h2></section>
    <section class="page" id="operations"><h2>Данные и эксплуатационный чек-лист</h2></section>
  </main>
</body>
</html>
```

Заполнить каждый раздел законченным русским текстом и описанными ниже таблицами и схемами. В итоговом HTML не оставлять маркеры незавершённого текста или фиктивные значения.

- [ ] **Step 4: Нарисовать общую топологию как inline SVG**

В разделе `topology` создать SVG с `viewBox="0 0 1200 720"`, `<title>` и `<desc>`. Разместить:

- браузер оператора слева;
- центральную площадку по центру с `screenloop-ui :8098`, `screenloop :8099`, Worker/Node Hub и `/data`;
- локальную LAN с телевизорами справа сверху;
- удалённую площадку с Screenloop Node, кэшем и телевизорами справа снизу;
- стрелки `HTTP(S)`, `API / SSE`, `SSDP + SOAP`, `HTTP Range /stream`, `WSS исходящий`, `HTTPS sync`;
- легенду четырёх типов потоков.

Определить стрелки один раз через SVG-маркеры:

```html
<defs>
  <marker id="arrow-control" markerWidth="8" markerHeight="8" refX="7" refY="4" orient="auto">
    <path d="M0,0 L8,4 L0,8 z" fill="#1d5fd1"/>
  </marker>
  <marker id="arrow-media" markerWidth="8" markerHeight="8" refX="7" refY="4" orient="auto">
    <path d="M0,0 L8,4 L0,8 z" fill="#138a61"/>
  </marker>
</defs>
```

Под каждой двунаправленной логической связью использовать отдельные направленные линии, чтобы было видно, что SOAP-команду инициирует Screenloop, а HTTP Range-запрос — телевизор.

- [ ] **Step 5: Нарисовать жизненный цикл контента как inline SVG**

В разделе `content-flow` создать горизонтальную SVG-схему из десяти пронумерованных этапов:

`Загрузка → Проверка → Оригинал + SQLite → ffprobe → Очередь профилей → ffmpeg → Плейлист → Назначение ТВ → Node sync при необходимости → HTTP Range + мониторинг`.

Под основной линией сделать две ветви после назначения:

- `Локальный ТВ`: подписанный URL контроллера → backend `:8099`;
- `Node-телевизор`: конфигурация по WSS → HTTPS-загрузка в кэш → подписанный URL ноды `:8099`.

Рядом добавить выделенный вывод: «SOAP передаёт команду и URL; байты видео телевизор запрашивает сам».

- [ ] **Step 6: Нарисовать автономность Node как inline SVG**

В разделе `node-site` создать диаграмму состояний:

`Enrollment → Online / Sync → Controller unavailable → Offline playback → Reconnected → Online / Sync`.

Под состояниями указать:

- enrollment-токен одноразовый и действует 24 часа;
- постоянное соединение — исходящий WSS;
- синхронизация кэша и конфигурации — каждые 30 секунд при связи;
- переподключение — backoff 2–60 секунд;
- offline: последний известный плейлист, локальный кэш и вычисленное расписание продолжают работать;
- незакэшированный новый ролик недоступен до восстановления связи.

- [ ] **Step 7: Заполнить технические разделы точными таблицами и сценариями**

Добавить:

- таблицу компонентов центрального сервера: nginx/Vue, FastAPI, Store/SQLite, Command Worker, Poll Worker, Transcode Worker, Node Hub;
- таблицу `/data`: `db/screenloop.sqlite3`, `media`, `transcoded`, `profiles`, с указанием что резервируется и что можно пересоздать;
- таблицу сети с источником, назначением, транспортом, направлением и политикой firewall;
- пошаговое описание локального DLNA-потока и Node-потока;
- секции ролей, сессий, CSRF, CIDR, enrollment и stream-токенов;
- карточки ошибок: upload, ffmpeg, TV offline, stale control URL, manual standby, closed schedule, Node offline, missing cache item, reconnect;
- эксплуатационный чек-лист, который не включает обновление версий приложения.

- [ ] **Step 8: Запустить контрактный тест и добиться прохождения**

Run:

```bash
python3 -m unittest tests.test_architecture_document -v
```

Expected: 4 tests, `OK`.

- [ ] **Step 9: Проверить diff и закоммитить функционально законченный документ**

Run:

```bash
git diff --check -- docs/screenloop-architecture.ru.html tests/test_architecture_document.py
git add docs/screenloop-architecture.ru.html tests/test_architecture_document.py
git commit -m "docs: add Screenloop architecture document"
```

Expected: commit includes only the HTML document and its contract test.

### Task 2: Печатный рендеринг и визуальная корректировка

**Files:**

- Modify: `docs/screenloop-architecture.ru.html`
- Test: `tests/test_architecture_document.py`

**Interfaces:**

- Consumes: готовый автономный HTML из Task 1.
- Produces: визуально проверенную экранную и A4/PDF-версию без обрезания, наложений и нечитаемого текста.

- [ ] **Step 1: Повторно выполнить структурный контракт перед визуальной проверкой**

Run:

```bash
python3 -m unittest tests.test_architecture_document -v
```

Expected: 4 tests, `OK`.

- [ ] **Step 2: Сформировать PDF через headless Chromium**

Run:

```bash
chromium --headless --no-sandbox --disable-gpu --print-to-pdf=/tmp/screenloop-architecture.pdf --print-to-pdf-no-header file:///home/gezzy/screenloop/docs/screenloop-architecture.ru.html
```

Expected: Chromium сообщает о записанном PDF; файл `/tmp/screenloop-architecture.pdf` существует и имеет ненулевой размер.

- [ ] **Step 3: Проверить метаданные PDF и растеризовать страницы для просмотра**

Run:

```bash
pdfinfo /tmp/screenloop-architecture.pdf
pdftoppm -png -r 110 -f 1 -l 20 /tmp/screenloop-architecture.pdf /tmp/screenloop-architecture
```

Expected: формат страниц A4, ненулевое число страниц; PNG создаются для каждой фактической страницы. Если PDF длиннее 20 страниц, увеличить `-l` до числа из `pdfinfo`.

- [ ] **Step 4: Визуально проверить ключевые страницы**

Открыть PNG титульной страницы, общей топологии, жизненного цикла и Node-автономности. Проверить:

- подписи не перекрывают стрелки и границы;
- русский текст не обрезан;
- цветовые роли совпадают с легендой;
- таблицы помещаются по ширине;
- заголовок не остаётся один внизу страницы;
- схема не делится между страницами;
- мелкий текст схем читается при A4-масштабе.

- [ ] **Step 5: Исправить только выявленные проблемы печати**

Для широких таблиц применять `font-size: 8.5pt` внутри print media и разрешать перенос слов. Для слишком высокой схемы уменьшать внутренние SVG-отступы или переносить сопроводительный текст на следующую страницу. Не уменьшать основной печатный текст ниже 9pt.

```css
@media print {
  h2, h3 { break-after: avoid; }
  table { font-size: 8.5pt; }
  th, td { overflow-wrap: anywhere; }
  .figure { break-inside: avoid; page-break-inside: avoid; }
}
```

- [ ] **Step 6: Повторить PDF-рендеринг после исправлений**

Run заново:

```bash
chromium --headless --no-sandbox --disable-gpu --print-to-pdf=/tmp/screenloop-architecture.pdf --print-to-pdf-no-header file:///home/gezzy/screenloop/docs/screenloop-architecture.ru.html
```

Expected: PDF успешно перезаписан; повторный просмотр исправленных страниц не показывает обрезаний и наложений.

- [ ] **Step 7: Проверить и закоммитить печатные правки, если они потребовались**

Run:

```bash
python3 -m unittest tests.test_architecture_document -v
git diff --check -- docs/screenloop-architecture.ru.html tests/test_architecture_document.py
git add docs/screenloop-architecture.ru.html tests/test_architecture_document.py
git commit -m "docs: refine architecture PDF layout"
```

Expected: tests pass; commit содержит только фактически потребовавшиеся печатные правки. Если HTML не менялся, отдельный пустой commit не создавать.

### Task 3: Итоговая проверка репозитория и передача результата

**Files:**

- Verify: `docs/screenloop-architecture.ru.html`
- Verify: `tests/test_architecture_document.py`

**Interfaces:**

- Consumes: визуально проверенный документ из Task 2.
- Produces: подтверждённый результат и точные команды для последующего получения PDF.

- [ ] **Step 1: Запустить целевой тест и основную Python-проверку репозитория**

Run:

```bash
python3 -m unittest tests.test_architecture_document -v
python3 -m unittest discover -s tests
```

Expected: оба запуска завершаются `OK`. Если общая проверка падает в пользовательских незавершённых изменениях, отдельно зафиксировать это и не изменять их без разрешения.

- [ ] **Step 2: Проверить итоговый diff и рабочее дерево**

Run:

```bash
git diff --check
git status --short
git log -3 --oneline
```

Expected: документ и тест закоммичены; исходные пользовательские изменения остаются нетронутыми и незакоммиченными.

- [ ] **Step 3: Передать HTML и временный PDF пользователю**

В финальном сообщении дать ссылки на:

- `docs/screenloop-architecture.ru.html` как основной результат;
- `/tmp/screenloop-architecture.pdf` как проверочную PDF-копию, с пояснением, что временный файл можно позже заменить финальным экспортом;
- контрактный тест и дизайн-спецификацию.

Также указать фактическое число PDF-страниц, команды тестирования, результаты проверок и отметить, что обновление приложения сознательно не входит в документ.
