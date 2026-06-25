/* Shared supplier line-item UI: per-unit cost/sell + line-total breakdown, markup %,
 * manual per-unit selling-price override (⚑ MANUAL badge, cap-bypass), and updated-at stamp.
 * Used by the invoices, supplier-quotes, and upload-result views — one source of truth so the
 * override's cap-bypass + MANUAL behaviour is IDENTICAL everywhere.
 *
 * Per-view wiring via LineItems.setContext({ endpoint, refetch, partEditable }):
 *   endpoint    : base for the price route; PUT `${endpoint}/${id}/price` (default '/invoices/item').
 *                 All three views store lines as InvoiceItem, so the default route works for all.
 *   refetch     : fn() called after a successful override/reset to re-render the active view.
 *   partEditable: when true, the part-number cell is the editable invoice variant (uses the
 *                 invoice page's global startEditPartNumber/savePartNumber/… ); else plain display.
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
  // quotes once Phase 2 lands). false → display-only: plain selling price, markup % only, NO edit
  // affordances or onclicks (quotes Phase 1, so override is genuinely inert until wired).
  let ctx = { endpoint: '/invoices/item', refetch: null, partEditable: false, overrideEnabled: true };
  function setContext(c) {
    ctx = Object.assign({ endpoint: '/invoices/item', refetch: null, partEditable: false, overrideEnabled: true }, c || {});
  }

  function renderRow(item) {
    const id = parseInt(item.id);
    const qty = parseFloat(item.quantity) || 0, multi = qty > 1;
    const costU = parseFloat(item.cost_per_item) || 0;
    const sellU = parseFloat(item.selling_price) || 0;
    const profitU = parseFloat(item.profit_per_item) || 0;
    const manual = !!item.price_overridden;
    const markup = (item.markup_percent == null) ? null : parseFloat(item.markup_percent);
    const part = _esc(item.part_number || '-'), partAttr = _escA(item.part_number || '');
    const pencil = '<svg class="inline w-3.5 h-3.5 text-gray-400 ml-0.5" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M11 5H6a2 2 0 00-2 2v11a2 2 0 002 2h11a2 2 0 002-2v-5m-1.414-9.414a2 2 0 112.828 2.828L11.828 15H9v-2.828l8.586-8.586z"/></svg>';
    const ok = '<svg class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M5 13l4 4L19 7"/></svg>';
    const x = '<svg class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M6 18L18 6M6 6l12 12"/></svg>';

    const partCell = ctx.partEditable
      ? `<td id="part-cell-${id}" class="px-4 py-3 text-sm align-top"><span id="part-display-${id}" class="font-mono text-gray-900 dark:text-white cursor-pointer hover:text-blue-600 dark:hover:text-blue-400 hover:underline" onclick="startEditPartNumber(${id}, '${partAttr}')">${part}</span><div id="part-edit-${id}" class="hidden flex items-center space-x-1"><input type="text" id="part-input-${id}" class="w-28 px-2 py-1 text-sm font-mono border border-blue-500 rounded dark:bg-gray-700 dark:text-white uppercase" onkeydown="handlePartNumberKeydown(event, ${id})"><button onclick="savePartNumber(${id})" class="p-1 text-green-600">${ok}</button><button onclick="cancelEditPartNumber(${id})" class="p-1 text-red-600">${x}</button></div></td>`
      : `<td class="px-4 py-3 text-sm align-top"><span class="font-mono text-gray-900 dark:text-white">${part}</span></td>`;
    const descCell = `<td class="px-4 py-3 text-sm text-gray-500 dark:text-gray-400 align-top">${_esc(item.description || '-')}</td>`;
    const qtyCell = `<td class="px-4 py-3 text-sm text-gray-900 dark:text-white text-center align-top">${qty}</td>`;
    const costCell = `<td class="px-4 py-3 text-sm text-right text-gray-900 dark:text-white align-top"><div>${fmtMoney(costU)}${multi ? '<span class="text-gray-400 text-xs"> /u</span>' : ''}</div>${multi ? `<div class="text-xs text-gray-400">${fmtMoney(costU * qty)} line</div>` : ''}</td>`;
    const sellCell = ctx.overrideEnabled
      ? `<td class="px-4 py-3 text-sm text-right align-top ${manual ? 'bg-amber-50 dark:bg-amber-900/10' : ''}"><div id="sell-display-${id}"><span class="font-medium text-gray-900 dark:text-white cursor-pointer hover:text-blue-600 hover:underline" onclick="LineItems.editSellPrice(${id}, ${sellU})" title="Click to edit selling price">${fmtMoney(sellU)}${multi ? '<span class="text-gray-400 text-xs"> /u</span>' : ''}</span>${pencil}</div><div id="sell-edit-${id}" class="hidden flex items-center justify-end space-x-1"><span class="text-xs text-gray-400">£</span><input type="number" step="0.01" min="0" id="sell-input-${id}" class="w-20 px-2 py-1 text-sm text-right border border-blue-500 rounded dark:bg-gray-700 dark:text-white" onkeydown="LineItems.handleSellKeydown(event, ${id})"><button onclick="LineItems.saveSellPrice(${id})" class="p-1 text-green-600 hover:bg-green-50 rounded">${ok}</button><button onclick="LineItems.cancelSellEdit(${id})" class="p-1 text-red-600 hover:bg-red-50 rounded">${x}</button></div>${multi ? `<div class="text-xs text-gray-400">${fmtMoney(sellU * qty)} line</div>` : ''}</td>`
      : `<td class="px-4 py-3 text-sm text-right text-gray-900 dark:text-white align-top"><div>${fmtMoney(sellU)}${multi ? '<span class="text-gray-400 text-xs"> /u</span>' : ''}</div>${multi ? `<div class="text-xs text-gray-400">${fmtMoney(sellU * qty)} line</div>` : ''}</td>`;
    const markupCell = ctx.overrideEnabled
      ? `<td class="px-4 py-3 text-sm text-right align-top">${manual ? `<span class="inline-block px-2 py-0.5 rounded-full text-xs font-bold bg-amber-500 text-white whitespace-nowrap">⚑ MANUAL</span><div class="text-xs text-gray-500 mt-1">${markup != null ? markup.toFixed(1) + '%' : ''} · <a class="text-blue-600 cursor-pointer hover:underline" onclick="LineItems.resetPrice(${id})">reset</a></div>` : `<span class="text-gray-700 dark:text-gray-300">${markup != null ? markup.toFixed(1) + '%' : '—'}</span>`}</td>`
      : `<td class="px-4 py-3 text-sm text-right align-top"><span class="text-gray-700 dark:text-gray-300">${markup != null ? markup.toFixed(1) + '%' : '—'}</span></td>`;
    const lineProfit = profitU * qty;
    const profitCell = `<td class="px-4 py-3 text-sm text-right font-medium align-top ${lineProfit >= 0 ? 'text-green-600 dark:text-green-400' : 'text-red-600 dark:text-red-400'}">${fmtMoney(lineProfit)}${multi ? `<div class="text-xs text-gray-400 font-normal">${fmtMoney(profitU)}/u</div>` : ''}</td>`;
    const updCell = `<td class="px-4 py-3 text-xs text-gray-400 text-center align-top" title="${item.updated_at || ''}">${manual ? relTime(item.updated_at) : '—'}</td>`;
    return `<tr>${partCell}${descCell}${qtyCell}${costCell}${sellCell}${markupCell}${profitCell}${updCell}</tr>`;
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

  window.LineItems = {
    setContext, renderRow,
    editSellPrice, cancelSellEdit, handleSellKeydown, saveSellPrice, resetPrice,
    fmtMoney, relTime
  };
})();
