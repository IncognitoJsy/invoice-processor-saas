"""Dashboard routes"""
from flask import Blueprint, render_template

bp = Blueprint('dashboard', __name__, url_prefix='/dashboard')

@bp.route('/')
def index():
    return {'message': 'Dashboard'}, 200
