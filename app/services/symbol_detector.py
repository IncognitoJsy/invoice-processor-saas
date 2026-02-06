"""Symbol detection service using OpenCV template matching.

Takes a cropped symbol from the key area and finds all matching instances
across the full drawing, with confidence scoring.

ADD TO: app/services/symbol_detector.py (new file)
INSTALL: pip install opencv-python-headless numpy
"""
import cv2
import numpy as np
import os
import logging

logger = logging.getLogger(__name__)


class SymbolDetector:
    """Detects symbols on electrical drawings using OpenCV template matching.
    
    Workflow:
    1. User draws box over symbol in key area → we get a cropped template image
    2. We pre-process both template and drawing (grayscale, threshold, etc.)
    3. Run multi-scale template matching to handle slight size variations
    4. Apply non-maximum suppression to remove overlapping detections
    5. Filter out detections in the excluded key area
    6. Return list of {x, y, confidence} for each match
    """

    def __init__(self):
        self.match_methods = [cv2.TM_CCOEFF_NORMED]
        self.nms_threshold = 0.3  # Non-maximum suppression overlap threshold
        self.min_confidence = 0.65
        self.scale_range = (0.8, 1.2)  # Check 80% to 120% of template size
        self.scale_steps = 5

    def detect(self, drawing_path, template_path=None, crop_rect=None,
               exclude_area=None, confidence_threshold=0.7):
        """
        Run symbol detection on a drawing.
        
        Args:
            drawing_path: Path to the full drawing image (PNG)
            template_path: Path to pre-saved cropped symbol image (optional)
            crop_rect: {x, y, w, h} to crop template from the drawing itself
            exclude_area: {x, y, w, h} area to exclude from results (key area)
            confidence_threshold: Minimum confidence for a detection (0-1)
            
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
            # Add small padding around crop
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

        # Pre-process
        drawing_gray = cv2.cvtColor(drawing, cv2.COLOR_BGR2GRAY)
        template_gray = cv2.cvtColor(template, cv2.COLOR_BGR2GRAY)

        # Multi-scale template matching
        all_detections = []
        th, tw = template_gray.shape[:2]

        # Generate scale factors
        scales = np.linspace(self.scale_range[0], self.scale_range[1], self.scale_steps)

        for scale in scales:
            # Resize template
            new_w = max(5, int(tw * scale))
            new_h = max(5, int(th * scale))

            if new_w >= drawing_gray.shape[1] or new_h >= drawing_gray.shape[0]:
                continue

            scaled_template = cv2.resize(template_gray, (new_w, new_h))

            # Run template matching
            for method in self.match_methods:
                result = cv2.matchTemplate(drawing_gray, scaled_template, method)

                # Get locations above threshold
                locations = np.where(result >= confidence_threshold)

                for pt_y, pt_x in zip(*locations):
                    confidence = float(result[pt_y, pt_x])

                    # Center point of the detection
                    cx = int(pt_x + new_w / 2)
                    cy = int(pt_y + new_h / 2)

                    all_detections.append({
                        'x': cx,
                        'y': cy,
                        'w': new_w,
                        'h': new_h,
                        'confidence': round(confidence, 3),
                        'box_x': int(pt_x),
                        'box_y': int(pt_y),
                    })

        logger.info(f"Raw detections before NMS: {len(all_detections)}")

        if not all_detections:
            return []

        # Non-maximum suppression to remove overlaps
        detections = self._non_max_suppression(all_detections)

        logger.info(f"Detections after NMS: {len(detections)}")

        # Filter out detections in the excluded area (key/legend)
        if exclude_area:
            ex = exclude_area
            detections = [
                d for d in detections
                if not (ex['x'] <= d['x'] <= ex['x'] + ex['w'] and
                        ex['y'] <= d['y'] <= ex['y'] + ex['h'])
            ]
            logger.info(f"Detections after excluding key area: {len(detections)}")

        # Filter out the template's own position (if crop_rect was used)
        if crop_rect:
            cr = crop_rect
            cr_cx = cr['x'] + cr['w'] / 2
            cr_cy = cr['y'] + cr['h'] / 2
            detections = [
                d for d in detections
                if abs(d['x'] - cr_cx) > cr['w'] * 0.5 or abs(d['y'] - cr_cy) > cr['h'] * 0.5
            ]

        # Sort by confidence descending
        detections.sort(key=lambda d: d['confidence'], reverse=True)

        return detections

    def _non_max_suppression(self, detections):
        """Remove overlapping detections, keeping highest confidence ones."""
        if not detections:
            return []

        # Convert to arrays for NMS
        boxes = np.array([
            [d['box_x'], d['box_y'], d['box_x'] + d['w'], d['box_y'] + d['h']]
            for d in detections
        ], dtype=np.float32)

        confidences = np.array([d['confidence'] for d in detections], dtype=np.float32)

        # Sort by confidence
        idxs = np.argsort(confidences)[::-1]

        keep = []
        while len(idxs) > 0:
            i = idxs[0]
            keep.append(i)

            if len(idxs) == 1:
                break

            # Calculate IoU with remaining boxes
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

            # Remove overlapping boxes
            remaining = np.where(iou <= self.nms_threshold)[0]
            idxs = idxs[remaining + 1]

        return [detections[i] for i in keep]

    def detect_with_fallback(self, drawing_path, template_path=None, crop_rect=None,
                              exclude_area=None, confidence_threshold=0.7,
                              use_claude_vision=False, anthropic_api_key=None):
        """
        Run OpenCV detection first, fall back to Claude Vision if too few results.
        
        This is the hybrid approach - OpenCV is fast and free, Claude Vision
        can catch symbols that template matching misses.
        """
        # Try OpenCV first
        detections = self.detect(
            drawing_path=drawing_path,
            template_path=template_path,
            crop_rect=crop_rect,
            exclude_area=exclude_area,
            confidence_threshold=confidence_threshold,
        )

        if len(detections) > 0 or not use_claude_vision:
            return detections

        # Fallback to Claude Vision API
        if use_claude_vision and anthropic_api_key:
            logger.info("OpenCV found no matches, trying Claude Vision...")
            try:
                return self._detect_with_claude_vision(
                    drawing_path=drawing_path,
                    template_path=template_path,
                    crop_rect=crop_rect,
                    exclude_area=exclude_area,
                    anthropic_api_key=anthropic_api_key,
                )
            except Exception as e:
                logger.error(f"Claude Vision fallback failed: {e}")

        return detections

    def _detect_with_claude_vision(self, drawing_path, template_path=None,
                                    crop_rect=None, exclude_area=None,
                                    anthropic_api_key=None):
        """Use Claude Vision API to find symbol matches on the drawing.
        
        Sends the full drawing + cropped symbol to Claude and asks it to
        identify all matching symbol locations.
        """
        import anthropic
        import base64

        client = anthropic.Anthropic(api_key=anthropic_api_key)

        # Load images as base64
        with open(drawing_path, 'rb') as f:
            drawing_b64 = base64.b64encode(f.read()).decode()

        template_b64 = None
        if template_path and os.path.exists(template_path):
            with open(template_path, 'rb') as f:
                template_b64 = base64.b64encode(f.read()).decode()

        # Build prompt
        prompt = """Look at the electrical drawing provided. I've also provided a cropped symbol from the drawing's key/legend.

Find ALL instances of this exact symbol on the drawing (excluding the key/legend area itself).

For each instance found, provide the approximate pixel coordinates (x, y) of the center of the symbol.

Respond ONLY with a JSON array like:
[{"x": 150, "y": 200, "confidence": 0.9}, {"x": 350, "y": 400, "confidence": 0.85}]

If you can't find any matches, respond with: []"""

        if exclude_area:
            prompt += f"\n\nExclude the area at x={exclude_area['x']}, y={exclude_area['y']}, width={exclude_area['w']}, height={exclude_area['h']} (this is the symbol key/legend)."

        content = []
        content.append({
            "type": "text",
            "text": "Here is the full electrical drawing:"
        })
        content.append({
            "type": "image",
            "source": {
                "type": "base64",
                "media_type": "image/png",
                "data": drawing_b64,
            }
        })

        if template_b64:
            content.append({
                "type": "text",
                "text": "Here is the symbol to find (cropped from the key):"
            })
            content.append({
                "type": "image",
                "source": {
                    "type": "base64",
                    "media_type": "image/png",
                    "data": template_b64,
                }
            })

        content.append({"type": "text", "text": prompt})

        response = client.messages.create(
            model="claude-sonnet-4-20250514",
            max_tokens=2000,
            messages=[{"role": "user", "content": content}],
        )

        # Parse response
        response_text = response.content[0].text.strip()

        # Extract JSON from response
        import re
        json_match = re.search(r'\[.*\]', response_text, re.DOTALL)
        if json_match:
            import json
            detections = json.loads(json_match.group())
            # Add source marker
            for d in detections:
                d['source'] = 'claude_vision'
                d['w'] = 20  # Approximate
                d['h'] = 20
            return detections

        return []
