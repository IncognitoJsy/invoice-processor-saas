/* Shared supplier line-item UI: per-unit cost/sell + line-total breakdown, markup %,
 * manual per-unit selling-price override (⚑ MANUAL badge, cap-bypass), and updated-at stamp.
 * Used by the invoices, supplier-quotes, and upload-result views — one source of truth so the
 * override's cap-bypass + MANUAL behaviour is IDENTICAL everywhere.
 *
 * Per-view wiring via LineItems.setContext({ endpoint, refetch, partEditable, editable }):
 *   endpoint    : base for the routes; PUT `${endpoint}/${id}/price|quantity|exclude`
 *                 (default '/invoices/item'). All views store lines as InvoiceItem.
 *   refetch     : fn() called after a successful edit to re-render the active view (so header
 *                 totals reflect the server recompute — exclude/qty/override all funnel through it).
 *   partEditable: when true, the part-number cell is the editable invoice variant.
 *   editable    : when true (UNSYNCED invoices only — the server also enforces this), the quantity
 *                 is inline-editable and each row gets a remove/restore (soft-remove) control. The
 *                 caller passes editable:false for synced invoices, so the controls simply vanish.
 */
(function () {
  'use strict';

  function _esc(str) {
    if (str === null || str === undefined) return '';
    return String(str).replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;').replace(/'/g, '&#039;');
  }
  function _escA(str) {
    if (str === null || str === undefined) return '';
    return String(str).replace(/&/g, '&amp;').replace(/"/g, '&quot;').replace(/'/g, '&#039;')
      .replace(/</g, '&lt;').replace(/>/g, '&gt;');
  }
  function fmtMoney(n) { return '£' + (parseFloat(n || 0)).toFixed(2); }
  function relTime(iso) {
    if (!iso) return '—';
    const d = new Date(iso), s = Math.floor((Date.now() - d.getTime()) / 1000);
    if (s < 60) return 'just now';
    if (s < 3600) return Math.floor(s / 60) + 'm ago';
    if (s < 86400) return Math.floor(s / 3600) + 'h ago';
    if (s < 2592000) return Math.floor(s / 86400) + 'd ago';
    return d.toLocaleDateString('en-GB', { day: 'numeric', month: 'short' });
  }

  // One active view at a time (a single open modal / result), so a single current context is safe.
  // overrideEnabled=true → interactive selling-price edit + ⚑ MANUAL badge + reset (invoices, and
  // quotes once Phase 2 lands). false → display-only. editable=true adds qty edit + remove/restore.
  let ctx = { endpoint: '/invoices/item', refetch: null, partEditable: false, overrideEnabled: true, editable: false };
  function setContext(c) {
    ctx = Object.assign({ endpoint: '/invoices/item', refetch: null, partEditable: false, overrideEnabled: true, editable: false }, c || {});
  }

  function renderRow(item) {
    const id = parseInt(item.id);
    const qty = parseFloat(item.quantity) || 0, multi = qty > 1;
    const costU = parseFloat(item.cost_per_item) || 0;
    const sellU = parseFloat(item.selling_price) || 0;
    const profitU = parseFloat(item.profit_per_item) || 0;
    const manual = !!item.price_overridden;
    const excluded = !!item.excluded;
    const deduction = (parseFloat(item.total_amount) || 0) < 0;  // sign-derived supplier deduction — retained, not billed
    const markup = (item.markup_percent == null) ? null : parseFloat(item.markup_percent);
    const part = _esc(item.part_number || '-'), partAttr = _escA(item.part_number || '');
    const strike = excluded ? 'line-through' : '';
    const pencil = '<svg class="gz-edit-pencil inline w-3.5 h-3.5 ml-0.5" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M11 5H6a2 2 0 00-2 2v11a2 2 0 002 2h11a2 2 0 002-2v-5m-1.414-9.414a2 2 0 112.828 2.828L11.828 15H9v-2.828l8.586-8.586z"/></svg>';
    const ok = '<svg class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M5 13l4 4L19 7"/></svg>';
    const x = '<svg class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M6 18L18 6M6 6l12 12"/></svg>';
    const trash = '<svg class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M19 7l-.867 12.142A2 2 0 0116.138 21H7.862a2 2 0 01-1.995-1.858L5 7m5 4v6m4-6v6m1-10V4a1 1 0 00-1-1h-4a1 1 0 00-1 1v3M4 7h16"/></svg>';
    const exclBadge = excluded ? '<span class="inline-block px-1.5 py-0.5 mr-1 rounded text-[10px] font-bold bg-gray-400 text-white align-middle">EXCLUDED</span>' : '';
    const dedBadge = deduction ? '<span class="inline-block px-1.5 py-0.5 mr-1 rounded text-[10px] font-bold bg-indigo-500 text-white align-middle" title="Supplier deduction — a component removed from a kit. Kept for reconciliation, NOT billed to the customer.">DEDUCTION</span>' : '';

    const partCell = ctx.partEditable
      ? `<td id="part-cell-${id}" class="px-4 py-3 text-sm align-top">${exclBadge}${dedBadge}<span id="part-display-${id}" class="gz-editable font-mono text-gray-900 dark:text-white ${strike}" onclick="startEditPartNumber(${id}, '${partAttr}')" title="Click to edit part number">${part}${pencil}</span><div id="part-edit-${id}" class="hidden flex items-center space-x-1"><input type="text" id="part-input-${id}" class="w-28 px-2 py-1 text-sm font-mono border border-blue-500 rounded dark:bg-gray-700 dark:text-white uppercase" onkeydown="handlePartNumberKeydown(event, ${id})"><button onclick="savePartNumber(${id})" class="p-1 text-green-600">${ok}</button><button onclick="cancelEditPartNumber(${id})" class="p-1 text-red-600">${x}</button></div></td>`
      : `<td class="px-4 py-3 text-sm align-top">${exclBadge}${dedBadge}<span class="font-mono text-gray-900 dark:text-white ${strike}">${part}</span></td>`;
    const descCell = `<td class="px-4 py-3 text-sm text-gray-500 dark:text-gray-400 align-top ${strike}">${_esc(item.description || '-')}</td>`;
    const qtyCell = ctx.editable
      ? `<td class="px-4 py-3 text-sm text-center align-top"><div id="qty-display-${id}" class="gz-editable" onclick="LineItems.editQty(${id}, ${qty})" title="Click to edit quantity"><span class="text-gray-900 dark:text-white ${strike}">${qty}</span>${pencil}</div><div id="qty-edit-${id}" class="hidden flex items-center justify-center space-x-1"><input type="number" step="0.01" min="0" id="qty-input-${id}" class="w-16 px-2 py-1 text-sm text-center border border-blue-500 rounded dark:bg-gray-700 dark:text-white" onkeydown="LineItems.handleQtyKeydown(event, ${id})"><button onclick="LineItems.saveQty(${id})" class="p-1 text-green-600 hover:bg-green-50 rounded">${ok}</button><button onclick="LineItems.cancelQtyEdit(${id})" class="p-1 text-red-600 hover:bg-red-50 rounded">${x}</button></div></td>`
      : `<td class="px-4 py-3 text-sm text-gray-900 dark:text-white text-center align-top ${strike}">${qty}</td>`;
    const costCell = `<td class="px-4 py-3 text-sm text-right text-gray-900 dark:text-white align-top ${strike}"><div>${fmtMoney(costU)}${multi ? '<span class="text-gray-400 text-xs"> /u</span>' : ''}</div>${(multi || deduction) ? `<div class="text-xs text-gray-400">${fmtMoney(costU * qty)} line</div>` : ''}</td>`;
    const sellCell = deduction
      ? `<td class="px-4 py-3 text-sm text-right align-top" title="Not charged to the customer — this supplier deduction is absorbed into your margin"><div class="text-gray-500 dark:text-gray-400">${fmtMoney(sellU)}</div><div class="text-[11px] text-indigo-500 dark:text-indigo-300 font-medium whitespace-nowrap">not charged</div></td>`
      : ctx.overrideEnabled
      ? `<td class="px-4 py-3 text-sm text-right align-top ${manual ? 'bg-amber-50 dark:bg-amber-900/10' : ''}"><div id="sell-display-${id}" class="gz-editable" onclick="LineItems.editSellPrice(${id}, ${sellU})" title="Click to edit selling price"><span class="font-medium text-gray-900 dark:text-white ${strike}">${fmtMoney(sellU)}${multi ? '<span class="text-gray-400 text-xs"> /u</span>' : ''}</span>${pencil}</div><div id="sell-edit-${id}" class="hidden flex items-center justify-end space-x-1"><span class="text-xs text-gray-400">£</span><input type="number" step="0.01" min="0" id="sell-input-${id}" class="w-20 px-2 py-1 text-sm text-right border border-blue-500 rounded dark:bg-gray-700 dark:text-white" onkeydown="LineItems.handleSellKeydown(event, ${id})"><button onclick="LineItems.saveSellPrice(${id})" class="p-1 text-green-600 hover:bg-green-50 rounded">${ok}</button><button onclick="LineItems.cancelSellEdit(${id})" class="p-1 text-red-600 hover:bg-red-50 rounded">${x}</button></div>${multi ? `<div class="text-xs text-gray-400">${fmtMoney(sellU * qty)} line</div>` : ''}</td>`
      : `<td class="px-4 py-3 text-sm text-right text-gray-900 dark:text-white align-top ${strike}"><div>${fmtMoney(sellU)}${multi ? '<span class="text-gray-400 text-xs"> /u</span>' : ''}</div>${multi ? `<div class="text-xs text-gray-400">${fmtMoney(sellU * qty)} line</div>` : ''}</td>`;
    const markupCell = deduction
      ? `<td class="px-4 py-3 text-sm text-right align-top"><span class="text-gray-400" title="No markup — a deduction is not sold">—</span></td>`
      : ctx.overrideEnabled
      ? `<td class="px-4 py-3 text-sm text-right align-top">${manual ? `<span class="inline-block px-2 py-0.5 rounded-full text-xs font-bold bg-amber-500 text-white whitespace-nowrap">⚑ MANUAL</span><div class="text-xs text-gray-500 mt-1">${markup != null ? markup.toFixed(1) + '%' : ''} · <a class="text-blue-600 cursor-pointer hover:underline" onclick="LineItems.resetPrice(${id})">reset</a></div>` : `<span class="text-gray-700 dark:text-gray-300 ${strike}">${markup != null ? markup.toFixed(1) + '%' : '—'}</span>`}</td>`
      : `<td class="px-4 py-3 text-sm text-right align-top"><span class="text-gray-700 dark:text-gray-300 ${strike}">${markup != null ? markup.toFixed(1) + '%' : '—'}</span></td>`;
    const lineProfit = profitU * qty;
    const profitCell = deduction
      ? `<td class="px-4 py-3 text-sm text-right align-top"><span class="text-gray-400">—</span></td>`
      : `<td class="px-4 py-3 text-sm text-right font-medium align-top ${strike} ${lineProfit >= 0 ? 'text-green-600 dark:text-green-400' : 'text-red-600 dark:text-red-400'}">${fmtMoney(lineProfit)}${multi ? `<div class="text-xs text-gray-400 font-normal">${fmtMoney(profitU)}/u</div>` : ''}</td>`;
    const updCell = `<td class="px-4 py-3 text-xs text-gray-400 text-center align-top" title="${item.updated_at || ''}">${manual ? relTime(item.updated_at) : '—'}</td>`;
    // Action cell only in editable views (unsynced invoices). Omitted otherwise so shared 8-column
    // views (quotes / upload result / synced invoices) keep their header alignment.
    const actionCell = ctx.editable
      ? `<td class="px-3 py-3 text-center align-top">${deduction
          ? '<span class="text-gray-300 dark:text-gray-600" title="A supplier deduction stays on record for reconciliation — it is already not billed to the customer">—</span>'
          : excluded
          ? `<button onclick="LineItems.toggleExclude(${id}, false)" class="text-xs text-blue-600 hover:underline whitespace-nowrap" title="Restore this line">↩ Restore</button>`
          : `<button onclick="LineItems.toggleExclude(${id}, true)" class="text-gray-400 hover:text-red-600" title="Remove this line (kept for your records, excluded from totals & sync)">${trash}</button>`
        }</td>`
      : '';
    const rowCls = excluded ? 'row-excluded opacity-50 bg-gray-50 dark:bg-gray-900/30'
      : deduction ? 'row-deduction bg-indigo-50/60 dark:bg-indigo-900/20'
      : '';
    return `<tr class="${rowCls}">${partCell}${descCell}${qtyCell}${costCell}${sellCell}${markupCell}${profitCell}${updCell}${actionCell}</tr>`;
  }

  function editSellPrice(id, perUnit) {
    document.getElementById('sell-display-' + id).classList.add('hidden');
    document.getElementById('sell-edit-' + id).classList.remove('hidden');
    const inp = document.getElementById('sell-input-' + id);
    inp.value = (parseFloat(perUnit) || 0).toFixed(2); inp.focus(); inp.select();
  }
  function cancelSellEdit(id) {
    document.getElementById('sell-edit-' + id).classList.add('hidden');
    document.getElementById('sell-display-' + id).classList.remove('hidden');
  }
  function handleSellKeydown(ev, id) {
    if (ev.key === 'Enter') { ev.preventDefault(); saveSellPrice(id); }
    else if (ev.key === 'Escape') { cancelSellEdit(id); }
  }
  async function saveSellPrice(id) {
    const v = parseFloat(document.getElementById('sell-input-' + id).value);
    if (isNaN(v) || v <= 0) { alert('Enter a selling price greater than 0'); return; }
    try {
      const r = await fetch(ctx.endpoint + '/' + id + '/price', { method: 'PUT', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ selling_price: v }) });
      const d = await r.json();
      if (d.success) { if (ctx.refetch) ctx.refetch(); } else { alert('Failed to update price: ' + (d.error || 'Unknown error')); }
    } catch (e) { console.error(e); alert('Error updating price'); }
  }
  async function resetPrice(id) {
    if (!confirm('Reset to the calculated price? This removes the manual override.')) return;
    try {
      const r = await fetch(ctx.endpoint + '/' + id + '/price?reset=true', { method: 'PUT', headers: { 'Content-Type': 'application/json' } });
      const d = await r.json();
      if (d.success) { if (ctx.refetch) ctx.refetch(); } else { alert('Failed to reset price: ' + (d.error || 'Unknown error')); }
    } catch (e) { console.error(e); alert('Error resetting price'); }
  }

  // ── Quantity edit (editable views only; server enforces unsynced-only) ──────────────────
  function editQty(id, current) {
    document.getElementById('qty-display-' + id).classList.add('hidden');
    document.getElementById('qty-edit-' + id).classList.remove('hidden');
    const inp = document.getElementById('qty-input-' + id);
    inp.value = parseFloat(current) || 0; inp.focus(); inp.select();
  }
  function cancelQtyEdit(id) {
    document.getElementById('qty-edit-' + id).classList.add('hidden');
    document.getElementById('qty-display-' + id).classList.remove('hidden');
  }
  function handleQtyKeydown(ev, id) {
    if (ev.key === 'Enter') { ev.preventDefault(); saveQty(id); }
    else if (ev.key === 'Escape') { cancelQtyEdit(id); }
  }
  async function saveQty(id) {
    const v = parseFloat(document.getElementById('qty-input-' + id).value);
    if (isNaN(v) || v <= 0) { alert('Enter a quantity greater than 0'); return; }
    try {
      const r = await fetch(ctx.endpoint + '/' + id + '/quantity', { method: 'PUT', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ quantity: v }) });
      const d = await r.json();
      if (d.success) { if (ctx.refetch) ctx.refetch(); } else { alert('Failed to update quantity: ' + (d.error || 'Unknown error')); }
    } catch (e) { console.error(e); alert('Error updating quantity'); }
  }

  // ── Soft-remove / restore (editable views only; server enforces unsynced-only) ──────────
  async function toggleExclude(id, exclude) {
    if (exclude && !confirm('Remove this line? It stays on record for your audit trail but is excluded from the totals and from syncing to QuickBooks/Xero. You can restore it any time before syncing.')) return;
    try {
      const q = exclude ? '' : '?restore=true';
      const r = await fetch(ctx.endpoint + '/' + id + '/exclude' + q, { method: 'PUT', headers: { 'Content-Type': 'application/json' } });
      const d = await r.json();
      if (d.success) { if (ctx.refetch) ctx.refetch(); } else { alert('Failed: ' + (d.error || 'Unknown error')); }
    } catch (e) { console.error(e); alert('Error updating line'); }
  }

  window.LineItems = {
    setContext, renderRow,
    editSellPrice, cancelSellEdit, handleSellKeydown, saveSellPrice, resetPrice,
    editQty, cancelQtyEdit, handleQtyKeydown, saveQty, toggleExclude,
    fmtMoney, relTime
  };
})();
