# Changelog

All notable changes to **devboard** will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [1.1.0](https://github.com/rdm9x/devboard/compare/v1.0.0...v1.1.0) (2026-08-31)


### Added

* **8e0f3bb869db:** add Flask calculator backend with safe eval and tests ([03ad391](https://github.com/rdm9x/devboard/commit/03ad391095ed524185d51b92540253f43f2fa12a))
* add Demo mode button and Clear demo UI (E3.3) ([a0dfc76](https://github.com/rdm9x/devboard/commit/a0dfc765294c50a497753c5e1759910d57a2d3d4))
* add Demo mode button in settings (E3.3) — Try/Clear demo ([207988c](https://github.com/rdm9x/devboard/commit/207988c5726878b23cd253e753eb7902aebd54df))
* add LLM role config tests (E6.6) ([44bb535](https://github.com/rdm9x/devboard/commit/44bb535d3da018754694ca31eed71a4f7632b363))
* add llm/model frontmatter to all roles (E6.6) ([47baabe](https://github.com/rdm9x/devboard/commit/47baabe5fc9552e6d8f8c1f858b1cb0e86c9cc81))
* add performance baseline docs (E8.6) ([5906791](https://github.com/rdm9x/devboard/commit/5906791f0a7bd6f7632b19ad2f8e7f409027e715))
* add POST/DELETE /api/demo endpoint for onboarding Demo mode ([da12975](https://github.com/rdm9x/devboard/commit/da129753311da854d5668e9cfe8a4aa0495780fc))
* add Replay tour button in settings (E3.4) ([fd9f40b](https://github.com/rdm9x/devboard/commit/fd9f40b09905102c1a6b778e91686155b6e777f6))
* add role import endpoint tests and 6 example roles (E7.3-E7.5) ([dbb721e](https://github.com/rdm9x/devboard/commit/dbb721e48383418def1f27803c60769e4c5799c7))
* **ADR-009 Phase 1:** Управляющий + долгосрочная память поверх dev ([7c281d1](https://github.com/rdm9x/devboard/commit/7c281d19539f349f50548fa16edbd2f61546c169))
* **ADR-009 Phase 2:** пилот marketing-отдел готов ([7365bd4](https://github.com/rdm9x/devboard/commit/7365bd4dde61aab832cc0ec74e19915641d9be68))
* **B1-1.5:** /api/team/start — параметр role + backend подбор скрипта ([63db859](https://github.com/rdm9x/devboard/commit/63db8595023ffd4325045e65a5db9d07a49a15a4))
* **B1:** SQL migration — chat_threads + chat_messages.thread_id ([4decc6a](https://github.com/rdm9x/devboard/commit/4decc6a660bc94fbafb7aa7c3eef57d2e1393041))
* **B2-1.6:** company-context onboarding — endpoint + inherits injection ([8fc6849](https://github.com/rdm9x/devboard/commit/8fc6849b1c16b23595d3276adb2830dfff60758e))
* **B2:** devboard-work.sh + .ps1 — парсинг --role &lt;slug&gt; ([758553a](https://github.com/rdm9x/devboard/commit/758553a7f342c5e3e6c2692e692749d4d46147a1))
* **B2:** Owner Dashboard Backend API (ADR-013) ([78c4aa2](https://github.com/rdm9x/devboard/commit/78c4aa2ab8688c8f2c4c4a4323037427ae069741))
* **B2:** REST endpoints — artifacts list + open-file + open-folder ([8eda6e2](https://github.com/rdm9x/devboard/commit/8eda6e2bb933af796a8ea2570fd28b23660f9ceb))
* **B5-1.6:** model_hint per-role — инжекция PRIDE_TEAM_MODEL при старте сессии ([995e57e](https://github.com/rdm9x/devboard/commit/995e57e15c608cb5503f8ddcc7ce1a554fab482b))
* **board:** чип PRJ-NNN на карточке задачи ([b89687c](https://github.com/rdm9x/devboard/commit/b89687c252450872bad1a4bbec5ec021f5a6e466))
* **chat Stage 5:** auto-reply — managing-director responds to owner messages ([8de0f63](https://github.com/rdm9x/devboard/commit/8de0f63b646c4f5f3be79451b37a40f75400b84b))
* **chat:** turn /chat into a tab inside main page, monolithic dark theme ([9a73294](https://github.com/rdm9x/devboard/commit/9a7329444a6644c1a572b745aaed47dedbe741ae))
* **chat:** кнопки «В архив» / «Восстановить» на тредах ([e3316a8](https://github.com/rdm9x/devboard/commit/e3316a8740035adbe75fa1eb390dd426f618019a))
* **chat:** убрать нативные alert/confirm/prompt — кастомные модалки ([01e1a54](https://github.com/rdm9x/devboard/commit/01e1a54bc9ef43454fb0bfcf9a44fc0e3ae1f9b4))
* **db:** add task_artifacts migration ([28fbbba](https://github.com/rdm9x/devboard/commit/28fbbba5a2350d8b0b3c75e7b04da9faa561aac3))
* **E7.2:** replace model text input with dynamic dropdown per LLM provider ([287f158](https://github.com/rdm9x/devboard/commit/287f1585b07357019fc754ac867ad68fd14ee2fb))
* **E7.2:** wire dynamic LLM model dropdown — HTML+i18n+CSS+e2e ([641f910](https://github.com/rdm9x/devboard/commit/641f9103459459369c2cd2e45ccd4e8e820c701e))
* **F1-1.6:** split-button dropdown «Запустить команду» с выбором роли ([46f712d](https://github.com/rdm9x/devboard/commit/46f712d707975230cf97a55b4558ba4ea761e95a))
* **F2-1.5:** Roles tab — collapsible department sections ([f13e37c](https://github.com/rdm9x/devboard/commit/f13e37cf545a3fe498139fb705d6d12be07270d6))
* **F2-1.6:** Roles tab — единая таблица с colgroup и dept-group строками ([14eb87c](https://github.com/rdm9x/devboard/commit/14eb87c0d1fa7fffa36b2410d5b451de0faffe27))
* **F2.1:** DB migration enabled + PATCH endpoint + session filter + MCP field ([aa4fd80](https://github.com/rdm9x/devboard/commit/aa4fd80e6b463c332af74b2d0c2e8de2c7498706))
* **F2.2:** checkbox на todo-карточках + CSS disabled + column counter + i18n ([3d58ce1](https://github.com/rdm9x/devboard/commit/3d58ce1430b37ba9df1c32fe55e4d2c626913c6b))
* **F2:** Threads list with search, sort by updated_at, and archive collapsible ([9e72ead](https://github.com/rdm9x/devboard/commit/9e72ead273f75d6d00043b495001861d789ac1e6))
* **F3-1.5:** chat — dynamic placeholder and interlocutor description ([5ce0a39](https://github.com/rdm9x/devboard/commit/5ce0a39e0f8847af94284c11b8ba15f80df52499))
* **F3:** Implement active thread message rendering + input ([dfc20bc](https://github.com/rdm9x/devboard/commit/dfc20bca845d46b73270f9d09714161ba8eab721))
* **f3:** Owner Dashboard Frontend UI — implement project cards, progress, action items ([bca68b2](https://github.com/rdm9x/devboard/commit/bca68b2db28e9f9f755acd31a71eb492bda550f5))
* **F5:** Sidebar chat button + remove right panel from kanban ([6dcf55a](https://github.com/rdm9x/devboard/commit/6dcf55ad7b9718703b1713aeb9f1ac63b45e788e))
* **F5:** Sidebar chat button with onboarding tooltip ([22edf2d](https://github.com/rdm9x/devboard/commit/22edf2d300119b4ebcc0a8ea116cc818d9d65d7f))
* **inbox:** секция «Отчёты по проектам» на столе — быстрый доступ ([710e9b1](https://github.com/rdm9x/devboard/commit/710e9b197841834e07e9e089648be6131d721794))
* **memory:** curated manager memory — core knowledge tag, cascade archive ([7c79761](https://github.com/rdm9x/devboard/commit/7c79761e8edccc16e64250f80e7366b196ff19a9))
* **Phase 3a B1+WIP:** chat_threads migration + chat UI scaffolding + safety rule ([9634adb](https://github.com/rdm9x/devboard/commit/9634adb1f19e7f6dfc3f6d41acf04035d1400a6d))
* **planning Stage 1:** live button + REST + schema for Phase 3b orchestration ([b5d3aae](https://github.com/rdm9x/devboard/commit/b5d3aae89f92b31e63c1f6302cbf7ebea1c2c820))
* **planning Stage 1:** UI + Flask endpoints (paired with previous commit) ([ba1bd44](https://github.com/rdm9x/devboard/commit/ba1bd440a8c384aa554d59f81520f779994e2639))
* **planning Stage 2:** orchestrator + planning-mode prompts for leads ([ed86c87](https://github.com/rdm9x/devboard/commit/ed86c877969642b24ead52eb7d28b0b45bace542))
* **planning Stage 3:** live banner + accept/reject/revise buttons ([c42a2ac](https://github.com/rdm9x/devboard/commit/c42a2ac0d4b0ccac4b3a50d0b9ef4604caafea7d))
* **planning Stage 4a:** each planning session gets its own chat thread ([86b8bc5](https://github.com/rdm9x/devboard/commit/86b8bc5ebeb622e8b0f410eec3bc558c833b85d1))
* **planning Stage 4b:** «Принять» decomposes the plan into kanban tasks ([659ac22](https://github.com/rdm9x/devboard/commit/659ac22d2c68e81c8334df3542d68cc5eaf3d0b8))
* **planning Stage 4c:** «Доработать» = managing-director resynthesizes report ([7533f67](https://github.com/rdm9x/devboard/commit/7533f67709ba0fa04ae4c8d2402f989bb9c17e86))
* **planning:** жёсткий cost-tracking + настраиваемый лимит в форме ([2ee01e3](https://github.com/rdm9x/devboard/commit/2ee01e378c8ee3fe6b22676feaacab6396a659ef))
* **planning:** профили моделей base/deep + chat-responder на haiku ([7e4981a](https://github.com/rdm9x/devboard/commit/7e4981a4bba26ffe2ec1ddf4259e0bfc315e011b))
* **projects:** PRJ-NNN structure + UI cleanup + 13 test repairs ([a74a02d](https://github.com/rdm9x/devboard/commit/a74a02dbc23bd194f0f029015cc64d083455b8f9))
* **report:** авто HTML-отчёт по проекту когда все задачи завершены ([165ab9a](https://github.com/rdm9x/devboard/commit/165ab9a6f5fa76378caf596a4d15b93ed9abcb9e))
* **rework:** «Доработать» реально заставляет переделать, а не закрыть повторно ([caab7f8](https://github.com/rdm9x/devboard/commit/caab7f86a658f8fcb6bf7e61bdd579911cad3f46))
* **S1.1:** rename product pride-team → devboard across entire repo ([30c8e11](https://github.com/rdm9x/devboard/commit/30c8e115357dd6b0128daa85d02b59ebf1198ca4))
* **S1.2:** replace personal name «дмитрий» with neutral «пользователь»/«user» ([500d7ac](https://github.com/rdm9x/devboard/commit/500d7ac969004b34a91c46e46c9bf4191dfa63e2))
* **S15.2:** ADR-006 token optimization quick wins ([4d735ab](https://github.com/rdm9x/devboard/commit/4d735ab9ea8091ddcacc0e8d6c08c94876cfb1be))
* **S16.3:** cmd+k global search + shortcuts tutorial page ([32262bd](https://github.com/rdm9x/devboard/commit/32262bd219726c9ae85bc6d10c5a831ee23c1856))
* **S17.5:** persistence auto_mode при перезагрузке дашборда ([1bf53df](https://github.com/rdm9x/devboard/commit/1bf53dfe68ffcfd0ba98c9f991a137137c95684a))
* **S2.1:** complete Settings page — backend endpoint, en.json, aria fix ([966597d](https://github.com/rdm9x/devboard/commit/966597de11456ec891c8bc64814bb46a3ef2734c))
* **S2.1:** Settings page CSS — 6 sections (Language/Theme/Team/Backups/Usage/Danger) ([5914a54](https://github.com/rdm9x/devboard/commit/5914a5430a8fedde90f08e12179fd56d0d26a960))
* **S2.1:** Settings page CSS — layout, sections, rows, danger zone ([59d93dc](https://github.com/rdm9x/devboard/commit/59d93dcc0530e61b17f3f95d3f6cbad0a79804ae))
* **S2.2:** output_locale backend — POST /api/team/start сохраняет locale, devboard-work.sh передаёт в claude ([6c7b14a](https://github.com/rdm9x/devboard/commit/6c7b14a9ddbfff065f443cf4928ad68197877859))
* **S2.3:** Role names localized in EN locale ([6ac86d0](https://github.com/rdm9x/devboard/commit/6ac86d0a36522d284965508e4266dbcd68955e36))
* **S2.4:** chat scroll-to-bottom on load + floating down-arrow button ([6e110dd](https://github.com/rdm9x/devboard/commit/6e110dd22f27ed9ba53fa51ff7cfcaa51fd0e5a5))
* **S5.2:** Statistics — lifetime task counters (done, created, rate, in-progress) ([36aac02](https://github.com/rdm9x/devboard/commit/36aac02ba3f1b031b806a3f20fe3e22103e042c4))
* **S5.3:** first-run wizard — language, expertise, theme steps ([199b016](https://github.com/rdm9x/devboard/commit/199b01669668610a79c4b34a561b69aa17d94cc0))
* **S5.4:** expand onboarding tour from 5 to 12 steps ([ac9c626](https://github.com/rdm9x/devboard/commit/ac9c62660fa9a78ecdbc653bad24d18e9a57fb4c))
* **S5.5:** add reader-mode i18n keys + dashboard tests ([fb10d5e](https://github.com/rdm9x/devboard/commit/fb10d5e64e39ebf92128870a43249cf2c625eb2f))
* **S5.5:** task modal reader-mode — TL;DR, steps, acceptance, option buttons ([3224122](https://github.com/rdm9x/devboard/commit/3224122f8a08b18f6066212f4cf3ed2be7e70ea0))
* **S6.4:** safety-net — MCP done → review с system-комментарием и чат-алертом ([e68003c](https://github.com/rdm9x/devboard/commit/e68003c6172a7577b12ece39339fc2479830d44d))
* **S8.1:** реализация ADR-003 на уровне БД — таблица departments ([32cc46c](https://github.com/rdm9x/devboard/commit/32cc46c514fe011b37fc01ebaa13fe1df8a82ac0))
* **S8.2:** department_id в MCP-tools + новые tools list/get/create_department ([d2203f2](https://github.com/rdm9x/devboard/commit/d2203f25a1d8f5e1c3d0ef75d5625f2e29a8d335))
* **S8.3:** REST API endpoints для departments + обратная совместимость tasks/chat ([eba88c1](https://github.com/rdm9x/devboard/commit/eba88c1f0d6e29f1bf8cf85fbaaa84366327812a))
* **team:** status показывает все активные роли + dropdown без Управляющего ([053b6ca](https://github.com/rdm9x/devboard/commit/053b6ca12c99470801b0ad8a7fd985d825e1eba1))
* **team:** главная кнопка запускает ВСЕ отделы, dropdown — точечно ([84a6ad9](https://github.com/rdm9x/devboard/commit/84a6ad9107514cd2cbb39b89ca73a398985abdbf))
* **v1.2:** Settings tab, dual-locale (UI+output), EN role names, chat UX ([e9900b1](https://github.com/rdm9x/devboard/commit/e9900b17336ee18d0de0d869334d2982b05d44b2))
* **v1.3:** Statistics tab, sidebar reorder, plain-language teamlead mode ([5ae4c5c](https://github.com/rdm9x/devboard/commit/5ae4c5c01fba21206bbe96b661a1a94770678d58))
* **v1.4:** final polish — i18n consistency, port unification, docs update ([3ae15f4](https://github.com/rdm9x/devboard/commit/3ae15f427e23c35b41ed4bfe5ce81f757aa705a9))
* **v1.5:** first-run wizard, expanded tour, task reader-mode, stats fixes ([cfd4b1e](https://github.com/rdm9x/devboard/commit/cfd4b1e123b81e4882eacb380cc4056bef5d8c43))
* **v1.5:** first-run wizard, expanded tour, task reader-mode, stats fixes ([2ef621d](https://github.com/rdm9x/devboard/commit/2ef621d00e43542ce8a103292757f25ee6bd06d7))
* **v1.6:** S6.6 — умные браузер-уведомления + секция Notifications в Settings ([15fea36](https://github.com/rdm9x/devboard/commit/15fea36891810fbdd5c3ec33e0c9f353a906d7c2))
* **v2.0.1:** cross-platform install reliability ([d021352](https://github.com/rdm9x/devboard/commit/d0213521fc8bb472288804f43e240145277508f5))
* **v2.0.2:** tutorial — Learn tab с 5 страницами + onboarding integration ([8924e37](https://github.com/rdm9x/devboard/commit/8924e37af5e12a6b74fe9cc7de9c5d17373c5e73))
* **v2.0:** Phase 2-4 — frontend departments + HR-pipeline + inter-department ([278feee](https://github.com/rdm9x/devboard/commit/278feeecb710dcb10ccbcf056a6bbb95fbbf995e))


### Fixed

* #modal-confirm → z-index: 250 (выше любого .modal: 100). ([fd09047](https://github.com/rdm9x/devboard/commit/fd0904779a8fcb90f13e443e29267f8f3473a18a))
* 3 мелких хвоста (тесты + prompt лидов + alerts в app.js) ([0338df7](https://github.com/rdm9x/devboard/commit/0338df7d7508708f2d19652f9baa165df4f35ec0))
* add repo root to sys.path and seed chat messages in demo endpoint ([c528ef8](https://github.com/rdm9x/devboard/commit/c528ef80961d26e72aba1b6a86c1787f72256fce))
* **ADR-009 Phase 1.7:** assignee dropdown + миграция тимлид→dev-lead + cleanup ([179b932](https://github.com/rdm9x/devboard/commit/179b9323f4167a4b194016e4b34b5b6e6b92b061))
* align router pick tests with counters key rename and label fix ([ba90a87](https://github.com/rdm9x/devboard/commit/ba90a87dd6591572e3f058213da41c8aafe9c720))
* **artifacts:** кнопка открытия файла зовёт /api/open-file вместо file:// ([45e8660](https://github.com/rdm9x/devboard/commit/45e8660e9d12b9c98369adc7b52ce8dfb1eac1af))
* **auto-mode:** _has_pending_work проверяет весь отдел, не только лида ([71004c0](https://github.com/rdm9x/devboard/commit/71004c0e4e7eac0f4e50cde568d019f7e44d9ea8))
* **auto-mode:** использовать smart-default role в _auto_monitor_loop ([0265754](https://github.com/rdm9x/devboard/commit/0265754887e7d39947051ab57e375ac91870a99d))
* **B3-1.5:** убрать hardcoded assignee='тимлид' — динамический lookup по dept_id ([886b4c6](https://github.com/rdm9x/devboard/commit/886b4c63fdbe5b9786811f36fcd3a5af046ab0bd))
* **card:** badge модели на карточке учитывает task.model_hint ([e9eb83e](https://github.com/rdm9x/devboard/commit/e9eb83e422bac21c350f17c555575ff6c8523d09))
* **chat:** live-refresh thread messages every 5s (no manual reload) ([675be7e](https://github.com/rdm9x/devboard/commit/675be7e61726bf991fa25716cd3f8c328b3621b3))
* **chat:** override legacy max-height:400px that pinned input mid-view ([9509b49](https://github.com/rdm9x/devboard/commit/9509b4965274aa1f6792300b9ba60140d841d9b8))
* **chat:** preserve dark theme on reload, fill the chat view to full height ([cefdf90](https://github.com/rdm9x/devboard/commit/cefdf90afb5db547223802ad1b16f9ae44c390fe))
* **chat:** use 'owner' as message author instead of unknown 'user' ([f35c8f3](https://github.com/rdm9x/devboard/commit/f35c8f328bde57c55260e49b720c208827bf8874))
* **coordination:** зависимости задач + передача контекста смежных отделов ([098ca5d](https://github.com/rdm9x/devboard/commit/098ca5dc044fdebc81ddf9ad3492fc20135100fe))
* correct Docker paths after cyrillics→latin rename; security hardening ([44e2619](https://github.com/rdm9x/devboard/commit/44e2619a584f8d3180bfbaa6017e4cfc23295abe))
* **critical:** _find_lead_for_department dev → dev-lead, не legacy 'тимлид' ([a8e4d04](https://github.com/rdm9x/devboard/commit/a8e4d04412c076e6058afd065239af64816e0428))
* **F1+F2 real:** assignee dropdown — реальная динамическая загрузка ролей ([6a1186d](https://github.com/rdm9x/devboard/commit/6a1186d89d5f745cb11b68aaa93fd917a842f23e))
* **F3-1.6:** default chat channel = Управляющий (__global__) по ADR-009 ([ca18f1a](https://github.com/rdm9x/devboard/commit/ca18f1a0fe99e0092b6ccd92ccc4fe272b1e67c6))
* **F4-1.6:** legacy «тимлид» → нейтральные метки в i18n и канбане ([c0b3c6c](https://github.com/rdm9x/devboard/commit/c0b3c6c7df8e702812abbf785f1344bbc660f2c3))
* hide '+ Department' button until HR-pipeline fix (issue [#0](https://github.com/rdm9x/devboard/issues/0)bead55b) ([220bf57](https://github.com/rdm9x/devboard/commit/220bf57564b41bb3fc280370c651171b641662ef))
* **HR-fix:** pipeline rewrite — stream-json reader + respawn for revise ([4d8057e](https://github.com/rdm9x/devboard/commit/4d8057e803ac9c121e1d04225ff5856d179f31df))
* **inbox:** отчёты не рендерились — забыл container.appendChild(item) ([812b032](https://github.com/rdm9x/devboard/commit/812b032e77a49f2df5a0c3f1ba41388c93989fab))
* **Phase 1.8 leftover:** pyproject.toml + sqlite3.Row .get() crash ([6073ad9](https://github.com/rdm9x/devboard/commit/6073ad98c1ce3b03010880a755920d7fea2993ca))
* **planning:** orphan recovery on orchestrator start; shorter lead timeout ([e9a5161](https://github.com/rdm9x/devboard/commit/e9a5161adc90ad92cdb84bb54556a90d50b4ef14))
* **planning:** owner sees lead replies inside planning threads ([9943000](https://github.com/rdm9x/devboard/commit/9943000fdd58889b93e2d6cf00afc7e03d36e064))
* **planning:** persist consolidated_proposal; chat-responder can't fake task creation ([45f17d7](https://github.com/rdm9x/devboard/commit/45f17d7928243e34edcbfc29c14241f092e476e8))
* **planning:** post a confirmation message into the active thread ([a81c017](https://github.com/rdm9x/devboard/commit/a81c0174cc8fa0e50614f9c90ec25d6152912402))
* **planning:** задачи привязываются к проекту — workspace/artifacts работают ([45bc517](https://github.com/rdm9x/devboard/commit/45bc517c56335d4ef7464dbecf512552fd2bcdf2))
* recognize 'owner' role in add_chat_message_to_thread() ([2a9694e](https://github.com/rdm9x/devboard/commit/2a9694eada40b2d1f869ea81098a5d5a40c0146c))
* remove duplicate api_open_folder route causing Flask AssertionError ([ee028e1](https://github.com/rdm9x/devboard/commit/ee028e1c6614629750c13c81a4b32421b047a04e))
* **report:** таймаут генерации отчёта 180→420с для больших проектов ([fd4d002](https://github.com/rdm9x/devboard/commit/fd4d00235fc4d6a889aebb84f85157f1b724e5fa))
* **roles:** запрет тимлиду коммитить файлы сторонних проектов в Devboard ([512d452](https://github.com/rdm9x/devboard/commit/512d452d618cfd4ae18dbb5b44d800dac4ad9f8b))
* **roles:** тимлид больше не отвечает «принял оба правила» на старые admin-сообщения ([4da1428](https://github.com/rdm9x/devboard/commit/4da1428a75130fc8c44c58fa980668aba72c668a))
* **roles:** тимлиду запрещены submit_result(new_status='done') и update_task(status='done') ([447970b](https://github.com/rdm9x/devboard/commit/447970b64660bafc30ae7d44f63cc3856d990d6d))
* **router:** B5 — model_hint пользователя переопределяет архитектурные labels ([2273525](https://github.com/rdm9x/devboard/commit/227352523643acdd9ed12b8fd46f20d423a179c2))
* **router:** filter enabled=False tasks in pick_from_db() ([62e9c4a](https://github.com/rdm9x/devboard/commit/62e9c4a960263c6dc0239b0200a89c4053491abf))
* **router:** model_hint — latest task wins (вместо max rank) ([2624566](https://github.com/rdm9x/devboard/commit/2624566d89ab03c0f8b349463279b93cf95de4cf))
* **router:** pick selects freshest model_hint, ignores rank — latest wins ([198fa30](https://github.com/rdm9x/devboard/commit/198fa3044f11d7ab00670adf8c04c33c2b53bda5))
* **routing:** use currentDepartment() — корректный localStorage ключ ([5a46070](https://github.com/rdm9x/devboard/commit/5a460700c9c702e430c547e97a00318dd7367720))
* **routing:** новая задача через UI идёт в current_department, не в dev ([fb10060](https://github.com/rdm9x/devboard/commit/fb100609467f3b3c9851a4d860b488eb2887f728))
* **S1.3-S1.5:** CSS scrollbar gap, column header z-index, i18n todo→В очереди ([de135ef](https://github.com/rdm9x/devboard/commit/de135ef7ff69a497021196fab92d3126d661cc57))
* **S1.4:** column header background opaque (var(--surface) не glass-bg-2) ([38c417c](https://github.com/rdm9x/devboard/commit/38c417c415c8bef1009ff148c59513300736925d))
* **S17.2:** ADR-006 prompt caching + model_hint end-to-end ([9f71bdd](https://github.com/rdm9x/devboard/commit/9f71bddb08eecaa9d1aeddab739d550b74974fca))
* **S17.3:** auto-mode restart — reader_thread guard before next session ([87cde8f](https://github.com/rdm9x/devboard/commit/87cde8f3aad14212b10f378a34dde6ddff5e5923))
* **S3.6:** demo idempotency toast — improved i18n key with reset hint ([57e05e7](https://github.com/rdm9x/devboard/commit/57e05e7d57f4207246144c9c70cdfe2b0e1c3f39))
* **S5.1:** statistics show all models including haiku ([0394072](https://github.com/rdm9x/devboard/commit/0394072b81ef856ee79ad2bd00016304233527cd))
* **S5.2:** move statsLifetime section before kpiGrid — lifetime counters shown first ([46eb4f5](https://github.com/rdm9x/devboard/commit/46eb4f55a4b200f5cba18d191b0fd50c7c8aed92))
* **S6.2:** acceptance checklist — grid layout 16+1fr с гарантированным выравниванием ([ce910f1](https://github.com/rdm9x/devboard/commit/ce910f1107a27f9399b9a24609390bbaa1f13805))
* **S6.2:** acceptance checklist — выравнивание чекбокса и текста на одной линии ([be8f754](https://github.com/rdm9x/devboard/commit/be8f75401a141bbdfe141cd11d73da27303c0c79))
* **S6.2:** removed duplicate .acceptance-item legacy override (was forcing 14px + cursor:default) ([91b32a8](https://github.com/rdm9x/devboard/commit/91b32a856fb009e869a07f554f4f90f6bb06daad))
* **S6.2:** tighten reader-mode typescale — TL;DR 18→14px, labels 11→10px ([c9b064e](https://github.com/rdm9x/devboard/commit/c9b064e97ce99cfa36bfffc08644d2c70d904bfc))
* **S6.5:** add Cyrillic slug→i18n key mapping for Roles table display names ([26fee23](https://github.com/rdm9x/devboard/commit/26fee23757c9e960dbdbb4f3f79b6ef7c37dee4a))
* **S6.5:** убрать дубликат slug в Roles tab — оставить только display name ([0993fed](https://github.com/rdm9x/devboard/commit/0993fed30e8bd011fb477c4f044a4284850dd4c6))
* **security:** isolate Devboard agents from external systems (Bitrix24) ([056f990](https://github.com/rdm9x/devboard/commit/056f990e28e89d79152de10170b2cc25439aab74))
* **TASK_PROMPT:** лид не ждёт сигнала — делегирует todo задачи специалистов сам ([77d60f0](https://github.com/rdm9x/devboard/commit/77d60f0f370c3e8647d923ac731b0e889be5ec6d))
* **TASK_PROMPT:** лид ставит wip ПЕРЕД делегированием — видимый прогресс ([d391675](https://github.com/rdm9x/devboard/commit/d391675195f587bb0fff44b97edeb1f541ab1799))
* **tasks:** «Доработать» возвращает в todo, а не в wip ([211fd76](https://github.com/rdm9x/devboard/commit/211fd764113601b5c4f799164dc5089d6a3535c2))
* **team:** «Остановить» убивает всю process group, не только родителя ([4fba79d](https://github.com/rdm9x/devboard/commit/4fba79d7c21c07df77c9eb72f152b7a138b3e59d))
* **team/start:** smart-default — запускаем lead с самой свежей todo задачей ([e715002](https://github.com/rdm9x/devboard/commit/e715002eea16ccec9f9f3d7f46d4fe2041bf8fae))
* **team:** subprocess моментально exit'ил — slug роли + env-strip ([b88e99c](https://github.com/rdm9x/devboard/commit/b88e99c50b7edc87601bf2688c0a0bd46799a76d))
* **test:** fix artifacts API tests import path ([e485237](https://github.com/rdm9x/devboard/commit/e48523735e51f5fb1c15752c24a048de8058166c))
* **test:** test_api_team_start_happy под B1 default role + сохранён marketing E2E artifact ([14c4d80](https://github.com/rdm9x/devboard/commit/14c4d80c547d67beff8f84c3edd1337124a06183))
* **ui:** confirm-диалог удаления — z-index выше карточки задачи ([fd09047](https://github.com/rdm9x/devboard/commit/fd0904779a8fcb90f13e443e29267f8f3473a18a))
* update default sonnet model to claude-sonnet-4-6 in router ([2b075e2](https://github.com/rdm9x/devboard/commit/2b075e25cf8c7f4d869f22ccaef3e6ac81458dd4))
* update llm_factory tests — OllamaProvider now implemented (E6.5) ([5402107](https://github.com/rdm9x/devboard/commit/540210787b668a37b28eafaa1abdda700960e1c8))
* Update test assertions for _has_pending_work_for_role refactoring ([b4786f4](https://github.com/rdm9x/devboard/commit/b4786f4c1861111b7dc65da739fa01133f8bd04f))
* **urls:** repo path github.com/devboard/devboard → github.com/rdm9x/devboard ([49841f9](https://github.com/rdm9x/devboard/commit/49841f9a215126b8a9b7054fb46e3078d0b07add))
* use EN fallbacks in tour.js to prevent RU flash on EN browser ([011ce95](https://github.com/rdm9x/devboard/commit/011ce95caa2d75cb6cdb234fc4b0e16cd04b7312))
* **v1.6:** Statistics layout regression + task reader-mode v2 (полная переделка) ([b236bae](https://github.com/rdm9x/devboard/commit/b236baeb0885a314c283291af5b5a736af719aba))
* **v2.0.1+:** UTF-8 encoding + line endings + devboard-work locale/expertise ([cf23fbe](https://github.com/rdm9x/devboard/commit/cf23fbef6a0559efedd9157922ba2af1fb325b3e))
* **v2.1.2:** token optim verified + auto-mode restart bug fix ([1278d56](https://github.com/rdm9x/devboard/commit/1278d565a23a5b85a53da3ca112fa696c52bb31a))
* **windows:** UTF-8 encoding для PowerShell и subprocess — лечим иероглифы ([e0bc4dd](https://github.com/rdm9x/devboard/commit/e0bc4ddc2567c8afcb5cb79518cfe06bb24a4d10))
* динамическая валидация ролей + onboarding skipped flag ([614e690](https://github.com/rdm9x/devboard/commit/614e69030b1147564b9945500d0fbc82268995e5))
* добавить pyyaml в dependencies dashboard (roles/validator.py) ([ffc7795](https://github.com/rdm9x/devboard/commit/ffc77955ef17704ef020d4284a9e360d2a514930))
* чип модели на карточках учитывает модель роли-исполнителя из БД ([2971c18](https://github.com/rdm9x/devboard/commit/2971c18606ae70dae606152b3525d805c4541c00))


### Changed

* rename env vars PRIDE_* to DEVBOARD_* ([9d39cc1](https://github.com/rdm9x/devboard/commit/9d39cc1cb5b6392cd1f8dd31ed1836c0269ee07c))
* rename MCP server pride-tasks to devboard-tasks ([e883552](https://github.com/rdm9x/devboard/commit/e8835525805a6cbddc07327a9a4f801c039dd54b))
* rename pride_tasks module to devboard_tasks ([992c5c9](https://github.com/rdm9x/devboard/commit/992c5c9c0ca313443f615f985622cc23e46ac904))

## [2.1.2] - 2026-05-25

Token optimisation verified + auto-mode reliability fix.

### Added
- **ADR-006 token-opt audit** (S17.1): `docs/qa/token-opt-audit-2026-05.md` — checklist of 4 quick-wins; 2 of 4 confirmed applied, 2 gaps identified and fixed in S17.2.
- **Prompt caching enabled** (S17.2): `ANTHROPIC_PROMPT_CACHING_ENABLED=1` uncommented in `devboard-work.sh`; added to `devboard-work.ps1`. Expected −30% input tokens on repeated sessions.
- **model_hint end-to-end** (S17.2): UI dropdown (auto/haiku/sonnet/opus) in new-task modal; `app.js` passes value to API; `router.py` `pick()` uses hint as model override. 8 new tests in `test_router.py`.

### Fixed
- **Auto-mode restart race condition** (S17.3): `_auto_monitor_loop` was launching a new session before `_stream_reader` released the SQLite write-lock, causing `claude` to time out after 90 s with `is_error=1`. Fix: `reader_thread` guard in `_auto_can_start` blocks restart until cleanup completes. 4 new tests in `test_team_process.py`.

## [2.1.1] - 2026-05-25

Tutorial deep dive — full learning content for non-technical users.

### Added
- **Tutorial Intro expanded** (S16.1): `learn.page.intro.body` 934→4271 chars — concept explanation vs ChatGPT/Copilot, 7-role guide with LLM model rationale, ASCII task lifecycle diagram, "what devboard cannot do" section.
- **Tutorial Tasks expanded** (S16.1): `learn.page.tasks.body` 1548→8696 chars — 5 good/bad example pairs (UI fix, new feature, docs, business logic, analytics) with detailed breakdowns + "what to do when a task stalls" section.
- **Tutorial Departments+HR expanded** (S16.2): `departments.body` +4524 chars (7 department scenarios, lifecycle, SVG diagram), `hr.body` +5353 chars (6-step state machine, 3 full chat transcripts, 5 templates, troubleshooting).
- **Cmd+K global search** (S16.3): keyboard listener `Cmd/Ctrl+K` → focus `#search`; `?`/`Cmd+/` → shortcuts overlay; `Esc` closes modals. `shortcuts.body` expanded to 1584 chars with full shortcut table.

## [2.0.0] - 2026-05-23

First multi-team release of **devboard**. The single-team kanban becomes a platform of AI departments, each with its own roles, kanban, and chat. Existing v1.x installs upgrade automatically via an idempotent migration that moves every existing task, role, and chat message into the default `dev` department. Three accepted ADRs lock in the design.

### Added

- **Departments (ADR-003).** New `departments` table; `department_id` foreign key on `tasks`, `roles`, and `chat_messages`. `NULL` is reserved for global rows — HR/owner roles and the inter-department audit channel. Indexes `(department_id, status)` keep per-department kanban queries cheap. Migration script `scripts/migrate_v2_departments.py` is atomic, idempotent, and supports `--rollback`. Three new MCP tools (`list_departments`, `get_department`, `create_department`); existing tools (`create_task`, `list_tasks`, `chat_post`, `chat_recent`) accept an optional `department_id` (default `'dev'`). REST endpoints: `GET /api/departments`, `GET /api/departments/<id>`, `POST /api/departments`, `PATCH /api/departments/<id>/archive`. `GET /api/tasks` and `GET /api/chat` honour `?department=<id>` and fall back to `dev`.
- **HR role + 5 department templates (ADR-004).** New global role `roles/hr.md` (`department_id = NULL`) — a meta-agent that creates departments from YAML templates via a chat-driven edit loop with the owner. Five MVP templates live in `templates/departments/`: `marketing-v1`, `design-v1`, `sales-v1`, `support-v1`, `operations-v1`. HR pipeline state machine (`idle → hr_planning → awaiting_owner_review → hr_revising → hr_activating → active`) with hard limits: max 8 roles per department, max 5 edit iterations, whitelisted models only, no destructive-labelled roles. Every generated role file carries `extras.hr_meta` (template_id, hr_session_id, customizations) for auditable history.
- **Inter-department workflow (ADR-005).** New columns `tasks.requester_department_id` and `tasks.requester_role_slug`. Only a department Lead (or owner) can create cross-department tasks via `POST /api/departments/<target>/tasks`; rank-and-file roles are blocked at both the REST layer and the MCP layer. The receiving Lead may **take** or **counter-propose** — there is no `Decline`. `P1`/`P2` priorities and `requires_budget`/`destructive` labels escalate to the owner's Inbox. Global append-only `inter_department_events` table with SQL triggers that reject UPDATE/DELETE. Capacity badges in the sidebar (`N in work, M in queue`), position-preview on cross-task creation; no ETA promises. Owner has two escape hatches: `priority-bump` and `admin-override`. Rate limit: 10 `P3` cross-tasks per 24h per (requester, target) pair.

### Migration

Upgrade from any v1.x to v2.0.0 is **automatic and idempotent**:

- The dashboard runs `scripts/migrate_v2_departments.py` on first start. It creates the `departments` table, inserts the default row `id='dev'`, adds the `department_id` column to `tasks`/`roles`/`chat_messages`, and backfills every existing row to `'dev'`. Global roles (`hr`, `owner`, `user`, `пользователь`) keep `department_id = NULL`.
- The migration is wrapped in a single transaction. If any step fails the database is left on v1.x.
- A `--rollback` mode restores from the auto-created `*.pre-v2.bak` backup.
- The v1.6 → v2.0 path is covered end-to-end by the smoke test `mcp_server/tests/test_v2_migration_smoke.py` (replays the anonymised fixture `tests/fixtures/v1.6_snapshot.db`, asserts no row counts change, asserts the second and third runs are no-ops).

See [`docs/migration-v2.md`](docs/migration-v2.md) for the full upgrade guide.

## [2.1.0] - 2026-05-24

Night-batch release: Windows reliability + tutorial + token optimization.
Includes all of v2.0.1, v2.0.2, and v2.1.0 changes landed via automated sprints S13–S15.

### Added
- **Token optimization (ADR-006)** (S15.1/S15.2): `chat_recent` default limit 50→10; `model_hint` optional field on tasks (DB column + MCP tools `create_task`/`update_task`/`list_tasks`/`get_task`); `AGENTS.md` split into core (~70 lines) + `docs/AGENTS_EXTENDED.md` (full reference); `ANTHROPIC_PROMPT_CACHING_ENABLED` comment in `devboard-work.sh`. Expected: −30–50% tokens/session (baseline $2.92 → target $1.80).
- **Tutorial вкладка /learn** — see v2.0.2 below.
- **Docker-first + Windows reliability** — see v2.0.1 below.

### Fixed
- `scripts/migrate_s15_model_hint.py` — idempotent standalone migration for existing DBs.

## [2.0.2] - 2026-05-24 (tutorial)

### Added
- **Tutorial вкладка /learn** (S14.1): двухколоночный layout (TOC 200px + long-read article), 5 страниц, localStorage для текущей страницы, re-render при смене локали, a11y + light/dark.
- **Контент: Введение + Как формулировать задачи** (S14.2): метафора виртуальных сотрудников, 5-шаговый workflow, ограничения; примеры хороших/плохих задач с `.example-good` / `.example-bad` стилизацией; EN + RU.
- **Контент: Отделы + HR** (S14.3): когда нужен отдел, как создать, шаблоны; бриф для HR с примерами good/bad, edit-loop; EN + RU.
- **Страница Shortcuts + wizard интеграция** (S14.4): таблица горячих клавиш (`Esc`, `Ctrl/Cmd+Enter`, `Ctrl/Cmd+K` coming soon); кнопка «Открыть обучение» в last step first-run wizard; кнопка Replay tutorial в Settings.

## [2.0.1] - 2026-05-24 (windows reliability)

### Added
- **Docker-first Quick Start** (S13.1): `docker compose up` инструкция в README.md, README.ru.md, README_WINDOWS.md как primary path; порт исправлен 5000→4999 в Dockerfile EXPOSE/HEALTHCHECK и docker-compose.yml ports/healthcheck.
- **Windows diagnostic mode** (S13.2): `"Запустить devboard.bat" --diag` — печатает Python/OS/encoding/venv/ExecutionPolicy без запуска дашборда.
- **Cross-platform troubleshooting guide** (S13.3): `docs/INSTALL_TROUBLESHOOTING.md` — гайд по типичным ошибкам install на Windows/macOS/Linux.

### Fixed
- **setup.py Windows UTF-8** (S13.2): `sys.stdout.reconfigure(encoding="utf-8")` под `IS_WINDOWS` guard; `PYTHONIOENCODING=utf-8` + `PYTHONUTF8=1` propagated во все дочерние subprocess через `run()` helper.
- **ExecutionPolicy** (S13.2): батник автоматически делает `Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass` при запуске.
- **Error message Python not found** (S13.2): добавлена ссылка на python.org/downloads с явной инструкцией про галочку "Add Python 3.x to PATH".
- **CRLF protection** (S13.3): `.gitattributes` — `*.sh eol=lf`, `*.ps1 eol=crlf`, `*.py eol=lf`; устраняет `bad interpreter ^M` при клонировании на Windows с `autocrlf=true`.
- **HR subprocess encoding** (S13.3): `dashboard/hr.py::spawn_hr_subprocess` — добавлены `encoding="utf-8"`, `errors="replace"` и `env["PYTHONUTF8"]="1"`; кириллица в HR-сессиях на Windows больше не превращается в мусор.
- **devboard-start.ps1 hardcoded port** (S13.3): заменён `5000` на `$env:PRIDE_DASHBOARD_PORT` (по умолчанию `4999`) в сообщении «already running».
- **devboard-work.ps1 feature parity** (S13.3): добавлены output_locale (`data/.output_locale` → `LANG_PROMPT`), user_expertise (`data/.user_expertise` → `DEVBOARD_USER_EXPERTISE`), ветка `non-tech` с `$ExpertisePrompt`; паритет с `.sh`-версией достигнут.

## [Unreleased] / v2.0-alpha.1 (departments backend)

### Added

- **Departments data model** (S8.1, ADR-003): new `departments` table in SQLite; `department_id` column added to `tasks`, `roles`, `chat_messages`; `ensure_dev_department()` migrates all existing data to the default `dev` department; `scripts/migrate_v2_departments.py` with idempotent run and `--rollback` support.
- **MCP-tools: department support** (S8.2): `create_task`, `list_tasks`, `chat_post`, `chat_recent` accept optional `department_id` (default `'dev'`); three new tools — `list_departments`, `get_department`, `create_department`.
- **REST API: /api/departments** (S8.3): `GET /api/departments`, `GET /api/departments/<id>`, `POST /api/departments`, `PATCH /api/departments/<id>/archive`; `GET /api/tasks` and `GET /api/chat` now accept `?department=<id>` with backward-compatible fallback to `'dev'`.

## [Unreleased] / v1.6 (local)

### Fixed

- **Statistics layout regression** (S6.1): restored original KPI grid layout broken by S5.2. Lifetime counters moved into a dedicated `#statsLifetime` section at the top with new `.lifetime-counter-grid` / `.lifetime-counter-card` classes (4 cards in a row, 2×2 on ≤768 px, colour-coded: green / blue / accent / yellow). Existing sections (models, roles, heatmap) unchanged.
- **Task modal reader-mode v2** (S6.2): complete rewrite of task detail overlay. Shows TL;DR prominently (18 px, accent border-left), inline option-buttons for numbered choices (click posts a comment), acceptance checklist with localStorage state, and a collapsible "Technical details" section. Fallback to plain markdown for tasks without TL;DR. 6 i18n keys added. New `test_task_parser.py` (6 tests).

## [Unreleased] / v1.5 (local)

### Added

- **First-run wizard** (S5.3): full-screen overlay on first open — 4 steps (language, expertise level, theme, done). Saves `ui_locale`, `output_locale`, `user_expertise`, `devboard-theme` to localStorage. Launches onboarding tour automatically after completion. Settings → Danger zone: reset/restart buttons.
- **Expanded onboarding tour** (S5.4): 12 steps covering all 6 nav-items (Board, Inbox, Statistics, Roles, Archive, Settings), topbar controls (Start, Auto mode), and chat panel. Replaces the previous 5-step tour.
- **Task reader-mode** (S5.5): task modal now shows structured view — large TL;DR, steps checklist, acceptance checklist, and inline answer buttons for option questions. Raw markdown collapsed under "Technical details" toggle. Backend: `GET /api/tasks/<id>/parsed` endpoint.
- **Statistics lifetime counters** (S5.2): 4 large KPI cards (tasks done, total created, completion rate %, in progress) always shown across full history including archived tasks. Count-up animation on render.

### Fixed

- **Statistics haiku model** (S5.1): `COALESCE(SUM(total_cost_usd), 0.0)` prevents `TypeError` crash in stats endpoint when haiku sessions have `NULL` cost — all models including `claude-haiku-4-5-20251001` now appear in the models breakdown.
- **Inbox nav label** (S5.7): RU sidebar nav label «Inbox» → «На столе»; EN unchanged.
- **Inbox group height** (S5.7): `.inbox-groups { align-items: start }` — each group sizes to its own content instead of stretching to match the tallest group.

## [Unreleased] / v1.4 (local)

### Added

- **i18n coverage** (S4.1): wrapped ~28 hardcoded Russian `title`/`aria-label`/`placeholder` attributes in `kanban.html` and `app.js` with `data-i18n-attr` — all tooltips now follow UI locale.
- **`name_en` in example roles** (S4.8): all 6 `roles/examples/*.md` now have `name_en` and `slug` frontmatter fields; passes role validator.
- **AGENTS.md caveats** (S4.6): added 4 entries to "Частые подводные камни" — Settings, Statistics, i18n public API, plain-language mode.
- **README features** (S4.4): `README.md` and `README.ru.md` now mention Settings tab, Statistics tab, dual-language i18n, and plain-language mode.

### Changed

- **Port unified to 4999** (S4.3): `dashboard/app.py` default, `.env.example`, `devboard-start.sh`, `README.md`, `README.ru.md`, `CONTRIBUTING.md`, `DEPLOYMENT.md`, `README_WINDOWS.md`, `setup.py`, `docs/launch/devto-post.md`.
- **Error responses** (S4.2): backend (`app.py`, `tools.py`) now returns both `{"причина": …, "reason": …}` dual-key; frontend reads `err.причина || err.reason`.
- **`ARCHITECTURE.md`** (S4.5): ADR-002 → Accepted, new endpoints (`/api/settings/static-info`, `/api/stats/aggregates`, `/api/demo`), `name_en` mentioned in roles frontmatter section.

### Fixed

- **Stale path refs** (S4.7): removed all `/D.AI/команда` from docstrings/comments in `app.py`, `server.py`, `db.py`, `devboard-work.sh`, `roles/*.md`, `approval_gates.md`.
- **Orphaned TODO** (S4.9): removed `TODO(E2.3)` comment from `locale-switcher.js` — `i18n-loader.js` (E2.3) is long done.

## [Unreleased] / v1.3 (local)

### Added

- **Statistics tab** (S3.2): new sidebar entry with 5 sections — KPI cards (sessions, turns, cost, files, lines, hours), model breakdown table with inline bars, role activity bars, 24h hourly heatmap, top achievements. Zero external dependencies; vanilla CSS animations. Backend: `GET /api/stats/aggregates?range=today|24h|week|all` with 60s cache.
- **Sidebar reorder** (S3.3): Board → Inbox → Statistics → Roles → Archive → Settings. Default view on first load is Board; `last_view` persisted in localStorage.
- **Plain-language mode** (S3.4): `user_expertise` toggle in Settings (Developer / Non-developer). Stored in `localStorage`; sent to `POST /api/team/start`; saved in `data/.user_expertise`; read by `commands/devboard-work.sh` which adds a `--append-system-prompt` block for non-technical users.

### Removed

- **Usage section from Settings** (S3.1): moved to the dedicated Statistics tab. Settings now has 5 sections (Language / Theme / Team / Backups / Danger zone).

## [Unreleased] / v1.2 (local)

### Added

- **Settings page** (S2.1): full settings tab with 6 sections — Language, Theme, Team, Backups, Usage, Danger zone. Replaces the read-only "Status" sidebar item.
- **Dual-axis i18n** (S2.2): separate `ui_locale` (interface language) and `output_locale` (team chat/task language). Output locale stored in `data/.output_locale` and injected into claude via `--append-system-prompt`.
- **EN role names** (S2.3): roles display as `Team Lead / Backend / QA / Architect / Frontend / DevOps / Tech Writer` when `ui_locale=en`. Resolved via `ROLE_DISPLAY` map in `app.js`; `name_en` frontmatter added to all `roles/*.md`.
- **Chat UX** (S2.4): auto-scroll to bottom on load; floating ⬇ button with unread badge when scrolled up; auto-scroll on new messages if already at bottom.

### Fixed

- `.gitignore`: added `data/.env.local` and `data/.output_locale` to prevent accidental credential/runtime-state commits.

## [1.1.0] - 2026-05-22

### Changed

- Product renamed: `pride-team` → `devboard` across the entire repo (sidebar brand, README, packages, configs, launcher scripts).
- Owner role renamed: `пользователь`/`пользователь` → `пользователь`/`user` in code, i18n, tests, and DB migration script (`scripts/migrate_user_to_user.py`) for open-source friendliness.
- i18n RU: todo column label "К работе" → "В очереди".

### Fixed

- CSS: scrollbar in kanban columns no longer overlaps card borders (`padding-right: 8px; scrollbar-gutter: stable` on `.column .cards`).
- CSS: column header no longer hidden by top-card hover transform (`position: sticky; z-index: 2` on `.column h2`).

## [1.0.0] - Unreleased

First public release. Open-source baseline of devboard — a local kanban driven by a small fleet of AI role-bots (Team Lead, Backend, QA, and optional specialists).

### Added

- MIT `LICENSE` and `NOTICE` files at the repository root.
- Top-level `.gitignore` covering `.env`, virtualenvs, build artifacts, IDE files, and SQLite WAL/SHM siblings.
- `gitleaks` audit run on the full git history; no secrets leaked.
- English UI with runtime i18n switcher backed by `static/i18n/{ru,en}.json`.
- Onboarding tour: 5-step first-run popovers across kanban, task detail, run-team, approvals, and chat.
- Empty-state illustrations and copy for empty kanban columns and chat thread.
- Demo mode: one-click seeding of a sample task graph for first-time exploration.
- `README.md` rewritten as the public landing page (quickstart, screenshots placeholder, roles, configuration, architecture-at-a-glance).
- `CONTRIBUTING.md` covering setup, code style, branching, adding roles and LLM providers, testing, and PR process.
- `ARCHITECTURE.md` with component diagram, data model, and three end-to-end flow diagrams (create task, run team, approval gate).
- `CHANGELOG.md` (this file) in Keep a Changelog 1.1.0 format.
- Issue and pull request templates under `.github/`.
- `Dockerfile` and `docker-compose.yml` for VPS deployment; image runs as a non-root user.
- GitHub Actions CI workflow: `ruff check`, `mypy`, and `pytest` on every push and pull request.
- Multi-LLM support via `LLMProvider` abstraction with Claude, OpenAI, and Ollama backends (see [ADR-001](docs/adr/0001-llm-provider.md)).
- Per-role provider/model selection through YAML frontmatter (`llm`, `model`, `temperature`, `max_tokens`) in `roles/*.md` (see [ADR-002](docs/adr/0002-role-format.md)).
- Configurable roles: load any `roles/<name>.md` without code changes; strict frontmatter validation with clear `RoleConfigError` messages.
- Role marketplace v0: import a role from a remote URL into the local `roles/` directory.
- UI for adding, editing, and deleting roles from the dashboard *Roles* page.
- Five example community roles shipped under `roles/examples/`: Product Manager, Designer, Security Auditor, Code Reviewer, Data Analyst.
- Per-role MCP tool allowlist (`tools:` field) — declarative allowlist enforced at subagent spawn.
- Unit and integration test suites under `mcp_сервер/tests/`, `дашборд/tests/`, and `smoke/tests/`.
- Coverage reporting via `pytest-cov`; baseline coverage threshold enforced in CI.
- `.pre-commit-config.yaml` wiring `ruff`, `mypy`, and `gitleaks` to run before every commit.
- Stress test for the kanban write path — eight concurrent writers against `fcntl` + `BEGIN IMMEDIATE`, asserts no lost updates and no `database is locked` errors.

### Changed

- Renamed Cyrillic source folders to Latin equivalents for cross-platform tooling:
  `роли/` → `roles/`, `дашборд/` → `dashboard/`, `команды/` → `commands/`, `мcp_сервер/` → `mcp_server/`.
- Launcher scripts renamed to Latin: `devboard-start.sh`, `devboard-work.sh`, and their Windows `.ps1`/`.bat` counterparts.
- Internal module imports and `pyproject.toml` package paths updated to match the new folder names.
- Default UI language is now English; Russian remains available via the in-app language switcher.
- Team Lead invocation goes through `create_provider()` instead of a hard-coded `claude --print` call.
- Role files now require explicit `schema_version: 1` frontmatter; existing roles migrated.
- Dashboard *Roles* page shows the new `name` / `description` / `llm` / `model` fields and the per-role tool allowlist.

### Fixed

- Race condition in `_atomic_modify` where a stale `fcntl` lock could persist after an abnormal exit; lock file is now cleaned up on startup.
- Stream-json parser no longer crashes on partial UTF-8 fragments split across SSE chunks.
- Backup thread now exits cleanly on `SIGTERM`; previously could leave a half-written `.backup` snapshot.

### Security

- `gitleaks` audit run against the full git history before the public release — no secrets leaked.
- `.env`, `.env.*`, and `*.key` patterns added to `.gitignore`.
- Docker image runs as a non-root user (`uid 1000`) with a read-only root filesystem where possible.
- Approval-gated operations (`git push`, `ssh`, `systemctl restart`, destructive shell commands) cannot be executed by subagents directly; they must go through the human approval flow documented in `approval_gates.md`.
- CI runs `gitleaks` and `pip-audit` on every pull request.
- All third-party LLM SDKs are imported lazily inside their provider modules so a user who does not need a given provider is not forced to install its dependencies.

<!--
When releasing:
1. Replace [Unreleased] with [X.Y.Z] - YYYY-MM-DD
2. Add an empty [Unreleased] section at the top with Added/Changed/Fixed/Security headings
3. Bump the version in setup.py / pyproject.toml
4. Create an annotated git tag vX.Y.Z and push it
5. Cut a GitHub release using the new section as the release notes body
-->
