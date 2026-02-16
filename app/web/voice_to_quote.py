"""Voice-to-Quote: Parse Plaud transcriptions into structured materials lists"""
from flask import Blueprint, request, jsonify, render_template, current_app
from flask_login import login_required, current_user
from app.extensions import db
from app.models.user_preference import UserPreference, CorrectionLog, ProductCache
from datetime import datetime, timedelta
import anthropic
import json
import os
import logging

logger = logging.getLogger(__name__)

bp = Blueprint('voice_to_quote', __name__, url_prefix='/voice-to-quote')

PRODUCT_CACHE_TTL_HOURS = 24  # Refresh cache if older than this


def get_knowledge_base():
    """Load the electrical knowledge base from file"""
    kb_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'data', 'electrical_knowledge_base.md')
    try:
        with open(kb_path, 'r') as f:
            return f.read()
    except FileNotFoundError:
        logger.error(f"Knowledge base not found at {kb_path}")
        return ""


def get_user_preferences_formatted(user_id):
    """Load user preferences formatted for the AI prompt"""
    prefs = UserPreference.query.filter_by(user_id=user_id, active=True).all()
    if not prefs:
        return ""
    
    categories = {}
    for p in prefs:
        if p.category not in categories:
            categories[p.category] = []
        categories[p.category].append(p.to_prompt_line())
    
    lines = []
    category_labels = {
        'brand_default': 'Brand Defaults',
        'product_swap': 'Product Swaps',
        'mounting_height': 'Mounting Heights',
        'circuit_preference': 'Circuit Preferences',
        'supplier': 'Supplier Preferences',
        'cable_preference': 'Cable Preferences',
        'general': 'General Preferences',
    }
    
    for cat, items in categories.items():
        label = category_labels.get(cat, cat.replace('_', ' ').title())
        lines.append(f"\n### {label}")
        lines.extend(items)
    
    return "\n".join(lines)


def get_user_products(user_id):
    """Pull user's product list from Xero/QuickBooks for price matching"""
    try:
        from app.models.connection import Connection
        conn = Connection.query.filter_by(user_id=user_id, active=True).first()
        if not conn:
            return []
        
        from app.services.product_matcher import fetch_user_products
        from flask_login import current_user
        return fetch_user_products(current_user)
    except ImportError:
        logger.warning("Product matcher not available — skipping product fetch")
        return []
    except Exception as e:
        logger.error(f"Failed to fetch user products: {e}")
        return []


def build_system_prompt(knowledge_base, user_preferences_text, user_products, has_floor_plan=False):
    """Build the full system prompt for Claude API"""
    
    prompt = f"""You are GoZappify's electrical installation AI parser. Your job is to parse voice transcriptions from site visits into structured materials lists for quoting.

REFERENCE DOCUMENT — Apply these rules unless the transcription explicitly states otherwise:

{knowledge_base}

"""
    
    if user_preferences_text:
        prompt += f"""
USER PREFERENCES — These OVERRIDE knowledge base defaults where they conflict:
{user_preferences_text}

IMPORTANT: User preferences always take priority over knowledge base defaults.
If the user's preference says "Default downlight: Aurora EN-DE52BZ/40", use that instead of Collingwood DLT5515000.
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
    
    prompt += """INSTRUCTIONS:
1. Parse the transcription into structured room-by-room data
2. Detect and apply job-level settings (finish, wall type) vs room-level overrides
3. Handle mid-speech corrections — use the CORRECTED value after "sorry", "actually", "apologies", etc.
4. For EVERY switch position, use 2-way switches (WMPS12) even if described as 1-way
5. Resolve part numbers using knowledge base defaults (then user preferences override)
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


# ─────────────────────────────────────────────────────────
# ROUTES
# ─────────────────────────────────────────────────────────

@bp.route('/')
@login_required
def index():
    """Voice-to-quote main page"""
    return render_template('voice_to_quote/index.html')


@bp.route('/teach')
@login_required
def teach_ai():
    """Teach AI page — chat interface for managing preferences"""
    return render_template('voice_to_quote/teach_ai.html')


@bp.route('/parse', methods=['POST'])
@login_required
def parse_transcription():
    """Parse a transcription and return structured materials list"""
    try:
        if request.content_type and 'multipart/form-data' in request.content_type:
            transcription = request.form.get('transcription', '').strip()
            data = {}
        else:
            data = request.get_json() or {}
            transcription = data.get('transcription', '').strip()
        
        job_id = request.form.get('job_id') or data.get('job_id')
        
        if not transcription:
            return jsonify({'error': 'No transcription provided'}), 400
        
        if len(transcription) < 20:
            return jsonify({'error': 'Transcription too short — please provide more detail'}), 400
        
        knowledge_base = get_knowledge_base()
        if not knowledge_base:
            return jsonify({'error': 'Knowledge base not found — contact support'}), 500
        
        user_preferences_text = get_user_preferences_formatted(current_user.id)
        user_products = get_user_products(current_user.id)
        
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
        
        system_prompt = build_system_prompt(
            knowledge_base, user_preferences_text, user_products, has_floor_plan
        )
        
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
        
        response_text = ""
        for block in message.content:
            if hasattr(block, 'text'):
                response_text += block.text
        
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


# ─────────────────────────────────────────────────────────
# TEACH AI — Chat interface for preference management
# ─────────────────────────────────────────────────────────

@bp.route('/teach/chat', methods=['POST'])
@login_required
def teach_ai_chat():
    """Process a Teach AI chat message — parse natural language into preference updates"""
    try:
        data = request.get_json()
        message = data.get('message', '').strip()
        chat_history = data.get('history', [])
        
        if not message:
            return jsonify({'error': 'No message provided'}), 400
        
        prefs = UserPreference.query.filter_by(user_id=current_user.id, active=True).all()
        prefs_summary = "\n".join([f"- [{p.category}] {p.key}: {p.value}" for p in prefs]) if prefs else "No preferences set yet."
        
        api_key = os.getenv('ANTHROPIC_API_KEY')
        if not api_key:
            return jsonify({'error': 'Claude API key not configured'}), 500
        
        client = anthropic.Anthropic(api_key=api_key)
        
        system_prompt = f"""You are GoZappify's Teach AI assistant. You help UK electrical contractors set up their personal preferences so the Voice-to-Quote AI produces better results for them.

YOUR JOB:
1. Understand what the user wants to change about how the AI quotes for them
2. Convert their natural language into structured preference updates
3. Confirm what you're saving before saving it
4. Answer questions about their current preferences

CURRENT USER PREFERENCES:
{prefs_summary}

VALID PREFERENCE CATEGORIES:
- brand_default: Default brand/product for a type of fitting (e.g. "downlight", "socket", "switch", "smoke_detector", "extractor_fan", "radiator", "led_tape")
- product_swap: Replace specific part numbers (key = old part number, value = new part number)
- mounting_height: Custom heights in mm FFL (e.g. "sockets", "switches", "worktop_sockets")
- circuit_preference: How they wire circuits (e.g. "kitchen_sockets: radial", "lighting: separate per room")
- supplier: Preferred supplier for product types (e.g. "lighting: Edmundson", "general: CEF")
- cable_preference: Cable type preferences (e.g. "sockets: 2.5mm T&E", "lighting: 1.5mm T&E")
- general: Anything else (e.g. "back_box_depth: 47mm", "finish: chrome", "always_use_metal_boxes: true")

When the user tells you a preference, respond with:
1. A confirmation of what you understood
2. A JSON block (wrapped in ```json ... ```) with the actions to take:

```json
{{
  "actions": [
    {{
      "type": "add" | "update" | "remove",
      "category": "string",
      "key": "string",
      "value": "string",
      "description": "human-readable explanation"
    }}
  ]
}}
```

IMPORTANT RULES:
- Be conversational and friendly — these are sparkies, not developers
- If something is ambiguous, ASK before saving
- If they ask "what do you know about me" or "show my preferences", list them clearly
- If they say "remove" or "delete" or "forget" something, use type: "remove"
- If they update an existing preference, use type: "update"
- Multiple preferences in one message = multiple actions
- Keep your responses concise — sparkies don't want essays
- If they ask about something that isn't a preference (like electrical regs), answer the question but don't create a preference
- ALWAYS include the JSON action block when making changes — the system reads it to save the preference

EXAMPLES:

User: "I always use BG Nexus for my sockets and switches"
Response: Got it — I'll set BG Nexus as your default for both sockets and switches.
```json
{{"actions": [{{"type": "add", "category": "brand_default", "key": "socket", "value": "BG Nexus", "description": "User prefers BG Nexus sockets"}}, {{"type": "add", "category": "brand_default", "key": "switch", "value": "BG Nexus", "description": "User prefers BG Nexus switches"}}]}}
```

User: "My standard downlight is the Aurora EN-DE52BZ/40"
Response: Noted — I'll use the Aurora EN-DE52BZ/40 as your default downlight instead of Collingwood.
```json
{{"actions": [{{"type": "add", "category": "brand_default", "key": "downlight", "value": "Aurora EN-DE52BZ/40", "description": "User prefers Aurora downlights over Collingwood"}}]}}
```

User: "What's my default downlight?"
Response: [Check preferences and answer — no JSON block needed]
"""
        
        messages = []
        for h in chat_history[-10:]:
            messages.append({"role": h["role"], "content": h["content"]})
        messages.append({"role": "user", "content": message})
        
        response = client.messages.create(
            model="claude-sonnet-4-20250514",
            max_tokens=1500,
            system=system_prompt,
            messages=messages
        )
        
        response_text = ""
        for block in response.content:
            if hasattr(block, 'text'):
                response_text += block.text
        
        # Check if response contains JSON actions to apply
        actions_applied = []
        if '```json' in response_text:
            try:
                json_start = response_text.index('```json') + 7
                json_end = response_text.index('```', json_start)
                json_str = response_text[json_start:json_end].strip()
                actions_data = json.loads(json_str)
                
                if 'actions' in actions_data:
                    for action in actions_data['actions']:
                        result = apply_preference_action(
                            current_user.id,
                            action.get('type', 'add'),
                            action.get('category', 'general'),
                            action.get('key', ''),
                            action.get('value', ''),
                            action.get('description', '')
                        )
                        actions_applied.append(result)
                    
                    db.session.commit()
            except (ValueError, json.JSONDecodeError, KeyError) as e:
                logger.warning(f"Failed to parse Teach AI actions: {e}")
        
        # Strip the JSON block from the response shown to user
        clean_response = response_text
        if '```json' in clean_response:
            try:
                before = clean_response[:clean_response.index('```json')]
                after_end = clean_response.index('```', clean_response.index('```json') + 7) + 3
                after = clean_response[after_end:]
                clean_response = (before + after).strip()
            except ValueError:
                pass
        
        return jsonify({
            'success': True,
            'response': clean_response,
            'actions_applied': actions_applied,
            'token_usage': {
                'input': response.usage.input_tokens,
                'output': response.usage.output_tokens
            }
        })
        
    except anthropic.APIError as e:
        logger.error(f"Teach AI API error: {e}")
        return jsonify({'error': f'AI service error: {str(e)}'}), 500
    except Exception as e:
        logger.error(f"Teach AI error: {e}", exc_info=True)
        return jsonify({'error': f'Unexpected error: {str(e)}'}), 500


def apply_preference_action(user_id, action_type, category, key, value, description):
    """Apply a single preference action (add/update/remove)"""
    key = key.strip().lower().replace(' ', '_')
    
    existing = UserPreference.query.filter_by(
        user_id=user_id, category=category, key=key
    ).first()
    
    if action_type == 'remove':
        if existing:
            existing.active = False
            return {'action': 'removed', 'category': category, 'key': key}
        return {'action': 'not_found', 'category': category, 'key': key}
    
    if existing:
        existing.value = value
        existing.description = description
        existing.active = True
        existing.source = 'chat'
        return {'action': 'updated', 'category': category, 'key': key, 'value': value}
    else:
        pref = UserPreference(
            user_id=user_id,
            category=category,
            key=key,
            value=value,
            description=description,
            source='chat',
            active=True
        )
        db.session.add(pref)
        return {'action': 'added', 'category': category, 'key': key, 'value': value}


# ─────────────────────────────────────────────────────────
# PREFERENCES API
# ─────────────────────────────────────────────────────────

@bp.route('/preferences', methods=['GET'])
@login_required
def get_preferences():
    """Get all active preferences for the current user"""
    prefs = UserPreference.query.filter_by(
        user_id=current_user.id, active=True
    ).order_by(UserPreference.category, UserPreference.key).all()
    
    return jsonify({
        'success': True,
        'preferences': [p.to_dict() for p in prefs]
    })


@bp.route('/preferences/<int:pref_id>', methods=['DELETE'])
@login_required
def delete_preference(pref_id):
    """Delete (deactivate) a specific preference"""
    pref = UserPreference.query.filter_by(id=pref_id, user_id=current_user.id).first()
    if not pref:
        return jsonify({'error': 'Preference not found'}), 404
    pref.active = False
    db.session.commit()
    return jsonify({'success': True})


@bp.route('/preferences/<int:pref_id>', methods=['PUT'])
@login_required
def update_preference(pref_id):
    """Update a specific preference"""
    pref = UserPreference.query.filter_by(id=pref_id, user_id=current_user.id).first()
    if not pref:
        return jsonify({'error': 'Preference not found'}), 404
    data = request.get_json()
    if 'value' in data:
        pref.value = data['value']
    if 'description' in data:
        pref.description = data['description']
    if 'active' in data:
        pref.active = data['active']
    db.session.commit()
    return jsonify({'success': True, 'preference': pref.to_dict()})


# ─────────────────────────────────────────────────────────
# CORRECTION LOGGING
# ─────────────────────────────────────────────────────────

PROMOTION_THRESHOLD = 3

@bp.route('/log-correction', methods=['POST'])
@login_required
def log_correction():
    """Log a user correction on parsed results"""
    try:
        data = request.get_json()
        field_type = data.get('field_type', '').strip()
        original_value = data.get('original_value', '').strip()
        corrected_value = data.get('corrected_value', '').strip()
        
        if not field_type or not corrected_value:
            return jsonify({'error': 'Missing required fields'}), 400
        
        existing = CorrectionLog.query.filter_by(
            user_id=current_user.id,
            field_type=field_type,
            original_value=original_value,
            corrected_value=corrected_value,
            promoted=False
        ).first()
        
        if existing:
            existing.correction_count += 1
            existing.updated_at = db.func.now()
        else:
            existing = CorrectionLog(
                user_id=current_user.id,
                job_title=data.get('job_title', ''),
                room_name=data.get('room_name', ''),
                field_type=field_type,
                original_value=original_value,
                corrected_value=corrected_value,
                context=data.get('context', ''),
                correction_count=1
            )
            db.session.add(existing)
        
        db.session.flush()
        
        should_promote = False
        promotion_suggestion = None
        
        if existing.correction_count >= PROMOTION_THRESHOLD and not existing.promoted:
            should_promote = True
            category_map = {
                'part_number': 'product_swap',
                'product': 'product_swap',
                'back_box': 'general',
                'cable': 'cable_preference',
                'quantity': 'general',
            }
            category = category_map.get(field_type, 'general')
            
            promotion_suggestion = {
                'message': f"You've changed '{original_value}' to '{corrected_value}' {existing.correction_count} times. Want me to remember this?",
                'category': category,
                'key': original_value.lower().replace(' ', '_') if original_value else field_type,
                'value': corrected_value,
                'correction_id': existing.id
            }
        
        db.session.commit()
        
        return jsonify({
            'success': True,
            'correction_count': existing.correction_count,
            'should_promote': should_promote,
            'promotion_suggestion': promotion_suggestion
        })
        
    except Exception as e:
        db.session.rollback()
        logger.error(f"Log correction error: {e}", exc_info=True)
        return jsonify({'error': str(e)}), 500


@bp.route('/promote-correction', methods=['POST'])
@login_required
def promote_correction():
    """Promote a correction to a permanent preference"""
    try:
        data = request.get_json()
        correction_id = data.get('correction_id')
        
        correction = CorrectionLog.query.filter_by(
            id=correction_id, user_id=current_user.id
        ).first()
        
        if not correction:
            return jsonify({'error': 'Correction not found'}), 404
        
        category = data.get('category', 'general')
        key = data.get('key', correction.original_value or correction.field_type)
        value = data.get('value', correction.corrected_value)
        description = f"Auto-learned: changed {correction.original_value} to {correction.corrected_value} ({correction.correction_count}x)"
        
        result = apply_preference_action(current_user.id, 'add', category, key, value, description)
        
        correction.promoted = True
        db.session.commit()
        
        return jsonify({'success': True, 'preference': result})
        
    except Exception as e:
        db.session.rollback()
        logger.error(f"Promote correction error: {e}", exc_info=True)
        return jsonify({'error': str(e)}), 500


@bp.route('/update-item', methods=['POST'])
@login_required
def update_item():
    """Update a parsed item (resolve flag, change quantity, etc.)"""
    try:
        data = request.get_json()
        return jsonify({'success': True})
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@bp.route('/extract-text', methods=['POST'])
@login_required
def extract_text():
    """Extract text from uploaded PDF or DOCX files"""
    try:
        if 'file' not in request.files:
            return jsonify({'error': 'No file provided'}), 400
        
        file = request.files['file']
        if not file.filename:
            return jsonify({'error': 'No file selected'}), 400
        
        ext = file.filename.rsplit('.', 1)[-1].lower()
        
        if ext == 'txt' or ext == 'md':
            # Plain text — just read it
            text = file.read().decode('utf-8', errors='replace')
            return jsonify({'success': True, 'text': text})
        
        elif ext == 'pdf':
            # PDF extraction
            try:
                import pdfplumber
            except ImportError:
                try:
                    from PyPDF2 import PdfReader
                    reader = PdfReader(file)
                    text = ""
                    for page in reader.pages:
                        page_text = page.extract_text()
                        if page_text:
                            text += page_text + "\n"
                    if not text.strip():
                        return jsonify({'error': 'Could not extract text from PDF — it may be image-based. Try copying the text manually.'}), 400
                    return jsonify({'success': True, 'text': text.strip()})
                except ImportError:
                    return jsonify({'error': 'PDF processing not available — please paste the text manually'}), 400
            
            text = ""
            with pdfplumber.open(file) as pdf:
                for page in pdf.pages:
                    page_text = page.extract_text()
                    if page_text:
                        text += page_text + "\n"
            
            if not text.strip():
                return jsonify({'error': 'Could not extract text from PDF — it may be image-based. Try copying the text manually.'}), 400
            
            return jsonify({'success': True, 'text': text.strip()})
        
        elif ext == 'docx':
            try:
                import docx
            except ImportError:
                return jsonify({'error': 'DOCX processing not available — please paste the text manually'}), 400
            
            import io
            doc = docx.Document(io.BytesIO(file.read()))
            text = "\n".join([para.text for para in doc.paragraphs if para.text.strip()])
            
            if not text.strip():
                return jsonify({'error': 'Could not extract text from DOCX — the document appears empty.'}), 400
            
            return jsonify({'success': True, 'text': text.strip()})
        
        else:
            return jsonify({'error': f'Unsupported file type: .{ext}'}), 400
    
    except Exception as e:
        logger.error(f"Text extraction error: {e}", exc_info=True)
        return jsonify({'error': f'Failed to extract text: {str(e)}'}), 500


# ─────────────────────────────────────────────────────────
# PRODUCT CACHE & MATCHING
# ─────────────────────────────────────────────────────────

def get_cached_products(user_id, force_refresh=False):
    """Get products from cache, refreshing from Xero/QB if stale or forced.
    
    Returns list of product dicts ready for matching.
    """
    cache_cutoff = datetime.utcnow() - timedelta(hours=PRODUCT_CACHE_TTL_HOURS)
    
    # Check if cache is fresh
    if not force_refresh:
        latest = ProductCache.query.filter_by(user_id=user_id).order_by(
            ProductCache.synced_at.desc()
        ).first()
        
        if latest and latest.synced_at and latest.synced_at > cache_cutoff:
            # Cache is fresh — return from DB
            cached = ProductCache.query.filter_by(user_id=user_id).all()
            return [p.to_dict() for p in cached]
    
    # Cache is stale or forced — refresh from accounting system
    try:
        from app.services.product_matcher import fetch_user_products
        from flask_login import current_user
        fresh_products = fetch_user_products(current_user)
        
        if fresh_products:
            # Clear old cache
            ProductCache.query.filter_by(user_id=user_id).delete()
            
            # Insert new cache
            now = datetime.utcnow()
            for p in fresh_products:
                cache_entry = ProductCache(
                    user_id=user_id,
                    product_id=p.get('id', ''),
                    code=p.get('code', ''),
                    name=p.get('name', ''),
                    description=p.get('description', ''),
                    purchase_description=p.get('purchase_description', ''),
                    purchase_price=p.get('purchase_price', 0),
                    sale_price=p.get('sale_price', 0),
                    source=p.get('source', ''),
                    synced_at=now
                )
                db.session.add(cache_entry)
            
            db.session.commit()
            logger.info(f"Product cache refreshed for user {user_id}: {len(fresh_products)} products")
            return fresh_products
        else:
            # No products from API — return existing cache if any
            cached = ProductCache.query.filter_by(user_id=user_id).all()
            return [p.to_dict() for p in cached]
    
    except ImportError:
        logger.warning("Product matcher module not available")
        cached = ProductCache.query.filter_by(user_id=user_id).all()
        return [p.to_dict() for p in cached]
    except Exception as e:
        logger.error(f"Failed to refresh product cache: {e}")
        cached = ProductCache.query.filter_by(user_id=user_id).all()
        return [p.to_dict() for p in cached]


@bp.route('/fetch-products', methods=['GET'])
@login_required
def fetch_products():
    """Fetch user's product list — from cache or fresh from accounting system.
    
    Query params:
        refresh=true — force refresh from Xero/QB
    """
    try:
        force_refresh = request.args.get('refresh', '').lower() == 'true'
        products = get_cached_products(current_user.id, force_refresh=force_refresh)
        
        # Get cache age
        latest = ProductCache.query.filter_by(user_id=current_user.id).order_by(
            ProductCache.synced_at.desc()
        ).first()
        cache_age = None
        if latest and latest.synced_at:
            cache_age = (datetime.utcnow() - latest.synced_at).total_seconds()
        
        return jsonify({
            'success': True,
            'products': products,
            'count': len(products),
            'cached': not force_refresh and cache_age is not None,
            'cache_age_seconds': int(cache_age) if cache_age else None,
            'cache_age_human': format_cache_age(cache_age) if cache_age else None
        })
    except Exception as e:
        logger.error(f"Fetch products error: {e}", exc_info=True)
        return jsonify({'error': str(e)}), 500


@bp.route('/search-products', methods=['GET'])
@login_required
def search_products():
    """Search cached products by code or description — for live search in match review.
    
    Query params:
        q=search term (min 2 chars)
        limit=10 (max results)
    """
    try:
        query = request.args.get('q', '').strip()
        limit = min(int(request.args.get('limit', 10)), 50)
        
        if len(query) < 2:
            return jsonify({'results': []})
        
        search_term = f"%{query}%"
        
        results = ProductCache.query.filter(
            ProductCache.user_id == current_user.id,
            db.or_(
                ProductCache.code.ilike(search_term),
                ProductCache.name.ilike(search_term),
                ProductCache.description.ilike(search_term),
                ProductCache.purchase_description.ilike(search_term)
            )
        ).limit(limit).all()
        
        return jsonify({
            'results': [p.to_dict() for p in results]
        })
    except Exception as e:
        logger.error(f"Search products error: {e}", exc_info=True)
        return jsonify({'results': []})


@bp.route('/sync-products', methods=['POST'])
@login_required
def sync_products():
    """Force refresh the product cache from Xero/QB"""
    try:
        products = get_cached_products(current_user.id, force_refresh=True)
        return jsonify({
            'success': True,
            'count': len(products),
            'message': f'Synced {len(products)} products from your accounting system'
        })
    except Exception as e:
        logger.error(f"Sync products error: {e}", exc_info=True)
        return jsonify({'error': str(e)}), 500


def format_cache_age(seconds):
    """Format cache age in human-readable form"""
    if not seconds:
        return 'just now'
    if seconds < 60:
        return 'just now'
    if seconds < 3600:
        mins = int(seconds / 60)
        return f'{mins}m ago'
    if seconds < 86400:
        hours = int(seconds / 3600)
        return f'{hours}h ago'
    days = int(seconds / 86400)
    return f'{days}d ago'


@bp.route('/match-products', methods=['POST'])
@login_required
def match_products():
    """Match parsed combined_materials against user's cached product list.
    
    Expects: {combined_materials: [...]}
    Returns: {results: [{material, matches, status, selected, clean_description}], products: [...cached]}
    """
    try:
        data = request.get_json() or {}
        combined_materials = data.get('combined_materials', [])
        
        if not combined_materials:
            return jsonify({'error': 'No materials to match'}), 400
        
        # Always use cached products
        products = get_cached_products(current_user.id)
        
        if not products:
            # No products available — return all as unmatched + empty product list
            results = []
            for i, item in enumerate(combined_materials):
                results.append({
                    'index': i,
                    'material': item,
                    'matches': [],
                    'status': 'unmatched',
                    'selected': None,
                    'clean_description': None
                })
            return jsonify({
                'success': True,
                'results': results,
                'products': [],
                'no_products': True,
                'message': 'No accounting system connected — connect Xero or QuickBooks to enable product matching'
            })
        
        # Run fuzzy matching
        from app.services.product_matcher import match_all_materials, ai_match_unresolved, generate_clean_descriptions
        
        match_results = match_all_materials(combined_materials, products)
        
        # Collect unmatched items for AI assistance
        unmatched = []
        for i, result in enumerate(match_results):
            result['index'] = i
            if result['status'] == 'unmatched':
                unmatched.append({'index': i, 'material': result['material']})
        
        # AI-assisted matching for unresolved items
        if unmatched:
            api_key = os.getenv('ANTHROPIC_API_KEY')
            if api_key:
                ai_results = ai_match_unresolved(unmatched, products, api_key)
                for idx, ai_match in ai_results.items():
                    if idx < len(match_results):
                        match_results[idx]['matches'].insert(0, ai_match)
                        match_results[idx]['status'] = 'review'
                        match_results[idx]['selected'] = ai_match
        
        # Generate clean customer descriptions for matched items
        api_key = os.getenv('ANTHROPIC_API_KEY')
        if api_key:
            clean_descs = generate_clean_descriptions(match_results, api_key)
            for idx, desc in clean_descs.items():
                if idx < len(match_results):
                    match_results[idx]['clean_description'] = desc
        
        # Summary stats
        stats = {
            'total': len(match_results),
            'matched': sum(1 for r in match_results if r['status'] == 'matched'),
            'review': sum(1 for r in match_results if r['status'] == 'review'),
            'unmatched': sum(1 for r in match_results if r['status'] == 'unmatched'),
        }
        
        return jsonify({
            'success': True,
            'results': match_results,
            'products': products,  # Send full product list to frontend for live search
            'stats': stats,
            'product_count': len(products)
        })
    
    except Exception as e:
        logger.error(f"Product matching error: {e}", exc_info=True)
        return jsonify({'error': f'Matching failed: {str(e)}'}), 500


@bp.route('/confirm-matches', methods=['POST'])
@login_required
def confirm_matches():
    """Confirm product matches and prepare for Quote Builder.
    
    Expects: {matches: [{material_index, product_id, product_code, sale_price, clean_description, quantity}]}
    Returns: {quote_items: [...ready for quote builder]}
    """
    try:
        data = request.get_json() or {}
        confirmed = data.get('matches', [])
        
        if not confirmed:
            return jsonify({'error': 'No matches to confirm'}), 400
        
        quote_items = []
        for match in confirmed:
            quote_items.append({
                'product_code': match.get('product_code', ''),
                'description': match.get('clean_description') or match.get('description', ''),
                'supplier_description': match.get('supplier_description', ''),
                'quantity': match.get('quantity', 0),
                'unit_price': match.get('sale_price', 0),
                'total': round(match.get('quantity', 0) * match.get('sale_price', 0), 2),
                'product_id': match.get('product_id', ''),
                'source': match.get('source', 'voice_to_quote')
            })
        
        total_value = sum(item['total'] for item in quote_items)
        
        return jsonify({
            'success': True,
            'quote_items': quote_items,
            'item_count': len(quote_items),
            'total_value': round(total_value, 2)
        })
    
    except Exception as e:
        logger.error(f"Confirm matches error: {e}", exc_info=True)
        return jsonify({'error': str(e)}), 500
