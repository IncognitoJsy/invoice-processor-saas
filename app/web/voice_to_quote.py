"""Voice-to-Quote: Parse Plaud transcriptions into structured materials lists"""
from flask import Blueprint, request, jsonify, render_template, current_app
from flask_login import login_required, current_user
from app.extensions import db
import anthropic
import json
import os
import logging

logger = logging.getLogger(__name__)

bp = Blueprint('voice_to_quote', __name__, url_prefix='/voice-to-quote')


def get_knowledge_base():
    """Load the electrical knowledge base from file"""
    kb_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'data', 'electrical_knowledge_base.md')
    try:
        with open(kb_path, 'r') as f:
            return f.read()
    except FileNotFoundError:
        logger.error(f"Knowledge base not found at {kb_path}")
        return ""


def get_user_preferences(user_id):
    """Load user-specific preferences (brand defaults, circuit preferences, etc.)"""
    # TODO: Pull from user settings table once built
    # For now, return empty dict — knowledge base defaults apply
    return {}


def get_user_products(user_id):
    """Pull user's product list from Xero/QuickBooks for price matching"""
    # TODO: Query user's connected accounting system
    # Returns list of {part_number, description, unit_price, supplier}
    return []


def build_system_prompt(knowledge_base, user_preferences, user_products, has_floor_plan=False):
    """Build the full system prompt for Claude API"""
    
    prompt = f"""You are GoZappify's electrical installation AI parser. Your job is to parse voice transcriptions from site visits into structured materials lists for quoting.

REFERENCE DOCUMENT — Apply these rules unless the transcription explicitly states otherwise:

{knowledge_base}

"""
    
    if user_preferences:
        prompt += f"""
USER PREFERENCES — These override knowledge base defaults where applicable:
{json.dumps(user_preferences, indent=2)}

"""
    
    if user_products:
        prompt += f"""
USER PRODUCT LIST — Match parsed items against these products FIRST (from user's accounting system):
{json.dumps(user_products[:200], indent=2)}

When matching, always use the MORE EXPENSIVE option if multiple similar products exist.
"""
    
    if has_floor_plan:
        prompt += """
A floor plan image has been provided for reference. Use it to:
- Validate room dimensions against the transcription
- Check door/window positions for switch placement
- Identify rooms not mentioned in the transcription
- Understand cable routing context

The transcription is the PRIMARY source — the plan is supplementary context ONLY.
Do NOT add items to the materials list based on the plan alone.
"""
    
    prompt += """
INSTRUCTIONS:
1. Parse the transcription into structured room-by-room data
2. Detect and apply job-level settings (finish, wall type) vs room-level overrides
3. Handle mid-speech corrections — use the CORRECTED value after "sorry", "actually", "apologies", etc.
4. For EVERY switch position, use 2-way switches (WMPS12) even if described as 1-way
5. Resolve part numbers using knowledge base defaults
6. Calculate cable estimates where room dimensions are provided
7. Include all sundries (earth sleeving, clips, Wagos, conduit drops)
8. Flag anything ambiguous with clear questions the user can answer
9. Generate BOTH per-room materials list AND combined supplier materials list

CRITICAL RULES — NEVER VIOLATE THESE:
- NEVER use 25mm metal boxes — default is 35mm, "deep" means 47mm
- NEVER spec 1-way switches — always use 2-way (WMPS12 for standard, WMGS12 for grid)
- 3-gang and 4-gang plates (grid AND dimmer) need TWIN (2-gang) back boxes, NOT single
- NeoStat-E = electric UFH (mat + accessories). Any other NeoStat = wet UFH (thermostat only)
- NeoStat thermostats need a single (1-gang) back box
- Extractor fans ALWAYS include fan isolator (WMPS3PIF) + single back box, wired to lighting switch
- Default extractor: Envirovent SIL100T (built-in run-on timer)
- Shaver sockets ALWAYS need 47mm deep back box
- Bathroom switches go on EXTERNAL wall outside entrance, never inside
- Data/TV/telephone consolidate onto euro module plates (WMP2EU/WMP4EU), NOT individual face plates
- Euro modules: WMMRJ45 (data), WMMQX (TV/SAT), WMMBTM (telephone), WMMB (blank)
- Dimmer positions use WMDRPXKIT system, NOT grid (WMGP/WMGF34)
- Grid switch positions use WMGP + WMGF34 frame + WMGS12 (2-way) or WMGS16 (intermediate)
- WMGF34 is universal — same frame for 3-gang and 4-gang plates
- LED tape default brand: FOSS
- Smoke alarms: Aico Ei146e (or Ei3016). Heat alarms: Aico Ei144e (or Ei3014). CO alarms: Aico Ei3018. All mains interlinked.
- Detection always on dedicated circuit (6A RCBO)
- Towel rails connect via flex outlet plate (WMP2FO), NOT FCU
- Pendant default: Hager WPS6 ceiling rose + B22 LED lamp 7.5-8W (or wire to position if client supplies)
- Collingwood DLT5515000 is the default downlight (colour & wattage switchable, matt white bezel)
- Collingwood GLO19 in-ground lights are IP68 — safe for all bathroom zones
- Wall-mounted heaters/radiators default to Rointe Kyros RAD4: KRIW0600RAD4 (up to 9m²), KRIW1200RAD4 (9-18m²), KRIW1800RAD4 (18m²+)
- Size radiators from room dimensions automatically when available
- Worktop sockets: 1060mm from FFL (910mm worktop + 150mm above)
- Standard sockets: 450mm FFL. Switches: 1200mm FFL.
- "All walls" mentioned in any room context = job-level unless clearly room-specific
- Circuits continue between rooms — only add board run if user specifies distance or dedicated circuit
- When multiple suppliers stock similar items, quote the MORE EXPENSIVE option

Return valid JSON matching this structure:
{
  "job": {
    "title": "string",
    "client": "string or null",
    "scope": "string",
    "default_wall_type": "string or null",
    "default_finish": "string or null",
    "default_back_box_depth": "35mm"
  },
  "rooms": [
    {
      "name": "string",
      "dimensions": {"length": number, "width": number, "height": number} or null,
      "wall_type": "string",
      "wall_type_source": "job_level | room_level | flagged",
      "finish": "string",
      "accessories": [
        {
          "type": "string",
          "quantity": number,
          "part_number": "string or null",
          "description": "string",
          "back_box": "string or null",
          "back_box_part": "string or null",
          "circuit": "string",
          "cable_type": "string",
          "notes": "string or null"
        }
      ],
      "switching": [
        {
          "location": "string",
          "system": "grid | dimmer | standard",
          "components": [
            {"quantity": number, "part_number": "string", "description": "string"}
          ],
          "back_box": "string",
          "notes": "string or null"
        }
      ],
      "cable_summary": {
        "cable_type": {"metres": number, "calculation": "string"}
      },
      "sundries": [
        {"item": "string", "quantity": "string", "calculation": "string"}
      ],
      "flags": [
        {"message": "string", "severity": "amber | red", "default_value": "string or null"}
      ]
    }
  ],
  "combined_materials": [
    {
      "part_number": "string",
      "description": "string",
      "total_quantity": number,
      "unit": "each | metres | lengths"
    }
  ],
  "global_flags": [
    {"message": "string", "severity": "amber | red"}
  ]
}
"""
    return prompt


@bp.route('/')
@login_required
def index():
    """Voice-to-quote main page"""
    return render_template('voice_to_quote/index.html')


@bp.route('/parse', methods=['POST'])
@login_required
def parse_transcription():
    """Parse a transcription and return structured materials list"""
    try:
        # Handle both JSON and FormData (when floor plan is attached)
        if request.content_type and 'multipart/form-data' in request.content_type:
            transcription = request.form.get('transcription', '').strip()
        else:
            data = request.get_json()
            transcription = data.get('transcription', '').strip() if data else ''
        
        job_id = request.form.get('job_id') or (data.get('job_id') if not request.content_type or 'multipart' not in request.content_type else None)
        
        if not transcription:
            return jsonify({'error': 'No transcription provided'}), 400
        
        if len(transcription) < 20:
            return jsonify({'error': 'Transcription too short — please provide more detail'}), 400
        
        # Load knowledge base and user context
        knowledge_base = get_knowledge_base()
        if not knowledge_base:
            return jsonify({'error': 'Knowledge base not found — contact support'}), 500
        
        user_preferences = get_user_preferences(current_user.id)
        user_products = get_user_products(current_user.id)
        
        # Check for floor plan image
        has_floor_plan = False
        floor_plan_data = None
        floor_plan_ext = None
        if 'floor_plan' in request.files:
            floor_plan_file = request.files['floor_plan']
            if floor_plan_file.filename:
                import base64
                floor_plan_data = base64.b64encode(floor_plan_file.read()).decode('utf-8')
                floor_plan_ext = floor_plan_file.filename.rsplit('.', 1)[-1].lower()
                has_floor_plan = True
        
        # Build system prompt
        system_prompt = build_system_prompt(
            knowledge_base, user_preferences, user_products, has_floor_plan
        )
        
        # Build messages
        user_content = []
        
        if has_floor_plan and floor_plan_data:
            media_type_map = {
                'jpg': 'image/jpeg', 'jpeg': 'image/jpeg',
                'png': 'image/png', 'gif': 'image/gif',
                'webp': 'image/webp'
            }
            media_type = media_type_map.get(floor_plan_ext, 'image/jpeg')
            user_content.append({
                "type": "image",
                "source": {
                    "type": "base64",
                    "media_type": media_type,
                    "data": floor_plan_data
                }
            })
        
        user_content.append({
            "type": "text",
            "text": f"""Parse this site visit transcription into a structured materials list:

---
{transcription}
---

Return the full structured JSON output with all materials, quantities, cable estimates, and flags.
Return ONLY valid JSON — no markdown, no backticks, no explanation before or after."""
        })
        
        # Call Claude API
        api_key = os.getenv('ANTHROPIC_API_KEY')
        if not api_key:
            return jsonify({'error': 'Claude API key not configured'}), 500
        
        client = anthropic.Anthropic(api_key=api_key)
        
        message = client.messages.create(
            model="claude-sonnet-4-20250514",
            max_tokens=8000,
            system=system_prompt,
            messages=[
                {"role": "user", "content": user_content}
            ]
        )
        
        # Extract response text
        response_text = ""
        for block in message.content:
            if hasattr(block, 'text'):
                response_text += block.text
        
        # Parse JSON from response — strip markdown fences if present
        response_text = response_text.strip()
        if response_text.startswith('```'):
            response_text = response_text.split('\n', 1)[1]
            if response_text.endswith('```'):
                response_text = response_text[:-3]
            response_text = response_text.strip()
        
        try:
            parsed_data = json.loads(response_text)
        except json.JSONDecodeError as e:
            logger.error(f"Failed to parse Claude response as JSON: {e}")
            logger.error(f"Response was: {response_text[:500]}")
            return jsonify({
                'error': 'AI returned invalid format — please try again',
                'raw_response': response_text[:1000]
            }), 500
        
        # TODO: If job_id provided, merge with existing job data
        # TODO: Save parsed data to database
        # TODO: Match against user's Xero/QB product list for pricing
        
        return jsonify({
            'success': True,
            'data': parsed_data,
            'token_usage': {
                'input': message.usage.input_tokens,
                'output': message.usage.output_tokens
            }
        })
        
    except anthropic.APIError as e:
        logger.error(f"Claude API error: {e}")
        return jsonify({'error': f'AI service error: {str(e)}'}), 500
    except Exception as e:
        logger.error(f"Parse transcription error: {e}", exc_info=True)
        return jsonify({'error': f'Unexpected error: {str(e)}'}), 500


@bp.route('/update-item', methods=['POST'])
@login_required
def update_item():
    """Update a parsed item (resolve flag, change quantity, etc.)"""
    try:
        data = request.get_json()
        # TODO: Update the parsed data in session/database
        # This is the endpoint the review UI calls when user confirms/changes a flag
        return jsonify({'success': True})
    except Exception as e:
        return jsonify({'error': str(e)}), 500
