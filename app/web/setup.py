"""Setup wizard for new users"""
from flask import Blueprint, render_template, redirect, url_for, request, flash
from flask_login import login_required, current_user
from app.extensions import db
from app.models.quickbooks import QuickBooksConnection
import logging
import requests

bp = Blueprint('setup', __name__, url_prefix='/setup')
logger = logging.getLogger(__name__)


def get_qb_accounts(user_id):
    """Fetch QuickBooks accounts for dropdowns"""
    qb = QuickBooksConnection.query.filter_by(user_id=user_id).first()
    if not qb or not qb.access_token:
        return [], []
    
    try:
        headers = {
            'Authorization': f'Bearer {qb.access_token}',
            'Accept': 'application/json'
        }
        
        # Query for Income accounts
        income_query = "SELECT * FROM Account WHERE AccountType = 'Income' MAXRESULTS 100"
        income_url = f"https://quickbooks.api.intuit.com/v3/company/{qb.realm_id}/query?query={income_query}"
        
        income_response = requests.get(income_url, headers=headers)
        income_accounts = []
        if income_response.status_code == 200:
            data = income_response.json()
            income_accounts = data.get('QueryResponse', {}).get('Account', [])
        
        # Query for Expense accounts (Cost of Goods Sold and Expense types)
        expense_query = "SELECT * FROM Account WHERE AccountType IN ('Cost of Goods Sold', 'Expense') MAXRESULTS 100"
        expense_url = f"https://quickbooks.api.intuit.com/v3/company/{qb.realm_id}/query?query={expense_query}"
        
        expense_response = requests.get(expense_url, headers=headers)
        expense_accounts = []
        if expense_response.status_code == 200:
            data = expense_response.json()
            expense_accounts = data.get('QueryResponse', {}).get('Account', [])
        
        return income_accounts, expense_accounts
        
    except Exception as e:
        logger.error(f"Error fetching QB accounts: {e}")
        return [], []


@bp.route('/')
@login_required
def index():
    """Setup wizard main page"""
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
        qb = QuickBooksConnection.query.filter_by(user_id=current_user.id).first()
        qb_connected = qb and qb.access_token
        return render_template('setup/step2_quickbooks.html', qb_connected=qb_connected)
    
    elif step == 3:
        # Check if QuickBooks is connected
        qb = QuickBooksConnection.query.filter_by(user_id=current_user.id).first()
        qb_connected = qb and qb.access_token
        
        income_accounts = []
        expense_accounts = []
        current_income = None
        current_expense = None
        
        if qb_connected:
            income_accounts, expense_accounts = get_qb_accounts(current_user.id)
            current_income = qb.default_income_account_id
            current_expense = qb.default_expense_account_id
        
        return render_template('setup/step3_settings.html',
                             qb_connected=qb_connected,
                             income_accounts=income_accounts,
                             expense_accounts=expense_accounts,
                             current_income_account=current_income,
                             current_expense_account=current_expense)
    
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


@bp.route('/save-settings', methods=['POST'])
@login_required
def save_settings():
    """Save markup and QB accounts from step 3"""
    try:
        # Save markup
        markup = request.form.get('default_markup', '50')
        current_user.default_markup = float(markup)
        
        # Save QB accounts if connected
        qb = QuickBooksConnection.query.filter_by(user_id=current_user.id).first()
        if qb:
            income_account = request.form.get('income_account')
            expense_account = request.form.get('expense_account')
            
            if income_account:
                qb.default_income_account_id = income_account
            if expense_account:
                qb.default_expense_account_id = expense_account
        
        db.session.commit()
        
        logger.info(f"User {current_user.id} saved settings: markup={markup}%")
        return redirect(url_for('setup.step', step=4))
        
    except ValueError:
        flash('Please enter a valid number for markup.', 'error')
        return redirect(url_for('setup.step', step=3))
    except Exception as e:
        logger.error(f"Error saving settings: {e}")
        flash('Error saving settings. Please try again.', 'error')
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
