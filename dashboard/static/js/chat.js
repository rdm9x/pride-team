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
    const savedTheme = localStorage.getItem('theme') || 'light';
    document.documentElement.setAttribute('data-theme', savedTheme);
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

      // Auto-select first active thread
      if (allThreads.active.length > 0) {
        selectThread({ id: allThreads.active[0].id, title: allThreads.active[0].title });
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
            </div>
          </div>
        `;
      })
      .join('');

    // Attach click handlers
    container.querySelectorAll('.thread-item').forEach((item) => {
      item.addEventListener('click', () => {
        selectThread({
          id: item.dataset.threadId,
          title: item.dataset.threadTitle,
        });
      });
    });
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
            </div>
          </div>
        `;
      })
      .join('');

    // Attach click handlers
    container.querySelectorAll('.archive-thread-item').forEach((item) => {
      item.addEventListener('click', () => {
        selectThread({
          id: item.dataset.threadId,
          title: item.dataset.threadTitle,
        });
      });
    });
  }

  // ============================================================
  // F2: Thread Selection
  // ============================================================

  function selectThread(threadData) {
    if (!threadData || !threadData.id) return;

    currentThreadId = threadData.id;

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
            author: 'user',
            text: text,
          }),
        });

        if (!response.ok) throw new Error('Failed to send message');

        input.value = '';
        await loadAndRenderMessages(currentThreadId);
        input.focus();
      } catch (error) {
        console.error('Error sending message:', error);
        alert('Failed to send message: ' + error.message);
      } finally {
        input.disabled = false;
        sendButton.disabled = false;
      }
    }

    async function startSession() {
      if (!currentThreadId) {
        alert('Please select a thread first');
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
        alert('Team session started');
      } catch (error) {
        console.error('Error starting session:', error);
        alert('Failed to start session: ' + error.message);
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

    console.log('Chat page initialized');
  });

  // ============================================================
  // Listen for Theme Changes
  // ============================================================

  window.addEventListener('theme-changed', (e) => {
    document.documentElement.setAttribute('data-theme', e.detail.theme);
  });
})();
