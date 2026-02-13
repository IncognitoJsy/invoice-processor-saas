/**
 * GoZappify Takeoff Canvas v8
 * Complete rebuild: tap-to-place symbols, deletable cable runs,
 * containment lines, floor area (UFH), quick measure, eye toggles.
 */
function takeoffCanvas(projectId, documentId) {
  return {
    projectId, documentId,
    loading: true, saving: false,

    // Canvas state
    canvas: null, ctx: null,
    img: null, imgW: 0, imgH: 0,
    zoom: 1, panX: 0, panY: 0,
    isPanning: false, panStartX: 0, panStartY: 0,
    panStartPanX: 0, panStartPanY: 0,

    // Current tool: select | symbol | room | cable | containment | area | measure | scale
    tool: 'select',
    notification: '',
    notifTimeout: null,

    // Scale calibration
    scalePixelsPerMetre: 50,
    scaleCalibrated: false,
    scalePoints: [],
    scaleInputVisible: false,
    scaleRealMetres: '',

    // Symbol types & placed markers
    symbolTypes: [],
    // Each: { id, name, color, productId, productName, productSku, purchasePrice, salePrice, visible }
    activeSymbolTypeId: null,
    markers: [],
    // Each: { id, typeId, x, y, visible }
    nextMarkerId: 1,

    // Rooms
    rooms: [],
    // Each: { id, name, points:[], color, visible }
    roomDrawing: false,
    roomPoints: [],
    roomNameInput: '',
    nextRoomId: 1,

    // Cable runs
    cableTypes: [
      { value: 'twin_earth_1.5', label: '1.5mm T&E (Lighting)', color: '#facc15' },
      { value: 'twin_earth_2.5', label: '2.5mm T&E (Sockets)', color: '#3b82f6' },
      { value: 'twin_earth_4.0', label: '4.0mm T&E (Ring/Radial)', color: '#22d3ee' },
      { value: 'twin_earth_6.0', label: '6.0mm T&E (Cooker)', color: '#ef4444' },
      { value: 'twin_earth_10', label: '10mm T&E (Shower)', color: '#a855f7' },
      { value: 'cat6', label: 'Cat6 Data', color: '#10b981' },
      { value: 'fire_alarm', label: 'Fire Alarm', color: '#f97316' },
      { value: 'swa', label: 'SWA', color: '#6b7280' },
    ],
    activeCableType: 'twin_earth_2.5',
    cableRuns: [],
    // Each: { id, type, points:[], metres, visible, label }
    cableDrawing: false,
    cablePoints: [],
    nextCableId: 1,

    // Containment
    containmentTypes: [
      { value: 'trunking_mini', label: 'Mini Trunking', color: '#fb923c' },
      { value: 'trunking_maxi', label: 'Maxi Trunking', color: '#e879f9' },
      { value: 'conduit_20mm', label: '20mm Conduit', color: '#fbbf24' },
      { value: 'conduit_25mm', label: '25mm Conduit', color: '#a3e635' },
      { value: 'basket_tray', label: 'Basket Tray', color: '#67e8f9' },
      { value: 'ladder_rack', label: 'Ladder Rack', color: '#c084fc' },
    ],
    activeContainmentType: 'trunking_mini',
    containmentRuns: [],
    containmentDrawing: false,
    containmentPoints: [],
    nextContainmentId: 1,

    // Floor areas
    areas: [],
    // Each: { id, name, points:[], sqm, visible }
    areaDrawing: false,
    areaPoints: [],
    areaNameInput: '',
    nextAreaId: 1,

    // Quick measure (temporary)
    measurePoints: [],
    measureResult: null,

    // Selection
    selectedItem: null, // { type: 'marker'|'cable'|'containment'|'room'|'area', id }

    // Product search
    showProductSearch: false,
    productSearchQuery: '',
    productSearchResults: [],
    productSearching: false,
    productSearchFor: null, // symbolType id we're linking

    // ─── Init ───────────────────────────────────────
    init() {
      this.canvas = this.$refs.canvas;
      this.ctx = this.canvas.getContext('2d');
      this.loadDrawing();
      this.setupEvents();
      this.loadState();
    },

    loadDrawing() {
      this.img = new Image();
      this.img.crossOrigin = 'anonymous';
      this.img.onload = () => {
        this.imgW = this.img.naturalWidth;
        this.imgH = this.img.naturalHeight;
        this.fitToView();
        this.loading = false;
        this.render();
      };
      this.img.onerror = () => { this.loading = false; this.notify('Failed to load drawing', 'error'); };
      this.img.src = `/quotebuilder/api/projects/${this.projectId}/documents/${this.documentId}/render`;
    },

    fitToView() {
      if (!this.imgW) return;
      const cw = this.canvas.parentElement.clientWidth;
      const ch = this.canvas.parentElement.clientHeight;
      this.canvas.width = cw;
      this.canvas.height = ch;
      const sx = cw / this.imgW, sy = ch / this.imgH;
      this.zoom = Math.min(sx, sy) * 0.95;
      this.panX = (cw - this.imgW * this.zoom) / 2;
      this.panY = (ch - this.imgH * this.zoom) / 2;
      this.render();
    },

    setupEvents() {
      // Resize
      const ro = new ResizeObserver(() => { if (this.img && this.imgW) { this.canvas.width = this.canvas.parentElement.clientWidth; this.canvas.height = this.canvas.parentElement.clientHeight; this.render(); } });
      ro.observe(this.canvas.parentElement);

      // Wheel zoom
      this.canvas.addEventListener('wheel', (e) => {
        e.preventDefault();
        const rect = this.canvas.getBoundingClientRect();
        const mx = e.clientX - rect.left, my = e.clientY - rect.top;
        const oldZ = this.zoom;
        const delta = e.deltaY > 0 ? 0.9 : 1.1;
        this.zoom = Math.max(0.05, Math.min(20, this.zoom * delta));
        this.panX = mx - (mx - this.panX) * (this.zoom / oldZ);
        this.panY = my - (my - this.panY) * (this.zoom / oldZ);
        this.render();
      }, { passive: false });

      // Keyboard
      document.addEventListener('keydown', (e) => {
        if (e.key === 'Delete' || e.key === 'Backspace') {
          if (this.selectedItem && !e.target.closest('input')) { e.preventDefault(); this.deleteSelected(); }
        }
        if (e.key === 'Escape') {
          this.cancelDrawing();
          this.selectedItem = null;
          this.measurePoints = [];
          this.measureResult = null;
          this.render();
        }
        if (e.key === '0') this.fitToView();
      });
    },

    // ─── Coordinate transforms ──────────────────────
    screenToCanvas(sx, sy) {
      return { x: (sx - this.panX) / this.zoom, y: (sy - this.panY) / this.zoom };
    },
    canvasToScreen(cx, cy) {
      return { x: cx * this.zoom + this.panX, y: cy * this.zoom + this.panY };
    },
    getCanvasPos(e) {
      const rect = this.canvas.getBoundingClientRect();
      return this.screenToCanvas(e.clientX - rect.left, e.clientY - rect.top);
    },

    // ─── Mouse handlers ─────────────────────────────
    onMouseDown(e) {
      if (e.button === 1 || (e.button === 0 && this.tool === 'select' && !e.shiftKey)) {
        this.isPanning = true;
        this.panStartX = e.clientX;
        this.panStartY = e.clientY;
        this.panStartPanX = this.panX;
        this.panStartPanY = this.panY;
        this.canvas.style.cursor = 'grabbing';
      }
    },

    onMouseMove(e) {
      if (this.isPanning) {
        this.panX = this.panStartPanX + (e.clientX - this.panStartX);
        this.panY = this.panStartPanY + (e.clientY - this.panStartY);
        this.render();
      }
    },

    onMouseUp(e) {
      if (this.isPanning) {
        const dx = Math.abs(e.clientX - this.panStartX);
        const dy = Math.abs(e.clientY - this.panStartY);
        this.isPanning = false;
        this.canvas.style.cursor = '';
        if (dx > 3 || dy > 3) return; // Was a drag, not a click
      }
      // It was a click
      const pos = this.getCanvasPos(e);
      this.handleClick(pos);
    },

    handleClick(pos) {
      switch (this.tool) {
        case 'select': this.handleSelectClick(pos); break;
        case 'symbol': this.handleSymbolClick(pos); break;
        case 'room': this.handleRoomClick(pos); break;
        case 'cable': this.handleCableClick(pos); break;
        case 'containment': this.handleContainmentClick(pos); break;
        case 'area': this.handleAreaClick(pos); break;
        case 'measure': this.handleMeasureClick(pos); break;
        case 'scale': this.handleScaleClick(pos); break;
      }
    },

    handleSelectClick(pos) {
      // Try to select nearest item
      let best = null, bestDist = 20 / this.zoom;

      // Check markers
      for (const m of this.markers) {
        const d = Math.hypot(m.x - pos.x, m.y - pos.y);
        if (d < bestDist) { bestDist = d; best = { type: 'marker', id: m.id }; }
      }
      // Check cable run points
      for (const c of this.cableRuns) {
        for (let i = 0; i < c.points.length - 1; i++) {
          const d = this.distToSegment(pos, c.points[i], c.points[i + 1]);
          if (d < bestDist) { bestDist = d; best = { type: 'cable', id: c.id }; }
        }
      }
      // Check containment
      for (const c of this.containmentRuns) {
        for (let i = 0; i < c.points.length - 1; i++) {
          const d = this.distToSegment(pos, c.points[i], c.points[i + 1]);
          if (d < bestDist) { bestDist = d; best = { type: 'containment', id: c.id }; }
        }
      }
      this.selectedItem = best;
      this.render();
    },

    handleSymbolClick(pos) {
      if (!this.activeSymbolTypeId) { this.notify('Select a symbol type first'); return; }
      const id = this.nextMarkerId++;
      this.markers.push({ id, typeId: this.activeSymbolTypeId, x: pos.x, y: pos.y, visible: true });
      this.render();
      this.autoSave();
    },

    handleRoomClick(pos) {
      this.roomPoints.push(pos);
      this.roomDrawing = true;
      this.render();
    },

    handleCableClick(pos) {
      this.cablePoints.push(pos);
      this.cableDrawing = true;
      this.render();
    },

    handleContainmentClick(pos) {
      this.containmentPoints.push(pos);
      this.containmentDrawing = true;
      this.render();
    },

    handleAreaClick(pos) {
      this.areaPoints.push(pos);
      this.areaDrawing = true;
      this.render();
    },

    handleMeasureClick(pos) {
      this.measurePoints.push(pos);
      if (this.measurePoints.length >= 2) {
        const totalPx = this.calcPolylineLength(this.measurePoints);
        const metres = totalPx / this.scalePixelsPerMetre;
        this.measureResult = metres.toFixed(2) + 'm';
        this.notify(`Measurement: ${metres.toFixed(2)}m`);
        // Don't clear immediately — let user see it, Escape or new click clears
      }
      this.render();
    },

    handleScaleClick(pos) {
      this.scalePoints.push(pos);
      if (this.scalePoints.length === 2) {
        this.scaleInputVisible = true;
      }
      this.render();
    },

    confirmScale() {
      const metres = parseFloat(this.scaleRealMetres);
      if (!metres || metres <= 0) return;
      const px = Math.hypot(this.scalePoints[1].x - this.scalePoints[0].x, this.scalePoints[1].y - this.scalePoints[0].y);
      this.scalePixelsPerMetre = px / metres;
      this.scaleCalibrated = true;
      this.scaleInputVisible = false;
      this.scalePoints = [];
      this.scaleRealMetres = '';
      this.setTool('select');
      this.notify(`Scale set: ${metres}m`);
      this.render();
      this.autoSave();
    },

    // ─── Finish drawing operations ──────────────────
    finishRoom() {
      if (this.roomPoints.length < 3) { this.notify('Need at least 3 points'); return; }
      const name = this.roomNameInput.trim() || `Room ${this.nextRoomId}`;
      const colors = ['#3b82f6', '#10b981', '#f59e0b', '#ef4444', '#8b5cf6', '#ec4899', '#06b6d4', '#84cc16'];
      const color = colors[(this.nextRoomId - 1) % colors.length];
      this.rooms.push({ id: this.nextRoomId++, name, points: [...this.roomPoints], color, visible: true });
      this.roomPoints = [];
      this.roomDrawing = false;
      this.roomNameInput = '';
      this.render();
      this.autoSave();
      this.notify(`Room "${name}" added`);
    },

    finishCable() {
      if (this.cablePoints.length < 2) { this.notify('Need at least 2 points'); return; }
      const type = this.cableTypes.find(t => t.value === this.activeCableType);
      const totalPx = this.calcPolylineLength(this.cablePoints);
      const metres = totalPx / this.scalePixelsPerMetre;
      const wasteMetres = metres * 1.1; // 10% waste
      this.cableRuns.push({
        id: this.nextCableId++,
        type: this.activeCableType,
        label: type ? type.label : this.activeCableType,
        color: type ? type.color : '#888',
        points: [...this.cablePoints],
        metres: parseFloat(metres.toFixed(2)),
        metresWithWaste: parseFloat(wasteMetres.toFixed(2)),
        visible: true,
      });
      this.cablePoints = [];
      this.cableDrawing = false;
      this.render();
      this.autoSave();
      this.notify(`Cable run: ${metres.toFixed(1)}m (+10% waste = ${wasteMetres.toFixed(1)}m)`);
    },

    finishContainment() {
      if (this.containmentPoints.length < 2) { this.notify('Need at least 2 points'); return; }
      const type = this.containmentTypes.find(t => t.value === this.activeContainmentType);
      const totalPx = this.calcPolylineLength(this.containmentPoints);
      const metres = totalPx / this.scalePixelsPerMetre;
      this.containmentRuns.push({
        id: this.nextContainmentId++,
        type: this.activeContainmentType,
        label: type ? type.label : this.activeContainmentType,
        color: type ? type.color : '#888',
        points: [...this.containmentPoints],
        metres: parseFloat(metres.toFixed(2)),
        visible: true,
      });
      this.containmentPoints = [];
      this.containmentDrawing = false;
      this.render();
      this.autoSave();
      this.notify(`Containment: ${metres.toFixed(1)}m`);
    },

    finishArea() {
      if (this.areaPoints.length < 3) { this.notify('Need at least 3 points'); return; }
      const name = this.areaNameInput.trim() || `Area ${this.nextAreaId}`;
      const sqm = this.calcPolygonArea(this.areaPoints) / (this.scalePixelsPerMetre ** 2);
      this.areas.push({
        id: this.nextAreaId++,
        name,
        points: [...this.areaPoints],
        sqm: parseFloat(sqm.toFixed(2)),
        visible: true,
      });
      this.areaPoints = [];
      this.areaDrawing = false;
      this.areaNameInput = '';
      this.render();
      this.autoSave();
      this.notify(`${name}: ${sqm.toFixed(2)} m²`);
    },

    undoLastPoint() {
      if (this.tool === 'cable' && this.cablePoints.length > 0) this.cablePoints.pop();
      else if (this.tool === 'containment' && this.containmentPoints.length > 0) this.containmentPoints.pop();
      else if (this.tool === 'room' && this.roomPoints.length > 0) this.roomPoints.pop();
      else if (this.tool === 'area' && this.areaPoints.length > 0) this.areaPoints.pop();
      else if (this.tool === 'measure' && this.measurePoints.length > 0) { this.measurePoints.pop(); this.measureResult = null; }
      this.render();
    },

    cancelDrawing() {
      this.cablePoints = []; this.cableDrawing = false;
      this.containmentPoints = []; this.containmentDrawing = false;
      this.roomPoints = []; this.roomDrawing = false;
      this.areaPoints = []; this.areaDrawing = false;
      this.measurePoints = []; this.measureResult = null;
      this.scalePoints = []; this.scaleInputVisible = false;
      this.render();
    },

    // ─── Tool switching ─────────────────────────────
    setTool(t) {
      this.cancelDrawing();
      this.selectedItem = null;
      this.tool = t;
      const hints = {
        select: 'Click & drag to pan. Scroll to zoom. Click items to select.',
        symbol: 'Tap on the drawing to place markers.',
        room: 'Click points to draw room boundary. Click "Finish Room" when done.',
        cable: 'Click points along cable route. Click "Finish Run" when done.',
        containment: 'Click points along containment route. Click "Finish" when done.',
        area: 'Click points around perimeter for floor area. Click "Finish Area" when done.',
        measure: 'Click points to measure. Press Escape to clear.',
        scale: 'Click two points of a known distance.',
      };
      this.notify(hints[t] || '');
      this.render();
    },

    // ─── Delete ─────────────────────────────────────
    deleteSelected() {
      if (!this.selectedItem) return;
      const { type, id } = this.selectedItem;
      if (type === 'marker') this.markers = this.markers.filter(m => m.id !== id);
      else if (type === 'cable') this.cableRuns = this.cableRuns.filter(c => c.id !== id);
      else if (type === 'containment') this.containmentRuns = this.containmentRuns.filter(c => c.id !== id);
      else if (type === 'room') this.rooms = this.rooms.filter(r => r.id !== id);
      else if (type === 'area') this.areas = this.areas.filter(a => a.id !== id);
      this.selectedItem = null;
      this.render();
      this.autoSave();
    },

    deleteItem(type, id) {
      if (type === 'marker') this.markers = this.markers.filter(m => m.id !== id);
      else if (type === 'cable') this.cableRuns = this.cableRuns.filter(c => c.id !== id);
      else if (type === 'containment') this.containmentRuns = this.containmentRuns.filter(c => c.id !== id);
      else if (type === 'room') this.rooms = this.rooms.filter(r => r.id !== id);
      else if (type === 'area') this.areas = this.areas.filter(a => a.id !== id);
      else if (type === 'symbolType') {
        this.symbolTypes = this.symbolTypes.filter(s => s.id !== id);
        this.markers = this.markers.filter(m => m.typeId !== id);
        if (this.activeSymbolTypeId === id) this.activeSymbolTypeId = null;
      }
      if (this.selectedItem && this.selectedItem.type === type && this.selectedItem.id === id) this.selectedItem = null;
      this.render();
      this.autoSave();
    },

    // ─── Eye toggle ─────────────────────────────────
    toggleVisibility(type, id) {
      let item;
      if (type === 'marker') item = this.markers.find(m => m.id === id);
      else if (type === 'cable') item = this.cableRuns.find(c => c.id === id);
      else if (type === 'containment') item = this.containmentRuns.find(c => c.id === id);
      else if (type === 'room') item = this.rooms.find(r => r.id === id);
      else if (type === 'area') item = this.areas.find(a => a.id === id);
      else if (type === 'symbolType') {
        item = this.symbolTypes.find(s => s.id === id);
        if (item) {
          item.visible = !item.visible;
          // Toggle all markers of this type too
          this.markers.filter(m => m.typeId === id).forEach(m => m.visible = item.visible);
        }
        this.render();
        return;
      }
      if (item) item.visible = !item.visible;
      this.render();
    },

    toggleAllVisibility(type, visible) {
      if (type === 'symbols') { this.symbolTypes.forEach(s => s.visible = visible); this.markers.forEach(m => m.visible = visible); }
      else if (type === 'rooms') this.rooms.forEach(r => r.visible = visible);
      else if (type === 'cables') this.cableRuns.forEach(c => c.visible = visible);
      else if (type === 'containment') this.containmentRuns.forEach(c => c.visible = visible);
      else if (type === 'areas') this.areas.forEach(a => a.visible = visible);
      this.render();
    },

    // ─── Symbol type management ─────────────────────
    addSymbolType() {
      const colors = ['#ef4444', '#3b82f6', '#10b981', '#f59e0b', '#8b5cf6', '#ec4899', '#06b6d4', '#84cc16', '#f97316', '#6366f1'];
      const id = Date.now();
      this.symbolTypes.push({
        id, name: 'New Symbol', color: colors[this.symbolTypes.length % colors.length],
        productId: null, productName: null, productSku: null,
        purchasePrice: 0, salePrice: 0, visible: true,
      });
      this.activeSymbolTypeId = id;
      // Immediately open rename
      this.$nextTick(() => {
        const input = document.querySelector(`[data-symbol-name="${id}"]`);
        if (input) { input.focus(); input.select(); }
      });
    },

    getSymbolType(id) { return this.symbolTypes.find(s => s.id === id); },
    getMarkerCount(typeId) { return this.markers.filter(m => m.typeId === typeId).length; },

    // ─── Product search ─────────────────────────────
    openProductSearch(symbolTypeId) {
      this.productSearchFor = symbolTypeId;
      this.productSearchQuery = '';
      this.productSearchResults = [];
      this.showProductSearch = true;
      this.$nextTick(() => { document.getElementById('product-search-input')?.focus(); });
    },

    async searchProducts() {
      if (this.productSearchQuery.length < 2) return;
      this.productSearching = true;
      try {
        const res = await fetch(`/quotebuilder/api/products/search?q=${encodeURIComponent(this.productSearchQuery)}`);
        const data = await res.json();
        this.productSearchResults = data.products || [];
      } catch (e) { console.error('Search error:', e); }
      this.productSearching = false;
    },

    linkProduct(product) {
      const st = this.symbolTypes.find(s => s.id === this.productSearchFor);
      if (st) {
        st.productId = product.id;
        st.productName = product.name;
        st.productSku = product.sku || '';
        st.purchasePrice = product.purchase_price || 0;
        st.salePrice = product.sale_price || 0;
        if (st.name === 'New Symbol') st.name = product.name;
      }
      this.showProductSearch = false;
      this.autoSave();
    },

    // ─── Utility calculations ───────────────────────
    calcPolylineLength(points) {
      let len = 0;
      for (let i = 1; i < points.length; i++) {
        len += Math.hypot(points[i].x - points[i - 1].x, points[i].y - points[i - 1].y);
      }
      return len;
    },

    calcPolygonArea(points) {
      // Shoelace formula
      let area = 0;
      const n = points.length;
      for (let i = 0; i < n; i++) {
        const j = (i + 1) % n;
        area += points[i].x * points[j].y;
        area -= points[j].x * points[i].y;
      }
      return Math.abs(area) / 2;
    },

    distToSegment(p, a, b) {
      const dx = b.x - a.x, dy = b.y - a.y;
      const lenSq = dx * dx + dy * dy;
      if (lenSq === 0) return Math.hypot(p.x - a.x, p.y - a.y);
      let t = ((p.x - a.x) * dx + (p.y - a.y) * dy) / lenSq;
      t = Math.max(0, Math.min(1, t));
      return Math.hypot(p.x - (a.x + t * dx), p.y - (a.y + t * dy));
    },

    pointInPolygon(point, polygon) {
      let inside = false;
      for (let i = 0, j = polygon.length - 1; i < polygon.length; j = i++) {
        const xi = polygon[i].x, yi = polygon[i].y;
        const xj = polygon[j].x, yj = polygon[j].y;
        if (((yi > point.y) !== (yj > point.y)) && (point.x < (xj - xi) * (point.y - yi) / (yj - yi) + xi)) {
          inside = !inside;
        }
      }
      return inside;
    },

    getMarkerRoom(marker) {
      for (const room of this.rooms) {
        if (this.pointInPolygon(marker, room.points)) return room;
      }
      return null;
    },

    // ─── Summary calculations ───────────────────────
    get symbolSummary() {
      return this.symbolTypes.map(st => {
        const count = this.getMarkerCount(st.id);
        return {
          ...st, count,
          totalPurchase: count * (st.purchasePrice || 0),
          totalSale: count * (st.salePrice || 0),
        };
      });
    },

    get cableSummary() {
      const grouped = {};
      for (const run of this.cableRuns) {
        if (!grouped[run.type]) grouped[run.type] = { label: run.label, color: run.color, metres: 0, runs: 0 };
        grouped[run.type].metres += run.metresWithWaste || run.metres;
        grouped[run.type].runs++;
      }
      return Object.values(grouped);
    },

    get containmentSummary() {
      const grouped = {};
      for (const run of this.containmentRuns) {
        if (!grouped[run.type]) grouped[run.type] = { label: run.label, color: run.color, metres: 0, runs: 0 };
        grouped[run.type].metres += run.metres;
        grouped[run.type].runs++;
      }
      return Object.values(grouped);
    },

    get totalSymbolPurchase() { return this.symbolSummary.reduce((sum, s) => sum + s.totalPurchase, 0); },
    get totalSymbolSale() { return this.symbolSummary.reduce((sum, s) => sum + s.totalSale, 0); },
    get totalAreaSqm() { return this.areas.reduce((sum, a) => sum + a.sqm, 0); },

    // ─── Notify ─────────────────────────────────────
    notify(msg, type = 'info') {
      this.notification = msg;
      clearTimeout(this.notifTimeout);
      if (msg) this.notifTimeout = setTimeout(() => this.notification = '', 5000);
    },

    // ─── Rendering ──────────────────────────────────
    render() {
      if (!this.ctx || !this.canvas) return;
      const ctx = this.ctx;
      const cw = this.canvas.width, ch = this.canvas.height;

      ctx.clearRect(0, 0, cw, ch);
      ctx.fillStyle = '#111827';
      ctx.fillRect(0, 0, cw, ch);

      ctx.save();
      ctx.translate(this.panX, this.panY);
      ctx.scale(this.zoom, this.zoom);

      // Drawing image
      if (this.img && this.imgW) {
        ctx.drawImage(this.img, 0, 0, this.imgW, this.imgH);
      }

      const lw = (px) => px / this.zoom; // Scale-independent line widths

      // ── Rooms ──
      for (const room of this.rooms) {
        if (!room.visible) continue;
        if (room.points.length < 3) continue;
        ctx.beginPath();
        ctx.moveTo(room.points[0].x, room.points[0].y);
        for (let i = 1; i < room.points.length; i++) ctx.lineTo(room.points[i].x, room.points[i].y);
        ctx.closePath();
        ctx.fillStyle = room.color + '18';
        ctx.fill();
        ctx.strokeStyle = room.color;
        ctx.lineWidth = lw(this.selectedItem?.type === 'room' && this.selectedItem.id === room.id ? 4 : 2);
        ctx.stroke();
        // Label
        const cx = room.points.reduce((s, p) => s + p.x, 0) / room.points.length;
        const cy = room.points.reduce((s, p) => s + p.y, 0) / room.points.length;
        ctx.font = `bold ${lw(13)}px sans-serif`;
        ctx.fillStyle = room.color;
        ctx.textAlign = 'center';
        ctx.fillText(room.name, cx, cy);
      }

      // ── Floor areas ──
      for (const area of this.areas) {
        if (!area.visible) continue;
        if (area.points.length < 3) continue;
        ctx.beginPath();
        ctx.moveTo(area.points[0].x, area.points[0].y);
        for (let i = 1; i < area.points.length; i++) ctx.lineTo(area.points[i].x, area.points[i].y);
        ctx.closePath();
        ctx.fillStyle = 'rgba(251,191,36,0.12)';
        ctx.fill();
        ctx.strokeStyle = '#fbbf24';
        ctx.lineWidth = lw(this.selectedItem?.type === 'area' && this.selectedItem.id === area.id ? 4 : 2);
        ctx.setLineDash([lw(8), lw(4)]);
        ctx.stroke();
        ctx.setLineDash([]);
        const cx = area.points.reduce((s, p) => s + p.x, 0) / area.points.length;
        const cy = area.points.reduce((s, p) => s + p.y, 0) / area.points.length;
        ctx.font = `bold ${lw(12)}px sans-serif`;
        ctx.fillStyle = '#fbbf24';
        ctx.textAlign = 'center';
        ctx.fillText(`${area.name}: ${area.sqm} m²`, cx, cy);
      }

      // ── Cable runs ──
      for (const run of this.cableRuns) {
        if (!run.visible) continue;
        if (run.points.length < 2) continue;
        const selected = this.selectedItem?.type === 'cable' && this.selectedItem.id === run.id;
        ctx.beginPath();
        ctx.moveTo(run.points[0].x, run.points[0].y);
        for (let i = 1; i < run.points.length; i++) ctx.lineTo(run.points[i].x, run.points[i].y);
        ctx.strokeStyle = run.color;
        ctx.lineWidth = lw(selected ? 5 : 3);
        ctx.stroke();
        // Metres label at midpoint
        const mid = Math.floor(run.points.length / 2);
        const mp = run.points[mid];
        ctx.font = `bold ${lw(10)}px sans-serif`;
        ctx.fillStyle = run.color;
        ctx.textAlign = 'center';
        ctx.fillText(`${run.metres}m`, mp.x, mp.y - lw(8));
        // Dots at each point
        for (const p of run.points) {
          ctx.beginPath(); ctx.arc(p.x, p.y, lw(3), 0, Math.PI * 2);
          ctx.fillStyle = run.color; ctx.fill();
        }
      }

      // ── Containment runs ──
      for (const run of this.containmentRuns) {
        if (!run.visible) continue;
        if (run.points.length < 2) continue;
        const selected = this.selectedItem?.type === 'containment' && this.selectedItem.id === run.id;
        ctx.beginPath();
        ctx.moveTo(run.points[0].x, run.points[0].y);
        for (let i = 1; i < run.points.length; i++) ctx.lineTo(run.points[i].x, run.points[i].y);
        ctx.strokeStyle = run.color;
        ctx.lineWidth = lw(selected ? 7 : 5);
        ctx.lineCap = 'round';
        ctx.stroke();
        // Double-line effect
        ctx.strokeStyle = '#111827';
        ctx.lineWidth = lw(selected ? 3 : 1.5);
        ctx.stroke();
        ctx.lineCap = 'butt';
        // Label
        const mid = Math.floor(run.points.length / 2);
        const mp = run.points[mid];
        ctx.font = `bold ${lw(10)}px sans-serif`;
        ctx.fillStyle = run.color;
        ctx.textAlign = 'center';
        ctx.fillText(`${run.label} ${run.metres}m`, mp.x, mp.y - lw(10));
      }

      // ── Symbol markers ──
      for (const marker of this.markers) {
        if (!marker.visible) continue;
        const st = this.getSymbolType(marker.typeId);
        if (!st || !st.visible) continue;
        const selected = this.selectedItem?.type === 'marker' && this.selectedItem.id === marker.id;
        const r = lw(selected ? 10 : 7);
        ctx.beginPath();
        ctx.arc(marker.x, marker.y, r, 0, Math.PI * 2);
        ctx.fillStyle = st.color;
        ctx.fill();
        ctx.strokeStyle = selected ? '#fff' : '#000';
        ctx.lineWidth = lw(selected ? 2.5 : 1);
        ctx.stroke();
      }

      // ── Drawing in progress ──
      // Room points
      if (this.roomPoints.length > 0) {
        ctx.beginPath();
        ctx.moveTo(this.roomPoints[0].x, this.roomPoints[0].y);
        for (let i = 1; i < this.roomPoints.length; i++) ctx.lineTo(this.roomPoints[i].x, this.roomPoints[i].y);
        ctx.strokeStyle = '#6366f1';
        ctx.lineWidth = lw(2);
        ctx.setLineDash([lw(6), lw(4)]);
        ctx.stroke();
        ctx.setLineDash([]);
        for (const p of this.roomPoints) {
          ctx.beginPath(); ctx.arc(p.x, p.y, lw(5), 0, Math.PI * 2);
          ctx.fillStyle = '#6366f1'; ctx.fill();
        }
      }

      // Cable points in progress
      if (this.cablePoints.length > 0) {
        const type = this.cableTypes.find(t => t.value === this.activeCableType);
        const color = type ? type.color : '#888';
        ctx.beginPath();
        ctx.moveTo(this.cablePoints[0].x, this.cablePoints[0].y);
        for (let i = 1; i < this.cablePoints.length; i++) ctx.lineTo(this.cablePoints[i].x, this.cablePoints[i].y);
        ctx.strokeStyle = color;
        ctx.lineWidth = lw(3);
        ctx.setLineDash([lw(6), lw(4)]);
        ctx.stroke();
        ctx.setLineDash([]);
        for (const p of this.cablePoints) {
          ctx.beginPath(); ctx.arc(p.x, p.y, lw(4), 0, Math.PI * 2);
          ctx.fillStyle = color; ctx.fill();
        }
        // Show running total
        if (this.cablePoints.length >= 2) {
          const totalPx = this.calcPolylineLength(this.cablePoints);
          const metres = (totalPx / this.scalePixelsPerMetre).toFixed(1);
          const last = this.cablePoints[this.cablePoints.length - 1];
          ctx.font = `bold ${lw(11)}px sans-serif`;
          ctx.fillStyle = color;
          ctx.textAlign = 'left';
          ctx.fillText(`${metres}m`, last.x + lw(8), last.y - lw(5));
        }
      }

      // Containment points in progress
      if (this.containmentPoints.length > 0) {
        const type = this.containmentTypes.find(t => t.value === this.activeContainmentType);
        const color = type ? type.color : '#888';
        ctx.beginPath();
        ctx.moveTo(this.containmentPoints[0].x, this.containmentPoints[0].y);
        for (let i = 1; i < this.containmentPoints.length; i++) ctx.lineTo(this.containmentPoints[i].x, this.containmentPoints[i].y);
        ctx.strokeStyle = color;
        ctx.lineWidth = lw(5);
        ctx.setLineDash([lw(8), lw(4)]);
        ctx.stroke();
        ctx.setLineDash([]);
        for (const p of this.containmentPoints) {
          ctx.beginPath(); ctx.arc(p.x, p.y, lw(4), 0, Math.PI * 2);
          ctx.fillStyle = color; ctx.fill();
        }
        if (this.containmentPoints.length >= 2) {
          const totalPx = this.calcPolylineLength(this.containmentPoints);
          const metres = (totalPx / this.scalePixelsPerMetre).toFixed(1);
          const last = this.containmentPoints[this.containmentPoints.length - 1];
          ctx.font = `bold ${lw(11)}px sans-serif`;
          ctx.fillStyle = color;
          ctx.textAlign = 'left';
          ctx.fillText(`${metres}m`, last.x + lw(8), last.y - lw(5));
        }
      }

      // Area points in progress
      if (this.areaPoints.length > 0) {
        ctx.beginPath();
        ctx.moveTo(this.areaPoints[0].x, this.areaPoints[0].y);
        for (let i = 1; i < this.areaPoints.length; i++) ctx.lineTo(this.areaPoints[i].x, this.areaPoints[i].y);
        ctx.strokeStyle = '#fbbf24';
        ctx.lineWidth = lw(2);
        ctx.setLineDash([lw(6), lw(4)]);
        ctx.stroke();
        ctx.setLineDash([]);
        for (const p of this.areaPoints) {
          ctx.beginPath(); ctx.arc(p.x, p.y, lw(5), 0, Math.PI * 2);
          ctx.fillStyle = '#fbbf24'; ctx.fill();
        }
      }

      // Measure points (temporary)
      if (this.measurePoints.length > 0) {
        ctx.beginPath();
        ctx.moveTo(this.measurePoints[0].x, this.measurePoints[0].y);
        for (let i = 1; i < this.measurePoints.length; i++) ctx.lineTo(this.measurePoints[i].x, this.measurePoints[i].y);
        ctx.strokeStyle = '#94a3b8';
        ctx.lineWidth = lw(2);
        ctx.setLineDash([lw(4), lw(4)]);
        ctx.stroke();
        ctx.setLineDash([]);
        for (const p of this.measurePoints) {
          ctx.beginPath(); ctx.arc(p.x, p.y, lw(4), 0, Math.PI * 2);
          ctx.fillStyle = '#94a3b8'; ctx.fill();
        }
        if (this.measureResult) {
          const last = this.measurePoints[this.measurePoints.length - 1];
          ctx.font = `bold ${lw(14)}px sans-serif`;
          ctx.fillStyle = '#fff';
          ctx.strokeStyle = '#000';
          ctx.lineWidth = lw(3);
          ctx.textAlign = 'left';
          ctx.strokeText(this.measureResult, last.x + lw(10), last.y - lw(8));
          ctx.fillText(this.measureResult, last.x + lw(10), last.y - lw(8));
        }
      }

      // Scale calibration points
      for (const p of this.scalePoints) {
        ctx.beginPath(); ctx.arc(p.x, p.y, lw(6), 0, Math.PI * 2);
        ctx.fillStyle = '#ef4444'; ctx.fill();
        ctx.strokeStyle = '#fff'; ctx.lineWidth = lw(2); ctx.stroke();
      }
      if (this.scalePoints.length === 2) {
        ctx.beginPath();
        ctx.moveTo(this.scalePoints[0].x, this.scalePoints[0].y);
        ctx.lineTo(this.scalePoints[1].x, this.scalePoints[1].y);
        ctx.strokeStyle = '#ef4444';
        ctx.lineWidth = lw(2);
        ctx.setLineDash([lw(6), lw(4)]);
        ctx.stroke();
        ctx.setLineDash([]);
      }

      ctx.restore();

      // Zoom badge
      ctx.fillStyle = 'rgba(0,0,0,0.6)';
      ctx.fillRect(8, ch - 28, 56, 22);
      ctx.fillStyle = '#94a3b8';
      ctx.font = '11px sans-serif';
      ctx.textAlign = 'left';
      ctx.fillText(`${Math.round(this.zoom * 100)}%`, 14, ch - 13);
    },

    // ─── Save / Load state ──────────────────────────
    autoSave() {
      clearTimeout(this._saveTimer);
      this._saveTimer = setTimeout(() => this.saveState(), 1000);
    },

    async saveState() {
      this.saving = true;
      const state = {
        scalePixelsPerMetre: this.scalePixelsPerMetre,
        scaleCalibrated: this.scaleCalibrated,
        symbolTypes: this.symbolTypes,
        markers: this.markers,
        rooms: this.rooms,
        cableRuns: this.cableRuns,
        containmentRuns: this.containmentRuns,
        areas: this.areas,
        nextMarkerId: this.nextMarkerId,
        nextRoomId: this.nextRoomId,
        nextCableId: this.nextCableId,
        nextContainmentId: this.nextContainmentId,
        nextAreaId: this.nextAreaId,
      };
      try {
        await fetch(`/quotebuilder/api/projects/${this.projectId}/documents/${this.documentId}/takeoff-v8-state`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify(state),
        });
      } catch (e) { console.error('Save error:', e); }
      this.saving = false;
    },

    async loadState() {
      try {
        const res = await fetch(`/quotebuilder/api/projects/${this.projectId}/documents/${this.documentId}/takeoff-v8-state`);
        if (res.ok) {
          const state = await res.json();
          if (state && !state.empty && state.symbolTypes) {
            this.scalePixelsPerMetre = state.scalePixelsPerMetre || 50;
            this.scaleCalibrated = state.scaleCalibrated || false;
            this.symbolTypes = state.symbolTypes || [];
            this.markers = state.markers || [];
            this.rooms = state.rooms || [];
            this.cableRuns = state.cableRuns || [];
            this.containmentRuns = state.containmentRuns || [];
            this.areas = state.areas || [];
            this.nextMarkerId = state.nextMarkerId || (this.markers.length > 0 ? Math.max(...this.markers.map(m => m.id)) + 1 : 1);
            this.nextRoomId = state.nextRoomId || (this.rooms.length > 0 ? Math.max(...this.rooms.map(r => r.id)) + 1 : 1);
            this.nextCableId = state.nextCableId || (this.cableRuns.length > 0 ? Math.max(...this.cableRuns.map(c => c.id)) + 1 : 1);
            this.nextContainmentId = state.nextContainmentId || (this.containmentRuns.length > 0 ? Math.max(...this.containmentRuns.map(c => c.id)) + 1 : 1);
            this.nextAreaId = state.nextAreaId || (this.areas.length > 0 ? Math.max(...this.areas.map(a => a.id)) + 1 : 1);
            this.render();
          }
        }
      } catch (e) { console.error('Load error:', e); }
    },
  };
}
