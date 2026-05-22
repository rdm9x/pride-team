/* =========================================================================
 * tour.js — onboarding-тур для pride-team.
 *
 * Без зависимостей. Чистый vanilla JS.
 * Создаёт overlay с подсветкой целевого элемента + popover-tooltip рядом.
 *
 * Использование:
 *   const tour = new Tour([
 *     { selector: null,       title: '…', body: '…', position: 'center' },
 *     { selector: '#btn',     title: '…', body: '…', position: 'bottom' },
 *     ...
 *   ], { i18n: t, onComplete: fn, onSkip: fn });
 *   tour.start();
 *
 * Автоматически:
 *   - не запускается повторно если localStorage.onboarding_completed_at стоит
 *   - сохраняет timestamp при завершении
 *   - Esc или Skip — пропускает весь тур
 * ========================================================================= */
(function (global) {
  'use strict';

  // --- i18n fallback ------------------------------------------------------
  // Берём из window.t если объявлен, иначе возвращаем fallback-текст.
  // Это позволяет работать и до того, как i18n-loader будет готов.
  function tr(key, fallback) {
    if (typeof global.t === 'function') {
      const v = global.t(key);
      if (v && v !== key) return v;
    }
    return fallback;
  }

  // --- Локализованные шаги тура -------------------------------------------
  // Селекторы выбраны под реальный DOM kanban.html. Если элемент не найден —
  // шаг показывается по центру (graceful degradation).
  const DEFAULT_STEPS = [
    {
      selector: null,
      i18nTitle: 'onboarding.tour.step1.title',
      i18nBody:  'onboarding.tour.step1.body',
      fallbackTitle: 'Hi! Meet your AI team',
      fallbackBody:  'Seven roles — team-lead, backend, frontend, QA, architect, DevOps, tech-writer — collaborate on tasks as a single team. A quick minute to show you how it works.',
      position: 'center',
    },
    {
      selector: '#btn-new-task',
      i18nTitle: 'onboarding.tour.step2.title',
      i18nBody:  'onboarding.tour.step2.body',
      fallbackTitle: 'Create tasks here',
      fallbackBody:  'Click «+ New task», describe what needs doing. The team-lead will break it down and delegate.',
      position: 'bottom',
    },
    {
      selector: '.team-roles',
      fallbackSelector: 'aside.sidebar',
      i18nTitle: 'onboarding.tour.step3.title',
      i18nBody:  'onboarding.tour.step3.body',
      fallbackTitle: 'Roles live in roles/*.md',
      fallbackBody:  'Each role has its own system prompt under roles/. Want to tweak behaviour? Edit that role\'s markdown file.',
      position: 'right',
    },
    {
      selector: '#btn-start',
      i18nTitle: 'onboarding.tour.step4.title',
      i18nBody:  'onboarding.tour.step4.body',
      fallbackTitle: 'Launch the team-lead — they\'ll dispatch work',
      fallbackBody:  '«▶ Start team» — the team-lead reads the board, picks the next task and starts delegating. «⏹ Stop» ends the session.',
      position: 'bottom',
    },
    {
      selector: '.column[data-status="wip"]',
      i18nTitle: 'onboarding.tour.step5.title',
      i18nBody:  'onboarding.tour.step5.body',
      fallbackTitle: 'The board updates in real time',
      fallbackBody:  'The «In progress» column lights up as soon as the team picks up work. No refresh needed. You\'re set!',
      position: 'left',
    },
  ];

  const STORAGE_KEY = 'onboarding_completed_at';
  const POPOVER_GAP = 14;    // px между подсвеченным элементом и tooltip
  const VIEWPORT_PAD = 12;   // px от края viewport

  // ========================================================================
  // class Tour
  // ========================================================================
  class Tour {
    constructor(steps, options = {}) {
      this.steps = Array.isArray(steps) && steps.length ? steps : DEFAULT_STEPS;
      this.opts = {
        onComplete: options.onComplete || null,
        onSkip:     options.onSkip     || null,
        storageKey: options.storageKey || STORAGE_KEY,
      };
      this.index = 0;
      this.root = null;        // контейнер тура (.tour-root)
      this.parts = [];         // 4 затемнённых div'а
      this.hole = null;        // подсвеченная рамка
      this.popover = null;     // tooltip
      this.lastFocus = null;   // куда вернуть фокус после закрытия
      this._onKey = this._onKey.bind(this);
      this._onResize = this._onResize.bind(this);
      this._destroyed = false;
    }

    // --- public API -------------------------------------------------------
    start() {
      if (this._destroyed) return;
      this.lastFocus = document.activeElement;
      this._build();
      this._show(0);
      document.addEventListener('keydown', this._onKey);
      window.addEventListener('resize', this._onResize);
      window.addEventListener('scroll', this._onResize, true);
    }

    next() {
      if (this.index >= this.steps.length - 1) {
        this.complete();
      } else {
        this._show(this.index + 1);
      }
    }

    prev() {
      if (this.index > 0) this._show(this.index - 1);
    }

    skip() {
      if (typeof this.opts.onSkip === 'function') {
        try { this.opts.onSkip(this.index); } catch (e) { /* ignore */ }
      }
      this._teardown();
    }

    complete() {
      try {
        localStorage.setItem(this.opts.storageKey, String(Date.now()));
      } catch (e) { /* localStorage may be blocked */ }
      if (typeof this.opts.onComplete === 'function') {
        try { this.opts.onComplete(); } catch (e) { /* ignore */ }
      }
      this._teardown();
    }

    // --- DOM build --------------------------------------------------------
    _build() {
      const root = document.createElement('div');
      root.className = 'tour-root';
      root.setAttribute('role', 'dialog');
      root.setAttribute('aria-modal', 'true');
      root.setAttribute('aria-labelledby', 'tour-title');

      // 4 затемняющих квадрата (top/right/bottom/left от дырки)
      for (let i = 0; i < 4; i++) {
        const part = document.createElement('div');
        part.className = 'tour-mask-part';
        root.appendChild(part);
        this.parts.push(part);
      }

      const hole = document.createElement('div');
      hole.className = 'tour-hole';
      hole.setAttribute('aria-hidden', 'true');
      root.appendChild(hole);
      this.hole = hole;

      const pop = document.createElement('div');
      pop.className = 'tour-popover';
      pop.setAttribute('role', 'document');
      pop.innerHTML = `
        <div class="tour-popover-arrow" aria-hidden="true"></div>
        <header class="tour-popover-header">
          <h3 class="tour-popover-title" id="tour-title"></h3>
          <span class="tour-popover-progress" aria-live="polite"></span>
        </header>
        <div class="tour-popover-body"></div>
        <div class="tour-popover-actions">
          <button type="button" class="tour-skip" data-i18n="onboarding.tour.skip">Skip</button>
          <div class="tour-popover-nav">
            <button type="button" class="tour-prev" data-i18n="onboarding.tour.prev">Back</button>
            <button type="button" class="tour-next primary" data-i18n="onboarding.tour.next">Next</button>
          </div>
        </div>
      `;
      root.appendChild(pop);
      this.popover = pop;

      // Локализация кнопок (если t() готов — переопределит fallback)
      pop.querySelector('.tour-skip').textContent = tr('onboarding.tour.skip', 'Skip');
      pop.querySelector('.tour-prev').textContent = tr('onboarding.tour.prev', 'Back');
      this._nextBtn = pop.querySelector('.tour-next');

      // Обработчики кнопок
      pop.querySelector('.tour-skip').addEventListener('click', () => this.skip());
      pop.querySelector('.tour-prev').addEventListener('click', () => this.prev());
      this._nextBtn.addEventListener('click', () => this.next());

      document.body.appendChild(root);
      this.root = root;
    }

    // --- Показ шага ------------------------------------------------------
    _show(idx) {
      this.index = idx;
      const step = this.steps[idx];
      if (!step) { this.complete(); return; }

      // Находим целевой элемент. Если не нашли — fallback на центр.
      let target = null;
      if (step.selector) {
        target = document.querySelector(step.selector);
        if (!target && step.fallbackSelector) {
          target = document.querySelector(step.fallbackSelector);
        }
      }

      // Заполняем содержимое
      this.popover.querySelector('.tour-popover-title').textContent =
        tr(step.i18nTitle, step.fallbackTitle);
      this.popover.querySelector('.tour-popover-body').textContent =
        tr(step.i18nBody, step.fallbackBody);
      this.popover.querySelector('.tour-popover-progress').textContent =
        `${idx + 1} / ${this.steps.length}`;

      // Кнопки «Назад»/«Далее»
      this.popover.querySelector('.tour-prev').disabled = (idx === 0);
      const isLast = (idx === this.steps.length - 1);
      this._nextBtn.textContent = isLast
        ? tr('onboarding.tour.finish', 'Done')
        : tr('onboarding.tour.next', 'Next');

      // Если есть селектор — прокручиваем элемент в viewport
      if (target) {
        try {
          target.scrollIntoView({ block: 'center', inline: 'center', behavior: 'smooth' });
        } catch (e) { /* old browsers */ }
      }

      // Даём браузеру отрисовать scroll, потом позиционируем
      requestAnimationFrame(() => this._position(step, target));

      // Делаем popover видимым
      this.popover.classList.add('is-visible');

      // Фокус на «Далее» (для keyboard nav)
      try { this._nextBtn.focus({ preventScroll: true }); } catch (e) { this._nextBtn.focus(); }
    }

    // --- Позиционирование маски + popover --------------------------------
    _position(step, target) {
      const W = window.innerWidth;
      const H = window.innerHeight;
      let rect = null;

      if (target) {
        rect = target.getBoundingClientRect();
        // Если элемент за viewport — считаем что цели нет (центрируем)
        if (rect.bottom < 0 || rect.top > H || rect.right < 0 || rect.left > W ||
            rect.width === 0 || rect.height === 0) {
          rect = null;
        }
      }

      const centerMode = !rect || step.position === 'center';

      if (centerMode) {
        // Прячем «дырку» и подсвечиваем всё затемнением: 1 большой part сверху.
        this.hole.style.opacity = '0';
        this._setParts(0, 0, 0, 0, W, H);
        this.popover.classList.add('is-center');
        this.popover.removeAttribute('data-pos');
        this.popover.style.top = '';
        this.popover.style.left = '';
        return;
      }

      // padding вокруг подсвеченного элемента
      const pad = 6;
      const hx = Math.max(0, rect.left - pad);
      const hy = Math.max(0, rect.top - pad);
      const hw = Math.min(W - hx, rect.width + pad * 2);
      const hh = Math.min(H - hy, rect.height + pad * 2);

      // Подсвеченная рамка
      this.hole.style.opacity = '1';
      this.hole.style.top  = hy + 'px';
      this.hole.style.left = hx + 'px';
      this.hole.style.width  = hw + 'px';
      this.hole.style.height = hh + 'px';

      // Затемнение через 4 части (выше / ниже / слева / справа от дырки)
      this._setParts(hx, hy, hw, hh, W, H);

      // Tooltip позиционирование
      this.popover.classList.remove('is-center');
      const pos = this._pickPosition(step.position, hx, hy, hw, hh, W, H);
      this.popover.setAttribute('data-pos', pos);

      const popRect = this.popover.getBoundingClientRect();
      // popover может быть ещё не отрисован — используем известную ширину 360px
      const pw = popRect.width  || 360;
      const ph = popRect.height || 180;

      let px, py;
      switch (pos) {
        case 'bottom':
          px = hx + hw / 2 - pw / 2;
          py = hy + hh + POPOVER_GAP;
          break;
        case 'top':
          px = hx + hw / 2 - pw / 2;
          py = hy - ph - POPOVER_GAP;
          break;
        case 'right':
          px = hx + hw + POPOVER_GAP;
          py = hy + hh / 2 - ph / 2;
          break;
        case 'left':
        default:
          px = hx - pw - POPOVER_GAP;
          py = hy + hh / 2 - ph / 2;
          break;
      }

      // Зажимаем в viewport
      px = Math.max(VIEWPORT_PAD, Math.min(px, W - pw - VIEWPORT_PAD));
      py = Math.max(VIEWPORT_PAD, Math.min(py, H - ph - VIEWPORT_PAD));

      this.popover.style.top = py + 'px';
      this.popover.style.left = px + 'px';
    }

    // Выбор стороны: если запрошенная не вмещается — переключаемся на противоположную
    _pickPosition(want, hx, hy, hw, hh, W, H) {
      const pw = 360, ph = 200;
      const fits = {
        bottom: (hy + hh + POPOVER_GAP + ph + VIEWPORT_PAD) <= H,
        top:    (hy - POPOVER_GAP - ph - VIEWPORT_PAD) >= 0,
        right:  (hx + hw + POPOVER_GAP + pw + VIEWPORT_PAD) <= W,
        left:   (hx - POPOVER_GAP - pw - VIEWPORT_PAD) >= 0,
      };
      if (want && fits[want]) return want;
      // приоритет fallback'ов
      for (const p of ['bottom', 'top', 'right', 'left']) {
        if (fits[p]) return p;
      }
      return 'bottom';
    }

    // Размещение 4 затемняющих частей вокруг дырки (hx,hy,hw,hh)
    _setParts(hx, hy, hw, hh, W, H) {
      const [top, right, bottom, left] = this.parts;
      // top: 0,0 → W × hy
      top.style.top = '0';
      top.style.left = '0';
      top.style.width = W + 'px';
      top.style.height = hy + 'px';
      // bottom: 0, hy+hh → W × (H - hy - hh)
      bottom.style.top = (hy + hh) + 'px';
      bottom.style.left = '0';
      bottom.style.width = W + 'px';
      bottom.style.height = Math.max(0, H - hy - hh) + 'px';
      // left: 0, hy → hx × hh
      left.style.top = hy + 'px';
      left.style.left = '0';
      left.style.width = hx + 'px';
      left.style.height = hh + 'px';
      // right: hx+hw, hy → (W - hx - hw) × hh
      right.style.top = hy + 'px';
      right.style.left = (hx + hw) + 'px';
      right.style.width = Math.max(0, W - hx - hw) + 'px';
      right.style.height = hh + 'px';
    }

    // --- Events ----------------------------------------------------------
    _onKey(e) {
      if (e.key === 'Escape') {
        e.preventDefault();
        this.skip();
        return;
      }
      if (e.key === 'ArrowRight' || e.key === 'Enter') {
        e.preventDefault();
        this.next();
        return;
      }
      if (e.key === 'ArrowLeft') {
        e.preventDefault();
        this.prev();
        return;
      }
      // Trap focus: Tab по кругу внутри popover
      if (e.key === 'Tab' && this.popover) {
        const focusable = this.popover.querySelectorAll(
          'button:not([disabled]), [href], input, select, textarea, [tabindex]:not([tabindex="-1"])'
        );
        if (!focusable.length) return;
        const first = focusable[0];
        const last  = focusable[focusable.length - 1];
        if (e.shiftKey && document.activeElement === first) {
          e.preventDefault(); last.focus();
        } else if (!e.shiftKey && document.activeElement === last) {
          e.preventDefault(); first.focus();
        }
      }
    }

    _onResize() {
      if (this._destroyed || !this.steps[this.index]) return;
      const step = this.steps[this.index];
      let target = step.selector ? document.querySelector(step.selector) : null;
      if (!target && step.fallbackSelector) {
        target = document.querySelector(step.fallbackSelector);
      }
      this._position(step, target);
    }

    // --- Teardown --------------------------------------------------------
    _teardown() {
      if (this._destroyed) return;
      this._destroyed = true;
      document.removeEventListener('keydown', this._onKey);
      window.removeEventListener('resize', this._onResize);
      window.removeEventListener('scroll', this._onResize, true);
      if (this.root && this.root.parentNode) {
        this.root.parentNode.removeChild(this.root);
      }
      this.root = null;
      this.parts = [];
      this.hole = null;
      this.popover = null;
      // Возвращаем фокус туда, где был
      if (this.lastFocus && typeof this.lastFocus.focus === 'function') {
        try { this.lastFocus.focus(); } catch (e) { /* ignore */ }
      }
    }
  }

  // ========================================================================
  // Автозапуск при первом открытии
  // ========================================================================
  function shouldAutoStart() {
    try {
      return !localStorage.getItem(STORAGE_KEY);
    } catch (e) {
      return false; // localStorage недоступен — не показываем
    }
  }

  function autoStart() {
    if (!shouldAutoStart()) return;
    // Небольшая задержка чтобы дать app.js отрисовать UI.
    // Если i18n ещё не готов — повторяем попытку до 3 раз с шагом 200мс.
    function tryStart(attemptsLeft) {
      if (typeof global.t === 'function' || attemptsLeft <= 0) {
        const tour = new Tour(DEFAULT_STEPS);
        tour.start();
        global.__prideTour = tour; // удобно дебажить из консоли
      } else {
        setTimeout(() => tryStart(attemptsLeft - 1), 200);
      }
    }
    setTimeout(() => tryStart(3), 600);
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', autoStart);
  } else {
    autoStart();
  }

  // Экспорт для ручного запуска (например из консоли):
  //   PrideTour.reset(); — сбросить флаг и показать тур снова
  //   new PrideTour.Tour(steps).start();
  global.PrideTour = {
    Tour,
    DEFAULT_STEPS,
    reset() {
      try { localStorage.removeItem(STORAGE_KEY); } catch (e) {}
      const tour = new Tour(DEFAULT_STEPS);
      tour.start();
      global.__prideTour = tour;
      return tour;
    },
    isCompleted() {
      try { return !!localStorage.getItem(STORAGE_KEY); }
      catch (e) { return false; }
    },
  };
})(window);
