/*
 * CustomerPicker — the ONE searchable customer dropdown, shared by the invoice sync picker
 * (QuickBooks + Xero) and the Jobs page, so behaviour can't drift (same lesson as window.LineItems).
 *
 * Served sub-second from the local CustomerCache endpoints (read is cache-only; the ~9s live pull
 * happens only on ?refresh=true — the Refresh button, a stale page-load, or a search-miss).
 *
 * Container-scoped (no global element ids), so multiple pickers coexist on one page. The container
 * must hold children tagged with data-cp roles:
 *   search | hidden | dropdown | selected | selectedName | clear | refresh | synced
 *
 * Instantiate:
 *   new CustomerPicker({
 *     container: el|id, provider: 'quickbooks'|'xero',
 *     endpoint: '/integrations/api/quickbooks/customers',
 *     matchEndpoint: '/integrations/api/quickbooks/match-customer', // optional (suggestions)
 *     onSelect: (externalId, displayName) => {...},                 // required
 *     onClear: () => {...},                                         // optional
 *   });
 *
 * Provider shapes (identical to the cache endpoints): QB {Id, DisplayName, FullyQualifiedName};
 * Xero {ContactID, Name, EmailAddress}.
 */
(function () {
  function _relTime(iso) {
    if (window.LineItems && typeof window.LineItems.relTime === 'function') return window.LineItems.relTime(iso);
    if (!iso) return '';
    const s = Math.max(0, (Date.now() - new Date(iso).getTime()) / 1000);
    if (s < 60) return 'just now';
    if (s < 3600) return Math.floor(s / 60) + 'm ago';
    if (s < 86400) return Math.floor(s / 3600) + 'h ago';
    return Math.floor(s / 86400) + 'd ago';
  }
  function _esc(s) { return String(s == null ? '' : s).replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;'); }
  function _escAttr(s) { return String(s == null ? '' : s).replace(/&/g, '&amp;').replace(/"/g, '&quot;').replace(/'/g, '&#39;').replace(/</g, '&lt;').replace(/>/g, '&gt;'); }
  function _debounce(fn, ms) { let t; return function () { clearTimeout(t); const a = arguments, c = this; t = setTimeout(() => fn.apply(c, a), ms); }; }

  class CustomerPicker {
    constructor(opts) {
      this.root = typeof opts.container === 'string' ? document.getElementById(opts.container) : opts.container;
      if (!this.root) return;
      this.provider = opts.provider || 'quickbooks';
      this.endpoint = opts.endpoint;
      this.matchEndpoint = opts.matchEndpoint || null;
      this.onSelect = opts.onSelect || function () {};
      this.onClear = opts.onClear || function () {};

      this.customers = [];
      this.suggestions = [];
      this.syncedAt = null;
      this.open = false;
      this.matchDone = false;
      this.jobReference = opts.jobReference || null;
      this.lastAutoRefresh = 0;
      this.selectedId = null;

      this.$search = this._q('search');
      this.$hidden = this._q('hidden');
      this.$dropdown = this._q('dropdown');
      this.$selected = this._q('selected');
      this.$selectedName = this._q('selectedName');
      this.$synced = this._q('synced');

      this._wire();
      this.load();
    }

    _q(role) { return this.root.querySelector('[data-cp="' + role + '"]'); }

    // ---- provider-aware accessors ----
    _id(c) { return this.provider === 'xero' ? c.ContactID : c.Id; }
    _name(c) { return this.provider === 'xero' ? (c.Name || 'Unknown') : (c.FullyQualifiedName || c.DisplayName); }
    _sub(c) { return this.provider === 'xero' ? false : (c.FullyQualifiedName || '').includes(':'); }
    _indent(c) { return this.provider === 'xero' ? 0 : ((c.FullyQualifiedName || '').match(/:/g) || []).length; }
    _matches(c, term) {
      if (this.provider === 'xero') return (c.Name || '').toLowerCase().includes(term);
      return (c.DisplayName || '').toLowerCase().includes(term) || (c.FullyQualifiedName || '').toLowerCase().includes(term);
    }

    _wire() {
      const s = this.$search;
      if (s) {
        s.addEventListener('focus', () => this._openDropdown());
        s.addEventListener('input', _debounce(() => this._render(s.value), 150));
        s.addEventListener('keydown', (e) => {
          if (e.key === 'Escape') this._closeDropdown();
          else if (e.key === 'ArrowDown') { e.preventDefault(); this._focusItem(1); }
          else if (e.key === 'ArrowUp') { e.preventDefault(); this._focusItem(-1); }
          else if (e.key === 'Enter') { e.preventDefault(); this._selectFocused(); }
        });
      }
      document.addEventListener('click', (e) => { if (!this.root.contains(e.target)) this._closeDropdown(); });
      const refresh = this._q('refresh');
      if (refresh) refresh.addEventListener('click', () => this.refresh(false));
      const clear = this._q('clear');
      if (clear) clear.addEventListener('click', () => this.clear());
    }

    async load() {
      try {
        const r = await fetch(this.endpoint);
        const data = await r.json();
        if (data.customers) this.customers = data.customers;
        this.syncedAt = data.synced_at || null;
        this._meta();
        if (data.stale) this.refresh(true);   // background, non-blocking
      } catch (e) { console.error('CustomerPicker load', e); }
    }

    async refresh(silent) {
      const btn = this._q('refresh');
      if (btn && !silent) { btn.disabled = true; btn.dataset.prev = btn.textContent; btn.textContent = 'Refreshing…'; }
      try {
        const r = await fetch(this.endpoint + (this.endpoint.includes('?') ? '&' : '?') + 'refresh=true');
        const data = await r.json();
        if (data.customers) this.customers = data.customers;
        this.syncedAt = data.synced_at || null;
        this._meta();
        if (this.open) this._render(this.$search ? this.$search.value : '');
      } catch (e) { console.error('CustomerPicker refresh', e); }
      finally { if (btn && !silent) { btn.disabled = false; btn.textContent = btn.dataset.prev || '🔄 Refresh'; } }
    }

    _meta() { if (this.$synced) this.$synced.textContent = this.syncedAt ? ('Synced ' + _relTime(this.syncedAt)) : 'Not synced yet'; }

    setJobReference(ref) { this.jobReference = ref; this.matchDone = false; this.suggestions = []; }

    async _runSuggestions() {
      if (!this.matchEndpoint || !this.jobReference) return;
      try {
        const r = await fetch(this.matchEndpoint + '?job_reference=' + encodeURIComponent(this.jobReference));
        const data = await r.json();
        if (data.matches && data.matches.length) {
          this.suggestions = data.matches;
          if (data.matches[0].confidence >= 80) this._select(data.matches[0].customer_id, data.matches[0].customer_name);
          else if (this.open) this._render(this.$search ? this.$search.value : '');
        }
      } catch (e) { console.error('CustomerPicker suggestions', e); }
    }

    _openDropdown() {
      if (!this.$dropdown) return;
      this.$dropdown.classList.remove('hidden');
      this.open = true;
      if (!this.matchDone && this.jobReference && !this.selectedId) { this.matchDone = true; this._runSuggestions(); }
      this._render(this.$search ? this.$search.value : '');
    }
    _closeDropdown() { if (this.$dropdown) { this.$dropdown.classList.add('hidden'); this.open = false; } }

    _render(searchTerm) {
      const dd = this.$dropdown; if (!dd) return;
      const term = (searchTerm || '').toLowerCase().trim();
      const sorted = [...this.customers].sort((a, b) => this._name(a).toUpperCase().localeCompare(this._name(b).toUpperCase()));
      let html = '';
      if (this.suggestions.length && term === '') {
        html += '<div class="px-3 py-2 text-xs font-semibold text-green-600 dark:text-green-400 bg-green-50 dark:bg-green-900/20 border-b border-gray-200 dark:border-gray-700">⭐ Suggested</div>';
        this.suggestions.forEach(m => {
          const c = this.customers.find(x => this._id(x) === m.customer_id);
          if (!c) return;
          const nm = this._name(c), en = _escAttr(nm);
          html += '<div class="cp-option px-3 py-2 cursor-pointer hover:bg-blue-50 dark:hover:bg-blue-900/20 flex items-center justify-between" data-id="' + _escAttr(this._id(c)) + '" data-name="' + en + '"><span class="text-sm font-medium text-gray-900 dark:text-white truncate">⭐ ' + _esc(nm) + '</span><span class="text-xs text-green-600 dark:text-green-400 ml-2">' + parseInt(m.confidence) + '%</span></div>';
        });
        html += '<div class="px-3 py-2 text-xs font-semibold text-gray-500 dark:text-gray-400 bg-gray-50 dark:bg-gray-800 border-b border-gray-200 dark:border-gray-700">All Customers</div>';
      }
      const filtered = term ? sorted.filter(c => this._matches(c, term)) : sorted;
      filtered.slice(0, 100).forEach(c => {
        if (term === '' && this.suggestions.some(s => s.customer_id === this._id(c))) return;
        const nm = this._name(c), en = _escAttr(nm), sub = this._sub(c), lvl = this._indent(c);
        const pad = lvl > 0 ? 'pl-' + (3 + lvl * 4) : 'pl-3';
        html += '<div class="cp-option ' + pad + ' pr-3 py-2 cursor-pointer hover:bg-blue-50 dark:hover:bg-blue-900/20" data-id="' + _escAttr(this._id(c)) + '" data-name="' + en + '"><span class="text-sm text-gray-900 dark:text-white truncate">' + (sub ? '<span class="text-gray-400 mr-1">↳</span>' : '') + _esc(nm) + '</span></div>';
      });
      if (filtered.length === 0) {
        html = '<div class="px-3 py-4 text-sm text-gray-500 dark:text-gray-400 text-center">' + (term.length >= 3 ? 'No match — checking for new customers…' : 'No customers found') + '</div>';
        if (term.length >= 3) this._maybeAutoRefresh();
      }
      dd.innerHTML = html;
      dd.querySelectorAll('.cp-option').forEach(el => el.addEventListener('click', () => this._select(el.dataset.id, el.dataset.name)));
    }

    _maybeAutoRefresh() { const now = Date.now(); if (now - this.lastAutoRefresh < 60000) return; this.lastAutoRefresh = now; this.refresh(true); }

    _select(id, name) {
      this.selectedId = id;
      if (this.$hidden) this.$hidden.value = id;
      if (this.$search) this.$search.value = '';
      if (this.$selected) this.$selected.classList.remove('hidden');
      if (this.$selectedName) this.$selectedName.textContent = name;
      this._closeDropdown();
      this.onSelect(id, name);
    }

    clear() {
      this.selectedId = null;
      if (this.$hidden) this.$hidden.value = '';
      if (this.$selected) this.$selected.classList.add('hidden');
      if (this.$search) this.$search.value = '';
      this.onClear();
    }

    value() { return this.$hidden ? this.$hidden.value : this.selectedId; }
    selectedName() { return this.$selectedName ? this.$selectedName.textContent : ''; }
    close() { this._closeDropdown(); }

    _items() { return this.$dropdown ? this.$dropdown.querySelectorAll('.cp-option') : []; }
    _focusItem(dir) {
      const items = this._items(); if (!items.length) return;
      const cls = ['focused', 'bg-blue-50', 'dark:bg-blue-900/20'];
      const cur = this.$dropdown.querySelector('.cp-option.focused');
      let idx = cur ? Array.from(items).indexOf(cur) : -1;
      if (cur) cur.classList.remove(...cls);
      idx = dir > 0 ? Math.min(items.length - 1, idx + 1) : Math.max(0, idx - 1);
      if (idx < 0) idx = 0;
      items[idx].classList.add(...cls);
      items[idx].scrollIntoView({ block: 'nearest' });
    }
    _selectFocused() { const f = this.$dropdown && this.$dropdown.querySelector('.cp-option.focused'); if (f) this._select(f.dataset.id, f.dataset.name); }
  }

  window.CustomerPicker = CustomerPicker;
})();
