"""Invoice routes"""
from flask import Blueprint

bp = Blueprint('invoices', __name__, url_prefix='/invoices')

@bp.route('/')
def index():
    return {'message': 'Invoices'}, 200
