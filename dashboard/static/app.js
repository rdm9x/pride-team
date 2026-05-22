(function () {
  "use strict";

  const REFRESH_MS = 3000;
  const STATUSES = ["todo", "wip", "needs_approval", "review", "done"];

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
  });

  // ===================== Views & navigation =====================

  let currentView = "inbox";
  function switchView(name) {
    currentView = name;
    $$(".nav-item").forEach((b) => b.classList.toggle("active", b.dataset.view === name));
    $$(".view").forEach((v) => (v.hidden = v.dataset.view !== name));
    if (name === "archive") loadArchive();
    if (name === "settings") loadSettings();
    if (name === "roles") loadRoles();
  }
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
  function i18n(key) {
    return (typeof window.t === "function") ? window.t(key) : key;
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
    const role = t.assignee ? `<span class="role">${t.assignee}</span>` : "";
    const linkIcon = t._has_deps ? `<span class="link-icon ico" title="${i18n("kanban.card.has_deps")}">🔗</span>` : "";
    const model = pickModelForTask(t);
    const modelChip = model
      ? `<span class="model ${model}" title="Модель LLM для этой задачи: ${model}">${model}</span>`
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
        alert(i18n("kanban.move_failed") + (err.причина || r.status));
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

  async function openTaskModal(id) {
    const r = await fetch("/api/tasks/" + id);
    if (!r.ok) return;
    const { задача: t } = await r.json();
    $("#modal-task-title").textContent = `#${t.id.slice(0, 6)} · ${t.title}`;
    $("#modal-task-body").innerHTML = renderTaskBody(t);
    bindTaskActions(t);
    $("#modal-task").hidden = false;
  }

  function renderTaskBody(t) {
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
      `<div class="sub">#${s.id.slice(0, 6)} · ${escapeHtml(statusLabel(s.status))} · ${escapeHtml(s.assignee || i18n("task.subtasks.no_assignee"))} · ${escapeHtml(s.title)}</div>`,
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
        <span class="pill role">${escapeHtml(t.assignee || i18n("task.meta.unassigned"))}</span>
        <span class="pill prio-${escapeHtml(t.priority)}">${escapeHtml(t.priority)}</span>
        <span class="pill">labels: ${labels}</span>
        <button class="edit-btn" id="btn-edit" title="${i18n("task.meta.edit_title")}">${i18n("task.meta.edit_btn")}</button>
      </div>
      <div style="color:var(--muted);font-size:12px;margin-top:6px">
        ${createdUpdated}
      </div>

      <div id="view-mode">
        <h3>${i18n("task.section.description")}</h3>
        <div style="white-space:pre-wrap">${escapeHtml(t.description || "—")}</div>
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
              ${["тимлид", "бэкенд", "qa", "архитектор", "frontend", "devops", "техписатель", "пользователь"].map((r) => `<option value="${r}"${r === t.assignee ? " selected" : ""}>${r}</option>`).join("")}
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
          alert(i18n("modal.task.save_failed") + (err.причина || r.status));
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
          alert(i18n("modal.task.dep_failed") + (err.причина || r.status));
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
      alert(i18n("modal.task.create_failed") + (err.причина || r.status));
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
      const data = await r.json();
      if (data.already_exists) {
        showDemoToast('demo.already_exists', 'Demo data already loaded.');
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
    const r = await fetch("/api/team/start", { method: "POST" });
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
      if (inbox.approvals.includes(t)) groupName = i18n("inbox.notify.approvals");
      else if (inbox.reviews.includes(t)) groupName = i18n("inbox.notify.reviews");
      else if (inbox.questions.includes(t)) groupName = i18n("inbox.notify.questions");
      notify(groupName, t.title);
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
          <span class="role">${i18n("inbox.from_prefix")}${escapeHtml(author)}</span>
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
  async function loadSettings() {
    const r = await fetch("/api/usage");
    const u = await r.json();
    const row = (label, w) =>
      `<tr><td>${label}</td><td class="num">${w.sessions}</td><td class="num">${w.turns}</td>` +
      `<td class="num">${(w.input_tokens || 0).toLocaleString(dtLocale())}</td>` +
      `<td class="num">${(w.output_tokens || 0).toLocaleString(dtLocale())}</td>` +
      `<td class="num">$${(w.cost_usd || 0).toFixed(4)}</td></tr>`;
    const models = (u.models || []).map(
      (m) => `<li><code>${escapeHtml(m.model || "—")}</code> · ${m.sessions} ${i18n("usage.models.unit_sessions")} · ${m.turns} ${i18n("usage.models.unit_turns")}</li>`
    ).join("") || `<li style='color:#8b949e'>${i18n("usage.models.empty")}</li>`;
    const noteLine1 = i18n("usage.note.line1");
    const noteLine2 = i18n("usage.note.line2");
    $("#usage-detail-table").innerHTML = `
      <table class="usage-table">
        <thead>
          <tr><th>${i18n("usage.table.window")}</th><th class="num">${i18n("usage.table.sessions")}</th><th class="num">${i18n("usage.table.turns")}</th>
              <th class="num">Input</th><th class="num">Output</th>
              <th class="num">${i18n("usage.table.cost")}</th></tr>
        </thead>
        <tbody>
          ${row(i18n("usage.row.last5h"), u.last_5h || {})}
          ${row(i18n("usage.row.today"), u.today || {})}
          ${row(i18n("usage.row.last24h"), u.last_24h || {})}
          ${row(i18n("usage.row.total"), u.total || {})}
        </tbody>
      </table>
      <h3 style="margin-top:18px">${i18n("usage.models.title")}</h3>
      <ul style="padding-left: 20px; margin: 0">${models}</ul>
      <div class="usage-note">
        ${noteLine1}<br>
        ${noteLine2}
      </div>
    `;
    // TG-статус
    try {
      const t = await fetch("/api/usage");
      // Простая проверка наличия env-переменных через router (не идеально, но рабоче)
    } catch (_) {}
  }

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
    } catch (_) {}
  }
  requestNotifPermission();

  function notify(title, body) {
    if (!notificationsAllowed) return;
    if (!document.hidden && document.hasFocus()) return; // окно в фокусе — не дёргаем
    try {
      const n = new Notification(title, {
        body: (body || "").slice(0, 200),
        icon: "/static/favicon.png",
        tag: "devboard",
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
  };

  function renderChat(messages) {
    const body = $("#chat-body");
    if (messages.length === 0) {
      body.innerHTML = `<div style="color:var(--muted);font-size:11px;font-style:italic">${i18n("chat.empty")}</div>`;
      return;
    }
    const atBottom = body.scrollHeight - body.scrollTop - body.clientHeight < 30;
    body.innerHTML = messages.map((m) => {
      const time = new Date(m.created_at * 1000).toLocaleTimeString(dtLocale(), {hour:"2-digit", minute:"2-digit"});
      const icon = AUTHOR_ICON[m.author] || "•";
      return `<div class="chat-message author-${escapeHtml(m.author)}">
        <div class="head">
          <span class="who"><span class="ico">${icon}</span> ${escapeHtml(m.author)}</span>
          <span class="time">${time}</span>
        </div>
        <div class="chat-text">${formatChatText(m.text)}</div>
      </div>`;
    }).join("");
    body.querySelectorAll("[data-task-ref]").forEach((el) =>
      el.addEventListener("click", () => openTaskModal(el.dataset.taskRef)),
    );
    if (atBottom) body.scrollTop = body.scrollHeight;

    // === Уведомления о новых сообщениях НЕ от Дмитрия ===
    const latest = messages[messages.length - 1];
    lastChatId = latest.id;
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
      // Browser notification — для самого свежего
      const m = newFromTeam[newFromTeam.length - 1];
      const preview = m.text.slice(0, 120) + (m.text.length > 120 ? "…" : "");
      notify(`${AUTHOR_ICON[m.author] || ""} ${m.author}`, preview);
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
      alert(i18n("chat.send_failed") + (err.причина || r.status));
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
      alert(i18n("modal.task.create_failed") + (err.причина || r.status));
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
      alert(i18n("roles.error.deleteFailed") + (err.причина || r.status));
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

    const rows = roles.map((r) => {
      const llm = r.llm || "—";
      const model = escapeHtml(r.model || "—");
      const desc = escapeHtml(r.description || "—");
      return `<tr data-role-name="${escapeAttr(r.name)}">
        <td class="role-name-cell"><code>${escapeHtml(r.name)}</code></td>
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
            <th data-i18n="roles.col.name">Имя</th>
            <th data-i18n="roles.col.description">Описание</th>
            <th data-i18n="roles.col.llm">LLM</th>
            <th data-i18n="roles.col.model">Модель</th>
            <th data-i18n="roles.col.actions">Действия</th>
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
    // Если открыта settings / archive — перечитываем
    if (currentView === "settings") loadSettings();
    if (currentView === "archive") loadArchive();
  });

  refresh();
  setInterval(refresh, REFRESH_MS);
  connectLiveStream();
})();
