/**
 * GoZappify Takeoff Canvas - Interactive drawing takeoff tool
 * 
 * This is the core JavaScript module for the takeoff canvas.
 * It handles:
 * - PDF/image rendering on HTML5 canvas
 * - Symbol selection (draw box over key) and AI detection
 * - Room zone drawing (polygon)
 * - Cable run measurement (click-to-click paths)
 * - Floor area measurement
 * - Scale calibration
 * - Product search and linking
 * 
 * SAVE TO: app/static/js/takeoff-canvas.js
 * 
 * Used by the takeoff template via Alpine.js data binding.
 */

function takeoffCanvas(projectId, documentId) {
    return {
        // ── State ────────────────────────────────────────────────
        projectId: projectId,
        documentId: documentId,
        loading: true,
        error: null,
        notification: null,
        notificationTimeout: null,

        // Canvas
        canvas: null,
        ctx: null,
        canvasWidth: 0,
        canvasHeight: 0,
        drawingImage: null,
        drawingLoaded: false,

        // Mode: 'select' | 'symbol' | 'room' | 'cable' | 'area' | 'scale'
        mode: 'select',
        
        // Scale
        scale: 50, // px per metre (default, user should calibrate)
        scaleCalibrated: false,
        scalePoints: [], // Two points for scale calibration
        scaleRealDistance: null,

        // Symbol detection
        symbolTemplates: [],
        detections: [],
        isDrawingBox: false,
        boxStart: null,
        currentBox: null,
        selectedTemplate: null,
        symbolLabel: '',
        detecting: false,

        // Key area exclusion (user marks where the key/legend is)
        keyArea: null,
        settingKeyArea: false,

        // Rooms
        rooms: [],
        roomPoints: [], // Points being drawn for a new room
        drawingRoom: false,
        roomName: '',
        highlightedRoom: null,

        // Cable runs
        cableRuns: [],
        cablePoints: [], // Points for current cable run
        cableType: 'socket',
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
        areas: [],
        areaPoints: [],

        // Product search
        productSearch: '',
        productResults: [],
        productSearchTimeout: null,
        linkingTemplate: null,

        // Summary
        showSummary: false,

        // ── Initialisation ───────────────────────────────────────
        async init() {
            this.canvas = this.$refs.takeoffCanvas;
            if (!this.canvas) {
                this.error = 'Canvas element not found';
                return;
            }
            this.ctx = this.canvas.getContext('2d');

            // Load the drawing image
            await this.loadDrawing();

            // Load existing takeoff state
            await this.loadState();

            // Set up canvas event listeners
            this.setupCanvasEvents();

            this.loading = false;
            this.redraw();
        },

        async loadDrawing() {
            return new Promise((resolve, reject) => {
                this.drawingImage = new Image();
                this.drawingImage.onload = () => {
                    this.drawingLoaded = true;
                    // Size canvas to image
                    this.canvasWidth = this.drawingImage.width;
                    this.canvasHeight = this.drawingImage.height;
                    this.canvas.width = this.canvasWidth;
                    this.canvas.height = this.canvasHeight;
                    resolve();
                };
                this.drawingImage.onerror = () => {
                    this.error = 'Failed to load drawing image';
                    reject();
                };
                this.drawingImage.src = `/quotebuilder/api/projects/${this.projectId}/documents/${this.documentId}/render`;
            });
        },

        async loadState() {
            try {
                const resp = await fetch(`/quotebuilder/api/projects/${this.projectId}/documents/${this.documentId}/takeoff-state`);
                const data = await resp.json();
                if (data.success) {
                    this.rooms = data.rooms || [];
                    this.symbolTemplates = data.symbol_templates || [];
                    this.detections = data.detections || [];
                    this.cableRuns = data.cable_runs || [];
                    this.areas = data.areas || [];
                    this.scale = data.scale || 50;
                    if (data.scale && data.scale !== 50) {
                        this.scaleCalibrated = true;
                    }
                }
            } catch (e) {
                console.error('Failed to load takeoff state:', e);
            }
        },

        // ── Canvas Events ────────────────────────────────────────
        setupCanvasEvents() {
            this.canvas.addEventListener('mousedown', (e) => this.onMouseDown(e));
            this.canvas.addEventListener('mousemove', (e) => this.onMouseMove(e));
            this.canvas.addEventListener('mouseup', (e) => this.onMouseUp(e));
            this.canvas.addEventListener('click', (e) => this.onClick(e));
            this.canvas.addEventListener('dblclick', (e) => this.onDoubleClick(e));
        },

        getCanvasPos(e) {
            const rect = this.canvas.getBoundingClientRect();
            const scaleX = this.canvas.width / rect.width;
            const scaleY = this.canvas.height / rect.height;
            return {
                x: Math.round((e.clientX - rect.left) * scaleX),
                y: Math.round((e.clientY - rect.top) * scaleY),
            };
        },

        onMouseDown(e) {
            const pos = this.getCanvasPos(e);

            if (this.mode === 'symbol' || this.settingKeyArea) {
                this.isDrawingBox = true;
                this.boxStart = pos;
                this.currentBox = { x: pos.x, y: pos.y, w: 0, h: 0 };
            }
        },

        onMouseMove(e) {
            const pos = this.getCanvasPos(e);

            if (this.isDrawingBox && this.boxStart) {
                this.currentBox = {
                    x: Math.min(this.boxStart.x, pos.x),
                    y: Math.min(this.boxStart.y, pos.y),
                    w: Math.abs(pos.x - this.boxStart.x),
                    h: Math.abs(pos.y - this.boxStart.y),
                };
                this.redraw();
            }
        },

        onMouseUp(e) {
            if (this.isDrawingBox && this.currentBox && this.currentBox.w > 10 && this.currentBox.h > 10) {
                if (this.settingKeyArea) {
                    this.keyArea = { ...this.currentBox };
                    this.settingKeyArea = false;
                    this.notify('Key area set — symbol detections will exclude this region');
                } else if (this.mode === 'symbol') {
                    this.onSymbolBoxDrawn(this.currentBox);
                }
            }

            this.isDrawingBox = false;
            this.boxStart = null;
            this.currentBox = null;
            this.redraw();
        },

        onClick(e) {
            const pos = this.getCanvasPos(e);

            if (this.mode === 'room' && this.drawingRoom) {
                this.roomPoints.push(pos);
                this.redraw();
            }

            if (this.mode === 'cable') {
                this.cablePoints.push(pos);
                this.redraw();
            }

            if (this.mode === 'area') {
                this.areaPoints.push(pos);
                this.redraw();
            }

            if (this.mode === 'scale') {
                this.scalePoints.push(pos);
                if (this.scalePoints.length === 2) {
                    this.promptScaleDistance();
                }
                this.redraw();
            }
        },

        onDoubleClick(e) {
            // Double-click finishes room drawing
            if (this.mode === 'room' && this.drawingRoom && this.roomPoints.length >= 3) {
                this.finishRoom();
            }
        },

        // ── Symbol Detection ─────────────────────────────────────
        async onSymbolBoxDrawn(box) {
            // Prompt user for label
            this.symbolLabel = prompt('Label this symbol (e.g. "Double Socket", "Downlight"):');
            if (!this.symbolLabel) return;

            // Get cropped image data from canvas
            const cropCanvas = document.createElement('canvas');
            cropCanvas.width = box.w;
            cropCanvas.height = box.h;
            const cropCtx = cropCanvas.getContext('2d');
            cropCtx.drawImage(this.drawingImage, box.x, box.y, box.w, box.h, 0, 0, box.w, box.h);
            const cropB64 = cropCanvas.toDataURL('image/png');

            try {
                // Create symbol template
                const resp = await fetch(`/quotebuilder/api/projects/${this.projectId}/documents/${this.documentId}/symbol-templates`, {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({
                        label: this.symbolLabel,
                        crop_x: box.x,
                        crop_y: box.y,
                        crop_w: box.w,
                        crop_h: box.h,
                        crop_image: cropB64,
                    }),
                });
                const data = await resp.json();

                if (data.success) {
                    this.symbolTemplates.push(data.template);
                    this.notify(`Symbol template "${this.symbolLabel}" created`);

                    // Automatically run detection
                    await this.runDetection(data.template);
                }
            } catch (e) {
                this.notify('Error creating symbol template: ' + e.message, 'error');
            }
        },

        async runDetection(template) {
            this.detecting = true;
            this.notify(`Scanning drawing for "${template.label}"...`);

            try {
                const resp = await fetch(`/quotebuilder/api/projects/${this.projectId}/documents/${this.documentId}/detect-symbols`, {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({
                        template_id: template.id,
                        exclude_area: this.keyArea,
                        confidence_threshold: 0.65,
                    }),
                });
                const data = await resp.json();

                if (data.success) {
                    // Add new detections (replace old ones for this symbol type)
                    this.detections = this.detections.filter(d => d.symbol_type_id !== template.symbol_type_id);
                    this.detections = [...this.detections, ...data.detections];

                    // Update template count
                    const tpl = this.symbolTemplates.find(t => t.id === template.id);
                    if (tpl) tpl.total_found = data.count;

                    this.notify(`Found ${data.count} × ${template.label}`);
                    this.redraw();
                } else {
                    this.notify('Detection failed: ' + data.error, 'error');
                }
            } catch (e) {
                this.notify('Detection error: ' + e.message, 'error');
            }

            this.detecting = false;
        },

        // ── Room Drawing ─────────────────────────────────────────
        startDrawingRoom() {
            this.mode = 'room';
            this.drawingRoom = true;
            this.roomPoints = [];
            this.roomName = '';
        },

        async finishRoom() {
            if (this.roomPoints.length < 3) return;

            this.roomName = prompt('Name this room (e.g. "Kitchen", "Bedroom 1"):');
            if (!this.roomName) {
                this.roomPoints = [];
                this.drawingRoom = false;
                return;
            }

            try {
                const resp = await fetch(`/quotebuilder/api/projects/${this.projectId}/documents/${this.documentId}/rooms`, {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({
                        name: this.roomName,
                        boundary_points: this.roomPoints,
                    }),
                });
                const data = await resp.json();

                if (data.success) {
                    this.rooms.push(data.room);
                    this.notify(`Room "${this.roomName}" created with ${this.roomPoints.length} points`);
                    
                    // Reload detections (rooms may have been re-assigned)
                    await this.loadState();
                }
            } catch (e) {
                this.notify('Error creating room: ' + e.message, 'error');
            }

            this.roomPoints = [];
            this.drawingRoom = false;
            this.redraw();
        },

        cancelRoom() {
            this.roomPoints = [];
            this.drawingRoom = false;
            this.redraw();
        },

        // ── Cable Run ────────────────────────────────────────────
        async finishCableRun() {
            if (this.cablePoints.length < 2) return;

            const label = this.cableTypes.find(c => c.value === this.cableType)?.label || this.cableType;

            try {
                const resp = await fetch(`/quotebuilder/api/projects/${this.projectId}/documents/${this.documentId}/cable-runs`, {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({
                        cable_type: this.cableType,
                        cable_label: label,
                        route_points: this.cablePoints,
                        waste_percent: 10,
                    }),
                });
                const data = await resp.json();

                if (data.success) {
                    this.cableRuns.push(data.cable_run);
                    this.notify(`Cable run: ${data.cable_run.length_metres}m ${label} (${data.cable_run.total_metres}m inc. waste)`);
                }
            } catch (e) {
                this.notify('Error saving cable run: ' + e.message, 'error');
            }

            this.cablePoints = [];
            this.redraw();
        },

        undoLastCablePoint() {
            this.cablePoints.pop();
            this.redraw();
        },

        // ── Area Measurement ─────────────────────────────────────
        async finishArea() {
            if (this.areaPoints.length < 3) return;

            try {
                const resp = await fetch(`/quotebuilder/api/projects/${this.projectId}/documents/${this.documentId}/areas`, {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({
                        points: this.areaPoints,
                        label: `Area ${this.areas.length + 1}`,
                    }),
                });
                const data = await resp.json();

                if (data.success) {
                    this.areas.push(data.area);
                    this.notify(`Area measured: ${data.area.area_sqm}m²`);
                }
            } catch (e) {
                this.notify('Error measuring area: ' + e.message, 'error');
            }

            this.areaPoints = [];
            this.redraw();
        },

        // ── Scale Calibration ────────────────────────────────────
        promptScaleDistance() {
            const input = prompt('What is the real-world distance between these two points (in metres)?');
            if (!input) {
                this.scalePoints = [];
                return;
            }

            const realDist = parseFloat(input);
            if (isNaN(realDist) || realDist <= 0) {
                this.notify('Invalid distance', 'error');
                this.scalePoints = [];
                return;
            }

            // Calculate pixel distance
            const dx = this.scalePoints[1].x - this.scalePoints[0].x;
            const dy = this.scalePoints[1].y - this.scalePoints[0].y;
            const pixelDist = Math.sqrt(dx * dx + dy * dy);

            this.scale = pixelDist / realDist;
            this.scaleCalibrated = true;

            // Save to server
            fetch(`/quotebuilder/api/projects/${this.projectId}/documents/${this.documentId}/scale`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    pixel_distance: pixelDist,
                    real_distance: realDist,
                }),
            });

            this.notify(`Scale set: ${this.scale.toFixed(1)} px/m (${realDist}m = ${pixelDist.toFixed(0)}px)`);
            this.scalePoints = [];
            this.mode = 'select';
            this.redraw();
        },

        // ── Product Search & Linking ─────────────────────────────
        async searchProducts(query) {
            if (query.length < 2) {
                this.productResults = [];
                return;
            }

            clearTimeout(this.productSearchTimeout);
            this.productSearchTimeout = setTimeout(async () => {
                try {
                    const resp = await fetch(`/quotebuilder/api/products/search?q=${encodeURIComponent(query)}`);
                    const data = await resp.json();
                    if (data.success) {
                        this.productResults = data.products;
                    }
                } catch (e) {
                    console.error('Product search error:', e);
                }
            }, 300);
        },

        async linkProduct(template, product) {
            try {
                const resp = await fetch(`/quotebuilder/api/projects/${this.projectId}/link-product`, {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({
                        template_id: template.id,
                        product: product,
                    }),
                });
                const data = await resp.json();

                if (data.success) {
                    // Update template
                    const tpl = this.symbolTemplates.find(t => t.id === template.id);
                    if (tpl) {
                        tpl.default_part_number = product.sku;
                        tpl.default_product_description = product.description || product.name;
                        tpl.default_unit_cost = product.purchase_cost;
                        tpl.default_unit_sell = product.unit_price;
                    }

                    this.linkingTemplate = null;
                    this.productSearch = '';
                    this.productResults = [];
                    this.notify(`Linked ${product.sku} to ${template.label} — ${data.materials_created} material lines created`);
                }
            } catch (e) {
                this.notify('Error linking product: ' + e.message, 'error');
            }
        },

        // ── Canvas Rendering ─────────────────────────────────────
        redraw() {
            if (!this.ctx || !this.drawingLoaded) return;

            const ctx = this.ctx;
            ctx.clearRect(0, 0, this.canvasWidth, this.canvasHeight);

            // Draw the actual drawing image
            ctx.drawImage(this.drawingImage, 0, 0);

            // Draw rooms
            this.rooms.forEach(room => {
                const pts = room.boundary_points;
                if (!pts || pts.length < 3) return;

                ctx.fillStyle = this.highlightedRoom === room.id ? 'rgba(99, 102, 241, 0.15)' : 'rgba(99, 102, 241, 0.06)';
                ctx.beginPath();
                ctx.moveTo(pts[0].x, pts[0].y);
                pts.slice(1).forEach(p => ctx.lineTo(p.x, p.y));
                ctx.closePath();
                ctx.fill();

                ctx.strokeStyle = this.highlightedRoom === room.id ? '#6366f1' : 'rgba(99, 102, 241, 0.5)';
                ctx.lineWidth = this.highlightedRoom === room.id ? 3 : 1.5;
                ctx.stroke();

                // Room label
                const cx = pts.reduce((s, p) => s + p.x, 0) / pts.length;
                const cy = pts.reduce((s, p) => s + p.y, 0) / pts.length;
                ctx.fillStyle = 'rgba(99, 102, 241, 0.85)';
                ctx.font = 'bold 14px system-ui, sans-serif';
                const tw = ctx.measureText(room.name).width;
                ctx.fillRect(cx - tw / 2 - 6, cy - 10, tw + 12, 22);
                ctx.fillStyle = '#fff';
                ctx.textAlign = 'center';
                ctx.textBaseline = 'middle';
                ctx.fillText(room.name, cx, cy + 1);
            });

            // Draw in-progress room
            if (this.roomPoints.length > 0) {
                ctx.strokeStyle = '#6366f1';
                ctx.lineWidth = 2;
                ctx.setLineDash([6, 3]);
                ctx.beginPath();
                ctx.moveTo(this.roomPoints[0].x, this.roomPoints[0].y);
                this.roomPoints.slice(1).forEach(p => ctx.lineTo(p.x, p.y));
                ctx.stroke();
                ctx.setLineDash([]);

                this.roomPoints.forEach(p => {
                    ctx.fillStyle = '#6366f1';
                    ctx.beginPath();
                    ctx.arc(p.x, p.y, 4, 0, Math.PI * 2);
                    ctx.fill();
                });
            }

            // Draw detections
            this.detections.forEach(det => {
                const tpl = this.symbolTemplates.find(t => t.symbol_type_id === det.symbol_type_id);
                const color = tpl?.color || '#3b82f6';

                // Highlight circle
                ctx.fillStyle = det.confirmed ? 'rgba(34, 197, 94, 0.2)' : `${color}22`;
                ctx.beginPath();
                ctx.arc(det.x, det.y, 14, 0, Math.PI * 2);
                ctx.fill();

                ctx.strokeStyle = det.confirmed ? '#22c55e' : color;
                ctx.lineWidth = 2;
                ctx.stroke();

                // Confidence indicator
                if (det.confidence && det.confidence < 0.85) {
                    ctx.fillStyle = '#fbbf24';
                    ctx.font = '10px system-ui';
                    ctx.textAlign = 'center';
                    ctx.fillText('?', det.x, det.y - 18);
                }
            });

            // Draw cable runs (saved)
            this.cableRuns.forEach(run => {
                const pts = run.route_points;
                if (!pts || pts.length < 2) return;
                const cType = this.cableTypes.find(c => c.value === run.cable_type);
                
                ctx.strokeStyle = cType?.color || '#f97316';
                ctx.lineWidth = 2;
                ctx.setLineDash([4, 4]);
                ctx.globalAlpha = 0.5;
                ctx.beginPath();
                ctx.moveTo(pts[0].x, pts[0].y);
                pts.slice(1).forEach(p => ctx.lineTo(p.x, p.y));
                ctx.stroke();
                ctx.setLineDash([]);
                ctx.globalAlpha = 1;
            });

            // Draw in-progress cable run
            if (this.cablePoints.length > 0) {
                const cType = this.cableTypes.find(c => c.value === this.cableType);
                ctx.strokeStyle = cType?.color || '#f97316';
                ctx.lineWidth = 2.5;
                ctx.setLineDash([5, 3]);
                ctx.beginPath();
                ctx.moveTo(this.cablePoints[0].x, this.cablePoints[0].y);
                this.cablePoints.slice(1).forEach(p => ctx.lineTo(p.x, p.y));
                ctx.stroke();
                ctx.setLineDash([]);

                this.cablePoints.forEach((p, i) => {
                    ctx.fillStyle = i === 0 ? (cType?.color || '#f97316') : '#fff';
                    ctx.strokeStyle = cType?.color || '#f97316';
                    ctx.lineWidth = 2;
                    ctx.beginPath();
                    ctx.arc(p.x, p.y, 5, 0, Math.PI * 2);
                    ctx.fill();
                    ctx.stroke();
                });

                // Running length label
                if (this.cablePoints.length > 1) {
                    let totalPx = 0;
                    for (let i = 1; i < this.cablePoints.length; i++) {
                        const dx = this.cablePoints[i].x - this.cablePoints[i-1].x;
                        const dy = this.cablePoints[i].y - this.cablePoints[i-1].y;
                        totalPx += Math.sqrt(dx * dx + dy * dy);
                    }
                    const metres = (totalPx / this.scale).toFixed(1);
                    const lastP = this.cablePoints[this.cablePoints.length - 1];
                    
                    ctx.fillStyle = cType?.color || '#f97316';
                    ctx.font = 'bold 12px system-ui';
                    const labelW = ctx.measureText(`${metres}m`).width + 12;
                    ctx.fillRect(lastP.x + 12, lastP.y - 14, labelW, 22);
                    ctx.fillStyle = '#fff';
                    ctx.textAlign = 'left';
                    ctx.textBaseline = 'middle';
                    ctx.fillText(`${metres}m`, lastP.x + 18, lastP.y - 3);
                }
            }

            // Draw in-progress area measurement
            if (this.areaPoints.length > 0) {
                ctx.strokeStyle = '#8b5cf6';
                ctx.lineWidth = 2;
                ctx.setLineDash([4, 4]);
                ctx.beginPath();
                ctx.moveTo(this.areaPoints[0].x, this.areaPoints[0].y);
                this.areaPoints.slice(1).forEach(p => ctx.lineTo(p.x, p.y));
                if (this.areaPoints.length > 2) {
                    ctx.lineTo(this.areaPoints[0].x, this.areaPoints[0].y);
                    ctx.fillStyle = 'rgba(139, 92, 246, 0.08)';
                    ctx.fill();
                }
                ctx.stroke();
                ctx.setLineDash([]);

                this.areaPoints.forEach(p => {
                    ctx.fillStyle = '#8b5cf6';
                    ctx.beginPath();
                    ctx.arc(p.x, p.y, 4, 0, Math.PI * 2);
                    ctx.fill();
                });
            }

            // Draw saved areas
            this.areas.forEach(area => {
                const pts = area.points;
                if (!pts || pts.length < 3) return;
                ctx.fillStyle = 'rgba(139, 92, 246, 0.06)';
                ctx.strokeStyle = 'rgba(139, 92, 246, 0.4)';
                ctx.lineWidth = 1;
                ctx.beginPath();
                ctx.moveTo(pts[0].x, pts[0].y);
                pts.slice(1).forEach(p => ctx.lineTo(p.x, p.y));
                ctx.closePath();
                ctx.fill();
                ctx.stroke();

                // Area label
                if (area.area_sqm) {
                    const cx = pts.reduce((s, p) => s + p.x, 0) / pts.length;
                    const cy = pts.reduce((s, p) => s + p.y, 0) / pts.length;
                    ctx.fillStyle = 'rgba(139, 92, 246, 0.85)';
                    const label = `${area.area_sqm}m²`;
                    ctx.font = 'bold 12px system-ui';
                    const lw = ctx.measureText(label).width + 10;
                    ctx.fillRect(cx - lw / 2, cy - 9, lw, 20);
                    ctx.fillStyle = '#fff';
                    ctx.textAlign = 'center';
                    ctx.textBaseline = 'middle';
                    ctx.fillText(label, cx, cy + 1);
                }
            });

            // Draw key area exclusion zone
            if (this.keyArea) {
                ctx.strokeStyle = '#ef4444';
                ctx.lineWidth = 2;
                ctx.setLineDash([8, 4]);
                ctx.strokeRect(this.keyArea.x, this.keyArea.y, this.keyArea.w, this.keyArea.h);
                ctx.setLineDash([]);
                ctx.fillStyle = 'rgba(239, 68, 68, 0.05)';
                ctx.fillRect(this.keyArea.x, this.keyArea.y, this.keyArea.w, this.keyArea.h);

                ctx.fillStyle = '#ef4444';
                ctx.font = 'bold 11px system-ui';
                ctx.textAlign = 'center';
                ctx.fillText('KEY (excluded)', this.keyArea.x + this.keyArea.w / 2, this.keyArea.y - 5);
            }

            // Draw current selection box
            if (this.currentBox) {
                ctx.strokeStyle = this.settingKeyArea ? '#ef4444' : '#6366f1';
                ctx.lineWidth = 2;
                ctx.setLineDash([6, 3]);
                ctx.strokeRect(this.currentBox.x, this.currentBox.y, this.currentBox.w, this.currentBox.h);
                ctx.setLineDash([]);
                ctx.fillStyle = this.settingKeyArea ? 'rgba(239, 68, 68, 0.08)' : 'rgba(99, 102, 241, 0.08)';
                ctx.fillRect(this.currentBox.x, this.currentBox.y, this.currentBox.w, this.currentBox.h);
            }

            // Scale calibration points
            if (this.scalePoints.length > 0) {
                ctx.strokeStyle = '#10b981';
                ctx.lineWidth = 2;
                this.scalePoints.forEach(p => {
                    ctx.fillStyle = '#10b981';
                    ctx.beginPath();
                    ctx.arc(p.x, p.y, 6, 0, Math.PI * 2);
                    ctx.fill();
                    ctx.strokeStyle = '#fff';
                    ctx.stroke();
                });

                if (this.scalePoints.length === 2) {
                    ctx.strokeStyle = '#10b981';
                    ctx.setLineDash([4, 4]);
                    ctx.beginPath();
                    ctx.moveTo(this.scalePoints[0].x, this.scalePoints[0].y);
                    ctx.lineTo(this.scalePoints[1].x, this.scalePoints[1].y);
                    ctx.stroke();
                    ctx.setLineDash([]);
                }
            }
        },

        // ── Helpers ──────────────────────────────────────────────
        notify(msg, type = 'success') {
            this.notification = { msg, type };
            clearTimeout(this.notificationTimeout);
            this.notificationTimeout = setTimeout(() => {
                this.notification = null;
            }, 4000);
        },

        getDetectionsByRoom() {
            const grouped = {};
            this.rooms.forEach(r => {
                grouped[r.id] = {
                    room: r,
                    detections: this.detections.filter(d => d.room_id === r.id),
                };
            });
            // Unassigned
            const unassigned = this.detections.filter(d => !d.room_id);
            if (unassigned.length > 0) {
                grouped['unassigned'] = {
                    room: { id: null, name: 'Unassigned' },
                    detections: unassigned,
                };
            }
            return grouped;
        },

        getDetectionCountBySymbol() {
            const counts = {};
            this.symbolTemplates.forEach(t => {
                counts[t.symbol_type_id] = {
                    template: t,
                    count: this.detections.filter(d => d.symbol_type_id === t.symbol_type_id && !d.rejected).length,
                };
            });
            return counts;
        },

        getCableRunSummary() {
            const summary = {};
            this.cableTypes.forEach(ct => {
                const runs = this.cableRuns.filter(r => r.cable_type === ct.value);
                if (runs.length > 0) {
                    summary[ct.value] = {
                        label: ct.label,
                        color: ct.color,
                        runs: runs.length,
                        totalMetres: runs.reduce((s, r) => s + (r.total_metres || 0), 0),
                    };
                }
            });
            return summary;
        },

        setMode(newMode) {
            this.mode = newMode;
            this.cablePoints = [];
            this.areaPoints = [];
            this.roomPoints = [];
            this.scalePoints = [];
            this.drawingRoom = false;
            this.isDrawingBox = false;
            this.redraw();
        },

        getCursor() {
            if (this.mode === 'symbol' || this.settingKeyArea) return 'crosshair';
            if (this.mode === 'room' && this.drawingRoom) return 'crosshair';
            if (this.mode === 'cable') return 'crosshair';
            if (this.mode === 'area') return 'crosshair';
            if (this.mode === 'scale') return 'crosshair';
            return 'default';
        },

        async deleteRoom(roomId) {
            if (!confirm('Delete this room? Detections will be unassigned.')) return;
            try {
                await fetch(`/quotebuilder/api/projects/${this.projectId}/rooms/${roomId}`, { method: 'DELETE' });
                this.rooms = this.rooms.filter(r => r.id !== roomId);
                await this.loadState();
                this.redraw();
                this.notify('Room deleted');
            } catch (e) {
                this.notify('Error deleting room', 'error');
            }
        },

        async deleteCableRun(runId) {
            try {
                await fetch(`/quotebuilder/api/projects/${this.projectId}/cable-runs/${runId}`, { method: 'DELETE' });
                this.cableRuns = this.cableRuns.filter(r => r.id !== runId);
                this.redraw();
                this.notify('Cable run deleted');
            } catch (e) {
                this.notify('Error deleting cable run', 'error');
            }
        },
    };
}
