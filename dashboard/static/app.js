(function () {
  "use strict";

  const REFRESH_MS = 3000;
  const STATUSES = ["todo", "wip", "needs_approval", "review", "done"];

  // ===================== Role display names (i18n) =====================
  const ROLE_DISPLAY = {
    // Cyrillic DB keys
    "тимлид":      { slug: "teamlead",   en: "Team Lead",   ru: "тимлид" },
    "бэкенд":      { slug: "backend",    en: "Backend",     ru: "бэкенд" },
    "qa":          { slug: "qa",         en: "QA",          ru: "qa" },
    "архитектор":  { slug: "architect",  en: "Architect",   ru: "архитектор" },
    "frontend":    { slug: "frontend",   en: "Frontend",    ru: "frontend" },
    "devops":      { slug: "devops",     en: "DevOps",      ru: "devops" },
    "техписатель": { slug: "techwriter", en: "Tech Writer", ru: "техписатель" },
    "пользователь":{ slug: "user",       en: "User",        ru: "пользователь" },
    "Управляющий": { slug: "managing-director", en: "Managing Director", ru: "Управляющий" },
    // Slug aliases (for chat authors and any slug-based references)
    "teamlead":   { slug: "teamlead",   en: "Team Lead",   ru: "тимлид" },
    "backend":    { slug: "backend",    en: "Backend",     ru: "бэкенд" },
    "architect":  { slug: "architect",  en: "Architect",   ru: "архитектор" },
    "techwriter": { slug: "techwriter", en: "Tech Writer", ru: "техписатель" },
    "user":       { slug: "user",       en: "User",        ru: "пользователь" },
    // ADR-009: новые slug'и для иерархии (Управляющий + lead отдела).
    // dev-lead — переименованный 'teamlead' (см. roles/dev/lead.md); старый
    // 'тимлид'/'teamlead' оставлены выше для backward-compat сообщений в БД.
    "managing-director": { slug: "managing-director", en: "Managing Director", ru: "Управляющий" },
    "dev-lead":          { slug: "dev-lead",          en: "Dev Lead",          ru: "Лид разработки" },
    // F1-1.5: маркетинговые роли
    "hr":                { slug: "hr",                en: "HR",                ru: "HR" },
    "copywriter":        { slug: "copywriter",        en: "Copywriter",        ru: "Копирайтер" },
    "brand-manager":     { slug: "brand-manager",     en: "Brand Manager",     ru: "Бренд-менеджер" },
    "seo-specialist":    { slug: "seo-specialist",    en: "SEO Specialist",    ru: "SEO-специалист" },
    "marketing-analyst": { slug: "marketing-analyst", en: "Marketing Analyst", ru: "Маркетинг-аналитик" },
    "marketing-lead":    { slug: "marketing-lead",    en: "Marketing Lead",    ru: "Маркетинг-лид" },
  };

  function displayRole(name) {
    if (!name) return name;
    const entry = ROLE_DISPLAY[name];
    if (!entry) return name;
    return (window.getLocale && window.getLocale() === "en") ? entry.en : entry.ru;
  }

  const $ = (sel) => document.querySelector(sel);
  const $$ = (sel) => Array.from(document.querySelectorAll(sel));

  // ===================== Custom prompt / confirm (вместо нативных) =====================

  function customPrompt(title, opts = {}) {
    return new Promise((resolve) => {
      const dlg = $("#modal-prompt");
      $("#prompt-title").textContent = title;
      const input = $("#prompt-input");
      input.value = opts.default || "";
      input.placeholder = opts.placeholder || "";
      dlg.hidden = false;
      setTimeout(() => input.focus(), 50);
      const okBtn = dlg.querySelector("[data-prompt-ok]");
      const cancelBtns = dlg.querySelectorAll("[data-prompt-cancel]");

      function cleanup() {
        dlg.hidden = true;
        okBtn.removeEventListener("click", onOk);
        cancelBtns.forEach((b) => b.removeEventListener("click", onCancel));
        input.removeEventListener("keydown", onKey);
      }
      function onOk() { const v = input.value; cleanup(); resolve(v); }
      function onCancel() { cleanup(); resolve(null); }
      function onKey(e) {
        if (e.key === "Enter" && (e.metaKey || e.ctrlKey)) onOk();
        if (e.key === "Escape") onCancel();
      }
      okBtn.addEventListener("click", onOk);
      cancelBtns.forEach((b) => b.addEventListener("click", onCancel));
      input.addEventListener("keydown", onKey);
    });
  }

  function customConfirm(text) {
    return new Promise((resolve) => {
      const dlg = $("#modal-confirm");
      $("#confirm-text").textContent = text;
      dlg.hidden = false;
      const okBtn = dlg.querySelector("[data-confirm-ok]");
      const cancelBtns = dlg.querySelectorAll("[data-confirm-cancel]");

      function cleanup() {
        dlg.hidden = true;
        okBtn.removeEventListener("click", onOk);
        cancelBtns.forEach((b) => b.removeEventListener("click", onCancel));
      }
      function onOk() { cleanup(); resolve(true); }
      function onCancel() { cleanup(); resolve(false); }
      okBtn.addEventListener("click", onOk);
      cancelBtns.forEach((b) => b.addEventListener("click", onCancel));
    });
  }

  // ===================== Theme toggle =====================
  function applyTheme(theme) {
    document.documentElement.setAttribute("data-theme", theme);
    localStorage.setItem("devboard-theme", theme);
    $$("[data-theme-set]").forEach((b) =>
      b.classList.toggle("active", b.dataset.themeSet === theme)
    );
  }
  const savedTheme = localStorage.getItem("devboard-theme") || "dark";
  applyTheme(savedTheme);
  $$("[data-theme-set]").forEach((b) =>
    b.addEventListener("click", () => applyTheme(b.dataset.themeSet))
  );

  // ===================== Chat collapse =====================
  function applyChatCollapsed(collapsed) {
    document.querySelector(".app").classList.toggle("chat-collapsed", collapsed);
    document.getElementById("chat").classList.toggle("collapsed", collapsed);
    localStorage.setItem("devboard-chat-collapsed", collapsed ? "1" : "0");
  }
  applyChatCollapsed(localStorage.getItem("devboard-chat-collapsed") === "1");
  document.getElementById("chat-collapse").addEventListener("click", () => applyChatCollapsed(true));
  document.getElementById("chat-expand-rail").addEventListener("click", () => {
    applyChatCollapsed(false);
    markChatRead();
    scrollToBottom(false);
  });

  // ===================== Views & navigation =====================

  const _defaultView = "board";
  let currentView = localStorage.getItem("last_view") || _defaultView;

  function switchView(name) {
    currentView = name;
    localStorage.setItem("last_view", name);
    $$(".nav-item").forEach((b) => b.classList.toggle("active", b.dataset.view === name));
    $$(".view").forEach((v) => (v.hidden = v.dataset.view !== name));
    if (name === "archive") loadArchive();
    if (name === "settings") loadSettings();
    if (name === "roles") loadRoles();
    if (name === "stats") loadStats();
    if (name === "learn") loadLearn();
  }
  // Apply initial view from localStorage
  switchView(currentView);
  $$(".nav-item").forEach((b) =>
    b.addEventListener("click", () => switchView(b.dataset.view)),
  );

  // ===================== Departments (S9.1) =====================
  // Storage key — выбранный пользователем отдел; fallback на 'dev' (default).
  const DEPT_STORAGE_KEY = "devboard-current-department";
  let _departmentsCache = [];

  function currentDepartment() {
    try {
      return localStorage.getItem(DEPT_STORAGE_KEY) || "dev";
    } catch (_) {
      return "dev";
    }
  }

  function setCurrentDepartment(id) {
    if (!id) return;
    const prev = currentDepartment();
    try { localStorage.setItem(DEPT_STORAGE_KEY, id); } catch (_) {}
    // Подсветка активного отдела
    $$(".dept-item").forEach((b) => {
      const active = b.dataset.dept === id;
      b.classList.toggle("active", active);
      b.setAttribute("aria-pressed", active ? "true" : "false");
    });
    // Переключение отдела через sidebar — фокус чата уходит на dept-чат.
    setCurrentChatChannel(id);
    if (prev !== id) {
      // S9.2: Полный refresh всех views (board/inbox/chat/...)
      try { refresh(); } catch (_) {}
      // Активная "тяжёлая" view может не входить в refresh-цикл —
      // обновим её отдельно, чтобы переключение отдела было виже за <500ms.
      try {
        if (currentView === "archive") loadArchive();
        if (currentView === "roles") loadRoles();
        // stats — глобальные (см. S9.2), не зависят от отдела.
      } catch (_) {}
      // F1-1.5: мгновенный перерендер списка агентов при смене отдела.
      try { loadSidebarAgents(); } catch (_) {}
    }
  }

  // ===================== Chat channel (ADR-009 §2.7.2) =====================
  // Активный канал чата независим от выбранного отдела для board/inbox.
  // Значения:
  //   "__global__"  → общий чат (department_id IS NULL); собеседник = Управляющий.
  //   "<dept_id>"   → чат отдела; собеседник = lead отдела (dev-lead и т.п.).
  // Backward-compat: первый запуск — fallback на текущий отдел.
  const CHAT_CHANNEL_KEY = "devboard-current-chat-channel";
  const CHAT_CHANNEL_GLOBAL = "__global__";

  // F3 (1.6): fallback — общий чат с Управляющим (ADR-009 §2.7.2).
  // По умолчанию owner общается с Управляющим; переключение в dept-чат — через клик на отдел.
  function currentChatChannel() {
    try {
      const v = localStorage.getItem(CHAT_CHANNEL_KEY);
      if (v) return v;
    } catch (_) {}
    return CHAT_CHANNEL_GLOBAL;
  }

  function _updateChatHeaderLabel() {
    const lbl = document.getElementById("chat-title-label");
    const desc = document.getElementById("chat-description");
    const input = document.getElementById("chat-input");
    const ch = currentChatChannel();
    if (ch === CHAT_CHANNEL_GLOBAL) {
      // «Чат с Управляющим» — основной собеседник owner-а в общем чате.
      if (lbl) {
        const v = i18n("chat.title_managing_director");
        lbl.textContent = (v && v !== "chat.title_managing_director")
          ? v : "Чат с Управляющим";
      }
      if (input) {
        const ph = i18n("chat.placeholder_managing_director");
        input.placeholder = (ph && ph !== "chat.placeholder_managing_director")
          ? ph : "Напиши Управляющему…";
      }
      if (desc) {
        const d = i18n("chat.description_managing_director");
        desc.textContent = (d && d !== "chat.description_managing_director")
          ? d : "Управляющий — координирует все отделы";
      }
    } else {
      // Чат отдела — собеседник lead. Используем существующий ключ chat.title.
      if (lbl) {
        const v = i18n("chat.title");
        lbl.textContent = (v && v !== "chat.title") ? v : "Чат с тимлидом";
      }
      if (input) {
        const ph = i18n("chat.placeholder_lead", { leadName: ch + "-lead" });
        input.placeholder = (ph && ph !== "chat.placeholder_lead")
          ? ph : ch + "-lead…";
      }
      if (desc) {
        const d = i18n("chat.description_lead", { deptName: ch });
        desc.textContent = (d && d !== "chat.description_lead")
          ? d : ch + "-lead — координирует " + ch + "-отдел";
      }
    }
  }

  function _updateManagingDirectorActive() {
    const btn = document.getElementById("btn-managing-director");
    if (!btn) return;
    const active = currentChatChannel() === CHAT_CHANNEL_GLOBAL;
    btn.classList.toggle("active", active);
    btn.setAttribute("aria-pressed", active ? "true" : "false");
    // Если активен общий чат — убираем подсветку с dept-item'ов (только в плане чата),
    // но active-класс самого отдела (board/inbox) остаётся согласованным со state'ом.
    // Стили дептов и MD-row — независимы; ничего больше не трогаем.
  }

  function setCurrentChatChannel(channel) {
    if (!channel) return;
    const prev = currentChatChannel();
    try { localStorage.setItem(CHAT_CHANNEL_KEY, channel); } catch (_) {}
    _updateManagingDirectorActive();
    _updateChatHeaderLabel();
    if (prev !== channel) {
      try { refreshChat(); } catch (_) {}
    }
  }

  // Локализованное имя отдела:
  // 1) явный display_name_en / display_name_ru из API (если backend добавит)
  // 2) i18n ключ dept.<id>
  // 3) name из API
  // 4) id
  function deptDisplayName(d) {
    const locale = (window.getLocale && window.getLocale()) || "ru";
    if (locale === "en" && d.display_name_en) return d.display_name_en;
    if (locale === "ru" && d.display_name_ru) return d.display_name_ru;
    const i18nKey = "dept." + d.id;
    const translated = (typeof window.t === "function") ? window.t(i18nKey) : i18nKey;
    if (translated && translated !== i18nKey) return translated;
    return d.name || d.id;
  }

  function renderDepartments(depts) {
    const wrap = document.getElementById("departments-items");
    if (!wrap) return;
    _departmentsCache = depts;

    // Если текущий отдел не найден среди активных — упасть обратно на 'dev'
    const cur = currentDepartment();
    const exists = depts.some((d) => d.id === cur);
    if (!exists && depts.length > 0) {
      const fallback = depts.some((d) => d.id === "dev") ? "dev" : depts[0].id;
      try { localStorage.setItem(DEPT_STORAGE_KEY, fallback); } catch (_) {}
    }
    const activeId = currentDepartment();

    // F1 (1.6): после обновления кеша отделов — перерисуем popup ролей если он открыт.
    try {
      const popup = document.getElementById("start-role-popup");
      if (popup && !popup.hidden) renderStartRolePopup();
    } catch (_) {}

    wrap.innerHTML = "";
    depts.forEach((d) => {
      const btn = document.createElement("button");
      btn.type = "button";
      btn.className = "dept-item" + (d.id === activeId ? " active" : "");
      btn.dataset.dept = d.id;
      btn.setAttribute("aria-pressed", d.id === activeId ? "true" : "false");

      const ico = document.createElement("span");
      ico.className = "ico";
      ico.textContent = d.icon || "🗂";

      const lbl = document.createElement("span");
      lbl.className = "lbl";
      lbl.textContent = deptDisplayName(d);

      // S11.2: показываем (open/total) — open = задачи требующие внимания
      // (todo/wip/blocked/needs_approval), total = все активные (без archived).
      const openCount = (d.counts && (d.counts.open || 0)) || 0;
      const totalCount = (d.counts && (d.counts.total != null ? d.counts.total : openCount)) || 0;
      const badge = document.createElement("span");
      badge.className = "badge counts" + (totalCount === 0 ? " zero" : "");
      // Семантика: "5/12" — открытые/всего. Если нет ни одной — единственный "0".
      if (totalCount === 0) {
        badge.textContent = "0";
      } else {
        badge.innerHTML = `<span class="open">${openCount}</span>` +
          `<span class="total">/${totalCount}</span>`;
      }
      // Tooltip с расшифровкой counts
      const countsTitle = (typeof window.t === "function")
        ? window.t("sidebar.dept_counts_title", { open: openCount, total: totalCount })
        : `${openCount} open / ${totalCount} total`;
      badge.title = countsTitle;
      badge.setAttribute("aria-label", countsTitle);

      btn.title = (d.description && d.description.length > 0)
        ? d.description
        : deptDisplayName(d);

      btn.appendChild(ico);
      btn.appendChild(lbl);
      btn.appendChild(badge);

      btn.addEventListener("click", () => setCurrentDepartment(d.id));
      wrap.appendChild(btn);
    });
  }

  async function loadDepartments() {
    try {
      const r = await fetch("/api/departments");
      if (!r.ok) return;
      const data = await r.json();
      renderDepartments(data.departments || []);
    } catch (e) {
      console.error("loadDepartments failed", e);
    }
  }

  // ===================== Sidebar agents list (F1-1.5) =====================
  // Показывает роли текущего отдела + глобальные (Управляющий, HR).
  // Данные берём из /api/roles?department=<id>:
  //   backend возвращает роли с department_id=<id> ИЛИ department_id IS NULL.
  // Глобальные роли (department_id=null) подтягиваются автоматически.

  // Иконки ролей — расширенная карта на базе AUTHOR_ICON.
  const _AGENT_ICON = {
    // Dev roles
    "бэкенд":           "🔧",
    "backend":          "🔧",
    "frontend":         "🎨",
    "qa":               "✓",
    "архитектор":       "🏗",
    "architect":        "🏗",
    "devops":           "🚀",
    "техписатель":      "📝",
    "techwriter":       "📝",
    "тимлид":           "🧭",
    "teamlead":         "🧭",
    "dev-lead":         "🧭",
    // Marketing roles
    "copywriter":       "✍",
    "brand-manager":    "🎯",
    "seo-specialist":   "🔍",
    "marketing-analyst":"📊",
    "marketing-lead":   "📣",
    // Global roles
    "Управляющий":      "🏛",
    "managing-director":"🏛",
    "hr":               "🧑‍💼",
    // Fallback
    "пользователь":     "👤",
    "user":             "👤",
  };

  function _agentIcon(name) {
    return _AGENT_ICON[name] || "🤖";
  }

  // Локализованное имя агента — использует ROLE_DISPLAY и display_name_* из API.
  function _agentDisplayName(role) {
    const locale = (typeof window.getLocale === "function") ? window.getLocale() : "ru";
    // 1. display_name из API (добавляется бэкендом в поле display_name_en/ru)
    if (locale === "en" && role.display_name_en) return role.display_name_en;
    if (locale !== "en" && role.display_name_ru) return role.display_name_ru;
    // 2. ROLE_DISPLAY (существующий словарь)
    const rd = ROLE_DISPLAY[role.name];
    if (rd) return locale === "en" ? rd.en : rd.ru;
    // 3. name_ru / name_en из метаданных если бэкенд добавит их позже
    if (locale !== "en" && role.name_ru) return role.name_ru;
    if (locale === "en" && role.name_en) return role.name_en;
    // 4. Сам slug
    return role.name;
  }

  function renderSidebarAgents(roles) {
    const wrap = document.getElementById("sidebar-agents");
    if (!wrap) return;
    if (!roles || roles.length === 0) {
      wrap.innerHTML = "";
      return;
    }

    const locale = (typeof window.getLocale === "function") ? window.getLocale() : "ru";
    const teamLabel = (typeof window.t === "function")
      ? window.t("sidebar.team")
      : (locale === "en" ? "Team" : "Команда");

    let html = `<div class="muted">${escapeHtml(teamLabel)}</div>`;
    roles.forEach((role) => {
      const ico = _agentIcon(role.name);
      const label = escapeHtml(_agentDisplayName(role));
      const deptId = role.department_id || null;
      const deptTitle = deptId
        ? escapeHtml(deptId)
        : (locale === "en" ? "Global role" : "Глобальная роль");
      html += `<div role="listitem" title="${label} — ${deptTitle}">${ico} <span>${label}</span></div>`;
    });
    wrap.innerHTML = html;
  }

  async function loadSidebarAgents() {
    try {
      const dept = currentDepartment();
      const r = await fetch("/api/roles?department=" + encodeURIComponent(dept));
      if (!r.ok) return;
      const data = await r.json();
      const raw = data.роли || [];
      // Фильтруем пользователя (не агент — это сам owner)
      const agents = raw.filter((role) => role.name !== "пользователь" && role.name !== "user");
      renderSidebarAgents(agents);
    } catch (e) {
      console.error("loadSidebarAgents failed", e);
    }
  }

  // ===================== Managing Director button (ADR-009 §2.7.2) =====================
  // Глобальная строчка «🏛 Управляющий» над списком отделов.
  // Клик → переключает только чат-канал на общий (department_id IS NULL).
  // Board / Inbox / counters остаются в контексте ранее выбранного отдела.
  (function initManagingDirectorButton() {
    const btn = document.getElementById("btn-managing-director");
    if (!btn) return;
    btn.addEventListener("click", () => setCurrentChatChannel(CHAT_CHANNEL_GLOBAL));
    // Применить начальное состояние подсветки + заголовка чата.
    _updateManagingDirectorActive();
    _updateChatHeaderLabel();
  })();

  // При смене локали — обновить динамический label заголовка чата
  // (data-i18n="chat.title" обрабатывается i18n.js автоматически, но мы
  // переопределяем textContent через setCurrentChatChannel — поэтому при
  // localechange надо повторно подставить актуальный ключ).
  window.addEventListener("localechange", () => {
    try { _updateChatHeaderLabel(); } catch (_) {}
  });

  // ===================== Create-department modal (S10.4) =====================
  // Открывает модалку с 2 шагами: form → HR-chat-loop.
  // Использует REST API из S10.3: /api/hr/start, /api/hr/answer, /api/hr/approve,
  // /api/hr/status/<id> (polling 2s пока модалка открыта на шаге 2).
  const HR_POLL_MS = 2000;
  const HR_FINAL_STATES = new Set(["active", "aborted"]);

  const createDeptState = {
    sessionId: null,
    state: null,
    lastMessage: null,
    pollTimer: null,
    lastFocus: null,        // элемент, на котором был фокус до открытия модалки
    keydownHandler: null,   // focus-trap + Esc
    activeSinceOpen: false, // показывали ли мы tail-сообщение «активирован»
  };

  function _i18nDeptCreate(key, params) {
    return i18n("dept.create." + key, params);
  }

  // ----- Focus trap + Escape ----------------------------------------------
  function _createDeptKeydown(e) {
    const modal = document.getElementById("modal-create-department");
    if (!modal || modal.hidden) return;
    if (e.key === "Escape") {
      e.stopPropagation();
      closeCreateDeptModal();
      return;
    }
    if (e.key !== "Tab") return;
    const focusables = Array.from(modal.querySelectorAll(
      'a[href], button:not([disabled]), textarea:not([disabled]), input:not([disabled]), select:not([disabled]), [tabindex]:not([tabindex="-1"])'
    )).filter((el) => !el.hidden && el.offsetParent !== null);
    if (focusables.length === 0) return;
    const first = focusables[0];
    const last  = focusables[focusables.length - 1];
    if (e.shiftKey && document.activeElement === first) {
      e.preventDefault();
      last.focus();
    } else if (!e.shiftKey && document.activeElement === last) {
      e.preventDefault();
      first.focus();
    }
  }

  // ----- Chat rendering ---------------------------------------------------
  function _appendDeptChatMessage(role, text) {
    const wrap = document.getElementById("create-dept-chat");
    if (!wrap) return;
    const row = document.createElement("div");
    row.className = "create-dept-msg create-dept-msg-" + role;

    const who = document.createElement("span");
    who.className = "create-dept-msg-who";
    let label = "";
    if (role === "hr")        label = _i18nDeptCreate("step2.hr_label");
    else if (role === "you")  label = _i18nDeptCreate("step2.you_label");
    else                      label = _i18nDeptCreate("step2.system_label");
    who.textContent = label;

    const body = document.createElement("span");
    body.className = "create-dept-msg-body";
    body.textContent = text || "";

    row.appendChild(who);
    row.appendChild(body);
    wrap.appendChild(row);
    // auto-scroll к низу
    wrap.scrollTop = wrap.scrollHeight;
  }

  function _updateDeptStateLabel(state) {
    const lbl = document.getElementById("create-dept-state-label");
    const dot = document.querySelector("#create-dept-state .create-dept-state-dot");
    const cont = document.getElementById("create-dept-state");
    if (!lbl || !cont) return;
    const key = "state." + (state || "hr_planning");
    lbl.textContent = _i18nDeptCreate(key);
    if (dot) {
      dot.className = "create-dept-state-dot create-dept-state-dot-" + (state || "hr_planning");
    }
    cont.dataset.state = state || "";
  }

  function _setDeptError(stepId, text) {
    const el = document.getElementById(stepId);
    if (!el) return;
    if (text) {
      el.textContent = text;
      el.hidden = false;
    } else {
      el.textContent = "";
      el.hidden = true;
    }
  }

  function _setDeptStep(n) {
    const s1 = document.getElementById("create-dept-step-1");
    const s2 = document.getElementById("create-dept-step-2");
    if (s1) s1.hidden = n !== 1;
    if (s2) s2.hidden = n !== 2;
  }

  function _disableDeptStep2Buttons(disabled) {
    ["btn-create-dept-approve", "btn-create-dept-edit",
     "btn-create-dept-answer", "create-dept-answer-input"].forEach((id) => {
      const el = document.getElementById(id);
      if (el) el.disabled = disabled;
    });
  }

  // ----- Polling ----------------------------------------------------------
  function _stopDeptPolling() {
    if (createDeptState.pollTimer) {
      clearInterval(createDeptState.pollTimer);
      createDeptState.pollTimer = null;
    }
  }

  function _startDeptPolling() {
    _stopDeptPolling();
    createDeptState.pollTimer = setInterval(_pollDeptStatus, HR_POLL_MS);
  }

  async function _pollDeptStatus() {
    if (!createDeptState.sessionId) return;
    try {
      const r = await fetch("/api/hr/status/" + encodeURIComponent(createDeptState.sessionId));
      if (r.status === 404) {
        _setDeptError("create-dept-step2-error", _i18nDeptCreate("errors.session_lost"));
        _stopDeptPolling();
        return;
      }
      if (!r.ok) return;
      const data = await r.json();

      // Новое сообщение от HR?
      if (data.last_message && data.last_message !== createDeptState.lastMessage) {
        // last_message в БД — это последнее, что записано (может быть и owner-msg,
        // и HR-msg). На owner-side мы локально показываем то, что отправил юзер,
        // поэтому здесь добавляем только если это НЕ совпадает с тем, что мы
        // только что отправили (см. handler "answer" — он не апдейтит lastMessage
        // на owner-text, только инициализация).
        createDeptState.lastMessage = data.last_message;
        // На owner-стороне: показываем как HR, т.к. owner-сообщения мы добавляем сами.
        if (!data._owner_echo) {
          _appendDeptChatMessage("hr", data.last_message);
        }
      }

      if (data.state && data.state !== createDeptState.state) {
        createDeptState.state = data.state;
        _updateDeptStateLabel(data.state);
      }

      // Финальное состояние: active → закрыть модалку и обновить sidebar.
      if (data.state === "active" && !createDeptState.activeSinceOpen) {
        createDeptState.activeSinceOpen = true;
        const name = data.department_name || "";
        _appendDeptChatMessage("system",
          _i18nDeptCreate("success", { name: name }));
        _stopDeptPolling();
        // Небольшая пауза, чтобы пользователь увидел успешное сообщение
        setTimeout(() => {
          closeCreateDeptModal();
          try { loadDepartments(); } catch (_) {}
        }, 900);
      } else if (data.state === "aborted") {
        _setDeptError("create-dept-step2-error", _i18nDeptCreate("errors.aborted"));
        _disableDeptStep2Buttons(true);
        _stopDeptPolling();
      }
    } catch (e) {
      // network — тихо игнорируем, следующая итерация retry
    }
  }

  // ----- Open / close -----------------------------------------------------
  function openCreateDeptModal() {
    const modal = document.getElementById("modal-create-department");
    if (!modal) return;
    // reset state
    createDeptState.sessionId = null;
    createDeptState.state = null;
    createDeptState.lastMessage = null;
    createDeptState.activeSinceOpen = false;
    createDeptState.lastFocus = document.activeElement;

    // Reset form
    const form = document.getElementById("form-create-dept");
    if (form) form.reset();
    const aiRadio = document.querySelector('#form-create-dept input[name="template_hint"][value=""]');
    if (aiRadio) aiRadio.checked = true;
    const chat = document.getElementById("create-dept-chat");
    if (chat) chat.innerHTML = "";
    _setDeptError("create-dept-step1-error", null);
    _setDeptError("create-dept-step2-error", null);
    _disableDeptStep2Buttons(false);
    _setDeptStep(1);
    _updateDeptStateLabel("hr_planning");

    modal.hidden = false;
    // Установить focus на первое поле
    setTimeout(() => {
      const nameInput = document.getElementById("create-dept-name");
      if (nameInput) nameInput.focus();
    }, 50);

    // Подключить keydown handler (focus trap + Esc)
    createDeptState.keydownHandler = _createDeptKeydown;
    document.addEventListener("keydown", createDeptState.keydownHandler, true);
  }

  function closeCreateDeptModal() {
    const modal = document.getElementById("modal-create-department");
    if (!modal) return;
    modal.hidden = true;
    _stopDeptPolling();
    if (createDeptState.keydownHandler) {
      document.removeEventListener("keydown", createDeptState.keydownHandler, true);
      createDeptState.keydownHandler = null;
    }
    // Вернуть фокус на инициатор
    try {
      if (createDeptState.lastFocus && typeof createDeptState.lastFocus.focus === "function") {
        createDeptState.lastFocus.focus();
      }
    } catch (_) {}
  }

  // ----- Step 1: submit (start HR) ----------------------------------------
  async function _onCreateDeptStart(e) {
    if (e) e.preventDefault();
    const nameInput = document.getElementById("create-dept-name");
    const descInput = document.getElementById("create-dept-description");
    const hintInput = document.querySelector('#form-create-dept input[name="template_hint"]:checked');
    const startBtn = document.getElementById("btn-create-dept-start");

    const name = (nameInput?.value || "").trim();
    const description = (descInput?.value || "").trim();
    const templateHint = (hintInput?.value || "").trim() || null;

    if (!name) {
      _setDeptError("create-dept-step1-error", _i18nDeptCreate("errors.name_required"));
      nameInput?.focus();
      return;
    }
    _setDeptError("create-dept-step1-error", null);

    const body = { name, description };
    if (templateHint) body.template_hint = templateHint;

    if (startBtn) startBtn.disabled = true;

    try {
      const r = await fetch("/api/hr/start", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
      });
      if (!r.ok) {
        const err = await r.json().catch(() => ({}));
        const reason = err.причина || err.reason || ("HTTP " + r.status);
        _setDeptError("create-dept-step1-error",
          _i18nDeptCreate("errors.start_failed") + " " + reason);
        return;
      }
      const data = await r.json();
      createDeptState.sessionId = data.hr_session_id;
      createDeptState.state = data.state || "hr_planning";

      _setDeptStep(2);
      _updateDeptStateLabel(createDeptState.state);
      _appendDeptChatMessage("you",
        description || ("Создай отдел: " + name));
      _appendDeptChatMessage("system", _i18nDeptCreate("step2.first_hint"));

      // focus в поле ответа
      setTimeout(() => {
        const ans = document.getElementById("create-dept-answer-input");
        if (ans) ans.focus();
      }, 50);

      _startDeptPolling();
    } catch (e2) {
      _setDeptError("create-dept-step1-error", _i18nDeptCreate("errors.start_failed"));
    } finally {
      if (startBtn) startBtn.disabled = false;
    }
  }

  // ----- Step 2: send answer ----------------------------------------------
  async function _onCreateDeptAnswer(e) {
    if (e) e.preventDefault();
    if (!createDeptState.sessionId) return;
    const inp = document.getElementById("create-dept-answer-input");
    const text = (inp?.value || "").trim();
    if (!text) return;

    _setDeptError("create-dept-step2-error", null);
    _appendDeptChatMessage("you", text);
    if (inp) {
      inp.value = "";
      inp.focus();
    }

    try {
      const r = await fetch("/api/hr/answer", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          hr_session_id: createDeptState.sessionId,
          message: text,
        }),
      });
      if (!r.ok) {
        const err = await r.json().catch(() => ({}));
        const reason = err.причина || err.reason || ("HTTP " + r.status);
        _setDeptError("create-dept-step2-error",
          _i18nDeptCreate("errors.answer_failed") + " " + reason);
        return;
      }
      // Owner-сообщение записывается в last_message в БД — чтобы polling
      // не показал его повторно как HR-message, синхронизируем локально.
      createDeptState.lastMessage = text;
    } catch (e2) {
      _setDeptError("create-dept-step2-error", _i18nDeptCreate("errors.answer_failed"));
    }
  }

  // ----- Step 2: approve --------------------------------------------------
  async function _onCreateDeptApprove() {
    if (!createDeptState.sessionId) return;
    _setDeptError("create-dept-step2-error", null);
    _disableDeptStep2Buttons(true);

    try {
      const r = await fetch("/api/hr/approve", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ hr_session_id: createDeptState.sessionId }),
      });
      if (!r.ok) {
        const err = await r.json().catch(() => ({}));
        const reason = err.причина || err.reason || ("HTTP " + r.status);
        _setDeptError("create-dept-step2-error",
          _i18nDeptCreate("errors.approve_failed") + " " + reason);
        _disableDeptStep2Buttons(false);
        return;
      }
      // Polling сам подхватит переход в active/aborted.
      // Кратко покажем activation state:
      _updateDeptStateLabel("hr_activating");
    } catch (e2) {
      _setDeptError("create-dept-step2-error", _i18nDeptCreate("errors.approve_failed"));
      _disableDeptStep2Buttons(false);
    }
  }

  // ----- Wire up handlers (DOMContentLoaded) ------------------------------
  document.addEventListener("DOMContentLoaded", () => {
    // Прогрев кеша моделей ролей — чтобы pickModelForTask (чипы карточек)
    // знал модель каждой роли до открытия Roles tab.
    fetch("/api/roles?department=__all__")
      .then((r) => (r.ok ? r.json() : null))
      .then((data) => {
        if (!data) return;
        const raw = data.роли || [];
        const flat = raw.map((role) => {
          const ext = (role.capabilities && typeof role.capabilities === "object" && !Array.isArray(role.capabilities)) ? role.capabilities : {};
          return { name: role.name, model: ext.model || role.model || "" };
        });
        _refreshRoleModelCache(flat);
        // Перерисуем доску чтобы чипы обновились
        if (typeof refreshAll === "function") refreshAll();
      })
      .catch(() => {});

    // ADR-009 §2.7.1 (F1): кнопка «+ Department» открывает fast-path модалку
    // с 11 шаблонами. HR-flow доступен в ней через отдельную кнопку «через HR».
    const addBtn = document.getElementById("btn-add-department");
    if (addBtn) {
      addBtn.addEventListener("click", openAddDeptModal);
    }
    _wireAddDeptModal();

    const closeBtn = document.getElementById("btn-create-dept-close");
    if (closeBtn) closeBtn.addEventListener("click", closeCreateDeptModal);

    const cancelBtn = document.getElementById("btn-create-dept-cancel");
    if (cancelBtn) cancelBtn.addEventListener("click", closeCreateDeptModal);

    const form = document.getElementById("form-create-dept");
    if (form) form.addEventListener("submit", _onCreateDeptStart);

    const ansForm = document.getElementById("form-create-dept-answer");
    if (ansForm) ansForm.addEventListener("submit", _onCreateDeptAnswer);

    const editBtn = document.getElementById("btn-create-dept-edit");
    if (editBtn) editBtn.addEventListener("click", () => {
      // Просто фокус в поле ответа — owner может писать правки HR.
      const ans = document.getElementById("create-dept-answer-input");
      if (ans) ans.focus();
    });

    const approveBtn = document.getElementById("btn-create-dept-approve");
    if (approveBtn) approveBtn.addEventListener("click", _onCreateDeptApprove);

    // Клик по backdrop модалки — закрытие.
    const modal = document.getElementById("modal-create-department");
    if (modal) {
      modal.addEventListener("click", (ev) => {
        if (ev.target === modal) closeCreateDeptModal();
      });
    }
  });

  // ===================== ADR-009 §2.7.1 — Add-department fast-path modal =====================
  // Открывается по клику на «+ Department». Показывает 11 шаблонов:
  // marketing — активен (Phase 2), остальные 10 disabled (Phase 3).
  // Клик по активному шаблону → POST /api/departments {template_id: <slug>-v2}.
  // Кнопка «🧑‍💼 Создать через HR» — открывает старую модалку ADR-004.
  const addDeptState = {
    lastFocus: null,
    keydownHandler: null,
    busy: false,
  };

  function _addDeptKeydown(e) {
    const modal = document.getElementById("modal-add-department");
    if (!modal || modal.hidden) return;
    if (e.key === "Escape") {
      e.stopPropagation();
      closeAddDeptModal();
      return;
    }
    if (e.key !== "Tab") return;
    const focusables = Array.from(modal.querySelectorAll(
      'a[href], button:not([disabled]), textarea:not([disabled]), input:not([disabled]), select:not([disabled]), [tabindex]:not([tabindex="-1"])'
    )).filter((el) => !el.hidden && el.offsetParent !== null);
    if (focusables.length === 0) return;
    const first = focusables[0];
    const last  = focusables[focusables.length - 1];
    if (e.shiftKey && document.activeElement === first) {
      e.preventDefault();
      last.focus();
    } else if (!e.shiftKey && document.activeElement === last) {
      e.preventDefault();
      first.focus();
    }
  }

  function _setAddDeptError(text) {
    const el = document.getElementById("add-dept-error");
    if (!el) return;
    if (text) {
      el.textContent = text;
      el.hidden = false;
    } else {
      el.textContent = "";
      el.hidden = true;
    }
  }

  function openAddDeptModal() {
    const modal = document.getElementById("modal-add-department");
    if (!modal) return;
    addDeptState.lastFocus = document.activeElement;
    addDeptState.busy = false;
    _setAddDeptError(null);
    modal.hidden = false;

    // focus на первую активную карточку (marketing)
    setTimeout(() => {
      const firstActive = modal.querySelector(".add-dept-card-active");
      if (firstActive) firstActive.focus();
    }, 50);

    addDeptState.keydownHandler = _addDeptKeydown;
    document.addEventListener("keydown", addDeptState.keydownHandler, true);
  }

  function closeAddDeptModal() {
    const modal = document.getElementById("modal-add-department");
    if (!modal) return;
    modal.hidden = true;
    if (addDeptState.keydownHandler) {
      document.removeEventListener("keydown", addDeptState.keydownHandler, true);
      addDeptState.keydownHandler = null;
    }
    try {
      if (addDeptState.lastFocus && typeof addDeptState.lastFocus.focus === "function") {
        addDeptState.lastFocus.focus();
      }
    } catch (_) {}
  }

  async function _createDepartmentFromTemplate(templateId, cardEl) {
    if (addDeptState.busy) return;
    addDeptState.busy = true;
    _setAddDeptError(null);
    if (cardEl) cardEl.classList.add("is-loading");

    try {
      const r = await fetch("/api/departments", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ template_id: templateId }),
      });
      if (r.status === 201) {
        const data = await r.json().catch(() => ({}));
        const deptName = (data.department && (data.department.name || data.department.id)) || templateId;
        // Закрываем модалку.
        closeAddDeptModal();
        // Обновляем sidebar (без полной перезагрузки страницы — state сохраняем).
        try { await loadDepartments(); } catch (_) {}
        // toast / desktop notification.
        const okText = i18n("sidebar.add_department.created_ok", { name: deptName });
        try {
          if (typeof notify === "function") notify("info", okText, "");
        } catch (_) {}
        // Также alert на случай если уведомления выключены — short visual feedback.
        try {
          if (typeof window.flashToast === "function") {
            window.flashToast(okText);
          }
        } catch (_) {}
        return;
      }
      // Ошибка: 400 / 404 / 409
      let errMsg = "";
      try {
        const err = await r.json();
        errMsg = err.причина || err.reason || ("HTTP " + r.status);
        if (Array.isArray(err.missing) && err.missing.length) {
          errMsg += " (" + err.missing.slice(0, 3).join("; ") + ")";
        }
      } catch (_) {
        errMsg = "HTTP " + r.status;
      }
      _setAddDeptError(i18n("sidebar.add_department.error") + " " + errMsg);
    } catch (e) {
      _setAddDeptError(i18n("sidebar.add_department.error") + " " + (e && e.message ? e.message : ""));
    } finally {
      addDeptState.busy = false;
      if (cardEl) cardEl.classList.remove("is-loading");
    }
  }

  function _onAddDeptHrCustom() {
    // Переключаемся со fast-path модалки на старую HR-flow модалку (ADR-004).
    closeAddDeptModal();
    try {
      if (typeof openCreateDeptModal === "function") openCreateDeptModal();
    } catch (_) {}
  }

  function _wireAddDeptModal() {
    const modal = document.getElementById("modal-add-department");
    if (!modal) return;

    // Карточки шаблонов.
    modal.querySelectorAll(".add-dept-card").forEach((card) => {
      card.addEventListener("click", (ev) => {
        if (card.disabled || card.getAttribute("aria-disabled") === "true") return;
        ev.preventDefault();
        const templateId = card.getAttribute("data-template-id");
        if (!templateId) return;
        _createDepartmentFromTemplate(templateId, card);
      });
    });

    // Close button.
    const closeBtn = document.getElementById("btn-add-dept-close");
    if (closeBtn) closeBtn.addEventListener("click", closeAddDeptModal);

    // HR custom button.
    const hrBtn = document.getElementById("btn-add-dept-hr-custom");
    if (hrBtn) hrBtn.addEventListener("click", _onAddDeptHrCustom);

    // Backdrop click.
    modal.addEventListener("click", (ev) => {
      if (ev.target === modal) closeAddDeptModal();
    });
  }

  // ===================== Tasks: list & render =====================

  async function fetchTasks() {
    const r = await fetch("/api/tasks?department=" + encodeURIComponent(currentDepartment()));
    if (!r.ok) throw new Error("api/tasks " + r.status);
    return r.json();
  }

  // ===================== i18n helper =====================
  // Proxy к window.t (загружается i18n.js после app.js, вызовы идут позже)
  function i18n(key, params) {
    return (typeof window.t === "function") ? window.t(key, params) : key;
  }

  // locale-aware date formatter
  function dtLocale() {
    return (window.getLocale && window.getLocale() === "en") ? "en-US" : "ru-RU";
  }

  function shortAge(ts) {
    const sec = Math.max(0, Math.floor(Date.now() / 1000 - ts));
    if (sec < 60) return sec + i18n("kanban.card.age.sec");
    if (sec < 3600) return Math.floor(sec / 60) + i18n("kanban.card.age.min");
    if (sec < 86400) return Math.floor(sec / 3600) + i18n("kanban.card.age.hour");
    return Math.floor(sec / 86400) + i18n("kanban.card.age.day");
  }

  // Зеркало логики mcp_server/pride_tasks/router.pick для одной задачи.
  // Возвращает alias модели (haiku/sonnet/opus) или null для родительских эпиков.
  // Учитываются: labels (приоритетные) + модель роли-исполнителя из БД.
  const _ROLE_MODEL_CACHE = {}; // {assignee: "haiku"|"sonnet"|"opus"}

  function _modelAliasFromFull(modelFull) {
    if (!modelFull) return null;
    if (modelFull.includes("opus")) return "opus";
    if (modelFull.includes("sonnet")) return "sonnet";
    if (modelFull.includes("haiku")) return "haiku";
    return null;
  }

  // Заполняем кеш моделей ролей при загрузке /api/roles
  function _refreshRoleModelCache(rolesList) {
    for (const r of rolesList || []) {
      const alias = _modelAliasFromFull(r.model || r.capabilities?.model);
      if (alias) _ROLE_MODEL_CACHE[r.name] = alias;
    }
  }

  function pickModelForTask(t) {
    const labels = new Set(t.labels || []);
    if (labels.has("epic")) return null;
    // Сильные label-сигналы перебивают модель роли.
    if (labels.has("destructive")) return "opus";
    if (labels.has("design") || labels.has("architecture") || labels.has("adr")) return "opus";
    if (labels.has("trivial") || labels.has("chore") || labels.has("rename") || labels.has("polish")) return "haiku";
    // Если у роли-исполнителя в БД своя модель — используем её.
    if (t.assignee && _ROLE_MODEL_CACHE[t.assignee]) {
      return _ROLE_MODEL_CACHE[t.assignee];
    }
    return "sonnet";
  }

  function renderCard(t) {
    const card = document.createElement("div");
    card.className = "card";
    card.dataset.id = t.id;
    card.draggable = true;
    card.addEventListener("dragstart", (e) => {
      e.dataTransfer.setData("text/plain", t.id);
      e.dataTransfer.effectAllowed = "move";
      card.classList.add("dragging");
    });
    card.addEventListener("dragend", () => card.classList.remove("dragging"));

    const approval = t.requires_approval ? `<span class="approval ico">⚠</span>` : "";
    const role = t.assignee ? `<span class="role">${displayRole(t.assignee)}</span>` : "";
    const linkIcon = t._has_deps ? `<span class="link-icon ico" title="${i18n("kanban.card.has_deps")}">🔗</span>` : "";
    const model = pickModelForTask(t);
    const modelChip = model
      ? `<span class="model ${model}" title="${i18n("kanban.card.model_tooltip", { model })}">${model}</span>`
      : "";
    card.innerHTML = `
      <div class="meta">
        <span class="id">#${t.id.slice(0, 6)}</span>
        <span class="pri">${t.priority}</span>
        ${role}
        ${modelChip}
        ${approval}
        ${linkIcon}
      </div>
      <div class="title">${escapeHtml(t.title)}</div>
      <div class="footer">
        <span>${shortAge(t.created_at)} ${i18n("kanban.card.ago_suffix")}</span>
      </div>
    `;
    card.addEventListener("click", () => openTaskModal(t.id));
    return card;
  }

  function renderBoard(data) {
    const search = ($("#search").value || "").toLowerCase().trim();
    const showEmpty = $("#board-show-empty").checked;
    for (const status of STATUSES) {
      const container = document.querySelector(`[data-cards="${status}"]`);
      container.innerHTML = "";
      let tasks = data.колонки[status] || [];
      if (search) tasks = tasks.filter((t) => t.title.toLowerCase().includes(search));
      const emptyBlock = document.querySelector(`[data-empty="${status}"]`);
      if (tasks.length === 0) {
        if (emptyBlock) {
          // Дружелюбный empty-state (SVG + текст + опц. CTA) — для todo/wip/review/done
          emptyBlock.hidden = false;
        } else {
          // Fallback для колонок без кастомного empty-state (needs_approval)
          const empty = document.createElement("div");
          empty.className = "col-empty";
          empty.textContent = i18n("kanban.col_empty");
          container.appendChild(empty);
        }
      } else {
        if (emptyBlock) emptyBlock.hidden = true;
        tasks.forEach((t) => container.appendChild(renderCard(t)));
      }
      document.querySelector(`[data-count="${status}"]`).textContent = tasks.length;
      const col = document.querySelector(`[data-status="${status}"]`);
      col.classList.toggle("empty-collapsed", tasks.length === 0 && !showEmpty);
    }
    // Счётчик в sidebar
    const totalActive = Object.values(data.колонки).reduce(
      (s, arr) => s + arr.length, 0,
    );
    setNavBadge("nav-board-count", totalActive);
    setNavBadge("nav-archive-count", data.архив_count || 0);
  }
  $("#board-show-empty").addEventListener("change", () => refresh());

  function setNavBadge(id, n) {
    const el = $("#" + id);
    el.textContent = n;
    el.classList.toggle("empty", n === 0);
  }

  function escapeHtml(s) {
    return (s || "")
      .replaceAll("&", "&amp;")
      .replaceAll("<", "&lt;")
      .replaceAll(">", "&gt;")
      .replaceAll('"', "&quot;");
  }
  function escapeAttr(s) {
    return escapeHtml(s).replaceAll("'", "&#39;");
  }
  function extractTldr(description) {
    if (!description) return "";
    const m = description.match(/^\s*\**TL;?DR\**\s*:?\s*([^\n]+)/i);
    if (m) return m[1].trim().slice(0, 200);
    const lines = description.split(/\r?\n/).map((l) => l.trim()).filter(Boolean);
    if (!lines.length) return "";
    return lines[0].slice(0, 140);
  }

  /**
   * parseTaskDescription — JS-парсер описания задачи (S6.2).
   * Возвращает { tldr, questions:[{question, options:[]}], acceptance:[], raw }
   * или { tldr:null, questions:[], acceptance:[], raw } при fallback.
   */
  function parseTaskDescription(md) {
    if (!md || !md.trim()) {
      return { tldr: null, questions: [], acceptance: [], raw: md || "" };
    }

    const lines = md.split(/\r?\n/);
    let tldr = null;
    const questions = [];
    const acceptance = [];

    // --- 1. TL;DR ---
    // Ищем строку начинающуюся с **TL;DR** или **TL;DR**: или просто TL;DR:
    let tldrLineIdx = -1;
    for (let i = 0; i < lines.length; i++) {
      const l = lines[i];
      const m = l.match(/^\s*\*{0,2}TL;?DR\*{0,2}\s*:?\s*(.*)$/i);
      if (m) {
        tldrLineIdx = i;
        let text = m[1].trim();
        // Если текст пустой (TL;DR на отдельной строке), берём следующую непустую
        if (!text) {
          for (let j = i + 1; j < lines.length; j++) {
            const next = lines[j].trim();
            if (!next || next.startsWith("#")) break;
            text = next;
            break;
          }
        }
        // Собираем до пустой строки или следующего ##
        let extra = text;
        for (let j = i + 1; j < lines.length; j++) {
          const next = lines[j];
          if (!next.trim() || /^#+\s/.test(next)) break;
          // Пропускаем если это уже была строка с TL;DR-текстом
          if (j === tldrLineIdx + 1 && !m[1].trim()) { extra = next.trim(); break; }
        }
        tldr = extra.trim() || null;
        break;
      }
    }

    // --- 2. Questions / options ---
    // Ищем строки вида "Вопрос:" или "Question:", затем списочные строки
    let inQuestionBlock = false;
    let currentQuestion = null;
    let currentOptions = [];

    for (let i = 0; i < lines.length; i++) {
      const l = lines[i];
      // Начало блока вопросов
      if (/^\s*(Вопрос|Question)\s*:/i.test(l)) {
        if (currentQuestion !== null) {
          questions.push({ question: currentQuestion, options: currentOptions });
        }
        currentQuestion = l.replace(/^\s*(Вопрос|Question)\s*:\s*/i, "").trim();
        currentOptions = [];
        inQuestionBlock = true;
        continue;
      }
      // Варианты: "1. ...", "А) ...", "A) ...", "- ..." в блоке вопроса
      if (inQuestionBlock) {
        const optMatch = l.match(/^\s*(?:\d+[.)]\s*|[А-Яа-яA-Za-z][.)]\s*|-\s+)(.+)$/);
        if (optMatch) {
          currentOptions.push(optMatch[1].trim());
          continue;
        }
        // Пустая строка или заголовок — закрываем блок
        if (!l.trim() || /^#+\s/.test(l)) {
          inQuestionBlock = false;
          if (currentQuestion !== null) {
            questions.push({ question: currentQuestion, options: currentOptions });
            currentQuestion = null;
            currentOptions = [];
          }
        }
      }
    }
    // Добавляем незакрытый вопрос
    if (currentQuestion !== null) {
      questions.push({ question: currentQuestion, options: currentOptions });
    }

    // --- 3. Acceptance criteria ---
    // Ищем ## Acceptance или ## Acceptance criteria, затем bullet-строки
    let inAcceptance = false;
    for (let i = 0; i < lines.length; i++) {
      const l = lines[i];
      if (/^#+\s+Acceptance(\s+criteria)?/i.test(l)) {
        inAcceptance = true;
        continue;
      }
      if (inAcceptance) {
        // Новый заголовок — завершаем блок
        if (/^#+\s/.test(l)) { inAcceptance = false; continue; }
        // bullet или checkbox строки
        const bulletMatch = l.match(/^\s*[-*]\s+(.+)$/);
        const checkboxMatch = l.match(/^\s*[-*]?\s*\[([x ])\]\s*(.+)$/i);
        if (checkboxMatch) {
          acceptance.push(checkboxMatch[2].trim());
        } else if (bulletMatch) {
          acceptance.push(bulletMatch[1].trim());
        }
      }
    }

    return { tldr, questions, acceptance, raw: md };
  }

  // ===================== Drag-n-drop columns =====================
  $$("[data-status]").forEach((col) => {
    const status = col.dataset.status;
    col.addEventListener("dragover", (e) => {
      e.preventDefault();
      e.dataTransfer.dropEffect = "move";
      col.classList.add("drag-over");
    });
    col.addEventListener("dragleave", (e) => {
      if (!col.contains(e.relatedTarget)) col.classList.remove("drag-over");
    });
    col.addEventListener("drop", async (e) => {
      e.preventDefault();
      col.classList.remove("drag-over");
      const id = e.dataTransfer.getData("text/plain");
      if (!id) return;
      const r = await fetch("/api/tasks/" + id, {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ status }),
      });
      if (!r.ok) {
        const err = await r.json().catch(() => ({}));
        alert(i18n("kanban.move_failed") + (err.причина || err.reason || r.status));
      }
      refresh();
    });
  });

  // ===================== Task modal =====================

  // STATUS_LABEL: используем t() для поддержки переключения локали
  const STATUS_KEYS = ["todo", "wip", "needs_approval", "review", "done", "blocked"];
  function statusLabel(status) {
    return i18n("status." + status) || status;
  }
  // Для обратной совместимости с Object.entries(STATUS_LABEL)
  function getStatusLabels() {
    return STATUS_KEYS.map((k) => [k, statusLabel(k)]);
  }

  // Рендер user-mode: структурированное отображение с TL;DR, шагами, acceptance, опциями
  function renderUserMode(parsed) {
    if (!parsed || !parsed.has_structure) {
      return null; // Fallback к raw markdown
    }

    const parts = [];

    // TL;DR — крупно и выделено
    if (parsed.tldr) {
      parts.push(`
        <div class="task-tldr" id="task-tldr-text">
          <div class="task-tldr-label">${i18n("task.reader.tldr")}</div>
          <div class="task-tldr-content">${escapeHtml(parsed.tldr)}</div>
        </div>
      `);
    }

    // Шаги со списком
    if (parsed.steps && parsed.steps.length) {
      const stepsList = parsed.steps
        .map((step) => `<li>${escapeHtml(step)}</li>`)
        .join("");
      parts.push(`
        <div class="task-steps" id="task-steps-list">
          <div class="task-steps-label">${i18n("task.reader.steps")}</div>
          <ul class="task-steps-ul">${stepsList}</ul>
        </div>
      `);
    }

    // Acceptance criteria как чек-лист
    if (parsed.acceptance && parsed.acceptance.length) {
      const checkboxes = parsed.acceptance
        .map((item) => {
          const checked = item.checked ? "checked" : "";
          return `<li><label><input type="checkbox" ${checked}> ${escapeHtml(item.label)}</label></li>`;
        })
        .join("");
      parts.push(`
        <div class="task-acceptance" id="task-acceptance-list">
          <div class="task-acceptance-label">${i18n("task.reader.acceptance")}</div>
          <ul class="task-accept-ul">${checkboxes}</ul>
        </div>
      `);
    }

    // Варианты ответов как кнопки
    if (parsed.options && parsed.options.length) {
      const optionsBtns = parsed.options
        .map((opt) => {
          return `<button type="button" class="option-btn" data-option-value="${escapeAttr(opt.value)}">
            ${escapeHtml(opt.label)}
          </button>`;
        })
        .join("");
      parts.push(`
        <div class="reader-mode-section">
          <div class="task-steps-label">${i18n("task.reader.options") || "Варианты"}</div>
          <div class="options-buttons">${optionsBtns}</div>
        </div>
      `);
    }

    // Кнопка раскрыть технические детали (raw)
    parts.push(`
      <button type="button" class="btn-toggle-raw" id="btn-toggle-raw">
        ${i18n("task.reader.show_raw")}
      </button>
    `);

    return parts.length > 0 ? `<div class="reader-mode">${parts.join("")}</div>` : null;
  }

  // Рендер agent-mode: raw markdown в монопространстве
  function renderAgentMode(parsed) {
    if (!parsed || !parsed.raw_markdown) {
      return null;
    }
    return `
      <div id="task-raw-description" class="task-description-raw" style="display:none">
        ${escapeHtml(parsed.raw_markdown)}
      </div>
    `;
  }

  async function openTaskModal(id) {
    const r = await fetch("/api/tasks/" + id);
    if (!r.ok) return;
    const { задача: t } = await r.json();

    // Пытаемся получить парсированное description (от сервера)
    let serverParsed = null;
    const rParsed = await fetch("/api/tasks/" + id + "/parsed");
    if (rParsed.ok) {
      const pData = await rParsed.json();
      serverParsed = pData.parsed;
    }

    // Парсим описание на клиенте для reader-mode v2 (S6.2)
    const clientParsed = parseTaskDescription(t.description || "");

    $("#modal-task-title").textContent = `#${t.id.slice(0, 6)} · ${t.title}`;
    $("#modal-task-body").innerHTML = renderTaskBody(t, serverParsed, clientParsed);
    bindTaskActions(t);
    bindReaderMode(serverParsed);
    bindReaderModeV2(t, clientParsed);
    $("#modal-task").hidden = false;
  }

  /**
   * Render reader-mode v2 (S6.2): TL;DR, questions/options, acceptance, tech details collapsed.
   * Returns HTML string or null if description is empty.
   */
  function renderReaderModeV2(t, clientParsed) {
    const { tldr, questions, acceptance, raw } = clientParsed;
    const hasContent = tldr || questions.length || acceptance.length || raw.trim();
    if (!hasContent) return null;

    const parts = [];

    // TL;DR block
    if (tldr) {
      parts.push(`
        <div class="tldr-block">
          <div class="tldr-block-label">${escapeHtml(i18n("task.tldr_label"))}</div>
          <div class="tldr-block-text">${escapeHtml(tldr)}</div>
        </div>
      `);
    }

    // Questions / options block
    if (questions.length) {
      let qHtml = `<div class="questions-block">
        <div class="questions-block-label">${escapeHtml(i18n("task.questions_label"))}</div>`;
      questions.forEach((q, qi) => {
        if (q.question) {
          qHtml += `<div class="questions-block-question">${escapeHtml(q.question)}</div>`;
        }
        if (q.options.length) {
          qHtml += `<div class="questions-options-row">`;
          q.options.forEach((opt, oi) => {
            qHtml += `<button type="button" class="option-button" data-qi="${qi}" data-oi="${oi}" data-task-id="${escapeAttr(t.id)}" title="${escapeAttr(opt)}">${escapeHtml(opt)}</button>`;
          });
          qHtml += `</div>`;
        }
        qHtml += `<div class="questions-custom-row">
          <textarea class="questions-custom-textarea" data-qi="${qi}" placeholder="${escapeAttr(i18n("task.your_answer_placeholder"))}" rows="2"></textarea>
          <button type="button" class="questions-send-btn" data-qi="${qi}" data-task-id="${escapeAttr(t.id)}">${escapeHtml(i18n("task.send_answer"))}</button>
        </div>`;
      });
      qHtml += `</div>`;
      parts.push(qHtml);
    }

    // Acceptance checklist
    if (acceptance.length) {
      // Load saved state from localStorage
      let savedState = [];
      try {
        savedState = JSON.parse(localStorage.getItem("acceptance_" + t.id) || "[]");
      } catch (_) { savedState = []; }

      let acHtml = `<div class="acceptance-block" id="acceptance-block-${escapeAttr(t.id)}">
        <div class="acceptance-block-label">${escapeHtml(i18n("task.acceptance_label"))} (${savedState.filter(Boolean).length} из ${acceptance.length})</div>`;
      acceptance.forEach((item, idx) => {
        const checked = savedState[idx] === true;
        acHtml += `<div class="acceptance-item${checked ? " checked" : ""}">
          <input type="checkbox" id="ac-${escapeAttr(t.id)}-${idx}"
                 data-ac-task="${escapeAttr(t.id)}" data-ac-idx="${idx}"
                 ${checked ? "checked" : ""}
                 aria-label="${escapeAttr(item)}">
          <label for="ac-${escapeAttr(t.id)}-${idx}">${escapeHtml(item)}</label>
        </div>`;
      });
      acHtml += `</div>`;
      parts.push(acHtml);
    }

    // Tech details — collapsed by default
    if (raw.trim()) {
      parts.push(`
        <div class="tech-collapsed" id="tech-details-${escapeAttr(t.id)}">
          <button type="button" class="tech-toggle-btn" data-tech-toggle="${escapeAttr(t.id)}" aria-expanded="false">
            <span class="tech-toggle-arrow">▸</span>
            <span>${escapeHtml(i18n("task.tech_details_label"))}</span>
          </button>
          <div class="tech-content" id="tech-content-${escapeAttr(t.id)}" hidden>
            ${escapeHtml(raw)}
          </div>
        </div>
      `);
    }

    return `<div class="task-modal-readermode">${parts.join("")}</div>`;
  }

  function renderTaskBody(t, parsed, clientParsed) {
    const created = new Date(t.created_at * 1000).toLocaleString(dtLocale());
    const updated = new Date(t.updated_at * 1000).toLocaleString(dtLocale());
    const createdUpdated = i18n("task.meta.created_updated")
      .replace("{created}", created)
      .replace("{updated}", updated);
    const comments = (t.comments || []).map((c) =>
      `<div class="entry">
        <span class="when">${new Date(c.created_at * 1000).toLocaleTimeString(dtLocale())}</span>
        <span class="who">${escapeHtml(c.author)}</span>${escapeHtml(c.text)}
      </div>`,
    ).join("") || `<div class="entry" style="color:var(--muted)">${i18n("task.history.quiet")}</div>`;
    const subtasks = (t.subtasks || []).map((s) =>
      `<div class="sub">#${s.id.slice(0, 6)} · ${escapeHtml(statusLabel(s.status))} · ${escapeHtml(displayRole(s.assignee) || i18n("task.subtasks.no_assignee"))} · ${escapeHtml(s.title)}</div>`,
    ).join("") || `<div style="color:var(--muted)">${i18n("task.subtasks.none")}</div>`;
    const result = t.result
      ? `<pre class="result-block">${escapeHtml(JSON.stringify(t.result, null, 2))}</pre>`
      : `<div style="color:var(--muted)">${i18n("task.result.none")}</div>`;
    const labels = (t.labels && t.labels.length)
      ? t.labels.map((l) => `<code>${escapeHtml(l)}</code>`).join(" ")
      : "—";
    const blockedBy = t.blocked_by || [];
    const blocking  = t.blocking  || [];
    const blockedByHtml = blockedBy.length
      ? blockedBy.map((b) => `<span class="task-ref" data-task-ref="${b.id}">#${b.id.slice(0,6)} ${escapeHtml(b.title.slice(0,40))}</span>`).join(" ")
      : `<span style="color:var(--muted)">${i18n("task.deps.none")}</span>`;
    const blockingHtml = blocking.length
      ? blocking.map((b) => `<span class="task-ref" data-task-ref="${b.id}">#${b.id.slice(0,6)} ${escapeHtml(b.title.slice(0,40))}</span>`).join(" ")
      : `<span style="color:var(--muted)">${i18n("task.deps.none")}</span>`;

    return `
      <div class="task-meta">
        <span class="pill status-${escapeHtml(t.status)}">${escapeHtml(statusLabel(t.status))}</span>
        <span class="pill role">${escapeHtml(displayRole(t.assignee) || i18n("task.meta.unassigned"))}</span>
        <span class="pill prio-${escapeHtml(t.priority)}">${escapeHtml(t.priority)}</span>
        <span class="pill">labels: ${labels}</span>
        <button class="edit-btn" id="btn-edit" title="${i18n("task.meta.edit_title")}">${i18n("task.meta.edit_btn")}</button>
      </div>
      <div style="color:var(--muted);font-size:12px;margin-top:6px">
        ${createdUpdated}
      </div>

      <div id="view-mode">
        <h3>${i18n("task.section.description")}</h3>
        ${(function() {
          // Reader-mode v2 (S6.2): try client-parsed first
          if (clientParsed) {
            const v2 = renderReaderModeV2(t, clientParsed);
            if (v2) return v2;
          }
          // Fallback to server-parsed (S5.5 reader-mode)
          if (parsed && parsed.has_structure) {
            return renderUserMode(parsed) + (parsed.raw_markdown ? renderAgentMode(parsed) : "");
          }
          // Final fallback: plain text
          return `<div style="white-space:pre-wrap">${escapeHtml(t.description || "—")}</div>`;
        })()}
      </div>

      <form id="edit-mode" hidden>
        <h3>${i18n("task.section.edit")}</h3>
        <label>${i18n("modal.new.field.title")}<input name="title" value="${escapeAttr(t.title)}"></label>
        <label>${i18n("modal.new.field.description")}<textarea name="description" rows="8">${escapeHtml(t.description || "")}</textarea></label>
        <div class="row">
          <label>${i18n("modal.new.field.priority")}
            <select name="priority">
              ${["P0", "P1", "P2", "P3"].map((p) => `<option value="${p}"${p === t.priority ? " selected" : ""}>${p}</option>`).join("")}
            </select>
          </label>
          <label>${i18n("task.field.assignee")}
            <select name="assignee">
              <option value=""${!t.assignee ? " selected" : ""}>${i18n("common.none_dash")}</option>
              ${["тимлид", "бэкенд", "qa", "архитектор", "frontend", "devops", "техписатель", "пользователь"].map((r) => `<option value="${r}"${r === t.assignee ? " selected" : ""}>${escapeHtml(displayRole(r))}</option>`).join("")}
            </select>
          </label>
          <label>${i18n("task.field.status")}
            <select name="status">
              ${getStatusLabels().map(([k, v]) => `<option value="${k}"${k === t.status ? " selected" : ""}>${v}</option>`).join("")}
            </select>
          </label>
        </div>
        <div class="actions">
          <button type="button" id="btn-edit-cancel">${i18n("common.cancel")}</button>
          <button type="submit" class="primary">${i18n("common.save")}</button>
        </div>
      </form>

      <h3><span class="ico">🔗</span> ${i18n("task.section.deps")}</h3>
      <div class="deps-block">
        <div><b>${i18n("task.deps.blocked_by")}</b> ${blockedByHtml}</div>
        <div><b>${i18n("task.deps.blocking")}</b> ${blockingHtml}</div>
        <form class="dep-form" data-task-id="${t.id}">
          <input name="depends_on" placeholder="${i18n("task.deps.add_placeholder")}">
          <button type="submit">${i18n("task.deps.add_btn")}</button>
        </form>
      </div>

      <h3>${i18n("task.section.subtasks").replace("{n}", String((t.subtasks || []).length))}</h3>
      <div class="subtasks">${subtasks}</div>

      <h3>${i18n("task.section.result")}</h3>
      ${result}

      <h3>${i18n("task.section.history")}</h3>
      <div class="history">${comments}</div>

      <form class="comment-form" data-task-id="${t.id}">
        <input name="text" placeholder="${i18n("task.comment.placeholder")}">
        <button type="submit">${i18n("common.add")}</button>
      </form>

      <div class="actions-block">${renderActions(t)}</div>
    `;
  }

  function renderActions(t) {
    const buttons = [];
    if (t.status === "todo") {
      buttons.push(`<button data-action="status" data-value="wip">${i18n("task.btn.claim")}</button>`);
      buttons.push(`<button class="danger" data-action="delete">${i18n("task.btn.delete")}</button>`);
    }
    if (t.status === "wip") {
      buttons.push(`<button data-action="status" data-value="review">${i18n("task.btn.send_review")}</button>`);
      buttons.push(`<button data-action="status" data-value="blocked">${i18n("task.btn.block")}</button>`);
      buttons.push(`<button data-action="status" data-value="todo">${i18n("task.btn.back_to_queue")}</button>`);
    }
    if (t.status === "needs_approval") {
      buttons.push(`<button class="approve" data-action="approve">${i18n("task.btn.approve")}</button>`);
      buttons.push(`<button class="reject" data-action="reject">${i18n("task.btn.reject")}</button>`);
    }
    if (t.status === "review") {
      buttons.push(`<button class="approve" data-action="status" data-value="done">${i18n("task.btn.accept")}</button>`);
      buttons.push(`<button data-action="status" data-value="wip">${i18n("task.btn.rework")}</button>`);
    }
    if (t.status === "done") {
      buttons.push(`<button data-action="status" data-value="wip">${i18n("task.btn.reopen")}</button>`);
      buttons.push(`<button class="danger" data-action="delete">${i18n("task.btn.delete")}</button>`);
    }
    if (t.status === "blocked") {
      buttons.push(`<button data-action="status" data-value="todo">${i18n("task.btn.unblock")}</button>`);
    }
    return buttons.join(" ");
  }

  function bindTaskActions(t) {
    const root = $("#modal-task-body");
    const btnEdit = root.querySelector("#btn-edit");
    const btnCancel = root.querySelector("#btn-edit-cancel");
    const view = root.querySelector("#view-mode");
    const edit = root.querySelector("#edit-mode");
    if (btnEdit) btnEdit.addEventListener("click", () => { view.hidden = true; edit.hidden = false; });
    if (btnCancel) btnCancel.addEventListener("click", () => { edit.hidden = true; view.hidden = false; });
    if (edit) {
      edit.addEventListener("submit", async (e) => {
        e.preventDefault();
        const fd = new FormData(edit);
        const body = {
          title: fd.get("title"),
          description: fd.get("description"),
          priority: fd.get("priority"),
          assignee: fd.get("assignee") || null,
          status: fd.get("status"),
        };
        const r = await fetch("/api/tasks/" + t.id, {
          method: "PATCH",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify(body),
        });
        if (!r.ok) {
          const err = await r.json().catch(() => ({}));
          alert(i18n("modal.task.save_failed") + (err.причина || err.reason || r.status));
          return;
        }
        await openTaskModal(t.id);
        refresh();
      });
    }
    root.querySelectorAll(".deps-block [data-task-ref]").forEach((el) =>
      el.addEventListener("click", () => openTaskModal(el.dataset.taskRef)),
    );
    const depForm = root.querySelector(".dep-form");
    if (depForm) {
      depForm.addEventListener("submit", async (e) => {
        e.preventDefault();
        const id = depForm.depends_on.value.trim();
        if (!id) return;
        const r = await fetch(`/api/tasks/${t.id}/dependencies`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ depends_on: id }),
        });
        if (!r.ok) {
          const err = await r.json().catch(() => ({}));
          alert(i18n("modal.task.dep_failed") + (err.причина || err.reason || r.status));
          return;
        }
        depForm.depends_on.value = "";
        await openTaskModal(t.id);
      });
    }
    root.querySelectorAll("[data-action]").forEach((btn) => {
      btn.addEventListener("click", async () => {
        const action = btn.dataset.action;
        if (action === "status") {
          await fetch("/api/tasks/" + t.id, {
            method: "PATCH",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ status: btn.dataset.value }),
          });
        } else if (action === "approve") {
          await fetch("/api/tasks/" + t.id + "/approve", { method: "POST" });
        } else if (action === "reject") {
          await fetch("/api/tasks/" + t.id + "/reject", { method: "POST" });
        } else if (action === "delete") {
          const delMsg = i18n("modal.task.delete_confirm").replace("{title}", t.title.slice(0, 60));
          if (!(await customConfirm(delMsg))) return;
          await fetch("/api/tasks/" + t.id, { method: "DELETE" });
          closeModal("modal-task");
          refresh();
          return;
        }
        await openTaskModal(t.id);
        refresh();
      });
    });
    const form = root.querySelector(".comment-form");
    if (form) {
      form.addEventListener("submit", async (e) => {
        e.preventDefault();
        const text = form.text.value.trim();
        if (!text) return;
        await fetch("/api/tasks/" + t.id + "/comment", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ author: "пользователь", text }),
        });
        form.text.value = "";
        await openTaskModal(t.id);
      });
    }
  }

  // Reader mode: переключение между user-mode и raw-mode (S5.5)
  function bindReaderMode(parsed) {
    if (!parsed) return;

    const root = $("#modal-task-body");

    // Toggle raw (S5.5) — кнопка «Технические детали ↓» / «↑ Свернуть»
    const btnToggleRaw = root.querySelector("#btn-toggle-raw");
    const rawEl = root.querySelector("#task-raw-description");
    if (btnToggleRaw && rawEl) {
      btnToggleRaw.addEventListener("click", () => {
        const isVisible = rawEl.style.display !== "none";
        rawEl.style.display = isVisible ? "none" : "block";
        btnToggleRaw.textContent = isVisible
          ? i18n("task.reader.show_raw")
          : i18n("task.reader.hide_raw");
      });
    }

    // Совместимость: старые кнопки show/hide agent-mode
    const btnShowAgent = root.querySelector("#btn-show-agent-mode");
    const btnHideAgent = root.querySelector("#btn-hide-agent-mode");
    const readerMode = root.querySelector(".reader-mode");
    const agentMode = root.querySelector(".agent-mode");

    if (btnShowAgent) {
      btnShowAgent.addEventListener("click", () => {
        if (readerMode) readerMode.hidden = true;
        if (agentMode) agentMode.hidden = false;
      });
    }

    if (btnHideAgent) {
      btnHideAgent.addEventListener("click", () => {
        if (readerMode) readerMode.hidden = false;
        if (agentMode) agentMode.hidden = true;
      });
    }

    // Обработка кликов на кнопки вариантов (option-btn)
    root.querySelectorAll(".option-btn").forEach((btn) => {
      btn.addEventListener("click", async (e) => {
        e.preventDefault();
        const optionValue = btn.dataset.optionValue;
        const optionLabel = btn.textContent.trim();

        // Добавляем комментарий с выбранным вариантом
        const taskId = btn.closest("[data-task-id]")?.dataset.taskId ||
                      root.closest("[data-task-id]")?.dataset.taskId;
        if (!taskId) return;

        const text = `Выбран вариант: ${optionLabel}`;
        await fetch(`/api/tasks/${taskId}/comment`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ author: "пользователь", text }),
        });

        // Обновляем модалку чтобы показать новый комментарий
        const taskId2 = $("#modal-task-title").textContent.match(/#([a-z0-9]+)/)?.[1];
        if (taskId2) {
          await openTaskModal(taskId2);
        }
      });
    });
  }

  /**
   * bindReaderModeV2 — привязывает обработчики для reader-mode v2 (S6.2):
   * - option-button: добавляет комментарий, перезагружает модалку
   * - send-btn: отправляет textarea как комментарий
   * - acceptance checkboxes: сохраняют state в localStorage
   * - tech-toggle-btn: разворачивает/сворачивает технические детали
   */
  function bindReaderModeV2(t, clientParsed) {
    const root = $("#modal-task-body");
    if (!root || !clientParsed) return;

    // --- Option buttons (pill) ---
    root.querySelectorAll(".option-button").forEach((btn) => {
      btn.addEventListener("click", async () => {
        const optText = btn.title || btn.textContent.trim();
        const qi = btn.dataset.qi;
        const oi = btn.dataset.oi;
        const q = clientParsed.questions[qi];
        const questionText = q ? q.question : "";
        const commentText = questionText
          ? `Ответ: вариант ${parseInt(oi, 10) + 1} (${optText}) на вопрос: ${questionText}`
          : `Ответ: вариант ${parseInt(oi, 10) + 1} (${optText})`;

        await fetch(`/api/tasks/${t.id}/comment`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ author: "пользователь", text: commentText }),
        });
        await openTaskModal(t.id);
      });
    });

    // --- Send buttons (custom answer textarea) ---
    root.querySelectorAll(".questions-send-btn").forEach((btn) => {
      btn.addEventListener("click", async () => {
        const qi = btn.dataset.qi;
        const textarea = root.querySelector(`.questions-custom-textarea[data-qi="${qi}"]`);
        if (!textarea) return;
        const text = textarea.value.trim();
        if (!text) return;

        const q = clientParsed.questions[qi];
        const questionText = q ? q.question : "";
        const commentText = questionText
          ? `Ответ: ${text} (на вопрос: ${questionText})`
          : `Ответ: ${text}`;

        await fetch(`/api/tasks/${t.id}/comment`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ author: "пользователь", text: commentText }),
        });
        await openTaskModal(t.id);
      });
    });

    // --- Acceptance checkboxes — persist state to localStorage ---
    root.querySelectorAll("[data-ac-task]").forEach((cb) => {
      cb.addEventListener("change", () => {
        const taskId = cb.dataset.acTask;
        const idx = parseInt(cb.dataset.acIdx, 10);
        const n = clientParsed.acceptance.length;

        // Load current state
        let state = [];
        try { state = JSON.parse(localStorage.getItem("acceptance_" + taskId) || "[]"); } catch (_) { state = []; }
        while (state.length < n) state.push(false);

        state[idx] = cb.checked;
        localStorage.setItem("acceptance_" + taskId, JSON.stringify(state));

        // Update visual checked state
        const item = cb.closest(".acceptance-item");
        if (item) item.classList.toggle("checked", cb.checked);

        // Update counter label
        const labelEl = root.querySelector(`#acceptance-block-${taskId} .acceptance-block-label`);
        if (labelEl) {
          const doneCount = state.filter(Boolean).length;
          labelEl.textContent = `${i18n("task.acceptance_label")} (${doneCount} из ${n})`;
        }
      });
    });

    // --- Tech details toggle ---
    root.querySelectorAll("[data-tech-toggle]").forEach((btn) => {
      btn.addEventListener("click", () => {
        const taskId = btn.dataset.techToggle;
        const wrapper = root.querySelector(`#tech-details-${taskId}`);
        const content = root.querySelector(`#tech-content-${taskId}`);
        const arrow = btn.querySelector(".tech-toggle-arrow");
        if (!content) return;

        const isExpanded = btn.getAttribute("aria-expanded") === "true";
        content.hidden = isExpanded;
        btn.setAttribute("aria-expanded", isExpanded ? "false" : "true");
        if (wrapper) {
          wrapper.className = isExpanded ? "tech-collapsed" : "tech-expanded";
        }
      });
    });
  }

  // ===================== New-task modal =====================
  // F1 (ADR-009 Phase 1.7): загрузка ролей текущего отдела для assignee dropdown.
  async function loadAssigneeOptions() {
    const sel = $("#new-task-assignee");
    if (!sel) return;
    const dept = currentDepartment();
    sel.innerHTML = '<option value="" disabled selected>загрузка…</option>';
    try {
      const r = await fetch(`/api/departments/${encodeURIComponent(dept)}/roles`);
      if (!r.ok) throw new Error("HTTP " + r.status);
      const data = await r.json();
      const opts = [];
      if (data.lead && data.lead.name) {
        opts.push(`<option value="${escapeHtml(data.lead.name)}" selected>${escapeHtml(displayRole(data.lead.name))} (lead)</option>`);
      }
      (data.specialists || []).forEach((r) => {
        opts.push(`<option value="${escapeHtml(r.name)}">${escapeHtml(displayRole(r.name))}</option>`);
      });
      opts.push(`<option value="">${i18n("common.none_dash") || "— нет —"}</option>`);
      sel.innerHTML = opts.join("");
    } catch (e) {
      console.error("loadAssigneeOptions:", e);
      sel.innerHTML = '<option value="" disabled>ошибка загрузки ролей</option>';
    }
  }

  function openNewTaskModal() {
    $("#form-new-task").reset();
    loadAssigneeOptions();
    $("#modal-new").hidden = false;
  }
  $("#form-new-task").addEventListener("submit", async (e) => {
    e.preventDefault();
    const form = e.target;
    // ADR-003 §2.4.2 + ADR-009: задача создаётся в текущем активном отделе.
    // Используем существующую функцию currentDepartment() (читает ключ
    // 'devboard-current-department', не как в ADR-003 с двоеточием).
    const currentDept = currentDepartment();
    const modelHintVal = form.model_hint ? form.model_hint.value : "auto";
    const body = {
      title: form.title.value.trim(),
      description: form.description.value,
      priority: form.priority.value,
      assignee: form.assignee.value || null,
      requires_approval: form.requires_approval.checked,
      model_hint: modelHintVal === "auto" ? null : modelHintVal,
      department_id: currentDept,
    };
    const r = await fetch("/api/tasks", {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        "X-Department": currentDept,
      },
      body: JSON.stringify(body),
    });
    if (!r.ok) {
      const err = await r.json().catch(() => ({}));
      alert(i18n("modal.task.create_failed") + (err.причина || err.reason || r.status));
      return;
    }
    closeModal("modal-new");
    refresh();
  });
  function closeModal(id) { $("#" + id).hidden = true; }
  $$("[data-close]").forEach((btn) =>
    btn.addEventListener("click", () => closeModal(btn.dataset.close)),
  );
  $("#btn-new-task").addEventListener("click", openNewTaskModal);
  // CTA внутри empty-state колонки todo
  $$('[data-empty-action="create-task"]').forEach((btn) =>
    btn.addEventListener("click", openNewTaskModal),
  );
  $("#search").addEventListener("input", () => refresh());

  // ===================== Settings: Replay tour =====================
  document.getElementById('btn-replay-tour')?.addEventListener('click', () => {
    if (window.PrideTour) {
      window.PrideTour.reset();
    }
  });

  // ===================== Demo mode =====================

  // Check if demo tasks exist and toggle visibility of Clear-demo buttons
  async function refreshDemoState(tasks) {
    const hasDemoTasks = tasks && tasks.some(t => Array.isArray(t.labels) && t.labels.includes('demo'));
    const btnTopbarClear = document.getElementById('btn-topbar-demo-clear');
    const btnTopbarLoad  = document.getElementById('btn-topbar-demo');
    const btnSettingsClear = document.getElementById('btn-demo-clear');
    if (btnTopbarClear)  btnTopbarClear.hidden  = !hasDemoTasks;
    if (btnTopbarLoad)   btnTopbarLoad.hidden   = !!hasDemoTasks;
    if (btnSettingsClear) btnSettingsClear.disabled = false;
  }

  // Show the demo confirmation modal, resolve true/false
  function openDemoConfirmModal() {
    return new Promise((resolve) => {
      const dlg = document.getElementById('modal-demo-confirm');
      if (!dlg) { resolve(false); return; }
      dlg.hidden = false;
      const okBtn     = document.getElementById('btn-demo-confirm-ok');
      const cancelBtn = document.getElementById('btn-demo-confirm-cancel');
      const closeBtn  = document.getElementById('btn-demo-confirm-close');
      okBtn.focus();

      function cleanup() {
        dlg.hidden = true;
        okBtn.removeEventListener('click', onOk);
        cancelBtn.removeEventListener('click', onCancel);
        closeBtn.removeEventListener('click', onCancel);
        dlg.removeEventListener('keydown', onKey);
      }
      function onOk()     { cleanup(); resolve(true); }
      function onCancel() { cleanup(); resolve(false); }
      function onKey(e) { if (e.key === 'Escape') onCancel(); }

      okBtn.addEventListener('click', onOk);
      cancelBtn.addEventListener('click', onCancel);
      closeBtn.addEventListener('click', onCancel);
      dlg.addEventListener('keydown', onKey);
    });
  }

  // Show brief toast-style notification (reuse existing toast if present, else log)
  function showDemoToast(msgKey, fallback) {
    const msg = i18n(msgKey) || fallback;
    // Try to show in a status element if exists, otherwise console
    const el = document.getElementById('demo-toast-msg');
    if (el) {
      el.textContent = msg;
      el.hidden = false;
      setTimeout(() => { el.hidden = true; }, 3000);
    } else {
      console.info('[demo]', msg);
    }
  }

  async function loadDemoData() {
    const confirmed = await openDemoConfirmModal();
    if (!confirmed) return;

    const btns = [
      document.getElementById('btn-topbar-demo'),
      document.getElementById('btn-demo-create'),
    ].filter(Boolean);
    btns.forEach(b => { b.disabled = true; b.textContent = i18n('demo.loading') || 'Loading…'; });

    try {
      const r = await fetch('/api/demo', { method: 'POST' });
      if (r.status === 409) {
        showDemoToast('demo.alreadyLoaded', 'Demo already loaded. Click «Clear demo» to reset.');
        return;
      }
      const data = await r.json();
      if (data.already_exists) {
        showDemoToast('demo.alreadyLoaded', 'Demo already loaded. Click «Clear demo» to reset.');
      } else {
        showDemoToast('demo.loaded', 'Demo data loaded');
      }
      await refresh();
    } catch(e) {
      console.error('Demo create error', e);
    } finally {
      btns.forEach(b => { b.disabled = false; b.dataset.i18nKey = null; });
      // Re-apply i18n labels
      const loadBtn = document.getElementById('btn-topbar-demo');
      const createBtn = document.getElementById('btn-demo-create');
      if (loadBtn)   loadBtn.textContent   = i18n('demo.btn_load')   || 'Load demo';
      if (createBtn) createBtn.textContent = i18n('settings.demo.create') || 'Try with example data';
    }
  }

  async function clearDemoData() {
    const btns = [
      document.getElementById('btn-topbar-demo-clear'),
      document.getElementById('btn-demo-clear'),
    ].filter(Boolean);
    btns.forEach(b => { b.disabled = true; });

    try {
      await fetch('/api/demo', { method: 'DELETE' });
      showDemoToast('demo.cleared', 'Demo data cleared');
      await refresh();
    } catch(e) {
      console.error('Demo clear error', e);
    } finally {
      btns.forEach(b => { b.disabled = false; });
    }
  }

  // Wire up all demo buttons (topbar + settings panel)
  document.getElementById('btn-topbar-demo')?.addEventListener('click', loadDemoData);
  document.getElementById('btn-topbar-demo-clear')?.addEventListener('click', clearDemoData);
  document.getElementById('btn-demo-create')?.addEventListener('click', loadDemoData);
  document.getElementById('btn-demo-clear')?.addEventListener('click', clearDemoData);

  // ===================== Team controls =====================
  async function refreshTeamStatus() {
    const r = await fetch("/api/team/status");
    if (!r.ok) return;
    const s = await r.json();
    const badge = $("#team-status");
    const autoLabel = document.querySelector(".auto-toggle");
    const autoCheck = $("#auto-mode-toggle");

    // Авто-режим (бейдж)
    autoCheck.checked = !!s.auto_mode;
    autoLabel.classList.toggle("on", !!s.auto_mode);
    if (s.auto_mode) {
      autoLabel.title = (s.auto_pause_reason ? i18n("team.auto.paused") : i18n("team.auto.enabled"))
        .replace("{n}", s.starts_last_hour)
        .replace("{reason}", s.auto_pause_reason || "");
    } else {
      autoLabel.title = i18n("topbar.auto_title");
    }

    // Статус команды
    const startGroup = document.getElementById("start-btn-group");
    const startedAs  = document.getElementById("team-started-as");
    if (s.status === "running") {
      badge.textContent = i18n("team.status.running");
      badge.className = "status running";
      if (startGroup) startGroup.hidden = true;
      $("#btn-stop").hidden = false;
      // F1 (1.6): показываем роль активной сессии
      if (startedAs) {
        const roleSlug = s.role || "managing-director";
        const roleName = roleSlug === "managing-director"
          ? (i18n("managingDirector.label") || "Управляющий")
          : displayRole(roleSlug);
        const label = i18n("team.started_as").replace("{role}", roleName)
          || ("Запущен: " + roleName);
        startedAs.textContent = label;
        startedAs.hidden = false;
      }
    } else if (s.auto_mode && s.auto_pause_reason) {
      badge.textContent = i18n("team.status.auto_paused");
      badge.className = "status auto-paused";
      if (startGroup) startGroup.hidden = false;
      $("#btn-stop").hidden = true;
      if (startedAs) startedAs.hidden = true;
    } else {
      badge.textContent = i18n("team.status.stopped");
      badge.className = "status stopped";
      if (startGroup) startGroup.hidden = false;
      $("#btn-stop").hidden = true;
      if (startedAs) startedAs.hidden = true;
    }
  }

  // ===================== Live toggle =====================
  const liveSection = document.getElementById("live");
  const liveToggleBtn = document.getElementById("live-toggle");
  const liveOpen = localStorage.getItem("devboard-live-open") === "1";
  if (liveOpen) liveSection.classList.add("open");
  liveToggleBtn.setAttribute("aria-expanded", liveOpen ? "true" : "false");
  liveToggleBtn.addEventListener("click", () => {
    const willOpen = !liveSection.classList.contains("open");
    liveSection.classList.toggle("open", willOpen);
    liveToggleBtn.setAttribute("aria-expanded", willOpen ? "true" : "false");
    localStorage.setItem("devboard-live-open", willOpen ? "1" : "0");
    // Скроллим в конец при открытии
    if (willOpen) {
      const body = document.getElementById("live-body");
      body.scrollTop = body.scrollHeight;
    }
  });

  $("#auto-mode-toggle").addEventListener("change", async (e) => {
    await fetch("/api/team/auto", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ enabled: e.target.checked }),
    });
    refreshTeamStatus();
  });
  // ===================== F1 (1.6): team start with role dropdown =====================
  // Запуск команды с нужной ролью (role = slug отдела или "managing-director" для default)
  async function _teamStart(roleSlug) {
    const expertise = localStorage.getItem("user_expertise") || "non-tech";
    const body = { user_expertise: expertise };
    // managing-director → default (без role), любой другой slug → пробрасываем
    if (roleSlug && roleSlug !== "managing-director") {
      body.role = roleSlug;
    }
    const r = await fetch("/api/team/start", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    });
    if (!r.ok) {
      const err = await r.json().catch(() => ({}));
      alert(i18n("team.start_failed") + (err.reason || err.причина || r.status));
    }
    refreshTeamStatus();
  }

  // Рендер popup-меню ролей на основе _departmentsCache + Управляющий
  function renderStartRolePopup() {
    const popup = document.getElementById("start-role-popup");
    if (!popup) return;
    popup.innerHTML = "";

    // 1) Управляющий (default, всегда первый)
    const mdBtn = document.createElement("button");
    mdBtn.type = "button";
    mdBtn.className = "start-role-item default-role";
    mdBtn.setAttribute("role", "menuitem");
    mdBtn.innerHTML = `<span class="role-ico">🏛</span><span class="role-lbl">${escapeHtml(i18n("managingDirector.label") || "Управляющий")}</span>`;
    mdBtn.addEventListener("click", () => { closeStartRolePopup(); _teamStart("managing-director"); });
    popup.appendChild(mdBtn);

    // 2) Активные отделы из _departmentsCache
    const depts = _departmentsCache || [];
    depts.forEach((d) => {
      const btn = document.createElement("button");
      btn.type = "button";
      btn.className = "start-role-item";
      btn.setAttribute("role", "menuitem");
      const ico = d.icon || "🗂";
      const name = deptDisplayName(d);
      btn.innerHTML = `<span class="role-ico">${escapeHtml(ico)}</span><span class="role-lbl">${escapeHtml(name)}</span>`;
      btn.addEventListener("click", () => { closeStartRolePopup(); _teamStart(d.id); });
      popup.appendChild(btn);
    });
  }

  function openStartRolePopup() {
    const popup = document.getElementById("start-role-popup");
    const chevron = document.getElementById("btn-start-dropdown");
    if (!popup || !chevron) return;
    renderStartRolePopup();
    popup.hidden = false;
    chevron.setAttribute("aria-expanded", "true");
  }

  function closeStartRolePopup() {
    const popup = document.getElementById("start-role-popup");
    const chevron = document.getElementById("btn-start-dropdown");
    if (popup) popup.hidden = true;
    if (chevron) chevron.setAttribute("aria-expanded", "false");
  }

  // Main start button → всегда managing-director (default)
  $("#btn-start").addEventListener("click", () => _teamStart("managing-director"));

  // Chevron → открываем popup
  const _startDropdownBtn = document.getElementById("btn-start-dropdown");
  if (_startDropdownBtn) {
    _startDropdownBtn.addEventListener("click", (e) => {
      e.stopPropagation();
      const popup = document.getElementById("start-role-popup");
      if (popup && !popup.hidden) {
        closeStartRolePopup();
      } else {
        openStartRolePopup();
      }
    });
  }

  // Закрываем popup при клике вне
  document.addEventListener("click", (e) => {
    const group = document.getElementById("start-btn-group");
    if (group && !group.contains(e.target)) {
      closeStartRolePopup();
    }
  });

  // Закрываем popup по Escape
  document.addEventListener("keydown", (e) => {
    if (e.key === "Escape") {
      closeStartRolePopup();
    }
  });

  $("#btn-stop").addEventListener("click", async () => {
    await fetch("/api/team/stop", { method: "POST" });
    refreshTeamStatus();
  });

  // ===================== Live SSE =====================
  // Хранилище всех событий — при переключении режима пере-рендериваем.
  const liveEvents = [];      // [{ts, human, raw}]
  const LIVE_MAX = 2000;       // ограничение, чтобы DOM не задыхался
  let liveModeRaw = localStorage.getItem("devboard-live-raw") === "1";

  function renderLiveItem(item) {
    const text = liveModeRaw ? item.raw : item.human;
    if (!text) return null;
    return `[${item.ts}] ${text}`;
  }

  function renderLiveAll() {
    const body = $("#live-body");
    const lines = [];
    for (const item of liveEvents) {
      const t = renderLiveItem(item);
      if (t) lines.push(t);
    }
    const atBottom = body.scrollHeight - body.scrollTop - body.clientHeight < 30;
    body.textContent = lines.join("\n") + (lines.length ? "\n" : "");
    if (atBottom) body.scrollTop = body.scrollHeight;
  }

  function appendLiveEvent(item) {
    liveEvents.push(item);
    if (liveEvents.length > LIVE_MAX) liveEvents.splice(0, liveEvents.length - LIVE_MAX);
    const body = $("#live-body");
    const t = renderLiveItem(item);
    if (!t) return;
    const atBottom = body.scrollHeight - body.scrollTop - body.clientHeight < 30;
    body.textContent += t + "\n";
    if (atBottom) body.scrollTop = body.scrollHeight;
  }

  // Init toggle (segmented pill — те же стили что у theme-toggle)
  function applyLiveMode(mode) {
    liveModeRaw = mode === "raw";
    localStorage.setItem("devboard-live-raw", liveModeRaw ? "1" : "0");
    $$("[data-live-mode]").forEach((b) =>
      b.classList.toggle("active", b.dataset.liveMode === mode),
    );
    renderLiveAll();
  }
  applyLiveMode(liveModeRaw ? "raw" : "human");
  $$("[data-live-mode]").forEach((b) =>
    b.addEventListener("click", () => applyLiveMode(b.dataset.liveMode)),
  );

  function connectLiveStream() {
    const ev = new EventSource("/api/team/stream");
    ev.onmessage = (e) => {
      try {
        const data = JSON.parse(e.data);
        // Старый формат — простая строка
        if (typeof data === "string") {
          appendLiveEvent({ts: "", human: data, raw: data});
          return;
        }
        appendLiveEvent(data);
      } catch (_) {}
    };
    ev.onerror = () => {
      setTimeout(connectLiveStream, 3000);
      ev.close();
    };
  }

  // ===================== Inbox =====================
  async function refreshInbox() {
    // S9.1: добавляем ?department= для будущей per-dept фильтрации (S9.2).
    const r = await fetch("/api/inbox?department=" + encodeURIComponent(currentDepartment()));
    if (!r.ok) return;
    const inbox = await r.json();
    renderInbox(inbox);
    // S11.2: загружаем inter-dept секции (Lead inbox + Owner escalations)
    try { await refreshInterDeptSections(); } catch (_) { /* non-blocking */ }
  }

  // ===================== S11.2: Inter-department inbox (ADR-005) =====================
  // currentUserRoleSlug(): slug текущего пользователя дашборда.
  // По умолчанию owner ("пользователь"). LocalStorage может хранить override
  // (например, "marketing-lead" если бы у нас был role-switcher).
  function currentUserRoleSlug() {
    try {
      return localStorage.getItem("devboard-current-role") || "пользователь";
    } catch (_) {
      return "пользователь";
    }
  }
  // isCurrentUserLead(): true если owner ИЛИ slug заканчивается на -lead / совпадает с "тимлид"
  function isCurrentUserLead() {
    const slug = currentUserRoleSlug();
    if (!slug) return false;
    const s = slug.toLowerCase();
    if (s === "пользователь" || s === "owner") return true; // owner всегда видит как Lead
    if (s === "тимлид") return true;
    if (s.endsWith("-lead")) return true;
    return false;
  }
  function isCurrentUserOwner() {
    const s = (currentUserRoleSlug() || "").toLowerCase();
    return s === "пользователь" || s === "owner";
  }

  async function refreshInterDeptSections() {
    const leadSection = document.querySelector('[data-section="inter-dept"]');
    const ownerSection = document.querySelector('[data-section="dept-requests"]');
    if (!leadSection && !ownerSection) return;

    const showLead = isCurrentUserLead();
    const showOwner = isCurrentUserOwner();
    if (leadSection) leadSection.hidden = !showLead;
    if (ownerSection) ownerSection.hidden = !showOwner;

    if (!showLead && !showOwner) return;

    // Тянем все задачи (без department-фильтра), фильтруем сами.
    const r = await fetch("/api/tasks?department=__all__");
    if (!r.ok) return;
    const data = await r.json();
    const tasks = data.задачи || data.tasks || [];

    if (showLead) {
      // Inter-dept задачи, направленные в current department,
      // ещё не взятые в работу (status in [todo, needs_approval]).
      const curDept = currentDepartment();
      const incoming = tasks.filter((t) =>
        t.requester_department_id &&
        t.requester_department_id !== t.department_id &&
        t.department_id === curDept &&
        ["todo", "needs_approval"].includes(t.status)
      );
      renderInterDeptList(incoming);
    }

    if (showOwner) {
      // Owner escalations: все cross-dept задачи в needs_approval (P1/P2).
      const escalations = tasks.filter((t) =>
        t.requester_department_id &&
        t.requester_department_id !== t.department_id &&
        t.status === "needs_approval"
      );
      renderDeptRequestsList(escalations);
    }
  }

  // Локализованное имя отдела по id (использует _departmentsCache).
  function _deptNameById(id) {
    if (!id) return "";
    const d = (_departmentsCache || []).find((x) => x.id === id);
    return d ? deptDisplayName(d) : id;
  }
  function _deptIconById(id) {
    if (!id) return "🗂";
    const d = (_departmentsCache || []).find((x) => x.id === id);
    return (d && d.icon) || "🗂";
  }

  function _renderDeptBadge(deptId, variant) {
    const cls = variant === "target" ? "dept-origin-badge is-target" : "dept-origin-badge";
    return `<span class="${cls}">` +
      `<span class="ico">${escapeHtml(_deptIconById(deptId))}</span>` +
      `<span>${escapeHtml(_deptNameById(deptId))}</span>` +
      `</span>`;
  }

  function renderInterDeptList(tasks) {
    const list = document.getElementById("inter-dept-list");
    const count = document.getElementById("inter-dept-count");
    if (!list) return;
    if (count) count.textContent = String(tasks.length);
    list.innerHTML = "";
    if (tasks.length === 0) {
      const hint = document.createElement("div");
      hint.className = "inbox-empty-hint";
      hint.textContent = i18n("inbox.inter_dept.empty");
      list.appendChild(hint);
      return;
    }
    tasks.forEach((t) => {
      const item = document.createElement("div");
      item.className = "inbox-item";
      const requester = t.requester_role_slug || t.reporter || "—";
      item.innerHTML = `
        <div class="ttl" data-task-id="${escapeAttr(t.id)}">${escapeHtml(t.title)}</div>
        <div class="meta">
          <span>#${t.id.slice(0, 6)}</span>
          <span class="priority-chip prio-${escapeAttr(t.priority || "P3")}">${escapeHtml(t.priority || "P3")}</span>
          ${_renderDeptBadge(t.requester_department_id, "origin")}
          <span class="role">${i18n("inbox.from_prefix")}${escapeHtml(displayRole(requester))}</span>
        </div>
        <div class="inbox-actions"></div>
      `;
      const actions = item.querySelector(".inbox-actions");
      // Take into queue → PATCH status=todo + assignee=current role slug
      const takeBtn = document.createElement("button");
      takeBtn.className = "ok";
      takeBtn.textContent = i18n("inbox.inter_dept.take");
      takeBtn.addEventListener("click", (e) => {
        e.stopPropagation();
        interDeptTake(t);
      });
      actions.appendChild(takeBtn);
      // Counter
      const counterBtn = document.createElement("button");
      counterBtn.className = "neutral";
      counterBtn.textContent = i18n("inbox.inter_dept.counter");
      counterBtn.addEventListener("click", (e) => {
        e.stopPropagation();
        openCounterModal(t);
      });
      actions.appendChild(counterBtn);
      item.querySelector(".ttl").addEventListener("click", () => openTaskModal(t.id));
      list.appendChild(item);
    });
  }

  function renderDeptRequestsList(tasks) {
    const list = document.getElementById("dept-requests-list");
    const count = document.getElementById("dept-requests-count");
    if (!list) return;
    if (count) count.textContent = String(tasks.length);
    list.innerHTML = "";
    if (tasks.length === 0) {
      const hint = document.createElement("div");
      hint.className = "inbox-empty-hint";
      hint.textContent = i18n("inbox.dept_requests.empty");
      list.appendChild(hint);
      return;
    }
    tasks.forEach((t) => {
      const item = document.createElement("div");
      item.className = "inbox-item";
      item.innerHTML = `
        <div class="ttl" data-task-id="${escapeAttr(t.id)}">${escapeHtml(t.title)}</div>
        <div class="meta">
          <span>#${t.id.slice(0, 6)}</span>
          <span class="priority-chip prio-${escapeAttr(t.priority || "P3")}">${escapeHtml(t.priority || "P3")}</span>
          ${_renderDeptBadge(t.requester_department_id, "origin")}
          <span aria-hidden="true">→</span>
          ${_renderDeptBadge(t.department_id, "target")}
        </div>
        <div class="inbox-actions"></div>
      `;
      const actions = item.querySelector(".inbox-actions");
      const okBtn = document.createElement("button");
      okBtn.className = "ok";
      okBtn.textContent = i18n("inbox.action.approve");
      okBtn.addEventListener("click", (e) => {
        e.stopPropagation();
        inboxAction(t, "approve").then(refresh).catch(() => {});
      });
      actions.appendChild(okBtn);
      const noBtn = document.createElement("button");
      noBtn.className = "no";
      noBtn.textContent = i18n("inbox.action.reject");
      noBtn.addEventListener("click", (e) => {
        e.stopPropagation();
        inboxAction(t, "reject").then(refresh).catch(() => {});
      });
      actions.appendChild(noBtn);
      item.querySelector(".ttl").addEventListener("click", () => openTaskModal(t.id));
      list.appendChild(item);
    });
  }

  async function interDeptTake(task) {
    // Lead берёт задачу в очередь target department: status=todo, assignee=self.
    const assignee = currentUserRoleSlug();
    try {
      const r = await fetch(`/api/tasks/${encodeURIComponent(task.id)}`, {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ status: "todo", assignee }),
      });
      if (!r.ok) {
        const err = await r.json().catch(() => ({}));
        alert(i18n("inbox.inter_dept.error.take") + (err.причина || err.reason || r.status));
        return;
      }
      refresh();
    } catch (e) {
      console.error("interDeptTake:", e);
    }
  }

  // -------- Counter-proposal modal --------
  let _counterCurrentTask = null;
  function openCounterModal(task) {
    _counterCurrentTask = task;
    const modal = document.getElementById("modal-counter");
    if (!modal) return;
    // Сброс полей
    const form = document.getElementById("form-counter");
    if (form) form.reset();
    document.getElementById("counter-priority").value = "";
    document.getElementById("counter-error").hidden = true;
    document.getElementById("modal-counter-target").innerHTML =
      `<span>${escapeHtml(task.title)}</span> — #${escapeHtml(task.id.slice(0, 6))} (` +
      `${escapeHtml(task.priority || "P3")})`;
    modal.hidden = false;
    setTimeout(() => {
      const ta = form && form.querySelector("textarea[name=comment]");
      if (ta) ta.focus();
    }, 50);
  }

  async function submitCounter(e) {
    e.preventDefault();
    const task = _counterCurrentTask;
    if (!task) return;
    const errBox = document.getElementById("counter-error");
    errBox.hidden = true;
    const priority = document.getElementById("counter-priority").value || null;
    const form = e.target;
    const comment = (form.comment.value || "").trim();
    if (!comment) {
      errBox.textContent = i18n("modal.counter.error.comment_required");
      errBox.hidden = false;
      return;
    }
    const body = { comment };
    if (priority) body.priority = priority;
    try {
      const r = await fetch(`/api/tasks/${encodeURIComponent(task.id)}/counter`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
      });
      if (!r.ok) {
        const err = await r.json().catch(() => ({}));
        errBox.textContent = i18n("modal.counter.error.failed") + " " + (err.причина || err.reason || r.status);
        errBox.hidden = false;
        return;
      }
      closeModal("modal-counter");
      _counterCurrentTask = null;
      refresh();
    } catch (e2) {
      errBox.textContent = i18n("modal.counter.error.failed") + " " + (e2.message || e2);
      errBox.hidden = false;
    }
  }

  // -------- Inter-department create modal --------
  function openInterDeptModal() {
    const modal = document.getElementById("modal-inter-dept");
    if (!modal) return;
    // Заполняем dropdown target = все отделы кроме текущего (и не archived).
    const sel = document.getElementById("inter-dept-target");
    sel.innerHTML = "";
    const cur = currentDepartment();
    (_departmentsCache || []).forEach((d) => {
      if (d.id === cur) return;
      const opt = document.createElement("option");
      opt.value = d.id;
      opt.textContent = deptDisplayName(d);
      sel.appendChild(opt);
    });
    if (sel.options.length === 0) {
      const opt = document.createElement("option");
      opt.value = "";
      opt.textContent = i18n("modal.inter_dept.no_targets");
      opt.disabled = true;
      sel.appendChild(opt);
    }
    // Reset
    const form = document.getElementById("form-inter-dept");
    if (form) {
      form.title.value = "";
      form.description.value = "";
      form.priority.value = "P3";
    }
    document.getElementById("inter-dept-error").hidden = true;
    document.getElementById("inter-dept-capacity-hint").hidden = true;
    // Close new-task modal if open
    closeModal("modal-new");
    modal.hidden = false;
    setTimeout(() => { sel.focus(); }, 50);
    // Capacity hint refresh
    updateInterDeptCapacityHint();
  }

  async function updateInterDeptCapacityHint() {
    const sel = document.getElementById("inter-dept-target");
    const pri = document.getElementById("inter-dept-priority");
    const hint = document.getElementById("inter-dept-capacity-hint");
    if (!sel || !pri || !hint) return;
    const target = sel.value;
    const priority = pri.value || "P3";
    if (!target) { hint.hidden = true; return; }
    try {
      const r = await fetch(
        `/api/departments/${encodeURIComponent(target)}/queue-position?priority=${encodeURIComponent(priority)}`
      );
      if (!r.ok) { hint.hidden = true; return; }
      const data = await r.json();
      const pos = data.position;
      const tot = data.total;
      hint.textContent = i18n("modal.inter_dept.capacity_hint", { position: pos, total: tot });
      hint.classList.toggle("is-busy", pos >= 5);
      hint.hidden = false;
    } catch (_) {
      hint.hidden = true;
    }
  }

  async function submitInterDept(e) {
    e.preventDefault();
    const form = e.target;
    const errBox = document.getElementById("inter-dept-error");
    errBox.hidden = true;
    const target = form.target_department_id.value;
    const title = (form.title.value || "").trim();
    const description = (form.description.value || "").trim();
    const priority = form.priority.value || "P3";
    if (!target) {
      errBox.textContent = i18n("modal.inter_dept.error.no_target");
      errBox.hidden = false;
      return;
    }
    if (!title) {
      errBox.textContent = i18n("modal.inter_dept.error.no_title");
      errBox.hidden = false;
      return;
    }
    const body = {
      title,
      description,
      priority,
      requester_department_id: currentDepartment(),
      requester_role_slug: currentUserRoleSlug(),
    };
    try {
      const r = await fetch(`/api/departments/${encodeURIComponent(target)}/tasks`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
      });
      if (!r.ok) {
        const err = await r.json().catch(() => ({}));
        errBox.textContent = i18n("modal.inter_dept.error.failed") + " " + (err.причина || err.reason || r.status);
        errBox.hidden = false;
        return;
      }
      closeModal("modal-inter-dept");
      refresh();
    } catch (e2) {
      errBox.textContent = i18n("modal.inter_dept.error.failed") + " " + (e2.message || e2);
      errBox.hidden = false;
    }
  }

  // ===== Inbox notifications — пингуем при появлении новых задач =====
  let seenInboxIds = new Set(
    (localStorage.getItem("devboard-seen-inbox") || "").split(",").filter(Boolean)
  );

  function checkInboxNotifications(inbox) {
    const all = [...inbox.approvals, ...inbox.reviews, ...inbox.questions];
    const newOnes = all.filter((t) => !seenInboxIds.has(t.id));
    for (const t of newOnes) {
      let groupName = "Inbox";
      let level = "info";
      if (inbox.approvals.includes(t)) {
        groupName = i18n("inbox.notify.approvals");
        level = "important";   // ⚠ needs_approval — требует действия пользователя
      } else if (inbox.reviews.includes(t)) {
        groupName = i18n("inbox.notify.reviews");
        level = "info";
      } else if (inbox.questions.includes(t)) {
        groupName = i18n("inbox.notify.questions");
        level = "info";
      }
      notify(level, groupName, t.title);
      seenInboxIds.add(t.id);
    }
    // Чистим из seen те id что уже не в inbox (задача ушла из inbox = можно забыть)
    const stillInInbox = new Set(all.map((t) => t.id));
    seenInboxIds = new Set([...seenInboxIds].filter((id) => stillInInbox.has(id)));
    localStorage.setItem("devboard-seen-inbox", [...seenInboxIds].join(","));
  }

  function renderInbox(inbox) {
    checkInboxNotifications(inbox);
    setNavBadge("nav-inbox-count", inbox.total);
    if (inbox.total === 0) {
      $("#inbox-total-hint").textContent = i18n("inbox.total.empty");
    } else {
      $("#inbox-total-hint").textContent = i18n("inbox.total.count").replace("{n}", inbox.total);
    }
    renderInboxGroup("approvals", inbox.approvals, () => [
      { label: i18n("inbox.action.approve"), cls: "ok", action: "approve" },
      { label: i18n("inbox.action.reject"), cls: "no", action: "reject" },
    ]);
    renderInboxGroup("reviews", inbox.reviews, () => [
      { label: i18n("inbox.action.accept"), cls: "ok", action: "accept" },
      { label: i18n("inbox.action.rework"), cls: "", action: "rework" },
    ]);
    renderInboxGroup("questions", inbox.questions, () => [
      { label: i18n("inbox.action.reply"), cls: "ok", action: "reply" },
      { label: i18n("inbox.action.open"), cls: "", action: "open" },
    ]);
  }

  function renderInboxGroup(group, tasks, actionsFn) {
    const container = document.querySelector(`[data-list="${group}"]`);
    document.querySelector(`[data-gcount="${group}"]`).textContent = tasks.length;
    container.innerHTML = "";
    if (tasks.length === 0) {
      const hint = document.createElement("div");
      hint.className = "inbox-empty-hint";
      hint.textContent = i18n("inbox.empty_hint");
      container.appendChild(hint);
      return;
    }
    tasks.forEach((t) => {
      const item = document.createElement("div");
      item.className = "inbox-item";
      if ((t.labels || []).includes("destructive")) item.classList.add("destructive");
      const author = t.assignee !== "пользователь" ? t.assignee : (t.reporter || "—");
      const tldr = extractTldr(t.description);
      item.innerHTML = `
        <div class="ttl" data-task-id="${t.id}">${escapeHtml(t.title)}</div>
        ${tldr ? `<div class="tldr">${escapeHtml(tldr)}</div>` : ""}
        <div class="meta">
          <span>#${t.id.slice(0, 6)}</span>
          <span class="pri">${t.priority}</span>
          <span class="role">${i18n("inbox.from_prefix")}${escapeHtml(displayRole(author))}</span>
          <span>${shortAge(t.created_at)} ${i18n("kanban.card.ago_suffix")}</span>
        </div>
        <div class="inbox-actions"></div>
      `;
      const actionsBox = item.querySelector(".inbox-actions");
      actionsFn(t).forEach((a) => {
        const btn = document.createElement("button");
        btn.className = a.cls;
        btn.textContent = a.label;
        btn.addEventListener("click", (e) => {
          e.stopPropagation();
          inboxAction(t, a.action);
        });
        actionsBox.appendChild(btn);
      });
      item.querySelector(".ttl").addEventListener("click", () => openTaskModal(t.id));
      container.appendChild(item);
    });
  }

  async function inboxAction(t, action) {
    if (action === "open") return openTaskModal(t.id);
    if (action === "reply") {
      const text = await customPrompt(i18n("inbox.reply.title").replace("{title}", t.title.slice(0, 60)), {
        placeholder: i18n("inbox.reply.placeholder"),
      });
      if (text === null || !text.trim()) return;
      // 1. Сохраняем ответ как комментарий (он же зеркалится в чат)
      await fetch(`/api/tasks/${t.id}/comment`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ author: "пользователь", text: text.trim() }),
      });
      // 2. Возвращаем задачу инициатору — теперь её увидит тимлид/бэкенд/qa
      //    при следующем запуске. С твоего стола она уходит.
      const reporter = t.reporter || "тимлид";
      await fetch(`/api/tasks/${t.id}`, {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ status: "todo", assignee: reporter }),
      });
    } else if (action === "approve") {
      await fetch(`/api/tasks/${t.id}/approve`, { method: "POST" });
    } else if (action === "reject") {
      const reason = await customPrompt(i18n("inbox.reject.title"), {
        placeholder: i18n("inbox.reject.placeholder"),
      });
      if (reason === null) return;
      await fetch(`/api/tasks/${t.id}/reject`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ text: reason }),
      });
    } else if (action === "accept") {
      await fetch(`/api/tasks/${t.id}`, {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ status: "done" }),
      });
    } else if (action === "rework") {
      const comment = await customPrompt(i18n("inbox.rework.title"), {
        placeholder: i18n("inbox.rework.placeholder"),
      });
      if (comment === null) return;
      if (comment.trim()) {
        await fetch(`/api/tasks/${t.id}/comment`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ author: "пользователь", text: comment.trim() }),
        });
      }
      await fetch(`/api/tasks/${t.id}`, {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ status: "wip" }),
      });
    }
    refresh();
  }

  // ===================== Archive view =====================
  async function loadArchive() {
    // S9.2: archive фильтруется по текущему отделу (backend reuse /api/tasks?archived=1).
    const url =
      "/api/tasks?archived=1&department=" +
      encodeURIComponent(currentDepartment());
    const r = await fetch(url);
    if (!r.ok) return;
    const data = await r.json();
    const body = $("#archive-body");
    body.innerHTML = "";
    const archived = data.архив || [];
    if (archived.length === 0) {
      body.innerHTML = `<p class="muted">${i18n("archive.empty")}</p>`;
    } else {
      archived.forEach((t) => body.appendChild(renderCard(t)));
    }
  }

  // ===================== Settings view =====================

  // --- S2.1: Settings page state helpers ---
  function settingsGetUiLocale() {
    return localStorage.getItem("locale") || "ru";
  }
  function settingsGetOutputLocale() {
    return localStorage.getItem("output_locale") || "ru";
  }
  function settingsGetModelOverride() {
    return localStorage.getItem("next_model_override") || "auto";
  }

  // Sync the settings page controls from current state (called on open + locale change)
  function settingsSyncControls() {
    // Language
    const uiSel = $("#settings-ui-locale");
    if (uiSel) uiSel.value = settingsGetUiLocale();
    const outSel = $("#settings-output-locale");
    if (outSel) outSel.value = settingsGetOutputLocale();

    // Theme
    const currentTheme = document.documentElement.dataset.theme || "light";
    const lightRadio = $("#settings-theme-light");
    const darkRadio = $("#settings-theme-dark");
    if (lightRadio) lightRadio.checked = currentTheme === "light";
    if (darkRadio) darkRadio.checked = currentTheme === "dark";

    // Auto-mode toggle — mirror topbar checkbox
    const autoCheckbox = $("#settings-auto-mode");
    const topbarAuto = $("#auto-mode-toggle");
    if (autoCheckbox && topbarAuto) autoCheckbox.checked = topbarAuto.checked;

    // Model override
    const modelSel = $("#settings-model-override");
    if (modelSel) modelSel.value = settingsGetModelOverride();
  }

  async function loadSettings() {
    // Sync controls with current state
    settingsSyncControls();
    syncNotificationSettingsUI();

    // Load static info (backups, limits)
    try {
      const r = await fetch("/api/settings/static-info");
      if (r.ok) {
        const info = await r.json();
        // Backups path
        const pathEl = $("#settings-backups-path");
        if (pathEl) pathEl.textContent = info.backups_path || "data/backups/";
        // Last backup
        const lastEl = $("#settings-last-backup");
        if (lastEl) {
          if (info.last_backup) {
            const kb = info.last_backup.size_kb;
            const sizeStr = kb >= 1024
              ? (kb / 1024).toFixed(1) + " MB"
              : kb + " KB";
            lastEl.textContent = info.last_backup.name + " · " + sizeStr;
          } else {
            lastEl.textContent = i18n("settings.backups.none");
          }
        }
        // Router current value
        const routerEl = $("#settings-router-value");
        if (routerEl && info.auto_limits) {
          // Show limits info is already in read-only row; show router model from sidebar
          const routerSummary = $("#router-summary");
          routerEl.textContent = routerSummary
            ? routerSummary.textContent
            : i18n("settings.team.router_placeholder");
        }
      }
    } catch (_) {}

  }

  // --- S2.1: Wire settings controls (once on DOMContentLoaded) ---
  function initSettingsControls() {
    // UI locale dropdown
    const uiSel = $("#settings-ui-locale");
    if (uiSel) {
      uiSel.addEventListener("change", () => {
        const lang = uiSel.value;
        localStorage.setItem("locale", lang);
        // Use locale-switcher's setLocale if available, else call window.setLocale
        if (typeof window.setLocale === "function") {
          window.setLocale(lang);
        }
        // Keep topbar locale-switcher buttons in sync
        document.querySelectorAll(".locale-switcher [data-locale]").forEach((b) => {
          b.setAttribute("aria-pressed", b.dataset.locale === lang ? "true" : "false");
        });
        document.documentElement.setAttribute("lang", lang);
        // Re-sync settings select (i18n might re-render)
        setTimeout(() => { if (uiSel) uiSel.value = lang; }, 50);
      });
    }

    // Output locale dropdown
    const outSel = $("#settings-output-locale");
    if (outSel) {
      outSel.addEventListener("change", () => {
        localStorage.setItem("output_locale", outSel.value);
      });
    }

    // Theme radios — reuse applyTheme() so all side-effects (DOM attr, localStorage,
    // topbar button active state) are applied consistently and in one place.
    document.querySelectorAll("input[name='settings-theme']").forEach((radio) => {
      radio.addEventListener("change", () => {
        if (!radio.checked) return;
        applyTheme(radio.value);
      });
    });

    // Auto-mode toggle — mirrors topbar checkbox bidirectionally
    const settingsAuto = $("#settings-auto-mode");
    if (settingsAuto) {
      settingsAuto.addEventListener("change", () => {
        const topbarAuto = $("#auto-mode-toggle");
        if (topbarAuto && topbarAuto.checked !== settingsAuto.checked) {
          topbarAuto.checked = settingsAuto.checked;
          // Trigger the existing auto-mode handler
          topbarAuto.dispatchEvent(new Event("change"));
        }
      });
    }

    // Model override dropdown
    const modelSel = $("#settings-model-override");
    if (modelSel) {
      modelSel.addEventListener("change", () => {
        localStorage.setItem("next_model_override", modelSel.value);
      });
    }

    // Open backups folder button
    const btnOpenBackups = $("#btn-open-backups");
    if (btnOpenBackups) {
      btnOpenBackups.addEventListener("click", async () => {
        try {
          await fetch("/api/open-folder", { method: "POST", headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ path: "data/backups" }) });
        } catch (_) {
          // Fallback — open relative URL (won't open finder but avoids silent fail)
        }
      });
    }

    // Open tutorial from settings
    const btnOpenTutorial = $("#btn-open-tutorial");
    if (btnOpenTutorial) {
      btnOpenTutorial.addEventListener("click", () => {
        try { localStorage.setItem("devboard-learn-page", "intro"); } catch (_) {}
        switchView("learn");
        setLearnPage("intro");
      });
    }

    // Danger zone: reset tour
    const btnResetTour = $("#btn-reset-tour");
    if (btnResetTour) {
      btnResetTour.addEventListener("click", () => {
        localStorage.removeItem("onboarding_completed");
        localStorage.removeItem("onboarding_completed_at");
        alert(i18n("settings.danger.reset_tour_done"));
      });
    }

    // Danger zone: restart wizard
    const btnResetWizard = $("#btn-reset-wizard");
    if (btnResetWizard) {
      btnResetWizard.addEventListener("click", () => {
        localStorage.removeItem("first_run_done");
        location.reload();
      });
    }

    // Danger zone: clear localStorage
    const btnClearStorage = $("#btn-clear-storage");
    if (btnClearStorage) {
      btnClearStorage.addEventListener("click", () => {
        if (!confirm(i18n("settings.danger.clear_storage_confirm"))) return;
        localStorage.clear();
        location.reload();
      });
    }

    // Expertise toggle
    const expertiseGroup = $("#expertise-toggle-group");
    if (expertiseGroup) {
      const saved = localStorage.getItem("user_expertise") || "non-tech";
      expertiseGroup.querySelectorAll(".toggle-btn").forEach((btn) => {
        btn.classList.toggle("active", btn.dataset.expertise === saved);
        btn.addEventListener("click", () => {
          localStorage.setItem("user_expertise", btn.dataset.expertise);
          expertiseGroup.querySelectorAll(".toggle-btn").forEach((b) =>
            b.classList.toggle("active", b === btn)
          );
        });
      });
    }

    // Keep settings-auto-mode in sync when topbar auto changes
    const topbarAuto = $("#auto-mode-toggle");
    if (topbarAuto) {
      topbarAuto.addEventListener("change", () => {
        const settingsAuto2 = $("#settings-auto-mode");
        if (settingsAuto2) settingsAuto2.checked = topbarAuto.checked;
      });
    }

    // Keep theme radios in sync when topbar theme buttons change
    document.querySelectorAll("[data-theme-set]").forEach((btn) => {
      btn.addEventListener("click", () => {
        const theme = btn.dataset.themeSet;
        const lightR = $("#settings-theme-light");
        const darkR = $("#settings-theme-dark");
        if (lightR) lightR.checked = theme === "light";
        if (darkR) darkR.checked = theme === "dark";
      });
    });

    // Keep settings-ui-locale in sync on locale change
    window.addEventListener("localechange", () => {
      const uiSel2 = $("#settings-ui-locale");
      if (uiSel2) uiSel2.value = settingsGetUiLocale();
    });

    // --- Notification settings ---
    const notifToggle = document.getElementById("settings-notif-toggle");
    if (notifToggle) {
      notifToggle.addEventListener("change", () => {
        setNotificationSettings({ enabled: notifToggle.checked });
      });
    }

    document.querySelectorAll("input[name='settings-notif-level']").forEach((r) => {
      r.addEventListener("change", () => {
        if (r.checked) setNotificationSettings({ level: r.value });
      });
    });

    const permBtn = document.getElementById("btn-notif-request-permission");
    if (permBtn) {
      permBtn.addEventListener("click", () => requestNotifPermission());
    }

    // Initial sync
    syncNotificationSettingsUI();
  }

  // Initialize settings controls right away
  initSettingsControls();

  // ===================== Router / silence / usage badges =====================
  async function refreshRouter() {
    const r = await fetch("/api/router/pick");
    if (!r.ok) return;
    const d = await r.json();
    const badge = $("#router-badge");
    $("#router-summary").textContent = d.model_alias;
    badge.classList.remove("opus", "sonnet", "haiku");
    badge.classList.add(d.model_alias);
    const c = d.counters || {};
    badge.title = i18n("team.router.tooltip")
      .replace("{alias}", d.model_alias)
      .replace("{reason}", d.reason || "")
      .replace("{total}", c.total_workable)
      .replace("{arch}", c.architectural)
      .replace("{triv}", c.trivial)
      .replace("{epics}", c.epics_filtered);
  }

  async function refreshSilence() {
    const r = await fetch("/api/team/silence");
    if (!r.ok) return;
    const d = await r.json();
    const el = $("#silence-badge");
    if (d.silent) { el.hidden = false; el.title = d.reason || ""; }
    else el.hidden = true;
  }

  async function refreshUsage() {
    const r = await fetch("/api/usage");
    if (!r.ok) return;
    const u = await r.json();
    const last = u.last_5h || {sessions:0, turns:0, cost_usd:0};
    $("#usage-summary").textContent = i18n("usage.badge.short")
      .replace("{n}", last.turns)
      .replace("{cost}", last.cost_usd.toFixed(2));
  }

  // ===================== Chat =====================

  // Scroll utilities
  let _unreadChatSinceScroll = 0;
  const chatScrollBtn = document.getElementById('chat-scroll-bottom');
  const chatList = document.getElementById('chat-body');

  function isAtBottom() {
    if (!chatList) return true;
    return chatList.scrollTop + chatList.clientHeight >= chatList.scrollHeight - 50;
  }

  function scrollToBottom(smooth) {
    if (!chatList) return;
    chatList.scrollTo({ top: chatList.scrollHeight, behavior: smooth ? 'smooth' : 'instant' });
    _unreadChatSinceScroll = 0;
    updateScrollBtn();
  }

  function updateScrollBtn() {
    if (!chatScrollBtn) return;
    const atBottom = isAtBottom();
    chatScrollBtn.hidden = atBottom;
    if (_unreadChatSinceScroll > 0 && !atBottom) {
      chatScrollBtn.setAttribute('data-badge', _unreadChatSinceScroll);
    } else {
      chatScrollBtn.removeAttribute('data-badge');
    }
  }

  if (chatList) chatList.addEventListener('scroll', updateScrollBtn);
  if (chatScrollBtn) chatScrollBtn.addEventListener('click', () => scrollToBottom(true));

  async function refreshChat() {
    // S9.1 + ADR-009 §2.7.2:
    //   - currentChatChannel() === "__global__" → общий чат (department_id IS NULL),
    //     собеседник Управляющий. Backend принимает ?department=__global__.
    //   - иначе → чат конкретного отдела, собеседник dev-lead/<dept>-lead.
    const r = await fetch(
      "/api/chat?limit=200&department=" + encodeURIComponent(currentChatChannel())
    );
    if (!r.ok) return;
    const data = await r.json();
    renderChat(data.messages || []);
  }

  // === Browser notifications ===
  let notificationsAllowed = false;
  async function requestNotifPermission() {
    if (!("Notification" in window)) return;
    if (Notification.permission === "granted") { notificationsAllowed = true; return; }
    if (Notification.permission === "denied") return;
    try {
      const p = await Notification.requestPermission();
      notificationsAllowed = (p === "granted");
      // Refresh settings UI to reflect new permission state
      syncNotificationSettingsUI();
    } catch (_) {}
  }
  requestNotifPermission();

  // --- Notification settings helpers ---
  function getNotificationSettings() {
    const enabled = localStorage.getItem("notifications.enabled");
    const level   = localStorage.getItem("notifications.level");
    return {
      enabled: enabled === null ? true : enabled === "true",
      level:   level   || "important",   // 'critical' | 'important' | 'all'
    };
  }

  function setNotificationSettings(patch) {
    if (patch.enabled !== undefined) {
      localStorage.setItem("notifications.enabled", String(patch.enabled));
    }
    if (patch.level !== undefined) {
      localStorage.setItem("notifications.level", patch.level);
    }
    syncNotificationSettingsUI();
  }

  // Sync Settings page controls with current state (called on open and on permission change)
  function syncNotificationSettingsUI() {
    const s = getNotificationSettings();

    const toggleEl = document.getElementById("settings-notif-toggle");
    if (toggleEl) toggleEl.checked = s.enabled;

    document.querySelectorAll("input[name='settings-notif-level']").forEach((r) => {
      r.checked = r.value === s.level;
      r.disabled = !s.enabled;
    });

    // Level row: visually dim when disabled
    const levelRow = document.getElementById("settings-notif-level-row");
    if (levelRow) levelRow.classList.toggle("settings-row-disabled", !s.enabled);

    // Permission button
    const permBtn = document.getElementById("btn-notif-request-permission");
    if (permBtn) {
      const perm = ("Notification" in window) ? Notification.permission : "denied";
      permBtn.hidden = perm !== "default";
    }
  }

  /**
   * notify(level, title, body)
   * level: 'critical' | 'important' | 'info'
   *
   * Filters notifications based on user settings and tab visibility.
   * Never fires when the tab is visible (document.visibilityState === 'visible').
   */
  function notify(level, title, body) {
    if (!notificationsAllowed) return;
    // Never notify when tab is active
    if (document.visibilityState === "visible") return;
    const s = getNotificationSettings();
    if (!s.enabled) return;
    if (s.level === "critical"  && level !== "critical")  return;
    if (s.level === "important" && level === "info")       return;
    try {
      const n = new Notification(title, {
        body: (body || "").slice(0, 200),
        icon: "/static/favicon.png",
        tag: "devboard-" + level,
        silent: false,
      });
      n.onclick = () => { window.focus(); n.close(); };
      setTimeout(() => n.close(), 8000);
    } catch (_) {}
  }

  // Хранение «последнего увиденного» id сообщения чата
  let lastSeenChatId = parseInt(localStorage.getItem("devboard-last-seen-chat") || "0", 10);
  let lastChatId = 0;

  const AUTHOR_ICON = {
    "пользователь":    "👤",
    "тимлид":     "🧭",
    "бэкенд":     "🔧",
    "qa":         "✓",
    "архитектор": "🏗",
    "frontend":   "🎨",
    "devops":     "🚀",
    "техписатель":"📝",
    "system":     "⚙",
    // slug aliases for EN locale
    "teamlead":  "🧭",
    "backend":   "🔧",
    "architect": "🏗",
    "techwriter":"📝",
    "user":      "👤",
    // ADR-009: Управляющий + dev-lead (см. ROLE_DISPLAY выше)
    "Управляющий":       "🏛",
    "managing-director": "🏛",
    "dev-lead":          "🧭",
  };

  function renderChat(messages) {
    const body = chatList;
    if (!body) return;
    const isFirstRender = lastChatId === 0;
    if (messages.length === 0) {
      body.innerHTML = `<div style="color:var(--muted);font-size:11px;font-style:italic">${i18n("chat.empty")}</div>`;
      // Re-attach scroll button (innerHTML replaced it)
      if (chatScrollBtn) body.appendChild(chatScrollBtn);
      return;
    }
    const wasAtBottom = isAtBottom();
    body.innerHTML = messages.map((m) => {
      const time = new Date(m.created_at * 1000).toLocaleTimeString(dtLocale(), {hour:"2-digit", minute:"2-digit"});
      const icon = AUTHOR_ICON[m.author] || "•";
      return `<div class="chat-message author-${escapeHtml(m.author)}">
        <div class="head">
          <span class="who"><span class="ico">${icon}</span> ${escapeHtml(displayRole(m.author))}</span>
          <span class="time">${time}</span>
        </div>
        <div class="chat-text">${formatChatText(m.text)}</div>
      </div>`;
    }).join("");
    // Re-attach scroll button after innerHTML replacement
    if (chatScrollBtn) body.appendChild(chatScrollBtn);
    body.querySelectorAll("[data-task-ref]").forEach((el) =>
      el.addEventListener("click", () => openTaskModal(el.dataset.taskRef)),
    );

    // === Scroll logic ===
    // === Уведомления о новых сообщениях НЕ от пользователя ===
    const latest = messages[messages.length - 1];
    const prevLastChatId = lastChatId;
    lastChatId = latest.id;

    if (isFirstRender) {
      // Initial load: always scroll to bottom
      scrollToBottom(false);
    } else {
      const newMessages = messages.filter((m) => m.id > prevLastChatId);
      if (newMessages.length > 0 && wasAtBottom) {
        scrollToBottom(false);
      } else if (newMessages.length > 0 && !wasAtBottom) {
        _unreadChatSinceScroll += newMessages.length;
        updateScrollBtn();
      } else if (wasAtBottom) {
        scrollToBottom(false);
      }
    }

    const newFromTeam = messages.filter(
      (m) => m.id > lastSeenChatId && m.author !== "пользователь"
    );
    const chatCollapsed = document.querySelector(".app")?.classList.contains("chat-collapsed");
    const rail = document.getElementById("chat-expand-rail");

    if (newFromTeam.length > 0) {
      if (chatCollapsed) {
        rail.classList.add("has-unread");
      } else {
        // Чат раскрыт — сразу засчитываем как прочитанное
        lastSeenChatId = lastChatId;
        localStorage.setItem("devboard-last-seen-chat", String(lastSeenChatId));
      }
      // Browser notification — для самого свежего (уровень info: обычные чат-сообщения)
      const m = newFromTeam[newFromTeam.length - 1];
      const preview = m.text.slice(0, 120) + (m.text.length > 120 ? "…" : "");
      notify("info", `${AUTHOR_ICON[m.author] || ""} ${displayRole(m.author)}`, preview);
    }
  }

  // При раскрытии чата — снимаем мигание и фиксируем «всё прочитано»
  function markChatRead() {
    const rail = document.getElementById("chat-expand-rail");
    rail.classList.remove("has-unread");
    if (lastChatId > lastSeenChatId) {
      lastSeenChatId = lastChatId;
      localStorage.setItem("devboard-last-seen-chat", String(lastSeenChatId));
    }
  }

  function formatChatText(raw) {
    let s = escapeHtml(raw || "");
    s = s.replace(/```([\s\S]*?)```/g, (_, code) => `<pre class="md-code">${code}</pre>`);
    s = s.replace(/`([^`\n]+)`/g, '<code class="md-inline">$1</code>');
    s = s.replace(/\*\*([^*\n]+)\*\*/g, "<b>$1</b>");
    s = s.replace(/(^|[^*])\*([^*\n]+)\*(?!\*)/g, "$1<i>$2</i>");
    s = s.replace(/\[([^\]]+)\]\((https?:\/\/[^\s)]+)\)/g, '<a href="$2" target="_blank" rel="noopener">$1</a>');
    s = s.replace(/(?<!["=>])(https?:\/\/[^\s<]+)/g, '<a href="$1" target="_blank" rel="noopener">$1</a>');
    s = s.replace(/(^|[^\w])#([a-f0-9]{6,14})\b/gi, '$1<span class="task-ref" data-task-ref="$2">#$2</span>');
    const lines = s.split(/\r?\n/);
    const out = [];
    let listType = null;
    let para = [];
    const flushPara = () => { if (para.length) { out.push("<p>" + para.join("<br>") + "</p>"); para = []; } };
    const closeList = () => { if (listType) { out.push(`</${listType}>`); listType = null; } };
    for (const line of lines) {
      const ulMatch = line.match(/^\s*[-*]\s+(.+)$/);
      const olMatch = line.match(/^\s*\d+\.\s+(.+)$/);
      if (ulMatch) {
        flushPara();
        if (listType !== "ul") { closeList(); out.push("<ul>"); listType = "ul"; }
        out.push(`<li>${ulMatch[1]}</li>`);
      } else if (olMatch) {
        flushPara();
        if (listType !== "ol") { closeList(); out.push("<ol>"); listType = "ol"; }
        out.push(`<li>${olMatch[1]}</li>`);
      } else if (line.trim() === "") {
        closeList(); flushPara();
      } else {
        closeList(); para.push(line);
      }
    }
    closeList();
    flushPara();
    return out.join("");
  }

  // ===================== Planning sessions indicator (ADR-009 §2.7.3) =====================
  // Поведение:
  //   - GET /api/planning/active раз в REFRESH_MS — пока есть активные → баннер виден.
  //   - Клик на баннер → раскрывается панель с discussion_log.
  //   - Пока панель открыта — отдельно polling /api/planning/<id> раз в 5 сек.
  //   - phase='done' (или сессия исчезла из active) → панель/баннер прячутся.
  //   - Баннер виден только в общем чате (где разговаривает Управляющий) — там же,
  //     где может появиться приглашение на планёрку. В чатах отделов не показываем.
  const PLANNING_DETAIL_POLL_MS = 5000;
  const planningState = {
    active: [],                 // последний снапшот /api/planning/active
    selectedId: null,           // какая сессия раскрыта в панели
    panelOpen: false,
    detailTimer: null,          // setInterval handle для detail-polling
  };

  function _planningPhaseNum(phase) {
    return ({ gathering: 1, discussion: 2, consolidation: 3, distribution: 4, done: 5 }[phase] || 0);
  }
  function _planningPhaseName(phase) {
    const key = "planning.phase." + (phase || "gathering");
    const v = i18n(key);
    return (v && v !== key) ? v : (phase || "");
  }
  function _planningDeptName(deptId) {
    if (!deptId) return "";
    if (Array.isArray(_departmentsCache)) {
      const d = _departmentsCache.find((x) => x.id === deptId);
      if (d) return deptDisplayName(d);
    }
    // fallback на i18n ключ dept.<id> или сам id
    const key = "dept." + deptId;
    const t = (typeof window.t === "function") ? window.t(key) : key;
    return (t && t !== key) ? t : deptId;
  }
  function _planningDeptsText(deptIds) {
    if (!Array.isArray(deptIds) || deptIds.length === 0) return "—";
    return deptIds.map(_planningDeptName).join(", ");
  }

  function _renderPlanningBanner() {
    const banner = document.getElementById("planning-banner");
    const txt = document.getElementById("planning-banner-text");
    if (!banner || !txt) return;

    // Баннер показываем только в общем чате (собеседник = Управляющий).
    const inGlobalChat = (currentChatChannel() === CHAT_CHANNEL_GLOBAL);
    const active = planningState.active;

    if (!inGlobalChat || active.length === 0) {
      banner.hidden = true;
      // Если панель была открыта — закрываем (источник пропал).
      if (planningState.panelOpen) _closePlanningPanel();
      return;
    }

    banner.hidden = false;
    // Если выбранная сессия исчезла из active — переключиться на первую.
    if (planningState.selectedId &&
        !active.some((s) => s.id === planningState.selectedId)) {
      planningState.selectedId = active[0].id;
    }
    if (!planningState.selectedId) {
      planningState.selectedId = active[0].id;
    }

    const sess = active.find((s) => s.id === planningState.selectedId) || active[0];
    const phaseNum = _planningPhaseNum(sess.phase);
    const phaseName = _planningPhaseName(sess.phase);
    const repliesLabel = i18n("planning.replies_count", { n: sess.replies_count || 0 });

    if (active.length > 1) {
      // Если несколько одновременно — даём короткую форму + детали по клику.
      txt.textContent = i18n("planning.banner_multi", { n: active.length });
    } else {
      txt.textContent = i18n("planning.banner", {
        depts: _planningDeptsText(sess.departments_involved),
        phase_num: phaseNum,
        phase_name: phaseName,
        replies: repliesLabel,
      });
    }
  }

  function _renderPlanningPanel(detail) {
    const meta = document.getElementById("planning-panel-meta");
    const log = document.getElementById("planning-panel-log");
    const title = document.getElementById("planning-panel-title");
    if (!meta || !log) return;

    if (title) {
      const t1 = i18n("planning.panel_title");
      // Если активных несколько — добавим переключатель в conteh title.
      const active = planningState.active;
      if (active.length > 1 && detail) {
        const idx = active.findIndex((s) => s.id === detail.id);
        const total = active.length;
        title.innerHTML = "";
        const lab = document.createElement("span");
        lab.textContent = t1;
        title.appendChild(lab);
        const sw = document.createElement("span");
        sw.className = "planning-panel-switcher";
        const prev = document.createElement("button");
        prev.type = "button";
        prev.textContent = "‹";
        prev.disabled = idx <= 0;
        prev.addEventListener("click", (e) => {
          e.stopPropagation();
          if (idx > 0) _selectPlanningSession(active[idx - 1].id);
        });
        const lblIdx = document.createElement("span");
        lblIdx.className = "switch-label";
        lblIdx.textContent = i18n("planning.switch_session", { idx: idx + 1, total });
        const next = document.createElement("button");
        next.type = "button";
        next.textContent = "›";
        next.disabled = idx >= total - 1;
        next.addEventListener("click", (e) => {
          e.stopPropagation();
          if (idx < total - 1) _selectPlanningSession(active[idx + 1].id);
        });
        sw.appendChild(prev); sw.appendChild(lblIdx); sw.appendChild(next);
        title.appendChild(sw);
      } else {
        title.textContent = t1;
      }
    }

    if (!detail) {
      meta.innerHTML = `<span class="planning-empty">${escapeHtml(i18n("planning.loading"))}</span>`;
      log.innerHTML = "";
      return;
    }

    const phaseNum = _planningPhaseNum(detail.phase);
    const phaseName = _planningPhaseName(detail.phase);
    const deptsText = _planningDeptsText(detail.departments_involved);
    meta.innerHTML =
      `<span><span class="meta-key">${escapeHtml(i18n("planning.phase_label"))}:</span>` +
        `<span class="meta-val is-phase">${phaseNum} — ${escapeHtml(phaseName)}</span></span>` +
      `<span><span class="meta-key">${escapeHtml(i18n("planning.departments"))}:</span>` +
        `<span class="meta-val">${escapeHtml(deptsText)}</span></span>`;

    const replies = Array.isArray(detail.discussion_log) ? detail.discussion_log : [];
    if (replies.length === 0) {
      log.innerHTML = `<div class="planning-empty">${escapeHtml(i18n("planning.log_empty"))}</div>`;
      return;
    }
    // Сортируем по ts/timestamp на всякий случай (если backend не отсортировал).
    const sorted = replies.slice().sort((a, b) => {
      const ta = (a && (a.ts || a.timestamp)) || 0;
      const tb = (b && (b.ts || b.timestamp)) || 0;
      return ta - tb;
    });
    log.innerHTML = sorted.map((r) => {
      const ts = (r && (r.ts || r.timestamp)) || 0;
      const time = ts
        ? new Date(ts * 1000).toLocaleTimeString(dtLocale(), { hour: "2-digit", minute: "2-digit" })
        : "";
      const author = escapeHtml(displayRole(r.author || ""));
      const role = r.role ? `<span class="reply-role">· ${escapeHtml(r.role)}</span>` : "";
      const dept = r.dept ? `<span class="reply-dept">${escapeHtml(_planningDeptName(r.dept))}</span>` : "";
      const text = escapeHtml(r.text || "");
      return `<div class="planning-reply">
        <div class="reply-head">
          <span class="reply-author">${author}</span>
          ${role}
          ${dept}
          <span class="reply-time">${time}</span>
        </div>
        <div class="reply-text">${text}</div>
      </div>`;
    }).join("");
  }

  async function _fetchPlanningDetail(sessionId) {
    if (!sessionId) return null;
    try {
      const r = await fetch("/api/planning/" + encodeURIComponent(sessionId));
      if (!r.ok) return null;
      return await r.json();
    } catch (_) {
      return null;
    }
  }

  function _stopPlanningDetailPolling() {
    if (planningState.detailTimer) {
      clearInterval(planningState.detailTimer);
      planningState.detailTimer = null;
    }
  }

  async function _refreshPlanningDetail() {
    if (!planningState.panelOpen || !planningState.selectedId) return;
    const detail = await _fetchPlanningDetail(planningState.selectedId);
    if (!planningState.panelOpen) return;  // могли закрыть пока ждали
    if (!detail) {
      const log = document.getElementById("planning-panel-log");
      if (log) log.innerHTML = `<div class="planning-empty">${escapeHtml(i18n("planning.load_error"))}</div>`;
      return;
    }
    // Если phase=done — закрываем панель и убираем из active.
    if (detail.phase === "done") {
      _closePlanningPanel();
      // Локально удаляем сессию из active (active-polling её тоже не вернёт).
      planningState.active = planningState.active.filter((s) => s.id !== detail.id);
      _renderPlanningBanner();
      return;
    }
    _renderPlanningPanel(detail);
  }

  function _startPlanningDetailPolling() {
    _stopPlanningDetailPolling();
    planningState.detailTimer = setInterval(_refreshPlanningDetail, PLANNING_DETAIL_POLL_MS);
  }

  async function _openPlanningPanel() {
    const panel = document.getElementById("planning-panel");
    const banner = document.getElementById("planning-banner");
    if (!panel || !banner) return;
    if (!planningState.selectedId && planningState.active.length > 0) {
      planningState.selectedId = planningState.active[0].id;
    }
    if (!planningState.selectedId) return;
    planningState.panelOpen = true;
    panel.hidden = false;
    banner.setAttribute("aria-expanded", "true");
    _renderPlanningPanel(null);  // показать "loading"
    await _refreshPlanningDetail();
    _startPlanningDetailPolling();
  }

  function _closePlanningPanel() {
    const panel = document.getElementById("planning-panel");
    const banner = document.getElementById("planning-banner");
    planningState.panelOpen = false;
    if (panel) panel.hidden = true;
    if (banner) banner.setAttribute("aria-expanded", "false");
    _stopPlanningDetailPolling();
  }

  async function _selectPlanningSession(sessionId) {
    if (!sessionId) return;
    planningState.selectedId = sessionId;
    if (planningState.panelOpen) {
      _renderPlanningPanel(null);
      await _refreshPlanningDetail();
    }
    _renderPlanningBanner();
  }

  async function refreshPlanningActive() {
    try {
      const r = await fetch("/api/planning/active");
      if (!r.ok) {
        // 404 / 500 — тихо не показываем баннер.
        planningState.active = [];
      } else {
        const data = await r.json();
        planningState.active = Array.isArray(data.sessions) ? data.sessions : [];
      }
    } catch (_) {
      planningState.active = [];
    }
    _renderPlanningBanner();
    // Если панель открыта и наша сессия пропала из active — закрыть.
    if (planningState.panelOpen && planningState.selectedId &&
        !planningState.active.some((s) => s.id === planningState.selectedId)) {
      _closePlanningPanel();
    }
  }

  // Wire-up: клик на баннер → toggle панели; крестик → close.
  (function initPlanningBannerControls() {
    const banner = document.getElementById("planning-banner");
    const closeBtn = document.getElementById("planning-panel-close");
    if (banner) {
      banner.addEventListener("click", () => {
        if (planningState.panelOpen) _closePlanningPanel();
        else _openPlanningPanel();
      });
    }
    if (closeBtn) {
      closeBtn.addEventListener("click", (e) => {
        e.stopPropagation();
        _closePlanningPanel();
      });
    }
  })();

  // Перерисовать баннер при смене канала чата (мог уйти из общего → спрятать).
  window.addEventListener("localechange", () => {
    try { _renderPlanningBanner(); } catch (_) {}
    if (planningState.panelOpen) _refreshPlanningDetail();
  });

  // При focus окна — обновить состояние планёрок (полезно если был в фоне).
  window.addEventListener("focus", () => {
    try { refreshPlanningActive(); } catch (_) {}
  });

  // Хук в существующий setCurrentChatChannel чтобы баннер реагировал на переключение.
  (function hookChatChannelChange() {
    const orig = setCurrentChatChannel;
    setCurrentChatChannel = function (channel) {
      orig(channel);
      try { _renderPlanningBanner(); } catch (_) {}
    };
  })();

  $("#chat-form").addEventListener("submit", async (e) => {
    e.preventDefault();
    const input = $("#chat-input");
    const text = input.value.trim();
    if (!text) return;
    input.value = "";
    // S9.1 + ADR-009 §2.7.2: пишем в активный канал чата.
    //   currentChatChannel() === "__global__" → общий чат (Управляющий).
    //   иначе → чат конкретного отдела (lead).
    const r = await fetch(
      "/api/chat?department=" + encodeURIComponent(currentChatChannel()),
      {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ author: "пользователь", text }),
      }
    );
    if (!r.ok) {
      const err = await r.json().catch(() => ({}));
      alert(i18n("chat.send_failed") + (err.причина || err.reason || r.status));
      input.value = text;
      return;
    }
    await refreshChat();
  });

  // ===================== Roles =====================

  // Known model values per provider (for custom-detection in ollama)
  const _KNOWN_OLLAMA_MODELS = ["llama3.1", "qwen2.5-coder", "mistral"];

  /** Show the right model control for the selected LLM and pre-select/populate value */
  function _updateModelUI(llm, currentValue) {
    // Hide all provider blocks
    document.querySelectorAll("[data-for-llm]").forEach((el) => {
      el.hidden = true;
    });

    if (llm === "claude") {
      const sel = $("#role-model-claude");
      sel.hidden = false;
      // If currentValue is not in options, pick first
      const known = Array.from(sel.options).map((o) => o.value);
      if (currentValue && known.includes(currentValue)) {
        sel.value = currentValue;
      } else {
        sel.value = sel.options[0] ? sel.options[0].value : "";
      }
    } else if (llm === "openai") {
      const sel = $("#role-model-openai");
      sel.hidden = false;
      const known = Array.from(sel.options).map((o) => o.value);
      if (currentValue && known.includes(currentValue)) {
        sel.value = currentValue;
      } else {
        sel.value = sel.options[0] ? sel.options[0].value : "";
      }
    } else if (llm === "ollama") {
      const wrap = $("#role-model-ollama");
      wrap.hidden = false;
      const sel = $("#role-model-ollama-select");
      const customInput = $("#role-model-ollama-custom");

      if (!currentValue || _KNOWN_OLLAMA_MODELS.includes(currentValue)) {
        // Select from list
        sel.value = currentValue || _KNOWN_OLLAMA_MODELS[0];
        customInput.style.display = "none";
        customInput.value = "";
      } else {
        // Custom value — show input
        sel.value = "";  // "-- custom --"
        customInput.style.display = "";
        customInput.value = currentValue;
      }
    }
  }

  /** Read the active model value from whichever control is currently visible */
  function _getModelValue() {
    const llm = $("#role-field-llm").value;
    if (llm === "claude") return $("#role-model-claude").value;
    if (llm === "openai") return $("#role-model-openai").value;
    if (llm === "ollama") {
      const sel = $("#role-model-ollama-select");
      if (sel.value === "") {
        // custom
        return $("#role-model-ollama-custom").value.trim();
      }
      return sel.value;
    }
    return "";
  }

  let _rolesEditingName = null;  // null = create mode, string = edit mode

  function openRoleModal(role) {
    _rolesEditingName = role ? role.name : null;
    const form = $("#form-role");
    const titleEl = $("#modal-role-title");

    titleEl.textContent = role ? `${i18n("roles.modalTitle.edit")}: ${role.name}` : i18n("roles.modalTitle.new");
    form.reset();

    if (role) {
      form.name.value = role.name;
      form.name.disabled = true;  // имя роли — PK, не меняем
      form.description.value = role.description || "";
      form.llm.value = role.llm || "claude";
      _updateModelUI(form.llm.value, role.model || "");
      form.temperature.value = role.temperature != null ? role.temperature : 1;
      form.max_tokens.value = role.max_tokens || 8096;
      form.system_prompt.value = role.system_prompt || "";
    } else {
      form.name.disabled = false;
      form.temperature.value = 1;
      form.max_tokens.value = 8096;
      _updateModelUI("claude", "");
    }

    $("#modal-role").hidden = false;
    setTimeout(() => (role ? form.description.focus() : form.name.focus()), 50);
  }

  function closeRoleModal() {
    $("#modal-role").hidden = true;
    _rolesEditingName = null;
  }

  $("#btn-role-modal-close").addEventListener("click", closeRoleModal);
  $("#btn-role-cancel").addEventListener("click", closeRoleModal);
  $("#modal-role").addEventListener("keydown", (e) => {
    if (e.key === "Escape") closeRoleModal();
  });
  $("#btn-new-role") && $("#btn-new-role").addEventListener("click", () => openRoleModal(null));

  // Show correct model control when provider changes
  $("#role-field-llm").addEventListener("change", (e) => {
    _updateModelUI(e.target.value, "");
  });

  // Ollama: show/hide custom input when "-- custom --" is selected
  $("#role-model-ollama-select").addEventListener("change", (e) => {
    const customInput = $("#role-model-ollama-custom");
    if (e.target.value === "") {
      customInput.style.display = "";
      customInput.focus();
    } else {
      customInput.style.display = "none";
      customInput.value = "";
    }
  });

  $("#form-role").addEventListener("submit", async (e) => {
    e.preventDefault();
    const form = e.target;
    const body = {
      name: form.name.value.trim(),
      description: form.description.value.trim(),
      llm: form.llm.value,
      model: _getModelValue(),
      temperature: parseFloat(form.temperature.value),
      max_tokens: parseInt(form.max_tokens.value, 10),
      system_prompt: form.system_prompt.value,
    };

    const isEdit = _rolesEditingName !== null;
    const url = isEdit ? `/api/roles/${encodeURIComponent(_rolesEditingName)}` : "/api/roles";
    const method = isEdit ? "PUT" : "POST";

    const r = await fetch(url, {
      method,
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    });
    if (!r.ok) {
      const err = await r.json().catch(() => ({}));
      alert(i18n("modal.task.create_failed") + (err.причина || err.reason || r.status));
      return;
    }
    closeRoleModal();
    loadRoles();
  });

  async function deleteRole(name) {
    const confirmed = await customConfirm(i18n("roles.confirm.delete").replace("{name}", name));
    if (!confirmed) return;
    const r = await fetch(`/api/roles/${encodeURIComponent(name)}`, { method: "DELETE" });
    if (!r.ok) {
      const err = await r.json().catch(() => ({}));
      alert(i18n("roles.error.deleteFailed") + (err.причина || err.reason || r.status));
    }
    loadRoles();
  }

  function renderRolesTable(roles) {
    const body = $("#roles-body");
    if (!roles || roles.length === 0) {
      body.innerHTML = `<p class="muted">${i18n("roles.empty")}</p>`;
      setNavBadge("nav-roles-count", 0);
      return;
    }
    setNavBadge("nav-roles-count", roles.length);

    const locale = (typeof window.getLocale === "function") ? window.getLocale() : "ru";

    // S9.2: для колонки Department нужно локализованное имя отдела.
    // Берём из _departmentsCache (заполняется loadDepartments).
    const _deptById = {};
    (_departmentsCache || []).forEach((d) => { _deptById[d.id] = d; });
    const globalLabel = i18n("roles.dept.global");
    const _resolveDeptLabel = (deptId) => {
      if (!deptId) return globalLabel;
      const d = _deptById[deptId];
      if (d) return deptDisplayName(d);
      // fallback: i18n или сам id
      const i18nKey = "dept." + deptId;
      const i18nVal = i18n(i18nKey);
      return (i18nVal !== i18nKey) ? i18nVal : deptId;
    };

    // F2(1.5): resolve section label for a department id
    const _resolveSectionLabel = (deptId) => {
      if (!deptId) return i18n("roles.section.global");
      const sectionKey = "roles.section." + deptId;
      const sectionVal = i18n(sectionKey);
      if (sectionVal !== sectionKey) return sectionVal;
      // fallback to dept display name
      return _resolveDeptLabel(deptId);
    };

    // F2(1.5): section icons per known department id
    const _sectionIcon = (deptId) => {
      if (!deptId) return "🏛";
      if (deptId === "dev") return "💻";
      if (deptId === "marketing") return "📣";
      return "🏢";
    };

    const activeDept = currentDepartment();

    const _cyrillicSlugMap = {
      "тимлид": "teamlead",
      "бэкенд": "backend",
      "qa": "qa",
      "архитектор": "architect",
      "frontend": "frontend",
      "devops": "devops",
      "техписатель": "techwriter",
      "пользователь": "user",
    };

    const _renderRow = (r) => {
      const llm = r.llm || "—";
      const model = escapeHtml(r.model || "—");
      const desc = escapeHtml(r.description || "—");
      // Локализованное имя роли:
      // 1. display_name_en / display_name_ru если API вернул (поле из БД)
      // 2. roles.names.<slug> из i18n-словаря
      //    Кириллические slug'и маппим на латинские ключи словаря:
      //    тимлид→teamlead, бэкенд→backend, архитектор→architect, техписатель→techwriter,
      //    пользователь→user
      // 3. fallback — slug
      let displayName;
      if (locale === "en" && r.display_name_en) {
        displayName = r.display_name_en;
      } else if (locale !== "en" && r.display_name_ru) {
        displayName = r.display_name_ru;
      } else {
        const slugKey = _cyrillicSlugMap[r.name] || r.name.replace(/-/g, "_");
        const i18nKey = `roles.names.${slugKey}`;
        const i18nVal = i18n(i18nKey);
        displayName = (i18nVal !== i18nKey) ? i18nVal : r.name;
      }
      return `<tr data-role-name="${escapeAttr(r.name)}">
        <td class="role-name-cell"><span class="role-display-name">${escapeHtml(displayName)}</span></td>
        <td class="role-desc-cell">${desc}</td>
        <td class="role-llm-cell">${escapeHtml(llm)}</td>
        <td class="role-model-cell">${model}</td>
        <td class="role-actions-cell">
          <button class="role-edit-btn" data-role-edit="${escapeAttr(r.name)}"
                  title="${i18n("roles.btn.edit")}" aria-label="${i18n("roles.btn.edit")} ${escapeAttr(r.name)}">✎</button>
          <button class="role-delete-btn danger" data-role-delete="${escapeAttr(r.name)}"
                  title="${i18n("roles.btn.delete")}" aria-label="${i18n("roles.btn.delete")} ${escapeAttr(r.name)}">🗑</button>
        </td>
      </tr>`;
    };

    // F2(1.5): group roles by department_id (null → "global" bucket)
    // Order: global first, then known depts (dev, marketing), then rest alphabetically
    const _groups = new Map();
    roles.forEach((r) => {
      const key = r.department_id || null;
      if (!_groups.has(key)) _groups.set(key, []);
      _groups.get(key).push(r);
    });

    // Sort groups: null first, then by id
    const _sortedKeys = Array.from(_groups.keys()).sort((a, b) => {
      if (a === null) return -1;
      if (b === null) return 1;
      const order = ["dev", "marketing"];
      const ai = order.indexOf(a), bi = order.indexOf(b);
      if (ai !== -1 && bi !== -1) return ai - bi;
      if (ai !== -1) return -1;
      if (bi !== -1) return 1;
      return a.localeCompare(b);
    });

    // F2(1.5): restore collapsed state from sessionStorage
    const _collapseKey = (deptId) => "roles-section-collapsed:" + (deptId || "global");
    const _isCollapsed = (deptId) => sessionStorage.getItem(_collapseKey(deptId)) === "1";

    // F2(1.6): одна общая таблица с colgroup (фикс. ширина колонок) + dept-group строки
    const colCount = 5;
    let html = `
      <table class="roles-table roles-table--unified" aria-label="${escapeHtml(i18n("roles.title") || "Роли")}">
        <colgroup>
          <col style="width:20%">
          <col style="width:35%">
          <col style="width:10%">
          <col style="width:20%">
          <col style="width:15%">
        </colgroup>
        <thead class="roles-thead-sticky">
          <tr>
            <th scope="col">${i18n("roles.col.name")}</th>
            <th scope="col">${i18n("roles.col.description")}</th>
            <th scope="col">${i18n("roles.col.llm")}</th>
            <th scope="col">${i18n("roles.col.model")}</th>
            <th scope="col">${i18n("roles.col.actions")}</th>
          </tr>
        </thead>
        <tbody>`;

    _sortedKeys.forEach((deptId) => {
      const sectionRoles = _groups.get(deptId);
      const icon = _sectionIcon(deptId);
      const label = _resolveSectionLabel(deptId);
      const count = sectionRoles.length;
      const isActive = deptId && deptId === activeDept;

      // Строка-разделитель отдела (dept-group)
      html += `<tr class="dept-group${isActive ? " dept-group--active" : ""}"
                   data-section-dept="${escapeAttr(deptId || "global")}">
        <td colspan="${colCount}">
          <span class="dept-group-ico" aria-hidden="true">${icon}</span>
          <span class="dept-group-label">${escapeHtml(label)}</span>
          <span class="dept-group-count">${count} ${escapeHtml(i18n("roles.section.count_suffix") || "")}</span>
        </td>
      </tr>`;

      // Строки ролей этого отдела
      sectionRoles.forEach((r) => { html += _renderRow(r); });
    });

    html += `</tbody></table>`;
    body.innerHTML = html;

    // Bind edit / delete buttons
    body.querySelectorAll("[data-role-edit]").forEach((btn) => {
      btn.addEventListener("click", () => {
        const name = btn.dataset.roleEdit;
        const role = _rolesCache.find((r) => r.name === name);
        if (role) openRoleModal(role);
      });
    });
    body.querySelectorAll("[data-role-delete]").forEach((btn) => {
      btn.addEventListener("click", () => deleteRole(btn.dataset.roleDelete));
    });
  }

  let _rolesCache = [];

  async function loadRoles() {
    try {
      // S9.2: Roles tab показывает ВСЕ роли (global + per-department).
      // ?department=__all__ → backend отключает фильтр по department_id.
      const r = await fetch("/api/roles?department=__all__");
      if (!r.ok) throw new Error("api/roles " + r.status);
      const data = await r.json();
      // API returns {статус, всего, роли:[{name, description, capabilities, department_id}]}
      // capabilities can be a JSON object with extended fields (llm, model, etc.)
      const raw = data.роли || [];
      _rolesCache = raw.map((role) => {
        const caps = role.capabilities;
        const ext = (caps && typeof caps === "object" && !Array.isArray(caps)) ? caps : {};
        return {
          name: role.name,
          description: role.description,
          // S9.2: department_id — null/undefined для global ролей, иначе id отдела.
          department_id: role.department_id || null,
          llm: ext.llm || "claude",
          model: ext.model || "",
          temperature: ext.temperature != null ? ext.temperature : 1,
          max_tokens: ext.max_tokens || 8096,
          system_prompt: ext.system_prompt || "",
        };
      });
      renderRolesTable(_rolesCache);
      // Заполняем кеш для pickModelForTask (чтобы чипы карточек учитывали модель роли)
      _refreshRoleModelCache(_rolesCache);
    } catch (e) {
      console.error("loadRoles:", e);
    }
  }

  // ===================== Statistics view =====================

  let _statsRange = "today";

  async function loadStats(range) {
    if (range) _statsRange = range;
    // Update active tab
    $$(".stats-tab").forEach((tab) =>
      tab.classList.toggle("active", tab.dataset.range === _statsRange)
    );

    const kpiGrid = $("#statsKpiGrid");
    const modelsEl = $("#statsModels");
    const rolesEl = $("#statsRoles");
    const heatmapEl = $("#statsHeatmap");
    const topEl = $("#statsTop");
    const lifetimeGridEl = $("#statsLifetime");
    if (!kpiGrid) return;

    // Loading state
    if (lifetimeGridEl) lifetimeGridEl.innerHTML = "";
    kpiGrid.innerHTML = `<div class="stats-loading">${i18n("roles.loading")}</div>`;
    if (modelsEl) modelsEl.innerHTML = "";
    if (rolesEl) rolesEl.innerHTML = "";
    if (heatmapEl) heatmapEl.innerHTML = "";
    if (topEl) topEl.innerHTML = "";

    let data;
    try {
      const r = await fetch("/api/stats/aggregates?range=" + _statsRange);
      if (!r.ok) throw new Error("stats " + r.status);
      data = await r.json();
    } catch (e) {
      kpiGrid.innerHTML = `<div class="stats-loading" style="color:var(--red)">${e.message}</div>`;
      return;
    }

    // --- KPI cards: range-based counters (restored original layout) ---
    const kpiDefs = [
      { key: "sessions",      label: i18n("stats.sessions"),  value: data.sessions      || 0, unit: "" },
      { key: "turns",         label: i18n("stats.turns"),     value: data.turns         || 0, unit: "" },
      { key: "cost_usd",      label: i18n("stats.cost"),      value: "$" + (data.cost_usd || 0).toFixed(2), unit: "" },
      { key: "files_changed", label: i18n("stats.files"),     value: data.files_changed || 0, unit: "" },
      { key: "lines_written", label: i18n("stats.lines"),     value: data.lines_written || 0, unit: "" },
      { key: "hours_worked",  label: i18n("stats.hours"),     value: (data.hours_worked || 0).toFixed(1), unit: "h" },
    ];
    kpiGrid.innerHTML = kpiDefs.map((k) => `
      <div class="stats-kpi-card">
        <div class="stats-kpi-label">${escapeHtml(k.label)}</div>
        <div class="stats-kpi-value">${escapeHtml(String(k.value))}${k.unit ? '<span class="stats-kpi-unit">' + k.unit + '</span>' : ''}</div>
      </div>
    `).join("");

    // --- Models table ---
    if (modelsEl) {
      const models = data.models || [];
      let html = `<h3 class="stats-section-title">${i18n("stats.models.title")}</h3>`;
      if (models.length === 0) {
        html += `<div class="stats-empty">—</div>`;
      } else {
        html += `<table class="stats-table">
          <thead><tr>
            <th>Model</th><th class="num">Sessions</th><th class="num">Input tk</th><th class="num">Output tk</th><th class="num">Cost</th>
          </tr></thead>
          <tbody>
          ${models.map((m) => `<tr>
            <td><code>${escapeHtml(m.model || "—")}</code></td>
            <td class="num">${m.sessions || 0}</td>
            <td class="num">${(m.input_tokens || 0).toLocaleString()}</td>
            <td class="num">${(m.output_tokens || 0).toLocaleString()}</td>
            <td class="num">$${(m.cost_usd || 0).toFixed(2)}</td>
          </tr>`).join("")}
          </tbody>
        </table>`;
      }
      modelsEl.innerHTML = html;
    }

    // --- Roles bar chart ---
    if (rolesEl) {
      const roles = data.roles || [];
      let html = `<h3 class="stats-section-title">${i18n("stats.roles.title")}</h3>`;
      if (roles.length === 0) {
        html += `<div class="stats-empty">—</div>`;
      } else {
        const maxDone = Math.max(...roles.map((r) => r.done || 0), 1);
        html += `<div class="stats-bars">` + roles.map((r) => {
          const pct = Math.round(((r.done || 0) / maxDone) * 100);
          return `<div class="stats-bar-row">
            <span class="stats-bar-label">${escapeHtml(displayRole(r.name))}</span>
            <div class="stats-bar-track"><div class="stats-bar" style="width:${pct}%"></div></div>
            <span class="stats-bar-val">${r.done || 0} done · ${r.wip || 0} wip · ${r.todo || 0} todo</span>
          </div>`;
        }).join("") + `</div>`;
      }
      rolesEl.innerHTML = html;
    }

    // --- Heatmap 24h ---
    if (heatmapEl) {
      const hourly = data.hourly_activity || [];
      const maxCount = Math.max(...hourly.map((h) => h.count || 0), 1);
      let html = `<h3 class="stats-section-title">${i18n("stats.heatmap.title")}</h3>`;
      html += `<div class="stats-heatmap">`;
      for (let h = 0; h < 24; h++) {
        const entry = hourly.find((x) => x.hour === h) || { hour: h, count: 0 };
        const opacity = entry.count > 0 ? 0.15 + 0.85 * (entry.count / maxCount) : 0.06;
        html += `<div class="stats-heatmap-cell" title="${h}:00 — ${entry.count}" style="opacity:${opacity.toFixed(2)}">
          <span class="stats-heatmap-hour">${h}</span>
        </div>`;
      }
      html += `</div>`;
      heatmapEl.innerHTML = html;
    }

    // --- Top achievements ---
    if (topEl) {
      const top = data.top || {};
      let html = `<h3 class="stats-section-title">${i18n("stats.top.title")}</h3>`;
      html += `<div class="stats-top-grid">`;
      if (top.longest_turn) {
        html += `<div class="stats-top-card"><div class="stats-top-ico">🏆</div><div class="stats-top-label">Longest session</div><div class="stats-top-val">${top.longest_turn.turns} turns</div></div>`;
      }
      if (top.most_expensive_day) {
        html += `<div class="stats-top-card"><div class="stats-top-ico">💰</div><div class="stats-top-label">Most expensive day</div><div class="stats-top-val">${escapeHtml(top.most_expensive_day.date)} · $${(top.most_expensive_day.cost || 0).toFixed(2)}</div></div>`;
      }
      if (top.fastest_task) {
        html += `<div class="stats-top-card"><div class="stats-top-ico">⚡</div><div class="stats-top-label">Fastest task</div><div class="stats-top-val">${top.fastest_task.minutes} min</div></div>`;
      }
      if (top.most_productive_role) {
        html += `<div class="stats-top-card"><div class="stats-top-ico">🚀</div><div class="stats-top-label">Most productive</div><div class="stats-top-val">${escapeHtml(displayRole(top.most_productive_role))}</div></div>`;
      }
      html += `</div>`;
      topEl.innerHTML = html;
    }

    // --- Lifetime task counters (S6.1: отдельная секция с .lifetime-counter-* классами) ---
    const lifetimeEl = $("#statsLifetime");
    if (lifetimeEl) {
      const totalDone      = data.tasks_total_done      || 0;
      const totalCreated   = data.tasks_total_created   || 0;
      const inProgress     = data.tasks_in_progress     || 0;
      const completionRate = data.tasks_completion_rate || 0;
      const rateDisplay    = Math.round(completionRate * 100);

      const lifetimeDefs = [
        { id: "lt-done",       mod: "done",    label: i18n("stats.lifetime.done"),       rawVal: totalDone,    suffix: "" },
        { id: "lt-created",    mod: "created", label: i18n("stats.lifetime.created"),    rawVal: totalCreated, suffix: "" },
        { id: "lt-rate",       mod: "rate",    label: i18n("stats.lifetime.rate"),       rawVal: rateDisplay,  suffix: "%" },
        { id: "lt-inprogress", mod: "wip",     label: i18n("stats.lifetime.inprogress"), rawVal: inProgress,   suffix: "" },
      ];

      let lifetimeHtml = `<h3 class="stats-section-title">${i18n("stats.lifetime.title")}</h3>`;
      lifetimeHtml += `<div class="lifetime-counter-grid">`;
      lifetimeHtml += lifetimeDefs.map((d) => `
        <div class="lifetime-counter-card lifetime-counter-card--${escapeHtml(d.mod)}">
          <div class="lifetime-counter-value" id="${escapeHtml(d.id)}">0${escapeHtml(d.suffix)}</div>
          <div class="lifetime-counter-label">${escapeHtml(d.label)}</div>
        </div>
      `).join("");
      lifetimeHtml += `</div>`;
      lifetimeEl.innerHTML = lifetimeHtml;

      // Count-up animation (~600ms)
      lifetimeDefs.forEach((d) => {
        const el = document.getElementById(d.id);
        if (el) animateCounter(el, d.rawVal, d.suffix, 600);
      });
    }
  }

  /** Count-up animation: increments el.textContent from 0 to target over duration ms. */
  function animateCounter(el, target, suffix, duration) {
    if (!el) return;
    suffix = suffix || "";
    duration = duration || 600;
    if (target === 0) { el.textContent = "0" + suffix; return; }
    const start = Date.now();
    const tick = () => {
      const progress = Math.min((Date.now() - start) / duration, 1);
      el.textContent = Math.floor(progress * target) + suffix;
      if (progress < 1) requestAnimationFrame(tick);
      else el.textContent = target + suffix;
    };
    requestAnimationFrame(tick);
  }

  // Wire stats-tab clicks
  document.addEventListener("click", (e) => {
    const tab = e.target.closest(".stats-tab");
    if (tab) loadStats(tab.dataset.range);
  });

  // ===================== Refresh loop =====================
  let inFlight = false;
  async function refresh() {
    if (inFlight) return;
    inFlight = true;
    try {
      // S9.1: список отделов + counts обновляем на каждом цикле (lightweight call).
      await loadDepartments();
      const data = await fetchTasks();
      renderBoard(data);
      refreshDemoState(data.задачи || []);
      await refreshTeamStatus();
      await refreshInbox();
      await refreshUsage();
      await refreshRouter();
      await refreshSilence();
      await refreshChat();
      // ADR-009 §2.7.3: индикатор активных планёрок в шапке общего чата.
      // Не критично если упадёт — refreshPlanningActive ловит сетевые ошибки сам.
      try { await refreshPlanningActive(); } catch (_) {}
      // F1-1.5: список агентов текущего отдела в sidebar.
      try { await loadSidebarAgents(); } catch (_) {}
    } catch (e) {
      console.error(e);
    } finally {
      inFlight = false;
    }
  }

  // ===================== Locale change — rerender dynamic content =====================
  window.addEventListener("localechange", () => {
    // Обновляем динамически сгенерированный HTML при смене локали
    refresh();
    // Если открыта модалка задачи — перерисуем её
    const taskModal = $("#modal-task");
    if (taskModal && !taskModal.hidden) {
      const titleEl = $("#modal-task-title");
      const bodyEl = $("#modal-task-body");
      // Перечитываем задачу по заголовку (id в заголовке #xxxxxx)
      const m = (titleEl.textContent || "").match(/#([a-f0-9]+)/i);
      if (m) openTaskModal(m[1]);
      else bodyEl.innerHTML = "";
    }
    // Если открыта settings / archive / roles — перечитываем
    if (currentView === "settings") loadSettings();
    if (currentView === "archive") loadArchive();
    if (currentView === "roles") renderRolesTable(_rolesCache);
  });

  // ===================== First-run wizard =====================

  (function () {
    const WIZARD_DONE_KEY = "first_run_done";
    let _wizardStep = 1;
    const WIZARD_STEPS = 4;

    // Pending selections before saving (saved per step)
    let _wizardUILocale = localStorage.getItem("locale") || "ru";
    let _wizardOutputLocale = localStorage.getItem("output_locale") || _wizardUILocale;
    let _wizardExpertise = localStorage.getItem("user_expertise") || "non-tech";
    let _wizardTheme = localStorage.getItem("devboard-theme") || "dark";

    function wizardEl(id) { return document.getElementById(id); }

    function goToWizardStep(n) {
      _wizardStep = Math.max(1, Math.min(WIZARD_STEPS, n));
      // Show/hide steps
      document.querySelectorAll(".wizard-step").forEach((s) => {
        s.classList.toggle("active", parseInt(s.dataset.step, 10) === _wizardStep);
      });
      // Update dots
      document.querySelectorAll(".wizard-dot").forEach((d) => {
        d.classList.toggle("active", parseInt(d.dataset.dot, 10) <= _wizardStep);
      });
      // Update progress bar
      const bar = wizardEl("wizard-progress-bar");
      if (bar) bar.style.width = ((_wizardStep / WIZARD_STEPS) * 100) + "%";
      // Update progress bar aria
      const prog = document.querySelector(".wizard-progress");
      if (prog) prog.setAttribute("aria-valuenow", _wizardStep);
      // Nav buttons
      const prevBtn = wizardEl("wizard-prev");
      const nextBtn = wizardEl("wizard-next");
      const nav = wizardEl("wizard-nav");
      if (prevBtn) prevBtn.hidden = _wizardStep === 1;
      if (_wizardStep < WIZARD_STEPS) {
        if (nav) nav.hidden = false;
        if (nextBtn) nextBtn.hidden = false;
      } else {
        // Step 4 — Done: hide main nav, show inline buttons
        if (nav) nav.hidden = true;
      }
      // Step-specific sync
      if (_wizardStep === 1) syncWizardLangUI();
      if (_wizardStep === 2) syncWizardExpertiseUI();
      if (_wizardStep === 3) syncWizardThemeUI();
      // Accessibility: focus title
      const title = document.querySelector(".wizard-step.active .wizard-title");
      if (title) setTimeout(() => title.focus(), 50);
    }

    function syncWizardLangUI() {
      // UI locale
      document.querySelectorAll("[data-wizard-ui-locale]").forEach((b) => {
        const active = b.dataset.wizardUiLocale === _wizardUILocale;
        b.classList.toggle("active", active);
        b.setAttribute("aria-pressed", String(active));
      });
      // Output locale
      document.querySelectorAll("[data-wizard-output-locale]").forEach((b) => {
        const active = b.dataset.wizardOutputLocale === _wizardOutputLocale;
        b.classList.toggle("active", active);
        b.setAttribute("aria-pressed", String(active));
      });
    }

    function syncWizardExpertiseUI() {
      document.querySelectorAll(".wizard-expertise-card").forEach((card) => {
        card.classList.toggle("active", card.dataset.wizardExpertise === _wizardExpertise);
        const radio = card.querySelector("input[type=radio]");
        if (radio) radio.checked = card.dataset.wizardExpertise === _wizardExpertise;
      });
    }

    function syncWizardThemeUI() {
      document.querySelectorAll("[data-wizard-theme]").forEach((b) => {
        const active = b.dataset.wizardTheme === _wizardTheme;
        b.classList.toggle("active", active);
        b.setAttribute("aria-pressed", String(active));
      });
    }

    function applyWizardSelections() {
      // Apply UI locale
      localStorage.setItem("locale", _wizardUILocale);
      if (typeof window.setLocale === "function") window.setLocale(_wizardUILocale);
      document.documentElement.setAttribute("lang", _wizardUILocale);
      // Sync topbar locale switcher
      document.querySelectorAll(".locale-switcher [data-locale]").forEach((b) => {
        b.setAttribute("aria-pressed", b.dataset.locale === _wizardUILocale ? "true" : "false");
      });
      // Apply output locale
      localStorage.setItem("output_locale", _wizardOutputLocale);
      // Apply expertise
      localStorage.setItem("user_expertise", _wizardExpertise);
      // Apply theme
      applyTheme(_wizardTheme);
      // Sync settings page if open
      const uiSel = document.getElementById("settings-ui-locale");
      if (uiSel) uiSel.value = _wizardUILocale;
      const outSel = document.getElementById("settings-output-locale");
      if (outSel) outSel.value = _wizardOutputLocale;
      const expertGroup = document.getElementById("expertise-toggle-group");
      if (expertGroup) {
        expertGroup.querySelectorAll(".toggle-btn").forEach((b) =>
          b.classList.toggle("active", b.dataset.expertise === _wizardExpertise)
        );
      }
    }

    function finishWizard(startTourAfter) {
      applyWizardSelections();
      localStorage.setItem(WIZARD_DONE_KEY, "true");
      const overlay = wizardEl("first-run-wizard");
      if (overlay) {
        overlay.style.opacity = "0";
        overlay.style.transition = "opacity 0.18s ease";
        setTimeout(() => { overlay.style.display = "none"; }, 200);
      }
      if (startTourAfter) {
        // Give i18n a moment to settle after locale change
        setTimeout(() => {
          if (typeof window.startTour === "function") {
            window.startTour();
          } else if (window.PrideTour) {
            window.PrideTour.reset();
          }
        }, 300);
      }
    }

    function initFirstRunWizard() {
      if (localStorage.getItem(WIZARD_DONE_KEY) === "true") return;
      const overlay = wizardEl("first-run-wizard");
      if (!overlay) return;

      // Show overlay
      overlay.style.display = "flex";
      goToWizardStep(1);

      // --- Step 1: Language buttons ---
      document.querySelectorAll("[data-wizard-ui-locale]").forEach((btn) => {
        btn.addEventListener("click", () => {
          _wizardUILocale = btn.dataset.wizardUiLocale;
          // Auto-sync output locale to match
          _wizardOutputLocale = _wizardUILocale;
          syncWizardLangUI();
          // Apply locale immediately so i18n updates
          if (typeof window.setLocale === "function") window.setLocale(_wizardUILocale);
          document.documentElement.setAttribute("lang", _wizardUILocale);
          localStorage.setItem("locale", _wizardUILocale);
        });
      });
      document.querySelectorAll("[data-wizard-output-locale]").forEach((btn) => {
        btn.addEventListener("click", () => {
          _wizardOutputLocale = btn.dataset.wizardOutputLocale;
          syncWizardLangUI();
        });
      });

      // --- Step 2: Expertise cards ---
      document.querySelectorAll(".wizard-expertise-card").forEach((card) => {
        card.addEventListener("click", () => {
          _wizardExpertise = card.dataset.wizardExpertise;
          syncWizardExpertiseUI();
        });
      });

      // --- Step 3: Theme cards ---
      document.querySelectorAll("[data-wizard-theme]").forEach((btn) => {
        btn.addEventListener("click", () => {
          _wizardTheme = btn.dataset.wizardTheme;
          applyTheme(_wizardTheme);
          syncWizardThemeUI();
        });
      });

      // --- Nav: Next ---
      const nextBtn = wizardEl("wizard-next");
      if (nextBtn) {
        nextBtn.addEventListener("click", () => {
          if (_wizardStep < WIZARD_STEPS) goToWizardStep(_wizardStep + 1);
        });
      }

      // --- Nav: Prev ---
      const prevBtn = wizardEl("wizard-prev");
      if (prevBtn) {
        prevBtn.addEventListener("click", () => {
          if (_wizardStep > 1) goToWizardStep(_wizardStep - 1);
        });
      }

      // --- Step 4: Start tour ---
      const startTourBtn = wizardEl("wizard-start-tour");
      if (startTourBtn) {
        startTourBtn.addEventListener("click", () => finishWizard(true));
      }

      // --- Step 4: Open tutorial (learn intro) ---
      const openLearnBtn = wizardEl("wizard-open-learn");
      if (openLearnBtn) {
        openLearnBtn.addEventListener("click", () => {
          finishWizard(false);
          setTimeout(() => {
            switchView("learn");
            try { localStorage.setItem("devboard-learn-page", "intro"); } catch (_) {}
            setLearnPage("intro");
          }, 250);
        });
      }

      // --- Step 4: Skip ---
      const skipBtn = wizardEl("wizard-finish-skip");
      if (skipBtn) {
        skipBtn.addEventListener("click", () => finishWizard(false));
      }

      // --- Keyboard: Escape closes (skips) ---
      document.addEventListener("keydown", function onWizardKey(e) {
        if (e.key === "Escape" && localStorage.getItem(WIZARD_DONE_KEY) !== "true") {
          finishWizard(false);
          document.removeEventListener("keydown", onWizardKey);
        }
      });
    }

    // Auto-init on DOMContentLoaded (or immediately if DOM ready)
    if (document.readyState === "loading") {
      document.addEventListener("DOMContentLoaded", initFirstRunWizard);
    } else {
      // Slight delay to let i18n.js initialize first
      setTimeout(initFirstRunWizard, 0);
    }
  })();

  // ===================== Learn / Tutorial view (S14.1) =====================

  const LEARN_PAGES = ["intro", "tasks", "departments", "hr", "shortcuts"];
  const LEARN_PAGE_STORAGE_KEY = "devboard-learn-page";

  /** Return the i18n helper, falling back to a minimal wrapper so learn
   *  works even before i18n.js fully initialises (edge case on cold load). */
  function _learnT(key) {
    if (typeof window.t === "function") return window.t(key);
    return key;
  }

  /** Render content of a specific learn page into #learn-content. */
  function setLearnPage(page) {
    if (!LEARN_PAGES.includes(page)) page = "intro";

    // Persist
    try { localStorage.setItem(LEARN_PAGE_STORAGE_KEY, page); } catch (_) {}

    // Highlight active TOC button
    $$(".learn-toc-btn").forEach((btn) => {
      const active = btn.dataset.learnPage === page;
      btn.classList.toggle("active", active);
      btn.setAttribute("aria-current", active ? "page" : "false");
    });

    // Render page content
    const content = document.getElementById("learn-content");
    if (!content) return;

    const title = _learnT("learn.page." + page + ".title");
    const body  = _learnT("learn.page." + page + ".body");

    content.innerHTML =
      `<div class="learn-article">` +
        `<h1 class="learn-article-title">${escapeHtml(title)}</h1>` +
        `<div class="learn-article-body">${body}</div>` +
      `</div>`;

    // Accessibility: move focus to content area
    content.focus({ preventScroll: false });
    content.scrollTop = 0;
  }

  /** Called by switchView when user opens the Learn tab.
   *  Restores last-visited page from localStorage (default: "intro"). */
  function loadLearn() {
    let page = "intro";
    try {
      const saved = localStorage.getItem(LEARN_PAGE_STORAGE_KEY);
      if (saved && LEARN_PAGES.includes(saved)) page = saved;
    } catch (_) {}
    setLearnPage(page);
  }

  // Wire up TOC buttons
  $$(".learn-toc-btn").forEach((btn) => {
    btn.addEventListener("click", () => setLearnPage(btn.dataset.learnPage));
  });

  // Re-render current learn page when the UI locale changes so that all
  // strings (TOC labels + page content) update without a page reload.
  // We hook into the custom "localechange" event that i18n.js fires after
  // switching locale (it calls applyI18nToDOM() which dispatches the event).
  window.addEventListener("localechange", () => {
    if (currentView === "learn") setLearnPage(
      localStorage.getItem(LEARN_PAGE_STORAGE_KEY) || "intro"
    );
  });

  // ===================== S16.3: Global keyboard shortcuts =====================
  // Cmd/Ctrl+K  → focus #search input
  // Esc         → close topmost open modal OR clear #search
  // Cmd/Ctrl+/  → show shortcuts overlay
  // ?           → show shortcuts overlay (when no input focused)
  (function initGlobalShortcuts() {
    const searchInput = $("#search");

    /** Returns the topmost visible .modal element (last in DOM order), or null */
    function getOpenModal() {
      const modals = $$(".modal:not([hidden])");
      return modals.length ? modals[modals.length - 1] : null;
    }

    /** Open shortcuts overlay: populate body from i18n then show */
    function openShortcutsOverlay() {
      const overlay = $("#modal-shortcuts");
      if (!overlay) return;
      const body = $("#modal-shortcuts-body");
      if (body) {
        const pageKey = "learn.page.shortcuts.body";
        const html = (window.i18n && window.i18n(pageKey)) ? window.i18n(pageKey) : null;
        if (html && html !== pageKey) {
          body.innerHTML = html;
        } else {
          // Fallback inline if i18n not ready
          body.innerHTML =
            "<p>Keyboard shortcuts available in the dashboard.</p>" +
            "<table class='learn-shortcuts-table'><thead><tr><th>Key</th><th>Action</th></tr></thead><tbody>" +
            "<tr><td><kbd>Esc</kbd></td><td>Close modal / clear search</td></tr>" +
            "<tr><td><kbd>Cmd / Ctrl + K</kbd></td><td>Global search</td></tr>" +
            "<tr><td><kbd>Cmd / Ctrl + Enter</kbd></td><td>Save task in editor</td></tr>" +
            "<tr><td><kbd>Cmd / Ctrl + N</kbd></td><td>New task</td></tr>" +
            "<tr><td><kbd>Cmd / Ctrl + B</kbd></td><td>Toggle chat panel</td></tr>" +
            "<tr><td><kbd>?</kbd></td><td>Show this list</td></tr>" +
            "</tbody></table>";
        }
      }
      overlay.hidden = false;
      overlay.querySelector(".close")?.focus();
    }

    document.addEventListener("keydown", function onGlobalKey(e) {
      const tag = document.activeElement ? document.activeElement.tagName : "";
      const isTyping = tag === "INPUT" || tag === "TEXTAREA" || tag === "SELECT" ||
                       document.activeElement?.isContentEditable;

      // Cmd/Ctrl + K → focus search (always, prevent browser default)
      if ((e.metaKey || e.ctrlKey) && e.key === "k") {
        e.preventDefault();
        if (searchInput) {
          searchInput.focus();
          searchInput.select();
        }
        return;
      }

      // Cmd/Ctrl + / → shortcuts overlay
      if ((e.metaKey || e.ctrlKey) && e.key === "/") {
        e.preventDefault();
        openShortcutsOverlay();
        return;
      }

      // Cmd/Ctrl + B → toggle chat panel
      if ((e.metaKey || e.ctrlKey) && e.key === "b") {
        // Only if not in a text field (could interfere with bold)
        if (!isTyping) {
          e.preventDefault();
          const chatRail = $(".chat-rail") || $(".chat-panel");
          const chatToggle = $("#chat-toggle") || $("[data-action='toggle-chat']");
          if (chatToggle) chatToggle.click();
        }
        return;
      }

      // Escape → close topmost modal OR clear search
      if (e.key === "Escape") {
        const openModal = getOpenModal();
        if (openModal) {
          // Let existing per-modal Escape handlers run first via capture;
          // if modal is still open after microtask, close it here
          setTimeout(() => {
            if (!openModal.hidden) {
              openModal.hidden = true;
            }
          }, 0);
          return;
        }
        // No modal open → clear search if it has value
        if (searchInput && searchInput.value) {
          searchInput.value = "";
          searchInput.dispatchEvent(new Event("input"));
          searchInput.blur();
          return;
        }
        return;
      }

      // ? → show shortcuts overlay (only when not typing)
      if (e.key === "?" && !isTyping && !e.metaKey && !e.ctrlKey) {
        e.preventDefault();
        openShortcutsOverlay();
        return;
      }
    });
  })();

  // ===================== F2 (1.7): Company Context Modal =====================
  (function () {
    const modal = $("#modal-company-context");
    const form = $("#form-company-context");
    const closeBtn = $("#btn-company-context-close");
    const skipBtn = $("#btn-company-context-skip");
    const settingsBtn = $("#btn-settings-company-context");
    const errorEl = $("#company-context-error");

    if (!modal || !form) return;

    function closeCompanyContextModal(markAsSkipped = false) {
      if (modal) modal.hidden = true;
      if (errorEl) {
        errorEl.hidden = true;
        errorEl.textContent = "";
      }
      // Если юзер закрыл модалку без сохранения — запомним в localStorage,
      // чтобы не показывать каждую загрузку. Через Settings всегда можно открыть.
      if (markAsSkipped) {
        try { localStorage.setItem("company_context_skipped", "true"); } catch (_) {}
      }
    }

    async function openCompanyContextModal(shouldFetch = true) {
      if (shouldFetch) {
        try {
          const resp = await fetch("/api/onboarding/company-context");
          const data = await resp.json();
          if (data.exists && data.content) {
            const lines = data.content.split("\n");
            const frontmatter = {};
            for (let i = 0; i < lines.length; i++) {
              const line = lines[i].trim();
              if (!line || line.startsWith("##")) break;
              const m = line.match(/^(\w+):\s*(.+)$/);
              if (m) frontmatter[m[1]] = m[2];
            }
            if (frontmatter.name) $("#company-context-name").value = frontmatter.name;
            if (frontmatter.description) $("#company-context-description").value = frontmatter.description;
            if (frontmatter.brand_voice) $("#company-context-brand-voice").value = frontmatter.brand_voice;
            if (frontmatter.values) $("#company-context-values").value = frontmatter.values;
            if (frontmatter.audience) $("#company-context-audience").value = frontmatter.audience;
          }
        } catch (e) {
          console.error("Failed to fetch company context:", e);
        }
      }
      if (modal) modal.hidden = false;
      setTimeout(() => $("#company-context-name")?.focus(), 50);
    }

    async function saveCompanyContext(e) {
      e.preventDefault();
      if (errorEl) {
        errorEl.hidden = true;
        errorEl.textContent = "";
      }
      const formData = new FormData(form);
      const name = (formData.get("name") || "").trim();
      const description = (formData.get("description") || "").trim();
      const brand_voice = (formData.get("brand_voice") || "").trim();
      const values = (formData.get("values") || "").trim();
      const audience = (formData.get("audience") || "").trim();

      if (!name) {
        if (errorEl) {
          errorEl.textContent = "Название компании обязательно";
          errorEl.hidden = false;
        }
        return;
      }

      try {
        const resp = await fetch("/api/onboarding/company-context", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ name, description, brand_voice, values, audience }),
        });
        const result = await resp.json();
        if (!resp.ok) {
          const reason = result.reason || result.причина || "Ошибка сохранения";
          if (errorEl) {
            errorEl.textContent = reason;
            errorEl.hidden = false;
          }
          return;
        }
        // После успешного save — сбрасываем флаг skipped (контекст теперь есть).
        try { localStorage.removeItem("company_context_skipped"); } catch (_) {}
        closeCompanyContextModal();
      } catch (err) {
        console.error("Failed to save company context:", err);
        if (errorEl) {
          errorEl.textContent = err.message || "Сетевая ошибка";
          errorEl.hidden = false;
        }
      }
    }

    form.addEventListener("submit", saveCompanyContext);
    // Close/Skip — оба ставят флаг "skipped" чтобы не показывать каждую загрузку.
    if (closeBtn) closeBtn.addEventListener("click", () => closeCompanyContextModal(true));
    if (skipBtn) skipBtn.addEventListener("click", () => closeCompanyContextModal(true));
    if (settingsBtn) {
      settingsBtn.addEventListener("click", () => {
        // Из Settings — открываем всегда, даже если skipped.
        openCompanyContextModal(true);
      });
    }

    async function checkCompanyContextOnLoad(retryCount = 0) {
      try {
        const r = await fetch("/api/onboarding/company-context");
        if (!r.ok) throw new Error("HTTP " + r.status);
        const data = await r.json();
        if (data.exists) return;  // файл есть — ничего не показываем
        // Юзер уже скипал модалку в этой сессии браузера → не показываем снова.
        // Через Settings → «Контекст компании» можно открыть всегда.
        if (localStorage.getItem("company_context_skipped") === "true") return;
        const firstRunDone = localStorage.getItem("first_run_done") === "true";
        if (firstRunDone) {
          // First-run wizard уже пройден → показываем onboarding сразу.
          setTimeout(() => openCompanyContextModal(false), 300);
        } else {
          // First-run wizard ещё идёт → дождаться его завершения.
          // Backup: если wizard:done не диспатчится в 10 сек — показать всё равно.
          let fired = false;
          const fire = () => {
            if (fired) return;
            fired = true;
            setTimeout(() => openCompanyContextModal(false), 300);
            window.removeEventListener("wizard:done", fire);
          };
          window.addEventListener("wizard:done", fire);
          setTimeout(fire, 10000);
        }
      } catch (e) {
        // Retry до 3 раз — backend мог не успеть стартовать.
        if (retryCount < 3) {
          setTimeout(() => checkCompanyContextOnLoad(retryCount + 1), 1500);
        } else {
          console.error("Failed to check company context after 3 retries:", e);
        }
      }
    }

    window.openCompanyContextModal = openCompanyContextModal;
    window.closeCompanyContextModal = closeCompanyContextModal;
    setTimeout(checkCompanyContextOnLoad, 100);
  })();

  refresh();
  setInterval(refresh, REFRESH_MS);
  connectLiveStream();
})();
