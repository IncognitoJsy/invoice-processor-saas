"""Queue management routes"""
from flask import Blueprint

bp = Blueprint('queue', __name__, url_prefix='/queue')

@bp.route('/')
def index():
    return {'message': 'Queue'}, 200
