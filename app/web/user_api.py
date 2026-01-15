"""User API routes"""
from flask import Blueprint, jsonify
from flask_login import login_required, current_user
from app.extensions import db

bp = Blueprint('user_api', __name__, url_prefix='/api/user')


@bp.route('/complete-tour', methods=['POST'])
@login_required
def complete_tour():
    """Mark onboarding tour as completed"""
    current_user.tour_completed = True
    db.session.commit()
    return jsonify({'success': True})


@bp.route('/restart-tour', methods=['POST'])
@login_required
def restart_tour():
    """Allow user to restart the onboarding tour"""
    current_user.tour_completed = False
    db.session.commit()
    return jsonify({'success': True})


@bp.route('/profile', methods=['GET'])
@login_required
def get_profile():
    """Get current user profile info"""
    return jsonify({
        'email': current_user.email,
        'first_name': current_user.first_name,
        'last_name': current_user.last_name,
        'company_name': current_user.company_name,
        'plan': current_user.subscription_plan,
        'plan_display': current_user.plan_display_name,
        'setup_completed': current_user.setup_completed,
        'tour_completed': current_user.tour_completed
    })
