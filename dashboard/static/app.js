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
    // Slug aliases (for chat authors and any slug-based references)
    "teamlead":  { slug: "teamlead",   en: "Team Lead",   ru: "тимлид" },
    "backend":   { slug: "backend",    en: "Backend",     ru: "бэкенд" },
    "architect": { slug: "architect",  en: "Architect",   ru: "архитектор" },
    "techwriter":{ slug: "techwriter", en: "Tech Writer", ru: "техписатель" },
    "user":      { slug: "user",       en: "User",        ru: "пользователь" },
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
  }
  // Apply initial view from localStorage
  switchView(currentView);
  $$(".nav-item").forEach((b) =>
    b.addEventListener("click", () => switchView(b.dataset.view)),
  );

  // ===================== Tasks: list & render =====================

  async function fetchTasks() {
    const r = await fetch("/api/tasks");
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
  function pickModelForTask(t) {
    const labels = new Set(t.labels || []);
    if (labels.has("epic")) return null;
    if (labels.has("destructive")) return "opus";
    if (labels.has("design") || labels.has("architecture") || labels.has("adr")) return "opus";
    if (labels.has("trivial") || labels.has("chore") || labels.has("rename") || labels.has("polish")) return "haiku";
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
  function openNewTaskModal() {
    $("#form-new-task").reset();
    $("#modal-new").hidden = false;
  }
  $("#form-new-task").addEventListener("submit", async (e) => {
    e.preventDefault();
    const form = e.target;
    const body = {
      title: form.title.value.trim(),
      description: form.description.value,
      priority: form.priority.value,
      assignee: form.assignee.value || null,
      requires_approval: form.requires_approval.checked,
    };
    const r = await fetch("/api/tasks", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
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
    if (s.status === "running") {
      badge.textContent = i18n("team.status.running");
      badge.className = "status running";
      $("#btn-start").hidden = true;
      $("#btn-stop").hidden = false;
    } else if (s.auto_mode && s.auto_pause_reason) {
      badge.textContent = i18n("team.status.auto_paused");
      badge.className = "status auto-paused";
      $("#btn-start").hidden = false;
      $("#btn-stop").hidden = true;
    } else {
      badge.textContent = i18n("team.status.stopped");
      badge.className = "status stopped";
      $("#btn-start").hidden = false;
      $("#btn-stop").hidden = true;
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
  $("#btn-start").addEventListener("click", async () => {
    const expertise = localStorage.getItem("user_expertise") || "non-tech";
    const r = await fetch("/api/team/start", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ user_expertise: expertise }),
    });
    if (!r.ok) {
      const err = await r.json().catch(() => ({}));
      alert(i18n("team.start_failed") + (err.reason || r.status));
    }
    refreshTeamStatus();
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
    const r = await fetch("/api/inbox");
    if (!r.ok) return;
    const inbox = await r.json();
    renderInbox(inbox);
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
    const r = await fetch("/api/tasks?archived=1");
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
    const r = await fetch("/api/chat?limit=200");
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

  $("#chat-form").addEventListener("submit", async (e) => {
    e.preventDefault();
    const input = $("#chat-input");
    const text = input.value.trim();
    if (!text) return;
    input.value = "";
    const r = await fetch("/api/chat", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ author: "пользователь", text }),
    });
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

    const rows = roles.map((r) => {
      const llm = r.llm || "—";
      const model = escapeHtml(r.model || "—");
      const desc = escapeHtml(r.description || "—");
      // Локализованное имя роли:
      // 1. display_name_en / display_name_ru если API вернул (поле из БД)
      // 2. roles.names.<slug> из i18n-словаря
      // 3. fallback — slug
      let displayName;
      if (locale === "en" && r.display_name_en) {
        displayName = r.display_name_en;
      } else if (locale !== "en" && r.display_name_ru) {
        displayName = r.display_name_ru;
      } else {
        const i18nKey = `roles.names.${r.name.replace(/-/g, "_")}`;
        const i18nVal = i18n(i18nKey);
        displayName = (i18nVal !== i18nKey) ? i18nVal : r.name;
      }
      return `<tr data-role-name="${escapeAttr(r.name)}">
        <td class="role-name-cell"><span class="role-display-name">${escapeHtml(displayName)}</span><code class="role-slug">${escapeHtml(r.name)}</code></td>
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
    }).join("");

    body.innerHTML = `
      <table class="roles-table">
        <thead>
          <tr>
            <th>${i18n("roles.col.name")}</th>
            <th>${i18n("roles.col.description")}</th>
            <th>${i18n("roles.col.llm")}</th>
            <th>${i18n("roles.col.model")}</th>
            <th>${i18n("roles.col.actions")}</th>
          </tr>
        </thead>
        <tbody>${rows}</tbody>
      </table>
    `;

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
      const r = await fetch("/api/roles");
      if (!r.ok) throw new Error("api/roles " + r.status);
      const data = await r.json();
      // API returns {статус, всего, роли:[{name, description, capabilities}]}
      // capabilities can be a JSON object with extended fields (llm, model, etc.)
      const raw = data.роли || [];
      _rolesCache = raw.map((role) => {
        const caps = role.capabilities;
        const ext = (caps && typeof caps === "object" && !Array.isArray(caps)) ? caps : {};
        return {
          name: role.name,
          description: role.description,
          llm: ext.llm || "claude",
          model: ext.model || "",
          temperature: ext.temperature != null ? ext.temperature : 1,
          max_tokens: ext.max_tokens || 8096,
          system_prompt: ext.system_prompt || "",
        };
      });
      renderRolesTable(_rolesCache);
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
      const data = await fetchTasks();
      renderBoard(data);
      refreshDemoState(data.задачи || []);
      await refreshTeamStatus();
      await refreshInbox();
      await refreshUsage();
      await refreshRouter();
      await refreshSilence();
      await refreshChat();
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

  refresh();
  setInterval(refresh, REFRESH_MS);
  connectLiveStream();
})();
