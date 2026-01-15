"""Error handlers for the application"""
from flask import Blueprint, render_template

bp = Blueprint('errors', __name__)


@bp.app_errorhandler(404)
def not_found_error(error):
    """Handle 404 errors"""
    return render_template('errors/404.html'), 404


@bp.app_errorhandler(500)
def internal_error(error):
    """Handle 500 errors"""
    return render_template('errors/500.html'), 500


@bp.app_errorhandler(403)
def forbidden_error(error):
    """Handle 403 errors"""
    return render_template('errors/403.html'), 403
