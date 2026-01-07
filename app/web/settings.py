"""Settings routes"""
from flask import Blueprint

bp = Blueprint('settings', __name__, url_prefix='/settings')

@bp.route('/')
def index():
    return {'message': 'Settings'}, 200
