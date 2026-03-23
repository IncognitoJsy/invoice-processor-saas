"""Products & Services routes - full platform mode"""
from flask import Blueprint, render_template, redirect, url_for, request, flash, jsonify
from flask_login import login_required, current_user
from app.extensions import db
from app.models.product_service import ProductService
import logging

bp = Blueprint('products', __name__, url_prefix='/products')
logger = logging.getLogger(__name__)


def require_full_mode(f):
    from functools import wraps
    @wraps(f)
    def decorated(*args, **kwargs):
        if current_user.platform_mode not in ['full', 'both']:
            return redirect(url_for('dashboard.index'))
        return f(*args, **kwargs)
    return decorated


@bp.route('/')
@login_required
@require_full_mode
def index():
    item_type = request.args.get('type', '')
    query = ProductService.query.filter_by(user_id=current_user.id, is_active=True)
    if item_type:
        query = query.filter_by(item_type=item_type)
    products = query.order_by(ProductService.name.asc()).all()
    return render_template('products/index.html', products=products, item_type=item_type)


@bp.route('/new', methods=['GET', 'POST'])
@login_required
@require_full_mode
def new():
    if request.method == 'POST':
        product = ProductService(
            user_id=current_user.id,
            name=request.form.get('name', '').strip(),
            sku=request.form.get('sku', '').strip() or None,
            description=request.form.get('description', '').strip() or None,
            category=request.form.get('category', '').strip() or None,
            item_type=request.form.get('item_type', 'product'),
            purchase_price=float(request.form.get('purchase_price', 0) or 0),
            sale_price=float(request.form.get('sale_price', 0) or 0),
            unit_of_measure=request.form.get('unit_of_measure', '').strip() or None,
            tax_applicable=request.form.get('tax_applicable') == 'on',
            track_stock=request.form.get('track_stock') == 'on',
            quantity_in_stock=float(request.form.get('quantity_in_stock', 0) or 0),
        )
        db.session.add(product)
        db.session.commit()
        flash(f'{product.name} added successfully.', 'success')
        return redirect(url_for('products.index'))
    return render_template('products/edit.html', product=None)


@bp.route('/<int:product_id>/edit', methods=['GET', 'POST'])
@login_required
@require_full_mode
def edit(product_id):
    product = ProductService.query.filter_by(id=product_id, user_id=current_user.id).first_or_404()
    if request.method == 'POST':
        product.name = request.form.get('name', '').strip()
        product.sku = request.form.get('sku', '').strip() or None
        product.description = request.form.get('description', '').strip() or None
        product.category = request.form.get('category', '').strip() or None
        product.item_type = request.form.get('item_type', 'product')
        product.purchase_price = float(request.form.get('purchase_price', 0) or 0)
        product.sale_price = float(request.form.get('sale_price', 0) or 0)
        product.unit_of_measure = request.form.get('unit_of_measure', '').strip() or None
        product.tax_applicable = request.form.get('tax_applicable') == 'on'
        product.track_stock = request.form.get('track_stock') == 'on'
        product.quantity_in_stock = float(request.form.get('quantity_in_stock', 0) or 0)
        db.session.commit()
        flash(f'{product.name} updated successfully.', 'success')
        return redirect(url_for('products.index'))
    return render_template('products/edit.html', product=product)


@bp.route('/<int:product_id>/delete', methods=['POST'])
@login_required
@require_full_mode
def delete(product_id):
    product = ProductService.query.filter_by(id=product_id, user_id=current_user.id).first_or_404()
    product.is_active = False
    db.session.commit()
    flash(f'{product.name} removed.', 'success')
    return redirect(url_for('products.index'))
