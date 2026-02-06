/**
 * GoZappify Takeoff Canvas - Version 5
 * Smooth zoom, click-drag pan, AI-powered symbol detection
 */

document.addEventListener('alpine:init', () => {
    Alpine.data('takeoffCanvas', function() {
        return {
            // Canvas state
            canvas: null,
            ctx: null,
            image: null,
            imageLoaded: false,
            loading: true,
            error: null,

            // Zoom and pan
            zoom: 1,
            minZoom: 0.05,
            maxZoom: 8,
            panX: 0,
            panY: 0,
            isPanning: false,
            panStartX: 0,
            panStartY: 0,
            panStartPanX: 0,
            panStartPanY: 0,

            // Mode
            mode: 'select',

            // Scale
            scaleCalibrated: false,
            pxPerMetre: null,
            calibrationPoints: [],
            calibrationDistance: null,
            showCalibrationModal: false,

            // Rooms
            rooms: [],
            currentRoomPoints: [],
            selectedRoom: null,
            activeRoom: null,
            showRoomModal: false,
            newRoomName: '',
            showRoomPanel: false,

            // Symbol templates
            symbolTemplates: [],
            showSymbolModal: false,
            symbolSelectionBox: null,
            isSelectingSymbol: false,
            symbolSelectionStart: null,

            // Product search
            productSearchQuery: '',
            productSearchResults: [],
            productSearchLoading: false,
            productSearchPage: 1,
            productSearchHasMore: false,
            selectedProduct: null,

            // Symbol categories
            symbolCategories: [
                { id: 'socket', name: 'Socket', icon: '🔌' },
                { id: 'switch', name: 'Switch', icon: '🔘' },
                { id: 'light', name: 'Light', icon: '💡' },
                { id: 'data', name: 'Data/Comms', icon: '📡' },
                { id: 'fire', name: 'Fire/Safety', icon: '🔥' },
                { id: 'sensor', name: 'Sensor/PIR', icon: '👁️' },
                { id: 'consumer_unit', name: 'Consumer Unit', icon: '⚡' },
                { id: 'other', name: 'Other', icon: '⬜' }
            ],
            selectedCategory: 'socket',

            // Enhanced symbol fields
            symbolColour: '',
            symbolExpectedText: '',
            symbolGangCount: null,
            symbolIsDimmer: false,
            symbolDescription: '',
            useOcr: false,
            expectedText: '',

            // Colour options
            colourOptions: [
                { value: '', label: 'No specific colour' },
                { value: 'blue', label: 'Blue' },
                { value: 'red', label: 'Red' },
                { value: 'black', label: 'Black' },
                { value: 'green', label: 'Green' },
                { value: 'yellow', label: 'Yellow' },
                { value: 'white', label: 'White' }
            ],

            // Detections
            detections: [],
            selectedDetection: null,
            detecting: false,
            detectionMethod: 'ai',

            // Cable runs
            cableRuns: [],
            cableStartPoint: null,

            // Areas
            areas: [],

            // Summary
            showSummary: false,

            // Legend parsing
            parsingLegend: false,
            showLegendModal: false,
            legendTemplates: [],

            // Mouse tracking for click vs drag
            mouseDownPos: null,
            mouseMoved: false,

            init() {
                this.canvas = this.$refs.canvas;
                this.ctx = this.canvas.getContext('2d');
                this.resizeCanvas();
                this.loadDrawing();
                this.loadExistingData();
                this.setupEventListeners();
            },

            resizeCanvas() {
                if (!this.canvas) return;
                const container = this.canvas.parentElement;
                if (!container) return;
                const dpr = window.devicePixelRatio || 1;
                this.canvas.width = container.clientWidth * dpr;
                this.canvas.height = container.clientHeight * dpr;
                this.canvas.style.width = container.clientWidth + 'px';
                this.canvas.style.height = container.clientHeight + 'px';
                this.ctx.scale(dpr, dpr);
            },

            setupEventListeners() {
                // Smooth wheel zoom
                this.canvas.addEventListener('wheel', (e) => {
                    e.preventDefault();
                    const rect = this.canvas.getBoundingClientRect();
                    const mouseX = e.clientX - rect.left;
                    const mouseY = e.clientY - rect.top;
                    const delta = -e.deltaY;
                    const zoomIntensity = 0.002;
                    const factor = Math.exp(delta * zoomIntensity);
                    const newZoom = Math.max(this.minZoom, Math.min(this.maxZoom, this.zoom * factor));

                    if (newZoom !== this.zoom) {
                        const scale = newZoom / this.zoom;
                        this.panX = mouseX - (mouseX - this.panX) * scale;
                        this.panY = mouseY - (mouseY - this.panY) * scale;
                        this.zoom = newZoom;
                        this.render();
                    }
                }, { passive: false });

                // Keyboard shortcuts
                document.addEventListener('keydown', (e) => {
                    if (e.target.tagName === 'INPUT' || e.target.tagName === 'TEXTAREA') return;
                    if (e.key === 'Escape') this.cancelCurrentAction();
                    else if (e.key === '+' || e.key === '=') this.zoomIn();
                    else if (e.key === '-') this.zoomOut();
                    else if (e.key === '0') this.resetView();
                    else if (e.key === 'Delete' && this.selectedDetection) this.deleteDetection(this.selectedDetection);
                });

                // Window resize
                window.addEventListener('resize', () => { this.resizeCanvas(); this.render(); });

                // Touch support
                let lastTouchDist = 0;
                let lastTouchCenter = null;

                this.canvas.addEventListener('touchstart', (e) => {
                    if (e.touches.length === 2) {
                        e.preventDefault();
                        const dx = e.touches[0].clientX - e.touches[1].clientX;
                        const dy = e.touches[0].clientY - e.touches[1].clientY;
                        lastTouchDist = Math.sqrt(dx * dx + dy * dy);
                        lastTouchCenter = {
                            x: (e.touches[0].clientX + e.touches[1].clientX) / 2,
                            y: (e.touches[0].clientY + e.touches[1].clientY) / 2
                        };
                    }
                }, { passive: false });

                this.canvas.addEventListener('touchmove', (e) => {
                    if (e.touches.length === 2) {
                        e.preventDefault();
                        const dx = e.touches[0].clientX - e.touches[1].clientX;
                        const dy = e.touches[0].clientY - e.touches[1].clientY;
                        const dist = Math.sqrt(dx * dx + dy * dy);
                        const center = {
                            x: (e.touches[0].clientX + e.touches[1].clientX) / 2,
                            y: (e.touches[0].clientY + e.touches[1].clientY) / 2
                        };
                        if (lastTouchDist > 0) {
                            const factor = dist / lastTouchDist;
                            const rect = this.canvas.getBoundingClientRect();
                            const cx = center.x - rect.left;
                            const cy = center.y - rect.top;
                            const newZoom = Math.max(this.minZoom, Math.min(this.maxZoom, this.zoom * factor));
                            const sc = newZoom / this.zoom;
                            this.panX = cx - (cx - this.panX) * sc;
                            this.panY = cy - (cy - this.panY) * sc;
                            this.zoom = newZoom;
                        }
                        if (lastTouchCenter) {
                            this.panX += center.x - lastTouchCenter.x;
                            this.panY += center.y - lastTouchCenter.y;
                        }
                        lastTouchDist = dist;
                        lastTouchCenter = center;
                        this.render();
                    }
                }, { passive: false });

                this.canvas.addEventListener('touchend', () => { lastTouchDist = 0; lastTouchCenter = null; });
            },

            // === LOADING ===

            async loadDrawing() {
                this.loading = true;
                this.error = null;
                try {
                    const response = await fetch(`/quotebuilder/api/projects/${projectId}/documents/${documentId}/render`);
                    if (!response.ok) throw new Error('Failed to render drawing');
                    const blob = await response.blob();
                    const url = URL.createObjectURL(blob);

                    this.image = new Image();
                    this.image.onload = () => {
                        this.imageLoaded = true;
                        this.loading = false;
                        this.fitToScreen();
                        this.render();
                    };
                    this.image.onerror = () => {
                        this.error = 'Failed to load drawing image';
                        this.loading = false;
                    };
                    this.image.src = url;
                } catch (err) {
                    this.error = err.message;
                    this.loading = false;
                }
            },

            async loadExistingData() {
                try {
                    const stateRes = await fetch(`/quotebuilder/api/projects/${projectId}/documents/${documentId}/takeoff-state`);
                    if (stateRes.ok) {
                        const data = await stateRes.json();
                        if (data.success) {
                            this.rooms = data.rooms || [];
                            this.symbolTemplates = data.symbol_templates || [];
                            this.detections = data.detections || [];
                            this.cableRuns = data.cable_runs || [];
                            this.areas = data.areas || [];
                            if (data.scale) {
                                this.pxPerMetre = data.scale;
                                this.scaleCalibrated = true;
                            }
                        }
                    }
                } catch (err) {
                    console.error('Error loading existing data:', err);
                }
            },

            // === VIEW CONTROLS ===

            fitToScreen() {
                if (!this.image || !this.canvas) return;
                const container = this.canvas.parentElement;
                const cw = container.clientWidth;
                const ch = container.clientHeight;
                const scaleX = cw / this.image.width;
                const scaleY = ch / this.image.height;
                this.zoom = Math.min(scaleX, scaleY) * 0.92;
                this.panX = (cw - this.image.width * this.zoom) / 2;
                this.panY = (ch - this.image.height * this.zoom) / 2;
            },

            zoomIn() { this.smoothZoomTo(Math.min(this.maxZoom, this.zoom * 1.3)); },
            zoomOut() { this.smoothZoomTo(Math.max(this.minZoom, this.zoom / 1.3)); },

            smoothZoomTo(newZoom) {
                const cx = this.canvas.parentElement.clientWidth / 2;
                const cy = this.canvas.parentElement.clientHeight / 2;
                const startZoom = this.zoom;
                const startPanX = this.panX;
                const startPanY = this.panY;
                const targetScale = newZoom / startZoom;
                const targetPanX = cx - (cx - startPanX) * targetScale;
                const targetPanY = cy - (cy - startPanY) * targetScale;
                const duration = 200;
                const startTime = performance.now();

                const animate = (now) => {
                    const t = Math.min((now - startTime) / duration, 1);
                    const ease = 1 - Math.pow(1 - t, 3);
                    this.zoom = startZoom + (newZoom - startZoom) * ease;
                    this.panX = startPanX + (targetPanX - startPanX) * ease;
                    this.panY = startPanY + (targetPanY - startPanY) * ease;
                    this.render();
                    if (t < 1) requestAnimationFrame(animate);
                };
                requestAnimationFrame(animate);
            },

            resetView() { this.fitToScreen(); this.render(); },

            zoomToRoom(room) {
                if (!room.points || room.points.length < 3) return;
                const xs = room.points.map(p => p.x);
                const ys = room.points.map(p => p.y);
                const minX = Math.min(...xs), maxX = Math.max(...xs);
                const minY = Math.min(...ys), maxY = Math.max(...ys);
                const container = this.canvas.parentElement;
                const cw = container.clientWidth;
                const ch = container.clientHeight;
                const scaleX = cw / (maxX - minX + 200);
                const scaleY = ch / (maxY - minY + 200);
                this.zoom = Math.min(scaleX, scaleY, this.maxZoom);
                this.panX = cw / 2 - ((minX + maxX) / 2) * this.zoom;
                this.panY = ch / 2 - ((minY + maxY) / 2) * this.zoom;
                this.render();
            },

            screenToImage(screenX, screenY) {
                return { x: (screenX - this.panX) / this.zoom, y: (screenY - this.panY) / this.zoom };
            },

            // === MOUSE HANDLING ===

            handleMouseDown(e) {
                const rect = this.canvas.getBoundingClientRect();
                const screenX = e.clientX - rect.left;
                const screenY = e.clientY - rect.top;
                const imgCoords = this.screenToImage(screenX, screenY);

                this.mouseDownPos = { x: e.clientX, y: e.clientY };
                this.mouseMoved = false;

                // Middle mouse always pans
                if (e.button === 1) { e.preventDefault(); this.startPan(e); return; }
                if (e.button !== 0) return;

                // In select mode, left click starts pan (click detected on mouseup if no drag)
                if (this.mode === 'select') { this.startPan(e); return; }

                // Symbol mode: start selection box
                if (this.mode === 'symbol') {
                    this.isSelectingSymbol = true;
                    this.symbolSelectionStart = imgCoords;
                    this.symbolSelectionBox = { x: imgCoords.x, y: imgCoords.y, width: 0, height: 0 };
                    return;
                }

                switch (this.mode) {
                    case 'calibrate': this.handleCalibrateClick(imgCoords); break;
                    case 'room': this.handleRoomClick(imgCoords); break;
                    case 'cable': this.handleCableClick(imgCoords); break;
                }
            },

            startPan(e) {
                this.isPanning = true;
                this.panStartX = e.clientX;
                this.panStartY = e.clientY;
                this.panStartPanX = this.panX;
                this.panStartPanY = this.panY;
                this.canvas.style.cursor = 'grabbing';
            },

            handleMouseMove(e) {
                const rect = this.canvas.getBoundingClientRect();
                const screenX = e.clientX - rect.left;
                const screenY = e.clientY - rect.top;

                if (this.mouseDownPos) {
                    const dx = e.clientX - this.mouseDownPos.x;
                    const dy = e.clientY - this.mouseDownPos.y;
                    if (Math.abs(dx) > 3 || Math.abs(dy) > 3) this.mouseMoved = true;
                }

                if (this.isPanning) {
                    this.panX = this.panStartPanX + (e.clientX - this.panStartX);
                    this.panY = this.panStartPanY + (e.clientY - this.panStartY);
                    this.render();
                    return;
                }

                if (this.isSelectingSymbol && this.symbolSelectionStart) {
                    const imgCoords = this.screenToImage(screenX, screenY);
                    this.symbolSelectionBox = {
                        x: Math.min(this.symbolSelectionStart.x, imgCoords.x),
                        y: Math.min(this.symbolSelectionStart.y, imgCoords.y),
                        width: Math.abs(imgCoords.x - this.symbolSelectionStart.x),
                        height: Math.abs(imgCoords.y - this.symbolSelectionStart.y)
                    };
                    this.render();
                }

                if (this.mode === 'room' && this.currentRoomPoints.length > 0) {
                    this.render();
                    this.drawRoomPreview(this.screenToImage(screenX, screenY));
                }

                if (this.mode === 'cable' && this.cableStartPoint) {
                    this.render();
                    this.drawCablePreview(this.screenToImage(screenX, screenY));
                }
            },

            handleMouseUp(e) {
                if (this.isPanning) {
                    this.isPanning = false;
                    this.canvas.style.cursor = this.getCursorForMode();
                }

                // In select mode: if didn't drag, treat as click
                if (this.mode === 'select' && !this.mouseMoved && this.mouseDownPos) {
                    const rect = this.canvas.getBoundingClientRect();
                    const screenX = e.clientX - rect.left;
                    const screenY = e.clientY - rect.top;
                    this.handleSelectClick(this.screenToImage(screenX, screenY));
                }

                if (this.isSelectingSymbol && this.symbolSelectionBox) {
                    if (this.symbolSelectionBox.width > 10 && this.symbolSelectionBox.height > 10) {
                        this.openSymbolModal();
                    }
                    this.isSelectingSymbol = false;
                }

                this.mouseDownPos = null;
                this.mouseMoved = false;
            },

            getCursorForMode() {
                return { select: 'grab', calibrate: 'crosshair', symbol: 'crosshair', room: 'crosshair', cable: 'crosshair' }[this.mode] || 'grab';
            },

            setMode(newMode) {
                this.cancelCurrentAction();
                this.mode = newMode;
                this.canvas.style.cursor = this.getCursorForMode();
                this.render();
            },

            cancelCurrentAction() {
                this.isSelectingSymbol = false;
                this.symbolSelectionBox = null;
                this.symbolSelectionStart = null;
                this.currentRoomPoints = [];
                this.cableStartPoint = null;
                this.calibrationPoints = [];
                this.selectedDetection = null;
                this.mode = 'select';
                this.canvas.style.cursor = 'grab';
                this.render();
            },

            // === SYMBOL TEMPLATES ===

            openSymbolModal() {
                this.showSymbolModal = true;
                this.productSearchQuery = '';
                this.productSearchResults = [];
                this.selectedProduct = null;
                this.selectedCategory = 'socket';
                this.symbolColour = '';
                this.symbolExpectedText = '';
                this.symbolGangCount = null;
                this.symbolIsDimmer = false;
                this.symbolDescription = '';
                this.useOcr = false;
                this.expectedText = '';
            },

            async searchProducts() {
                if (!this.productSearchQuery || this.productSearchQuery.length < 2) {
                    this.productSearchResults = [];
                    return;
                }
                this.productSearchLoading = true;
                try {
                    const response = await fetch(`/quotebuilder/api/products/search?q=${encodeURIComponent(this.productSearchQuery)}&page=${this.productSearchPage}&limit=20`);
                    if (response.ok) {
                        const data = await response.json();
                        const products = data.products || data || [];
                        this.productSearchResults = this.productSearchPage === 1 ? products : [...this.productSearchResults, ...products];
                        this.productSearchHasMore = data.has_more || false;
                    }
                } catch (err) {
                    console.error('Product search failed:', err);
                } finally {
                    this.productSearchLoading = false;
                }
            },

            loadMoreProducts() { this.productSearchPage++; this.searchProducts(); },
            selectProduct(product) { this.selectedProduct = product; },

            async createSymbolTemplate() {
                if (!this.symbolSelectionBox || !this.selectedProduct) { alert('Please select a product'); return; }
                try {
                    const response = await fetch(`/quotebuilder/api/projects/${projectId}/documents/${documentId}/symbol-templates`, {
                        method: 'POST',
                        headers: { 'Content-Type': 'application/json' },
                        body: JSON.stringify({
                            name: this.selectedProduct.name,
                            category: this.selectedCategory,
                            description: this.symbolDescription,
                            document_id: documentId,
                            x: Math.round(this.symbolSelectionBox.x),
                            y: Math.round(this.symbolSelectionBox.y),
                            width: Math.round(this.symbolSelectionBox.width),
                            height: Math.round(this.symbolSelectionBox.height),
                            product_id: this.selectedProduct.id,
                            colour: this.symbolColour || null,
                            expected_text: this.useOcr ? this.expectedText : null,
                            gang_count: this.symbolGangCount || null,
                            is_dimmer: this.symbolIsDimmer
                        })
                    });
                    if (response.ok) {
                        const result = await response.json();
                        const template = result.template || result;
                        template.product = this.selectedProduct;
                        this.symbolTemplates.push(template);
                        this.closeSymbolModal();
                    }
                } catch (err) {
                    console.error('Failed to create symbol template:', err);
                }
            },

            closeSymbolModal() {
                this.showSymbolModal = false;
                this.symbolSelectionBox = null;
                this.productSearchQuery = '';
                this.productSearchResults = [];
                this.selectedProduct = null;
                this.productSearchPage = 1;
                this.render();
            },

            // === AI DETECTION ===

            async detectSymbols() {
                if (this.symbolTemplates.length === 0) { alert('Create at least one symbol template first'); return; }
                this.detecting = true;
                try {
                    const response = await fetch(`/quotebuilder/api/projects/${projectId}/documents/${documentId}/detect-symbols-ai`, {
                        method: 'POST',
                        headers: { 'Content-Type': 'application/json' },
                        body: JSON.stringify({ room_id: this.activeRoom?.id || null })
                    });
                    if (response.ok) {
                        const data = await response.json();
                        const newDets = data.detections || [];
                        newDets.forEach(d => {
                            if (!this.detections.some(ex => Math.abs(ex.x - d.x) < 30 && Math.abs(ex.y - d.y) < 30)) {
                                this.detections.push(d);
                            }
                        });
                        this.render();
                        alert(`Found ${newDets.length} symbols`);
                    } else {
                        const err = await response.json();
                        alert(`Detection failed: ${err.error || 'Unknown error'}`);
                    }
                } catch (err) {
                    alert('Detection failed: ' + err.message);
                } finally {
                    this.detecting = false;
                }
            },

            // === LEGEND PARSING ===

            async parseLegend() {
                this.parsingLegend = true;
                try {
                    const response = await fetch(`/quotebuilder/api/projects/${projectId}/documents/${documentId}/parse-legend`, {
                        method: 'POST',
                        headers: { 'Content-Type': 'application/json' },
                        body: JSON.stringify({})
                    });
                    if (response.ok) {
                        const data = await response.json();
                        this.legendTemplates = data.templates || [];
                        this.showLegendModal = true;
                        const tRes = await fetch(`/quotebuilder/api/projects/${projectId}/documents/${documentId}/symbol-templates`);
                        if (tRes.ok) {
                            const tData = await tRes.json();
                            this.symbolTemplates = tData.templates || tData || [];
                        }
                    } else {
                        const err = await response.json();
                        alert(`Legend parsing failed: ${err.error}`);
                    }
                } catch (err) {
                    alert('Legend parsing failed: ' + err.message);
                } finally {
                    this.parsingLegend = false;
                }
            },

            // === SCALE ===

            startCalibration() {
                this.mode = 'calibrate';
                this.calibrationPoints = [];
                this.canvas.style.cursor = 'crosshair';
            },

            handleCalibrateClick(imgCoords) {
                this.calibrationPoints.push(imgCoords);
                if (this.calibrationPoints.length === 2) {
                    this.showCalibrationModal = true;
                    this.mode = 'select';
                    this.canvas.style.cursor = 'grab';
                }
                this.render();
            },

            async saveCalibration() {
                if (!this.calibrationDistance || this.calibrationPoints.length !== 2) return;
                const [p1, p2] = this.calibrationPoints;
                const pxDist = Math.sqrt(Math.pow(p2.x - p1.x, 2) + Math.pow(p2.y - p1.y, 2));
                this.pxPerMetre = pxDist / this.calibrationDistance;
                try {
                    await fetch(`/quotebuilder/api/projects/${projectId}/documents/${documentId}/scale`, {
                        method: 'POST',
                        headers: { 'Content-Type': 'application/json' },
                        body: JSON.stringify({ px_per_metre: this.pxPerMetre })
                    });
                    this.scaleCalibrated = true;
                    this.showCalibrationModal = false;
                    this.calibrationPoints = [];
                    this.calibrationDistance = null;
                    this.render();
                } catch (err) {
                    console.error('Failed to save scale:', err);
                }
            },

            // === ROOMS ===

            handleRoomClick(imgCoords) { this.currentRoomPoints.push(imgCoords); this.render(); },

            finishRoom() { if (this.currentRoomPoints.length >= 3) this.showRoomModal = true; },

            async saveRoom() {
                if (!this.newRoomName || this.currentRoomPoints.length < 3) return;
                try {
                    const response = await fetch(`/quotebuilder/api/projects/${projectId}/documents/${documentId}/rooms`, {
                        method: 'POST',
                        headers: { 'Content-Type': 'application/json' },
                        body: JSON.stringify({ name: this.newRoomName, points: this.currentRoomPoints })
                    });
                    if (response.ok) {
                        const data = await response.json();
                        const room = data.room || data;
                        this.rooms.push(room);
                        this.showRoomModal = false;
                        this.currentRoomPoints = [];
                        this.newRoomName = '';
                        this.mode = 'select';
                        this.selectRoom(room);
                    }
                } catch (err) {
                    console.error('Failed to save room:', err);
                }
            },

            selectRoom(room) {
                this.selectedRoom = room;
                this.activeRoom = room;
                this.showRoomPanel = true;
                this.zoomToRoom(room);
            },

            exitRoom() {
                this.activeRoom = null;
                this.selectedRoom = null;
                this.showRoomPanel = false;
                this.resetView();
            },

            calculateRoomArea(room) {
                if (!this.scaleCalibrated || !room?.points || room.points.length < 3) return null;
                let area = 0;
                const n = room.points.length;
                for (let i = 0; i < n; i++) {
                    const j = (i + 1) % n;
                    area += room.points[i].x * room.points[j].y;
                    area -= room.points[j].x * room.points[i].y;
                }
                return Math.abs(area) / 2 / (this.pxPerMetre * this.pxPerMetre);
            },

            getRoomDetections(room) {
                if (!room?.points) return [];
                return this.detections.filter(d => this.pointInPolygon({ x: d.x + d.width / 2, y: d.y + d.height / 2 }, room.points));
            },

            getRoomCables(room) {
                if (!room?.points) return [];
                return this.cableRuns.filter(c => this.pointInPolygon({ x: (c.start_x + c.end_x) / 2, y: (c.start_y + c.end_y) / 2 }, room.points));
            },

            pointInPolygon(point, polygon) {
                if (!polygon || polygon.length < 3) return false;
                let inside = false;
                for (let i = 0, j = polygon.length - 1; i < polygon.length; j = i++) {
                    const xi = polygon[i].x, yi = polygon[i].y;
                    const xj = polygon[j].x, yj = polygon[j].y;
                    if (((yi > point.y) !== (yj > point.y)) && (point.x < (xj - xi) * (point.y - yi) / (yj - yi) + xi)) inside = !inside;
                }
                return inside;
            },

            // === SELECT ===

            handleSelectClick(imgCoords) {
                const det = this.findDetectionAt(imgCoords);
                if (det) { this.selectedDetection = det; this.selectedRoom = null; this.render(); return; }
                const room = this.findRoomAt(imgCoords);
                if (room) { this.selectRoom(room); return; }
                this.selectedDetection = null;
                this.selectedRoom = null;
                this.render();
            },

            findDetectionAt(imgCoords) {
                const r = 20 / this.zoom;
                return this.detections.find(d => Math.abs(imgCoords.x - (d.x + d.width / 2)) < d.width / 2 + r && Math.abs(imgCoords.y - (d.y + d.height / 2)) < d.height / 2 + r);
            },

            findRoomAt(imgCoords) {
                return this.rooms.find(room => room.points && this.pointInPolygon(imgCoords, room.points));
            },

            async deleteDetection(det) {
                if (!confirm('Delete this detection?')) return;
                try {
                    await fetch(`/quotebuilder/api/projects/${projectId}/detections/${det.id}`, { method: 'DELETE' });
                    this.detections = this.detections.filter(d => d.id !== det.id);
                    this.selectedDetection = null;
                    this.render();
                } catch (err) {
                    console.error('Failed to delete detection:', err);
                }
            },

            // === CABLES ===

            handleCableClick(imgCoords) {
                if (!this.cableStartPoint) { this.cableStartPoint = imgCoords; }
                else { this.saveCableRun(imgCoords); }
                this.render();
            },

            async saveCableRun(endPoint) {
                const pxLen = Math.sqrt(Math.pow(endPoint.x - this.cableStartPoint.x, 2) + Math.pow(endPoint.y - this.cableStartPoint.y, 2));
                const lenM = this.scaleCalibrated ? pxLen / this.pxPerMetre : null;
                try {
                    const response = await fetch(`/quotebuilder/api/projects/${projectId}/documents/${documentId}/cable-runs`, {
                        method: 'POST',
                        headers: { 'Content-Type': 'application/json' },
                        body: JSON.stringify({ start_x: this.cableStartPoint.x, start_y: this.cableStartPoint.y, end_x: endPoint.x, end_y: endPoint.y, length_metres: lenM, room_id: this.activeRoom?.id || null })
                    });
                    if (response.ok) {
                        const data = await response.json();
                        this.cableRuns.push(data.cable_run || data);
                        this.cableStartPoint = null;
                        this.render();
                    }
                } catch (err) {
                    console.error('Failed to save cable run:', err);
                }
            },

            // === SUMMARY ===

            getSummaryByRoom() {
                if (!Array.isArray(this.rooms)) return [];
                const summary = [];
                this.rooms.forEach(room => {
                    if (!room?.points) return;
                    const dets = this.getRoomDetections(room);
                    const cables = this.getRoomCables(room);
                    const byT = {};
                    dets.forEach(d => { const k = d.template_name || 'Unknown'; if (!byT[k]) byT[k] = { name: k, count: 0, category: d.category }; byT[k].count++; });
                    summary.push({ room, area: this.calculateRoomArea(room), items: Object.values(byT), totalCableLength: cables.reduce((s, c) => s + (c.length_metres || 0), 0) });
                });
                const unassigned = Array.isArray(this.detections) ? this.detections.filter(d => !this.rooms.some(r => r.points && this.pointInPolygon({ x: d.x + d.width / 2, y: d.y + d.height / 2 }, r.points))) : [];
                if (unassigned.length > 0) {
                    const byT = {};
                    unassigned.forEach(d => { const k = d.template_name || 'Unknown'; if (!byT[k]) byT[k] = { name: k, count: 0 }; byT[k].count++; });
                    summary.push({ room: { name: 'Unassigned', id: null }, area: null, items: Object.values(byT), totalCableLength: 0 });
                }
                return summary;
            },

            // === RENDERING ===

            render() {
                if (!this.ctx || !this.canvas) return;
                const container = this.canvas.parentElement;
                const cw = container.clientWidth;
                const ch = container.clientHeight;
                const dpr = window.devicePixelRatio || 1;

                if (this.canvas.width !== cw * dpr || this.canvas.height !== ch * dpr) {
                    this.canvas.width = cw * dpr;
                    this.canvas.height = ch * dpr;
                    this.canvas.style.width = cw + 'px';
                    this.canvas.style.height = ch + 'px';
                }

                this.ctx.save();
                this.ctx.setTransform(dpr, 0, 0, dpr, 0, 0);

                // Background
                this.ctx.fillStyle = '#0c0c18';
                this.ctx.fillRect(0, 0, cw, ch);

                if (!this.imageLoaded) { this.ctx.restore(); return; }

                this.ctx.save();
                this.ctx.translate(this.panX, this.panY);
                this.ctx.scale(this.zoom, this.zoom);

                // Shadow behind drawing
                this.ctx.shadowColor = 'rgba(0,0,0,0.5)';
                this.ctx.shadowBlur = 30;
                this.ctx.shadowOffsetX = 0;
                this.ctx.shadowOffsetY = 4;
                this.ctx.drawImage(this.image, 0, 0);
                this.ctx.shadowColor = 'transparent';

                // Overlays
                if (Array.isArray(this.rooms)) this.rooms.forEach(r => this.drawRoom(r));
                if (this.currentRoomPoints.length > 0) this.drawRoomPoints(this.currentRoomPoints, 'rgba(255,200,0,0.3)', '#ffcc00');
                if (Array.isArray(this.cableRuns)) this.cableRuns.forEach(c => this.drawCable(c));
                if (Array.isArray(this.detections)) this.detections.forEach(d => this.drawDetection(d));
                this.drawCalibration();
                if (this.symbolSelectionBox) this.drawSelectionBox();
                if (this.cableStartPoint) this.drawCableStart();

                this.ctx.restore();

                // HUD
                this.drawZoomIndicator();
                if (this.scaleCalibrated) this.drawScaleBar();

                this.ctx.restore();
            },

            drawRoom(room) {
                if (!room.points || room.points.length < 3) return;
                const isActive = this.activeRoom?.id === room.id;
                const isSelected = this.selectedRoom?.id === room.id;
                const fill = isActive ? 'rgba(74,222,128,0.15)' : isSelected ? 'rgba(100,200,255,0.2)' : 'rgba(100,200,255,0.08)';
                const stroke = isActive ? '#4ade80' : isSelected ? '#64c8ff' : '#4488aa';

                this.ctx.beginPath();
                this.ctx.moveTo(room.points[0].x, room.points[0].y);
                room.points.slice(1).forEach(p => this.ctx.lineTo(p.x, p.y));
                this.ctx.closePath();
                this.ctx.fillStyle = fill;
                this.ctx.fill();
                this.ctx.strokeStyle = stroke;
                this.ctx.lineWidth = (isActive ? 3 : 2) / this.zoom;
                this.ctx.stroke();

                const cx = room.points.reduce((s, p) => s + p.x, 0) / room.points.length;
                const cy = room.points.reduce((s, p) => s + p.y, 0) / room.points.length;
                const fs = Math.max(12, 14 / this.zoom);
                this.ctx.fillStyle = '#fff';
                this.ctx.font = `600 ${fs}px -apple-system, BlinkMacSystemFont, sans-serif`;
                this.ctx.textAlign = 'center';
                this.ctx.textBaseline = 'middle';
                this.ctx.fillText(room.name, cx, cy);

                if (this.scaleCalibrated) {
                    const area = this.calculateRoomArea(room);
                    if (area) {
                        this.ctx.fillStyle = 'rgba(200,200,200,0.8)';
                        this.ctx.font = `${Math.max(10, 12 / this.zoom)}px -apple-system, BlinkMacSystemFont, sans-serif`;
                        this.ctx.fillText(`${area.toFixed(2)} m²`, cx, cy + fs * 1.2);
                    }
                }
            },

            drawRoomPoints(points, fill, stroke) {
                this.ctx.beginPath();
                this.ctx.moveTo(points[0].x, points[0].y);
                points.slice(1).forEach(p => this.ctx.lineTo(p.x, p.y));
                this.ctx.closePath();
                this.ctx.fillStyle = fill;
                this.ctx.fill();
                this.ctx.strokeStyle = stroke;
                this.ctx.lineWidth = 2 / this.zoom;
                this.ctx.stroke();
                points.forEach(p => {
                    this.ctx.beginPath();
                    this.ctx.arc(p.x, p.y, 5 / this.zoom, 0, Math.PI * 2);
                    this.ctx.fillStyle = stroke;
                    this.ctx.fill();
                    this.ctx.strokeStyle = '#fff';
                    this.ctx.lineWidth = 1 / this.zoom;
                    this.ctx.stroke();
                });
            },

            drawRoomPreview(currentPoint) {
                if (this.currentRoomPoints.length === 0) return;
                this.ctx.save();
                this.ctx.translate(this.panX, this.panY);
                this.ctx.scale(this.zoom, this.zoom);
                this.ctx.beginPath();
                this.ctx.setLineDash([5 / this.zoom, 5 / this.zoom]);
                const last = this.currentRoomPoints[this.currentRoomPoints.length - 1];
                this.ctx.moveTo(last.x, last.y);
                this.ctx.lineTo(currentPoint.x, currentPoint.y);
                this.ctx.strokeStyle = '#ffcc00';
                this.ctx.lineWidth = 2 / this.zoom;
                this.ctx.stroke();
                this.ctx.setLineDash([]);
                this.ctx.restore();
            },

            drawCable(cable) {
                this.ctx.beginPath();
                this.ctx.moveTo(cable.start_x, cable.start_y);
                this.ctx.lineTo(cable.end_x, cable.end_y);
                this.ctx.strokeStyle = '#38bdf8';
                this.ctx.lineWidth = 3 / this.zoom;
                this.ctx.stroke();
                [{ x: cable.start_x, y: cable.start_y }, { x: cable.end_x, y: cable.end_y }].forEach(p => {
                    this.ctx.beginPath();
                    this.ctx.arc(p.x, p.y, 5 / this.zoom, 0, Math.PI * 2);
                    this.ctx.fillStyle = '#38bdf8';
                    this.ctx.fill();
                });
                if (cable.length_metres) {
                    const mx = (cable.start_x + cable.end_x) / 2;
                    const my = (cable.start_y + cable.end_y) / 2;
                    this.ctx.fillStyle = '#fff';
                    this.ctx.font = `500 ${Math.max(10, 12 / this.zoom)}px -apple-system, sans-serif`;
                    this.ctx.textAlign = 'center';
                    this.ctx.fillText(`${cable.length_metres.toFixed(2)}m`, mx, my - 10 / this.zoom);
                }
            },

            drawCablePreview(currentPoint) {
                if (!this.cableStartPoint) return;
                this.ctx.save();
                this.ctx.translate(this.panX, this.panY);
                this.ctx.scale(this.zoom, this.zoom);
                this.ctx.beginPath();
                this.ctx.setLineDash([5 / this.zoom, 5 / this.zoom]);
                this.ctx.moveTo(this.cableStartPoint.x, this.cableStartPoint.y);
                this.ctx.lineTo(currentPoint.x, currentPoint.y);
                this.ctx.strokeStyle = '#38bdf8';
                this.ctx.lineWidth = 2 / this.zoom;
                this.ctx.stroke();
                this.ctx.setLineDash([]);
                this.ctx.restore();
            },

            drawDetection(d) {
                const isSel = this.selectedDetection?.id === d.id;
                let col = isSel ? '#f87171' : d.product_id ? '#4ade80' : '#fbbf24';
                if (d.colour) { const cm = { blue: '#3b82f6', red: '#ef4444', black: '#666', green: '#22c55e' }; col = cm[d.colour] || col; }

                this.ctx.strokeStyle = col;
                this.ctx.lineWidth = (isSel ? 3 : 2) / this.zoom;
                this.ctx.strokeRect(d.x, d.y, d.width, d.height);

                let label = d.template_name || 'Unknown';
                if (d.gang_count) label += ` (${d.gang_count}G)`;
                if (d.is_dimmer) label += ' D';

                const fs = Math.max(9, 11 / this.zoom);
                this.ctx.font = `500 ${fs}px -apple-system, sans-serif`;
                const lw = this.ctx.measureText(label).width + 8 / this.zoom;
                const lh = fs + 6 / this.zoom;
                const lx = d.x, ly = d.y - lh - 2 / this.zoom;
                const r = 3 / this.zoom;

                this.ctx.fillStyle = col;
                this.ctx.beginPath();
                this.ctx.moveTo(lx + r, ly); this.ctx.lineTo(lx + lw - r, ly);
                this.ctx.arcTo(lx + lw, ly, lx + lw, ly + r, r); this.ctx.lineTo(lx + lw, ly + lh - r);
                this.ctx.arcTo(lx + lw, ly + lh, lx + lw - r, ly + lh, r); this.ctx.lineTo(lx + r, ly + lh);
                this.ctx.arcTo(lx, ly + lh, lx, ly + lh - r, r); this.ctx.lineTo(lx, ly + r);
                this.ctx.arcTo(lx, ly, lx + r, ly, r);
                this.ctx.fill();

                this.ctx.fillStyle = '#000';
                this.ctx.textBaseline = 'middle';
                this.ctx.fillText(label, lx + 4 / this.zoom, ly + lh / 2);
            },

            drawCalibration() {
                this.calibrationPoints.forEach(p => {
                    this.ctx.beginPath();
                    this.ctx.arc(p.x, p.y, 8 / this.zoom, 0, Math.PI * 2);
                    this.ctx.fillStyle = 'rgba(248,113,113,0.9)';
                    this.ctx.fill();
                    this.ctx.strokeStyle = '#fff';
                    this.ctx.lineWidth = 2 / this.zoom;
                    this.ctx.stroke();
                });
                if (this.calibrationPoints.length === 2) {
                    this.ctx.beginPath();
                    this.ctx.moveTo(this.calibrationPoints[0].x, this.calibrationPoints[0].y);
                    this.ctx.lineTo(this.calibrationPoints[1].x, this.calibrationPoints[1].y);
                    this.ctx.strokeStyle = '#f87171';
                    this.ctx.lineWidth = 3 / this.zoom;
                    this.ctx.setLineDash([10 / this.zoom, 5 / this.zoom]);
                    this.ctx.stroke();
                    this.ctx.setLineDash([]);
                }
            },

            drawSelectionBox() {
                this.ctx.strokeStyle = '#4ade80';
                this.ctx.lineWidth = 2 / this.zoom;
                this.ctx.setLineDash([6 / this.zoom, 4 / this.zoom]);
                this.ctx.strokeRect(this.symbolSelectionBox.x, this.symbolSelectionBox.y, this.symbolSelectionBox.width, this.symbolSelectionBox.height);
                this.ctx.setLineDash([]);
                this.ctx.fillStyle = 'rgba(74,222,128,0.1)';
                this.ctx.fillRect(this.symbolSelectionBox.x, this.symbolSelectionBox.y, this.symbolSelectionBox.width, this.symbolSelectionBox.height);
            },

            drawCableStart() {
                this.ctx.beginPath();
                this.ctx.arc(this.cableStartPoint.x, this.cableStartPoint.y, 6 / this.zoom, 0, Math.PI * 2);
                this.ctx.fillStyle = '#38bdf8';
                this.ctx.fill();
                this.ctx.strokeStyle = '#fff';
                this.ctx.lineWidth = 1.5 / this.zoom;
                this.ctx.stroke();
            },

            drawZoomIndicator() {
                const cw = this.canvas.parentElement.clientWidth;
                const ch = this.canvas.parentElement.clientHeight;
                const text = `${Math.round(this.zoom * 100)}%`;
                this.ctx.font = '600 12px -apple-system, BlinkMacSystemFont, sans-serif';
                const tw = this.ctx.measureText(text).width;
                const px = 16, py = ch - 16, pad = 10, h = 28, w = tw + pad * 2;

                this.ctx.fillStyle = 'rgba(12,12,24,0.85)';
                this.ctx.beginPath();
                this.ctx.roundRect(px, py - h, w, h, 6);
                this.ctx.fill();
                this.ctx.strokeStyle = 'rgba(255,255,255,0.1)';
                this.ctx.lineWidth = 1;
                this.ctx.stroke();

                this.ctx.fillStyle = 'rgba(255,255,255,0.7)';
                this.ctx.textAlign = 'left';
                this.ctx.textBaseline = 'middle';
                this.ctx.fillText(text, px + pad, py - h / 2);
            },

            drawScaleBar() {
                const cw = this.canvas.parentElement.clientWidth;
                const ch = this.canvas.parentElement.clientHeight;
                const scaleM = this.zoom > 0.5 ? 1 : this.zoom > 0.2 ? 2 : 5;
                const scalePx = scaleM * this.pxPerMetre * this.zoom;
                const x = cw - scalePx - 30;
                const y = ch - 20;

                this.ctx.fillStyle = 'rgba(12,12,24,0.85)';
                this.ctx.beginPath();
                this.ctx.roundRect(x - 12, y - 28, scalePx + 24, 40, 6);
                this.ctx.fill();
                this.ctx.strokeStyle = 'rgba(255,255,255,0.1)';
                this.ctx.lineWidth = 1;
                this.ctx.stroke();

                this.ctx.strokeStyle = 'rgba(255,255,255,0.8)';
                this.ctx.lineWidth = 2;
                this.ctx.beginPath();
                this.ctx.moveTo(x, y); this.ctx.lineTo(x + scalePx, y);
                this.ctx.moveTo(x, y - 4); this.ctx.lineTo(x, y + 4);
                this.ctx.moveTo(x + scalePx, y - 4); this.ctx.lineTo(x + scalePx, y + 4);
                this.ctx.stroke();

                this.ctx.fillStyle = 'rgba(255,255,255,0.7)';
                this.ctx.font = '500 11px -apple-system, BlinkMacSystemFont, sans-serif';
                this.ctx.textAlign = 'center';
                this.ctx.textBaseline = 'bottom';
                this.ctx.fillText(`${scaleM}m`, x + scalePx / 2, y - 6);
            }
        };
    });
});
