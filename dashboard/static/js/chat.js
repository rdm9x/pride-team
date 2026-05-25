/**
 * Chat Page (F1 Phase 3a)
 * Layout: 3-column grid (20% / 50% / 30%) with right column split 30%/70%
 *
 * Features:
 * - Responsive layout (mobile stack)
 * - Dark theme support
 * - Thread selection
 * - Message input
 */

(function () {
  'use strict';

  // ============================================================
  // Theme Initialization
  // ============================================================

  function initTheme() {
    const savedTheme = localStorage.getItem('theme') || 'light';
    document.documentElement.setAttribute('data-theme', savedTheme);
  }

  // ============================================================
  // Thread Selection
  // ============================================================

  function initThreadSelection() {
    const threadItems = document.querySelectorAll('.thread-item');

    threadItems.forEach((item) => {
      item.addEventListener('click', function () {
        // Remove active class from all threads
        threadItems.forEach((t) => t.classList.remove('active'));
        // Add active class to clicked thread
        this.classList.add('active');

        // TODO: Load messages for this thread
        console.log('Thread selected:', this.textContent);
      });
    });
  }

  // ============================================================
  // Message Input Handler
  // ============================================================

  function initMessageInput() {
    const input = document.querySelector('.chat-input-area input');
    const sendButton = document.querySelector('.chat-input-area button');

    if (!input || !sendButton) return;

    function sendMessage() {
      const text = input.value.trim();
      if (!text) return;

      // TODO: Send message to backend
      console.log('Message to send:', text);

      // Clear input
      input.value = '';
      input.focus();
    }

    // Send on button click
    sendButton.addEventListener('click', sendMessage);

    // Send on Enter (Shift+Enter for new line)
    input.addEventListener('keydown', (e) => {
      if (e.key === 'Enter' && !e.shiftKey) {
        e.preventDefault();
        sendMessage();
      }
    });
  }

  // ============================================================
  // Load Departments for Planning (F4)
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
      // Filter only todo and wip tasks
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
          // TODO: Open task modal in Phase 3b
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
  // Utility: Escape HTML
  // ============================================================

  function escapeHtml(text) {
    const div = document.createElement('div');
    div.textContent = text;
    return div.innerHTML;
  }

  // ============================================================
  // Responsive Mobile Support
  // ============================================================

  function initMobileSupport() {
    const chatApp = document.querySelector('.chat-app');
    const chatThreads = document.querySelector('.chat-threads');

    if (!chatApp || !chatThreads) return;

    // Check viewport
    const mediaQuery = window.matchMedia('(max-width: 768px)');

    function handleResize(e) {
      if (e.matches) {
        // Mobile: hide threads by default
        chatThreads.classList.remove('mobile-visible');
      } else {
        // Desktop: show threads
        chatThreads.classList.add('mobile-visible');
      }
    }

    mediaQuery.addEventListener('change', handleResize);
    handleResize(mediaQuery); // Initial check
  }

  // ============================================================
  // Initialize on DOM Ready
  // ============================================================

  document.addEventListener('DOMContentLoaded', function () {
    initTheme();
    initThreadSelection();
    initMessageInput();
    initMobileSupport();

    // F4: Load planning departments and managing director tasks
    loadPlanningDepartments();
    loadManagingDirectorTasks();

    console.log('Chat page initialized');
  });

  // ============================================================
  // Listen for Theme Changes (from main app)
  // ============================================================

  window.addEventListener('theme-changed', (e) => {
    document.documentElement.setAttribute('data-theme', e.detail.theme);
  });
})();
