/* ═══════════════════════════════════════════════════════════════
   ROOM MARKER v2 — Multi-level floor plan room marking
   
   Data structure:
   levels: [{
     name: "Ground Floor",
     pageIndex: 0,
     image: Image object (loaded),
     buildingOutline: {points, area_sqm, perimeter_m} | null,
     rooms: [{name, points, color, border, area_sqm, width_m, length_m, perimeter_m}]
   }]
   ═══════════════════════════════════════════════════════════════ */

(function() {
    'use strict';
    
    // ── Canvas & view state ──
    let canvas, ctx, container;
    let viewX = 0, viewY = 0, viewScale = 1;
    let isDragging = false, dragStartX = 0, dragStartY = 0, dragStartViewX = 0, dragStartViewY = 0;
    
    // ── Levels ──
    let levels = [];           // Array of level objects
    let activeLevelIdx = 0;    // Which level is currently shown
    
    // ── Tools: 'room', 'outline', 'measure' ──
    let activeTool = 'room';
    
    // ── Drawing state (shared by room & outline tools) ──
    let currentPoints = [];
    let isDrawing = false;
    let hoveredPoint = -1;
    
    // ── Measure tool ──
    let measurePoints = [];
    let isMeasuring = false;
    
    // ── Selection ──
    let selectedRoomIdx = -1;
    
    // ── Scale ──
    let pxPerMetre = 0;
    let scaleRatio = 50;
    
    // ── PDF pages (loaded as Image objects) ──
    let pageImages = [];       // [{img: Image, loaded: bool}]
    
    // ── Room colours ──
    const COLORS = [
        { fill: 'rgba(99, 102, 241, 0.25)',  border: 'rgba(99, 102, 241, 0.8)' },
        { fill: 'rgba(16, 185, 129, 0.25)',  border: 'rgba(16, 185, 129, 0.8)' },
        { fill: 'rgba(245, 158, 11, 0.25)',  border: 'rgba(245, 158, 11, 0.8)' },
        { fill: 'rgba(239, 68, 68, 0.25)',   border: 'rgba(239, 68, 68, 0.8)' },
        { fill: 'rgba(168, 85, 247, 0.25)',  border: 'rgba(168, 85, 247, 0.8)' },
        { fill: 'rgba(6, 182, 212, 0.25)',   border: 'rgba(6, 182, 212, 0.8)' },
        { fill: 'rgba(236, 72, 153, 0.25)',  border: 'rgba(236, 72, 153, 0.8)' },
        { fill: 'rgba(132, 204, 22, 0.25)',  border: 'rgba(132, 204, 22, 0.8)' },
        { fill: 'rgba(251, 146, 60, 0.25)',  border: 'rgba(251, 146, 60, 0.8)' },
        { fill: 'rgba(34, 211, 238, 0.25)',  border: 'rgba(34, 211, 238, 0.8)' },
    ];
    const OUTLINE_FILL = 'rgba(255, 255, 255, 0.08)';
    const OUTLINE_BORDER = 'rgba(255, 255, 255, 0.6)';
    
    // ═══════════════════════════════════════
    // PUBLIC API
    // ═══════════════════════════════════════
    window.RoomMarker = {
        open: openMarker,
        close: closeMarker,
        getLevels: () => levels,
    };
    
    // ── Open the marker ──
    function openMarker(imageSources, existingLevels, scaleSettings) {
        // Parse scale
        if (scaleSettings) {
            const m = scaleSettings.scale_ratio?.match(/1\s*[:]\s*(\d+)/);
            scaleRatio = m ? parseInt(m[1]) : 50;
        }
        
        // Reset state
        activeTool = 'room';
        currentPoints = [];
        isDrawing = false;
        measurePoints = [];
        isMeasuring = false;
        selectedRoomIdx = -1;
        activeLevelIdx = 0;
        pageImages = [];
        
        // Show overlay
        document.getElementById('room-marker-overlay').classList.remove('hidden');
        canvas = document.getElementById('room-marker-canvas');
        ctx = canvas.getContext('2d');
        container = document.getElementById('room-marker-container');
        
        // imageSources can be a string (single image) or array of strings (multi-page)
        const sources = Array.isArray(imageSources) ? imageSources : [imageSources];
        
        // Restore existing levels or create from pages
        if (existingLevels && existingLevels.length > 0) {
            levels = existingLevels.map((lv, i) => ({
                name: lv.name || `Level ${i + 1}`,
                pageIndex: lv.pageIndex ?? i,
                buildingOutline: lv.buildingOutline || null,
                rooms: (lv.rooms || []).map((r, ri) => ({
                    ...r,
                    color: r.color || COLORS[ri % COLORS.length].fill,
                    border: r.border || COLORS[ri % COLORS.length].border,
                })),
            }));
        } else {
            levels = sources.map((_, i) => ({
                name: sources.length === 1 ? 'Ground Floor' : `Level ${i + 1}`,
                pageIndex: i,
                buildingOutline: null,
                rooms: [],
            }));
        }
        
        // Load images
        let loadedCount = 0;
        sources.forEach((src, i) => {
            const img = new Image();
            img.crossOrigin = 'anonymous';
            pageImages[i] = { img, loaded: false };
            img.onload = () => {
                pageImages[i].loaded = true;
                loadedCount++;
                if (loadedCount === 1) {
                    // First image loaded — setup canvas
                    resizeCanvas();
                    fitImageToView();
                    calculatePxPerMetre();
                    render();
                }
                if (loadedCount === sources.length) {
                    updateLevelTabs();
                }
            };
            img.src = src;
        });
        
        // Bind events
        canvas.addEventListener('mousedown', onMouseDown);
        canvas.addEventListener('mousemove', onMouseMove);
        canvas.addEventListener('mouseup', onMouseUp);
        canvas.addEventListener('wheel', onWheel, { passive: false });
        canvas.addEventListener('dblclick', onDoubleClick);
        canvas.addEventListener('contextmenu', e => e.preventDefault());
        window.addEventListener('keydown', onKeyDown);
        window.addEventListener('resize', resizeCanvas);
        
        // Touch
        canvas.addEventListener('touchstart', onTouchStart, { passive: false });
        canvas.addEventListener('touchmove', onTouchMove, { passive: false });
        canvas.addEventListener('touchend', onTouchEnd);
        
        updateUI();
    }
    
    function closeMarker() {
        document.getElementById('room-marker-overlay').classList.add('hidden');
        
        // Unbind
        if (canvas) {
            canvas.removeEventListener('mousedown', onMouseDown);
            canvas.removeEventListener('mousemove', onMouseMove);
            canvas.removeEventListener('mouseup', onMouseUp);
            canvas.removeEventListener('wheel', onWheel);
            canvas.removeEventListener('dblclick', onDoubleClick);
            canvas.removeEventListener('touchstart', onTouchStart);
            canvas.removeEventListener('touchmove', onTouchMove);
            canvas.removeEventListener('touchend', onTouchEnd);
        }
        window.removeEventListener('keydown', onKeyDown);
        window.removeEventListener('resize', resizeCanvas);
        
        saveToJob();
    }
    
    // ═══════════════════════════════════════
    // HELPERS
    // ═══════════════════════════════════════
    function activeLevel() { return levels[activeLevelIdx] || levels[0]; }
    function activeImage() {
        const pi = activeLevel()?.pageIndex ?? 0;
        return pageImages[pi];
    }
    
    function calculatePxPerMetre() {
        const ai = activeImage();
        if (!ai || !ai.loaded) return;
        const papers = { 'A0': [1189,841], 'A1': [841,594], 'A2': [594,420], 'A3': [420,297], 'A4': [297,210] };
        const ps = document.getElementById('fp-paper-size')?.value || 'A1';
        const ori = document.getElementById('fp-orientation')?.value || 'landscape';
        const [pw, ph] = papers[ps] || [841, 594];
        const paperW_mm = ori === 'portrait' ? ph : pw;
        const realW_m = (paperW_mm * scaleRatio) / 1000;
        pxPerMetre = ai.img.width / realW_m;
    }
    
    function resizeCanvas() {
        if (!container || !canvas) return;
        canvas.width = container.clientWidth;
        canvas.height = container.clientHeight;
        render();
    }
    
    function fitImageToView() {
        const ai = activeImage();
        if (!ai || !ai.loaded) return;
        const pad = 40;
        const sx = (canvas.width - pad * 2) / ai.img.width;
        const sy = (canvas.height - pad * 2) / ai.img.height;
        viewScale = Math.min(sx, sy);
        viewX = (canvas.width - ai.img.width * viewScale) / 2;
        viewY = (canvas.height - ai.img.height * viewScale) / 2;
    }
    
    function screenToImage(sx, sy) {
        return { x: (sx - viewX) / viewScale, y: (sy - viewY) / viewScale };
    }
    function imageToScreen(ix, iy) {
        return { x: ix * viewScale + viewX, y: iy * viewScale + viewY };
    }
    
    // ═══════════════════════════════════════
    // MOUSE EVENTS
    // ═══════════════════════════════════════
    function onMouseDown(e) {
        const rect = canvas.getBoundingClientRect();
        const sx = e.clientX - rect.left, sy = e.clientY - rect.top;
        
        // Pan: middle click, right click, or alt+click
        if (e.button === 1 || e.button === 2 || (e.button === 0 && e.altKey)) {
            isDragging = true;
            dragStartX = sx; dragStartY = sy;
            dragStartViewX = viewX; dragStartViewY = viewY;
            canvas.style.cursor = 'grabbing';
            e.preventDefault();
            return;
        }
        
        if (e.button !== 0 || e.altKey) return;
        const imgPt = screenToImage(sx, sy);
        
        // ── Measure tool ──
        if (activeTool === 'measure') {
            if (!isMeasuring) {
                measurePoints = [imgPt];
                isMeasuring = true;
            } else {
                measurePoints.push(imgPt);
            }
            updateMeasureDisplay();
            render();
            return;
        }
        
        // ── Room or Outline tool ──
        if (activeTool === 'room' || activeTool === 'outline') {
            if (isDrawing) {
                // Check close on first point
                if (currentPoints.length >= 3) {
                    const first = imageToScreen(currentPoints[0].x, currentPoints[0].y);
                    if (Math.hypot(sx - first.x, sy - first.y) < 14) {
                        finishPolygon();
                        return;
                    }
                }
                currentPoints.push(imgPt);
                render();
            } else {
                if (activeTool === 'room') {
                    // Check click inside existing room
                    const lv = activeLevel();
                    let clicked = -1;
                    for (let i = lv.rooms.length - 1; i >= 0; i--) {
                        if (pointInPolygon(imgPt, lv.rooms[i].points)) { clicked = i; break; }
                    }
                    if (clicked >= 0) {
                        selectedRoomIdx = clicked;
                        updateRoomsList();
                        render();
                    } else {
                        // Start new room polygon
                        isDrawing = true;
                        currentPoints = [imgPt];
                        selectedRoomIdx = -1;
                        canvas.style.cursor = 'crosshair';
                        render();
                    }
                } else {
                    // Start outline polygon
                    isDrawing = true;
                    currentPoints = [imgPt];
                    canvas.style.cursor = 'crosshair';
                    render();
                }
            }
        }
    }
    
    function onMouseMove(e) {
        const rect = canvas.getBoundingClientRect();
        const sx = e.clientX - rect.left, sy = e.clientY - rect.top;
        
        if (isDragging) {
            viewX = dragStartViewX + (sx - dragStartX);
            viewY = dragStartViewY + (sy - dragStartY);
            render();
            return;
        }
        
        // Hover on first point for closing
        if (isDrawing && currentPoints.length >= 3) {
            const first = imageToScreen(currentPoints[0].x, currentPoints[0].y);
            const dist = Math.hypot(sx - first.x, sy - first.y);
            const newHover = dist < 14 ? 0 : -1;
            if (newHover !== hoveredPoint) {
                hoveredPoint = newHover;
                canvas.style.cursor = newHover === 0 ? 'pointer' : 'crosshair';
            }
        }
        
        // Live line to cursor
        if (isDrawing && currentPoints.length > 0) {
            render();
            const last = imageToScreen(currentPoints[currentPoints.length - 1].x, currentPoints[currentPoints.length - 1].y);
            ctx.beginPath();
            ctx.moveTo(last.x, last.y);
            ctx.lineTo(sx, sy);
            ctx.strokeStyle = activeTool === 'outline' ? 'rgba(255,255,255,0.5)' : 'rgba(99, 102, 241, 0.6)';
            ctx.lineWidth = 2;
            ctx.setLineDash([6, 4]);
            ctx.stroke();
            ctx.setLineDash([]);
        }
    }
    
    function onMouseUp(e) {
        if (isDragging) {
            isDragging = false;
            canvas.style.cursor = isDrawing ? 'crosshair' : 'default';
        }
    }
    
    function onWheel(e) {
        e.preventDefault();
        const rect = canvas.getBoundingClientRect();
        const mx = e.clientX - rect.left, my = e.clientY - rect.top;
        const factor = e.deltaY < 0 ? 1.03 : 0.97;
        const ns = viewScale * factor;
        if (ns < 0.05 || ns > 20) return;
        viewX = mx - (mx - viewX) * factor;
        viewY = my - (my - viewY) * factor;
        viewScale = ns;
        render();
    }
    
    function onDoubleClick(e) {
        if (isDrawing && currentPoints.length >= 3) finishPolygon();
    }
    
    function onKeyDown(e) {
        if (e.key === 'Escape') {
            if (activeTool === 'measure' && isMeasuring) {
                measurePoints = []; isMeasuring = false;
                updateMeasureDisplay(); render(); return;
            }
            if (isDrawing) {
                currentPoints = []; isDrawing = false;
                render(); return;
            }
        }
        if ((e.key === 'Delete' || e.key === 'Backspace') && !isDrawing) {
            if (selectedRoomIdx >= 0) {
                const lv = activeLevel();
                lv.rooms.splice(selectedRoomIdx, 1);
                selectedRoomIdx = -1;
                updateRoomsList(); render();
            }
        }
        if (e.key === 'z' && (e.ctrlKey || e.metaKey)) {
            if (activeTool === 'measure' && measurePoints.length > 0) {
                measurePoints.pop();
                if (!measurePoints.length) isMeasuring = false;
                updateMeasureDisplay(); render(); return;
            }
            if (isDrawing && currentPoints.length > 0) {
                currentPoints.pop();
                if (!currentPoints.length) isDrawing = false;
                render(); return;
            }
        }
    }
    
    // ── Touch support ──
    let lastTouchDist = 0, lastTouchMid = null;
    
    function onTouchStart(e) {
        if (e.touches.length === 2) {
            e.preventDefault();
            lastTouchDist = Math.hypot(e.touches[0].clientX - e.touches[1].clientX, e.touches[0].clientY - e.touches[1].clientY);
            lastTouchMid = { x: (e.touches[0].clientX + e.touches[1].clientX) / 2, y: (e.touches[0].clientY + e.touches[1].clientY) / 2 };
        } else if (e.touches.length === 1) {
            const rect = canvas.getBoundingClientRect();
            const sx = e.touches[0].clientX - rect.left, sy = e.touches[0].clientY - rect.top;
            if (isDrawing || activeTool === 'measure') {
                e.preventDefault();
                const imgPt = screenToImage(sx, sy);
                if (activeTool === 'measure') {
                    if (!isMeasuring) { measurePoints = [imgPt]; isMeasuring = true; }
                    else measurePoints.push(imgPt);
                    updateMeasureDisplay(); render();
                } else {
                    if (currentPoints.length >= 3) {
                        const first = imageToScreen(currentPoints[0].x, currentPoints[0].y);
                        if (Math.hypot(sx - first.x, sy - first.y) < 20) { finishPolygon(); return; }
                    }
                    currentPoints.push(imgPt); render();
                }
            } else {
                isDragging = true;
                dragStartX = sx; dragStartY = sy;
                dragStartViewX = viewX; dragStartViewY = viewY;
            }
        }
    }
    
    function onTouchMove(e) {
        if (e.touches.length === 2) {
            e.preventDefault();
            const dist = Math.hypot(e.touches[0].clientX - e.touches[1].clientX, e.touches[0].clientY - e.touches[1].clientY);
            const mid = { x: (e.touches[0].clientX + e.touches[1].clientX) / 2, y: (e.touches[0].clientY + e.touches[1].clientY) / 2 };
            const factor = dist / lastTouchDist;
            const rect = canvas.getBoundingClientRect();
            const mx = mid.x - rect.left, my = mid.y - rect.top;
            viewX = mx - (mx - viewX) * factor;
            viewY = my - (my - viewY) * factor;
            viewScale *= factor;
            if (lastTouchMid) { viewX += mid.x - lastTouchMid.x; viewY += mid.y - lastTouchMid.y; }
            lastTouchDist = dist; lastTouchMid = mid;
            render();
        } else if (e.touches.length === 1 && isDragging && !isDrawing) {
            const rect = canvas.getBoundingClientRect();
            const sx = e.touches[0].clientX - rect.left, sy = e.touches[0].clientY - rect.top;
            viewX = dragStartViewX + (sx - dragStartX);
            viewY = dragStartViewY + (sy - dragStartY);
            render();
        }
    }
    
    function onTouchEnd() { isDragging = false; lastTouchDist = 0; lastTouchMid = null; }
    
    // ═══════════════════════════════════════
    // POLYGON COMPLETION
    // ═══════════════════════════════════════
    function finishPolygon() {
        if (currentPoints.length < 3) return;
        
        const areaPx = polygonArea(currentPoints);
        const areaSqm = pxPerMetre > 0 ? areaPx / (pxPerMetre * pxPerMetre) : 0;
        const perimPx = polygonPerimeter(currentPoints);
        const perimM = pxPerMetre > 0 ? perimPx / pxPerMetre : 0;
        const bbox = polygonBBox(currentPoints);
        const widthM = pxPerMetre > 0 ? (bbox.maxX - bbox.minX) / pxPerMetre : 0;
        const lengthM = pxPerMetre > 0 ? (bbox.maxY - bbox.minY) / pxPerMetre : 0;
        
        const lv = activeLevel();
        
        if (activeTool === 'outline') {
            // Building outline
            lv.buildingOutline = {
                points: [...currentPoints],
                area_sqm: Math.round(areaSqm * 100) / 100,
                perimeter_m: Math.round(perimM * 100) / 100,
                width_m: Math.round(widthM * 100) / 100,
                length_m: Math.round(lengthM * 100) / 100,
            };
            currentPoints = []; isDrawing = false;
            updateUI(); render();
            return;
        }
        
        // Room polygon
        const name = prompt('Room name:', `Room ${lv.rooms.length + 1}`);
        if (name === null) { currentPoints = []; isDrawing = false; render(); return; }
        
        const ci = lv.rooms.length % COLORS.length;
        lv.rooms.push({
            name: name.trim() || `Room ${lv.rooms.length + 1}`,
            points: [...currentPoints],
            color: COLORS[ci].fill,
            border: COLORS[ci].border,
            area_sqm: Math.round(areaSqm * 100) / 100,
            width_m: Math.round(widthM * 100) / 100,
            length_m: Math.round(lengthM * 100) / 100,
            perimeter_m: Math.round(perimM * 100) / 100,
        });
        
        selectedRoomIdx = lv.rooms.length - 1;
        currentPoints = []; isDrawing = false;
        updateUI(); render();
    }
    
    // ═══════════════════════════════════════
    // GEOMETRY
    // ═══════════════════════════════════════
    function polygonArea(pts) {
        let a = 0;
        for (let i = 0, j = pts.length - 1; i < pts.length; j = i++) {
            a += pts[j].x * pts[i].y - pts[i].x * pts[j].y;
        }
        return Math.abs(a / 2);
    }
    function polygonPerimeter(pts) {
        let p = 0;
        for (let i = 0; i < pts.length; i++) {
            const j = (i + 1) % pts.length;
            p += Math.hypot(pts[j].x - pts[i].x, pts[j].y - pts[i].y);
        }
        return p;
    }
    function polygonBBox(pts) {
        let minX = Infinity, minY = Infinity, maxX = -Infinity, maxY = -Infinity;
        for (const p of pts) { minX = Math.min(minX, p.x); minY = Math.min(minY, p.y); maxX = Math.max(maxX, p.x); maxY = Math.max(maxY, p.y); }
        return { minX, minY, maxX, maxY };
    }
    function polygonCentroid(pts) {
        let cx = 0, cy = 0;
        for (const p of pts) { cx += p.x; cy += p.y; }
        return { x: cx / pts.length, y: cy / pts.length };
    }
    function pointInPolygon(pt, pts) {
        let inside = false;
        for (let i = 0, j = pts.length - 1; i < pts.length; j = i++) {
            const xi = pts[i].x, yi = pts[i].y, xj = pts[j].x, yj = pts[j].y;
            if ((yi > pt.y) !== (yj > pt.y) && pt.x < (xj - xi) * (pt.y - yi) / (yj - yi) + xi) inside = !inside;
        }
        return inside;
    }
    
    // ═══════════════════════════════════════
    // RENDERING
    // ═══════════════════════════════════════
    function render() {
        if (!ctx || !canvas) return;
        ctx.clearRect(0, 0, canvas.width, canvas.height);
        
        // Background
        ctx.fillStyle = '#111827';
        ctx.fillRect(0, 0, canvas.width, canvas.height);
        
        // Draw current level image
        const ai = activeImage();
        if (ai && ai.loaded) {
            ctx.drawImage(ai.img, viewX, viewY, ai.img.width * viewScale, ai.img.height * viewScale);
        }
        
        const lv = activeLevel();
        if (!lv) return;
        
        // Draw building outline
        if (lv.buildingOutline && lv.buildingOutline.points.length >= 3) {
            drawPoly(lv.buildingOutline.points, OUTLINE_FILL, OUTLINE_BORDER, 2, [8, 4]);
            // Label
            const c = polygonCentroid(lv.buildingOutline.points);
            const sc = imageToScreen(c.x, c.y);
            ctx.font = 'bold 11px system-ui';
            const txt = `Building: ${lv.buildingOutline.area_sqm}m²`;
            const tw = ctx.measureText(txt).width;
            ctx.fillStyle = 'rgba(0,0,0,0.5)';
            ctx.beginPath(); ctx.roundRect(sc.x - tw/2 - 6, sc.y - 10, tw + 12, 22, 4); ctx.fill();
            ctx.fillStyle = 'rgba(255,255,255,0.7)';
            ctx.textAlign = 'center';
            ctx.fillText(txt, sc.x, sc.y + 5);
        }
        
        // Draw rooms
        lv.rooms.forEach((room, idx) => {
            drawPoly(room.points, room.color, room.border, idx === selectedRoomIdx ? 3 : 1.5);
            
            const c = polygonCentroid(room.points);
            const sc = imageToScreen(c.x, c.y);
            const fs = Math.max(10, 12 * viewScale);
            
            ctx.font = `bold ${fs}px system-ui`;
            const label = room.name;
            const sub = `${room.area_sqm}m²`;
            const tw = Math.max(ctx.measureText(label).width, ctx.measureText(sub).width);
            
            ctx.fillStyle = idx === selectedRoomIdx ? 'rgba(99, 102, 241, 0.85)' : 'rgba(0,0,0,0.6)';
            ctx.beginPath(); ctx.roundRect(sc.x - tw/2 - 6, sc.y - 18, tw + 12, 34, 6); ctx.fill();
            
            ctx.textAlign = 'center';
            ctx.font = `bold ${Math.max(9, 11 * viewScale)}px system-ui`;
            ctx.fillStyle = '#fff';
            ctx.fillText(label, sc.x, sc.y - 3);
            ctx.font = `${Math.max(8, 10 * viewScale)}px system-ui`;
            ctx.fillStyle = 'rgba(255,255,255,0.7)';
            ctx.fillText(sub, sc.x, sc.y + 12);
        });
        
        // Draw in-progress polygon
        if (currentPoints.length > 0) {
            const isOutline = activeTool === 'outline';
            ctx.beginPath();
            const f = imageToScreen(currentPoints[0].x, currentPoints[0].y);
            ctx.moveTo(f.x, f.y);
            for (let i = 1; i < currentPoints.length; i++) {
                const p = imageToScreen(currentPoints[i].x, currentPoints[i].y);
                ctx.lineTo(p.x, p.y);
            }
            ctx.strokeStyle = isOutline ? 'rgba(255,255,255,0.8)' : 'rgba(99, 102, 241, 0.9)';
            ctx.lineWidth = 2;
            ctx.stroke();
            
            // Points
            currentPoints.forEach((pt, idx) => {
                const sp = imageToScreen(pt.x, pt.y);
                ctx.beginPath();
                ctx.arc(sp.x, sp.y, idx === 0 && hoveredPoint === 0 ? 8 : 5, 0, Math.PI * 2);
                ctx.fillStyle = idx === 0 ? (hoveredPoint === 0 ? '#22c55e' : (isOutline ? '#fff' : '#6366f1')) : (isOutline ? '#fff' : '#6366f1');
                ctx.fill();
                ctx.strokeStyle = '#fff'; ctx.lineWidth = 2; ctx.stroke();
            });
            
            if (currentPoints.length >= 3 && hoveredPoint === 0) {
                const sp = imageToScreen(currentPoints[0].x, currentPoints[0].y);
                ctx.font = '11px system-ui'; ctx.fillStyle = '#22c55e'; ctx.textAlign = 'center';
                ctx.fillText('Click to close', sp.x, sp.y - 14);
            }
        }
        
        // Draw measure line
        if (measurePoints.length > 0) {
            ctx.beginPath();
            const mf = imageToScreen(measurePoints[0].x, measurePoints[0].y);
            ctx.moveTo(mf.x, mf.y);
            let totalPx = 0;
            for (let i = 1; i < measurePoints.length; i++) {
                const p = imageToScreen(measurePoints[i].x, measurePoints[i].y);
                ctx.lineTo(p.x, p.y);
                totalPx += Math.hypot(measurePoints[i].x - measurePoints[i-1].x, measurePoints[i].y - measurePoints[i-1].y);
            }
            ctx.strokeStyle = '#f59e0b'; ctx.lineWidth = 2.5;
            ctx.setLineDash([8, 4]); ctx.stroke(); ctx.setLineDash([]);
            
            measurePoints.forEach(pt => {
                const sp = imageToScreen(pt.x, pt.y);
                ctx.beginPath(); ctx.arc(sp.x, sp.y, 4, 0, Math.PI * 2);
                ctx.fillStyle = '#f59e0b'; ctx.fill();
                ctx.strokeStyle = '#fff'; ctx.lineWidth = 1.5; ctx.stroke();
            });
            
            if (measurePoints.length >= 2) {
                const last = imageToScreen(measurePoints[measurePoints.length - 1].x, measurePoints[measurePoints.length - 1].y);
                const totalM = pxPerMetre > 0 ? totalPx / pxPerMetre : 0;
                ctx.font = 'bold 13px system-ui';
                const lbl = totalM.toFixed(2) + 'm';
                const tw = ctx.measureText(lbl).width;
                ctx.fillStyle = 'rgba(245, 158, 11, 0.85)';
                ctx.beginPath(); ctx.roundRect(last.x + 10, last.y - 12, tw + 12, 24, 4); ctx.fill();
                ctx.fillStyle = '#fff'; ctx.textAlign = 'left';
                ctx.fillText(lbl, last.x + 16, last.y + 4);
            }
        }
        
        // Bottom instruction bar
        let hint = '';
        if (activeTool === 'measure') {
            hint = isMeasuring ? `${measurePoints.length} points · Esc to clear · Ctrl+Z to undo` : 'Click to start measuring · Scroll to zoom · Alt+drag to pan';
        } else if (isDrawing) {
            const minPts = currentPoints.length >= 3;
            hint = minPts ? `${currentPoints.length} points · Click first point or double-click to close · Esc to cancel` : `Click around the ${activeTool === 'outline' ? 'building' : 'room'} edges · ${currentPoints.length}/3 min`;
        } else {
            hint = 'Click to start marking · Scroll to zoom · Alt+drag to pan';
        }
        
        const barColor = activeTool === 'measure' ? 'rgba(245, 158, 11, 0.7)' : 
                         activeTool === 'outline' ? 'rgba(255,255,255,0.4)' : 'rgba(99, 102, 241, 0.7)';
        ctx.fillStyle = barColor;
        ctx.fillRect(canvas.width/2 - 250, canvas.height - 50, 500, 32);
        ctx.fillStyle = '#fff'; ctx.font = '12px system-ui'; ctx.textAlign = 'center';
        ctx.fillText(hint, canvas.width/2, canvas.height - 30);
    }
    
    function drawPoly(pts, fill, stroke, lw, dash) {
        if (pts.length < 3) return;
        ctx.beginPath();
        const f = imageToScreen(pts[0].x, pts[0].y);
        ctx.moveTo(f.x, f.y);
        for (let i = 1; i < pts.length; i++) {
            const p = imageToScreen(pts[i].x, pts[i].y);
            ctx.lineTo(p.x, p.y);
        }
        ctx.closePath();
        ctx.fillStyle = fill; ctx.fill();
        if (dash) ctx.setLineDash(dash);
        ctx.strokeStyle = stroke; ctx.lineWidth = lw; ctx.stroke();
        if (dash) ctx.setLineDash([]);
    }
    
    // ═══════════════════════════════════════
    // UI UPDATES
    // ═══════════════════════════════════════
    function updateUI() {
        updateLevelTabs();
        updateToolButtons();
        updateRoomsList();
        updateOutlineInfo();
        updateMeasureDisplay();
    }
    
    function updateLevelTabs() {
        const el = document.getElementById('rm-level-tabs');
        if (!el) return;
        el.innerHTML = '';
        
        levels.forEach((lv, idx) => {
            const active = idx === activeLevelIdx;
            const tab = document.createElement('button');
            tab.className = active
                ? 'px-3 py-1.5 text-xs font-semibold rounded-lg bg-indigo-600 text-white transition'
                : 'px-3 py-1.5 text-xs font-medium rounded-lg bg-gray-700/50 text-gray-400 hover:text-gray-200 hover:bg-gray-700 transition';
            tab.textContent = lv.name;
            tab.onclick = () => switchLevel(idx);
            tab.ondblclick = () => renameLevel(idx);
            el.appendChild(tab);
        });
        
        // Add level button (only if multi-page PDF)
        if (pageImages.length > levels.length) {
            const addBtn = document.createElement('button');
            addBtn.className = 'px-2 py-1.5 text-xs text-gray-500 hover:text-gray-300 transition';
            addBtn.textContent = '+ Add Level';
            addBtn.onclick = addLevel;
            el.appendChild(addBtn);
        }
    }
    
    function updateToolButtons() {
        const tools = ['room', 'outline', 'measure'];
        tools.forEach(t => {
            const btn = document.getElementById('rm-tool-' + t);
            if (!btn) return;
            const isActive = activeTool === t;
            if (t === 'measure') {
                btn.className = isActive
                    ? 'px-3 py-2 bg-amber-600 text-white text-xs font-semibold rounded-lg shadow-lg transition flex items-center gap-1.5'
                    : 'px-3 py-2 bg-gray-700 hover:bg-gray-600 text-gray-300 text-xs rounded-lg shadow-lg transition flex items-center gap-1.5';
            } else if (t === 'outline') {
                btn.className = isActive
                    ? 'px-3 py-2 bg-white/20 text-white text-xs font-semibold rounded-lg shadow-lg transition flex items-center gap-1.5 border border-white/30'
                    : 'px-3 py-2 bg-gray-700 hover:bg-gray-600 text-gray-300 text-xs rounded-lg shadow-lg transition flex items-center gap-1.5';
            } else {
                btn.className = isActive
                    ? 'px-3 py-2 bg-indigo-600 text-white text-xs font-semibold rounded-lg shadow-lg transition flex items-center gap-1.5'
                    : 'px-3 py-2 bg-gray-700 hover:bg-gray-600 text-gray-300 text-xs rounded-lg shadow-lg transition flex items-center gap-1.5';
            }
        });
        
        // Show/hide measure info
        const mi = document.getElementById('rm-measure-info');
        if (mi) mi.style.display = activeTool === 'measure' ? 'block' : 'none';
    }
    
    function updateRoomsList() {
        const list = document.getElementById('rm-rooms-list');
        if (!list) return;
        list.innerHTML = '';
        
        const lv = activeLevel();
        if (!lv || !lv.rooms.length) {
            list.innerHTML = '<div class="text-center py-3 text-gray-500 text-xs">No rooms marked yet</div>';
            updateTotalArea();
            return;
        }
        
        lv.rooms.forEach((room, idx) => {
            const sel = idx === selectedRoomIdx;
            const div = document.createElement('div');
            div.className = `flex items-center justify-between px-3 py-2 rounded-lg cursor-pointer transition ${sel ? 'bg-indigo-900/30 border border-indigo-500/50' : 'bg-gray-700/30 hover:bg-gray-700/50 border border-transparent'}`;
            div.onclick = () => { selectedRoomIdx = idx; zoomToRoom(idx); };
            div.innerHTML = `
                <div class="flex items-center gap-2 min-w-0">
                    <span class="w-2.5 h-2.5 rounded-sm flex-shrink-0" style="background:${room.border}"></span>
                    <span class="text-xs font-medium text-gray-200 truncate">${room.name}</span>
                </div>
                <div class="flex items-center gap-2 flex-shrink-0">
                    <span class="text-[10px] text-gray-500 font-mono">${room.width_m}×${room.length_m}m</span>
                    <span class="text-[10px] font-mono font-semibold text-amber-400">${room.area_sqm}m²</span>
                    <button onclick="event.stopPropagation(); renameRoomAt(${idx})" class="text-gray-500 hover:text-gray-300 text-[10px]" title="Rename">✏️</button>
                    <button onclick="event.stopPropagation(); deleteRoomAt(${idx})" class="text-gray-500 hover:text-red-400 text-[10px]" title="Delete">🗑️</button>
                </div>
            `;
            list.appendChild(div);
        });
        
        updateTotalArea();
    }
    
    function updateTotalArea() {
        const el = document.getElementById('rm-total-area');
        if (!el) return;
        const lv = activeLevel();
        if (!lv) { el.textContent = ''; return; }
        const total = lv.rooms.reduce((s, r) => s + r.area_sqm, 0);
        el.textContent = lv.rooms.length ? `${Math.round(total * 100) / 100}m² · ${lv.rooms.length} room${lv.rooms.length !== 1 ? 's' : ''}` : '';
    }
    
    function updateOutlineInfo() {
        const el = document.getElementById('rm-outline-info');
        if (!el) return;
        const lv = activeLevel();
        if (lv && lv.buildingOutline) {
            el.innerHTML = `
                <div class="flex items-center justify-between">
                    <span class="text-xs text-gray-300">Building footprint</span>
                    <button onclick="clearOutline()" class="text-[10px] text-red-400 hover:text-red-300">Remove</button>
                </div>
                <div class="text-sm font-bold font-mono text-white mt-1">${lv.buildingOutline.area_sqm}m²</div>
                <div class="text-[10px] text-gray-400 font-mono">${lv.buildingOutline.width_m}m × ${lv.buildingOutline.length_m}m · Perimeter: ${lv.buildingOutline.perimeter_m}m</div>
            `;
            el.style.display = 'block';
        } else {
            el.style.display = 'none';
        }
    }
    
    function updateMeasureDisplay() {
        const el = document.getElementById('rm-measure-length');
        if (!el) return;
        if (measurePoints.length < 2) { el.textContent = '0.00m'; return; }
        let totalPx = 0;
        for (let i = 0; i < measurePoints.length - 1; i++) {
            totalPx += Math.hypot(measurePoints[i+1].x - measurePoints[i].x, measurePoints[i+1].y - measurePoints[i].y);
        }
        el.textContent = (pxPerMetre > 0 ? totalPx / pxPerMetre : 0).toFixed(2) + 'm';
    }
    
    // ═══════════════════════════════════════
    // ACTIONS (exposed to window)
    // ═══════════════════════════════════════
    window.setTool = function(tool) {
        activeTool = tool;
        if (isDrawing) { currentPoints = []; isDrawing = false; }
        if (tool !== 'measure') { measurePoints = []; isMeasuring = false; }
        canvas.style.cursor = (tool === 'measure' || tool === 'outline') ? 'crosshair' : 'default';
        updateUI(); render();
    };
    
    window.startNewRoom = function() {
        activeTool = 'room';
        isDrawing = true;
        currentPoints = [];
        selectedRoomIdx = -1;
        canvas.style.cursor = 'crosshair';
        updateUI(); render();
    };
    
    window.clearMeasure = function() {
        measurePoints = []; isMeasuring = false;
        updateMeasureDisplay(); render();
    };
    
    window.clearOutline = function() {
        const lv = activeLevel();
        if (lv) lv.buildingOutline = null;
        updateOutlineInfo(); render();
    };
    
    function zoomToRoom(idx) {
        const lv = activeLevel();
        if (!lv || idx < 0 || idx >= lv.rooms.length) return;
        selectedRoomIdx = idx;
        const bbox = polygonBBox(lv.rooms[idx].points);
        const pad = 80;
        const bw = bbox.maxX - bbox.minX, bh = bbox.maxY - bbox.minY;
        viewScale = Math.min((canvas.width - pad*2) / bw, (canvas.height - pad*2) / bh);
        const cx = (bbox.minX + bbox.maxX) / 2, cy = (bbox.minY + bbox.maxY) / 2;
        viewX = canvas.width/2 - cx * viewScale;
        viewY = canvas.height/2 - cy * viewScale;
        updateRoomsList(); render();
    }
    window.zoomToRoom = zoomToRoom;
    
    window.fitAllRooms = function() {
        fitImageToView();
        selectedRoomIdx = -1;
        updateRoomsList(); render();
    };
    
    window.deleteRoomAt = function(idx) {
        const lv = activeLevel();
        if (!lv || idx < 0 || idx >= lv.rooms.length) return;
        if (!confirm(`Delete "${lv.rooms[idx].name}"?`)) return;
        lv.rooms.splice(idx, 1);
        selectedRoomIdx = -1;
        updateRoomsList(); render();
    };
    
    window.renameRoomAt = function(idx) {
        const lv = activeLevel();
        if (!lv || idx < 0 || idx >= lv.rooms.length) return;
        const name = prompt('Room name:', lv.rooms[idx].name);
        if (name !== null) { lv.rooms[idx].name = name.trim() || lv.rooms[idx].name; updateRoomsList(); render(); }
    };
    
    // ── Level management ──
    function switchLevel(idx) {
        if (idx < 0 || idx >= levels.length) return;
        // Cancel drawing
        currentPoints = []; isDrawing = false;
        measurePoints = []; isMeasuring = false;
        selectedRoomIdx = -1;
        activeLevelIdx = idx;
        fitImageToView();
        calculatePxPerMetre();
        updateUI(); render();
    }
    
    function renameLevel(idx) {
        const name = prompt('Level name:', levels[idx].name);
        if (name !== null) { levels[idx].name = name.trim() || levels[idx].name; updateLevelTabs(); }
    }
    window.renameLevel = renameLevel;
    
    function addLevel() {
        // Find next unused page
        const usedPages = new Set(levels.map(l => l.pageIndex));
        let nextPage = -1;
        for (let i = 0; i < pageImages.length; i++) {
            if (!usedPages.has(i)) { nextPage = i; break; }
        }
        if (nextPage < 0) return;
        
        const name = prompt('Level name:', `Level ${levels.length + 1}`);
        if (name === null) return;
        
        levels.push({
            name: name.trim() || `Level ${levels.length + 1}`,
            pageIndex: nextPage,
            buildingOutline: null,
            rooms: [],
        });
        switchLevel(levels.length - 1);
    }
    
    // ═══════════════════════════════════════
    // SAVE TO JOB
    // ═══════════════════════════════════════
    async function saveToJob() {
        if (!window.currentJob) return;
        
        const data = levels.map(lv => ({
            name: lv.name,
            pageIndex: lv.pageIndex,
            buildingOutline: lv.buildingOutline,
            rooms: lv.rooms.map(r => ({
                name: r.name,
                points: r.points,
                area_sqm: r.area_sqm,
                width_m: r.width_m,
                length_m: r.length_m,
                perimeter_m: r.perimeter_m,
            })),
        }));
        
        // Flatten rooms for backward compatibility with the parser
        const allRooms = [];
        let totalArea = 0;
        data.forEach(lv => {
            lv.rooms.forEach(r => {
                allRooms.push({
                    name: `${r.name} (${lv.name})`,
                    width_m: r.width_m,
                    length_m: r.length_m,
                    area_sqm: r.area_sqm,
                    perimeter_m: r.perimeter_m,
                    level: lv.name,
                    points: r.points,
                });
                totalArea += r.area_sqm;
            });
            if (lv.buildingOutline) {
                totalArea = Math.max(totalArea, lv.buildingOutline.area_sqm);
            }
        });
        
        try {
            const resp = await fetch(`/voice-to-quote/jobs/${window.currentJob.id}/save-floor-plan-rooms`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    levels: data,
                    rooms: allRooms,
                    total_floor_area_sqm: Math.round(totalArea * 100) / 100,
                    source: 'manual',
                })
            });
            const result = await resp.json();
            if (result.success) {
                window.currentJob.floor_plan_rooms = { levels: data, rooms: allRooms, total_floor_area_sqm: totalArea };
                if (typeof displayExtractedRooms === 'function') {
                    displayExtractedRooms({ rooms: allRooms, total_floor_area_sqm: totalArea });
                }
            }
        } catch(e) {
            console.error('Failed to save rooms:', e);
        }
    }
    
})();
