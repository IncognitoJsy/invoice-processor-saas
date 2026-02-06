/**
 * GoZappify Takeoff Canvas - Version 4
 * AI-powered symbol detection using Claude Vision
 * Handles colours, text, gang counts, dimmers
 */

document.addEventListener('alpine:init', () => {
    Alpine.data('takeoffCanvas', function() {
        return {
            // ... (keeping all previous state from v3)
            
            // Canvas state
            canvas: null,
            ctx: null,
            image: null,
            imageLoaded: false,
            loading: true,
            error: null,
            
            // Zoom and pan
            zoom: 1,
            minZoom: 0.1,
            maxZoom: 5,
            panX: 0,
            panY: 0,
            isPanning: false,
            lastPanX: 0,
            lastPanY: 0,
            
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
            
            // Symbol templates - ENHANCED
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
            
            // NEW: Enhanced symbol fields
            symbolColour: '',
            symbolExpectedText: '',
            symbolGangCount: null,
            symbolIsDimmer: false,
            symbolDescription: '',
            
            // Colour options for PIR sensors etc
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
            detectionMethod: 'ai', // 'ai' or 'opencv'
            
            // Cable runs
            cableRuns: [],
            cableStartPoint: null,
            
            // Summary
            showSummary: false,
            
            // Legend parsing
            parsingLegend: false,
            showLegendModal: false,
            legendTemplates: [],
            
            init() {
                this.canvas = this.$refs.canvas;
                this.ctx = this.canvas.getContext('2d');
                this.loadDrawing();
                this.loadExistingData();
                this.setupEventListeners();
            },
            
            setupEventListeners() {
                // Mouse wheel zoom
                this.canvas.addEventListener('wheel', (e) => {
                    e.preventDefault();
                    const rect = this.canvas.getBoundingClientRect();
                    const mouseX = e.clientX - rect.left;
                    const mouseY = e.clientY - rect.top;
                    
                    const zoomFactor = e.deltaY > 0 ? 0.9 : 1.1;
                    const newZoom = Math.max(this.minZoom, Math.min(this.maxZoom, this.zoom * zoomFactor));
                    
                    if (newZoom !== this.zoom) {
                        const scale = newZoom / this.zoom;
                        this.panX = mouseX - (mouseX - this.panX) * scale;
                        this.panY = mouseY - (mouseY - this.panY) * scale;
                        this.zoom = newZoom;
                        this.render();
                    }
                }, { passive: false });
                
                document.addEventListener('keydown', (e) => {
                    if (e.target.tagName === 'INPUT' || e.target.tagName === 'TEXTAREA') return;
                    
                    if (e.key === 'Escape') this.cancelCurrentAction();
                    else if (e.key === '+' || e.key === '=') this.zoomIn();
                    else if (e.key === '-') this.zoomOut();
                    else if (e.key === '0') this.resetView();
                    else if (e.key === 'Delete' && this.selectedDetection) this.deleteDetection(this.selectedDetection);
                });
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
                    const [templatesRes, roomsRes, detectionsRes, cablesRes, stateRes] = await Promise.all([
                        fetch(`/quotebuilder/api/projects/${projectId}/documents/${documentId}/symbol-templates`),
                        fetch(`/quotebuilder/api/projects/${projectId}/documents/${documentId}/rooms`),
                        fetch(`/quotebuilder/api/projects/${projectId}/documents/${documentId}/detections`),
                        fetch(`/quotebuilder/api/projects/${projectId}/documents/${documentId}/cable-runs`),
                        fetch(`/quotebuilder/api/projects/${projectId}/documents/${documentId}/takeoff-state`)
                    ]);
                    
                    if (templatesRes.ok) this.symbolTemplates = await templatesRes.json();
                    if (roomsRes.ok) this.rooms = await roomsRes.json();
                    if (detectionsRes.ok) this.detections = await detectionsRes.json();
                    if (cablesRes.ok) this.cableRuns = await cablesRes.json();
                    if (stateRes.ok) {
                        const state = await stateRes.json();
                        if (state.px_per_metre) {
                            this.pxPerMetre = state.px_per_metre;
                            this.scaleCalibrated = true;
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
                const scaleX = container.clientWidth / this.image.width;
                const scaleY = container.clientHeight / this.image.height;
                this.zoom = Math.min(scaleX, scaleY) * 0.95;
                this.panX = (container.clientWidth - this.image.width * this.zoom) / 2;
                this.panY = (container.clientHeight - this.image.height * this.zoom) / 2;
            },
            
            zoomIn() { this.zoomTo(Math.min(this.maxZoom, this.zoom * 1.25)); },
            zoomOut() { this.zoomTo(Math.max(this.minZoom, this.zoom / 1.25)); },
            
            zoomTo(newZoom) {
                const centerX = this.canvas.width / 2;
                const centerY = this.canvas.height / 2;
                const scale = newZoom / this.zoom;
                this.panX = centerX - (centerX - this.panX) * scale;
                this.panY = centerY - (centerY - this.panY) * scale;
                this.zoom = newZoom;
                this.render();
            },
            
            resetView() { this.fitToScreen(); this.render(); },
            
            zoomToRoom(room) {
                if (!room.points || room.points.length < 3) return;
                const xs = room.points.map(p => p.x);
                const ys = room.points.map(p => p.y);
                const minX = Math.min(...xs), maxX = Math.max(...xs);
                const minY = Math.min(...ys), maxY = Math.max(...ys);
                const container = this.canvas.parentElement;
                const scaleX = container.clientWidth / (maxX - minX + 200);
                const scaleY = container.clientHeight / (maxY - minY + 200);
                this.zoom = Math.min(scaleX, scaleY, this.maxZoom);
                this.panX = container.clientWidth / 2 - ((minX + maxX) / 2) * this.zoom;
                this.panY = container.clientHeight / 2 - ((minY + maxY) / 2) * this.zoom;
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
                
                if (e.button === 1 || (e.button === 0 && e.shiftKey)) {
                    this.isPanning = true;
                    this.lastPanX = e.clientX;
                    this.lastPanY = e.clientY;
                    this.canvas.style.cursor = 'grabbing';
                    return;
                }
                
                if (e.button !== 0) return;
                
                switch (this.mode) {
                    case 'select': this.handleSelectClick(imgCoords); break;
                    case 'calibrate': this.handleCalibrateClick(imgCoords); break;
                    case 'room': this.handleRoomClick(imgCoords); break;
                    case 'symbol':
                        this.isSelectingSymbol = true;
                        this.symbolSelectionStart = imgCoords;
                        this.symbolSelectionBox = { x: imgCoords.x, y: imgCoords.y, width: 0, height: 0 };
                        break;
                    case 'cable': this.handleCableClick(imgCoords); break;
                }
            },
            
            handleMouseMove(e) {
                const rect = this.canvas.getBoundingClientRect();
                const screenX = e.clientX - rect.left;
                const screenY = e.clientY - rect.top;
                
                if (this.isPanning) {
                    this.panX += e.clientX - this.lastPanX;
                    this.panY += e.clientY - this.lastPanY;
                    this.lastPanX = e.clientX;
                    this.lastPanY = e.clientY;
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
                    return;
                }
                
                if (this.isSelectingSymbol && this.symbolSelectionBox) {
                    if (this.symbolSelectionBox.width > 10 && this.symbolSelectionBox.height > 10) {
                        this.openSymbolModal();
                    }
                    this.isSelectingSymbol = false;
                }
            },
            
            getCursorForMode() {
                return { calibrate: 'crosshair', symbol: 'crosshair', room: 'crosshair', cable: 'crosshair' }[this.mode] || 'default';
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
                this.render();
            },
            
            // === SYMBOL TEMPLATES - ENHANCED ===
            
            openSymbolModal() {
                this.showSymbolModal = true;
                this.productSearchQuery = '';
                this.productSearchResults = [];
                this.selectedProduct = null;
                this.selectedCategory = 'socket';
                // Reset enhanced fields
                this.symbolColour = '';
                this.symbolExpectedText = '';
                this.symbolGangCount = null;
                this.symbolIsDimmer = false;
                this.symbolDescription = '';
            },
            
            async searchProducts() {
                if (!this.productSearchQuery || this.productSearchQuery.length < 2) {
                    this.productSearchResults = [];
                    return;
                }
                
                this.productSearchLoading = true;
                try {
                    const response = await fetch(
                        `/quotebuilder/api/products/search?q=${encodeURIComponent(this.productSearchQuery)}&page=${this.productSearchPage}&limit=20`
                    );
                    if (response.ok) {
                        const data = await response.json();
                        this.productSearchResults = this.productSearchPage === 1 
                            ? (data.products || data) 
                            : [...this.productSearchResults, ...(data.products || data)];
                        this.productSearchHasMore = data.has_more || false;
                    }
                } catch (err) {
                    console.error('Product search failed:', err);
                } finally {
                    this.productSearchLoading = false;
                }
            },
            
            loadMoreProducts() {
                this.productSearchPage++;
                this.searchProducts();
            },
            
            selectProduct(product) {
                this.selectedProduct = product;
            },
            
            async createSymbolTemplate() {
                if (!this.symbolSelectionBox || !this.selectedProduct) {
                    alert('Please select a product');
                    return;
                }
                
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
                            // Enhanced fields
                            colour: this.symbolColour || null,
                            expected_text: this.symbolExpectedText || null,
                            gang_count: this.symbolGangCount || null,
                            is_dimmer: this.symbolIsDimmer
                        })
                    });
                    
                    if (response.ok) {
                        const template = await response.json();
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
            
            // === AI SYMBOL DETECTION ===
            
            async detectSymbols() {
                if (this.symbolTemplates.length === 0) {
                    alert('Please create at least one symbol template first');
                    return;
                }
                
                this.detecting = true;
                
                try {
                    // Use AI-powered detection
                    const response = await fetch(`/quotebuilder/api/projects/${projectId}/documents/${documentId}/detect-symbols-ai`, {
                        method: 'POST',
                        headers: { 'Content-Type': 'application/json' },
                        body: JSON.stringify({
                            room_id: this.activeRoom?.id || null
                        })
                    });
                    
                    if (response.ok) {
                        const data = await response.json();
                        const newDetections = data.detections || [];
                        
                        // Merge avoiding duplicates
                        newDetections.forEach(d => {
                            const exists = this.detections.some(existing => 
                                Math.abs(existing.x - d.x) < 30 && Math.abs(existing.y - d.y) < 30
                            );
                            if (!exists) {
                                this.detections.push(d);
                            }
                        });
                        
                        this.render();
                        
                        // Show summary
                        alert(`Found ${newDetections.length} symbols using AI detection`);
                    } else {
                        const err = await response.json();
                        alert(`Detection failed: ${err.error || 'Unknown error'}`);
                    }
                } catch (err) {
                    console.error('Failed to detect symbols:', err);
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
                        
                        // Reload templates
                        const templatesRes = await fetch(`/quotebuilder/api/projects/${projectId}/documents/${documentId}/symbol-templates`);
                        if (templatesRes.ok) {
                            this.symbolTemplates = await templatesRes.json();
                        }
                    } else {
                        const err = await response.json();
                        alert(`Legend parsing failed: ${err.error}`);
                    }
                } catch (err) {
                    console.error('Legend parsing failed:', err);
                    alert('Legend parsing failed: ' + err.message);
                } finally {
                    this.parsingLegend = false;
                }
            },
            
            // === REST OF METHODS (rooms, cables, rendering, etc.) ===
            // ... (same as v3 - keeping this comment brief)
            
            // Scale calibration
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
                    this.canvas.style.cursor = 'default';
                }
                this.render();
            },
            
            async saveCalibration() {
                if (!this.calibrationDistance || this.calibrationPoints.length !== 2) return;
                const [p1, p2] = this.calibrationPoints;
                const pixelDistance = Math.sqrt(Math.pow(p2.x - p1.x, 2) + Math.pow(p2.y - p1.y, 2));
                this.pxPerMetre = pixelDistance / this.calibrationDistance;
                
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
            
            // Rooms
            handleRoomClick(imgCoords) {
                this.currentRoomPoints.push(imgCoords);
                this.render();
            },
            
            finishRoom() {
                if (this.currentRoomPoints.length >= 3) {
                    this.showRoomModal = true;
                }
            },
            
            async saveRoom() {
                if (!this.newRoomName || this.currentRoomPoints.length < 3) return;
                
                try {
                    const response = await fetch(`/quotebuilder/api/projects/${projectId}/documents/${documentId}/rooms`, {
                        method: 'POST',
                        headers: { 'Content-Type': 'application/json' },
                        body: JSON.stringify({ name: this.newRoomName, points: this.currentRoomPoints })
                    });
                    
                    if (response.ok) {
                        const room = await response.json();
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
                return this.detections.filter(d => {
                    const cx = d.x + d.width / 2;
                    const cy = d.y + d.height / 2;
                    return this.pointInPolygon({ x: cx, y: cy }, room.points);
                });
            },
            
            getRoomCables(room) {
                if (!room?.points) return [];
                return this.cableRuns.filter(c => {
                    const mx = (c.start_x + c.end_x) / 2;
                    const my = (c.start_y + c.end_y) / 2;
                    return this.pointInPolygon({ x: mx, y: my }, room.points);
                });
            },
            
            pointInPolygon(point, polygon) {
                if (!polygon || polygon.length < 3) return false;
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
            
            // Select
            handleSelectClick(imgCoords) {
                const detection = this.findDetectionAt(imgCoords);
                if (detection) { this.selectedDetection = detection; this.selectedRoom = null; this.render(); return; }
                const room = this.findRoomAt(imgCoords);
                if (room) { this.selectRoom(room); return; }
                this.selectedDetection = null;
                this.selectedRoom = null;
                this.render();
            },
            
            findDetectionAt(imgCoords) {
                const r = 20 / this.zoom;
                return this.detections.find(d => {
                    const cx = d.x + d.width / 2, cy = d.y + d.height / 2;
                    return Math.abs(imgCoords.x - cx) < d.width / 2 + r && Math.abs(imgCoords.y - cy) < d.height / 2 + r;
                });
            },
            
            findRoomAt(imgCoords) {
                return this.rooms.find(room => this.pointInPolygon(imgCoords, room.points));
            },
            
            async deleteDetection(detection) {
                if (!confirm('Delete this detection?')) return;
                try {
                    await fetch(`/quotebuilder/api/projects/${projectId}/detections/${detection.id}`, { method: 'DELETE' });
                    this.detections = this.detections.filter(d => d.id !== detection.id);
                    this.selectedDetection = null;
                    this.render();
                } catch (err) {
                    console.error('Failed to delete detection:', err);
                }
            },
            
            // Cables
            handleCableClick(imgCoords) {
                if (!this.cableStartPoint) {
                    this.cableStartPoint = imgCoords;
                } else {
                    this.saveCableRun(imgCoords);
                }
                this.render();
            },
            
            async saveCableRun(endPoint) {
                const pixelLength = Math.sqrt(Math.pow(endPoint.x - this.cableStartPoint.x, 2) + Math.pow(endPoint.y - this.cableStartPoint.y, 2));
                const lengthMetres = this.scaleCalibrated ? pixelLength / this.pxPerMetre : null;
                
                try {
                    const response = await fetch(`/quotebuilder/api/projects/${projectId}/documents/${documentId}/cable-runs`, {
                        method: 'POST',
                        headers: { 'Content-Type': 'application/json' },
                        body: JSON.stringify({
                            start_x: this.cableStartPoint.x, start_y: this.cableStartPoint.y,
                            end_x: endPoint.x, end_y: endPoint.y,
                            length_metres: lengthMetres,
                            room_id: this.activeRoom?.id || null
                        })
                    });
                    if (response.ok) {
                        const cable = await response.json();
                        this.cableRuns.push(cable);
                        this.cableStartPoint = null;
                        this.render();
                    }
                } catch (err) {
                    console.error('Failed to save cable run:', err);
                }
            },
            
            // Summary
            getSummaryByRoom() {
                const summary = [];
                this.rooms.forEach(room => {
                    const detections = this.getRoomDetections(room);
                    const cables = this.getRoomCables(room);
                    const byTemplate = {};
                    detections.forEach(d => {
                        const k = d.template_name || 'Unknown';
                        if (!byTemplate[k]) byTemplate[k] = { name: k, count: 0, category: d.category };
                        byTemplate[k].count++;
                    });
                    summary.push({
                        room, area: this.calculateRoomArea(room),
                        items: Object.values(byTemplate),
                        totalCableLength: cables.reduce((s, c) => s + (c.length_metres || 0), 0)
                    });
                });
                
                // Unassigned
                const unassigned = this.detections.filter(d => !this.rooms.some(r => this.pointInPolygon({ x: d.x + d.width / 2, y: d.y + d.height / 2 }, r.points)));
                if (unassigned.length > 0) {
                    const byTemplate = {};
                    unassigned.forEach(d => {
                        const k = d.template_name || 'Unknown';
                        if (!byTemplate[k]) byTemplate[k] = { name: k, count: 0 };
                        byTemplate[k].count++;
                    });
                    summary.push({ room: { name: 'Unassigned', id: null }, area: null, items: Object.values(byTemplate), totalCableLength: 0 });
                }
                return summary;
            },
            
            // === RENDERING ===
            
            render() {
                if (!this.ctx || !this.canvas) return;
                const container = this.canvas.parentElement;
                this.canvas.width = container.clientWidth;
                this.canvas.height = container.clientHeight;
                
                this.ctx.fillStyle = '#0f0f1a';
                this.ctx.fillRect(0, 0, this.canvas.width, this.canvas.height);
                
                if (!this.imageLoaded) return;
                
                this.ctx.save();
                this.ctx.translate(this.panX, this.panY);
                this.ctx.scale(this.zoom, this.zoom);
                this.ctx.drawImage(this.image, 0, 0);
                
                // Draw rooms, detections, cables, etc.
                this.rooms.forEach(room => this.drawRoom(room));
                if (this.currentRoomPoints.length > 0) this.drawRoomPoints(this.currentRoomPoints, 'rgba(255,200,0,0.3)', '#ffcc00');
                this.cableRuns.forEach(cable => this.drawCable(cable));
                this.detections.forEach(detection => this.drawDetection(detection));
                this.drawCalibration();
                if (this.symbolSelectionBox) this.drawSelectionBox();
                if (this.cableStartPoint) this.drawCableStart();
                
                this.ctx.restore();
                this.drawZoomIndicator();
                if (this.scaleCalibrated) this.drawScaleBar();
            },
            
            drawRoom(room) {
                if (!room.points || room.points.length < 3) return;
                const isActive = this.activeRoom?.id === room.id;
                const isSelected = this.selectedRoom?.id === room.id;
                const fillColor = isActive ? 'rgba(100,255,150,0.2)' : isSelected ? 'rgba(100,200,255,0.25)' : 'rgba(100,200,255,0.1)';
                const strokeColor = isActive ? '#4ade80' : isSelected ? '#64c8ff' : '#4488aa';
                
                this.ctx.beginPath();
                this.ctx.moveTo(room.points[0].x, room.points[0].y);
                room.points.slice(1).forEach(p => this.ctx.lineTo(p.x, p.y));
                this.ctx.closePath();
                this.ctx.fillStyle = fillColor;
                this.ctx.fill();
                this.ctx.strokeStyle = strokeColor;
                this.ctx.lineWidth = (isActive ? 3 : 2) / this.zoom;
                this.ctx.stroke();
                
                // Label
                const cx = room.points.reduce((s, p) => s + p.x, 0) / room.points.length;
                const cy = room.points.reduce((s, p) => s + p.y, 0) / room.points.length;
                this.ctx.fillStyle = '#fff';
                this.ctx.font = `bold ${14 / this.zoom}px sans-serif`;
                this.ctx.textAlign = 'center';
                this.ctx.fillText(room.name, cx, cy);
                
                if (this.scaleCalibrated) {
                    const area = this.calculateRoomArea(room);
                    if (area) {
                        this.ctx.fillStyle = '#aaa';
                        this.ctx.font = `${12 / this.zoom}px sans-serif`;
                        this.ctx.fillText(`${area.toFixed(2)} m²`, cx, cy + 18 / this.zoom);
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
                    this.ctx.arc(p.x, p.y, 4 / this.zoom, 0, Math.PI * 2);
                    this.ctx.fillStyle = stroke;
                    this.ctx.fill();
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
                this.ctx.strokeStyle = '#00aaff';
                this.ctx.lineWidth = 3 / this.zoom;
                this.ctx.stroke();
                
                [{ x: cable.start_x, y: cable.start_y }, { x: cable.end_x, y: cable.end_y }].forEach(p => {
                    this.ctx.beginPath();
                    this.ctx.arc(p.x, p.y, 5 / this.zoom, 0, Math.PI * 2);
                    this.ctx.fillStyle = '#00aaff';
                    this.ctx.fill();
                });
                
                if (cable.length_metres) {
                    const mx = (cable.start_x + cable.end_x) / 2;
                    const my = (cable.start_y + cable.end_y) / 2;
                    this.ctx.fillStyle = '#fff';
                    this.ctx.font = `${12 / this.zoom}px sans-serif`;
                    this.ctx.textAlign = 'center';
                    this.ctx.fillText(`${cable.length_metres.toFixed(2)}m`, mx, my - 8 / this.zoom);
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
                this.ctx.strokeStyle = '#00aaff';
                this.ctx.lineWidth = 2 / this.zoom;
                this.ctx.stroke();
                this.ctx.setLineDash([]);
                this.ctx.restore();
            },
            
            drawDetection(d) {
                const isSelected = this.selectedDetection?.id === d.id;
                const hasProduct = d.product_id;
                
                // Colour based on detected colour
                let strokeColour = isSelected ? '#ff6b6b' : hasProduct ? '#00ff88' : '#ffaa00';
                if (d.colour) {
                    const colourMap = { blue: '#3b82f6', red: '#ef4444', black: '#666', green: '#22c55e' };
                    strokeColour = colourMap[d.colour] || strokeColour;
                }
                
                this.ctx.strokeStyle = strokeColour;
                this.ctx.lineWidth = (isSelected ? 3 : 2) / this.zoom;
                this.ctx.strokeRect(d.x, d.y, d.width, d.height);
                
                // Label
                let label = d.template_name || 'Unknown';
                if (d.gang_count) label += ` (${d.gang_count}G)`;
                if (d.is_dimmer) label += ' D';
                
                this.ctx.font = `${11 / this.zoom}px sans-serif`;
                const lw = this.ctx.measureText(label).width + 8 / this.zoom;
                this.ctx.fillStyle = strokeColour;
                this.ctx.fillRect(d.x, d.y - 18 / this.zoom, lw, 16 / this.zoom);
                this.ctx.fillStyle = '#000';
                this.ctx.fillText(label, d.x + 4 / this.zoom, d.y - 6 / this.zoom);
            },
            
            drawCalibration() {
                this.calibrationPoints.forEach(p => {
                    this.ctx.beginPath();
                    this.ctx.arc(p.x, p.y, 8 / this.zoom, 0, Math.PI * 2);
                    this.ctx.fillStyle = '#ff6b6b';
                    this.ctx.fill();
                    this.ctx.strokeStyle = '#fff';
                    this.ctx.lineWidth = 2 / this.zoom;
                    this.ctx.stroke();
                });
                if (this.calibrationPoints.length === 2) {
                    this.ctx.beginPath();
                    this.ctx.moveTo(this.calibrationPoints[0].x, this.calibrationPoints[0].y);
                    this.ctx.lineTo(this.calibrationPoints[1].x, this.calibrationPoints[1].y);
                    this.ctx.strokeStyle = '#ff6b6b';
                    this.ctx.lineWidth = 3 / this.zoom;
                    this.ctx.setLineDash([10 / this.zoom, 5 / this.zoom]);
                    this.ctx.stroke();
                    this.ctx.setLineDash([]);
                }
            },
            
            drawSelectionBox() {
                this.ctx.strokeStyle = '#00ff88';
                this.ctx.lineWidth = 2 / this.zoom;
                this.ctx.setLineDash([5 / this.zoom, 5 / this.zoom]);
                this.ctx.strokeRect(this.symbolSelectionBox.x, this.symbolSelectionBox.y, this.symbolSelectionBox.width, this.symbolSelectionBox.height);
                this.ctx.setLineDash([]);
            },
            
            drawCableStart() {
                this.ctx.beginPath();
                this.ctx.arc(this.cableStartPoint.x, this.cableStartPoint.y, 6 / this.zoom, 0, Math.PI * 2);
                this.ctx.fillStyle = '#00aaff';
                this.ctx.fill();
            },
            
            drawZoomIndicator() {
                this.ctx.fillStyle = 'rgba(0,0,0,0.7)';
                this.ctx.fillRect(10, this.canvas.height - 35, 60, 25);
                this.ctx.fillStyle = '#fff';
                this.ctx.font = '14px sans-serif';
                this.ctx.textAlign = 'left';
                this.ctx.fillText(`${Math.round(this.zoom * 100)}%`, 20, this.canvas.height - 17);
            },
            
            drawScaleBar() {
                const scaleM = this.zoom > 0.5 ? 1 : this.zoom > 0.2 ? 2 : 5;
                const scalePx = scaleM * this.pxPerMetre * this.zoom;
                const x = this.canvas.width - scalePx - 20;
                const y = this.canvas.height - 20;
                
                this.ctx.fillStyle = 'rgba(0,0,0,0.7)';
                this.ctx.fillRect(x - 10, y - 25, scalePx + 20, 35);
                this.ctx.strokeStyle = '#fff';
                this.ctx.lineWidth = 3;
                this.ctx.beginPath();
                this.ctx.moveTo(x, y);
                this.ctx.lineTo(x + scalePx, y);
                this.ctx.moveTo(x, y - 5);
                this.ctx.lineTo(x, y + 5);
                this.ctx.moveTo(x + scalePx, y - 5);
                this.ctx.lineTo(x + scalePx, y + 5);
                this.ctx.stroke();
                this.ctx.fillStyle = '#fff';
                this.ctx.font = '12px sans-serif';
                this.ctx.textAlign = 'center';
                this.ctx.fillText(`${scaleM}m`, x + scalePx / 2, y - 8);
            }
        };
    });
});
