/**
 * Chat Page (F1/F2/F3/F4)
 * Layout: 3-column grid (20% / 50% / 30%) with right column split 30%/70%
 *
 * Features:
 * - F1: Layout, responsive, dark theme
 * - F2: Threads list with search, sort by updated_at, archive collapsible
 * - F3: Load messages, render with markdown
 * - F4: Planning create form, managing director tasks
 */

(function () {
  'use strict';

  // State
  let allThreads = {
    active: [],
    archived: [],
  };

  let currentThreadId = null;

  // ============================================================
  // Simple Markdown Renderer
  // ============================================================

  function renderMarkdown(text) {
    let html = escapeHtml(text);

    // Headers
    html = html.replace(/^### (.+)$/gm, '<h3>$1</h3>');
    html = html.replace(/^## (.+)$/gm, '<h2>$1</h2>');
    html = html.replace(/^# (.+)$/gm, '<h1>$1</h1>');

    // Bold
    html = html.replace(/\*\*(.+?)\*\*/g, '<strong>$1</strong>');
    html = html.replace(/__(.+?)__/g, '<strong>$1</strong>');

    // Italic
    html = html.replace(/\*(.+?)\*/g, '<em>$1</em>');
    html = html.replace(/_(.+?)_/g, '<em>$1</em>');

    // Code (inline)
    html = html.replace(/`([^`]+)`/g, '<code>$1</code>');

    // Code block
    html = html.replace(/```([a-z]*)\n([\s\S]*?)```/g, '<pre><code class="language-$1">$2</code></pre>');

    // Lists (unordered)
    html = html.replace(/^\s*[-*] (.+)$/gm, '<li>$1</li>');
    html = html.replace(/(<li>.*<\/li>)/s, (match) => '<ul>' + match + '</ul>');

    // Line breaks
    html = html.replace(/\n\n/g, '</p><p>');
    html = '<p>' + html + '</p>';

    return html;
  }

  // ============================================================
  // Theme Initialization
  // ============================================================

  function initTheme() {
    // Темой управляет app.js (ключ 'devboard-theme', дефолт 'dark').
    // Здесь оставлен no-op чтобы не перетирать data-theme своим дефолтом.
  }

  // ============================================================
  // F2: Load Threads (active & archived)
  // ============================================================

  async function loadThreads() {
    try {
      // Fetch active threads
      const activeRes = await fetch('/api/threads?status=active');
      if (!activeRes.ok) throw new Error('Failed to load active threads');
      const activeData = await activeRes.json();
      allThreads.active = (activeData.threads || []).sort((a, b) => (b.updated_at || 0) - (a.updated_at || 0));

      // Fetch archived/finished threads
      const finishedRes = await fetch('/api/threads?status=finished');
      if (!finishedRes.ok) throw new Error('Failed to load finished threads');
      const finishedData = await finishedRes.json();
      allThreads.archived = (finishedData.threads || []).sort((a, b) => (b.updated_at || 0) - (a.updated_at || 0));

      // Also fetch archived status threads
      const archivedRes = await fetch('/api/threads?status=archived');
      if (archivedRes.ok) {
        const archivedData = await archivedRes.json();
        const archivedThreads = (archivedData.threads || []).sort((a, b) => (b.updated_at || 0) - (a.updated_at || 0));
        allThreads.archived = allThreads.archived.concat(archivedThreads);
      }

      // Sort archived threads by updated_at descending
      allThreads.archived.sort((a, b) => (b.updated_at || 0) - (a.updated_at || 0));

      // Render active threads
      renderActiveThreads(allThreads.active);

      // Update archive count
      updateArchiveCount();

      // Initialize archive toggle
      initArchiveToggle();

      // Если archive section уже развёрнут — перерисовать (после archive/restore).
      const archiveList = document.getElementById('threads-archive-list');
      if (archiveList && archiveList.style.display === 'flex') {
        renderArchiveThreads(allThreads.archived);
      }

      // Восстанавливаем последний выбранный thread (если он ещё активен),
      // иначе — auto-select первый.
      let restored = null;
      try {
        const savedId = localStorage.getItem('chat_active_thread');
        if (savedId) {
          restored = allThreads.active.find(t => t.id === savedId);
        }
      } catch (_) { /* localStorage недоступен — пропускаем */ }
      const pick = restored || allThreads.active[0];
      if (pick) {
        selectThread({ id: pick.id, title: pick.title });
      }
    } catch (error) {
      console.error('Error loading threads:', error);
      const activeList = document.getElementById('threads-active-list');
      if (activeList) {
        activeList.innerHTML = `<div class="loading" style="color: var(--red); text-align: center;">Error loading threads</div>`;
      }
    }
  }

  // ============================================================
  // F2: Render Active Threads
  // ============================================================

  function renderActiveThreads(threads) {
    const container = document.getElementById('threads-active-list');
    if (!container) return;

    if (threads.length === 0) {
      container.innerHTML = '<div class="loading" style="font-size: 11px; color: var(--text-3); text-align: center; padding: 16px;">No threads yet</div>';
      return;
    }

    const archiveTitle = (window.t && window.t('chat.threads.archive_action')) || 'Архивировать';
    container.innerHTML = threads
      .map((thread) => {
        const icon = thread.kind === 'planning' ? '🤔' : '📌';
        const timestamp = formatTimeAgo(thread.updated_at);
        const isActive = thread.id === currentThreadId;

        return `
          <div class="thread-item ${isActive ? 'active' : ''}" data-thread-id="${escapeHtml(thread.id)}" data-thread-title="${escapeHtml(thread.title)}">
            <div style="display: flex; gap: 6px; align-items: flex-start;">
              <span style="font-size: 14px; flex-shrink: 0;">${icon}</span>
              <div style="flex: 1; min-width: 0;">
                <div style="font-weight: 500; color: inherit; word-break: break-word; white-space: normal;">${escapeHtml(thread.title)}</div>
                <div style="font-size: 10px; color: var(--text-3); margin-top: 2px;">${timestamp}</div>
              </div>
              <button type="button" class="thread-row-action" data-action="archive"
                      data-thread-id="${escapeHtml(thread.id)}"
                      title="${escapeHtml(archiveTitle)}"
                      aria-label="${escapeHtml(archiveTitle)}">🗄</button>
            </div>
          </div>
        `;
      })
      .join('');

    // Attach click handlers
    container.querySelectorAll('.thread-item').forEach((item) => {
      item.addEventListener('click', (e) => {
        if (e.target.closest('.thread-row-action')) return;  // клик по кнопке — не открывать тред
        selectThread({
          id: item.dataset.threadId,
          title: item.dataset.threadTitle,
        });
      });
    });
    container.querySelectorAll('.thread-row-action[data-action="archive"]').forEach((btn) => {
      btn.addEventListener('click', (e) => {
        e.stopPropagation();
        archiveThread(btn.dataset.threadId);
      });
    });
  }

  async function archiveThread(threadId) {
    if (!threadId) return;
    const confirmMsg = (window.t && window.t('chat.threads.archive_confirm')) || 'Архивировать этот чат?';
    const ok = await (window.customConfirm ? window.customConfirm(confirmMsg) : Promise.resolve(confirm(confirmMsg)));
    if (!ok) return;
    try {
      const resp = await fetch(`/api/threads/${encodeURIComponent(threadId)}`, {
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ status: 'archived' }),
      });
      if (!resp.ok) throw new Error('archive failed');
      // Если архивируем активный тред — снять selection (loadThreads подберёт другой)
      if (threadId === currentThreadId) {
        try { localStorage.removeItem('chat_active_thread'); } catch (_) { /* ignore */ }
        currentThreadId = null;
      }
      await loadThreads();
    } catch (err) {
      console.error('archive thread failed', err);
      await (window.customAlert || alert)('Не удалось архивировать тред');
    }
  }

  async function restoreThread(threadId) {
    if (!threadId) return;
    try {
      const resp = await fetch(`/api/threads/${encodeURIComponent(threadId)}`, {
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ status: 'active' }),
      });
      if (!resp.ok) throw new Error('restore failed');
      await loadThreads();
    } catch (err) {
      console.error('restore thread failed', err);
      await (window.customAlert || alert)('Не удалось восстановить тред');
    }
  }

  // ============================================================
  // F2: Archive Toggle
  // ============================================================

  function initArchiveToggle() {
    const toggle = document.getElementById('archive-toggle');
    const archiveList = document.getElementById('threads-archive-list');
    const archiveIcon = document.getElementById('archive-icon');

    if (!toggle || !archiveList) return;

    let isExpanded = false;

    toggle.addEventListener('click', () => {
      isExpanded = !isExpanded;
      archiveIcon.textContent = isExpanded ? '▼' : '▶';
      archiveList.style.display = isExpanded ? 'flex' : 'none';

      if (isExpanded && allThreads.archived.length > 0) {
        renderArchiveThreads(allThreads.archived);
      }
    });
  }

  function updateArchiveCount() {
    const badge = document.getElementById('archive-count');
    if (badge) {
      badge.textContent = `(${allThreads.archived.length})`;
    }
  }

  function renderArchiveThreads(threads) {
    const container = document.getElementById('threads-archive-list');
    if (!container) return;

    if (threads.length === 0) {
      container.innerHTML = '<div class="loading" style="font-size: 11px; color: var(--text-3); text-align: center; padding: 12px;">No archived threads</div>';
      return;
    }

    const restoreTitle = (window.t && window.t('chat.threads.restore_action')) || 'Восстановить';
    container.innerHTML = threads
      .map((thread) => {
        const icon = thread.kind === 'planning' ? '🤔' : '📌';
        const timestamp = formatTimeAgo(thread.updated_at);
        const isActive = thread.id === currentThreadId;

        return `
          <div class="archive-thread-item ${isActive ? 'active' : ''}" data-thread-id="${escapeHtml(thread.id)}" data-thread-title="${escapeHtml(thread.title)}">
            <div style="display: flex; gap: 6px; align-items: flex-start;">
              <span style="font-size: 14px; flex-shrink: 0;">${icon}</span>
              <div style="flex: 1; min-width: 0;">
                <div style="font-weight: 500; color: inherit; word-break: break-word; white-space: normal;">${escapeHtml(thread.title)}</div>
                <div style="font-size: 10px; color: var(--text-3); margin-top: 2px;">${timestamp}</div>
              </div>
              <button type="button" class="thread-row-action" data-action="restore"
                      data-thread-id="${escapeHtml(thread.id)}"
                      title="${escapeHtml(restoreTitle)}"
                      aria-label="${escapeHtml(restoreTitle)}">↺</button>
            </div>
          </div>
        `;
      })
      .join('');

    // Attach click handlers
    container.querySelectorAll('.archive-thread-item').forEach((item) => {
      item.addEventListener('click', (e) => {
        if (e.target.closest('.thread-row-action')) return;
        selectThread({
          id: item.dataset.threadId,
          title: item.dataset.threadTitle,
        });
      });
    });
    container.querySelectorAll('.thread-row-action[data-action="restore"]').forEach((btn) => {
      btn.addEventListener('click', (e) => {
        e.stopPropagation();
        restoreThread(btn.dataset.threadId);
      });
    });
  }

  // ============================================================
  // F2: Thread Selection
  // ============================================================

  function selectThread(threadData) {
    if (!threadData || !threadData.id) return;

    currentThreadId = threadData.id;
    try { localStorage.setItem('chat_active_thread', threadData.id); } catch (_) { /* ignore */ }
    // Stage 3: обновляем planning-баннер для нового треда.
    if (typeof _fetchAndRenderPlanning === 'function') _fetchAndRenderPlanning();

    // Remove active from all threads (active + archived)
    document.querySelectorAll('.thread-item, .archive-thread-item').forEach((item) => {
      item.classList.remove('active');
    });

    // Mark selected thread as active
    const selectedItem = document.querySelector(
      `.thread-item[data-thread-id="${threadData.id}"], .archive-thread-item[data-thread-id="${threadData.id}"]`
    );
    if (selectedItem) {
      selectedItem.classList.add('active');
    }

    // Update center panel
    loadAndRenderMessages(threadData.id, threadData.title);
  }

  // ============================================================
  // F3: Load Messages from API
  // ============================================================

  async function loadAndRenderMessages(threadId, threadTitle) {
    const headerEl = document.querySelector('.chat-header h2');
    const messagesContainer = document.querySelector('.chat-messages');

    if (headerEl) {
      headerEl.textContent = threadTitle || 'Conversation';
    }

    if (!messagesContainer) return;

    messagesContainer.innerHTML = '<div class="loading">Loading messages…</div>';

    try {
      const response = await fetch(`/api/threads/${threadId}/messages?viewer=owner`);
      if (!response.ok) throw new Error('Failed to load messages');

      const data = await response.json();
      const messages = data.messages || [];

      messagesContainer.innerHTML = '';

      if (messages.length === 0) {
        messagesContainer.innerHTML = '<div class="message-placeholder">No messages yet. Start the conversation!</div>';
        return;
      }

      // Render each message
      messages.forEach((msg) => {
        const msgEl = renderMessage(msg);
        messagesContainer.appendChild(msgEl);
      });

      // Auto-scroll to bottom
      messagesContainer.scrollTop = messagesContainer.scrollHeight;
    } catch (error) {
      console.error('Error loading messages:', error);
      messagesContainer.innerHTML = '<div class="message-placeholder" style="color: var(--red);">Error loading messages</div>';
    }
  }

  // ============================================================
  // Render Single Message
  // ============================================================

  function renderMessage(msg) {
    const msgEl = document.createElement('div');
    msgEl.className = 'message-card';
    msgEl.style.cssText = `
      background: var(--surface-2);
      border: 1px solid var(--border);
      border-radius: 6px;
      padding: 12px;
    `;

    // Author + timestamp
    const headerEl = document.createElement('div');
    headerEl.style.cssText = `
      display: flex;
      justify-content: space-between;
      align-items: center;
      margin-bottom: 8px;
      padding-bottom: 8px;
      border-bottom: 1px solid var(--border);
      font-size: 11px;
      color: var(--text-3);
    `;

    const authorEl = document.createElement('strong');
    authorEl.style.color = 'var(--text)';
    authorEl.textContent = msg.author || 'Unknown';
    headerEl.appendChild(authorEl);

    const timeEl = document.createElement('span');
    timeEl.textContent = formatTime(msg.created_at);
    headerEl.appendChild(timeEl);

    msgEl.appendChild(headerEl);

    // Message text (rendered as markdown)
    const textEl = document.createElement('div');
    textEl.className = 'message-text';
    textEl.style.cssText = `
      color: var(--text-2);
      font-size: 12px;
      line-height: 1.5;
      word-break: break-word;
    `;
    textEl.innerHTML = renderMarkdown(msg.text);
    msgEl.appendChild(textEl);

    return msgEl;
  }

  // ============================================================
  // F2: Search Filter
  // ============================================================

  function initThreadSearch() {
    const searchInput = document.getElementById('threads-search');
    if (!searchInput) return;

    searchInput.addEventListener('input', (e) => {
      const query = e.target.value.toLowerCase().trim();

      // Filter active threads
      document.querySelectorAll('#threads-active-list .thread-item').forEach((item) => {
        const title = (item.dataset.threadTitle || '').toLowerCase();
        const matches = !query || title.includes(query);
        item.classList.toggle('hidden', !matches);
      });

      // Filter archived threads
      document.querySelectorAll('#threads-archive-list .archive-thread-item').forEach((item) => {
        const title = (item.dataset.threadTitle || '').toLowerCase();
        const matches = !query || title.includes(query);
        item.classList.toggle('hidden', !matches);
      });
    });
  }

  // ============================================================
  // Format Timestamps
  // ============================================================

  function formatTimeAgo(timestamp) {
    if (!timestamp) return '';

    const now = Math.floor(Date.now() / 1000);
    const diff = now - timestamp;

    if (diff < 60) return 'now';
    if (diff < 3600) return `${Math.floor(diff / 60)}m ago`;
    if (diff < 86400) return `${Math.floor(diff / 3600)}h ago`;
    if (diff < 604800) return `${Math.floor(diff / 86400)}d ago`;

    const date = new Date(timestamp * 1000);
    return date.toLocaleDateString('en-US', { month: 'short', day: 'numeric' });
  }

  function formatTime(timestamp) {
    if (!timestamp) return '';

    const date = new Date(timestamp * 1000 || timestamp);
    const now = new Date();
    const sameDay = date.toDateString() === now.toDateString();

    if (sameDay) {
      return date.toLocaleTimeString('en-US', { hour: '2-digit', minute: '2-digit', hour12: false });
    }
    return date.toLocaleDateString('en-US', { month: 'short', day: 'numeric' });
  }

  // ============================================================
  // Message Input Handler + Send
  // ============================================================

  function initMessageInput() {
    const input = document.getElementById('message-input');
    const sendButton = document.getElementById('btn-send-message');
    const startSessionButton = document.getElementById('btn-start-session');

    if (!input || !sendButton) return;

    async function sendMessage() {
      const text = input.value.trim();
      if (!text || !currentThreadId) return;

      input.disabled = true;
      sendButton.disabled = true;

      try {
        const response = await fetch(`/api/threads/${currentThreadId}/messages`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            author: 'owner',
            text: text,
          }),
        });

        if (!response.ok) throw new Error('Failed to send message');

        input.value = '';
        await loadAndRenderMessages(currentThreadId);
        input.focus();
      } catch (error) {
        console.error('Error sending message:', error);
        await (window.customAlert || alert)('Failed to send message: ' + error.message);
      } finally {
        input.disabled = false;
        sendButton.disabled = false;
      }
    }

    async function startSession() {
      if (!currentThreadId) {
        await (window.customAlert || alert)('Please select a thread first');
        return;
      }

      startSessionButton.disabled = true;
      try {
        const response = await fetch('/api/team/start', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            thread_id: currentThreadId,
          }),
        });

        if (!response.ok) throw new Error('Failed to start session');

        console.log('Team session started with thread context');
        await (window.customAlert || alert)('Team session started');
      } catch (error) {
        console.error('Error starting session:', error);
        await (window.customAlert || alert)('Failed to start session: ' + error.message);
      } finally {
        startSessionButton.disabled = false;
      }
    }

    sendButton.addEventListener('click', sendMessage);
    if (startSessionButton) {
      startSessionButton.addEventListener('click', startSession);
    }

    input.addEventListener('keydown', (e) => {
      if ((e.metaKey || e.ctrlKey) && e.key === 'Enter') {
        e.preventDefault();
        sendMessage();
      }
    });
  }

  // ============================================================
  // Utility: Escape HTML
  // ============================================================

  function escapeHtml(text) {
    const div = document.createElement('div');
    div.textContent = text;
    return div.innerHTML;
  }

  // ============================================================
  // Load Planning Departments (F4)
  // ============================================================

  async function loadPlanningDepartments() {
    const container = document.getElementById('planning-departments');
    if (!container) return;

    try {
      const response = await fetch('/api/departments');
      if (!response.ok) throw new Error('Failed to load departments');

      const data = await response.json();
      const depts = data.departments || [];

      container.innerHTML = '';

      depts.forEach((dept) => {
        const label = document.createElement('label');
        label.className = 'dept-checkbox';
        label.innerHTML = `
          <input type="checkbox" name="dept_${dept.id}" value="${dept.id}">
          <span>${dept.name}</span>
        `;
        container.appendChild(label);
      });
    } catch (error) {
      console.error('Error loading departments:', error);
      container.innerHTML = '<p class="loading" style="color: var(--red);">Не удалось загрузить отделы</p>';
    }
  }

  // ============================================================
  // Planning banner (Stage 3) — индикатор прогресса в треде +
  // кнопки accept/reject/revise когда планёрка завершена.
  // ============================================================

  let _planningPollTimer = null;

  function _humanPlanningStatus(p) {
    if (!p) return '';
    if (p.status === 'pending') return 'Ждёт запуска…';
    if (p.status === 'running') {
      const r = p.current_round || 1;
      const t = p.total_rounds || 3;
      const phase = p.phase === 'consolidation' ? 'Управляющий синтезирует' : `Раунд ${r} из ${t}`;
      return phase;
    }
    if (p.status === 'aborted') return 'Прервана';
    if (p.status === 'done') {
      if (p.decision === 'accept') return 'Принято owner-ом ✓';
      if (p.decision === 'reject') return 'Отклонено owner-ом';
      if (p.decision === 'revise') return 'Owner попросил доработать';
      return 'Завершена — жду твоего решения';
    }
    return p.status;
  }

  function renderPlanningBanner(planning) {
    const el = document.getElementById('planning-banner');
    if (!el) return;
    if (!planning) {
      el.hidden = true;
      el.innerHTML = '';
      return;
    }
    el.hidden = false;
    el.className = 'planning-banner';
    if (planning.status === 'done') el.classList.add('done');
    if (planning.status === 'aborted') el.classList.add('aborted');

    const topic = (planning.topic || planning.owner_request || '').slice(0, 80);
    const status = _humanPlanningStatus(planning);
    const idShort = (planning.id || '').slice(0, 6);
    const profile = planning.model_profile || 'base';
    const profileBadge = profile === 'deep'
      ? '<span class="planning-banner-profile deep" title="Opus на синтезе и пересборке">🧠 Opus</span>'
      : '';

    let actionsHtml = '';
    if (planning.status === 'running' || planning.status === 'pending') {
      actionsHtml = `<button data-action="stop" data-id="${planning.id}">⛔ Остановить</button>`;
    } else if (planning.status === 'done' && !planning.decision) {
      actionsHtml = `
        <button class="primary" data-action="accept" data-id="${planning.id}">Принять</button>
        <button data-action="revise" data-id="${planning.id}">Доработать</button>
        <button data-action="reject" data-id="${planning.id}">Отклонить</button>
      `;
    }

    el.innerHTML = `
      <div class="planning-banner-info">
        <span>🤔</span>
        <span class="planning-banner-status">${escapeHtml(status)}</span>
        ${profileBadge}
        <span style="color: var(--text-3);">— #${escapeHtml(idShort)} ${escapeHtml(topic)}</span>
      </div>
      <div class="planning-banner-actions">${actionsHtml}</div>
    `;

    // Привязываем клик-обработчики к новым кнопкам.
    el.querySelectorAll('button[data-action]').forEach(b => {
      b.addEventListener('click', () => _onPlanningAction(b.dataset.action, b.dataset.id));
    });
  }

  async function _fetchAndRenderPlanning() {
    if (!currentThreadId) { renderPlanningBanner(null); return; }
    try {
      const r = await fetch(`/api/threads/${encodeURIComponent(currentThreadId)}/planning`);
      if (!r.ok) { renderPlanningBanner(null); return; }
      const data = await r.json();
      renderPlanningBanner(data.planning);
    } catch (_) { /* ignore */ }
  }

  async function _onPlanningAction(action, id) {
    if (!id) return;
    if (action === 'stop') {
      const ok = await (window.customConfirm
        ? window.customConfirm('Остановить активную планёрку?')
        : Promise.resolve(confirm('Остановить активную планёрку?')));
      if (!ok) return;
      await fetch(`/api/planning/${encodeURIComponent(id)}/stop`, {method: 'POST'});
    } else if (action === 'accept' || action === 'reject' || action === 'revise') {
      let comment = null;
      if (action === 'revise' || action === 'reject') {
        const promptTitle = action === 'revise'
          ? 'Что доработать? (необязательно)'
          : 'Причина отклонения? (необязательно)';
        comment = window.customPrompt
          ? await window.customPrompt(promptTitle, { placeholder: 'Опционально…' })
          : prompt(promptTitle);
        if (comment === null) return; // отмена prompt
      }
      const resp = await fetch(`/api/planning/${encodeURIComponent(id)}/decision`, {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({decision: action, comment}),
      });
      if (!resp.ok) {
        const j = await resp.json().catch(() => ({}));
        await (window.customAlert || alert)('Не удалось сохранить решение: ' + (j.причина || j.reason || resp.statusText));
        return;
      }
    }
    await _fetchAndRenderPlanning();
    if (currentThreadId) await loadAndRenderMessages(currentThreadId);
  }

  // Silent refresh thread messages (без spinner и без сброса scroll).
  let _lastRenderedMessageCount = 0;
  async function _silentRefreshMessages() {
    if (!currentThreadId) return;
    try {
      const r = await fetch(`/api/threads/${encodeURIComponent(currentThreadId)}/messages?viewer=owner`);
      if (!r.ok) return;
      const data = await r.json();
      const messages = data.messages || [];
      // Если число сообщений не изменилось — не перерисовываем.
      if (messages.length === _lastRenderedMessageCount) return;
      _lastRenderedMessageCount = messages.length;

      const container = document.querySelector('.chat-messages');
      if (!container) return;

      // Проверяем, был ли пользователь в самом низу — чтобы не дёргать его
      // если он листает старые сообщения.
      const wasAtBottom =
        container.scrollHeight - container.scrollTop - container.clientHeight < 50;

      container.innerHTML = '';
      if (messages.length === 0) {
        container.innerHTML = '<div class="message-placeholder">No messages yet. Start the conversation!</div>';
      } else {
        messages.forEach((msg) => container.appendChild(renderMessage(msg)));
      }
      if (wasAtBottom) container.scrollTop = container.scrollHeight;
    } catch (_) { /* network blip — игнорируем */ }
  }

  function initPlanningBannerPoll() {
    if (_planningPollTimer) clearInterval(_planningPollTimer);
    _fetchAndRenderPlanning();
    _silentRefreshMessages();
    _planningPollTimer = setInterval(() => {
      _fetchAndRenderPlanning();
      _silentRefreshMessages();
    }, 5000);
  }

  // Перерисовка баннера при смене треда — вызывается из selectThread напрямую.

  // ============================================================
  // Create Planning Session (Phase 3b — Этап 1)
  // ============================================================

  function initPlanningCreate() {
    const btn = document.getElementById('btn-planning-create');
    if (!btn) return;

    btn.addEventListener('click', async () => {
      const deptInputs = document.querySelectorAll('#planning-departments input[type="checkbox"]:checked');
      const departments = Array.from(deptInputs).map(i => i.value);
      const roundsSel = document.getElementById('planning-rounds-chat');
      const profileSel = document.getElementById('planning-profile-chat');
      const costSel = document.getElementById('planning-cost-limit-chat');
      const topicInp = document.getElementById('planning-topic');
      const rounds = roundsSel ? parseInt(roundsSel.value, 10) : 3;
      const modelProfile = profileSel ? profileSel.value : 'base';
      const costLimitUsd = costSel ? parseFloat(costSel.value) : 10;
      const topic = topicInp ? topicInp.value.trim() : '';

      if (departments.length === 0) {
        await (window.customAlert || alert)('Выбери хотя бы один отдел для планёрки');
        return;
      }
      if (!topic) {
        await (window.customAlert || alert)('Введи тему планёрки');
        return;
      }

      btn.disabled = true;
      try {
        const resp = await fetch('/api/planning/start', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            departments,
            topic,
            rounds,
            model_profile: modelProfile,
            cost_limit_usd: costLimitUsd,
            owner_request: topic,
          }),
        });
        const data = await resp.json();
        if (!resp.ok || data.статус !== 'ok') {
          const reason = data.причина || data.reason || resp.statusText;
          await (window.customAlert || alert)('Не удалось создать планёрку: ' + reason);
          return;
        }
        // Очищаем форму
        if (topicInp) topicInp.value = '';
        document.querySelectorAll('#planning-departments input[type="checkbox"]').forEach(i => i.checked = false);
        // Новая планёрка = новый thread. Перезагружаем список тредов
        // и переключаемся на свежий, чтобы owner сразу увидел диалог.
        const newThreadId = data?.сессия?.thread_id || data?.session?.thread_id;
        await loadThreads();  // обновит правую панель тредов
        if (newThreadId) {
          selectThread({ id: newThreadId, title: topic });
        }
      } catch (e) {
        console.error('planning start failed', e);
        await (window.customAlert || alert)('Ошибка сети при создании планёрки');
      } finally {
        btn.disabled = false;
      }
    });
  }

  // ============================================================
  // Load Managing Director Tasks (F4)
  // ============================================================

  async function loadManagingDirectorTasks() {
    const container = document.getElementById('tasks-list');
    if (!container) return;

    try {
      const response = await fetch('/api/tasks?assignee=managing-director');
      if (!response.ok) throw new Error('Failed to load tasks');

      const data = await response.json();
      const allTasks = data.задачи || [];
      const tasks = allTasks.filter(t => ['todo', 'wip'].includes(t.status));

      container.innerHTML = '';

      if (tasks.length === 0) {
        container.innerHTML = '<p class="loading" data-i18n="managing_director_tasks.empty">Нет активных задач</p>';
        return;
      }

      tasks.forEach((task) => {
        const taskEl = document.createElement('div');
        taskEl.className = 'task-item';
        taskEl.innerHTML = `
          <div class="task-item-title">${escapeHtml(task.title)}</div>
          <div class="task-item-meta">
            <span class="task-item-badge">${task.status}</span>
            <span>${task.priority || 'P2'}</span>
          </div>
        `;
        taskEl.style.cursor = 'pointer';
        taskEl.addEventListener('click', () => {
          console.log('Task clicked:', task.id);
        });
        container.appendChild(taskEl);
      });
    } catch (error) {
      console.error('Error loading tasks:', error);
      container.innerHTML = '<p class="loading" style="color: var(--red);" data-i18n="managing_director_tasks.error">Не удалось загрузить задачи</p>';
    }
  }

  // ============================================================
  // Responsive Mobile Support
  // ============================================================

  function initMobileSupport() {
    const chatApp = document.querySelector('.chat-app');
    const chatThreads = document.querySelector('.chat-threads');

    if (!chatApp || !chatThreads) return;

    const mediaQuery = window.matchMedia('(max-width: 768px)');

    function handleResize(e) {
      if (e.matches) {
        chatThreads.classList.remove('mobile-visible');
      } else {
        chatThreads.classList.add('mobile-visible');
      }
    }

    mediaQuery.addEventListener('change', handleResize);
    handleResize(mediaQuery);
  }

  // ============================================================
  // Initialize on DOM Ready
  // ============================================================

  document.addEventListener('DOMContentLoaded', function () {
    initTheme();
    initThreadSearch();
    loadThreads();
    initMessageInput();
    initMobileSupport();

    // F4: Load planning departments and managing director tasks
    loadPlanningDepartments();
    loadManagingDirectorTasks();
    initPlanningCreate();
    initPlanningBannerPoll();

    console.log('Chat page initialized');
  });

  // ============================================================
  // Listen for Theme Changes
  // ============================================================

  window.addEventListener('theme-changed', (e) => {
    document.documentElement.setAttribute('data-theme', e.detail.theme);
  });
})();
