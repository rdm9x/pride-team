/* devboard i18n loader — vanilla, no deps.
 * API: window.t(key, params), window.setLocale(lang), window.loadLocale(lang),
 *      window.applyI18nToDOM(), window.getLocale().
 * Markup: data-i18n="dot.path"  data-i18n-attr="placeholder:dot.path[,title:other.path]"
 * Event:  'localechange' on window after setLocale().
 */
(function (global) {
  'use strict';

  var cache = Object.create(null); // lang -> dict
  var current = null;              // currently active dict
  var currentLang = null;

  function resolve(key) {
    if (!current || !key) return undefined;
    // Try direct key first (safety for flat JSON with dots)
    if (Object.prototype.hasOwnProperty.call(current, key)) {
      var direct = current[key];
      if (typeof direct === 'string') return direct;
    }
    var parts = key.split('.');
    var node = current;
    for (var i = 0; i < parts.length; i++) {
      if (node == null || typeof node !== 'object') return undefined;
      node = node[parts[i]];
    }
    return typeof node === 'string' ? node : undefined;
  }

  function interpolate(str, params) {
    if (!params) return str;
    return str.replace(/\{(\w+)\}/g, function (m, k) {
      return params[k] != null ? params[k] : m;
    });
  }

  function t(key, params) {
    var s = resolve(key);
    if (s == null) return key;
    return interpolate(s, params);
  }

  function loadLocale(lang) {
    if (cache[lang]) {
      current = cache[lang];
      currentLang = lang;
      return Promise.resolve(cache[lang]);
    }
    return fetch('/static/i18n/' + lang + '.json', { credentials: 'same-origin' })
      .then(function (r) {
        if (!r.ok) throw new Error('i18n ' + lang + ' ' + r.status);
        return r.json();
      })
      .then(function (dict) {
        cache[lang] = dict;
        current = dict;
        currentLang = lang;
        return dict;
      })
      .catch(function (err) {
        console.warn('[i18n] load failed for "' + lang + '":', err.message);
        if (lang !== 'ru') return loadLocale('ru');
        throw err;
      });
  }

  function applyToDOM(root) {
    var scope = root || document;
    var nodes = scope.querySelectorAll('[data-i18n]');
    for (var i = 0; i < nodes.length; i++) {
      var el = nodes[i];
      var key = el.getAttribute('data-i18n');
      var fallback = el.textContent;
      var val = resolve(key);
      if (val != null) el.textContent = val;
      else if (!fallback) el.textContent = key;
    }
    var attrNodes = scope.querySelectorAll('[data-i18n-attr]');
    for (var j = 0; j < attrNodes.length; j++) {
      var node = attrNodes[j];
      var spec = node.getAttribute('data-i18n-attr');
      var pairs = spec.split(',');
      for (var k = 0; k < pairs.length; k++) {
        var pair = pairs[k].trim();
        var idx = pair.indexOf(':');
        if (idx < 0) continue;
        var attr = pair.slice(0, idx).trim();
        var akey = pair.slice(idx + 1).trim();
        var aval = resolve(akey);
        if (aval != null) node.setAttribute(attr, aval);
      }
    }
  }

  function setLocale(lang) {
    return loadLocale(lang).then(function () {
      try { document.documentElement.lang = currentLang; } catch (e) {}
      applyToDOM();
      try { global.dispatchEvent(new Event('localechange')); } catch (e) {}
      return currentLang;
    });
  }

  function getLocale() { return currentLang; }

  // Expose
  global.t = t;
  global.loadLocale = loadLocale;
  global.applyI18nToDOM = applyToDOM;
  global.setLocale = setLocale;
  global.getLocale = getLocale;

  // Auto-init
  function init() {
    var saved = null;
    try { saved = localStorage.getItem('locale'); } catch (e) {}
    var nav = (global.navigator && global.navigator.language) || 'ru';
    var lang = saved || nav.slice(0, 2);
    var finalLang = (lang === 'en') ? 'en' : 'ru';
    setLocale(finalLang).catch(function (e) {
      console.warn('[i18n] init failed:', e && e.message);
    });
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', init, { once: true });
  } else {
    init();
  }
})(window);
