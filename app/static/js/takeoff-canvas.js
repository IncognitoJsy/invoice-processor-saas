/**
 * GoZappify Takeoff Canvas V6
 * V1 layout (drawing left, panels right) + zoom/pan + QB/Xero product search
 */

function takeoffCanvas(projectId, documentId) {
    return {
        projectId,
        documentId,
        loading: true,
        error: null,

        canvas: null,
        ctx: null,
        drawingImage: null,
        drawingLoaded: false,

        // Zoom/Pan — image always renders within the canvas box
        zoom: 1,
        panX: 0,
        panY: 0,
        isPanning: false,
        panAnchorX: 0,
        panAnchorY: 0,
        panStartX: 0,
        panStartY: 0,
        didDrag: false,

        // Scale
        scaleCalibrated: false,
        pxPerMetre: 50,
        scalePoints: [],
        showScaleModal: false,
        scaleRealDistance: '',

        // Mode
        mode: 'select',

        // Symbol box
        isDrawingBox: false,
        boxStart: null,
        currentBox: null,

        // Product search
        showProductModal: false,
        productQuery: '',
        productResults: [],
        productSearching: false,
        selectedProduct: null,
        pendingBox: null,

        // Data
        symbolTemplates: [],
        detections: [],
        detecting: false,
        selectedDetection: null,
        rooms: [],
        roomPoints: [],
        showRoomNameModal: false,
        roomName: '',
        activeRoom: null,
        cableRuns: [],
        cablePoints: [],
        cableType: 'socket',
        cableTypes: [
            { value: 'lighting', label: '1.5mm T&E (Lighting)', color: '#fbbf24' },
            { value: 'socket', label: '2.5mm T&E (Sockets)', color: '#3b82f6' },
            { value: 'cooker', label: '6mm T&E (Cooker)', color: '#ef4444' },
            { value: 'shower', label: '10mm T&E (Shower)', color: '#8b5cf6' },
            { value: 'data', label: 'Cat6 Data', color: '#10b981' },
        ],
        notification: null,
        notifTimeout: null,

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

        notify(msg, type) {
            this.notification = { msg, type: type || 'info' };
            clearTimeout(this.notifTimeout);
            this.notifTimeout = setTimeout(() => this.notification = null, 4000);
        },

        // ── Load ─────────────────────────────────────────────────
        async loadDrawing() {
            return new Promise((resolve, reject) => {
                this.drawingImage = new Image();
                this.drawingImage.onload = () => {
                    this.drawingLoaded = true;
                    resolve();
                };
                this.drawingImage.onerror = () => { this.error = 'Failed to load drawing'; reject(); };
                this.drawingImage.src = `/quotebuilder/api/projects/${this.projectId}/documents/${this.documentId}/render`;
            });
        },

        async loadState() {
            try {
                const res = await fetch(`/quotebuilder/api/projects/${this.projectId}/documents/${this.documentId}/takeoff-state`);
                const data = await res.json();
                if (data.success) {
                    this.symbolTemplates = data.symbol_templates || [];
                    this.detections = data.detections || [];
                    this.rooms = data.rooms || [];
                    this.cableRuns = data.cable_runs || [];
                    if (data.scale && data.scale > 0) { this.pxPerMetre = data.scale; this.scaleCalibrated = true; }
                }
            } catch (e) { console.error('Load state error:', e); }
        },

        // ── Events ───────────────────────────────────────────────
        setupEvents() {
            this.canvas.addEventListener('wheel', (e) => {
                e.preventDefault();
                const rect = this.canvas.getBoundingClientRect();
                const mx = e.clientX - rect.left;
                const my = e.clientY - rect.top;
                const factor = e.deltaY < 0 ? 1.15 : 0.87;
                const newZoom = Math.max(0.1, Math.min(15, this.zoom * factor));
                const scale = newZoom / this.zoom;
                this.panX = mx - (mx - this.panX) * scale;
                this.panY = my - (my - this.panY) * scale;
                this.zoom = newZoom;
                this.redraw();
            }, { passive: false });

            document.addEventListener('keydown', (e) => {
                if (e.target.tagName === 'INPUT' || e.target.tagName === 'TEXTAREA') return;
                if (e.key === 'Escape') this.cancelAction();
                if (e.key === '0') this.fitToScreen();
                if (e.key === 'Delete' && this.selectedDetection) this.deleteDetection(this.selectedDetection);
            });

            // Resize canvas when window resizes
            window.addEventListener('resize', () => this.redraw());
        },

        fitToScreen() {
            if (!this.drawingImage || !this.canvas) return;
            const container = this.canvas.parentElement;
            const cw = container.clientWidth;
            const ch = container.clientHeight;
            const sx = cw / this.drawingImage.width;
            const sy = ch / this.drawingImage.height;
            this.zoom = Math.min(sx, sy) * 0.95;
            this.panX = (cw - this.drawingImage.width * this.zoom) / 2;
            this.panY = (ch - this.drawingImage.height * this.zoom) / 2;
            this.redraw();
        },

        screenToImage(sx, sy) {
            return { x: (sx - this.panX) / this.zoom, y: (sy - this.panY) / this.zoom };
        },

        // ── Mouse ────────────────────────────────────────────────
        onMouseDown(e) {
            const rect = this.canvas.getBoundingClientRect();
            const sx = e.clientX - rect.left;
            const sy = e.clientY - rect.top;
            const img = this.screenToImage(sx, sy);
            this.didDrag = false;

            if (this.mode === 'select') {
                this.isPanning = true;
                this.panAnchorX = e.clientX; this.panAnchorY = e.clientY;
                this.panStartX = this.panX; this.panStartY = this.panY;
                this.canvas.style.cursor = 'grabbing';
                return;
            }
            if (this.mode === 'symbol') { this.isDrawingBox = true; this.boxStart = img; this.currentBox = null; return; }
            if (this.mode === 'scale') {
                this.scalePoints.push(img);
                if (this.scalePoints.length === 2) { this.showScaleModal = true; this.mode = 'select'; }
                this.redraw(); return;
            }
            if (this.mode === 'room') { this.roomPoints.push(img); this.redraw(); return; }
            if (this.mode === 'cable') { this.cablePoints.push(img); this.redraw(); return; }
        },

        onMouseMove(e) {
            const rect = this.canvas.getBoundingClientRect();
            const sx = e.clientX - rect.left;
            const sy = e.clientY - rect.top;
            if (this.isPanning) {
                const dx = e.clientX - this.panAnchorX;
                const dy = e.clientY - this.panAnchorY;
                if (Math.abs(dx) > 3 || Math.abs(dy) > 3) this.didDrag = true;
                this.panX = this.panStartX + dx;
                this.panY = this.panStartY + dy;
                this.redraw(); return;
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
                this.canvas.style.cursor = this.mode === 'select' ? 'grab' : 'crosshair';
                if (!this.didDrag) {
                    const rect = this.canvas.getBoundingClientRect();
                    const img = this.screenToImage(e.clientX - rect.left, e.clientY - rect.top);
                    this.handleSelectClick(img);
                }
                return;
            }
            if (this.isDrawingBox && this.currentBox && this.currentBox.w > 10 && this.currentBox.h > 10) {
                this.isDrawingBox = false;
                this.pendingBox = { ...this.currentBox };
                this.openProductSearch();
                return;
            }
            this.isDrawingBox = false; this.currentBox = null;
        },

        handleSelectClick(img) {
            const det = this.detections.find(d => {
                const w = d.crop?.w || 40, h = d.crop?.h || 40;
                return img.x >= d.x-w/2 && img.x <= d.x+w/2 && img.y >= d.y-h/2 && img.y <= d.y+h/2;
            });
            if (det) { this.selectedDetection = det; this.redraw(); return; }

            const room = this.rooms.find(r => {
                const pts = r.boundary_points || r.points || [];
                return pts.length >= 3 && this.pointInPoly(img, pts);
            });
            if (room) { this.activeRoom = room; this.zoomToRoom(room); return; }

            this.selectedDetection = null; this.activeRoom = null; this.redraw();
        },

        pointInPoly(pt, poly) {
            let inside = false;
            for (let i = 0, j = poly.length - 1; i < poly.length; j = i++) {
                const xi = poly[i].x, yi = poly[i].y, xj = poly[j].x, yj = poly[j].y;
                if (((yi > pt.y) !== (yj > pt.y)) && (pt.x < (xj-xi)*(pt.y-yi)/(yj-yi)+xi)) inside = !inside;
            }
            return inside;
        },

        zoomToRoom(room) {
            const pts = room.boundary_points || room.points || [];
            if (pts.length < 3) return;
            const xs = pts.map(p=>p.x), ys = pts.map(p=>p.y);
            const container = this.canvas.parentElement;
            const cw = container.clientWidth, ch = container.clientHeight;
            const minX = Math.min(...xs), maxX = Math.max(...xs), minY = Math.min(...ys), maxY = Math.max(...ys);
            this.zoom = Math.min(cw / (maxX-minX+200), ch / (maxY-minY+200), 8);
            this.panX = cw/2 - ((minX+maxX)/2)*this.zoom;
            this.panY = ch/2 - ((minY+maxY)/2)*this.zoom;
            this.redraw();
        },

        // ── Helpers ──────────────────────────────────────────────
        getRoomDetectionCount(room) {
            return this.detections.filter(d => d.room_id === room.id).length;
        },

        getSummary() {
            const m = {};
            for (const d of this.detections) {
                const k = d.symbol_label || d.template_name || 'Unknown';
                if (!m[k]) m[k] = { name: k, count: 0, part: d.part_number };
                m[k].count++;
            }
            return Object.values(m);
        },

        getTotalCableLength() {
            return this.cableRuns.reduce((s, c) => s + (c.length_metres || c.total_length_m || 0), 0);
        },

        // ── Mode ─────────────────────────────────────────────────
        setMode(m) { this.cancelAction(); this.mode = m; this.canvas.style.cursor = m === 'select' ? 'grab' : 'crosshair'; },
        cancelAction() {
            this.mode = 'select'; this.isDrawingBox = false; this.currentBox = null; this.boxStart = null;
            this.roomPoints = []; this.cablePoints = []; this.scalePoints = []; this.selectedDetection = null;
            this.canvas.style.cursor = 'grab'; this.redraw();
        },

        // ── Product Search ───────────────────────────────────────
        openProductSearch() {
            this.showProductModal = true; this.productQuery = ''; this.productResults = [];
            this.selectedProduct = null; this.productSearching = false;
            this.$nextTick(() => { const el = document.getElementById('productSearchInput'); if (el) el.focus(); });
        },

        async searchProducts() {
            if (this.productQuery.length < 2) { this.productResults = []; return; }
            this.productSearching = true;
            try {
                const res = await fetch(`/quotebuilder/api/products/search?q=${encodeURIComponent(this.productQuery)}`);
                const data = await res.json();
                this.productResults = data.products || [];
            } catch (e) { this.productResults = []; }
            this.productSearching = false;
        },

        selectProduct(p) { this.selectedProduct = p; },

        async confirmSymbolTemplate() {
            if (!this.selectedProduct || !this.pendingBox) return;
            const box = this.pendingBox, product = this.selectedProduct;

            // Crop symbol
            const cc = document.createElement('canvas');
            cc.width = box.w; cc.height = box.h;
            cc.getContext('2d').drawImage(this.drawingImage, box.x, box.y, box.w, box.h, 0, 0, box.w, box.h);
            const cropB64 = cc.toDataURL('image/png');

            this.showProductModal = false;
            this.notify('Creating template...', 'info');

            try {
                const res = await fetch(`/quotebuilder/api/projects/${this.projectId}/documents/${this.documentId}/symbol-templates`, {
                    method: 'POST', headers: {'Content-Type':'application/json'},
                    body: JSON.stringify({ label: product.name, crop_x: Math.round(box.x), crop_y: Math.round(box.y), crop_w: Math.round(box.w), crop_h: Math.round(box.h), crop_image: cropB64 })
                });
                const data = await res.json();
                if (data.success) {
                    const tmpl = data.template;
                    this.symbolTemplates.push(tmpl);
                    await fetch(`/quotebuilder/api/projects/${this.projectId}/link-product`, {
                        method: 'POST', headers: {'Content-Type':'application/json'},
                        body: JSON.stringify({ template_id: tmpl.id, product })
                    });
                    this.notify(`Scanning for "${product.name}"...`, 'info');
                    await this.runDetection(tmpl);
                }
            } catch (e) { this.notify('Error: ' + e.message, 'error'); }

            this.pendingBox = null; this.currentBox = null; this.mode = 'select'; this.canvas.style.cursor = 'grab';
        },

        async runDetection(tmpl) {
            this.detecting = true;
            try {
                const res = await fetch(`/quotebuilder/api/projects/${this.projectId}/documents/${this.documentId}/detect-symbols`, {
                    method: 'POST', headers: {'Content-Type':'application/json'},
                    body: JSON.stringify({ template_id: tmpl.id, confidence_threshold: 0.65 })
                });
                const data = await res.json();
                if (data.success) {
                    this.detections = this.detections.filter(d => d.symbol_type_id !== tmpl.symbol_type_id);
                    this.detections.push(...(data.detections || []));
                    // Update template count
                    const t = this.symbolTemplates.find(s => s.id === tmpl.id);
                    if (t) t.total_found = data.count;
                    this.notify(`Found ${data.count} × ${tmpl.label}`, 'success');
                } else { this.notify(data.error || 'Detection failed', 'error'); }
            } catch (e) { this.notify('Detection error: ' + e.message, 'error'); }
            this.detecting = false; this.redraw();
        },

        cancelProductModal() { this.showProductModal = false; this.pendingBox = null; this.currentBox = null; this.redraw(); },

        // ── Scale ────────────────────────────────────────────────
        startScale() { this.scalePoints = []; this.mode = 'scale'; this.canvas.style.cursor = 'crosshair'; this.notify('Click two points of known distance', 'info'); },

        async saveScale() {
            const dist = parseFloat(this.scaleRealDistance);
            if (!dist || dist <= 0 || this.scalePoints.length !== 2) return;
            const [p1,p2] = this.scalePoints;
            const pxDist = Math.sqrt(Math.pow(p2.x-p1.x,2)+Math.pow(p2.y-p1.y,2));
            this.pxPerMetre = pxDist / dist;
            try {
                await fetch(`/quotebuilder/api/projects/${this.projectId}/documents/${this.documentId}/scale`, {
                    method:'POST', headers:{'Content-Type':'application/json'},
                    body: JSON.stringify({pixel_distance: pxDist, real_distance: dist})
                });
                this.scaleCalibrated = true; this.notify('Scale calibrated', 'success');
            } catch(e) { this.notify('Failed to save scale','error'); }
            this.showScaleModal = false; this.scalePoints = []; this.scaleRealDistance = ''; this.redraw();
        },

        // ── Rooms ────────────────────────────────────────────────
        finishRoom() { if (this.roomPoints.length >= 3) this.showRoomNameModal = true; },
        async saveRoom() {
            if (!this.roomName || this.roomPoints.length < 3) return;
            try {
                const res = await fetch(`/quotebuilder/api/projects/${this.projectId}/documents/${this.documentId}/rooms`, {
                    method:'POST', headers:{'Content-Type':'application/json'},
                    body: JSON.stringify({name: this.roomName, boundary_points: this.roomPoints})
                });
                const data = await res.json();
                if (data.success) { this.rooms.push(data.room); this.notify(`Room "${this.roomName}" created`, 'success'); }
            } catch(e) { this.notify('Failed to create room','error'); }
            this.showRoomNameModal = false; this.roomName = ''; this.roomPoints = []; this.mode = 'select'; this.canvas.style.cursor = 'grab'; this.redraw();
        },
        exitRoom() { this.activeRoom = null; this.fitToScreen(); },

        // ── Cables ───────────────────────────────────────────────
        async finishCable() {
            if (this.cablePoints.length < 2) return;
            try {
                const res = await fetch(`/quotebuilder/api/projects/${this.projectId}/documents/${this.documentId}/cable-runs`, {
                    method:'POST', headers:{'Content-Type':'application/json'},
                    body: JSON.stringify({route_points: this.cablePoints, cable_type: this.cableType, room_id: this.activeRoom?.id||null, waste_percent:10})
                });
                const data = await res.json();
                if (data.success) {
                    this.cableRuns.push(data.cable_run);
                    const len = data.cable_run.length_metres || data.cable_run.total_length_m;
                    this.notify(`Cable: ${len?len.toFixed(2)+'m':'saved'}`, 'success');
                }
            } catch(e) { this.notify('Failed to save cable','error'); }
            this.cablePoints = []; this.redraw();
        },

        // ── Detections ───────────────────────────────────────────
        async deleteDetection(det) {
            if (!confirm('Delete this detection?')) return;
            try {
                await fetch(`/quotebuilder/api/projects/${this.projectId}/detections/${det.id}`, {method:'DELETE'});
                this.detections = this.detections.filter(d=>d.id!==det.id);
                this.selectedDetection = null; this.notify('Deleted','info'); this.redraw();
            } catch(e) { this.notify('Failed','error'); }
        },

        // ── Render ───────────────────────────────────────────────
        redraw() {
            if (!this.ctx || !this.drawingLoaded) return;
            const container = this.canvas.parentElement;
            const cw = container.clientWidth, ch = container.clientHeight;
            this.canvas.width = cw; this.canvas.height = ch;
            const ctx = this.ctx;

            ctx.fillStyle = '#0f0f1a'; ctx.fillRect(0, 0, cw, ch);
            ctx.save();
            ctx.translate(this.panX, this.panY);
            ctx.scale(this.zoom, this.zoom);

            // Drawing
            ctx.drawImage(this.drawingImage, 0, 0);

            const lw = (v) => v / this.zoom;

            // Rooms
            for (const room of this.rooms) {
                const pts = room.boundary_points || room.points || [];
                if (pts.length < 3) continue;
                const active = this.activeRoom?.id === room.id;
                ctx.beginPath(); ctx.moveTo(pts[0].x, pts[0].y);
                pts.slice(1).forEach(p => ctx.lineTo(p.x, p.y)); ctx.closePath();
                ctx.fillStyle = active ? 'rgba(99,102,241,0.15)' : 'rgba(99,102,241,0.05)';
                ctx.fill();
                ctx.strokeStyle = active ? '#818cf8' : '#6366f1';
                ctx.lineWidth = lw(active ? 3 : 1.5); ctx.stroke();
                const cx = pts.reduce((s,p)=>s+p.x,0)/pts.length;
                const cy = pts.reduce((s,p)=>s+p.y,0)/pts.length;
                ctx.fillStyle = '#fff'; ctx.font = `bold ${lw(13)}px sans-serif`;
                ctx.textAlign = 'center'; ctx.fillText(room.name, cx, cy);
            }

            // Room points being drawn
            if (this.roomPoints.length) {
                ctx.beginPath(); ctx.moveTo(this.roomPoints[0].x, this.roomPoints[0].y);
                this.roomPoints.slice(1).forEach(p => ctx.lineTo(p.x, p.y));
                ctx.strokeStyle = '#fbbf24'; ctx.lineWidth = lw(2);
                ctx.setLineDash([lw(6), lw(4)]); ctx.stroke(); ctx.setLineDash([]);
                this.roomPoints.forEach(p => { ctx.beginPath(); ctx.arc(p.x,p.y,lw(4),0,Math.PI*2); ctx.fillStyle='#fbbf24'; ctx.fill(); });
            }

            // Cable runs
            for (const c of this.cableRuns) {
                const pts = c.route_points || c.points || [];
                if (pts.length < 2) continue;
                const col = this.cableTypes.find(t=>t.value===c.cable_type)?.color || '#3b82f6';
                ctx.beginPath(); ctx.moveTo(pts[0].x,pts[0].y);
                pts.slice(1).forEach(p=>ctx.lineTo(p.x,p.y));
                ctx.strokeStyle=col; ctx.lineWidth=lw(3); ctx.stroke();
            }

            // Cable points
            if (this.cablePoints.length) {
                const col = this.cableTypes.find(t=>t.value===this.cableType)?.color || '#3b82f6';
                ctx.beginPath(); ctx.moveTo(this.cablePoints[0].x,this.cablePoints[0].y);
                this.cablePoints.slice(1).forEach(p=>ctx.lineTo(p.x,p.y));
                ctx.strokeStyle=col; ctx.lineWidth=lw(2); ctx.setLineDash([lw(6),lw(4)]); ctx.stroke(); ctx.setLineDash([]);
                this.cablePoints.forEach(p=>{ctx.beginPath();ctx.arc(p.x,p.y,lw(4),0,Math.PI*2);ctx.fillStyle=col;ctx.fill();});
            }

            // Detections
            for (const d of this.detections) {
                if (d.rejected) continue;
                const sel = this.selectedDetection?.id === d.id;
                const w = d.crop?.w||40, h = d.crop?.h||40;
                ctx.strokeStyle = sel ? '#f87171' : '#4ade80'; ctx.lineWidth = lw(sel?3:1.5);
                ctx.strokeRect(d.x-w/2, d.y-h/2, w, h);
                const label = d.symbol_label||d.template_name||'?';
                ctx.font = `${lw(10)}px sans-serif`;
                const tw = ctx.measureText(label).width + lw(6);
                ctx.fillStyle = sel ? '#f87171' : '#4ade80';
                ctx.fillRect(d.x-w/2, d.y-h/2-lw(14), tw, lw(13));
                ctx.fillStyle='#000'; ctx.textAlign='left';
                ctx.fillText(label, d.x-w/2+lw(3), d.y-h/2-lw(4));
            }

            // Scale points
            for (const p of this.scalePoints) {
                ctx.beginPath(); ctx.arc(p.x,p.y,lw(6),0,Math.PI*2);
                ctx.fillStyle='#f87171'; ctx.fill();
                ctx.strokeStyle='#fff'; ctx.lineWidth=lw(2); ctx.stroke();
            }
            if (this.scalePoints.length===2) {
                ctx.beginPath(); ctx.moveTo(this.scalePoints[0].x,this.scalePoints[0].y);
                ctx.lineTo(this.scalePoints[1].x,this.scalePoints[1].y);
                ctx.strokeStyle='#f87171'; ctx.lineWidth=lw(2);
                ctx.setLineDash([lw(6),lw(4)]); ctx.stroke(); ctx.setLineDash([]);
            }

            // Selection box
            if (this.currentBox) {
                ctx.strokeStyle='#4ade80'; ctx.lineWidth=lw(2);
                ctx.setLineDash([lw(6),lw(4)]);
                ctx.strokeRect(this.currentBox.x,this.currentBox.y,this.currentBox.w,this.currentBox.h);
                ctx.setLineDash([]);
                ctx.fillStyle='rgba(74,222,128,0.08)';
                ctx.fillRect(this.currentBox.x,this.currentBox.y,this.currentBox.w,this.currentBox.h);
            }

            ctx.restore();

            // Zoom % badge
            ctx.fillStyle='rgba(0,0,0,0.6)'; ctx.fillRect(8,ch-28,52,20);
            ctx.fillStyle='#64748b'; ctx.font='11px sans-serif'; ctx.textAlign='left';
            ctx.fillText(`${Math.round(this.zoom*100)}%`, 14, ch-14);
        },
    };
}
