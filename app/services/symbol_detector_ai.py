"""
GoZappify Symbol Detection Service - Version 4
Uses Claude Vision API for intelligent symbol identification
Handles colours, text inside symbols, and subtle variations
"""

import anthropic
import base64
import json
import re
from typing import List, Dict, Tuple, Optional
import fitz  # PyMuPDF
import io

# Initialize Anthropic client
client = anthropic.Anthropic()

def render_pdf_page(pdf_path: str, page_num: int = 0, zoom: float = 2.0) -> bytes:
    """Render a PDF page to PNG image bytes."""
    doc = fitz.open(pdf_path)
    page = doc[page_num]
    mat = fitz.Matrix(zoom, zoom)
    pix = page.get_pixmap(matrix=mat, alpha=False)
    img_bytes = pix.tobytes("png")
    doc.close()
    return img_bytes


def render_region(pdf_path: str, page_num: int, x: int, y: int, 
                  width: int, height: int, zoom: float = 2.0, padding: int = 20) -> bytes:
    """Render a specific region of a PDF page."""
    doc = fitz.open(pdf_path)
    page = doc[page_num]
    
    # Add padding around the region
    x1 = max(0, x - padding)
    y1 = max(0, y - padding)
    x2 = x + width + padding
    y2 = y + height + padding
    
    # Create clip rect
    clip = fitz.Rect(x1 / zoom, y1 / zoom, x2 / zoom, y2 / zoom)
    mat = fitz.Matrix(zoom, zoom)
    pix = page.get_pixmap(matrix=mat, clip=clip, alpha=False)
    img_bytes = pix.tobytes("png")
    doc.close()
    return img_bytes


def identify_symbol_with_vision(
    image_bytes: bytes,
    symbol_templates: List[Dict],
    context: str = ""
) -> Dict:
    """
    Use Claude Vision to identify what symbol is in the image.
    
    Parameters:
    - image_bytes: PNG image of the symbol region
    - symbol_templates: List of known symbol types with descriptions
    - context: Additional context about the drawing
    
    Returns:
    - Dict with identified symbol type, confidence, and details
    """
    
    # Build template descriptions for Claude
    template_descriptions = []
    for t in symbol_templates:
        desc = f"- {t['name']}: {t.get('description', '')} (Category: {t.get('category', 'unknown')})"
        if t.get('distinguishing_features'):
            desc += f" Key features: {t['distinguishing_features']}"
        template_descriptions.append(desc)
    
    template_list = "\n".join(template_descriptions)
    
    prompt = f"""Analyze this electrical symbol from an architectural drawing.

Known symbol types in this project:
{template_list}

{f"Additional context: {context}" if context else ""}

Identify what symbol this is. Pay close attention to:
1. The COLOUR of any elements (blue, red, black, etc.)
2. Any TEXT or LETTERS inside or near the symbol
3. The NUMBER of small lines/ticks at the end of switches (indicates gang count)
4. Small subscript letters like "D" for dimmer

Respond in JSON format:
{{
    "identified_as": "exact name from the list above or 'unknown'",
    "confidence": 0.0-1.0,
    "colour_detected": "colour if relevant",
    "text_detected": "any text/letters found",
    "gang_count": null or number if this is a switch,
    "is_dimmer": true/false if this is a switch,
    "reasoning": "brief explanation of why you identified it this way"
}}

If you cannot confidently identify the symbol, set confidence below 0.7 and explain why."""

    # Encode image
    image_base64 = base64.standard_b64encode(image_bytes).decode("utf-8")
    
    try:
        response = client.messages.create(
            model="claude-opus-4-6",  # Use latest Opus for best vision
            max_tokens=500,
            messages=[
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "image",
                            "source": {
                                "type": "base64",
                                "media_type": "image/png",
                                "data": image_base64
                            }
                        },
                        {
                            "type": "text",
                            "text": prompt
                        }
                    ]
                }
            ]
        )
        
        # Parse JSON response
        response_text = response.content[0].text
        
        # Extract JSON from response
        json_match = re.search(r'\{[\s\S]*\}', response_text)
        if json_match:
            return json.loads(json_match.group())
        else:
            return {
                "identified_as": "unknown",
                "confidence": 0.0,
                "reasoning": "Failed to parse response"
            }
            
    except Exception as e:
        return {
            "identified_as": "unknown",
            "confidence": 0.0,
            "reasoning": f"API error: {str(e)}"
        }


def scan_drawing_for_symbols(
    pdf_path: str,
    page_num: int,
    symbol_templates: List[Dict],
    grid_size: int = 100,
    zoom: float = 2.0
) -> List[Dict]:
    """
    Scan an entire drawing to find and identify all symbols.
    Uses a grid-based approach with Claude Vision for identification.
    
    Parameters:
    - pdf_path: Path to PDF file
    - page_num: Page number
    - symbol_templates: Known symbol types
    - grid_size: Size of scanning grid in pixels
    - zoom: Render zoom level
    
    Returns:
    - List of detected symbols with positions and identifications
    """
    
    # First, render the full page
    full_image = render_pdf_page(pdf_path, page_num, zoom)
    
    # Get page dimensions
    doc = fitz.open(pdf_path)
    page = doc[page_num]
    page_width = int(page.rect.width * zoom)
    page_height = int(page.rect.height * zoom)
    doc.close()
    
    # Use Claude to analyze the full drawing first
    overview = get_drawing_overview(full_image, symbol_templates)
    
    return overview.get('symbols', [])


def get_drawing_overview(
    image_bytes: bytes,
    symbol_templates: List[Dict]
) -> Dict:
    """
    Use Claude Vision to analyze an entire drawing and locate all symbols.
    """
    
    # Build template descriptions
    template_descriptions = []
    for t in symbol_templates:
        desc = f"- **{t['name']}** (ID: {t['id']}): {t.get('description', '')}"
        if t.get('distinguishing_features'):
            desc += f". Key features: {t['distinguishing_features']}"
        template_descriptions.append(desc)
    
    template_list = "\n".join(template_descriptions)
    
    prompt = f"""Analyze this electrical floor plan drawing and identify ALL electrical symbols.

Known symbol types to look for:
{template_list}

For EACH symbol you find, provide:
1. The symbol type (from the list above)
2. Approximate position (describe location like "top-left corner", "center of main room", etc.)
3. Any distinguishing features (colour, text inside, number of gang lines for switches)

IMPORTANT distinctions to make:
- PIR sensors: Check the COLOUR (blue = master, red/black = slave, different icon = motion detector)
- Switches: Count the small TICK MARKS at the end (1 tick = 1-gang, 2 ticks = 2-gang, 3 ticks = 3-gang)
- Dimmers vs Switches: Look for a small "D" subscript near the symbol
- Smoke/Multi/Heat detectors: Look for letters S, M, or H inside the circle

Respond in JSON format:
{{
    "total_symbols_found": number,
    "symbols": [
        {{
            "template_id": id from list or null if unknown,
            "template_name": "name from list",
            "location_description": "where on the drawing",
            "estimated_x_percent": 0-100 (percentage from left),
            "estimated_y_percent": 0-100 (percentage from top),
            "colour": "if relevant",
            "text_inside": "if any",
            "gang_count": number if switch,
            "is_dimmer": true/false if switch,
            "confidence": 0.0-1.0,
            "notes": "any other observations"
        }}
    ],
    "rooms_identified": ["list of room names if visible"],
    "drawing_notes": "any relevant observations about the drawing"
}}

Be thorough - count every symbol you can see, even if some are partially obscured."""

    image_base64 = base64.standard_b64encode(image_bytes).decode("utf-8")
    
    try:
        response = client.messages.create(
            model="claude-opus-4-6",
            max_tokens=4000,
            messages=[
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "image",
                            "source": {
                                "type": "base64",
                                "media_type": "image/png",
                                "data": image_base64
                            }
                        },
                        {
                            "type": "text",
                            "text": prompt
                        }
                    ]
                }
            ]
        )
        
        response_text = response.content[0].text
        json_match = re.search(r'\{[\s\S]*\}', response_text)
        if json_match:
            result = json.loads(json_match.group())
            return result
        
        return {"symbols": [], "error": "Failed to parse response"}
        
    except Exception as e:
        return {"symbols": [], "error": str(e)}


def refine_symbol_positions(
    pdf_path: str,
    page_num: int,
    rough_detections: List[Dict],
    zoom: float = 2.0
) -> List[Dict]:
    """
    Take rough percentage-based positions from Claude and refine them
    to exact pixel coordinates using template matching or further vision analysis.
    """
    
    doc = fitz.open(pdf_path)
    page = doc[page_num]
    page_width = int(page.rect.width * zoom)
    page_height = int(page.rect.height * zoom)
    doc.close()
    
    refined = []
    
    for detection in rough_detections:
        # Convert percentage to pixels
        x_percent = detection.get('estimated_x_percent', 50)
        y_percent = detection.get('estimated_y_percent', 50)
        
        estimated_x = int((x_percent / 100) * page_width)
        estimated_y = int((y_percent / 100) * page_height)
        
        # Assume typical symbol size
        symbol_size = 40  # pixels at 2x zoom
        
        refined.append({
            'x': max(0, estimated_x - symbol_size // 2),
            'y': max(0, estimated_y - symbol_size // 2),
            'width': symbol_size,
            'height': symbol_size,
            'template_id': detection.get('template_id'),
            'template_name': detection.get('template_name'),
            'confidence': detection.get('confidence', 0.8),
            'colour': detection.get('colour'),
            'text_inside': detection.get('text_inside'),
            'gang_count': detection.get('gang_count'),
            'is_dimmer': detection.get('is_dimmer'),
            'location_description': detection.get('location_description'),
            'notes': detection.get('notes')
        })
    
    return refined


def detect_symbols_with_ai(
    pdf_path: str,
    page_num: int,
    symbol_templates: List[Dict],
    zoom: float = 2.0
) -> List[Dict]:
    """
    Main entry point for AI-powered symbol detection.
    
    Parameters:
    - pdf_path: Path to PDF file
    - page_num: Page number to analyze
    - symbol_templates: List of symbol templates with descriptions
    - zoom: Render zoom level
    
    Returns:
    - List of detected symbols with positions and identifications
    """
    
    # Render the full page
    image_bytes = render_pdf_page(pdf_path, page_num, zoom)
    
    # Get Claude to analyze the drawing
    overview = get_drawing_overview(image_bytes, symbol_templates)
    
    if overview.get('error'):
        return []
    
    # Refine positions
    rough_detections = overview.get('symbols', [])
    refined_detections = refine_symbol_positions(
        pdf_path, page_num, rough_detections, zoom
    )
    
    return refined_detections


def create_symbol_description(
    name: str,
    category: str,
    colour: str = None,
    text_inside: str = None,
    gang_count: int = None,
    is_dimmer: bool = False
) -> str:
    """
    Create a human-readable description for a symbol template
    that helps Claude identify it.
    """
    parts = [name]
    
    if colour:
        parts.append(f"with {colour} colour")
    
    if text_inside:
        parts.append(f"containing letter '{text_inside}'")
    
    if gang_count:
        parts.append(f"{gang_count}-gang")
    
    if is_dimmer:
        parts.append("dimmer (has 'D' subscript)")
    
    return " ".join(parts)


# Fallback to OpenCV for when AI detection gives rough positions
# and we need precise coordinates

try:
    import cv2
    import numpy as np
    OPENCV_AVAILABLE = True
except ImportError:
    OPENCV_AVAILABLE = False


def refine_position_with_opencv(
    source_image: bytes,
    template_image: bytes,
    rough_x: int,
    rough_y: int,
    search_radius: int = 50
) -> Tuple[int, int, float]:
    """
    Use OpenCV to refine a rough position to exact coordinates.
    
    Parameters:
    - source_image: Full drawing image bytes
    - template_image: Symbol template image bytes
    - rough_x, rough_y: Approximate position from AI
    - search_radius: How far to search around the rough position
    
    Returns:
    - Tuple of (refined_x, refined_y, confidence)
    """
    if not OPENCV_AVAILABLE:
        return (rough_x, rough_y, 0.5)
    
    # Load images
    source_arr = np.frombuffer(source_image, np.uint8)
    source = cv2.imdecode(source_arr, cv2.IMREAD_COLOR)
    
    template_arr = np.frombuffer(template_image, np.uint8)
    template = cv2.imdecode(template_arr, cv2.IMREAD_COLOR)
    
    h, w = template.shape[:2]
    source_h, source_w = source.shape[:2]
    
    # Define search region
    x1 = max(0, rough_x - search_radius)
    y1 = max(0, rough_y - search_radius)
    x2 = min(source_w, rough_x + search_radius + w)
    y2 = min(source_h, rough_y + search_radius + h)
    
    search_region = source[y1:y2, x1:x2]
    
    if search_region.shape[0] < h or search_region.shape[1] < w:
        return (rough_x, rough_y, 0.5)
    
    # Template match within search region
    result = cv2.matchTemplate(search_region, template, cv2.TM_CCOEFF_NORMED)
    _, max_val, _, max_loc = cv2.minMaxLoc(result)
    
    # Convert back to full image coordinates
    refined_x = x1 + max_loc[0]
    refined_y = y1 + max_loc[1]
    
    return (refined_x, refined_y, float(max_val))
