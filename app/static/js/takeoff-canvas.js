/**
 * GoZappify Takeoff Canvas V7
 * Based on V1 structure + zoom/pan + QB/Xero product search
 */
function takeoffCanvas(projectId, documentId) {
    return {
        projectId, documentId,
        loading: true, error: null,
        notification: null, notificationTimeout: null,

        // Canvas
        canvas: null, ctx: null,
        drawingImage: null, drawingLoaded: false,

        // Zoom/Pan
        zoom: 1, panX: 0, panY: 0,
        isPanning: false, panAnchorX: 0, panAnchorY: 0, panStartX: 0, panStartY: 0, didDrag: false,

        // Mode
        mode: 'select',

        // Scale
        scale: 50, scaleCalibrated: false, scalePoints: [],
        showScaleModal: false, scaleRealDistance: '',
        showAutoScaleModal: false, autoScaleRatio: '', autoScalePaper: 'A1', autoScaleOrientation: 'landscape',

        // Symbol detection
        symbolTemplates: [], detections: [], detecting: false, detectingTemplateId: null,
        isDrawingBox: false, boxStart: null, currentBox: null,
        manualPlacingTemplate: null, // Template being manually placed on drawing

        // Product search (modal after symbol box)
        showProductModal: false, pendingBox: null,
        productSearch: '', productResults: [], productSearching: false, selectedProduct: null,

        // Product link from sidebar
        linkingTemplate: null,

        // Key area
        keyArea: null, settingKeyArea: false,

        // Rooms
        rooms: [], roomPoints: [], drawingRoom: false, highlightedRoom: null,

        // Cable runs
        cableRuns: [], cablePoints: [], cableType: 'socket',
        cableTypes: [
            { value: 'lighting', label: '1.5mm T&E (Lighting)', color: '#fbbf24' },
            { value: 'socket', label: '2.5mm T&E (Sockets)', color: '#3b82f6' },
            { value: 'cooker', label: '6.0mm T&E (Cooker)', color: '#ef4444' },
            { value: 'shower', label: '10mm T&E (Shower)', color: '#8b5cf6' },
            { value: 'data', label: 'Cat6 Data', color: '#10b981' },
            { value: 'fire_alarm', label: 'Fire Alarm', color: '#f97316' },
            { value: 'swa', label: 'SWA', color: '#6b7280' },
        ],

        // Areas
        areas: [], areaPoints: [],

        // Summary
        showSummary: false,

        // ── Init ─────────────────────────────────────────────────
        async init() {
            this.canvas = this.$refs.takeoffCanvas;
            if (!this.canvas) { this.error = 'Canvas not found'; return; }
            this.ctx = this.canvas.getContext('2d');
            await this.loadDrawing();
            await this.loadState();
            this.setupEvents();
            this.loading = false;
            this.fitToScreen();
        },

        async loadDrawing() {
            return new Promise((resolve, reject) => {
                this.drawingImage = new Image();
                this.drawingImage.onload = () => { this.drawingLoaded = true; resolve(); };
                this.drawingImage.onerror = () => { this.error = 'Failed to load drawing'; reject(); };
                this.drawingImage.src = `/quotebuilder/api/projects/${this.projectId}/documents/${this.documentId}/render`;
            });
        },

        async loadState() {
            try {
                const r = await fetch(`/quotebuilder/api/projects/${this.projectId}/documents/${this.documentId}/takeoff-state`);
                const d = await r.json();
                if (d.success) {
                    this.rooms = d.rooms || [];
                    this.symbolTemplates = d.symbol_templates || [];
                    this.detections = d.detections || [];
                    this.cableRuns = d.cable_runs || [];
                    this.areas = d.areas || [];
                    this.scale = d.scale || 50;
                    if (d.scale && d.scale !== 50) this.scaleCalibrated = true;
                    // Debug: log template linking status
                    this.symbolTemplates.forEach(t => {
                        console.log(`Template "${t.label}": part=${t.default_part_number || 'NONE'}, cost=${t.default_unit_cost}, sell=${t.default_unit_sell}`);
                    });
                }
            } catch (e) { console.error('Load state error:', e); }
        },

        // ── Events ───────────────────────────────────────────────
        setupEvents() {
            this.canvas.addEventListener('wheel', (e) => {
                e.preventDefault();
                const rect = this.canvas.getBoundingClientRect();
                const mx = e.clientX - rect.left, my = e.clientY - rect.top;
                // Trackpad-friendly: use actual deltaY magnitude, clamped and scaled down
                // Trackpads send small deltas frequently; mice send large deltas rarely
                const raw = Math.sign(e.deltaY) * Math.min(Math.abs(e.deltaY), 50);
                const factor = 1 - raw * 0.0015; // ~0.15% per pixel of scroll
                const minZoom = this.getMinZoom();
                const nz = Math.max(minZoom, Math.min(10, this.zoom * factor));
                if (nz === this.zoom) return;
                const s = nz / this.zoom;
                this.panX = mx - (mx - this.panX) * s;
                this.panY = my - (my - this.panY) * s;
                this.zoom = nz;
                this.constrainPan();
                this.redraw();
            }, { passive: false });

            document.addEventListener('keydown', (e) => {
                if (e.target.tagName === 'INPUT' || e.target.tagName === 'TEXTAREA') return;
                if (e.key === 'Escape') this.setMode('select');
                if (e.key === '0') this.fitToScreen();
            });

            window.addEventListener('resize', () => this.redraw());
        },

        // ── Zoom ─────────────────────────────────────────────────
        getMinZoom() {
            if (!this.drawingImage || !this.canvas) return 0.1;
            const c = this.canvas.parentElement;
            const sx = c.clientWidth / this.drawingImage.width;
            const sy = c.clientHeight / this.drawingImage.height;
            return Math.min(sx, sy) * 0.95;
        },

        constrainPan() {
            // Drawing edges never go past canvas edges — image stays fully within the box
            if (!this.drawingImage || !this.canvas) return;
            const c = this.canvas.parentElement;
            const cw = c.clientWidth, ch = c.clientHeight;
            const dw = this.drawingImage.width * this.zoom;
            const dh = this.drawingImage.height * this.zoom;

            // If image fits inside canvas, centre it
            if (dw <= cw) {
                this.panX = (cw - dw) / 2;
            } else {
                // Don't let left edge go right of canvas left, or right edge go left of canvas right
                this.panX = Math.max(cw - dw, Math.min(0, this.panX));
            }
            if (dh <= ch) {
                this.panY = (ch - dh) / 2;
            } else {
                this.panY = Math.max(ch - dh, Math.min(0, this.panY));
            }
        },

        fitToScreen() {
            if (!this.drawingImage || !this.canvas) return;
            const c = this.canvas.parentElement;
            this.zoom = this.getMinZoom();
            this.panX = (c.clientWidth - this.drawingImage.width * this.zoom) / 2;
            this.panY = (c.clientHeight - this.drawingImage.height * this.zoom) / 2;
            this.redraw();
        },

        zoomIn() { const min = this.getMinZoom(); this.zoom = Math.min(10, this.zoom * 1.3); this.constrainPan(); this.redraw(); },
        zoomOut() { const min = this.getMinZoom(); this.zoom = Math.max(min, this.zoom * 0.77); this.constrainPan(); this.redraw(); },

        screenToImage(sx, sy) {
            return { x: (sx - this.panX) / this.zoom, y: (sy - this.panY) / this.zoom };
        },

        zoomToRoom(room) {
            const pts = room.boundary_points || room.points || [];
            if (pts.length < 3) return;
            const xs = pts.map(p=>p.x), ys = pts.map(p=>p.y);
            const c = this.canvas.parentElement;
            const minX = Math.min(...xs), maxX = Math.max(...xs), minY = Math.min(...ys), maxY = Math.max(...ys);
            this.zoom = Math.min(c.clientWidth/(maxX-minX+200), c.clientHeight/(maxY-minY+200), 8);
            this.panX = c.clientWidth/2 - ((minX+maxX)/2)*this.zoom;
            this.panY = c.clientHeight/2 - ((minY+maxY)/2)*this.zoom;
            this.redraw();
        },

        // ── Mouse ────────────────────────────────────────────────
        onMouseDown(e) {
            const rect = this.canvas.getBoundingClientRect();
            const sx = e.clientX - rect.left, sy = e.clientY - rect.top;
            const img = this.screenToImage(sx, sy);
            this.didDrag = false;

            // Pan in select mode (no other action active)
            if (this.mode === 'select' && !this.settingKeyArea) {
                this.isPanning = true;
                this.panAnchorX = e.clientX; this.panAnchorY = e.clientY;
                this.panStartX = this.panX; this.panStartY = this.panY;
                this.canvas.style.cursor = 'grabbing';
                return;
            }

            // Drawing box for symbol or key area
            if (this.mode === 'symbol' || this.settingKeyArea) {
                this.isDrawingBox = true;
                this.boxStart = img;
                this.currentBox = { x: img.x, y: img.y, w: 0, h: 0 };
                return;
            }
        },

        onMouseMove(e) {
            const rect = this.canvas.getBoundingClientRect();
            const sx = e.clientX - rect.left, sy = e.clientY - rect.top;

            if (this.isPanning) {
                const dx = e.clientX - this.panAnchorX, dy = e.clientY - this.panAnchorY;
                if (Math.abs(dx) > 3 || Math.abs(dy) > 3) this.didDrag = true;
                this.panX = this.panStartX + dx; this.panY = this.panStartY + dy;
                this.constrainPan();
                this.redraw();
                return;
            }

            if (this.isDrawingBox && this.boxStart) {
                const img = this.screenToImage(sx, sy);
                this.currentBox = {
                    x: Math.min(this.boxStart.x, img.x), y: Math.min(this.boxStart.y, img.y),
                    w: Math.abs(img.x - this.boxStart.x), h: Math.abs(img.y - this.boxStart.y),
                };
                this.redraw();
            }
        },

        onMouseUp(e) {
            if (this.isPanning) {
                this.isPanning = false;
                this.canvas.style.cursor = this.getCursor();
                return;
            }

            if (this.isDrawingBox && this.currentBox && this.currentBox.w > 10 && this.currentBox.h > 10) {
                if (this.settingKeyArea) {
                    this.keyArea = { ...this.currentBox };
                    this.settingKeyArea = false;
                    this.notify('Key area set — excluded from detection');
                } else if (this.mode === 'symbol') {
                    this.onSymbolBoxDrawn(this.currentBox);
                }
            }
            this.isDrawingBox = false; this.boxStart = null; this.currentBox = null; this.redraw();
        },

        onClick(e) {
            // Only fire for click modes (not handled by mousedown/up)
            if (this.isPanning || this.isDrawingBox) return;
            const rect = this.canvas.getBoundingClientRect();
            const img = this.screenToImage(e.clientX - rect.left, e.clientY - rect.top);

            // Manual placement mode — click to place a detection
            if (this.manualPlacingTemplate) {
                this.placeManualDetection(img);
                return;
            }

            // Select mode — check if clicking X on a detection box
            if (this.mode === 'select' && !this.didDrag) {
                const hit = this.findDetectionAt(img.x, img.y);
                if (hit) {
                    if (confirm(`Remove this ${hit.symbol_label || 'detection'}?`)) {
                        this.deleteDetection(hit);
                    }
                    return;
                }
            }

            if (this.mode === 'room' && this.drawingRoom) { this.roomPoints.push(img); this.redraw(); }
            if (this.mode === 'cable') { this.cablePoints.push(img); this.redraw(); }
            if (this.mode === 'area') { this.areaPoints.push(img); this.redraw(); }
            if (this.mode === 'scale') {
                this.scalePoints.push(img);
                if (this.scalePoints.length === 2) { this.showScaleModal = true; }
                this.redraw();
            }
        },

        // Attach click via canvas mouseup when not dragging
        // We need separate click handling for point-based tools
        handleCanvasClick(e) {
            if (this.didDrag) return;
            this.onClick(e);
        },

        onDoubleClick(e) {
            if (this.mode === 'room' && this.drawingRoom && this.roomPoints.length >= 3) this.finishRoom();
        },

        // ── Symbol Detection ─────────────────────────────────────
        onSymbolBoxDrawn(box) {
            this.pendingBox = { ...box };
            this.showProductModal = true;
            this.productSearch = ''; this.productResults = []; this.selectedProduct = null;
            this.$nextTick(() => { const el = document.getElementById('productSearchInput'); if (el) el.focus(); });
        },

        async confirmSymbolWithProduct() {
            if (!this.selectedProduct || !this.pendingBox) return;
            const box = this.pendingBox, product = this.selectedProduct;

            // Crop image
            const cc = document.createElement('canvas');
            cc.width = box.w; cc.height = box.h;
            cc.getContext('2d').drawImage(this.drawingImage, box.x, box.y, box.w, box.h, 0, 0, box.w, box.h);
            const cropB64 = cc.toDataURL('image/png');

            this.showProductModal = false;
            this.notify(`Creating "${product.name}"...`);

            try {
                const res = await fetch(`/quotebuilder/api/projects/${this.projectId}/documents/${this.documentId}/symbol-templates`, {
                    method: 'POST', headers: {'Content-Type':'application/json'},
                    body: JSON.stringify({ label: product.name, crop_x: Math.round(box.x), crop_y: Math.round(box.y), crop_w: Math.round(box.w), crop_h: Math.round(box.h), crop_image: cropB64 })
                });
                const data = await res.json();
                if (data.success) {
                    const tmpl = data.template;
                    this.symbolTemplates.push(tmpl);

                    // Link product
                    const linkResp = await fetch(`/quotebuilder/api/projects/${this.projectId}/link-product`, {
                        method: 'POST', headers: {'Content-Type':'application/json'},
                        body: JSON.stringify({ template_id: tmpl.id, product })
                    });
                    const linkData = await linkResp.json();
                    if (!linkData.success) {
                        console.error('Link product failed:', linkData);
                        this.notify('Product link failed: ' + (linkData.error || ''), 'error');
                    }

                    // Auto-detect
                    this.notify(`Scanning for "${product.name}"...`);
                    await this.runDetection(tmpl);

                    // Reload to get updated template with linked product info
                    await this.loadState();
                    this.redraw();
                }
            } catch (e) { this.notify('Error: ' + e.message, 'error'); }
            this.pendingBox = null;
        },

        cancelProductModal() {
            this.showProductModal = false; this.pendingBox = null;
            this.productSearch = ''; this.productResults = []; this.selectedProduct = null;
        },

        async runDetection(template) {
            this.detecting = true;
            this.detectingTemplateId = template.id;
            try {
                const res = await fetch(`/quotebuilder/api/projects/${this.projectId}/documents/${this.documentId}/detect-symbols`, {
                    method: 'POST', headers: {'Content-Type':'application/json'},
                    body: JSON.stringify({ template_id: template.id, exclude_area: this.keyArea, confidence_threshold: 0.65 })
                });
                const data = await res.json();
                if (data.success) {
                    this.detections = this.detections.filter(d => d.symbol_type_id !== template.symbol_type_id);
                    this.detections.push(...(data.detections || []));
                    const t = this.symbolTemplates.find(s => s.id === template.id);
                    if (t) t.total_found = data.count;
                    this.notify(`Found ${data.count} × ${template.label}`);
                    this.redraw();
                } else { this.notify('Detection failed: ' + (data.error||''), 'error'); }
            } catch (e) { this.notify('Detection error: ' + e.message, 'error'); }
            this.detecting = false;
            this.detectingTemplateId = null;
        },

        // ── Product Search ───────────────────────────────────────

        // ── Delete / Manual Add Detections ────────────────────────
        async deleteDetection(det) {
            try {
                const res = await fetch(`/quotebuilder/api/projects/${this.projectId}/detections/${det.id}`, {
                    method: 'DELETE'
                });
                const data = await res.json();
                if (data.success) {
                    this.detections = this.detections.filter(d => d.id !== det.id);
                    // Update template count
                    const tpl = this.symbolTemplates.find(t => t.symbol_type_id === det.symbol_type_id);
                    if (tpl) tpl.total_found = Math.max(0, (tpl.total_found || 1) - 1);
                    this.notify(`Removed ${det.symbol_label || 'detection'}`);
                    this.redraw();
                }
            } catch (e) { this.notify('Delete error: ' + e.message, 'error'); }
        },

        startManualPlace(tpl) {
            this.manualPlacingTemplate = tpl;
            this.mode = 'select'; // Stay in select mode but track we're placing
            this.notify(`Click on the drawing to place "${tpl.label}"`);
        },

        cancelManualPlace() {
            this.manualPlacingTemplate = null;
            this.notify('Manual placement cancelled');
        },

        async placeManualDetection(imgCoords) {
            const tpl = this.manualPlacingTemplate;
            if (!tpl) return;

            try {
                const res = await fetch(`/quotebuilder/api/projects/${this.projectId}/documents/${this.documentId}/detections`, {
                    method: 'POST', headers: {'Content-Type':'application/json'},
                    body: JSON.stringify({
                        symbol_type_id: tpl.symbol_type_id,
                        symbol_label: tpl.label,
                        x: Math.round(imgCoords.x),
                        y: Math.round(imgCoords.y),
                    })
                });
                const data = await res.json();
                if (data.success) {
                    this.detections.push(data.detection);
                    // Update template count
                    const t = this.symbolTemplates.find(s => s.symbol_type_id === tpl.symbol_type_id);
                    if (t) t.total_found = (t.total_found || 0) + 1;
                    this.notify(`Placed ${tpl.label} manually`);
                    this.redraw();
                    // Don't clear manualPlacingTemplate — allow placing multiple
                }
            } catch (e) { this.notify('Place error: ' + e.message, 'error'); }
        },

        // ── Detection hit test (for clicking X to delete) ─────────
        findDetectionAt(imgX, imgY) {
            for (const d of this.detections) {
                if (d.rejected) continue;
                const tpl = this.symbolTemplates.find(t => t.symbol_type_id === d.symbol_type_id);
                const w = tpl?.crop?.w || 40, h = tpl?.crop?.h || 40;
                // Check if click is on the X button (top-right corner of detection box)
                const xBtnX = d.x + w/2;
                const xBtnY = d.y - h/2;
                const xBtnRadius = Math.max(12, w * 0.2);
                const dist = Math.sqrt((imgX - xBtnX)**2 + (imgY - xBtnY)**2);
                if (dist < xBtnRadius / this.zoom + 5) return d;
            }
            return null;
        },
        async searchProducts() {
            if (this.productSearch.length < 2) { this.productResults = []; return; }
            this.productSearching = true;
            try {
                const r = await fetch(`/quotebuilder/api/products/search?q=${encodeURIComponent(this.productSearch)}`);
                const d = await r.json();
                this.productResults = d.products || [];
            } catch (e) { this.productResults = []; }
            this.productSearching = false;
        },

        // Link from sidebar (existing template)
        openLinkProduct(tpl) {
            this.linkingTemplate = tpl;
            this.productSearch = ''; this.productResults = [];
        },

        async linkProduct(tpl, product) {
            try {
                const resp = await fetch(`/quotebuilder/api/projects/${this.projectId}/link-product`, {
                    method: 'POST', headers: {'Content-Type':'application/json'},
                    body: JSON.stringify({ template_id: tpl.id, product })
                });
                const data = await resp.json();
                if (data.success) {
                    this.notify(`Linked ${product.sku || product.name} to ${tpl.label}`);
                } else {
                    this.notify('Link failed: ' + (data.error || 'Unknown error'), 'error');
                    console.error('Link product failed:', data);
                }
                this.linkingTemplate = null;
                this.productSearch = '';
                this.productResults = [];
                await this.loadState();
                this.redraw();
            } catch (e) {
                this.notify('Link error: ' + e.message, 'error');
                console.error('Link product exception:', e);
            }
        },

        // ── Scale ────────────────────────────────────────────────
        async saveScale() {
            const dist = parseFloat(this.scaleRealDistance);
            if (!dist || dist <= 0 || this.scalePoints.length !== 2) return;
            const [p1,p2] = this.scalePoints;
            // These are already in image pixel coords (zoom-independent)
            const pxDist = Math.sqrt(Math.pow(p2.x-p1.x,2)+Math.pow(p2.y-p1.y,2));
            this.scale = pxDist / dist;
            try {
                await fetch(`/quotebuilder/api/projects/${this.projectId}/documents/${this.documentId}/scale`, {
                    method:'POST', headers:{'Content-Type':'application/json'},
                    body: JSON.stringify({pixel_distance: pxDist, real_distance: dist})
                });
                this.scaleCalibrated = true; this.notify('Scale calibrated: ' + Math.round(this.scale) + ' px/m');
            } catch(e) { this.notify('Failed to save scale','error'); }
            this.showScaleModal = false; this.scalePoints = []; this.scaleRealDistance = ''; this.redraw();
        },

        async autoScale(scaleRatio, paperSize, orientation) {
            // Calculate scale from drawing notation like "1:35 @ A1"
            try {
                const r = await fetch(`/quotebuilder/api/projects/${this.projectId}/documents/${this.documentId}/auto-scale`, {
                    method: 'POST', headers: {'Content-Type':'application/json'},
                    body: JSON.stringify({scale_ratio: scaleRatio, paper_size: paperSize, orientation: orientation || 'landscape'})
                });
                const d = await r.json();
                if (d.success) {
                    this.scale = d.px_per_metre;
                    this.scaleCalibrated = true;
                    this.showAutoScaleModal = false;
                    this.notify(`Scale set: ${d.description} (${d.px_per_metre} px/m)`);
                    this.redraw();
                } else {
                    this.notify(d.error || 'Auto-scale failed', 'error');
                }
            } catch(e) { this.notify('Auto-scale error: ' + e.message, 'error'); }
        },

        // ── Rooms ────────────────────────────────────────────────
        startDrawingRoom() { this.mode = 'room'; this.drawingRoom = true; this.roomPoints = []; },

        async finishRoom() {
            if (this.roomPoints.length < 3) return;
            const name = prompt('Name this room (e.g. "Kitchen", "Bedroom 1"):');
            if (!name) { this.roomPoints = []; this.drawingRoom = false; return; }
            try {
                const r = await fetch(`/quotebuilder/api/projects/${this.projectId}/documents/${this.documentId}/rooms`, {
                    method:'POST', headers:{'Content-Type':'application/json'},
                    body: JSON.stringify({name, boundary_points: this.roomPoints})
                });
                const d = await r.json();
                if (d.success) { this.rooms.push(d.room); this.notify(`Room "${name}" created`); await this.loadState(); }
            } catch(e) { this.notify('Error: '+e.message,'error'); }
            this.roomPoints = []; this.drawingRoom = false; this.redraw();
        },

        cancelRoom() { this.roomPoints = []; this.drawingRoom = false; this.redraw(); },

        async deleteRoom(roomId) {
            if (!confirm('Delete this room?')) return;
            try {
                await fetch(`/quotebuilder/api/projects/${this.projectId}/rooms/${roomId}`, {method:'DELETE'});
                this.rooms = this.rooms.filter(r=>r.id!==roomId);
                await this.loadState(); this.redraw(); this.notify('Room deleted');
            } catch(e) { this.notify('Error','error'); }
        },

        getRoomDetectionCount(room) { return this.detections.filter(d=>d.room_id===room.id).length; },

        // ── Cables ───────────────────────────────────────────────
        async finishCableRun() {
            if (this.cablePoints.length < 2) return;
            const label = this.cableTypes.find(c=>c.value===this.cableType)?.label || this.cableType;
            try {
                const r = await fetch(`/quotebuilder/api/projects/${this.projectId}/documents/${this.documentId}/cable-runs`, {
                    method:'POST', headers:{'Content-Type':'application/json'},
                    body: JSON.stringify({cable_type: this.cableType, cable_label: label, route_points: this.cablePoints, waste_percent: 10})
                });
                const d = await r.json();
                if (d.success) { this.cableRuns.push(d.cable_run); this.notify(`Cable: ${d.cable_run.length_metres||0}m ${label}`); }
            } catch(e) { this.notify('Error','error'); }
            this.cablePoints = []; this.redraw();
        },

        undoLastCablePoint() { this.cablePoints.pop(); this.redraw(); },

        // ── Areas ────────────────────────────────────────────────
        async finishArea() {
            if (this.areaPoints.length < 3) return;
            try {
                const r = await fetch(`/quotebuilder/api/projects/${this.projectId}/documents/${this.documentId}/areas`, {
                    method:'POST', headers:{'Content-Type':'application/json'},
                    body: JSON.stringify({points: this.areaPoints, label: `Area ${this.areas.length+1}`})
                });
                const d = await r.json();
                if (d.success) { this.areas.push(d.area); this.notify(`Area: ${d.area.area_sqm}m²`); }
            } catch(e) { this.notify('Error','error'); }
            this.areaPoints = []; this.redraw();
        },

        // ── Helpers ──────────────────────────────────────────────
        notify(msg, type) {
            this.notification = {msg, type: type||'success'};
            clearTimeout(this.notificationTimeout);
            this.notificationTimeout = setTimeout(()=>this.notification=null, 4000);
        },

        setMode(m) {
            this.mode = m; this.cablePoints = []; this.areaPoints = []; this.roomPoints = [];
            this.scalePoints = []; this.drawingRoom = false; this.isDrawingBox = false;
            this.settingKeyArea = false; this.redraw();
        },

        getCursor() {
            if (this.manualPlacingTemplate) return 'crosshair';
            if (this.mode === 'symbol' || this.settingKeyArea) return 'crosshair';
            if (this.mode === 'room' && this.drawingRoom) return 'crosshair';
            if (this.mode === 'cable' || this.mode === 'area' || this.mode === 'scale') return 'crosshair';
            return this.isPanning ? 'grabbing' : 'grab';
        },

        getDetectionsByRoom() {
            const g = {};
            this.rooms.forEach(r => { g[r.id] = {room: r, detections: this.detections.filter(d=>d.room_id===r.id)}; });
            const u = this.detections.filter(d=>!d.room_id);
            if (u.length > 0) g['unassigned'] = {room:{id:null,name:'Unassigned'}, detections: u};
            return g;
        },

        groupDetections(dets) {
            const g = {};
            dets.forEach(d => {
                if (!g[d.symbol_type_id]) {
                    const tpl = this.symbolTemplates.find(t=>t.symbol_type_id===d.symbol_type_id);
                    g[d.symbol_type_id] = {label:d.symbol_label, part_number:tpl?.default_part_number||'-', unit_cost:tpl?.default_unit_cost||0, unit_sell:tpl?.default_unit_sell||0, count:0};
                }
                g[d.symbol_type_id].count++;
            });
            return Object.values(g);
        },

        getCableRunSummary() {
            const s = {};
            this.cableTypes.forEach(ct => {
                const runs = this.cableRuns.filter(r=>r.cable_type===ct.value);
                if (runs.length > 0) s[ct.value] = {label:ct.label, color:ct.color, runs:runs.length, totalMetres:runs.reduce((a,r)=>a+(r.total_metres||r.length_metres||0),0)};
            });
            return s;
        },

        // ── Render ───────────────────────────────────────────────
        redraw() {
            if (!this.ctx || !this.drawingLoaded) return;
            const c = this.canvas.parentElement;
            const cw = c.clientWidth, ch = c.clientHeight;
            this.canvas.width = cw; this.canvas.height = ch;
            const ctx = this.ctx;

            ctx.fillStyle = '#111827'; ctx.fillRect(0, 0, cw, ch);
            ctx.save();
            ctx.translate(this.panX, this.panY);
            ctx.scale(this.zoom, this.zoom);

            // Drawing image
            ctx.drawImage(this.drawingImage, 0, 0);
            const lw = (v) => v / this.zoom;

            // Rooms
            for (const room of this.rooms) {
                const pts = room.boundary_points || room.points || [];
                if (pts.length < 3) continue;
                const hl = this.highlightedRoom === room.id;
                ctx.beginPath(); ctx.moveTo(pts[0].x, pts[0].y);
                pts.slice(1).forEach(p=>ctx.lineTo(p.x,p.y)); ctx.closePath();
                ctx.fillStyle = hl ? 'rgba(99,102,241,0.15)' : 'rgba(99,102,241,0.05)';
                ctx.fill();
                ctx.strokeStyle = hl ? '#818cf8' : '#6366f1';
                ctx.lineWidth = lw(hl?3:1.5); ctx.stroke();
                const cx = pts.reduce((s,p)=>s+p.x,0)/pts.length;
                const cy = pts.reduce((s,p)=>s+p.y,0)/pts.length;
                ctx.fillStyle = '#fff'; ctx.font = `bold ${lw(12)}px system-ui`;
                ctx.textAlign = 'center'; ctx.textBaseline = 'middle';
                ctx.fillText(room.name, cx, cy);
            }

            // Room points being drawn
            if (this.roomPoints.length) {
                ctx.strokeStyle = '#6366f1'; ctx.lineWidth = lw(2);
                ctx.setLineDash([lw(4),lw(4)]);
                ctx.beginPath(); ctx.moveTo(this.roomPoints[0].x, this.roomPoints[0].y);
                this.roomPoints.slice(1).forEach(p=>ctx.lineTo(p.x,p.y));
                if (this.roomPoints.length > 2) { ctx.lineTo(this.roomPoints[0].x,this.roomPoints[0].y); ctx.fillStyle='rgba(99,102,241,0.08)'; ctx.fill(); }
                ctx.stroke(); ctx.setLineDash([]);
                this.roomPoints.forEach(p=>{ctx.fillStyle='#6366f1';ctx.beginPath();ctx.arc(p.x,p.y,lw(4),0,Math.PI*2);ctx.fill();});
            }

            // Detections
            for (const d of this.detections) {
                if (d.rejected) continue;
                const tpl = this.symbolTemplates.find(t=>t.symbol_type_id===d.symbol_type_id);
                const w = tpl?.crop?.w || d.w || 40;
                const h = tpl?.crop?.h || d.h || 40;
                const col = tpl?.color || '#4ade80';
                // Box outline
                ctx.strokeStyle = col; ctx.lineWidth = lw(3);
                ctx.strokeRect(d.x-w/2, d.y-h/2, w, h);
                // Semi-transparent fill
                ctx.fillStyle = col.slice(0,7) + '30';
                ctx.fillRect(d.x-w/2, d.y-h/2, w, h);
                // Label badge
                const label = d.symbol_label || '?';
                ctx.font = `bold ${lw(11)}px system-ui`;
                const tw = ctx.measureText(label).width + lw(10);
                ctx.fillStyle = col;
                ctx.fillRect(d.x-w/2, d.y-h/2-lw(16), tw, lw(15));
                ctx.fillStyle = '#fff'; ctx.textAlign = 'left'; ctx.textBaseline = 'top';
                ctx.fillText(label, d.x-w/2+lw(5), d.y-h/2-lw(15));
                // X delete button (top-right corner)
                const xR = lw(8);
                const xCx = d.x + w/2, xCy = d.y - h/2;
                ctx.fillStyle = '#ef4444';
                ctx.beginPath(); ctx.arc(xCx, xCy, xR, 0, Math.PI*2); ctx.fill();
                ctx.strokeStyle = '#fff'; ctx.lineWidth = lw(2);
                ctx.beginPath(); ctx.moveTo(xCx-xR*0.5, xCy-xR*0.5); ctx.lineTo(xCx+xR*0.5, xCy+xR*0.5); ctx.stroke();
                ctx.beginPath(); ctx.moveTo(xCx+xR*0.5, xCy-xR*0.5); ctx.lineTo(xCx-xR*0.5, xCy+xR*0.5); ctx.stroke();
            }

            // Cable runs
            for (const run of this.cableRuns) {
                const pts = run.route_points || run.points || [];
                if (pts.length < 2) continue;
                const col = this.cableTypes.find(t=>t.value===run.cable_type)?.color || '#3b82f6';
                ctx.strokeStyle = col; ctx.lineWidth = lw(3);
                ctx.beginPath(); ctx.moveTo(pts[0].x,pts[0].y);
                pts.slice(1).forEach(p=>ctx.lineTo(p.x,p.y)); ctx.stroke();
                pts.forEach(p=>{ctx.fillStyle=col;ctx.beginPath();ctx.arc(p.x,p.y,lw(3),0,Math.PI*2);ctx.fill();});
            }

            // Cable points being drawn
            if (this.cablePoints.length) {
                const col = this.cableTypes.find(t=>t.value===this.cableType)?.color || '#3b82f6';
                ctx.strokeStyle = col; ctx.lineWidth = lw(2);
                ctx.setLineDash([lw(4),lw(4)]);
                ctx.beginPath(); ctx.moveTo(this.cablePoints[0].x,this.cablePoints[0].y);
                this.cablePoints.slice(1).forEach(p=>ctx.lineTo(p.x,p.y)); ctx.stroke(); ctx.setLineDash([]);
                this.cablePoints.forEach(p=>{ctx.fillStyle=col;ctx.beginPath();ctx.arc(p.x,p.y,lw(4),0,Math.PI*2);ctx.fill();});
            }

            // Areas
            for (const area of this.areas) {
                const pts = area.points; if (!pts || pts.length < 3) continue;
                ctx.fillStyle = 'rgba(139,92,246,0.06)'; ctx.strokeStyle = 'rgba(139,92,246,0.4)'; ctx.lineWidth = lw(1);
                ctx.beginPath(); ctx.moveTo(pts[0].x,pts[0].y); pts.slice(1).forEach(p=>ctx.lineTo(p.x,p.y));
                ctx.closePath(); ctx.fill(); ctx.stroke();
                if (area.area_sqm) {
                    const cx = pts.reduce((s,p)=>s+p.x,0)/pts.length, cy = pts.reduce((s,p)=>s+p.y,0)/pts.length;
                    const lb = `${area.area_sqm}m²`;
                    ctx.font = `bold ${lw(12)}px system-ui`;
                    const tw2 = ctx.measureText(lb).width + lw(10);
                    ctx.fillStyle = 'rgba(139,92,246,0.85)'; ctx.fillRect(cx-tw2/2,cy-lw(9),tw2,lw(20));
                    ctx.fillStyle = '#fff'; ctx.textAlign = 'center'; ctx.textBaseline = 'middle'; ctx.fillText(lb,cx,cy+lw(1));
                }
            }

            // Area points being drawn
            if (this.areaPoints.length) {
                ctx.strokeStyle = '#8b5cf6'; ctx.lineWidth = lw(2); ctx.setLineDash([lw(4),lw(4)]);
                ctx.beginPath(); ctx.moveTo(this.areaPoints[0].x,this.areaPoints[0].y);
                this.areaPoints.slice(1).forEach(p=>ctx.lineTo(p.x,p.y));
                if (this.areaPoints.length > 2) { ctx.lineTo(this.areaPoints[0].x,this.areaPoints[0].y); ctx.fillStyle='rgba(139,92,246,0.08)'; ctx.fill(); }
                ctx.stroke(); ctx.setLineDash([]);
                this.areaPoints.forEach(p=>{ctx.fillStyle='#8b5cf6';ctx.beginPath();ctx.arc(p.x,p.y,lw(4),0,Math.PI*2);ctx.fill();});
            }

            // Key area
            if (this.keyArea) {
                ctx.strokeStyle = '#ef4444'; ctx.lineWidth = lw(2); ctx.setLineDash([lw(8),lw(4)]);
                ctx.strokeRect(this.keyArea.x,this.keyArea.y,this.keyArea.w,this.keyArea.h);
                ctx.setLineDash([]); ctx.fillStyle = 'rgba(239,68,68,0.05)';
                ctx.fillRect(this.keyArea.x,this.keyArea.y,this.keyArea.w,this.keyArea.h);
                ctx.fillStyle = '#ef4444'; ctx.font = `bold ${lw(11)}px system-ui`;
                ctx.textAlign = 'center'; ctx.textBaseline = 'bottom';
                ctx.fillText('KEY (excluded)', this.keyArea.x+this.keyArea.w/2, this.keyArea.y-lw(4));
            }

            // Current box
            if (this.currentBox) {
                ctx.strokeStyle = this.settingKeyArea ? '#ef4444' : '#6366f1';
                ctx.lineWidth = lw(2); ctx.setLineDash([lw(6),lw(3)]);
                ctx.strokeRect(this.currentBox.x,this.currentBox.y,this.currentBox.w,this.currentBox.h);
                ctx.setLineDash([]);
                ctx.fillStyle = this.settingKeyArea ? 'rgba(239,68,68,0.08)' : 'rgba(99,102,241,0.08)';
                ctx.fillRect(this.currentBox.x,this.currentBox.y,this.currentBox.w,this.currentBox.h);
            }

            // Scale points
            for (const p of this.scalePoints) {
                ctx.fillStyle='#10b981'; ctx.beginPath(); ctx.arc(p.x,p.y,lw(6),0,Math.PI*2); ctx.fill();
                ctx.strokeStyle='#fff'; ctx.lineWidth=lw(2); ctx.stroke();
            }
            if (this.scalePoints.length===2) {
                ctx.strokeStyle='#10b981'; ctx.lineWidth=lw(2); ctx.setLineDash([lw(4),lw(4)]);
                ctx.beginPath(); ctx.moveTo(this.scalePoints[0].x,this.scalePoints[0].y);
                ctx.lineTo(this.scalePoints[1].x,this.scalePoints[1].y); ctx.stroke(); ctx.setLineDash([]);
            }

            ctx.restore();
        },
    };
}
