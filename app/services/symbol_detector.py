"""Symbol detection service using OpenCV template matching + rotation.

Matches symbols at multiple scales AND rotations (every 15° through 360°)
to handle symbols placed at any angle on the drawing.

SAVE TO: app/services/symbol_detector.py (REPLACE existing)
"""
import cv2
import numpy as np
import os
import logging

logger = logging.getLogger(__name__)


class SymbolDetector:
    def __init__(self):
        self.match_methods = [cv2.TM_CCOEFF_NORMED]
        self.nms_threshold = 0.3
        self.min_confidence = 0.65
        self.scale_range = (0.85, 1.15)
        self.scale_steps = 5
        self.rotation_angles = list(range(0, 360, 15))  # Every 15°

    def _rotate_template(self, template, angle):
        """Rotate template keeping all content visible with white border."""
        if angle == 0:
            return template
        h, w = template.shape[:2]
        cx, cy = w / 2, h / 2
        M = cv2.getRotationMatrix2D((cx, cy), angle, 1.0)
        cos = abs(M[0, 0])
        sin = abs(M[0, 1])
        new_w = int(h * sin + w * cos)
        new_h = int(h * cos + w * sin)
        M[0, 2] += (new_w / 2) - cx
        M[1, 2] += (new_h / 2) - cy
        return cv2.warpAffine(template, M, (new_w, new_h),
                              borderMode=cv2.BORDER_CONSTANT, borderValue=255)

    def detect(self, drawing_path, template_path=None, crop_rect=None,
               exclude_area=None, confidence_threshold=0.7):
        drawing = cv2.imread(drawing_path)
        if drawing is None:
            raise ValueError(f"Could not load drawing: {drawing_path}")

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
            raise ValueError("Template too small")

        drawing_gray = cv2.cvtColor(drawing, cv2.COLOR_BGR2GRAY)
        template_gray = cv2.cvtColor(template, cv2.COLOR_BGR2GRAY)

        all_detections = []
        th, tw = template_gray.shape[:2]
        scales = np.linspace(self.scale_range[0], self.scale_range[1], self.scale_steps)

        logger.info(f"Scanning {len(scales)} scales × {len(self.rotation_angles)} rotations = "
                    f"{len(scales) * len(self.rotation_angles)} combinations")

        for scale in scales:
            new_w = max(5, int(tw * scale))
            new_h = max(5, int(th * scale))
            scaled = cv2.resize(template_gray, (new_w, new_h))

            for angle in self.rotation_angles:
                rotated = self._rotate_template(scaled, angle)
                rh, rw = rotated.shape[:2]

                if rw >= drawing_gray.shape[1] or rh >= drawing_gray.shape[0]:
                    continue

                for method in self.match_methods:
                    result = cv2.matchTemplate(drawing_gray, rotated, method)
                    locations = np.where(result >= confidence_threshold)

                    for pt_y, pt_x in zip(*locations):
                        confidence = float(result[pt_y, pt_x])
                        all_detections.append({
                            'x': int(pt_x + rw / 2),
                            'y': int(pt_y + rh / 2),
                            'w': new_w, 'h': new_h,
                            'confidence': round(confidence, 3),
                            'box_x': int(pt_x), 'box_y': int(pt_y),
                            'rotation': angle,
                        })

        logger.info(f"Raw detections: {len(all_detections)}")
        if not all_detections:
            return []

        detections = self._non_max_suppression(all_detections)
        logger.info(f"After NMS: {len(detections)}")

        if exclude_area:
            ex = exclude_area
            detections = [d for d in detections
                          if not (ex['x'] <= d['x'] <= ex['x'] + ex['w'] and
                                  ex['y'] <= d['y'] <= ex['y'] + ex['h'])]
            logger.info(f"After key area exclusion: {len(detections)}")

        if crop_rect:
            cr = crop_rect
            cr_cx = cr['x'] + cr['w'] / 2
            cr_cy = cr['y'] + cr['h'] / 2
            detections = [d for d in detections
                          if abs(d['x'] - cr_cx) > cr['w'] * 0.5 or
                             abs(d['y'] - cr_cy) > cr['h'] * 0.5]

        detections.sort(key=lambda d: d['confidence'], reverse=True)
        return detections

    def _non_max_suppression(self, detections):
        """Distance-based NMS — better for rotated templates."""
        if not detections:
            return []
        detections.sort(key=lambda d: d['confidence'], reverse=True)
        keep = []
        for det in detections:
            is_dup = False
            for kept in keep:
                dist = np.sqrt((det['x'] - kept['x'])**2 + (det['y'] - kept['y'])**2)
                if dist < min(det['w'], det['h']) * 0.6:
                    is_dup = True
                    break
            if not is_dup:
                keep.append(det)
        return keep

    def detect_with_fallback(self, drawing_path, template_path=None, crop_rect=None,
                              exclude_area=None, confidence_threshold=0.7,
                              use_claude_vision=False, anthropic_api_key=None):
        detections = self.detect(drawing_path=drawing_path, template_path=template_path,
                                  crop_rect=crop_rect, exclude_area=exclude_area,
                                  confidence_threshold=confidence_threshold)
        if len(detections) > 0 or not use_claude_vision:
            return detections
        if use_claude_vision and anthropic_api_key:
            logger.info("OpenCV found no matches, trying Claude Vision...")
            try:
                return self._detect_with_claude_vision(
                    drawing_path=drawing_path, template_path=template_path,
                    crop_rect=crop_rect, exclude_area=exclude_area,
                    anthropic_api_key=anthropic_api_key)
            except Exception as e:
                logger.error(f"Claude Vision fallback failed: {e}")
        return detections

    def _detect_with_claude_vision(self, drawing_path, template_path=None,
                                    crop_rect=None, exclude_area=None,
                                    anthropic_api_key=None):
        import anthropic, base64
        client = anthropic.Anthropic(api_key=anthropic_api_key)
        with open(drawing_path, 'rb') as f:
            drawing_b64 = base64.b64encode(f.read()).decode()
        template_b64 = None
        if template_path and os.path.exists(template_path):
            with open(template_path, 'rb') as f:
                template_b64 = base64.b64encode(f.read()).decode()
        prompt = ("Find ALL instances of this exact symbol on the drawing "
                  "(excluding key/legend). Symbols may be rotated at any angle. "
                  "Only match identical symbols including any text/letters inside.\n\n"
                  "Respond ONLY with JSON: [{\"x\": 150, \"y\": 200, \"confidence\": 0.9}]\n"
                  "If none found: []")
        if exclude_area:
            prompt += (f"\n\nExclude area at x={exclude_area['x']}, y={exclude_area['y']}, "
                       f"w={exclude_area['w']}, h={exclude_area['h']}")
        content = [
            {"type": "text", "text": "Full drawing:"},
            {"type": "image", "source": {"type": "base64", "media_type": "image/png", "data": drawing_b64}},
        ]
        if template_b64:
            content.append({"type": "text", "text": "Symbol to find:"})
            content.append({"type": "image", "source": {"type": "base64", "media_type": "image/png", "data": template_b64}})
        content.append({"type": "text", "text": prompt})
        response = client.messages.create(model="claude-sonnet-4-20250514", max_tokens=2000,
                                           messages=[{"role": "user", "content": content}])
        import re, json
        json_match = re.search(r'\[.*\]', response.content[0].text.strip(), re.DOTALL)
        if json_match:
            dets = json.loads(json_match.group())
            for d in dets:
                d['source'] = 'claude_vision'
                d['w'] = d.get('w', 20)
                d['h'] = d.get('h', 20)
            return dets
        return []
