"""Settings routes"""
from flask import Blueprint, redirect, url_for
from flask_login import login_required

bp = Blueprint('settings', __name__, url_prefix='/settings')

@bp.route('/')
@login_required
def index():
    # Redirect to integrations for now
    return redirect('/integrations/quickbooks/settings')