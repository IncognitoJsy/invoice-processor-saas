"""Static pages routes (Help Centre, Privacy Policy, Terms of Service)"""
from flask import Blueprint, render_template

bp = Blueprint('pages', __name__)


@bp.route('/help')
def help_centre():
    """Help Centre / FAQ page"""
    return render_template('pages/help.html')


@bp.route('/privacy')
def privacy():
    """Privacy Policy page"""
    return render_template('pages/privacy.html')


@bp.route('/terms')
def terms():
    """Terms of Service page"""
    return render_template('pages/terms.html')
