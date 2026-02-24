"""Voice-to-Quote: Parse Plaud transcriptions into structured materials lists"""
from flask import Blueprint, request, jsonify, render_template, current_app, redirect
from flask_login import login_required, current_user
from app.extensions import db
from app.models.user_preference import UserPreference, CorrectionLog, ProductCache
from app.models.vtq_models import VTQJob, VTQTranscription
from datetime import datetime, timedelta
import anthropic
import json
import os
import logging

logger = logging.getLogger(__name__)

def repair_json(text):
    """Fix common JSON issues from Claude responses"""
    import re
    # Remove JavaScript-style comments (// ... and /* ... */)
    text = re.sub(r'//[^\n]*', '', text)
    text = re.sub(r'/\*.*?\*/', '', text, flags=re.DOTALL)
    # Remove trailing commas before } or ]
    text = re.sub(r',\s*([}\]])', r'\1', text)
    # Remove any BOM or zero-width chars
    text = text.replace('\ufeff', '').replace('\u200b', '')
    # Remove ellipsis or "..." entries that Claude sometimes adds
    text = re.sub(r'"\.\.\."[^,}\]]*[,]?', '', text)
    text = re.sub(r'\.\.\.[^,}\]]*[,]?', '', text)
    # Fix single quotes to double quotes only if no double quotes in keys
    if "'" in text and '"' not in text[:100]:
        text = text.replace("'", '"')
    # Clean up any double commas or empty entries left behind
    text = re.sub(r',\s*,', ',', text)
    text = re.sub(r'\[\s*,', '[', text)
    text = re.sub(r',\s*\]', ']', text)
    return text





def apply_product_swaps(parsed_data, user_id):
    """Post-process parsed results to apply saved product swaps.
    Matches on material description since AI part numbers are inconsistent."""
    swaps = UserPreference.query.filter_by(
        user_id=user_id,
        category='product_swap',
        active=True
    ).all()
    
    if not swaps:
        return parsed_data
    
    swap_map = {}
    for s in swaps:
        swap_map[s.key.lower()] = s.value
        swap_map[s.key.lower().replace('_', ' ')] = s.value
        swap_map[s.key.lower().replace(' ', '_')] = s.value
    
    def check_swap(item):
        pn = (item.get('part_number') or '').lower()
        if pn in swap_map:
            item['part_number'] = swap_map[pn]
            item['swap_applied'] = True
            return
        desc = (item.get('description') or '').lower()
        if desc in swap_map:
            item['part_number'] = swap_map[desc]
            item['swap_applied'] = True
            return
        for key, new_pn in swap_map.items():
            if len(key) > 3 and key in desc:
                item['part_number'] = new_pn
                item['swap_applied'] = True
                return
    
    for room in parsed_data.get('rooms', []):
        for acc in room.get('accessories', []):
            check_swap(acc)
    for mat in parsed_data.get('combined_materials', []):
        check_swap(mat)
    
    logger.info(f'Applied product swaps: {len(swap_map)} rules checked')
    return parsed_data

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
    """Pull user's product list from Xero/QuickBooks for the system prompt.
    Uses the cached product list if available.
    """
    try:
        cached = ProductCache.query.filter_by(user_id=user_id).limit(200).all()
        if cached:
            return [{'code': p.code, 'name': p.name, 'sale_price': p.sale_price} for p in cached]
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
    """Voice-to-quote main page — shows jobs list"""
    if not current_user.is_admin and current_user.subscription_plan not in ['ultimate', 'trial']:
        return redirect('/billing?upgrade=ultimate')
    return render_template('voice_to_quote/index.html')


@bp.route('/teach')
@login_required
def teach_ai():
    """Teach AI page — chat interface for managing preferences"""
    return render_template('voice_to_quote/teach_ai.html')


# ─────────────────────────────────────────────────────────
# JOBS — CRUD for quoting jobs
# ─────────────────────────────────────────────────────────

@bp.route('/jobs', methods=['GET'])
@login_required
def list_jobs():
    """List all jobs for the current user, optionally filtered by status"""
    status = request.args.get('status')
    query = VTQJob.query.filter_by(user_id=current_user.id)
    
    if status:
        query = query.filter_by(status=status)
    
    # Active jobs first (draft, parsed, matched), then by updated_at desc
    jobs = query.order_by(
        db.case(
            (VTQJob.status == 'draft', 1),
            (VTQJob.status == 'parsed', 2),
            (VTQJob.status == 'matched', 3),
            (VTQJob.status == 'quoted', 4),
            else_=5
        ),
        VTQJob.updated_at.desc()
    ).all()
    
    return jsonify({
        'success': True,
        'jobs': [j.to_dict(include_transcriptions=True) for j in jobs]
    })


@bp.route('/jobs', methods=['POST'])
@login_required
def create_job():
    """Create a new job"""
    data = request.get_json() or {}
    title = data.get('title', '').strip()
    
    if not title:
        return jsonify({'error': 'Job title is required'}), 400
    
    job = VTQJob(
        user_id=current_user.id,
        title=title,
        client_name=data.get('client_name', '').strip() or None,
        reference=data.get('reference', '').strip() or None,
        accounting_project_id=data.get('accounting_project_id'),
        accounting_project_name=data.get('accounting_project_name'),
        accounting_source=data.get('accounting_source'),
        notes=data.get('notes', '').strip() or None,
        status='draft'
    )
    
    db.session.add(job)
    db.session.commit()
    
    return jsonify({
        'success': True,
        'job': job.to_dict(include_transcriptions=True)
    }), 201


@bp.route('/jobs/<int:job_id>', methods=['GET'])
@login_required
def get_job(job_id):
    """Get a single job with transcriptions and parsed data"""
    job = VTQJob.query.filter_by(id=job_id, user_id=current_user.id).first()
    if not job:
        return jsonify({'error': 'Job not found'}), 404
    
    return jsonify({
        'success': True,
        'job': job.to_dict(include_transcriptions=True, include_parsed=True)
    })


@bp.route('/jobs/<int:job_id>', methods=['PUT'])
@login_required
def update_job(job_id):
    """Update job details"""
    job = VTQJob.query.filter_by(id=job_id, user_id=current_user.id).first()
    if not job:
        return jsonify({'error': 'Job not found'}), 404
    
    data = request.get_json() or {}
    
    if 'title' in data:
        job.title = data['title'].strip()
    if 'client_name' in data:
        job.client_name = data['client_name'].strip() or None
    if 'reference' in data:
        job.reference = data['reference'].strip() or None
    if 'notes' in data:
        job.notes = data['notes'].strip() or None
    if 'status' in data:
        job.status = data['status']
    if 'accounting_project_id' in data:
        job.accounting_project_id = data['accounting_project_id']
        job.accounting_project_name = data.get('accounting_project_name')
        job.accounting_source = data.get('accounting_source')
    
    db.session.commit()
    
    return jsonify({
        'success': True,
        'job': job.to_dict(include_transcriptions=True)
    })


@bp.route('/jobs/<int:job_id>', methods=['DELETE'])
@login_required
def delete_job(job_id):
    """Delete a job and all its transcriptions"""
    job = VTQJob.query.filter_by(id=job_id, user_id=current_user.id).first()
    if not job:
        return jsonify({'error': 'Job not found'}), 404
    
    db.session.delete(job)
    db.session.commit()
    
    return jsonify({'success': True})


# ─────────────────────────────────────────────────────────
# TRANSCRIPTIONS — Add/remove transcriptions within a job
# ─────────────────────────────────────────────────────────

@bp.route('/jobs/<int:job_id>/transcriptions', methods=['POST'])
@login_required
def add_transcription(job_id):
    """Add a transcription to a job"""
    job = VTQJob.query.filter_by(id=job_id, user_id=current_user.id).first()
    if not job:
        return jsonify({'error': 'Job not found'}), 404
    
    data = request.get_json() or {}
    text = data.get('text', '').strip()
    
    if not text or len(text) < 20:
        return jsonify({'error': 'Transcription too short — please provide more detail'}), 400
    
    transcription = VTQTranscription(
        job_id=job.id,
        user_id=current_user.id,
        title=data.get('title', '').strip() or None,
        text=text,
        source_filename=data.get('source_filename')
    )
    
    db.session.add(transcription)
    db.session.commit()
    
    return jsonify({
        'success': True,
        'transcription': transcription.to_dict(),
        'job': job.to_dict(include_transcriptions=True)
    }), 201


@bp.route('/jobs/<int:job_id>/transcriptions/<int:trans_id>', methods=['PUT'])
@login_required
def update_transcription(job_id, trans_id):
    """Update a transcription's text or title"""
    job = VTQJob.query.filter_by(id=job_id, user_id=current_user.id).first()
    if not job:
        return jsonify({'error': 'Job not found'}), 404
    
    trans = VTQTranscription.query.filter_by(id=trans_id, job_id=job.id).first()
    if not trans:
        return jsonify({'error': 'Transcription not found'}), 404
    
    data = request.get_json() or {}
    if 'text' in data:
        trans.text = data['text'].strip()
    if 'title' in data:
        trans.title = data['title'].strip() or None
    
    db.session.commit()
    
    return jsonify({'success': True, 'transcription': trans.to_dict()})


@bp.route('/jobs/<int:job_id>/transcriptions/<int:trans_id>', methods=['DELETE'])
@login_required
def delete_transcription(job_id, trans_id):
    """Delete a single transcription from a job"""
    job = VTQJob.query.filter_by(id=job_id, user_id=current_user.id).first()
    if not job:
        return jsonify({'error': 'Job not found'}), 404
    
    trans = VTQTranscription.query.filter_by(id=trans_id, job_id=job.id).first()
    if not trans:
        return jsonify({'error': 'Transcription not found'}), 404
    
    db.session.delete(trans)
    db.session.commit()
    
    return jsonify({
        'success': True,
        'job': job.to_dict(include_transcriptions=True)
    })


@bp.route('/jobs/<int:job_id>/parse', methods=['POST'])
@login_required
def parse_job(job_id):
    """Parse all unparsed transcriptions in a job (or re-parse all).
    
    Combines all transcription texts and sends to Claude as one parse.
    Saves parsed result to the job.
    """
    job = VTQJob.query.filter_by(id=job_id, user_id=current_user.id).first()
    if not job:
        return jsonify({'error': 'Job not found'}), 404
    
    data = request.get_json() or {}
    parse_all = data.get('parse_all', True)  # Default: parse all transcriptions together
    
    transcriptions = job.transcriptions.all()
    if not transcriptions:
        return jsonify({'error': 'No transcriptions to parse'}), 400
    
    # Combine transcription texts
    if parse_all:
        texts_to_parse = transcriptions
    else:
        texts_to_parse = [t for t in transcriptions if not t.is_parsed]
        if not texts_to_parse:
            return jsonify({'error': 'All transcriptions already parsed'}), 400
    
    # Build sections (one per transcription)
    sections = []
    for t in texts_to_parse:
        label = t.title or f"Recording {t.id}"
        sections.append({'label': label, 'text': t.text})
    
    combined_text = ""
    for s in sections:
        combined_text += f"\n--- {s['label']} ---\n{s['text']}\n"
    
    word_count = len(combined_text.split())
    logger.info(f"Total transcription: {word_count} words across {len(sections)} sections")
    
    # Build prompt and call Claude (reuse existing logic)
    knowledge_base = get_knowledge_base()
    if not knowledge_base:
        return jsonify({'error': 'Knowledge base not found — contact support'}), 500
    
    user_preferences_text = get_user_preferences_formatted(current_user.id)
    user_products = get_user_products(current_user.id)
    
    system_prompt = build_system_prompt(knowledge_base, user_preferences_text, user_products, False)
    
    # Build room data context from floor plan if available
    room_context = ""
    if job.floor_plan_rooms:
        try:
            import json as _json
            fp_data = _json.loads(job.floor_plan_rooms) if isinstance(job.floor_plan_rooms, str) else job.floor_plan_rooms
            rooms = fp_data.get('rooms', []) if isinstance(fp_data, dict) else fp_data
            if rooms:
                room_context = "\n\nFLOOR PLAN DATA (extracted from architectural drawing):\n"
                room_context += "The following room dimensions have been measured from a scaled floor plan.\n"
                room_context += "Use these measurements for cable run calculations and do NOT flag room dimensions as missing for these rooms.\n\n"
                for room in rooms:
                    name = room.get('name', 'Unknown')
                    width = room.get('width_m', '?')
                    length = room.get('length_m', '?')
                    area = room.get('area_sqm', '?')
                    perimeter = room.get('perimeter_m', '?')
                    notes = room.get('notes', '')
                    room_context += f"  - {name}: {width}m x {length}m = {area}m², perimeter {perimeter}m"
                    if notes:
                        room_context += f" ({notes})"
                    room_context += "\n"
                total_area = fp_data.get('total_floor_area_sqm') if isinstance(fp_data, dict) else None
                if total_area:
                    room_context += f"\n  Total floor area: {total_area}m²\n"
                drawing_notes = fp_data.get('drawing_notes') if isinstance(fp_data, dict) else None
                if drawing_notes:
                    room_context += f"  Drawing notes: {drawing_notes}\n"
                
                logger.info(f"Floor plan context added: {len(rooms)} rooms")
        except Exception as e:
            logger.warning(f"Failed to parse floor plan rooms: {e}")
            room_context = ""
    
    api_key = os.getenv('ANTHROPIC_API_KEY')
    if not api_key:
        return jsonify({'error': 'Claude API key not configured'}), 500
    
    CHUNK_WORD_LIMIT = 4000
    
    def call_parse_api(text_chunk, chunk_label=""):
        """Call Claude API to parse a text chunk. Returns parsed dict."""
        user_content = [{
            "type": "text",
            "text": f"""Parse this site visit transcription into a structured materials list:

---
{text_chunk}
---
{room_context}
Return the full structured JSON output with all materials, quantities, cable estimates, and flags.
Use the floor plan room dimensions (if provided above) to calculate accurate cable runs and do not flag room sizes as missing for rooms that have measurements from the floor plan.
Return ONLY valid JSON — no markdown, no backticks, no explanation before or after."""
        }]
        
        client = anthropic.Anthropic(api_key=api_key)
        message = client.messages.create(
            model="claude-sonnet-4-5-20250929",
            max_tokens=16000,
            temperature=0,
            system=system_prompt,
            messages=[{"role": "user", "content": user_content}]
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
        
        repaired = repair_json(response_text)
        try:
            return json.loads(repaired)
        except json.JSONDecodeError as je:
            pos = je.pos or 0
            snippet = repaired[max(0, pos-100):pos+100]
            logger.error(f"JSON error in chunk '{chunk_label}' at pos {pos}: {je.msg}")
            logger.error(f"Context: ...{snippet}...")
            raise
    
    def merge_parsed_results(results):
        """Merge multiple parsed results into one unified result."""
        merged = {
            'rooms': [],
            'combined_materials': [],
            'cable_estimates': [],
            'flags': [],
            'summary': {}
        }
        
        seen_rooms = set()
        
        for result in results:
            # Merge rooms
            for room in result.get('rooms', []):
                room_name = room.get('name', room.get('room', ''))
                if room_name and room_name not in seen_rooms:
                    seen_rooms.add(room_name)
                    merged['rooms'].append(room)
                elif room_name in seen_rooms:
                    # Room already exists — merge materials into existing room
                    for existing in merged['rooms']:
                        if existing.get('name', existing.get('room', '')) == room_name:
                            existing_materials = existing.get('materials', existing.get('items', []))
                            new_materials = room.get('materials', room.get('items', []))
                            existing_materials.extend(new_materials)
                            break
            
            # Merge combined materials
            merged['combined_materials'].extend(result.get('combined_materials', result.get('materials', [])))
            
            # Merge cable estimates
            merged['cable_estimates'].extend(result.get('cable_estimates', []))
            
            # Merge flags
            merged['flags'].extend(result.get('flags', []))
        
        # Deduplicate flags
        seen_flags = set()
        unique_flags = []
        for flag in merged['flags']:
            flag_text = flag.get('message', flag.get('text', str(flag)))
            if flag_text not in seen_flags:
                seen_flags.add(flag_text)
                unique_flags.append(flag)
        merged['flags'] = unique_flags
        
        # Copy any other top-level keys from the first result
        if results:
            for key in results[0]:
                if key not in merged:
                    merged[key] = results[0][key]
        
        return merged
    
    try:
        if word_count <= CHUNK_WORD_LIMIT:
            # Single call — existing behaviour
            logger.info(f"Single parse call ({word_count} words)")
            parsed_data = call_parse_api(combined_text)
        else:
            # Chunked parsing — split by sections and group into chunks
            logger.info(f"Chunked parsing: {word_count} words exceeds {CHUNK_WORD_LIMIT} limit")
            
            chunks = []
            current_chunk = ""
            current_words = 0
            
            for s in sections:
                section_text = f"\n--- {s['label']} ---\n{s['text']}\n"
                section_words = len(section_text.split())
                
                if current_words + section_words > CHUNK_WORD_LIMIT and current_chunk:
                    # Save current chunk and start new one
                    chunks.append(current_chunk)
                    current_chunk = section_text
                    current_words = section_words
                else:
                    current_chunk += section_text
                    current_words += section_words
            
            if current_chunk:
                chunks.append(current_chunk)
            
            # If a single section exceeds the limit, it goes as one chunk anyway
            # (Claude can handle it, just might be slower)
            
            logger.info(f"Split into {len(chunks)} chunks")
            
            results = []
            for i, chunk in enumerate(chunks):
                chunk_words = len(chunk.split())
                logger.info(f"Parsing chunk {i+1}/{len(chunks)} ({chunk_words} words)...")
                result = call_parse_api(chunk, f"chunk_{i+1}")
                results.append(result)
                logger.info(f"Chunk {i+1} parsed successfully")
            
            parsed_data = merge_parsed_results(results)
            logger.info(f"Merged {len(results)} chunks into final result")
        
        # Apply saved product swaps (post-processing)
        parsed_data = apply_product_swaps(parsed_data, current_user.id)
        
        # Save to job
        job.set_parsed_data(parsed_data)
        job.parsed_at = datetime.utcnow()
        job.status = 'parsed'
        
        # Mark transcriptions as parsed
        now = datetime.utcnow()
        for t in texts_to_parse:
            t.is_parsed = True
            t.parsed_at = now
        
        db.session.commit()
        
        return jsonify({
            'success': True,
            'data': parsed_data,
            'job': job.to_dict(include_transcriptions=True),
        })
    
    except json.JSONDecodeError as e:
        logger.error(f"Failed to parse Claude response as JSON: {e}")
        return jsonify({'error': 'AI returned invalid format — please try again'}), 500
    except anthropic.APIError as e:
        logger.error(f"Claude API error: {e}")
        return jsonify({'error': f'AI service error: {str(e)}'}), 500
    except Exception as e:
        logger.error(f"Parse job error: {e}", exc_info=True)
        return jsonify({'error': f'Unexpected error: {str(e)}'}), 500


@bp.route('/jobs/<int:job_id>/save-parsed', methods=['POST'])
@login_required
def save_parsed_data(job_id):
    """Save edited parsed data back to the job (after inline edits)"""
    job = VTQJob.query.filter_by(id=job_id, user_id=current_user.id).first()
    if not job:
        return jsonify({'error': 'Job not found'}), 404
    
    data = request.get_json() or {}
    parsed = data.get('parsed_data')
    if parsed:
        job.set_parsed_data(parsed)
        db.session.commit()
    
    return jsonify({'success': True})


@bp.route('/jobs/<int:job_id>/save-matches', methods=['POST'])
@login_required
def save_match_data(job_id):
    """Save product match results to the job"""
    job = VTQJob.query.filter_by(id=job_id, user_id=current_user.id).first()
    if not job:
        return jsonify({'error': 'Job not found'}), 404
    
    data = request.get_json() or {}
    matches = data.get('match_data')
    if matches:
        job.set_match_data(matches)
        job.matched_at = datetime.utcnow()
        job.status = 'matched'
        db.session.commit()
    
    return jsonify({'success': True})


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
            model="claude-sonnet-4-5-20250929",
            max_tokens=16000,
            temperature=0,
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
            parsed_data = json.loads(repair_json(response_text))
        except json.JSONDecodeError as e:
            logger.error(f"Failed to parse Claude response as JSON: {e}")
            logger.error(f"Response was: {response_text[:500]}")
            return jsonify({
                'error': 'AI returned invalid format — please try again',
                'raw_response': response_text[:1000]
            }), 500
        
        # Apply saved product swaps (post-processing)
        parsed_data = apply_product_swaps(parsed_data, current_user.id)
        
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
            model="claude-sonnet-4-5-20250929",
            max_tokens=1500,
            temperature=0.3,
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
    
    Expects: {matches: [{product_code, sale_price, clean_description, quantity, ...}]}
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


@bp.route('/send-to-quote-builder', methods=['POST'])
@login_required
def send_to_quote_builder():
    """Create a Quote Builder project from matched VTQ materials.
    
    Expects: {
        job_title: str,
        client_name: str (optional),
        matches: [{product_code, product_id, description, clean_description, 
                   supplier_description, quantity, sale_price, purchase_price}]
    }
    Returns: {success, project_id, project_url}
    """
    from app.models.project import Project, ProjectMaterial
    
    try:
        data = request.get_json() or {}
        matches = data.get('matches', [])
        
        if not matches:
            return jsonify({'error': 'No materials to send'}), 400
        
        # Create the project
        project = Project(
            user_id=current_user.id,
            name=data.get('job_title', 'Voice to Quote Project'),
            client_name=data.get('client_name') or None,
            site_address=data.get('site_address') or None,
            building_type=data.get('building_type', 'renovation'),
            materials_markup_percent=data.get('markup_percent', 25.0),
            labour_rate_per_hour=data.get('labour_rate', 45.0),
            contingency_percent=data.get('contingency_percent', 10.0),
        )
        db.session.add(project)
        db.session.flush()  # Get the project ID
        
        markup = float(project.materials_markup_percent)
        # Add each matched material
        for match in matches:
            purchase_price = float(match.get('purchase_price', 0) or 0)
            sale_price = float(match.get('sale_price', 0) or 0)
            
            # Use purchase price as unit_cost if available, otherwise back-calculate from sale price
            unit_cost = purchase_price if purchase_price > 0 else sale_price
            
            material = ProjectMaterial(
                project_id=project.id,
                manually_added=False,
                category=match.get('room_name') or match.get('category', 'Accessories'),
                part_number=match.get('product_code', '') or match.get('part_number', ''),
                description=match.get('clean_description') or match.get('description', ''),
                manufacturer=match.get('manufacturer', ''),
                quantity=float(match.get('quantity', 1) or 1),
                unit=match.get('unit', 'each'),
                unit_cost=unit_cost,
                price_source='quickbooks' if match.get('product_id') else 'voice_to_quote',
                price_verified=bool(match.get('product_id')),
                qb_item_id=str(match.get('product_id', '')) or None,
                qb_item_name=match.get('product_code', ''),
                notes=match.get('supplier_description', ''),
            )
            
            material.calculate_totals(markup_percent=markup)
            
            # Override with QB sales price if available (higher than markup calculation)
            if sale_price > 0 and sale_price > float(material.unit_sell or 0):
                material.unit_sell = round(sale_price, 4)
                material.total_sell = round(float(material.quantity or 0) * sale_price, 2)
                # Back-calculate the actual markup
                if purchase_price > 0:
                    material.markup_percent = round(((sale_price - purchase_price) / purchase_price) * 100, 2)
            
            db.session.add(material)
        
        # Recalculate project totals
        project.recalculate_totals()
        db.session.commit()
        
        logger.info(f"Created Quote Builder project '{project.name}' (ID: {project.id}) with {len(matches)} materials for user {current_user.id}")
        
        return jsonify({
            'success': True,
            'project_id': project.id,
            'project_uuid': project.uuid,
            'project_url': f'/quotebuilder/project/{project.id}',
            'item_count': len(matches),
            'total_materials_cost': float(project.total_materials_cost or 0),
            'total_materials_sell': float(project.total_materials_sell or 0),
        })
    
    except Exception as e:
        db.session.rollback()
        logger.error(f"Send to Quote Builder error: {e}", exc_info=True)
        return jsonify({'error': str(e)}), 500


# ─────────────────────────────────────────────────────────
# QB CUSTOMERS — Search & Link
# ─────────────────────────────────────────────────────────

@bp.route('/search-customers', methods=['GET'])
@login_required
def search_customers():
    """Search QuickBooks customers by name.
    
    ?q=smith&limit=15
    Returns: {customers: [{id, name, company, email, phone, balance}]}
    """
    from app.models.quickbooks import QuickBooksConnection
    from app.integrations.quickbooks_service import QuickBooksService
    
    query = request.args.get('q', '').strip()
    if len(query) < 2:
        return jsonify({'customers': [], 'error': 'Search term too short'})
    
    try:
        qb_connection = QuickBooksConnection.query.filter_by(
            user_id=current_user.id, is_active=True
        ).first()
        if not qb_connection:
            return jsonify({'customers': [], 'error': 'No QuickBooks connection'})
        
        qb = QuickBooksService(current_user)
        results = qb.search_customers(qb_connection, query)
        
        customers = []
        for c in results:
            customers.append({
                'id': c.get('Id'),
                'name': c.get('DisplayName', ''),
                'company': c.get('CompanyName', ''),
                'email': c.get('PrimaryEmailAddr', {}).get('Address', '') if c.get('PrimaryEmailAddr') else '',
                'phone': c.get('PrimaryPhone', {}).get('FreeFormNumber', '') if c.get('PrimaryPhone') else '',
                'balance': float(c.get('Balance', 0)),
            })
        
        return jsonify({'customers': customers, 'count': len(customers)})
    
    except Exception as e:
        logger.error(f"Customer search error: {e}", exc_info=True)
        return jsonify({'customers': [], 'error': str(e)})


@bp.route('/link-customer', methods=['POST'])
@login_required
def link_customer():
    """Link a QuickBooks customer to a Quote Builder project.
    
    Expects: {project_id: int, customer_id: str, customer_name: str}
    """
    from app.models.project import Project
    
    try:
        data = request.get_json() or {}
        project_id = data.get('project_id')
        customer_id = data.get('customer_id')
        customer_name = data.get('customer_name')
        
        if not project_id or not customer_id:
            return jsonify({'error': 'Project and customer are required'}), 400
        
        project = Project.query.filter_by(id=project_id, user_id=current_user.id).first()
        if not project:
            return jsonify({'error': 'Project not found'}), 404
        
        project.qb_customer_id = str(customer_id)
        project.qb_customer_name = customer_name
        db.session.commit()
        
        logger.info(f"Linked customer '{customer_name}' (ID: {customer_id}) to project {project_id}")
        
        return jsonify({
            'success': True,
            'project_id': project.id,
            'qb_customer_id': project.qb_customer_id,
            'qb_customer_name': project.qb_customer_name,
        })
    
    except Exception as e:
        logger.error(f"Link customer error: {e}", exc_info=True)
        return jsonify({'error': str(e)}), 500


@bp.route('/push-estimate', methods=['POST'])
@login_required
def push_estimate():
    """Push a Quote Builder project to QuickBooks as an Estimate.
    
    Expects: {project_id: int, memo: str (optional), expiry_days: int (optional)}
    Returns: {success, estimate_id, estimate_number}
    """
    from app.models.project import Project, ProjectMaterial
    from app.models.quickbooks import QuickBooksConnection
    from app.integrations.quickbooks_service import QuickBooksService
    
    try:
        data = request.get_json() or {}
        project_id = data.get('project_id')
        
        if not project_id:
            return jsonify({'error': 'Project ID is required'}), 400
        
        project = Project.query.filter_by(id=project_id, user_id=current_user.id).first()
        if not project:
            return jsonify({'error': 'Project not found'}), 404
        
        if not project.qb_customer_id:
            return jsonify({'error': 'Link a customer first before pushing to QuickBooks'}), 400
        
        qb_connection = QuickBooksConnection.query.filter_by(
            user_id=current_user.id, is_active=True
        ).first()
        if not qb_connection:
            return jsonify({'error': 'No QuickBooks connection'}), 400
        
        qb = QuickBooksService(current_user)
        
        # Get all project materials
        materials = ProjectMaterial.query.filter_by(project_id=project.id).all()
        if not materials:
            return jsonify({'error': 'No materials in project'}), 400
        
        # Build line items for QB Estimate, grouped by room/category
        line_items = []
        items_without_qb = []
        
        # Group materials by category (room name from VTQ)
        materials_by_cat = {}
        for mat in materials:
            cat = mat.category or 'General'
            if cat not in materials_by_cat:
                materials_by_cat[cat] = []
            materials_by_cat[cat].append(mat)
        
        # Only add room headers if there are 2+ categories
        show_room_headers = len(materials_by_cat) > 1
        
        for cat, cat_materials in materials_by_cat.items():
            # Insert room header as description-only line
            if show_room_headers:
                line_items.append({
                    'description_only': True,
                    'description': f'── {cat} ──',
                })
            
            for mat in cat_materials:
                if mat.qb_item_id:
                    line_items.append({
                        'item_id': mat.qb_item_id,
                        'quantity': float(mat.quantity),
                        'unit_price': float(mat.unit_sell or mat.unit_cost or 0),
                        'description': mat.description or mat.part_number or '',
                    })
                else:
                    # Try to find by SKU in QuickBooks
                    found = qb.find_item_by_sku(qb_connection, mat.part_number) if mat.part_number else None
                    if found:
                        mat.qb_item_id = str(found['Id'])
                        mat.qb_item_name = found.get('Name', '')
                        line_items.append({
                            'item_id': str(found['Id']),
                            'quantity': float(mat.quantity),
                            'unit_price': float(mat.unit_sell or mat.unit_cost or 0),
                            'description': mat.description or mat.part_number or '',
                        })
                    else:
                        items_without_qb.append(mat.part_number or mat.description)
        
        # Check we have actual product lines (not just description headers)
        product_lines = [li for li in line_items if not li.get('description_only')]
        if not product_lines:
            return jsonify({
                'error': 'No materials could be matched to QuickBooks items',
                'missing_items': items_without_qb
            }), 400
        
        # Add contingency line if project has contingency > 0
        contingency_pct = float(project.contingency_percent or 0)
        if contingency_pct > 0:
            materials_total = sum(item.get('unit_price', 0) * item.get('quantity', 0) for item in line_items if not item.get('description_only'))
            contingency_amount = round(materials_total * contingency_pct / 100, 2)
            
            # Find or note contingency item in QB
            contingency_item = qb.find_item_by_name(qb_connection, 'Contingency')
            if not contingency_item:
                contingency_item = qb.find_item_by_sku(qb_connection, 'CONTINGENCY')
            
            if contingency_item:
                line_items.append({
                    'item_id': str(contingency_item['Id']),
                    'quantity': 1,
                    'unit_price': contingency_amount,
                    'description': f'Contingency ({contingency_pct:.0f}%)',
                })
            else:
                logger.warning('No Contingency item found in QB - skipping contingency line')
        
        expiry_days = data.get('expiry_days', 30)
        
        result = qb.create_estimate(
            qb_connection, 
            project.qb_customer_id, 
            line_items,
            expiry_days=expiry_days
        )
        
        if result and 'Estimate' in result:
            estimate = result['Estimate']
            estimate_id = estimate.get('Id')
            estimate_number = estimate.get('DocNumber', '')
            
            # Update project status
            project.status = 'quoted'
            project.quoted_at = datetime.utcnow()
            db.session.commit()
            
            logger.info(f"Pushed estimate #{estimate_number} (ID: {estimate_id}) to QB for project {project_id}")
            
            return jsonify({
                'success': True,
                'estimate_id': estimate_id,
                'estimate_number': estimate_number,
                'line_count': len(line_items),
                'skipped_items': items_without_qb,
                'total': float(estimate.get('TotalAmt', 0)),
            })
        else:
            return jsonify({'error': 'QuickBooks did not return an estimate — check your connection'}), 500
    
    except Exception as e:
        logger.error(f"Push estimate error: {e}", exc_info=True)
        return jsonify({'error': str(e)}), 500


@bp.route('/update-prices-only', methods=['POST'])
@login_required
def update_prices_only():
    """Process a queued invoice ONLY to update product prices in QuickBooks — no bill created.
    
    Expects: {queue_id: int} or {invoice_id: int}
    Reads the invoice, extracts line items, updates cost+sale prices in QB for each product.
    """
    from app.models.quickbooks import QuickBooksConnection
    from app.integrations.quickbooks_service import QuickBooksService
    
    try:
        data = request.get_json() or {}
        queue_id = data.get('queue_id')
        invoice_id = data.get('invoice_id')
        
        if not queue_id and not invoice_id:
            return jsonify({'error': 'Provide queue_id or invoice_id'}), 400
        
        qb_connection = QuickBooksConnection.query.filter_by(
            user_id=current_user.id, is_active=True
        ).first()
        if not qb_connection:
            return jsonify({'error': 'No QuickBooks connection'}), 400
        
        qb = QuickBooksService(current_user)
        
        # Get the invoice data — from queue or processed invoices
        line_items = []
        source_name = ''
        
        if queue_id:
            from app.models.queued_invoice import QueuedInvoice
            queued = QueuedInvoice.query.filter_by(id=queue_id, user_id=current_user.id).first()
            if not queued:
                return jsonify({'error': 'Queued invoice not found'}), 404
            
            # Parse the PDF to get line items
            from app.services.invoice_processor import process_invoice_file
            parsed = process_invoice_file(queued.file_path)
            if parsed and parsed.get('line_items'):
                line_items = parsed['line_items']
                source_name = queued.original_filename
            else:
                return jsonify({'error': 'Could not parse invoice line items'}), 400
        
        elif invoice_id:
            from app.models.invoice import Invoice, InvoiceLineItem
            invoice = Invoice.query.filter_by(id=invoice_id, user_id=current_user.id).first()
            if not invoice:
                return jsonify({'error': 'Invoice not found'}), 404
            
            for item in invoice.line_items:
                line_items.append({
                    'sku': item.part_number or item.sku or '',
                    'description': item.description or '',
                    'unit_price': float(item.unit_price or 0),
                    'quantity': float(item.quantity or 0),
                })
            source_name = invoice.filename or f'Invoice #{invoice.id}'
        
        if not line_items:
            return jsonify({'error': 'No line items found in invoice'}), 400
        
        # Update prices in QuickBooks
        updated = 0
        skipped = 0
        errors = []
        
        for item in line_items:
            sku = item.get('sku') or item.get('part_number') or item.get('code', '')
            if not sku:
                skipped += 1
                continue
            
            unit_price = float(item.get('unit_price', 0) or 0)
            if unit_price <= 0:
                skipped += 1
                continue
            
            try:
                # Find item in QB
                found = qb.find_item_by_sku(qb_connection, sku)
                if not found:
                    found = qb.find_item_by_name(qb_connection, sku)
                
                if found:
                    # Calculate sale price with user's markup
                    markup = data.get('markup_percent', 25)
                    sale_price = round(unit_price * (1 + float(markup) / 100), 2)
                    
                    # Update the item
                    update_data = {
                        'Id': found['Id'],
                        'SyncToken': found['SyncToken'],
                        'Name': found['Name'],
                        'PurchaseCost': unit_price,
                        'UnitPrice': sale_price,
                    }
                    
                    result = qb.make_api_request(qb_connection, 'item', method='POST', data=update_data)
                    if result and 'Item' in result:
                        updated += 1
                    else:
                        errors.append(f'{sku}: Update failed')
                else:
                    skipped += 1
                    
            except Exception as e:
                errors.append(f'{sku}: {str(e)}')
        
        # Also update the product cache
        try:
            get_cached_products(current_user.id, force_refresh=True)
        except:
            pass
        
        logger.info(f"Price update from '{source_name}': {updated} updated, {skipped} skipped, {len(errors)} errors")
        
        return jsonify({
            'success': True,
            'updated': updated,
            'skipped': skipped,
            'errors': errors,
            'source': source_name,
        })
    
    except Exception as e:
        logger.error(f"Update prices error: {e}", exc_info=True)
        return jsonify({'error': str(e)}), 500



# ─────────────────────────────────────────────────────────
# LEARNING — Save corrections as user preferences
# ─────────────────────────────────────────────────────────

@bp.route('/save-correction', methods=['POST'])
@login_required
def save_correction():
    """Save a product correction as a user preference so the AI learns.
    
    Stores it as a product_swap preference:
      key = old_code (what AI suggested)
      value = new_code (what user corrected to)
    """
    data = request.get_json() or {}
    old_code = data.get('old_code', '').strip()
    new_code = data.get('new_code', '').strip()
    product_name = data.get('product_name', '').strip()
    material_name = data.get('material_name', '').strip()
    
    if not old_code or not new_code:
        return jsonify({'error': 'Missing old or new code'}), 400
    
    if old_code == new_code:
        return jsonify({'error': 'Codes are the same'}), 400
    
    # Use material_name as key (stable across parses) instead of AI-generated part number
    swap_key = material_name if material_name else old_code
    
    # Check if this correction already exists (by material name OR old code)
    existing = UserPreference.query.filter_by(
        user_id=current_user.id,
        category='product_swap',
        key=swap_key,
        active=True
    ).first()
    
    if not existing and swap_key != old_code:
        existing = UserPreference.query.filter_by(
            user_id=current_user.id,
            category='product_swap',
            key=old_code,
            active=True
        ).first()
    
    if existing:
        existing.value = new_code
        existing.key = swap_key
        existing.description = f"For {material_name or old_code}, always use part number {new_code} ({product_name})"
        logger.info(f"Updated correction: {swap_key} -> {new_code}")
    else:
        pref = UserPreference(
            user_id=current_user.id,
            category='product_swap',
            key=swap_key,
            value=new_code,
            description=f"For {material_name or old_code}, always use part number {new_code} ({product_name})",
            source='manual',
            active=True
        )
        db.session.add(pref)
        logger.info(f"Saved new correction: {swap_key} -> {new_code}")
    
    # Also log the correction for analytics
    try:
        correction = CorrectionLog(
            user_id=current_user.id,
            original_value=old_code,
            corrected_value=new_code,
            field_name='part_number',
            context=material_name
        )
        db.session.add(correction)
    except Exception:
        pass  # CorrectionLog is optional
    
    db.session.commit()
    
    return jsonify({
        'success': True,
        'message': f'Saved: {old_code} → {new_code}'
    })


# ─────────────────────────────────────────────────────────
# FLOOR PLAN — Upload, Scale, AI Room Extraction
# ─────────────────────────────────────────────────────────

@bp.route('/jobs/<int:job_id>/floor-plan', methods=['POST'])
@login_required
def upload_floor_plan(job_id):
    """Upload a floor plan drawing for a VTQ job.
    
    Accepts PDF or image. Stores it and returns the job with floor plan info.
    """
    job = VTQJob.query.filter_by(id=job_id, user_id=current_user.id).first()
    if not job:
        return jsonify({'error': 'Job not found'}), 404
    
    if 'file' not in request.files:
        return jsonify({'error': 'No file uploaded'}), 400
    
    file = request.files['file']
    if not file.filename:
        return jsonify({'error': 'No file selected'}), 400
    
    # Save the file
    import uuid
    ext = os.path.splitext(file.filename)[1].lower()
    if ext not in ['.pdf', '.png', '.jpg', '.jpeg', '.webp']:
        return jsonify({'error': 'Supported formats: PDF, PNG, JPG, WEBP'}), 400
    
    upload_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', '..', 'uploads', 'floor_plans')
    os.makedirs(upload_dir, exist_ok=True)
    
    safe_name = f"fp_{job_id}_{uuid.uuid4().hex[:8]}{ext}"
    save_path = os.path.join(upload_dir, safe_name)
    file.save(save_path)
    
    job.floor_plan_path = save_path
    job.floor_plan_filename = file.filename
    db.session.commit()
    
    logger.info(f"Floor plan uploaded for job {job_id}: {file.filename}")
    
    return jsonify({
        'success': True,
        'filename': file.filename,
        'job': job.to_dict()
    })


@bp.route('/jobs/<int:job_id>/floor-plan', methods=['DELETE'])
@login_required
def delete_floor_plan(job_id):
    """Remove floor plan from a VTQ job."""
    job = VTQJob.query.filter_by(id=job_id, user_id=current_user.id).first()
    if not job:
        return jsonify({'error': 'Job not found'}), 404
    
    if job.floor_plan_path and os.path.exists(job.floor_plan_path):
        os.remove(job.floor_plan_path)
    
    job.floor_plan_path = None
    job.floor_plan_filename = None
    job.floor_plan_scale = None
    job.floor_plan_paper = None
    job.floor_plan_orientation = None
    job.floor_plan_rooms = None
    db.session.commit()
    
    return jsonify({'success': True})


@bp.route('/jobs/<int:job_id>/floor-plan/preview')
@login_required
def preview_floor_plan(job_id):
    """Serve the floor plan file for preview."""
    from flask import send_file
    job = VTQJob.query.filter_by(id=job_id, user_id=current_user.id).first()
    if not job or not job.floor_plan_path or not os.path.exists(job.floor_plan_path):
        return jsonify({'error': 'No floor plan'}), 404
    
    return send_file(job.floor_plan_path, as_attachment=False)


@bp.route('/jobs/<int:job_id>/analyse-floor-plan', methods=['POST'])
@login_required
def analyse_floor_plan(job_id):
    """Set scale and use AI to extract room names + dimensions from the floor plan.
    
    Expects: {scale_ratio: '1:50', paper_size: 'A1', orientation: 'landscape'}
    Returns: {rooms: [{name, width_m, length_m, area_sqm, perimeter_m}]}
    """
    job = VTQJob.query.filter_by(id=job_id, user_id=current_user.id).first()
    if not job:
        return jsonify({'error': 'Job not found'}), 404
    
    if not job.floor_plan_path or not os.path.exists(job.floor_plan_path):
        return jsonify({'error': 'No floor plan uploaded'}), 400
    
    data = request.get_json() or {}
    scale_ratio = data.get('scale_ratio', '1:50')
    paper_size = data.get('paper_size', 'A1')
    orientation = data.get('orientation', 'landscape')
    
    # Save scale settings
    job.floor_plan_scale = scale_ratio
    job.floor_plan_paper = paper_size
    job.floor_plan_orientation = orientation
    
    # Parse scale ratio
    import re
    match = re.match(r'1\s*[:to]\s*(\d+)', scale_ratio, re.IGNORECASE)
    if not match:
        match = re.match(r'^(\d+)$', scale_ratio.strip())
    if not match:
        return jsonify({'error': 'Invalid scale ratio. Use format like 1:50 or just 50'}), 400
    
    ratio = int(match.group(1))
    
    # Paper sizes in mm
    papers = {
        'A0': (1189, 841), 'A1': (841, 594), 'A2': (594, 420),
        'A3': (420, 297), 'A4': (297, 210)
    }
    pw_mm, ph_mm = papers.get(paper_size, (841, 594))
    if orientation == 'portrait':
        pw_mm, ph_mm = ph_mm, pw_mm
    
    # Real-world dimensions of the drawing
    real_width_m = (pw_mm * ratio) / 1000
    real_height_m = (ph_mm * ratio) / 1000
    
    # Read the floor plan image
    import base64
    file_path = job.floor_plan_path
    ext = os.path.splitext(file_path)[1].lower()
    
    try:
        if ext == '.pdf':
            # Convert first page of PDF to image
            import subprocess
            import tempfile
            with tempfile.NamedTemporaryFile(suffix='.png', delete=False) as tmp:
                tmp_path = tmp.name
            
            # Try pdftoppm first, fall back to pdf2image
            try:
                subprocess.run([
                    'pdftoppm', '-png', '-r', '200', '-singlefile',
                    file_path, tmp_path.replace('.png', '')
                ], check=True, capture_output=True)
            except (FileNotFoundError, subprocess.CalledProcessError):
                from pdf2image import convert_from_path
                images = convert_from_path(file_path, first_page=1, last_page=1, dpi=200)
                images[0].save(tmp_path, 'PNG')
            
            with open(tmp_path, 'rb') as f:
                image_bytes = f.read()
            os.unlink(tmp_path)
            media_type = 'image/png'
        else:
            with open(file_path, 'rb') as f:
                image_bytes = f.read()
            media_type = f'image/{ext.replace(".", "").replace("jpg", "jpeg")}'
        
        image_b64 = base64.standard_b64encode(image_bytes).decode('utf-8')
        
    except Exception as e:
        logger.error(f"Failed to read floor plan: {e}")
        return jsonify({'error': f'Failed to read floor plan: {str(e)}'}), 500
    
    # Call Claude to analyse the floor plan
    try:
        client = anthropic.Anthropic()
        
        prompt = f"""Analyse this architectural floor plan drawing. The drawing is at scale {scale_ratio} on {paper_size} paper ({orientation}).
The full drawing represents approximately {real_width_m:.1f}m wide × {real_height_m:.1f}m tall in real-world dimensions.

Extract ALL rooms visible on the floor plan. For each room:
1. The room name/label as written on the drawing (e.g. "Kitchen", "Bedroom 1", "En-Suite", "Utility", "Lounge", "Hall", "WC")
2. Estimate the room dimensions in metres based on the scale — look for dimension lines or estimate from the room proportions relative to the overall drawing size
3. Calculate the area in square metres
4. Calculate the perimeter in metres

Return ONLY valid JSON, no markdown:
{{
    "rooms": [
        {{
            "name": "Kitchen",
            "width_m": 4.2,
            "length_m": 3.8,
            "area_sqm": 15.96,
            "perimeter_m": 16.0,
            "notes": "Open plan with dining area"
        }}
    ],
    "total_floor_area_sqm": 120.5,
    "drawing_notes": "Ground floor plan, 3-bed detached house"
}}

IMPORTANT:
- Extract EVERY room, including small ones like WCs, cupboards, hallways, landings
- If dimension lines are shown on the drawing, use those exact measurements
- If no dimension lines, estimate proportionally from the overall drawing size
- Be accurate with measurements — these will be used for cable run calculations
- Include any notes about room features (e.g. "has island unit", "L-shaped", "vaulted ceiling")"""

        response = client.messages.create(
            model="claude-sonnet-4-5-20250929",
            max_tokens=4000,
            temperature=0,
            messages=[{
                "role": "user",
                "content": [
                    {
                        "type": "image",
                        "source": {
                            "type": "base64",
                            "media_type": media_type,
                            "data": image_b64,
                        }
                    },
                    {
                        "type": "text",
                        "text": prompt
                    }
                ]
            }]
        )
        
        response_text = response.content[0].text.strip()
        
        # Clean up JSON
        if response_text.startswith('```'):
            lines = response_text.split('\n')
            response_text = '\n'.join(lines[1:-1])
        
        rooms_data = json.loads(repair_json(response_text))
        
        # Store results
        job.floor_plan_rooms = json.dumps(rooms_data)
        db.session.commit()
        
        logger.info(f"Floor plan analysed for job {job_id}: {len(rooms_data.get('rooms', []))} rooms extracted")
        
        return jsonify({
            'success': True,
            'rooms': rooms_data.get('rooms', []),
            'total_floor_area_sqm': rooms_data.get('total_floor_area_sqm'),
            'drawing_notes': rooms_data.get('drawing_notes'),
            'scale': scale_ratio,
            'paper_size': paper_size,
        })
        
    except json.JSONDecodeError as e:
        logger.error(f"Failed to parse AI room extraction: {e}")
        return jsonify({'error': 'AI could not parse the floor plan properly. Try a clearer image.'}), 500
    except Exception as e:
        logger.error(f"Floor plan analysis error: {e}", exc_info=True)
        return jsonify({'error': str(e)}), 500


@bp.route('/jobs/<int:job_id>/save-floor-plan-rooms', methods=['POST'])
@login_required
def save_floor_plan_rooms(job_id):
    """Save manually marked room data from the Room Marker canvas."""
    job = VTQJob.query.filter_by(id=job_id, user_id=current_user.id).first()
    if not job:
        return jsonify({'error': 'Job not found'}), 404
    
    data = request.get_json() or {}
    levels = data.get('levels', [])
    rooms = data.get('rooms', [])
    total_area = data.get('total_floor_area_sqm', 0)
    
    job.floor_plan_rooms = json.dumps({
        'levels': levels,
        'rooms': rooms,
        'total_floor_area_sqm': total_area,
        'source': 'manual',
    })
    db.session.commit()
    
    logger.info(f"Saved {len(rooms)} rooms across {len(levels)} levels for job {job_id}")
    return jsonify({'success': True, 'room_count': len(rooms), 'level_count': len(levels)})


@bp.route('/jobs/<int:job_id>/floor-plan-image')
@login_required
def floor_plan_image(job_id):
    """Serve the floor plan image for the Room Marker canvas."""
    from flask import send_file
    
    job = VTQJob.query.filter_by(id=job_id, user_id=current_user.id).first()
    if not job or not job.floor_plan_path:
        return '', 404
    
    if not os.path.exists(job.floor_plan_path):
        return jsonify({'error': 'Floor plan file not found'}), 404
    
    import mimetypes
    mime = mimetypes.guess_type(job.floor_plan_path)[0] or 'image/png'
    
    # For PDFs, convert first page to PNG
    if job.floor_plan_path.lower().endswith('.pdf'):
        import subprocess
        import tempfile
        with tempfile.NamedTemporaryFile(suffix='.png', delete=False) as tmp:
            tmp_path = tmp.name
        try:
            subprocess.run([
                'pdftoppm', '-png', '-r', '200', '-singlefile',
                job.floor_plan_path, tmp_path.replace('.png', '')
            ], check=True, capture_output=True)
        except (FileNotFoundError, subprocess.CalledProcessError):
            from pdf2image import convert_from_path
            images = convert_from_path(job.floor_plan_path, first_page=1, last_page=1, dpi=200)
            images[0].save(tmp_path, 'PNG')
        
        return send_file(tmp_path, mimetype='image/png')
    
    return send_file(job.floor_plan_path, mimetype=mime)
