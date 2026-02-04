"""Drawing Parser - AI-powered extraction of materials from electrical drawings"""
import anthropic
import os
import base64
import json
import logging
from typing import Dict, List
from datetime import datetime

logger = logging.getLogger(__name__)


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
            
        except Exception as e:
            self.logger.error(f"Drawing parse error: {str(e)}")
            import traceback
            self.logger.error(traceback.format_exc())
            return {'success': False, 'error': str(e)}
    
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

Return ONLY valid JSON, no markdown:
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

Return ONLY valid JSON, no markdown:
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
        """Parse Claude's JSON response"""
        try:
            # Clean up response
            text = text.strip()
            if text.startswith('```'):
                lines = text.split('\n')
                text = '\n'.join(lines[1:-1])
            
            data = json.loads(text)
            
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
            return {'success': False, 'error': f'Failed to parse response: {str(e)}'}
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
