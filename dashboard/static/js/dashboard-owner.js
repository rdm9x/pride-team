/**
 * Owner Dashboard (F3 — ADR-013)
 *
 * Загрузка и рендер проектов с progress, action items и артефактами.
 * Интеграция с backend API: GET /api/projects, POST /api/projects/<slug>/accept-task и т.д.
 */

(function () {
  "use strict";

  const REFRESH_MS = 5000; // Периодическое обновление списка проектов
  const $ = (sel) => document.querySelector(sel);
  const $$ = (sel) => Array.from(document.querySelectorAll(sel));

  // ===================== Utility Functions =====================

  function escapeHtml(text) {
    if (!text) return '';
    const map = {
      '&': '&amp;',
      '<': '&lt;',
      '>': '&gt;',
      '"': '&quot;',
      "'": '&#039;'
    };
    return text.replace(/[&<>"']/g, (m) => map[m]);
  }

  function getMimeTypeIcon(mimeType) {
    if (!mimeType) return '📄';
    if (mimeType.includes('image')) return '🎨';
    if (mimeType.includes('pdf')) return '📊';
    if (mimeType.includes('text/html') || mimeType.includes('text/css')) return '💻';
    if (mimeType.includes('video')) return '🎬';
    if (mimeType.includes('audio')) return '🔊';
    return '📄';
  }

  function getDateFromTimestamp(timestamp) {
    if (!timestamp) return '';
    const date = new Date(timestamp * 1000);
    const today = new Date();
    const yesterday = new Date(today);
    yesterday.setDate(yesterday.getDate() - 1);

    if (date.toDateString() === today.toDateString()) {
      return 'сегодня ' + date.toLocaleTimeString('ru-RU', { hour: '2-digit', minute: '2-digit' });
    }
    if (date.toDateString() === yesterday.toDateString()) {
      return 'вчера';
    }
    return date.toLocaleDateString('ru-RU', { month: 'short', day: 'numeric', year: date.getFullYear() !== today.getFullYear() ? 'numeric' : undefined });
  }

  // ===================== Main Functions =====================

  async function loadProjects(includeArchived = false) {
    try {
      const url = `/api/projects?include_archived=${includeArchived}&include_devboard=true`;
      const resp = await fetch(url);
      if (!resp.ok) throw new Error(`HTTP ${resp.status}`);

      const data = await resp.json();
      if (data.status !== 'ok') throw new Error(data.error || 'API error');

      renderProjects(data.projects, data.devboard_tasks);
    } catch (err) {
      console.error('Failed to load projects:', err);
      const container = $('#projects-container');
      container.innerHTML = `<div class="error-message" data-i18n="error.load_projects">Ошибка при загрузке проектов: ${escapeHtml(err.message)}</div>`;
    }
  }

  function renderProjects(projects, devboardTasks) {
    const container = $('#projects-container');
    container.innerHTML = '';

    // Основные проекты
    if (projects && projects.length > 0) {
      projects.forEach((project) => {
        const card = renderProjectCard(project);
        container.appendChild(card);
      });
    } else {
      container.innerHTML = '<div class="empty-state"><span data-i18n="dashboard.empty">Проекты не найдены</span></div>';
    }

    // Devboard tasks (if present)
    if (devboardTasks) {
      const devboardCard = renderProjectCard(devboardTasks);
      container.appendChild(devboardCard);
    }
  }

  function renderProjectCard(project) {
    const card = document.createElement('div');
    card.className = 'project-card';
    card.dataset.projectSlug = project.project_slug;

    // Progress stats
    const total = project.progress.total || 1;
    const percentage = Math.round(project.progress.percentage || 0);
    const isDone = percentage === 100;

    // Build action items HTML
    const actionItemsHtml = renderActionItems(project.action_items, project.project_slug);

    // Build artifacts section
    const artifactsHtml = renderArtifactsSection(project.artifacts);

    // Format last update time
    const lastUpdateText = getDateFromTimestamp(project.last_updated_at);

    card.innerHTML = `
      <div class="project-card-header">
        <div class="project-title-section">
          <h2 class="project-title">📦 ${escapeHtml(project.title)}</h2>
          <div class="project-status-badge ${project.status === 'completed' ? 'status-completed' : ''}">
            ${project.status === 'completed' ? '✅ ЗАВЕРШЕНО' : ''}
          </div>
        </div>
        ${lastUpdateText ? `<span class="project-timestamp" title="${new Date(project.last_updated_at * 1000).toLocaleString('ru-RU')}">${escapeHtml(lastUpdateText)}</span>` : ''}
      </div>

      <div class="progress-section">
        <div class="progress-stats">
          <span class="stat-badge">${project.progress.done} готово</span>
          <span class="stat-badge">${project.progress.in_progress} в работе</span>
          <span class="stat-badge">${project.progress.todo + project.progress.blocked} ждёт</span>
        </div>
        <div class="progress-bar">
          <div class="progress-fill" style="width: ${percentage}%"></div>
          <span class="progress-text">${percentage}%</span>
        </div>
      </div>

      ${actionItemsHtml}
      ${artifactsHtml}

      <div class="project-footer">
        <button class="btn-project-history" data-project-slug="${escapeHtml(project.project_slug)}"
                title="Показать историю проекта" aria-label="История">
          💬 История
        </button>
        <button class="btn-project-refresh" data-project-slug="${escapeHtml(project.project_slug)}"
                title="Обновить статусы" aria-label="Обновить">
          🔄 Обновить
        </button>
        ${project.workspace_path ? `
          <button class="btn-project-open-folder" data-path="${escapeHtml(project.workspace_path)}"
                  title="Открыть папку проекта" aria-label="Открыть папку">
            📂 Открыть
          </button>
        ` : ''}
      </div>
    `;

    // Attach event listeners
    card.querySelector('.btn-project-history')?.addEventListener('click', (e) => {
      e.preventDefault();
      showProjectHistory(project.project_slug);
    });

    card.querySelector('.btn-project-refresh')?.addEventListener('click', (e) => {
      e.preventDefault();
      loadProjects();
    });

    card.querySelector('.btn-project-open-folder')?.addEventListener('click', async (e) => {
      e.preventDefault();
      const path = e.currentTarget.dataset.path;
      try {
        const resp = await fetch('/api/open-folder', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ path })
        });
        if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
      } catch (err) {
        console.error('Failed to open folder:', err);
        alert('Не удалось открыть папку');
      }
    });

    // Attach action button listeners
    card.querySelectorAll('.btn-accept').forEach((btn) => {
      btn.addEventListener('click', (e) => {
        e.preventDefault();
        const taskId = btn.dataset.taskId;
        onAcceptTask(project.project_slug, taskId, btn);
      });
    });

    card.querySelectorAll('.btn-start').forEach((btn) => {
      btn.addEventListener('click', (e) => {
        e.preventDefault();
        const taskId = btn.dataset.taskId;
        const role = btn.dataset.role;
        onStartTask(project.project_slug, taskId, role, btn);
      });
    });

    card.querySelectorAll('.btn-unblock').forEach((btn) => {
      btn.addEventListener('click', (e) => {
        e.preventDefault();
        const taskId = btn.dataset.taskId;
        onUnblockTask(project.project_slug, taskId, btn);
      });
    });

    return card;
  }

  function renderActionItems(items, projectSlug) {
    let html = '';

    if (items.review && items.review.length > 0) {
      html += `
        <div class="action-section review-section">
          <h3 class="action-section-title">📋 Review (${items.review.length})</h3>
          <div class="action-items">
            ${items.review.map(task => `
              <div class="action-item">
                <div class="action-item-content">
                  <span class="task-id">#${escapeHtml(task.id.slice(0, 8))}</span>
                  <span class="task-title">${escapeHtml(task.title)}</span>
                  ${task.department_id ? `<span class="task-dept">${escapeHtml(task.department_id)}</span>` : ''}
                </div>
                <button class="btn-accept btn-small" data-task-id="${escapeHtml(task.id)}"
                        title="Принять работу" aria-label="Принять">
                  ✓ Принять
                </button>
              </div>
            `).join('')}
          </div>
        </div>
      `;
    }

    if (items.waiting_to_start && items.waiting_to_start.length > 0) {
      html += `
        <div class="action-section waiting-section">
          <h3 class="action-section-title">⏸ Ждёт запуска (${items.waiting_to_start.length})</h3>
          <div class="action-items">
            ${items.waiting_to_start.map(task => `
              <div class="action-item">
                <div class="action-item-content">
                  <span class="task-id">#${escapeHtml(task.id.slice(0, 8))}</span>
                  <span class="task-title">${escapeHtml(task.title)}</span>
                  <span class="task-role">${escapeHtml(task.assignee || 'unknown')}</span>
                </div>
                <button class="btn-start btn-small" data-task-id="${escapeHtml(task.id)}"
                        data-role="${escapeHtml(task.assignee)}"
                        title="Запустить задачу" aria-label="Запустить">
                  ▶ Запустить
                </button>
              </div>
            `).join('')}
          </div>
        </div>
      `;
    }

    if (items.blocked && items.blocked.length > 0) {
      html += `
        <div class="action-section blocked-section">
          <h3 class="action-section-title">🚨 Blocked (${items.blocked.length})</h3>
          <div class="action-items">
            ${items.blocked.map(task => `
              <div class="action-item blocked-item">
                <div class="action-item-content">
                  <span class="task-id">#${escapeHtml(task.id.slice(0, 8))}</span>
                  <span class="task-title">${escapeHtml(task.title)}</span>
                  ${task.blocking_reason ? `<span class="blocking-reason">${escapeHtml(task.blocking_reason)}</span>` : ''}
                </div>
                <button class="btn-unblock btn-small" data-task-id="${escapeHtml(task.id)}"
                        title="Разблокировать" aria-label="Разблокировать">
                  🔓 Разблокировать
                </button>
              </div>
            `).join('')}
          </div>
        </div>
      `;
    }

    return html;
  }

  function renderArtifactsSection(artifacts) {
    if (!artifacts || artifacts.length === 0) return '';

    const html = `
      <div class="artifacts-section">
        <h3 class="artifacts-title">🔗 Файлы (${artifacts.length})</h3>
        <div class="artifacts-list">
          ${artifacts.map(artifact => {
            const icon = getMimeTypeIcon(artifact.mime_type);
            const fileName = artifact.file_path.split('/').pop();
            return `
              <div class="artifact-chip" title="${escapeHtml(artifact.file_path)}">
                <span class="artifact-icon">${icon}</span>
                <span class="artifact-name">${escapeHtml(fileName)}</span>
              </div>
            `;
          }).join('')}
        </div>
      </div>
    `;
    return html;
  }

  async function onAcceptTask(projectSlug, taskId, btnElement) {
    const comment = prompt('Комментарий (опционально):');
    if (comment === null) return; // cancelled

    try {
      btnElement.disabled = true;
      btnElement.textContent = '⏳…';

      const resp = await fetch(`/api/projects/${encodeURIComponent(projectSlug)}/accept-task`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ task_id: taskId, comment: comment || '' })
      });

      if (!resp.ok) {
        const error = await resp.json();
        throw new Error(error.error || `HTTP ${resp.status}`);
      }

      // Success — refresh projects
      await loadProjects();
    } catch (err) {
      console.error('Failed to accept task:', err);
      alert(`Ошибка: ${err.message}`);
      btnElement.disabled = false;
      btnElement.textContent = '✓ Принять';
    }
  }

  async function onStartTask(projectSlug, taskId, role, btnElement) {
    try {
      btnElement.disabled = true;
      btnElement.textContent = '⏳…';

      const resp = await fetch(`/api/projects/${encodeURIComponent(projectSlug)}/start-task`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ task_id: taskId, role: role })
      });

      if (!resp.ok) {
        const error = await resp.json();
        throw new Error(error.error || `HTTP ${resp.status}`);
      }

      // Success — refresh projects
      await loadProjects();
    } catch (err) {
      console.error('Failed to start task:', err);
      alert(`Ошибка: ${err.message}`);
      btnElement.disabled = false;
      btnElement.textContent = `▶ Запустить`;
    }
  }

  async function onUnblockTask(projectSlug, taskId, btnElement) {
    const reason = prompt('Причина разблокировки:');
    if (reason === null) return; // cancelled

    try {
      btnElement.disabled = true;
      btnElement.textContent = '⏳…';

      const resp = await fetch(`/api/projects/${encodeURIComponent(projectSlug)}/unblock`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ task_id: taskId, reason: reason || '' })
      });

      if (!resp.ok) {
        const error = await resp.json();
        throw new Error(error.error || `HTTP ${resp.status}`);
      }

      // Success — refresh projects
      await loadProjects();
    } catch (err) {
      console.error('Failed to unblock task:', err);
      alert(`Ошибка: ${err.message}`);
      btnElement.disabled = false;
      btnElement.textContent = '🔓 Разблокировать';
    }
  }

  async function showProjectHistory(projectSlug) {
    const modal = $('#modal-project-history');
    const body = $('#modal-project-history-body');
    const title = $('#modal-project-history-title');

    try {
      title.textContent = `История проекта: ${projectSlug}`;
      body.innerHTML = '<div class="loading-spinner">Загрузка истории…</div>';
      modal.hidden = false;

      const resp = await fetch(`/api/projects/${encodeURIComponent(projectSlug)}`);
      if (!resp.ok) throw new Error(`HTTP ${resp.status}`);

      const data = await resp.json();
      if (data.status !== 'ok') throw new Error(data.error || 'API error');

      // Render project history (for now, simple chat thread)
      const chatThread = data.chat_thread;
      if (chatThread && chatThread.messages) {
        const messagesHtml = chatThread.messages.map(msg => `
          <div class="chat-message">
            <div class="message-author">${escapeHtml(msg.author)}</div>
            <div class="message-text">${escapeHtml(msg.text)}</div>
            <div class="message-time">${getDateFromTimestamp(msg.created_at)}</div>
          </div>
        `).join('');
        body.innerHTML = `
          <div class="project-history-content">
            <h3>${escapeHtml(chatThread.title)}</h3>
            <div class="chat-messages">${messagesHtml}</div>
            ${chatThread.decision_summary ? `<div class="decision-summary">
              <strong>Решение:</strong> ${escapeHtml(chatThread.decision_summary)}
            </div>` : ''}
          </div>
        `;
      } else {
        body.innerHTML = '<p>История проекта не найдена</p>';
      }
    } catch (err) {
      console.error('Failed to load project history:', err);
      body.innerHTML = `<div class="error-message">Ошибка: ${escapeHtml(err.message)}</div>`;
    }
  }

  // ===================== Initialization =====================

  function init() {
    // Load projects on initial page load
    loadProjects();

    // Set up refresh interval
    setInterval(() => {
      loadProjects();
    }, REFRESH_MS);

    // Handle view switching
    $$('[data-view]').forEach((btn) => {
      btn.addEventListener('click', (e) => {
        const view = e.currentTarget.dataset.view;
        showView(view);
      });
    });

    // Close modals
    $$('[data-close]').forEach((btn) => {
      btn.addEventListener('click', (e) => {
        const modalId = btn.dataset.close;
        const modal = $(`#${modalId}`);
        if (modal) modal.hidden = true;
      });
    });
  }

  function showView(view) {
    // Hide all views
    $$('[data-view-panel], .view').forEach(v => v.hidden = true);

    // Show selected view
    const viewEl = document.querySelector(`[data-view="${view}"]`);
    if (viewEl) viewEl.hidden = false;

    // Update nav buttons
    $$('[data-view]').forEach(btn => {
      btn.classList.toggle('active', btn.dataset.view === view);
    });
  }

  // Expose to global scope for external calls
  window.ownerDashboard = {
    loadProjects,
    init
  };

  // Initialize when DOM is ready
  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', init);
  } else {
    init();
  }
})();
