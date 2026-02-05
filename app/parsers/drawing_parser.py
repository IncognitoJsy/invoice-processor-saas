"""Drawing Parser - AI-powered extraction of materials from electrical drawings"""
import anthropic
import os
import base64
import json
import logging
import re
import tempfile
from typing import Dict, List
from datetime import datetime

logger = logging.getLogger(__name__)

# Max pages Anthropic API accepts per request
MAX_PDF_PAGES = 100
# We'll use a slightly lower chunk size to stay safe
PDF_CHUNK_SIZE = 80


class DrawingParser:
    """Parse electrical drawings using Claude's vision to extract materials list"""
    
    def __init__(self):
        api_key = os.getenv('ANTHROPIC_API_KEY')
        if not api_key:
            raise ValueError("ANTHROPIC_API_KEY environment variable not set")
        
        self.client = anthropic.Anthropic(
            api_key=api_key,
            max_retries=2
        )
        self.logger = logging.getLogger(__name__)
    
    def _get_pdf_page_count(self, file_path: str) -> int:
        """Get the number of pages in a PDF without heavy dependencies"""
        try:
            with open(file_path, 'rb') as f:
                content = f.read()
            
            # Try PyPDF2/pypdf first (more reliable)
            try:
                from pypdf import PdfReader
                reader = PdfReader(file_path)
                return len(reader.pages)
            except ImportError:
                pass
            
            try:
                from PyPDF2 import PdfReader
                reader = PdfReader(file_path)
                return len(reader.pages)
            except ImportError:
                pass
            
            # Fallback: count /Page objects in raw PDF (rough estimate)
            # This regex finds /Type /Page (but not /Type /Pages)
            page_count = len(re.findall(rb'/Type\s*/Page[^s]', content))
            if page_count > 0:
                return page_count
            
            # Last resort: assume it might be large
            # If file is over 10MB, flag as potentially large
            file_size_mb = len(content) / (1024 * 1024)
            if file_size_mb > 10:
                return 999  # Will trigger chunking or error
            
            return 1  # Default assumption
            
        except Exception as e:
            self.logger.warning(f"Could not count PDF pages: {e}")
            return 1
    
    def _split_pdf(self, file_path: str, chunk_size: int = PDF_CHUNK_SIZE) -> List[str]:
        """Split a large PDF into smaller chunks, return list of temp file paths"""
        try:
            # Try pypdf first
            try:
                from pypdf import PdfReader, PdfWriter
            except ImportError:
                from PyPDF2 import PdfReader, PdfWriter
            
            reader = PdfReader(file_path)
            total_pages = len(reader.pages)
            chunk_paths = []
            
            for start in range(0, total_pages, chunk_size):
                end = min(start + chunk_size, total_pages)
                writer = PdfWriter()
                
                for page_num in range(start, end):
                    writer.add_page(reader.pages[page_num])
                
                # Write chunk to temp file
                chunk_path = tempfile.mktemp(suffix=f'_pages_{start+1}-{end}.pdf')
                with open(chunk_path, 'wb') as f:
                    writer.write(f)
                
                chunk_paths.append(chunk_path)
                self.logger.info(f"Created PDF chunk: pages {start+1}-{end} of {total_pages}")
            
            return chunk_paths
            
        except ImportError:
            self.logger.error("No PDF library available for splitting (need pypdf or PyPDF2)")
            return []
        except Exception as e:
            self.logger.error(f"PDF split error: {e}")
            return []
    
    def _merge_results(self, results: List[Dict]) -> Dict:
        """Merge materials from multiple parse results (chunked PDFs)"""
        all_materials = []
        all_observations = []
        drawing_info = {}
        schedule_info = {}
        all_circuits = []
        cable_estimates = {
            'estimated_lighting_cable_m': 0,
            'estimated_power_cable_m': 0,
            'estimated_data_cable_m': 0,
        }
        
        for result in results:
            if not result.get('success'):
                continue
            
            all_materials.extend(result.get('materials', []))
            all_observations.extend(result.get('observations', []))
            all_circuits.extend(result.get('circuits', []))
            
            # Take the first valid drawing info
            if not drawing_info and result.get('drawing_info'):
                drawing_info = result['drawing_info']
            if not schedule_info and result.get('schedule_info'):
                schedule_info = result['schedule_info']
        
        return {
            'success': True,
            'materials': all_materials,
            'drawing_info': drawing_info,
            'schedule_info': schedule_info,
            'circuits': all_circuits,
            'observations': all_observations,
            'scale': drawing_info.get('scale'),
            'drawing_number': drawing_info.get('drawing_number'),
        }
    
    def parse(self, file_path: str, document_type: str = 'drawing', 
              system_type: str = 'all', floor_level: str = None) -> Dict:
        """
        Parse an electrical drawing to extract materials
        
        Args:
            file_path: Path to PDF or image file
            document_type: 'drawing', 'schedule', 'spec'
            system_type: 'lighting', 'power', 'data', 'fire_alarm', 'all'
            floor_level: 'ground', 'first', etc.
        
        Returns:
            Dict with materials list and metadata
        """
        try:
            self.logger.info(f"Parsing drawing: {file_path}")
            self.logger.info(f"Type: {document_type}, System: {system_type}, Floor: {floor_level}")
            
            # Determine file type
            file_ext = os.path.splitext(file_path)[1].lower()
            
            media_type_map = {
                '.pdf': 'application/pdf',
                '.jpg': 'image/jpeg',
                '.jpeg': 'image/jpeg',
                '.png': 'image/png',
            }
            
            media_type = media_type_map.get(file_ext)
            if not media_type:
                return {'success': False, 'error': f'Unsupported file type: {file_ext}'}
            
            # ---- Handle large PDFs ----
            if media_type == 'application/pdf':
                page_count = self._get_pdf_page_count(file_path)
                self.logger.info(f"PDF page count: {page_count}")
                
                if page_count > MAX_PDF_PAGES:
                    self.logger.info(f"PDF has {page_count} pages (>{MAX_PDF_PAGES}), splitting into chunks")
                    
                    chunk_paths = self._split_pdf(file_path)
                    
                    if not chunk_paths:
                        return {
                            'success': False, 
                            'error': f'This PDF has {page_count} pages which exceeds the {MAX_PDF_PAGES} page limit. '
                                     f'Please split it into smaller files and upload each section separately.'
                        }
                    
                    # Parse each chunk
                    chunk_results = []
                    try:
                        for i, chunk_path in enumerate(chunk_paths):
                            self.logger.info(f"Parsing chunk {i+1}/{len(chunk_paths)}")
                            result = self._parse_single_file(
                                chunk_path, media_type, document_type, system_type, floor_level
                            )
                            chunk_results.append(result)
                    finally:
                        # Clean up temp files
                        for chunk_path in chunk_paths:
                            try:
                                os.unlink(chunk_path)
                            except OSError:
                                pass
                    
                    # Merge all chunk results
                    return self._merge_results(chunk_results)
            
            # ---- Standard single-file parse ----
            return self._parse_single_file(file_path, media_type, document_type, system_type, floor_level)
            
        except anthropic.BadRequestError as e:
            error_msg = str(e)
            self.logger.error(f"Anthropic API error: {error_msg}")
            
            # Friendly error for "Could not process PDF"
            if 'Could not process PDF' in error_msg:
                return {
                    'success': False,
                    'error': 'This PDF could not be processed. It may be corrupted, scanned at too low a resolution, '
                             'or in an unsupported format. Try re-exporting it from the original software, '
                             'or convert it to PNG/JPG images and upload those instead.'
                }
            
            # Friendly error for page limit (shouldn't hit this now, but just in case)
            if '100 PDF pages' in error_msg:
                return {
                    'success': False,
                    'error': 'This PDF exceeds the 100 page limit. Please split it into smaller files '
                             'and upload each section separately.'
                }
            
            return {'success': False, 'error': f'API error: {error_msg}'}
            
        except Exception as e:
            self.logger.error(f"Drawing parse error: {str(e)}")
            import traceback
            self.logger.error(traceback.format_exc())
            return {'success': False, 'error': str(e)}
    
    def _parse_single_file(self, file_path: str, media_type: str,
                           document_type: str, system_type: str, 
                           floor_level: str) -> Dict:
        """Parse a single file (PDF or image) through Claude API"""
        
        # Read file
        with open(file_path, 'rb') as f:
            file_data = base64.standard_b64encode(f.read()).decode('utf-8')
        
        # Determine content type for API
        content_type = "document" if media_type == 'application/pdf' else "image"
        
        # Get the appropriate prompt based on document type
        if document_type == 'schedule':
            prompt = self._get_schedule_prompt(system_type)
        else:
            prompt = self._get_drawing_prompt(system_type, floor_level)
        
        # Call Claude API
        message = self.client.messages.create(
            model="claude-sonnet-4-20250514",
            max_tokens=8192,
            messages=[{
                "role": "user",
                "content": [
                    {
                        "type": content_type,
                        "source": {
                            "type": "base64",
                            "media_type": media_type,
                            "data": file_data
                        }
                    },
                    {
                        "type": "text",
                        "text": prompt
                    }
                ]
            }]
        )
        
        # Parse response
        response_text = message.content[0].text
        self.logger.info(f"Claude response: {len(response_text)} chars")
        
        return self._parse_response(response_text, document_type)
    
    def _get_drawing_prompt(self, system_type: str, floor_level: str) -> str:
        """Get prompt for parsing electrical layout drawings"""
        
        system_focus = ""
        if system_type == 'lighting':
            system_focus = """
FOCUS ON LIGHTING ITEMS:
- Downlights (fixed, adjustable, IP rated)
- Wall lights (internal and external)
- Floor lights
- LED tape and profiles
- Pendant points
- Emergency lighting
- Switches (1G, 2G, 3G, 4G - normal and dimmer)
- PIR/presence sensors
- Lighting control panels
"""
        elif system_type == 'power':
            system_focus = """
FOCUS ON POWER ITEMS:
- Double sockets (standard and USB)
- Single sockets
- Switched fused spurs
- Isolators
- Cooker outlets
- Shaver sockets
- Distribution boards
- RCBOs and MCBs
"""
        elif system_type == 'data':
            system_focus = """
FOCUS ON DATA/COMMS ITEMS:
- Data points (Cat6, Cat6A)
- TV/Coax points
- WiFi access points
- CCTV camera points
- Doorbell points
- Data cabinets
- Patch panels
"""
        elif system_type == 'fire_alarm':
            system_focus = """
FOCUS ON FIRE ALARM ITEMS:
- Smoke detectors
- Heat detectors
- Multi-sensor detectors
- Manual call points
- Sounders/beacons
- Fire alarm panels
"""
        
        return f"""You are an expert electrical estimator analysing electrical installation drawings.

Extract ALL electrical items shown on this drawing and return a materials list.
{system_focus}

CRITICAL: Count EVERY symbol on the drawing. Be thorough - missing items costs money!

For each item found, determine:
1. The type of item (from the legend or by recognising standard symbols)
2. The quantity (count carefully!)
3. A standard part number if you can identify the specific product
4. The appropriate category

Return ONLY valid JSON, no markdown, no code fences, no explanation before or after:
{{
    "success": true,
    "drawing_info": {{
        "scale": "1:50 or as shown",
        "drawing_number": "if visible",
        "title": "drawing title if shown",
        "floor_level": "{floor_level or 'unknown'}"
    }},
    "materials": [
        {{
            "category": "Lighting|Power|Data|Fire Alarm|Distribution|Cable|Containment|Accessories|Sundries",
            "part_number": "standard part number if identifiable",
            "description": "clear description of the item",
            "manufacturer": "if specified in legend",
            "quantity": 1,
            "unit": "each|m|box|roll",
            "unit_cost": null,
            "price_source": "estimated",
            "notes": "any relevant notes"
        }}
    ],
    "cable_estimates": {{
        "notes": "Brief notes on cable runs if you can estimate",
        "estimated_lighting_cable_m": 0,
        "estimated_power_cable_m": 0,
        "estimated_data_cable_m": 0
    }},
    "observations": [
        "Any important observations about the installation"
    ]
}}

MATERIAL CATEGORIES:
- Distribution: Consumer units, DBs, isolators, MCBs, RCBOs
- Cable: All cable types (T&E, SWA, data, fire)
- Accessories: Sockets, switches, dimmers, spurs, plates
- Lighting: All light fittings, LED tape, drivers
- Sensors: PIR, presence, motion detectors
- Fire Alarm: Smoke, heat, multi-sensor detectors
- Data: Data points, patch panels, WiFi APs
- Containment: Conduit, trunking, tray
- Sundries: Back boxes, fixings, terminations

COUNTING TIPS:
- Count each symbol individually
- Group identical items with quantity
- Note if items appear in multiple locations
- Include items shown in the legend even if not all placed

BE THOROUGH - this will be used for pricing!"""

    def _get_schedule_prompt(self, system_type: str) -> str:
        """Get prompt for parsing circuit schedules"""
        
        return """You are an expert electrical estimator analysing an electrical circuit schedule.

Extract ALL circuits and components from this schedule.

Return ONLY valid JSON, no markdown, no code fences, no explanation before or after:
{
    "success": true,
    "schedule_info": {
        "db_reference": "DB-1, DB-2, etc",
        "supply_type": "single_phase or three_phase",
        "total_ways": 0,
        "spare_ways": 0
    },
    "circuits": [
        {
            "circuit_number": "1",
            "description": "Lighting Ground Floor",
            "cable_type": "2.5mm² 2C+E",
            "cable_length_m": 45,
            "protection": "RCBO B16",
            "load_amps": 10
        }
    ],
    "distribution_materials": [
        {
            "category": "Distribution",
            "part_number": "part number if shown",
            "description": "item description",
            "manufacturer": "Hager/Schneider/etc",
            "quantity": 1,
            "unit": "each"
        }
    ],
    "cable_requirements": [
        {
            "category": "Cable",
            "part_number": "cable code",
            "description": "1.5mm² 2C+E LSZH T&E",
            "quantity": 250,
            "unit": "m"
        }
    ]
}

EXTRACT:
1. Distribution board specification (ways, type, manufacturer)
2. All MCBs/RCBOs with ratings
3. Cable types and lengths for each circuit
4. Main switch and isolator requirements
5. SPD if specified

Be precise with cable lengths - they're shown on the schedule."""

    def _parse_response(self, text: str, document_type: str) -> Dict:
        """Parse Claude's JSON response with robust handling"""
        try:
            # Clean up response - strip whitespace
            text = text.strip()
            
            # Remove markdown code fences (```json ... ``` or ``` ... ```)
            if text.startswith('```'):
                # Find the end fence
                lines = text.split('\n')
                # Remove first line (```json or ```)
                lines = lines[1:]
                # Remove last line if it's ```
                if lines and lines[-1].strip() == '```':
                    lines = lines[:-1]
                text = '\n'.join(lines).strip()
            
            # Also handle case where there's text before the JSON
            # Find the first { and last }
            json_start = text.find('{')
            json_end = text.rfind('}')
            
            if json_start == -1 or json_end == -1:
                self.logger.error(f"No JSON object found in response. First 200 chars: {text[:200]}")
                return {'success': False, 'error': 'AI response did not contain valid JSON. Please try parsing again.'}
            
            json_text = text[json_start:json_end + 1]
            
            try:
                data = json.loads(json_text)
            except json.JSONDecodeError:
                # Try fixing common issues: trailing commas
                cleaned = re.sub(r',\s*}', '}', json_text)
                cleaned = re.sub(r',\s*]', ']', cleaned)
                try:
                    data = json.loads(cleaned)
                except json.JSONDecodeError as e:
                    self.logger.error(f"JSON parse error after cleanup: {str(e)}")
                    self.logger.error(f"Response text (first 500 chars): {text[:500]}")
                    return {'success': False, 'error': 'Failed to parse AI response. Please try parsing this drawing again.'}
            
            if not data.get('success', True):
                return data
            
            # Transform to standard format
            materials = []
            
            # Handle drawing response
            if 'materials' in data:
                materials.extend(data['materials'])
            
            # Handle schedule response
            if 'distribution_materials' in data:
                materials.extend(data['distribution_materials'])
            if 'cable_requirements' in data:
                materials.extend(data['cable_requirements'])
            
            # Add estimated cables if provided
            if 'cable_estimates' in data:
                estimates = data['cable_estimates']
                
                if estimates.get('estimated_lighting_cable_m', 0) > 0:
                    materials.append({
                        'category': 'Cable',
                        'part_number': '6242Y-1.5',
                        'description': '1.5mm² 2C+E LSZH T&E (Lighting)',
                        'quantity': estimates['estimated_lighting_cable_m'],
                        'unit': 'm',
                        'price_source': 'estimated'
                    })
                
                if estimates.get('estimated_power_cable_m', 0) > 0:
                    materials.append({
                        'category': 'Cable',
                        'part_number': '6242Y-2.5',
                        'description': '2.5mm² 2C+E LSZH T&E (Power)',
                        'quantity': estimates['estimated_power_cable_m'],
                        'unit': 'm',
                        'price_source': 'estimated'
                    })
                
                if estimates.get('estimated_data_cable_m', 0) > 0:
                    materials.append({
                        'category': 'Cable',
                        'part_number': 'CAT6A-LSZH',
                        'description': 'CAT6A U/FTP LSZH Data Cable',
                        'quantity': estimates['estimated_data_cable_m'],
                        'unit': 'm',
                        'price_source': 'estimated'
                    })
            
            return {
                'success': True,
                'materials': materials,
                'drawing_info': data.get('drawing_info', {}),
                'schedule_info': data.get('schedule_info', {}),
                'circuits': data.get('circuits', []),
                'observations': data.get('observations', []),
                'scale': data.get('drawing_info', {}).get('scale'),
                'drawing_number': data.get('drawing_info', {}).get('drawing_number'),
            }
            
        except json.JSONDecodeError as e:
            self.logger.error(f"JSON parse error: {str(e)}")
            return {'success': False, 'error': 'Failed to parse AI response. Please try parsing this drawing again.'}
        except Exception as e:
            self.logger.error(f"Response parsing error: {str(e)}")
            return {'success': False, 'error': str(e)}


class MaterialsDatabase:
    """Standard electrical materials with typical pricing"""
    
    # This would normally come from a database, but here's a starter set
    STANDARD_MATERIALS = {
        # Distribution
        'db_18way_spn': {'desc': 'Consumer Unit 18 Way SP&N + SPD', 'unit': 'each', 'cost': 285},
        'db_24way_spn': {'desc': 'Consumer Unit 24 Way SP&N + SPD', 'unit': 'each', 'cost': 320},
        'rcbo_b16': {'desc': 'RCBO Type B 16A 30mA', 'unit': 'each', 'cost': 48},
        'rcbo_b32': {'desc': 'RCBO Type B 32A 30mA', 'unit': 'each', 'cost': 52},
        
        # Cable
        '6242Y-1.5': {'desc': '1.5mm² 2C+E LSZH T&E', 'unit': 'm', 'cost': 0.72},
        '6242Y-2.5': {'desc': '2.5mm² 2C+E LSZH T&E', 'unit': 'm', 'cost': 1.05},
        '6243Y-1.5': {'desc': '1.5mm² 3C+E LSZH T&E', 'unit': 'm', 'cost': 0.95},
        'CAT6A-LSZH': {'desc': 'CAT6A U/FTP LSZH', 'unit': 'm', 'cost': 0.95},
        
        # Accessories - Standard
        'socket_2g': {'desc': 'Double Socket 13A', 'unit': 'each', 'cost': 8},
        'socket_2g_usb': {'desc': 'Double Socket 13A + USB', 'unit': 'each', 'cost': 18},
        'switch_1g': {'desc': '1 Gang 2 Way Switch', 'unit': 'each', 'cost': 5},
        'switch_2g': {'desc': '2 Gang 2 Way Switch', 'unit': 'each', 'cost': 7},
        'dimmer_1g': {'desc': '1 Gang LED Dimmer', 'unit': 'each', 'cost': 25},
        'dimmer_2g': {'desc': '2 Gang LED Dimmer', 'unit': 'each', 'cost': 35},
        'fcu_switched': {'desc': 'Switched Fused Spur', 'unit': 'each', 'cost': 8},
        
        # Back Boxes
        'bb_1g_47mm': {'desc': '1G Metal Back Box 47mm', 'unit': 'each', 'cost': 2.80},
        'bb_2g_47mm': {'desc': '2G Metal Back Box 47mm', 'unit': 'each', 'cost': 3.50},
        
        # Fire Alarm
        'smoke_optical': {'desc': 'Optical Smoke Detector Mains', 'unit': 'each', 'cost': 42},
        'heat_detector': {'desc': 'Heat Detector Mains', 'unit': 'each', 'cost': 38},
        
        # Lighting (provisional)
        'downlight_fire_rated': {'desc': 'Fire Rated Downlight LED', 'unit': 'each', 'cost': 35},
        'downlight_ip65': {'desc': 'IP65 Fire Rated Downlight', 'unit': 'each', 'cost': 45},
    }
    
    @classmethod
    def get_estimated_cost(cls, part_number: str) -> float:
        """Get estimated cost for a part number"""
        if part_number in cls.STANDARD_MATERIALS:
            return cls.STANDARD_MATERIALS[part_number]['cost']
        return None
    
    @classmethod
    def enrich_materials(cls, materials: List[Dict]) -> List[Dict]:
        """Add estimated costs to materials without prices"""
        for material in materials:
            if not material.get('unit_cost'):
                part = material.get('part_number', '')
                estimated = cls.get_estimated_cost(part)
                if estimated:
                    material['unit_cost'] = estimated
                    material['price_source'] = 'estimated'
        return materials
