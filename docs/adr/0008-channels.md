# ADR-008 — Channels: коннекторы Devboard к внешним сервисам

- **Status:** Deferred (2026-05-25) — отложен до завершения ADR-009 по решению owner-а. Возвращаемся к коннекторам после построения отделов и роли Управляющего.
- **Authors:** Claude-сессия (Opus 4.7) после разбора openclaw
- **Sprint:** TBD (после ADR-009)
- **Related:**
  - **ADR-009** (`0009-managing-director.md`) — приоритетнее. Управляющий — главный будущий потребитель channels (Telegram-сводки для owner-а).
  - ADR-002 (`0002-role-format.md`) — формат ролей; здесь добавляется `allowed_channels` в frontmatter.
  - ADR-007 (`0007-memory-layer.md`) — Управляющий с долгосрочной памятью может слать сводки через channels.

---

## 1. Context

Owner ([handoff §6](../../ПЕРЕДАЧА_СЕССИИ.md), а также текущий вопрос про коннекторы к дашборду) хочет подключать Devboard к внешним сервисам:

- **Telegram** — нотификации о смене статусов, утренние сводки, прямые команды боту (`/inbox`, `/status`).
- **Bitrix24** — двусторонняя интеграция с CRM владельца (задачи Devboard ↔ задачи Битрикса, сделки → подзадачи).
- **Email** — daily digest, eскалации, отчёты.

Сейчас в Devboard:
- Никаких внешних коннекторов нет.
- MCP-серверы используются только для in-process tools (pride-tasks).
- Логика `notify_user` пишет в свою БД-таблицу, наружу не выходит.

Если просто начать впиливать ad-hoc по 1 интеграции — получим спагетти: токен Телеги в одном месте, secret Битрикса — в другом, обработка вебхуков скопирована, ретраи отсутствуют.

После разбора **openclaw `src/channels/`** видно их чёткое разделение:

| Абстракция | Что | OpenClaw файл |
|---|---|---|
| **Channel** | транспорт: send/receive/auth/secrets/config — реализация | `src/channels/message/types.ts:349` (`ChannelMessageAdapterShape`) |
| **Skill** | декларация capability в markdown — что я могу делать через какие channels | `skills/discord/SKILL.md` (frontmatter `allowed-tools: [message]`) |

Это даёт **separation transport/capability**: Telegram-бот один, но им пользуются разные роли (Advisor шлёт сводки, тимлид — нотификации). Аналогично для Bitrix24 — один коннектор, разные use-case.

---

## 2. Decision

### 2.1. Новая папка `channels/`

```
channels/
  __init__.py
  base.py                    # ChannelBase — абстрактный класс
  telegram/
    __init__.py
    channel.py               # TelegramChannel(ChannelBase)
    webhook.py               # Flask blueprint для входящих updates
    schema.py                # pydantic config модель
  bitrix24/
    channel.py
    webhook.py
    schema.py
  email/
    channel.py
    schema.py                # SMTP конфиг
```

### 2.2. Контракт `ChannelBase`

```python
class ChannelBase(ABC):
    name: str                        # 'telegram', 'bitrix24', 'email'
    config_schema: type[BaseModel]   # pydantic для валидации .env / Settings UI

    @abstractmethod
    def validate_config(self, config: dict) -> ValidationResult: ...

    @abstractmethod
    def send(self, payload: ChannelMessage) -> SendResult: ...
        """Отправить сообщение. payload — единый формат: {to, subject?, text, attachments?}."""

    @abstractmethod
    def receive(self, raw_update: dict) -> Optional[InboundMessage]:
        """Парсить входящий update от webhook'а или polling'а.
           Возвращает нормализованный InboundMessage или None если update нерелевантен."""

    def healthcheck(self) -> ChannelHealth:
        """Проверка live-связи (API ping). Default — раз в минуту фоновая задача."""

    @classmethod
    def lifecycle_hooks(cls) -> dict[str, Callable]:
        """on_register, on_start, on_stop, on_message_failed. Default — empty."""
```

Inspired by openclaw `ChannelMessageAdapterShape` (`/tmp/openclaw/src/channels/message/types.ts:349`), но **без** разделения на 4 sub-adapter (send/receive/durableFinal/live) — для нашего масштаба это overkill. Один интерфейс.

### 2.3. Skill = markdown frontmatter с allowed-channels

Существующие роли (`roles/тимлид.md`, `roles/бэкенд.md`, etc.) расширяются полем `allowed_channels`:

```yaml
---
name: тимлид
description: Координатор AI-команды
model: opus
allowed_channels: [telegram]   # NEW — может отправлять через TG
allowed_inbound: []            # NEW — не принимает входящих, только исходящие
---
```

```yaml
---
name: advisor
allowed_channels: [telegram, email]
allowed_inbound: [telegram]    # Advisor умеет читать ответы owner'а в TG
---
```

При запуске сессии CLI-обёртка (`devboard-work.sh`, `devboard-advisor.sh`) парсит frontmatter, читает `allowed_channels`, передаёт соответствующие MCP-tools (`channel_send_telegram`, `channel_send_email`).

### 2.4. MCP-tools для channels

Каждый channel экспонирует одну функцию через MCP:

| Tool | Channels |
|---|---|
| `channel_send(channel_name, to, text, subject?, attachments?)` | Унифицированный send |
| `channel_list_available()` | Какие channels настроены |
| `channel_health(name)` | Статус |

Внутри MCP-сервер диспатчит на `ChannelBase.send()` соответствующей реализации.

### 2.5. Secrets и config — два уровня

**Уровень 1 — .env (для разработчика):**
```env
TELEGRAM_BOT_TOKEN=123:ABC...
BITRIX24_WEBHOOK_URL=https://example.bitrix24.ru/rest/1/abc...
EMAIL_SMTP_HOST=smtp.yandex.ru
EMAIL_SMTP_USER=advisor@example.com
EMAIL_SMTP_PASS=...
```

**Уровень 2 — Settings UI (для пользователя):**
- Вкладка `/settings` → раздел «Channels».
- Список channels: для каждого — toggle ON/OFF, кнопка «Connect» (открывает форму с полями из `config_schema`).
- При сохранении → запись в `data/secrets.db` (отдельная БД, gitignored, с шифрованием на уровне SQLite encryption extension — пока YAGNI, начнём с plain JSON в `data/channels.json` под `chmod 600`).

**Resolution order**: ENV → secrets store → 400 «not configured».

### 2.6. Inbound flow — webhook'и

Telegram и Bitrix24 шлют webhook'и. Регистрируем Flask blueprint при старте:

```python
# dashboard/app.py
from channels.telegram.webhook import bp as tg_bp
from channels.bitrix24.webhook import bp as bx_bp

app.register_blueprint(tg_bp, url_prefix='/webhooks/telegram')
app.register_blueprint(bx_bp, url_prefix='/webhooks/bitrix24')
```

Endpoint валидирует source (HMAC для TG, IP allowlist для BX), парсит через `Channel.receive()`, нормализованный `InboundMessage` ставится в очередь `chat_messages` либо триггерит конкретный flow (создание задачи, ответ Advisor'у).

**Production-blocker:** Telegram webhook требует public HTTPS URL. На локальной машине owner'а — невозможно без ngrok / Cloudflare Tunnel. **Workaround для MVP**: long-polling (`getUpdates`) в фоновом потоке. Webhook — Фаза 2 когда будет prod-deploy.

### 2.7. Что входит в первый этап (MVP)

| Channel | Why first | Use-case |
|---|---|---|
| **Telegram** | Самый востребованный, owner живёт в TG | Daily digest «5 задач в review», alert «тимлид залип на сессии», `/inbox` команда |
| **Email** | Простой SMTP, без webhook'ов нужен | Еженедельный summary, эскалации |

### 2.8. Что НЕ в MVP

| Channel | Reason |
|---|---|
| Bitrix24 | Большая интеграция, отдельная ADR-009 потом. Требует mapping сущностей (deal ↔ task), webhook auth, OAuth refresh. |
| Slack/Discord | У Acme нет use-case (нет команды в Slack). Если когда-то — берём openclaw skill `discord/SKILL.md` как референс. |
| WhatsApp | Compliance, требует Meta Business API. Откладываем. |
| Voice/realtime | Overkill для канбана. |

---

## 3. Implementation Plan

### Фаза 1 — MVP (1 спринт)

| # | Задача | Owner | Сложность |
|---|---|---|---|
| 1 | `channels/base.py` — ChannelBase + ChannelMessage/InboundMessage types | архитектор | Easy (~150 LoC) |
| 2 | `channels/telegram/` — channel + long-polling worker | бэкенд | Medium (~300 LoC) |
| 3 | `channels/email/` — SMTP send | бэкенд | Easy (~150 LoC) |
| 4 | MCP-tools `channel_send` / `channel_list` / `channel_health` | бэкенд | Easy (~80 LoC) |
| 5 | `roles/*.md` — добавить `allowed_channels` в frontmatter всех 7 ролей | техписатель | Easy (5 минут на роль) |
| 6 | UI: вкладка `Settings → Channels` (toggle + connect форма) | frontend | Medium (~250 LoC JS) |
| 7 | E2E: послать TG message → получить /inbox команду → ответить | qa | Medium (~200 LoC) |

### Фаза 2 — Webhooks + Bitrix24 (отдельная ADR-009)

- Public HTTPS endpoint (Cloudflare Tunnel или Render deploy).
- Telegram webhook вместо polling.
- Bitrix24 — отдельная большая ADR с mapping сущностей.

### Фаза 3 — Capability-aware send (опционально)

По образцу openclaw `ChannelMessageLiveCapability` (`/tmp/openclaw/src/channels/message/types.ts:293`) — channel может объявить, что поддерживает streaming, draft preview, и т.п. Тимлид смотрит capabilities и выбирает оптимальный канал. **Пока не нужно** — у нас все каналы тривиальные.

---

## 4. Consequences

### Плюсы

- **Чистое разделение transport (channel) vs capability (skill).** Telegram-бот один, но используется тремя ролями.
- **Расширяемость.** Добавить новый channel = 1 файл + регистрация. Не нужно трогать роли, MCP-tools, или dashboard core.
- **Owner-controlled config.** Settings UI даёт владельцу подключить TG в 3 клика без правки .env.
- **Webhook + polling fallback.** На локалке работает через polling, в prod — через webhook без изменений роли.
- **Audit.** Все send/receive через единый интерфейс → легко логировать в `data/channels.log`.

### Минусы / риски

- **Новая большая папка.** ~5-10 файлов на channel. Mitigation — начинаем с 2 channel (TG + email), масштаб контролируемый.
- **Secrets management complexity.** Сейчас один `.env` — простой. С 5 channel'ами становится зоопарк. Mitigation — Settings UI как single source of truth, .env только fallback.
- **Polling vs webhook divergence.** Код для polling может отличаться от webhook handler'а → два code path. Mitigation — единый `Channel.receive(raw_update)` принимает оба.
- **Лимиты внешних API.** TG bot — 30 msg/sec, BX24 — 2 req/sec. Mitigation — rate-limiter в `ChannelBase.send` через `time.monotonic()` + per-channel budget.
- **i18n inbound.** Если пользователь пишет в TG на русском, а LLM-роль ожидает английского — нужен detect/translate. **Skip в MVP** — owner пишет на русском, advisor отвечает на русском.

---

## 5. Alternatives Considered

### 5.1. Просто MCP-сервер для каждого внешнего сервиса

«Telegram-MCP, Bitrix-MCP — отдельные процессы, тимлид зовёт их как обычные tools». **Отвергнуто:**

- MCP-tools — синхронные (request-response). Нет встроенной концепции webhook/incoming.
- Нет места для long-polling worker'а — внутри MCP-сервера не запустишь фоновый thread с persistent connection к TG API.
- Невозможен Settings UI (MCP-серверы пользователь не видит).

### 5.2. Прямой код в каждой роли

«Просто в `roles/тимлид.md` написать инструкцию `curl -X POST https://api.telegram.org/...`». **Отвергнуто:**

- Токен в роли = токен в git (даже если переменная — пример из роли утечёт).
- Каждая роль изобретает свой формат payload.
- Retry/rate-limit на стороне роли — больно.

### 5.3. Сторонняя библиотека вроде Apprise / Pushover

`pip install apprise` — multi-channel notification из коробки (TG/Slack/Email/Discord/100+ others). **Частично используем:**

- Для `send` — да, можно завернуть Apprise внутрь `EmailChannel.send` / `TelegramChannel.send`.
- Для `receive` — Apprise не умеет inbound. Нужна своя реализация.
- Вердикт: Apprise опционально для send-only channels. Но базовый интерфейс всё равно наш.

### 5.4. Полная имплементация openclaw plugin SDK для channels

`registerChannel(spec)` + `ChannelConfigAdapter` + `ChannelSecretsAdapter` + `ChannelMessageAdapterShape` + lifecycle hooks. **Отвергнуто:**

- Их `src/channels/` — 30+ файлов, 4 sub-adapter (send/receive/durableFinal/live).
- Наш масштаб (2-5 channels, single-tenant) этого не оправдывает.
- Берём паттерн «channel ≠ skill» и базовый interface; оставляем для возможного будущего ADR-X переходить на полную модель если понадобится.

### 5.5. Не делать channels, использовать только email

«Самое простое — почта». **Отвергнуто:** owner живёт в Telegram, email — формальный канал. Игнорируется. Делаем оба, но первый = TG.

---

## 6. Open Questions

1. **Где живут secrets — БД или файл?** Сейчас предлагается `data/channels.json` под chmod 600. Если когда-то появится multi-user — нужна шифрованная БД. Решаем при появлении.
2. **TG webhook vs polling.** В MVP — polling. Когда перейдём в prod — публичный URL → webhook. Это упрощает или усложняет миграцию?
3. **Bitrix24 mapping.** Куда деваются deal'ы, contacts, companies из BX24? Создавать ли отдельные сущности в Devboard или просто attach к существующим tasks? Откладываем в ADR-009.
4. **Что если channel падает в момент send?** Сейчас планируем in-memory retry с exponential backoff. Persistent очередь (как `durableFinal` у openclaw) — overkill для MVP.
5. **Channel-as-MCP.** Можно ли channel экспонировать как **отдельный MCP-сервер**, чтобы внешние Claude-сессии могли использовать их без знания нашего кода? Интересно, но это «MCP marketplace» уровень — отложено.

---

## 7. Related ADRs

- **ADR-002** — формат ролей. ADR-008 добавляет `allowed_channels` в frontmatter ролей.
- **ADR-007** (черновик, параллельно) — Advisor использует email и TG для daily digest.
- **Будущий ADR-009** — Bitrix24-интеграция (отдельная большая ADR).

---

## 8. Tasks для backend

1. **B1. `channels/base.py`** — ChannelBase + Pydantic-схемы payload (ChannelMessage, InboundMessage, SendResult).
2. **B2. `channels/telegram/channel.py`** — TG channel: send через Bot API, receive через `getUpdates` polling worker.
3. **B3. `channels/email/channel.py`** — SMTP send (smtplib + email.mime).
4. **B4. MCP-tools** — `channel_send`, `channel_list_available`, `channel_health` в `mcp_server/pride_tasks/tools.py`.
5. **B5. Polling worker** — фоновый thread в `dashboard/app.py` для TG long-polling. Старт при наличии конфига.
6. **B6. Secrets store** — `data/channels.json` + read/write helper'ы.

## 9. Tasks для frontend

1. **F1. Settings → Channels** — список доступных channels с toggle/connect.
2. **F2. Connect form** — динамически рендерит поля по `config_schema` пришедшему из `/api/channels/<name>/schema`.
3. **F3. Health badge** — статус каждого channel (last ping, last error).
4. **F4. i18n** ключи.

## 10. Tasks для DevOps

1. **D1. `.env.example`** — добавить новые переменные `TELEGRAM_BOT_TOKEN`, `EMAIL_*`.
2. **D2. Docker-compose** — экспонировать порт для будущих webhook'ов (но не подключаем).
3. **D3. Documentation** — `docs/channels-setup.md` с шагами как создать TG бот и привязать.

## 11. Tasks для QA

1. **Q1. Unit-tests** — каждый Channel.send/receive с mock API.
2. **Q2. E2E TG** — отправить TG msg на тестовый бот, увидеть в Devboard. Получить ответ.
3. **Q3. Settings persistence** — заполнить форму → перезапуск дашборда → конфиг подхватился.
4. **Q4. Rate-limit** — попытка отправить 100 msg/sec → не падает, queue работает.

---

## References

- OpenClaw channel contract — `/tmp/openclaw/src/channels/message/types.ts:258-358`.
- OpenClaw channel plugin shape — `/tmp/openclaw/src/channels/plugins/types.plugin.ts:61`.
- OpenClaw skill manifest example — `/tmp/openclaw/skills/discord/SKILL.md`.
- `mcp_server/pride_tasks/tools.py` — точка регистрации новых MCP-tools.
- `dashboard/app.py` — Flask blueprints для будущих `/webhooks/*`.
- Telegram Bot API — https://core.telegram.org/bots/api.
- Bitrix24 REST — https://dev.1c-bitrix.ru/rest_help/.

---

## Changelog

- **2026-05-25 — rev 1:** Initial draft. Источник: запрос owner'а про коннекторы + анализ openclaw channels/skills архитектуры.
- **2026-05-25 — rev 2:** Status: Draft → **Deferred**. По решению owner-а — приоритет переходит к ADR-009 (Управляющий + 11 отделов). Channels возвращаются после построения отделов. Ссылки на удалённый ADR-007 (Advisor) заменены на актуальный ADR-007 (Memory layer) и ADR-009.
