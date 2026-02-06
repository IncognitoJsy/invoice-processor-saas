"""Symbol detection service using OpenCV template matching + OCR filtering.

Takes a cropped symbol from the key area and finds all matching instances
across the full drawing, with confidence scoring.

KEY IMPROVEMENT: After template matching finds candidates, it uses OCR to read
the letter inside each detected symbol and only keeps matches where the letter
matches the original template. This prevents S, M, and H detectors from being
confused with each other.

SAVE TO: app/services/symbol_detector.py (REPLACE existing)
INSTALL: pip install opencv-python-headless numpy pytesseract
"""
import cv2
import numpy as np
import os
import logging

logger = logging.getLogger(__name__)

# Try to import pytesseract for OCR filtering
OCR_AVAILABLE = False
try:
    import pytesseract
    OCR_AVAILABLE = True
except ImportError:
    logger.warning("pytesseract not available - OCR-based symbol filtering disabled")


class SymbolDetector:
    """Detects symbols on electrical drawings using OpenCV template matching.
    
    Workflow:
    1. User draws box over symbol in key area → cropped template image
    2. Pre-process both template and drawing (grayscale, threshold, etc.)
    3. Run multi-scale template matching to handle slight size variations
    4. Apply non-maximum suppression to remove overlapping detections
    5. OCR post-filter: read text inside each detection, reject mismatches
    6. Filter out detections in the excluded key area
    7. Return list of {x, y, confidence} for each match
    """

    def __init__(self):
        self.match_methods = [cv2.TM_CCOEFF_NORMED]
        self.nms_threshold = 0.3
        self.min_confidence = 0.65
        self.scale_range = (0.85, 1.15)  # Tighter range — symbols on same drawing are same size
        self.scale_steps = 5

    def detect(self, drawing_path, template_path=None, crop_rect=None,
               exclude_area=None, confidence_threshold=0.7,
               template_text=None):
        """
        Run symbol detection on a drawing.
        
        Args:
            drawing_path: Path to the full drawing image (PNG)
            template_path: Path to pre-saved cropped symbol image (optional)
            crop_rect: {x, y, w, h} to crop template from the drawing itself
            exclude_area: {x, y, w, h} area to exclude from results (key area)
            confidence_threshold: Minimum confidence for a detection (0-1)
            template_text: Expected text inside the symbol (e.g. 'S', 'M', 'H')
                          If provided, OCR will verify each detection
            
        Returns:
            List of dicts: [{'x': int, 'y': int, 'confidence': float, 'w': int, 'h': int}, ...]
        """
        # Load drawing
        drawing = cv2.imread(drawing_path)
        if drawing is None:
            raise ValueError(f"Could not load drawing: {drawing_path}")

        # Get template image
        if template_path and os.path.exists(template_path):
            template = cv2.imread(template_path)
            if template is None:
                raise ValueError(f"Could not load template: {template_path}")
        elif crop_rect:
            x, y, w, h = crop_rect['x'], crop_rect['y'], crop_rect['w'], crop_rect['h']
            pad = 2
            x = max(0, x - pad)
            y = max(0, y - pad)
            w = min(drawing.shape[1] - x, w + 2 * pad)
            h = min(drawing.shape[0] - y, h + 2 * pad)
            template = drawing[y:y+h, x:x+w]
        else:
            raise ValueError("Either template_path or crop_rect must be provided")

        if template.shape[0] < 5 or template.shape[1] < 5:
            raise ValueError("Template too small - draw a larger box around the symbol")

        # If no template_text provided, try to read it from the template itself
        if template_text is None and OCR_AVAILABLE:
            template_text = self._extract_text_from_symbol(template)
            if template_text:
                logger.info(f"OCR detected template text: '{template_text}'")

        # Pre-process
        drawing_gray = cv2.cvtColor(drawing, cv2.COLOR_BGR2GRAY)
        template_gray = cv2.cvtColor(template, cv2.COLOR_BGR2GRAY)

        # Multi-scale template matching
        all_detections = []
        th, tw = template_gray.shape[:2]
        scales = np.linspace(self.scale_range[0], self.scale_range[1], self.scale_steps)

        for scale in scales:
            new_w = max(5, int(tw * scale))
            new_h = max(5, int(th * scale))

            if new_w >= drawing_gray.shape[1] or new_h >= drawing_gray.shape[0]:
                continue

            scaled_template = cv2.resize(template_gray, (new_w, new_h))

            for method in self.match_methods:
                result = cv2.matchTemplate(drawing_gray, scaled_template, method)
                locations = np.where(result >= confidence_threshold)

                for pt_y, pt_x in zip(*locations):
                    confidence = float(result[pt_y, pt_x])
                    cx = int(pt_x + new_w / 2)
                    cy = int(pt_y + new_h / 2)

                    all_detections.append({
                        'x': cx, 'y': cy,
                        'w': new_w, 'h': new_h,
                        'confidence': round(confidence, 3),
                        'box_x': int(pt_x), 'box_y': int(pt_y),
                    })

        logger.info(f"Raw detections before NMS: {len(all_detections)}")

        if not all_detections:
            return []

        # Non-maximum suppression
        detections = self._non_max_suppression(all_detections)
        logger.info(f"After NMS: {len(detections)}")

        # Filter out detections in the excluded area (key/legend)
        if exclude_area:
            ex = exclude_area
            detections = [
                d for d in detections
                if not (ex['x'] <= d['x'] <= ex['x'] + ex['w'] and
                        ex['y'] <= d['y'] <= ex['y'] + ex['h'])
            ]
            logger.info(f"After excluding key area: {len(detections)}")

        # Filter out the template's own position
        if crop_rect:
            cr = crop_rect
            cr_cx = cr['x'] + cr['w'] / 2
            cr_cy = cr['y'] + cr['h'] / 2
            detections = [
                d for d in detections
                if abs(d['x'] - cr_cx) > cr['w'] * 0.5 or abs(d['y'] - cr_cy) > cr['h'] * 0.5
            ]

        # ── OCR post-filter: verify text inside each detection ────
        if template_text and OCR_AVAILABLE and len(template_text) <= 3:
            logger.info(f"Running OCR post-filter for text '{template_text}' on {len(detections)} candidates")
            verified = []
            for d in detections:
                # Extract the region from the drawing
                bx, by = d['box_x'], d['box_y']
                bw, bh = d['w'], d['h']
                # Ensure bounds
                bx = max(0, bx)
                by = max(0, by)
                bw = min(drawing.shape[1] - bx, bw)
                bh = min(drawing.shape[0] - by, bh)
                
                region = drawing[by:by+bh, bx:bx+bw]
                detected_text = self._extract_text_from_symbol(region)
                
                if detected_text and detected_text.upper() == template_text.upper():
                    d['verified_text'] = detected_text
                    verified.append(d)
                    logger.debug(f"  ✓ ({d['x']},{d['y']}) text='{detected_text}' matches")
                elif not detected_text:
                    # OCR couldn't read it — keep it but lower confidence
                    d['confidence'] = round(d['confidence'] * 0.85, 3)
                    d['verified_text'] = None
                    verified.append(d)
                    logger.debug(f"  ? ({d['x']},{d['y']}) no OCR text, keeping with reduced confidence")
                else:
                    logger.debug(f"  ✗ ({d['x']},{d['y']}) text='{detected_text}' != '{template_text}', rejected")
            
            logger.info(f"After OCR filter: {len(verified)} (rejected {len(detections) - len(verified)})")
            detections = verified

        # Sort by confidence descending
        detections.sort(key=lambda d: d['confidence'], reverse=True)

        return detections

    def _extract_text_from_symbol(self, img):
        """Extract the letter/text inside a symbol using OCR.
        
        Works best for single characters inside circles (S, M, H, etc.)
        """
        if not OCR_AVAILABLE:
            return None
            
        try:
            if len(img.shape) == 3:
                gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
            else:
                gray = img.copy()

            # Focus on the centre 60% where the letter typically is
            h, w = gray.shape
            margin_x = int(w * 0.2)
            margin_y = int(h * 0.2)
            centre = gray[margin_y:h-margin_y, margin_x:w-margin_x]
            
            if centre.shape[0] < 5 or centre.shape[1] < 5:
                return None

            # Upscale for better OCR
            centre = cv2.resize(centre, None, fx=4, fy=4, interpolation=cv2.INTER_CUBIC)
            
            # Threshold
            _, thresh = cv2.threshold(centre, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)

            # Run OCR — single character mode (PSM 10)
            config = '--psm 10 -c tessedit_char_whitelist=ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789'
            text = pytesseract.image_to_string(thresh, config=config).strip()

            if text and len(text) <= 3:
                return text
            
            # Try inverted if nothing found
            if not text:
                inv = cv2.bitwise_not(thresh)
                text = pytesseract.image_to_string(inv, config=config).strip()
                if text and len(text) <= 3:
                    return text

            return None
        except Exception as e:
            logger.debug(f"OCR extraction error: {e}")
            return None

    def _non_max_suppression(self, detections):
        """Remove overlapping detections, keeping highest confidence ones."""
        if not detections:
            return []

        boxes = np.array([
            [d['box_x'], d['box_y'], d['box_x'] + d['w'], d['box_y'] + d['h']]
            for d in detections
        ], dtype=np.float32)

        confidences = np.array([d['confidence'] for d in detections], dtype=np.float32)
        idxs = np.argsort(confidences)[::-1]

        keep = []
        while len(idxs) > 0:
            i = idxs[0]
            keep.append(i)

            if len(idxs) == 1:
                break

            xx1 = np.maximum(boxes[i, 0], boxes[idxs[1:], 0])
            yy1 = np.maximum(boxes[i, 1], boxes[idxs[1:], 1])
            xx2 = np.minimum(boxes[i, 2], boxes[idxs[1:], 2])
            yy2 = np.minimum(boxes[i, 3], boxes[idxs[1:], 3])

            w = np.maximum(0, xx2 - xx1)
            h = np.maximum(0, yy2 - yy1)
            intersection = w * h
            area_i = (boxes[i, 2] - boxes[i, 0]) * (boxes[i, 3] - boxes[i, 1])
            area_others = (boxes[idxs[1:], 2] - boxes[idxs[1:], 0]) * (boxes[idxs[1:], 3] - boxes[idxs[1:], 1])
            union = area_i + area_others - intersection
            iou = intersection / (union + 1e-6)

            remaining = np.where(iou <= self.nms_threshold)[0]
            idxs = idxs[remaining + 1]

        return [detections[i] for i in keep]

    def detect_with_fallback(self, drawing_path, template_path=None, crop_rect=None,
                              exclude_area=None, confidence_threshold=0.7,
                              template_text=None,
                              use_claude_vision=False, anthropic_api_key=None):
        """Run OpenCV detection first, fall back to Claude Vision if no results."""
        detections = self.detect(
            drawing_path=drawing_path,
            template_path=template_path,
            crop_rect=crop_rect,
            exclude_area=exclude_area,
            confidence_threshold=confidence_threshold,
            template_text=template_text,
        )

        if len(detections) > 0 or not use_claude_vision:
            return detections

        if use_claude_vision and anthropic_api_key:
            logger.info("OpenCV found no matches, trying Claude Vision...")
            try:
                return self._detect_with_claude_vision(
                    drawing_path=drawing_path,
                    template_path=template_path,
                    crop_rect=crop_rect,
                    exclude_area=exclude_area,
                    anthropic_api_key=anthropic_api_key,
                    template_text=template_text,
                )
            except Exception as e:
                logger.error(f"Claude Vision fallback failed: {e}")

        return detections

    def _detect_with_claude_vision(self, drawing_path, template_path=None,
                                    crop_rect=None, exclude_area=None,
                                    anthropic_api_key=None, template_text=None):
        """Use Claude Vision API to find symbol matches on the drawing."""
        import anthropic
        import base64

        client = anthropic.Anthropic(api_key=anthropic_api_key)

        with open(drawing_path, 'rb') as f:
            drawing_b64 = base64.b64encode(f.read()).decode()

        template_b64 = None
        if template_path and os.path.exists(template_path):
            with open(template_path, 'rb') as f:
                template_b64 = base64.b64encode(f.read()).decode()

        prompt = """Look at the electrical drawing provided. I've also provided a cropped symbol from the drawing's key/legend.

Find ALL instances of this EXACT symbol on the drawing (excluding the key/legend area itself).

IMPORTANT: Only match symbols that are identical - including any text/letters inside them.
For example, if the template shows a circle with the letter 'S', do NOT match circles with 'M' or 'H'."""

        if template_text:
            prompt += f"\n\nThe symbol contains the letter/text '{template_text}'. Only match symbols containing exactly this text."

        prompt += """\n\nFor each instance found, provide the approximate pixel coordinates (x, y) of the center.

Respond ONLY with a JSON array like:
[{"x": 150, "y": 200, "confidence": 0.9}, {"x": 350, "y": 400, "confidence": 0.85}]

If you can't find any matches, respond with: []"""

        if exclude_area:
            prompt += f"\n\nExclude the key/legend area at x={exclude_area['x']}, y={exclude_area['y']}, width={exclude_area['w']}, height={exclude_area['h']}."

        content = [
            {"type": "text", "text": "Here is the full electrical drawing:"},
            {"type": "image", "source": {"type": "base64", "media_type": "image/png", "data": drawing_b64}},
        ]

        if template_b64:
            content.append({"type": "text", "text": "Here is the symbol to find (cropped from the key):"})
            content.append({"type": "image", "source": {"type": "base64", "media_type": "image/png", "data": template_b64}})

        content.append({"type": "text", "text": prompt})

        response = client.messages.create(
            model="claude-sonnet-4-20250514",
            max_tokens=2000,
            messages=[{"role": "user", "content": content}],
        )

        response_text = response.content[0].text.strip()

        import re, json
        json_match = re.search(r'\[.*\]', response_text, re.DOTALL)
        if json_match:
            detections = json.loads(json_match.group())
            for d in detections:
                d['source'] = 'claude_vision'
                d['w'] = 20
                d['h'] = 20
            return detections

        return []
