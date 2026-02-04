"""Quote Builder routes - electrical takeoff and estimation from drawings"""
from flask import Blueprint, render_template, jsonify, request, send_file, current_app
from flask_login import login_required, current_user
from werkzeug.utils import secure_filename
from datetime import datetime
import os
import uuid

bp = Blueprint('quotebuilder', __name__, url_prefix='/quotebuilder')


# =============================================================================
# PAGE ROUTES
# =============================================================================

@bp.route('/')
@login_required
def index():
    """Quote Builder main page - list all projects"""
    return render_template('quotebuilder/index.html')


@bp.route('/project/<int:project_id>')
@login_required
def project_detail(project_id):
    """Single project detail page"""
    from app.models.project import Project
    
    project = Project.query.filter_by(id=project_id, user_id=current_user.id).first_or_404()
    return render_template('quotebuilder/project.html', project=project)


@bp.route('/project/new')
@login_required
def new_project():
    """Create new project page"""
    return render_template('quotebuilder/new_project.html')


# =============================================================================
# PROJECT API ROUTES
# =============================================================================

@bp.route('/api/projects')
@login_required
def get_projects():
    """Get all projects for current user"""
    from app.models.project import Project
    
    projects = Project.query.filter_by(user_id=current_user.id)\
        .order_by(Project.updated_at.desc())\
        .all()
    
    # Stats
    total_quoted = sum(float(p.grand_total or 0) for p in projects if p.status in ['quoted', 'sent', 'won'])
    won_value = sum(float(p.grand_total or 0) for p in projects if p.status == 'won')
    
    return jsonify({
        'success': True,
        'projects': [p.to_dict() for p in projects],
        'stats': {
            'total_projects': len(projects),
            'draft': len([p for p in projects if p.status == 'draft']),
            'quoted': len([p for p in projects if p.status in ['quoted', 'sent']]),
            'won': len([p for p in projects if p.status == 'won']),
            'total_quoted_value': total_quoted,
            'won_value': won_value
        }
    })


@bp.route('/api/projects', methods=['POST'])
@login_required
def create_project():
    """Create a new project"""
    from app.models.project import Project
    from app.extensions import db
    
    data = request.get_json()
    
    project = Project(
        user_id=current_user.id,
        name=data.get('name', 'New Project'),
        client_name=data.get('client_name'),
        client_email=data.get('client_email'),
        client_phone=data.get('client_phone'),
        site_address=data.get('site_address'),
        supply_type=data.get('supply_type', 'single_phase'),
        building_type=data.get('building_type', 'renovation'),
        materials_markup_percent=data.get('materials_markup_percent', 25),
        labour_rate_per_hour=data.get('labour_rate_per_hour', 45),
        contingency_percent=data.get('contingency_percent', 10),
    )
    
    db.session.add(project)
    db.session.commit()
    
    return jsonify({
        'success': True,
        'project': project.to_dict()
    })


@bp.route('/api/projects/<int:project_id>')
@login_required
def get_project(project_id):
    """Get single project with all details"""
    from app.models.project import Project, ProjectDocument, ProjectMaterial, ProjectLabour
    
    project = Project.query.filter_by(id=project_id, user_id=current_user.id).first()
    
    if not project:
        return jsonify({'success': False, 'error': 'Project not found'}), 404
    
    documents = ProjectDocument.query.filter_by(project_id=project.id).all()
    materials = ProjectMaterial.query.filter_by(project_id=project.id).order_by(ProjectMaterial.category).all()
    labour = ProjectLabour.query.filter_by(project_id=project.id).all()
    
    # Group materials by category
    materials_by_category = {}
    for m in materials:
        cat = m.category or 'Uncategorised'
        if cat not in materials_by_category:
            materials_by_category[cat] = []
        materials_by_category[cat].append(m.to_dict())
    
    return jsonify({
        'success': True,
        'project': project.to_dict(),
        'documents': [d.to_dict() for d in documents],
        'materials': [m.to_dict() for m in materials],
        'materials_by_category': materials_by_category,
        'labour': [l.to_dict() for l in labour],
    })


@bp.route('/api/projects/<int:project_id>', methods=['PUT'])
@login_required
def update_project(project_id):
    """Update project settings"""
    from app.models.project import Project
    from app.extensions import db
    
    project = Project.query.filter_by(id=project_id, user_id=current_user.id).first()
    
    if not project:
        return jsonify({'success': False, 'error': 'Project not found'}), 404
    
    data = request.get_json()
    
    # Update allowed fields
    for field in ['name', 'client_name', 'client_email', 'client_phone', 'site_address',
                  'supply_type', 'building_type', 'materials_markup_percent',
                  'labour_rate_per_hour', 'contingency_percent', 'status', 'quote_valid_days']:
        if field in data:
            setattr(project, field, data[field])
    
    # Recalculate if markup or contingency changed
    if 'materials_markup_percent' in data or 'contingency_percent' in data:
        # Update all material markups
        from app.models.project import ProjectMaterial
        if 'materials_markup_percent' in data:
            for material in ProjectMaterial.query.filter_by(project_id=project.id).all():
                material.calculate_totals(markup_percent=data['materials_markup_percent'])
        
        project.recalculate_totals()
    
    db.session.commit()
    
    return jsonify({
        'success': True,
        'project': project.to_dict()
    })


@bp.route('/api/projects/<int:project_id>', methods=['DELETE'])
@login_required
def delete_project(project_id):
    """Delete a project"""
    from app.models.project import Project
    from app.extensions import db
    
    project = Project.query.filter_by(id=project_id, user_id=current_user.id).first()
    
    if not project:
        return jsonify({'success': False, 'error': 'Project not found'}), 404
    
    db.session.delete(project)
    db.session.commit()
    
    return jsonify({'success': True})


# =============================================================================
# DOCUMENT UPLOAD & PARSING
# =============================================================================

@bp.route('/api/projects/<int:project_id>/documents', methods=['POST'])
@login_required
def upload_document(project_id):
    """Upload drawings/specs to a project"""
    from app.models.project import Project, ProjectDocument
    from app.extensions import db
    
    project = Project.query.filter_by(id=project_id, user_id=current_user.id).first()
    
    if not project:
        return jsonify({'success': False, 'error': 'Project not found'}), 404
    
    if 'file' not in request.files:
        return jsonify({'success': False, 'error': 'No file provided'}), 400
    
    file = request.files['file']
    
    if file.filename == '':
        return jsonify({'success': False, 'error': 'No file selected'}), 400
    
    # Validate file type
    allowed_extensions = {'pdf', 'png', 'jpg', 'jpeg', 'dwg'}
    ext = file.filename.rsplit('.', 1)[-1].lower() if '.' in file.filename else ''
    
    if ext not in allowed_extensions:
        return jsonify({'success': False, 'error': f'File type .{ext} not allowed'}), 400
    
    # Save file
    filename = f"{uuid.uuid4().hex}_{secure_filename(file.filename)}"
    upload_folder = os.path.join(current_app.root_path, 'uploads', 'projects', str(project_id))
    os.makedirs(upload_folder, exist_ok=True)
    
    file_path = os.path.join(upload_folder, filename)
    file.save(file_path)
    
    # Create document record
    document = ProjectDocument(
        project_id=project.id,
        filename=filename,
        original_filename=file.filename,
        file_path=file_path,
        file_size=os.path.getsize(file_path),
        mime_type=file.content_type,
        document_type=request.form.get('document_type', 'drawing'),
        floor_level=request.form.get('floor_level'),
        system_type=request.form.get('system_type', 'all'),
    )
    
    db.session.add(document)
    db.session.commit()
    
    return jsonify({
        'success': True,
        'document': document.to_dict()
    })


@bp.route('/api/projects/<int:project_id>/documents/<int:doc_id>/parse', methods=['POST'])
@login_required
def parse_document(project_id, doc_id):
    """Parse a drawing using AI to extract materials"""
    from app.models.project import Project, ProjectDocument, ProjectMaterial
    from app.extensions import db
    from app.parsers.drawing_parser import DrawingParser
    
    project = Project.query.filter_by(id=project_id, user_id=current_user.id).first()
    if not project:
        return jsonify({'success': False, 'error': 'Project not found'}), 404
    
    document = ProjectDocument.query.filter_by(id=doc_id, project_id=project_id).first()
    if not document:
        return jsonify({'success': False, 'error': 'Document not found'}), 404
    
    try:
        # Parse the drawing
        parser = DrawingParser()
        result = parser.parse(
            document.file_path,
            document_type=document.document_type,
            system_type=document.system_type,
            floor_level=document.floor_level
        )
        
        if not result.get('success'):
            document.parse_error = result.get('error', 'Unknown parsing error')
            db.session.commit()
            return jsonify({'success': False, 'error': result.get('error')}), 400
        
        # Add extracted materials to project
        materials_added = 0
        for item in result.get('materials', []):
            # Check if similar material already exists
            existing = ProjectMaterial.query.filter_by(
                project_id=project.id,
                part_number=item.get('part_number'),
                category=item.get('category')
            ).first()
            
            if existing:
                # Update quantity
                existing.quantity = float(existing.quantity or 0) + float(item.get('quantity', 0))
                existing.calculate_totals(markup_percent=float(project.materials_markup_percent))
            else:
                # Add new material
                material = ProjectMaterial(
                    project_id=project.id,
                    source_document_id=document.id,
                    category=item.get('category'),
                    part_number=item.get('part_number'),
                    description=item.get('description'),
                    manufacturer=item.get('manufacturer'),
                    quantity=item.get('quantity', 1),
                    unit=item.get('unit', 'each'),
                    unit_cost=item.get('unit_cost'),
                    price_source=item.get('price_source', 'estimated'),
                )
                material.calculate_totals(markup_percent=float(project.materials_markup_percent))
                db.session.add(material)
                materials_added += 1
        
        # Update document status
        document.parsed = True
        document.parsed_at = datetime.utcnow()
        document.scale = result.get('scale')
        document.drawing_number = result.get('drawing_number')
        
        # Recalculate project totals
        project.recalculate_totals()
        
        db.session.commit()
        
        return jsonify({
            'success': True,
            'materials_added': materials_added,
            'materials_updated': len(result.get('materials', [])) - materials_added,
            'document': document.to_dict()
        })
        
    except Exception as e:
        current_app.logger.error(f"Drawing parse error: {str(e)}")
        document.parse_error = str(e)
        db.session.commit()
        return jsonify({'success': False, 'error': str(e)}), 500


# =============================================================================
# MATERIALS API
# =============================================================================

@bp.route('/api/projects/<int:project_id>/materials', methods=['POST'])
@login_required
def add_material(project_id):
    """Manually add a material to project"""
    from app.models.project import Project, ProjectMaterial
    from app.extensions import db
    
    project = Project.query.filter_by(id=project_id, user_id=current_user.id).first()
    if not project:
        return jsonify({'success': False, 'error': 'Project not found'}), 404
    
    data = request.get_json()
    
    material = ProjectMaterial(
        project_id=project.id,
        manually_added=True,
        category=data.get('category', 'Uncategorised'),
        part_number=data.get('part_number'),
        description=data.get('description'),
        manufacturer=data.get('manufacturer'),
        quantity=data.get('quantity', 1),
        unit=data.get('unit', 'each'),
        unit_cost=data.get('unit_cost'),
        price_source='manual',
        notes=data.get('notes'),
    )
    
    material.calculate_totals(markup_percent=float(project.materials_markup_percent))
    
    db.session.add(material)
    project.recalculate_totals()
    db.session.commit()
    
    return jsonify({
        'success': True,
        'material': material.to_dict(),
        'project_totals': {
            'total_materials_cost': float(project.total_materials_cost),
            'total_materials_sell': float(project.total_materials_sell),
            'grand_total': float(project.grand_total),
        }
    })


@bp.route('/api/projects/<int:project_id>/materials/<int:material_id>', methods=['PUT'])
@login_required
def update_material(project_id, material_id):
    """Update a material"""
    from app.models.project import Project, ProjectMaterial
    from app.extensions import db
    
    project = Project.query.filter_by(id=project_id, user_id=current_user.id).first()
    if not project:
        return jsonify({'success': False, 'error': 'Project not found'}), 404
    
    material = ProjectMaterial.query.filter_by(id=material_id, project_id=project_id).first()
    if not material:
        return jsonify({'success': False, 'error': 'Material not found'}), 404
    
    data = request.get_json()
    
    for field in ['category', 'part_number', 'description', 'manufacturer',
                  'quantity', 'unit', 'unit_cost', 'markup_percent', 'notes']:
        if field in data:
            setattr(material, field, data[field])
    
    material.calculate_totals()
    project.recalculate_totals()
    db.session.commit()
    
    return jsonify({
        'success': True,
        'material': material.to_dict(),
        'project_totals': {
            'total_materials_cost': float(project.total_materials_cost),
            'total_materials_sell': float(project.total_materials_sell),
            'grand_total': float(project.grand_total),
        }
    })


@bp.route('/api/projects/<int:project_id>/materials/<int:material_id>', methods=['DELETE'])
@login_required
def delete_material(project_id, material_id):
    """Delete a material"""
    from app.models.project import Project, ProjectMaterial
    from app.extensions import db
    
    project = Project.query.filter_by(id=project_id, user_id=current_user.id).first()
    if not project:
        return jsonify({'success': False, 'error': 'Project not found'}), 404
    
    material = ProjectMaterial.query.filter_by(id=material_id, project_id=project_id).first()
    if not material:
        return jsonify({'success': False, 'error': 'Material not found'}), 404
    
    db.session.delete(material)
    project.recalculate_totals()
    db.session.commit()
    
    return jsonify({'success': True})


# =============================================================================
# PRICING - QB/XERO MATCHING
# =============================================================================

@bp.route('/api/projects/<int:project_id>/match-prices', methods=['POST'])
@login_required
def match_prices_from_accounting(project_id):
    """Match materials to QuickBooks/Xero products and pull prices"""
    from app.models.project import Project, ProjectMaterial
    from app.models.quickbooks import QuickBooksConnection
    from app.integrations.quickbooks_service import QuickBooksService
    from app.extensions import db
    
    project = Project.query.filter_by(id=project_id, user_id=current_user.id).first()
    if not project:
        return jsonify({'success': False, 'error': 'Project not found'}), 404
    
    # Get QB connection
    qb_connection = QuickBooksConnection.query.filter_by(
        user_id=current_user.id,
        is_active=True
    ).first()
    
    if not qb_connection:
        return jsonify({'success': False, 'error': 'QuickBooks not connected'}), 400
    
    qb_service = QuickBooksService()
    
    # Get all QB items
    response = qb_service.get_items(qb_connection)
    if 'error' in response:
        return jsonify({'success': False, 'error': response['error']}), 400
    
    qb_items = response.get('QueryResponse', {}).get('Item', [])
    
    # Build lookup by SKU
    qb_by_sku = {}
    for item in qb_items:
        sku = item.get('Sku', '').upper()
        if sku:
            qb_by_sku[sku] = item
    
    # Match materials
    materials = ProjectMaterial.query.filter_by(project_id=project_id).all()
    matched = 0
    unmatched = []
    
    for material in materials:
        part_upper = (material.part_number or '').upper()
        
        if part_upper in qb_by_sku:
            qb_item = qb_by_sku[part_upper]
            
            # Get purchase cost and sales price
            purchase_cost = float(qb_item.get('PurchaseCost', 0) or 0)
            sales_price = float(qb_item.get('UnitPrice', 0) or 0)
            
            material.unit_cost = purchase_cost if purchase_cost > 0 else material.unit_cost
            material.qb_item_id = qb_item.get('Id')
            material.qb_item_name = qb_item.get('Name')
            material.price_source = 'quickbooks'
            material.price_verified = True
            material.price_date = datetime.utcnow()
            
            # Use higher of QB sales price or calculated price
            material.calculate_totals(markup_percent=float(project.materials_markup_percent))
            if sales_price > float(material.unit_sell or 0):
                material.unit_sell = sales_price
                material.total_sell = round(float(material.quantity) * sales_price, 2)
            
            matched += 1
        else:
            unmatched.append({
                'part_number': material.part_number,
                'description': material.description
            })
    
    project.recalculate_totals()
    db.session.commit()
    
    return jsonify({
        'success': True,
        'matched': matched,
        'unmatched_count': len(unmatched),
        'unmatched': unmatched[:20],  # Return first 20 unmatched
        'project_totals': {
            'total_materials_cost': float(project.total_materials_cost),
            'total_materials_sell': float(project.total_materials_sell),
            'grand_total': float(project.grand_total),
        }
    })


# =============================================================================
# SUPPLIER QUOTE REQUESTS
# =============================================================================

@bp.route('/api/projects/<int:project_id>/supplier-request', methods=['POST'])
@login_required
def generate_supplier_request(project_id):
    """Generate supplier quote request spreadsheet"""
    from app.models.project import Project, ProjectMaterial, SupplierQuoteRequest
    from app.extensions import db
    import io
    from openpyxl import Workbook
    from openpyxl.styles import Font, PatternFill, Alignment, Border, Side
    
    project = Project.query.filter_by(id=project_id, user_id=current_user.id).first()
    if not project:
        return jsonify({'success': False, 'error': 'Project not found'}), 404
    
    data = request.get_json()
    category_filter = data.get('category')  # Optional - filter by category
    supplier_name = data.get('supplier_name', 'Supplier')
    
    # Get materials
    query = ProjectMaterial.query.filter_by(project_id=project_id)
    if category_filter:
        query = query.filter_by(category=category_filter)
    
    materials = query.filter(
        (ProjectMaterial.price_verified == False) | (ProjectMaterial.price_source == 'estimated')
    ).all()
    
    if not materials:
        return jsonify({'success': False, 'error': 'No materials need pricing'}), 400
    
    # Create Excel workbook
    wb = Workbook()
    ws = wb.active
    ws.title = "Quote Request"
    
    # Styles
    header_font = Font(bold=True, color="FFFFFF")
    header_fill = PatternFill("solid", fgColor="1F4E79")
    
    # Header info
    ws['A1'] = f"QUOTATION REQUEST - {project.name}"
    ws['A1'].font = Font(bold=True, size=14)
    ws['A2'] = f"Project: {project.site_address or project.name}"
    ws['A3'] = f"Date: {datetime.now().strftime('%d/%m/%Y')}"
    ws['A4'] = f"Contact: {current_user.company_name or current_user.email}"
    
    # Column headers
    headers = ["Item", "Description", "Manufacturer", "Part Number", "Qty", "Unit", "Your Price", "Total"]
    for col, header in enumerate(headers, 1):
        cell = ws.cell(row=6, column=col, value=header)
        cell.font = header_font
        cell.fill = header_fill
    
    # Data rows
    for idx, material in enumerate(materials, 1):
        row = 6 + idx
        ws.cell(row=row, column=1, value=idx)
        ws.cell(row=row, column=2, value=material.description)
        ws.cell(row=row, column=3, value=material.manufacturer)
        ws.cell(row=row, column=4, value=material.part_number)
        ws.cell(row=row, column=5, value=float(material.quantity))
        ws.cell(row=row, column=6, value=material.unit)
        ws.cell(row=row, column=7, value="")  # Supplier fills in
        ws.cell(row=row, column=8, value=f"=E{row}*G{row}")
    
    # Column widths
    ws.column_dimensions['B'].width = 45
    ws.column_dimensions['C'].width = 15
    ws.column_dimensions['D'].width = 18
    
    # Save to bytes
    output = io.BytesIO()
    wb.save(output)
    output.seek(0)
    
    # Track the request
    quote_request = SupplierQuoteRequest(
        project_id=project.id,
        supplier_name=supplier_name,
        category=category_filter,
        items_count=len(materials),
        status='pending'
    )
    db.session.add(quote_request)
    db.session.commit()
    
    # Return file
    filename = f"{project.name.replace(' ', '_')}_Quote_Request_{supplier_name}.xlsx"
    
    return send_file(
        output,
        mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
        as_attachment=True,
        download_name=filename
    )


# =============================================================================
# LABOUR CALCULATIONS
# =============================================================================

@bp.route('/api/projects/<int:project_id>/calculate-labour', methods=['POST'])
@login_required
def calculate_labour(project_id):
    """Auto-calculate labour based on materials quantities"""
    from app.models.project import Project, ProjectMaterial, ProjectLabour
    from app.extensions import db
    
    project = Project.query.filter_by(id=project_id, user_id=current_user.id).first()
    if not project:
        return jsonify({'success': False, 'error': 'Project not found'}), 404
    
    # Delete existing auto-calculated labour
    ProjectLabour.query.filter_by(project_id=project_id, auto_calculated=True).delete()
    
    # Get materials
    materials = ProjectMaterial.query.filter_by(project_id=project_id).all()
    
    # Labour rates per task (hours per unit)
    labour_rates = {
        # First fix times (per point)
        'downlights': {'first_fix': 0.25, 'second_fix': 0.15},
        'sockets': {'first_fix': 0.5, 'second_fix': 0.17},
        'switches': {'first_fix': 0.25, 'second_fix': 0.17},
        'fused_spurs': {'first_fix': 0.5, 'second_fix': 0.17},
        'data_points': {'first_fix': 0.5, 'second_fix': 0.25},
        'smoke_detectors': {'first_fix': 0.25, 'second_fix': 0.17},
        'distribution': {'install': 8},  # Per board
        'cable_per_100m': {'install': 2},
        'led_tape_per_m': {'install': 0.5},
        'containment_per_m': {'install': 0.1},
        'testing': {'per_circuit': 0.25},
    }
    
    # Building type multiplier
    multipliers = {
        'new_build': 0.7,
        'renovation': 1.0,
        'retrofit': 1.5,
        'listed': 2.0,
    }
    multiplier = multipliers.get(project.building_type, 1.0)
    
    # Count materials by type
    counts = {
        'downlights': 0,
        'sockets': 0,
        'switches': 0,
        'fused_spurs': 0,
        'data_points': 0,
        'smoke_detectors': 0,
        'distribution_boards': 0,
        'cable_metres': 0,
        'led_tape_metres': 0,
        'containment_metres': 0,
    }
    
    for m in materials:
        cat = (m.category or '').lower()
        desc = (m.description or '').lower()
        qty = float(m.quantity or 0)
        
        if 'downlight' in desc or 'light_type_a' in (m.part_number or '').lower():
            counts['downlights'] += qty
        elif 'socket' in desc and 'double' in desc:
            counts['sockets'] += qty
        elif 'switch' in desc or 'dimmer' in desc:
            counts['switches'] += qty
        elif 'spur' in desc or 'fcu' in desc:
            counts['fused_spurs'] += qty
        elif 'data' in desc or 'cat6' in desc.lower():
            counts['data_points'] += qty
        elif 'smoke' in desc or 'heat' in desc or 'detector' in desc:
            counts['smoke_detectors'] += qty
        elif 'consumer unit' in desc or 'distribution' in desc:
            counts['distribution_boards'] += qty
        elif 'cable' in cat and m.unit == 'm':
            counts['cable_metres'] += qty
        elif 'led tape' in desc or 'tape' in cat:
            counts['led_tape_metres'] += qty
        elif 'conduit' in desc or 'trunking' in desc:
            counts['containment_metres'] += qty
    
    # Generate labour items
    labour_items = []
    rate = float(project.labour_rate_per_hour)
    
    # First fix
    first_fix_hours = (
        counts['downlights'] * labour_rates['downlights']['first_fix'] +
        counts['sockets'] * labour_rates['sockets']['first_fix'] +
        counts['switches'] * labour_rates['switches']['first_fix'] +
        counts['fused_spurs'] * labour_rates['fused_spurs']['first_fix'] +
        counts['data_points'] * labour_rates['data_points']['first_fix'] +
        counts['smoke_detectors'] * labour_rates['smoke_detectors']['first_fix']
    ) * multiplier
    
    if first_fix_hours > 0:
        labour = ProjectLabour(
            project_id=project.id,
            task="First Fix (cabling & back boxes)",
            hours=round(first_fix_hours, 1),
            rate=rate,
            auto_calculated=True,
            calculation_basis=f"{int(counts['sockets'])} sockets, {int(counts['switches'])} switches, {int(counts['downlights'])} lights"
        )
        labour.calculate_total()
        db.session.add(labour)
        labour_items.append(labour.to_dict())
    
    # Second fix
    second_fix_hours = (
        counts['downlights'] * labour_rates['downlights']['second_fix'] +
        counts['sockets'] * labour_rates['sockets']['second_fix'] +
        counts['switches'] * labour_rates['switches']['second_fix'] +
        counts['fused_spurs'] * labour_rates['fused_spurs']['second_fix'] +
        counts['data_points'] * labour_rates['data_points']['second_fix'] +
        counts['smoke_detectors'] * labour_rates['smoke_detectors']['second_fix']
    ) * multiplier
    
    if second_fix_hours > 0:
        labour = ProjectLabour(
            project_id=project.id,
            task="Second Fix (accessories & fittings)",
            hours=round(second_fix_hours, 1),
            rate=rate,
            auto_calculated=True,
        )
        labour.calculate_total()
        db.session.add(labour)
        labour_items.append(labour.to_dict())
    
    # Distribution boards
    if counts['distribution_boards'] > 0:
        db_hours = counts['distribution_boards'] * labour_rates['distribution']['install'] * multiplier
        labour = ProjectLabour(
            project_id=project.id,
            task="Distribution Board Installation",
            hours=round(db_hours, 1),
            rate=rate,
            auto_calculated=True,
            calculation_basis=f"{int(counts['distribution_boards'])} board(s)"
        )
        labour.calculate_total()
        db.session.add(labour)
        labour_items.append(labour.to_dict())
    
    # LED tape
    if counts['led_tape_metres'] > 0:
        tape_hours = counts['led_tape_metres'] * labour_rates['led_tape_per_m']['install']
        labour = ProjectLabour(
            project_id=project.id,
            task="LED Tape Installation",
            hours=round(tape_hours, 1),
            rate=rate,
            auto_calculated=True,
            calculation_basis=f"{int(counts['led_tape_metres'])}m of LED tape"
        )
        labour.calculate_total()
        db.session.add(labour)
        labour_items.append(labour.to_dict())
    
    # Containment
    if counts['containment_metres'] > 0:
        cont_hours = counts['containment_metres'] * labour_rates['containment_per_m']['install'] * multiplier
        labour = ProjectLabour(
            project_id=project.id,
            task="Containment Installation",
            hours=round(cont_hours, 1),
            rate=rate,
            auto_calculated=True,
        )
        labour.calculate_total()
        db.session.add(labour)
        labour_items.append(labour.to_dict())
    
    # Testing (estimate circuits from DB count × 10 ways average)
    estimated_circuits = max(10, counts['distribution_boards'] * 10)
    test_hours = estimated_circuits * labour_rates['testing']['per_circuit']
    labour = ProjectLabour(
        project_id=project.id,
        task="Testing & Certification",
        hours=round(test_hours, 1),
        rate=rate,
        auto_calculated=True,
        calculation_basis=f"~{estimated_circuits} circuits"
    )
    labour.calculate_total()
    db.session.add(labour)
    labour_items.append(labour.to_dict())
    
    # Recalculate totals
    project.recalculate_totals()
    db.session.commit()
    
    return jsonify({
        'success': True,
        'labour': labour_items,
        'total_hours': float(project.total_labour_hours),
        'total_cost': float(project.total_labour_cost),
        'project_totals': {
            'subtotal': float(project.subtotal),
            'contingency': float(project.contingency_amount),
            'grand_total': float(project.grand_total),
        }
    })


# =============================================================================
# QUOTE GENERATION
# =============================================================================

@bp.route('/api/projects/<int:project_id>/generate-quote', methods=['POST'])
@login_required
def generate_quote_pdf(project_id):
    """Generate professional PDF quotation"""
    from app.models.project import Project, ProjectMaterial, ProjectLabour
    # PDF generation would go here - using reportlab or similar
    # For now, return a placeholder
    
    project = Project.query.filter_by(id=project_id, user_id=current_user.id).first()
    if not project:
        return jsonify({'success': False, 'error': 'Project not found'}), 404
    
    # Update status
    project.status = 'quoted'
    project.quoted_at = datetime.utcnow()
    
    from app.extensions import db
    db.session.commit()
    
    return jsonify({
        'success': True,
        'message': 'Quote generated',
        'project': project.to_dict()
    })
