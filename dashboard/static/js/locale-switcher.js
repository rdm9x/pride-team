/* ===================== Locale switcher (E2.4) =====================
 *
 * Маленький модуль: вешает обработчики на кнопки .locale-switcher
 * в шапке, сохраняет выбор в localStorage и зовёт window.setLocale(),
 * который экспортирует i18n.js (E2.3).
 *
 * Принципы:
 *  - Инициализация начальной локали — НЕ наша забота, её делает i18n.js
 *    (читает localStorage / navigator.language до загрузки JSON-словарей).
 *  - Мы лишь подсвечиваем текущую активную кнопку (по тому что лежит в
 *    localStorage; если ничего — по navigator.language; если и того нет — 'ru').
 *  - Если window.setLocale ещё не определён (i18n.js не подцепился) — пишем
 *    в localStorage всё равно: при следующей загрузке i18n.js подхватит.
 *  - aria-pressed переключается на кнопках; <html lang> обновляется.
 *
 */
(function () {
  "use strict";

  const SUPPORTED = ["ru", "en"];
  // ВАЖНО: ключ должен совпадать с тем, что читает i18n.js (E2.3).
  // i18n.js делает localStorage.getItem('locale') — синхронизируемся.
  const STORAGE_KEY = "locale";

  function detectInitialLocale() {
    const saved = localStorage.getItem(STORAGE_KEY);
    if (saved && SUPPORTED.includes(saved)) return saved;
    const nav = (navigator.language || "ru").slice(0, 2).toLowerCase();
    return SUPPORTED.includes(nav) ? nav : "ru";
  }

  function applyActiveState(lang) {
    document.querySelectorAll(".locale-switcher [data-locale]").forEach((b) => {
      const isActive = b.dataset.locale === lang;
      b.setAttribute("aria-pressed", isActive ? "true" : "false");
    });
  }

  function setLocale(lang) {
    if (!SUPPORTED.includes(lang)) return;
    // 1) persist — даже если i18n.js ещё не загружен, при следующем визите
    //    он подхватит сохранённое значение.
    localStorage.setItem(STORAGE_KEY, lang);
    // 2) <html lang="..."> — нужно для скринридеров и CSS :lang().
    document.documentElement.setAttribute("lang", lang);
    // 3) UI подсветка кнопок.
    applyActiveState(lang);
    // 4) Передаём управление i18n.js — он сам подменит строки в DOM.
    if (typeof window.setLocale === "function") {
      try {
        window.setLocale(lang);
      } catch (e) {
        console.warn("locale-switcher: window.setLocale() threw", e);
      }
    } else {
      // i18n.js не загружен (или ещё не успел) — это ок: при следующей
      // загрузке страницы он прочитает localStorage и подхватит lang.
      console.warn(
        "locale-switcher: window.setLocale() not available yet — " +
          "locale saved to localStorage, UI strings will refresh on next load",
      );
    }
  }

  function currentLangFromEnv() {
    // i18n.js (E2.3) предоставляет window.getLocale() — это самый точный источник.
    if (typeof window.getLocale === "function") {
      const g = window.getLocale();
      if (g) return g;
    }
    return (
      document.documentElement.getAttribute("lang") || detectInitialLocale()
    );
  }

  function init() {
    const buttons = document.querySelectorAll(".locale-switcher [data-locale]");
    if (!buttons.length) return; // компонент не отрисован — ничего не делаем

    // Подсветка на старте. Если i18n.js ещё не успел загрузить локаль (fetch async),
    // событие 'localechange' ниже допереключит кнопки сразу как только он закончит.
    applyActiveState(currentLangFromEnv());

    buttons.forEach((btn) => {
      btn.addEventListener("click", () => setLocale(btn.dataset.locale));
    });

    // Если i18n.js или кто-то ещё поменяет локаль не через нашу кнопку
    // (например при init после async fetch) — пересинхронизируем подсветку.
    window.addEventListener("localechange", () => {
      applyActiveState(currentLangFromEnv());
    });
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", init);
  } else {
    init();
  }
})();
