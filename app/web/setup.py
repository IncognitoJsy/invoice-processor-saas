"""Setup wizard for new users"""
from flask import Blueprint, render_template, redirect, url_for, request, flash, jsonify
from flask_login import login_required, current_user
from app.extensions import db
import logging

bp = Blueprint('setup', __name__, url_prefix='/setup')
logger = logging.getLogger(__name__)

@bp.route('/')
@login_required
def index():
    """Setup wizard main page"""
    # If setup already completed, redirect to dashboard
    if current_user.setup_completed:
        return redirect(url_for('dashboard.index'))
    
    return render_template('setup/index.html')

@bp.route('/step/<int:step>')
@login_required
def step(step):
    """Individual setup steps"""
    if current_user.setup_completed:
        return redirect(url_for('dashboard.index'))
    
    if step == 1:
        return render_template('setup/step1_business.html')
    elif step == 2:
        return render_template('setup/step2_quickbooks.html')
    elif step == 3:
        return render_template('setup/step3_markup.html')
    elif step == 4:
        return render_template('setup/step4_complete.html')
    else:
        return redirect(url_for('setup.index'))

@bp.route('/save-business', methods=['POST'])
@login_required
def save_business():
    """Save business info from step 1"""
    try:
        current_user.company_name = request.form.get('company_name', '').strip()
        current_user.first_name = request.form.get('first_name', '').strip()
        current_user.last_name = request.form.get('last_name', '').strip()
        db.session.commit()
        
        logger.info(f"User {current_user.id} saved business info")
        return redirect(url_for('setup.step', step=2))
    except Exception as e:
        logger.error(f"Error saving business info: {e}")
        flash('Error saving information. Please try again.', 'error')
        return redirect(url_for('setup.step', step=1))

@bp.route('/save-markup', methods=['POST'])
@login_required
def save_markup():
    """Save default markup from step 3"""
    try:
        markup = request.form.get('default_markup', '50')
        current_user.default_markup = float(markup)
        db.session.commit()
        
        logger.info(f"User {current_user.id} set default markup to {markup}%")
        return redirect(url_for('setup.step', step=4))
    except ValueError:
        flash('Please enter a valid number for markup.', 'error')
        return redirect(url_for('setup.step', step=3))
    except Exception as e:
        logger.error(f"Error saving markup: {e}")
        flash('Error saving markup. Please try again.', 'error')
        return redirect(url_for('setup.step', step=3))

@bp.route('/complete', methods=['POST'])
@login_required
def complete():
    """Mark setup as complete"""
    try:
        current_user.setup_completed = True
        db.session.commit()
        
        logger.info(f"User {current_user.id} completed setup wizard")
        flash('Setup complete! Welcome to FluxOps.', 'success')
        return redirect(url_for('dashboard.index'))
    except Exception as e:
        logger.error(f"Error completing setup: {e}")
        flash('Error completing setup. Please try again.', 'error')
        return redirect(url_for('setup.step', step=4))

@bp.route('/skip')
@login_required
def skip():
    """Skip setup wizard entirely"""
    try:
        current_user.setup_completed = True
        db.session.commit()
        
        logger.info(f"User {current_user.id} skipped setup wizard")
        return redirect(url_for('dashboard.index'))
    except Exception as e:
        logger.error(f"Error skipping setup: {e}")
        return redirect(url_for('setup.index'))
