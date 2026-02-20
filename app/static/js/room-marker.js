/* ═══════════════════════════════════════════════════════════════
   ROOM MARKER CANVAS — Manual polygon room marking for VTQ
   Click points around a room → close polygon → name it → area calculated
   ═══════════════════════════════════════════════════════════════ */

(function() {
    'use strict';
    
    // ── State ──
    let canvas, ctx, container;
    let image = null;
    let imageLoaded = false;
    
    // View transform (pan & zoom)
    let viewX = 0, viewY = 0, viewScale = 1;
    let isDragging = false, dragStartX = 0, dragStartY = 0, dragStartViewX = 0, dragStartViewY = 0;
    
    // Drawing state
    let currentPoints = [];      // Points of polygon being drawn
    let isDrawing = false;
    let hoveredPoint = -1;       // Index of point being hovered (for closing)
    
    // Rooms data
    let rooms = [];              // [{name, points, color, area_sqm, width_m, length_m, perimeter_m}]
    let selectedRoomIdx = -1;
    let editingRoomIdx = -1;
    
    // Scale
    let pxPerMetre = 0;          // Pixels per metre (calculated from scale settings)
    let scaleRatio = 50;         // e.g. 50 for 1:50
    
    // Colours for rooms
    const ROOM_COLORS = [
        'rgba(99, 102, 241, 0.25)',   // indigo
        'rgba(16, 185, 129, 0.25)',   // emerald
        'rgba(245, 158, 11, 0.25)',   // amber
        'rgba(239, 68, 68, 0.25)',    // red
        'rgba(168, 85, 247, 0.25)',   // purple
        'rgba(6, 182, 212, 0.25)',    // cyan
        'rgba(236, 72, 153, 0.25)',   // pink
        'rgba(132, 204, 22, 0.25)',   // lime
        'rgba(251, 146, 60, 0.25)',   // orange
        'rgba(34, 211, 238, 0.25)',   // teal
    ];
    const ROOM_BORDERS = [
        'rgba(99, 102, 241, 0.8)',
        'rgba(16, 185, 129, 0.8)',
        'rgba(245, 158, 11, 0.8)',
        'rgba(239, 68, 68, 0.8)',
        'rgba(168, 85, 247, 0.8)',
        'rgba(6, 182, 212, 0.8)',
        'rgba(236, 72, 153, 0.8)',
        'rgba(132, 204, 22, 0.8)',
        'rgba(251, 146, 60, 0.8)',
        'rgba(34, 211, 238, 0.8)',
    ];
    
    // ── Initialise ──
    window.RoomMarker = {
        open: openMarker,
        close: closeMarker,
        getRooms: () => rooms,
        setRooms: (r) => { rooms = r || []; },
        setImage: setFloorPlanImage,
    };
    
    function openMarker(imageSrc, existingRooms, scaleSettings) {
        // Parse scale
        if (scaleSettings) {
            const match = scaleSettings.scale_ratio?.match(/1\s*[:]\s*(\d+)/);
            scaleRatio = match ? parseInt(match[1]) : 50;
            
            const papers = {
                'A0': [1189, 841], 'A1': [841, 594], 'A2': [594, 420],
                'A3': [420, 297], 'A4': [297, 210]
            };
            const [pw, ph] = papers[scaleSettings.paper_size] || [841, 594];
            const paperW = scaleSettings.orientation === 'portrait' ? ph : pw;
            // pxPerMetre will be set after image loads (image pixels / real-world metres)
        }
        
        // Restore existing rooms with colors
        rooms = (existingRooms || []).map((r, idx) => ({
            ...r,
            color: r.color || ROOM_COLORS[idx % ROOM_COLORS.length],
            border: r.border || ROOM_BORDERS[idx % ROOM_BORDERS.length],
        }));
        selectedRoomIdx = -1;
        currentPoints = [];
        isDrawing = false;
        
        // Create overlay
        const overlay = document.getElementById('room-marker-overlay');
        overlay.classList.remove('hidden');
        
        canvas = document.getElementById('room-marker-canvas');
        ctx = canvas.getContext('2d');
        container = document.getElementById('room-marker-container');
        
        // Load image
        if (imageSrc) {
            image = new Image();
            image.crossOrigin = 'anonymous';
            image.onload = () => {
                imageLoaded = true;
                resizeCanvas();
                fitImageToView();
                
                // Calculate px per metre from image width and paper/scale
                const papers = {
                    'A0': [1189, 841], 'A1': [841, 594], 'A2': [594, 420],
                    'A3': [420, 297], 'A4': [297, 210]
                };
                const paperSize = document.getElementById('fp-paper-size')?.value || 'A1';
                const orientation = document.getElementById('fp-orientation')?.value || 'landscape';
                const [pw, ph] = papers[paperSize] || [841, 594];
                const paperW_mm = orientation === 'portrait' ? ph : pw;
                const realWidth_m = (paperW_mm * scaleRatio) / 1000;
                pxPerMetre = image.width / realWidth_m;
                
                render();
            };
            image.src = imageSrc;
        }
        
        // Bind events
        canvas.addEventListener('mousedown', onMouseDown);
        canvas.addEventListener('mousemove', onMouseMove);
        canvas.addEventListener('mouseup', onMouseUp);
        canvas.addEventListener('wheel', onWheel, { passive: false });
        canvas.addEventListener('dblclick', onDoubleClick);
        window.addEventListener('keydown', onKeyDown);
        window.addEventListener('resize', resizeCanvas);
        
        // Touch support
        canvas.addEventListener('touchstart', onTouchStart, { passive: false });
        canvas.addEventListener('touchmove', onTouchMove, { passive: false });
        canvas.addEventListener('touchend', onTouchEnd);
        
        updateRoomsList();
    }
    
    function closeMarker() {
        const overlay = document.getElementById('room-marker-overlay');
        overlay.classList.add('hidden');
        
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
        
        // Save rooms back to the job
        saveRoomsToJob();
    }
    
    function setFloorPlanImage(src) {
        if (!src) return;
        image = new Image();
        image.crossOrigin = 'anonymous';
        image.onload = () => { imageLoaded = true; };
        image.src = src;
    }
    
    // ── Canvas sizing ──
    function resizeCanvas() {
        if (!container || !canvas) return;
        canvas.width = container.clientWidth;
        canvas.height = container.clientHeight;
        render();
    }
    
    function fitImageToView() {
        if (!image || !canvas) return;
        const padX = 40, padY = 40;
        const scaleX = (canvas.width - padX * 2) / image.width;
        const scaleY = (canvas.height - padY * 2) / image.height;
        viewScale = Math.min(scaleX, scaleY);
        viewX = (canvas.width - image.width * viewScale) / 2;
        viewY = (canvas.height - image.height * viewScale) / 2;
    }
    
    // ── Coordinate transforms ──
    function screenToImage(sx, sy) {
        return {
            x: (sx - viewX) / viewScale,
            y: (sy - viewY) / viewScale
        };
    }
    
    function imageToScreen(ix, iy) {
        return {
            x: ix * viewScale + viewX,
            y: iy * viewScale + viewY
        };
    }
    
    // ── Mouse events ──
    function onMouseDown(e) {
        const rect = canvas.getBoundingClientRect();
        const sx = e.clientX - rect.left;
        const sy = e.clientY - rect.top;
        
        if (e.button === 1 || e.button === 2 || (e.button === 0 && e.altKey)) {
            // Middle click or alt+click = pan
            isDragging = true;
            dragStartX = sx;
            dragStartY = sy;
            dragStartViewX = viewX;
            dragStartViewY = viewY;
            canvas.style.cursor = 'grabbing';
            e.preventDefault();
            return;
        }
        
        if (e.button === 0 && !e.altKey) {
            const imgPt = screenToImage(sx, sy);
            
            if (isDrawing) {
                // Check if clicking near first point to close
                if (currentPoints.length >= 3) {
                    const first = imageToScreen(currentPoints[0].x, currentPoints[0].y);
                    const dist = Math.hypot(sx - first.x, sy - first.y);
                    if (dist < 12) {
                        finishPolygon();
                        return;
                    }
                }
                currentPoints.push(imgPt);
                render();
            } else {
                // Check if clicking inside an existing room
                let clickedRoom = -1;
                for (let i = rooms.length - 1; i >= 0; i--) {
                    if (pointInPolygon(imgPt, rooms[i].points)) {
                        clickedRoom = i;
                        break;
                    }
                }
                
                if (clickedRoom >= 0) {
                    selectedRoomIdx = clickedRoom;
                    updateRoomsList();
                    render();
                } else {
                    // Start new polygon
                    isDrawing = true;
                    currentPoints = [imgPt];
                    selectedRoomIdx = -1;
                    updateToolbar();
                    render();
                }
            }
        }
    }
    
    function onMouseMove(e) {
        const rect = canvas.getBoundingClientRect();
        const sx = e.clientX - rect.left;
        const sy = e.clientY - rect.top;
        
        if (isDragging) {
            viewX = dragStartViewX + (sx - dragStartX);
            viewY = dragStartViewY + (sy - dragStartY);
            render();
            return;
        }
        
        // Check hover on first point for closing
        if (isDrawing && currentPoints.length >= 3) {
            const first = imageToScreen(currentPoints[0].x, currentPoints[0].y);
            const dist = Math.hypot(sx - first.x, sy - first.y);
            const newHover = dist < 12 ? 0 : -1;
            if (newHover !== hoveredPoint) {
                hoveredPoint = newHover;
                canvas.style.cursor = newHover === 0 ? 'pointer' : 'crosshair';
                render();
            }
        }
        
        if (isDrawing) {
            // Draw live line to cursor
            render();
            const imgPt = screenToImage(sx, sy);
            if (currentPoints.length > 0) {
                const lastPt = imageToScreen(currentPoints[currentPoints.length - 1].x, currentPoints[currentPoints.length - 1].y);
                ctx.beginPath();
                ctx.moveTo(lastPt.x, lastPt.y);
                ctx.lineTo(sx, sy);
                ctx.strokeStyle = 'rgba(99, 102, 241, 0.6)';
                ctx.lineWidth = 2;
                ctx.setLineDash([6, 4]);
                ctx.stroke();
                ctx.setLineDash([]);
            }
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
        const mx = e.clientX - rect.left;
        const my = e.clientY - rect.top;
        
        const zoomFactor = e.deltaY < 0 ? 1.03 : 0.97;
        const newScale = viewScale * zoomFactor;
        
        if (newScale < 0.05 || newScale > 20) return;
        
        viewX = mx - (mx - viewX) * zoomFactor;
        viewY = my - (my - viewY) * zoomFactor;
        viewScale = newScale;
        
        render();
    }
    
    function onDoubleClick(e) {
        if (isDrawing && currentPoints.length >= 3) {
            finishPolygon();
        }
    }
    
    function onKeyDown(e) {
        if (e.key === 'Escape') {
            if (isDrawing) {
                currentPoints = [];
                isDrawing = false;
                updateToolbar();
                render();
            }
        }
        if (e.key === 'Delete' || e.key === 'Backspace') {
            if (selectedRoomIdx >= 0 && !isDrawing) {
                rooms.splice(selectedRoomIdx, 1);
                selectedRoomIdx = -1;
                updateRoomsList();
                render();
            }
        }
        if (e.key === 'z' && (e.ctrlKey || e.metaKey) && isDrawing) {
            // Undo last point
            if (currentPoints.length > 0) {
                currentPoints.pop();
                if (currentPoints.length === 0) {
                    isDrawing = false;
                    updateToolbar();
                }
                render();
            }
        }
    }
    
    // ── Touch support ──
    let lastTouchDist = 0;
    let lastTouchMid = null;
    
    function onTouchStart(e) {
        if (e.touches.length === 2) {
            // Pinch zoom start
            e.preventDefault();
            lastTouchDist = Math.hypot(
                e.touches[0].clientX - e.touches[1].clientX,
                e.touches[0].clientY - e.touches[1].clientY
            );
            lastTouchMid = {
                x: (e.touches[0].clientX + e.touches[1].clientX) / 2,
                y: (e.touches[0].clientY + e.touches[1].clientY) / 2
            };
        } else if (e.touches.length === 1) {
            const rect = canvas.getBoundingClientRect();
            const sx = e.touches[0].clientX - rect.left;
            const sy = e.touches[0].clientY - rect.top;
            
            if (isDrawing) {
                e.preventDefault();
                const imgPt = screenToImage(sx, sy);
                
                if (currentPoints.length >= 3) {
                    const first = imageToScreen(currentPoints[0].x, currentPoints[0].y);
                    if (Math.hypot(sx - first.x, sy - first.y) < 20) {
                        finishPolygon();
                        return;
                    }
                }
                currentPoints.push(imgPt);
                render();
            } else {
                // Pan
                isDragging = true;
                dragStartX = sx;
                dragStartY = sy;
                dragStartViewX = viewX;
                dragStartViewY = viewY;
            }
        }
    }
    
    function onTouchMove(e) {
        if (e.touches.length === 2) {
            e.preventDefault();
            const dist = Math.hypot(
                e.touches[0].clientX - e.touches[1].clientX,
                e.touches[0].clientY - e.touches[1].clientY
            );
            const mid = {
                x: (e.touches[0].clientX + e.touches[1].clientX) / 2,
                y: (e.touches[0].clientY + e.touches[1].clientY) / 2
            };
            
            const factor = dist / lastTouchDist;
            const rect = canvas.getBoundingClientRect();
            const mx = mid.x - rect.left;
            const my = mid.y - rect.top;
            
            viewX = mx - (mx - viewX) * factor;
            viewY = my - (my - viewY) * factor;
            viewScale *= factor;
            
            // Also pan
            if (lastTouchMid) {
                viewX += (mid.x - lastTouchMid.x);
                viewY += (mid.y - lastTouchMid.y);
            }
            
            lastTouchDist = dist;
            lastTouchMid = mid;
            render();
        } else if (e.touches.length === 1 && isDragging && !isDrawing) {
            const rect = canvas.getBoundingClientRect();
            const sx = e.touches[0].clientX - rect.left;
            const sy = e.touches[0].clientY - rect.top;
            viewX = dragStartViewX + (sx - dragStartX);
            viewY = dragStartViewY + (sy - dragStartY);
            render();
        }
    }
    
    function onTouchEnd(e) {
        isDragging = false;
        lastTouchDist = 0;
        lastTouchMid = null;
    }
    
    // ── Polygon completion ──
    function finishPolygon() {
        if (currentPoints.length < 3) return;
        
        // Calculate area
        const areaPx = polygonArea(currentPoints);
        const areaSqm = pxPerMetre > 0 ? areaPx / (pxPerMetre * pxPerMetre) : 0;
        const perimeterPx = polygonPerimeter(currentPoints);
        const perimeterM = pxPerMetre > 0 ? perimeterPx / pxPerMetre : 0;
        
        // Bounding box for width/length
        const bbox = polygonBBox(currentPoints);
        const widthM = pxPerMetre > 0 ? (bbox.maxX - bbox.minX) / pxPerMetre : 0;
        const lengthM = pxPerMetre > 0 ? (bbox.maxY - bbox.minY) / pxPerMetre : 0;
        
        const colorIdx = rooms.length % ROOM_COLORS.length;
        
        // Prompt for room name
        const name = prompt('Room name:', `Room ${rooms.length + 1}`);
        if (name === null) {
            // Cancelled — discard
            currentPoints = [];
            isDrawing = false;
            updateToolbar();
            render();
            return;
        }
        
        rooms.push({
            name: name.trim() || `Room ${rooms.length + 1}`,
            points: [...currentPoints],
            color: ROOM_COLORS[colorIdx],
            border: ROOM_BORDERS[colorIdx],
            area_sqm: Math.round(areaSqm * 100) / 100,
            width_m: Math.round(widthM * 100) / 100,
            length_m: Math.round(lengthM * 100) / 100,
            perimeter_m: Math.round(perimeterM * 100) / 100,
        });
        
        currentPoints = [];
        isDrawing = false;
        selectedRoomIdx = rooms.length - 1;
        
        updateToolbar();
        updateRoomsList();
        render();
    }
    
    // ── Geometry helpers ──
    function polygonArea(pts) {
        let area = 0;
        for (let i = 0, j = pts.length - 1; i < pts.length; j = i++) {
            area += pts[j].x * pts[i].y;
            area -= pts[i].x * pts[j].y;
        }
        return Math.abs(area / 2);
    }
    
    function polygonPerimeter(pts) {
        let perim = 0;
        for (let i = 0; i < pts.length; i++) {
            const j = (i + 1) % pts.length;
            perim += Math.hypot(pts[j].x - pts[i].x, pts[j].y - pts[i].y);
        }
        return perim;
    }
    
    function polygonBBox(pts) {
        let minX = Infinity, minY = Infinity, maxX = -Infinity, maxY = -Infinity;
        for (const p of pts) {
            if (p.x < minX) minX = p.x;
            if (p.y < minY) minY = p.y;
            if (p.x > maxX) maxX = p.x;
            if (p.y > maxY) maxY = p.y;
        }
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
            const xi = pts[i].x, yi = pts[i].y;
            const xj = pts[j].x, yj = pts[j].y;
            if ((yi > pt.y) !== (yj > pt.y) && pt.x < (xj - xi) * (pt.y - yi) / (yj - yi) + xi) {
                inside = !inside;
            }
        }
        return inside;
    }
    
    // ── Rendering ──
    function render() {
        if (!ctx || !canvas) return;
        ctx.clearRect(0, 0, canvas.width, canvas.height);
        
        // Background
        ctx.fillStyle = '#111827';
        ctx.fillRect(0, 0, canvas.width, canvas.height);
        
        // Draw image
        if (image && imageLoaded) {
            ctx.drawImage(image, viewX, viewY, image.width * viewScale, image.height * viewScale);
        }
        
        // Draw existing rooms
        rooms.forEach((room, idx) => {
            drawPolygon(room.points, room.color, room.border, idx === selectedRoomIdx ? 3 : 1.5);
            
            // Label
            const centroid = polygonCentroid(room.points);
            const sc = imageToScreen(centroid.x, centroid.y);
            
            // Background for label
            ctx.font = `bold ${Math.max(11, 13 * viewScale)}px system-ui`;
            const label = `${room.name}`;
            const sublabel = `${room.area_sqm}m²`;
            const tw = Math.max(ctx.measureText(label).width, ctx.measureText(sublabel).width);
            
            ctx.fillStyle = idx === selectedRoomIdx ? 'rgba(99, 102, 241, 0.85)' : 'rgba(0,0,0,0.6)';
            ctx.beginPath();
            ctx.roundRect(sc.x - tw/2 - 6, sc.y - 18, tw + 12, 34, 6);
            ctx.fill();
            
            ctx.fillStyle = '#fff';
            ctx.textAlign = 'center';
            ctx.font = `bold ${Math.max(10, 12 * viewScale)}px system-ui`;
            ctx.fillText(label, sc.x, sc.y - 3);
            ctx.font = `${Math.max(9, 10 * viewScale)}px system-ui`;
            ctx.fillStyle = 'rgba(255,255,255,0.7)';
            ctx.fillText(sublabel, sc.x, sc.y + 12);
        });
        
        // Draw current polygon being drawn
        if (currentPoints.length > 0) {
            // Draw lines
            ctx.beginPath();
            const first = imageToScreen(currentPoints[0].x, currentPoints[0].y);
            ctx.moveTo(first.x, first.y);
            for (let i = 1; i < currentPoints.length; i++) {
                const p = imageToScreen(currentPoints[i].x, currentPoints[i].y);
                ctx.lineTo(p.x, p.y);
            }
            ctx.strokeStyle = 'rgba(99, 102, 241, 0.9)';
            ctx.lineWidth = 2;
            ctx.stroke();
            
            // Draw points
            currentPoints.forEach((pt, idx) => {
                const sp = imageToScreen(pt.x, pt.y);
                ctx.beginPath();
                ctx.arc(sp.x, sp.y, idx === 0 && hoveredPoint === 0 ? 8 : 5, 0, Math.PI * 2);
                ctx.fillStyle = idx === 0 ? (hoveredPoint === 0 ? '#22c55e' : '#6366f1') : '#6366f1';
                ctx.fill();
                ctx.strokeStyle = '#fff';
                ctx.lineWidth = 2;
                ctx.stroke();
            });
            
            // Show "click to close" hint on first point
            if (currentPoints.length >= 3 && hoveredPoint === 0) {
                const sp = imageToScreen(currentPoints[0].x, currentPoints[0].y);
                ctx.font = '11px system-ui';
                ctx.fillStyle = '#22c55e';
                ctx.textAlign = 'center';
                ctx.fillText('Click to close', sp.x, sp.y - 14);
            }
        }
        
        // Instructions overlay
        if (!rooms.length && !isDrawing) {
            ctx.fillStyle = 'rgba(0,0,0,0.5)';
            ctx.fillRect(canvas.width/2 - 180, canvas.height - 60, 360, 40);
            ctx.fillStyle = '#fff';
            ctx.font = '13px system-ui';
            ctx.textAlign = 'center';
            ctx.fillText('Click to start marking a room · Scroll to zoom · Alt+drag to pan', canvas.width/2, canvas.height - 35);
        } else if (isDrawing) {
            ctx.fillStyle = 'rgba(99, 102, 241, 0.7)';
            ctx.fillRect(canvas.width/2 - 200, canvas.height - 60, 400, 40);
            ctx.fillStyle = '#fff';
            ctx.font = '13px system-ui';
            ctx.textAlign = 'center';
            const hint = currentPoints.length >= 3 
                ? `${currentPoints.length} points · Click first point or double-click to close · Esc to cancel · Ctrl+Z to undo`
                : `Click around the room edges · ${currentPoints.length}/3 points minimum`;
            ctx.fillText(hint, canvas.width/2, canvas.height - 35);
        }
    }
    
    function drawPolygon(pts, fill, stroke, lineWidth) {
        if (pts.length < 3) return;
        ctx.beginPath();
        const first = imageToScreen(pts[0].x, pts[0].y);
        ctx.moveTo(first.x, first.y);
        for (let i = 1; i < pts.length; i++) {
            const p = imageToScreen(pts[i].x, pts[i].y);
            ctx.lineTo(p.x, p.y);
        }
        ctx.closePath();
        ctx.fillStyle = fill;
        ctx.fill();
        ctx.strokeStyle = stroke;
        ctx.lineWidth = lineWidth;
        ctx.stroke();
    }
    
    // ── Zoom to room ──
    window.zoomToRoom = function(idx) {
        if (idx < 0 || idx >= rooms.length) return;
        selectedRoomIdx = idx;
        
        const room = rooms[idx];
        const bbox = polygonBBox(room.points);
        const pad = 80;
        
        const bboxW = bbox.maxX - bbox.minX;
        const bboxH = bbox.maxY - bbox.minY;
        
        const scaleX = (canvas.width - pad * 2) / bboxW;
        const scaleY = (canvas.height - pad * 2) / bboxH;
        viewScale = Math.min(scaleX, scaleY);
        
        const cx = (bbox.minX + bbox.maxX) / 2;
        const cy = (bbox.minY + bbox.maxY) / 2;
        viewX = canvas.width / 2 - cx * viewScale;
        viewY = canvas.height / 2 - cy * viewScale;
        
        updateRoomsList();
        render();
    };
    
    window.fitAllRooms = function() {
        fitImageToView();
        selectedRoomIdx = -1;
        updateRoomsList();
        render();
    };
    
    window.deleteRoom = function(idx) {
        if (idx < 0 || idx >= rooms.length) return;
        if (!confirm(`Delete "${rooms[idx].name}"?`)) return;
        rooms.splice(idx, 1);
        selectedRoomIdx = -1;
        updateRoomsList();
        render();
    };
    
    window.renameRoom = function(idx) {
        if (idx < 0 || idx >= rooms.length) return;
        const name = prompt('Room name:', rooms[idx].name);
        if (name !== null) {
            rooms[idx].name = name.trim() || rooms[idx].name;
            updateRoomsList();
            render();
        }
    };
    
    window.startNewRoom = function() {
        isDrawing = true;
        currentPoints = [];
        selectedRoomIdx = -1;
        updateToolbar();
        render();
        canvas.style.cursor = 'crosshair';
    };
    
    // ── UI updates ──
    function updateToolbar() {
        const btn = document.getElementById('rm-new-room-btn');
        if (btn) {
            btn.style.display = isDrawing ? 'none' : '';
        }
    }
    
    function updateRoomsList() {
        const list = document.getElementById('rm-rooms-list');
        if (!list) return;
        
        list.innerHTML = '';
        
        if (rooms.length === 0) {
            list.innerHTML = '<div class="text-center py-4 text-gray-500 text-sm">No rooms marked yet. Click on the drawing to start.</div>';
            return;
        }
        
        let totalArea = 0;
        rooms.forEach((room, idx) => {
            totalArea += room.area_sqm;
            const isSelected = idx === selectedRoomIdx;
            const div = document.createElement('div');
            div.className = `flex items-center justify-between px-3 py-2 rounded-lg cursor-pointer transition ${isSelected ? 'bg-indigo-900/30 border border-indigo-500/50' : 'bg-gray-700/30 hover:bg-gray-700/50 border border-transparent'}`;
            div.onclick = () => zoomToRoom(idx);
            div.innerHTML = `
                <div class="flex items-center gap-2">
                    <span class="w-3 h-3 rounded-sm" style="background:${room.border}"></span>
                    <span class="text-sm font-medium text-gray-200">${room.name}</span>
                </div>
                <div class="flex items-center gap-3">
                    <span class="text-xs text-gray-400 font-mono">${room.width_m}×${room.length_m}m</span>
                    <span class="text-xs font-mono font-semibold text-amber-400">${room.area_sqm}m²</span>
                    <button onclick="event.stopPropagation(); renameRoom(${idx})" class="text-gray-500 hover:text-gray-300 text-xs" title="Rename">✏️</button>
                    <button onclick="event.stopPropagation(); deleteRoom(${idx})" class="text-gray-500 hover:text-red-400 text-xs" title="Delete">🗑️</button>
                </div>
            `;
            list.appendChild(div);
        });
        
        // Total
        const totalDiv = document.getElementById('rm-total-area');
        if (totalDiv) {
            totalDiv.textContent = `Total: ${Math.round(totalArea * 100) / 100}m² · ${rooms.length} room${rooms.length !== 1 ? 's' : ''}`;
        }
    }
    
    // ── Save rooms to job ──
    async function saveRoomsToJob() {
        if (!window.currentJob) return;
        
        const roomData = rooms.map(r => ({
            name: r.name,
            width_m: r.width_m,
            length_m: r.length_m,
            area_sqm: r.area_sqm,
            perimeter_m: r.perimeter_m,
            points: r.points,  // Save polygon points for re-opening
        }));
        
        const totalArea = roomData.reduce((sum, r) => sum + r.area_sqm, 0);
        
        try {
            const resp = await fetch(`/voice-to-quote/jobs/${window.currentJob.id}/save-floor-plan-rooms`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    rooms: roomData,
                    total_floor_area_sqm: Math.round(totalArea * 100) / 100,
                })
            });
            const data = await resp.json();
            if (data.success) {
                window.currentJob.floor_plan_rooms = { rooms: roomData, total_floor_area_sqm: totalArea };
                // Update the main page rooms display
                if (typeof displayExtractedRooms === 'function') {
                    displayExtractedRooms({ rooms: roomData, total_floor_area_sqm: totalArea });
                }
            }
        } catch(e) {
            console.error('Failed to save rooms:', e);
        }
    }
    
})();
