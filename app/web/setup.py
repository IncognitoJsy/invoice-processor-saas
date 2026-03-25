"""Setup wizard for new users"""
from flask import Blueprint, render_template, redirect, url_for, request, flash
from flask_login import login_required, current_user
from app.extensions import db
from app.models.quickbooks import QuickBooksConnection
from app.models.xero import XeroConnection
from datetime import datetime
import logging
import requests

bp = Blueprint('setup', __name__, url_prefix='/setup')
logger = logging.getLogger(__name__)


def get_qb_accounts(user_id):
    qb = QuickBooksConnection.query.filter_by(user_id=user_id).first()
    if not qb or not qb.access_token:
        return [], []
    try:
        headers = {'Authorization': f'Bearer {qb.access_token}', 'Accept': 'application/json'}
        income_query = "SELECT * FROM Account WHERE AccountType = 'Income' MAXRESULTS 100"
        income_url = f"https://quickbooks.api.intuit.com/v3/company/{qb.realm_id}/query?query={income_query}"
        income_response = requests.get(income_url, headers=headers)
        income_accounts = []
        if income_response.status_code == 200:
            income_accounts = income_response.json().get('QueryResponse', {}).get('Account', [])
        expense_query = "SELECT * FROM Account WHERE AccountType IN ('Cost of Goods Sold', 'Expense') MAXRESULTS 100"
        expense_url = f"https://quickbooks.api.intuit.com/v3/company/{qb.realm_id}/query?query={expense_query}"
        expense_response = requests.get(expense_url, headers=headers)
        expense_accounts = []
        if expense_response.status_code == 200:
            expense_accounts = expense_response.json().get('QueryResponse', {}).get('Account', [])
        return income_accounts, expense_accounts
    except Exception as e:
        logger.error(f"Error fetching QB accounts: {e}")
        return [], []


def get_xero_accounts(user_id):
    from app.integrations.xero_service import XeroService
    xero_conn = XeroConnection.query.filter_by(user_id=user_id).first()
    if not xero_conn or not xero_conn.is_active:
        return [], []
    try:
        xero = XeroService()
        return xero.get_revenue_accounts(xero_conn), xero.get_expense_accounts(xero_conn)
    except Exception as e:
        logger.error(f"Error fetching Xero accounts: {e}")
        return [], []


@bp.route('/')
@login_required
def index():
    if current_user.setup_completed:
        return redirect(url_for('dashboard.index'))
    return render_template('setup/index.html')


@bp.route('/step/<int:step>')
@login_required
def step(step):
    if current_user.setup_completed:
        return redirect(url_for('dashboard.index'))

    if step == 1:
        return render_template('setup/step1_business.html')

    elif step == 2:
        return render_template('setup/step2_mode.html')

    elif step == 3:
        return render_template('setup/step3_trade.html')

    elif step == 4:
        return render_template('setup/step4_tax.html')

    elif step == 5:
        # Accounting connect step — only for sync/both users
        mode = current_user.platform_mode or 'sync'
        if mode == 'full':
            return redirect(url_for('setup.step', step=6))
        qb = QuickBooksConnection.query.filter_by(user_id=current_user.id).first()
        qb_connected = qb and qb.access_token and qb.is_active
        qb_company_name = qb.company_name if qb else None
        xero = XeroConnection.query.filter_by(user_id=current_user.id).first()
        xero_connected = xero and xero.is_active
        xero_tenant_name = xero.tenant_name if xero else None
        return render_template('setup/step2_quickbooks.html',
                               qb_connected=qb_connected,
                               qb_company_name=qb_company_name,
                               xero_connected=xero_connected,
                               xero_tenant_name=xero_tenant_name,
                               step_override=5,
                               total_steps=7)

    elif step == 6:
        # Settings (markup + accounts)
        mode = current_user.platform_mode or 'sync'

        # Full platform users only need markup setting — no accounting accounts
        if mode == 'full':
            return render_template('setup/step3_settings.html',
                                   qb_connected=False,
                                   income_accounts=[],
                                   expense_accounts=[],
                                   current_income_account=None,
                                   current_expense_account=None,
                                   xero_connected=False,
                                   xero_sales_accounts=[],
                                   xero_expense_accounts=[],
                                   current_xero_sales_account=None,
                                   current_xero_expense_account=None,
                                   step_override=6,
                                   total_steps=6,
                                   platform_mode=mode)

        qb = QuickBooksConnection.query.filter_by(user_id=current_user.id).first()
        qb_connected = qb and qb.access_token and qb.is_active
        xero = XeroConnection.query.filter_by(user_id=current_user.id).first()
        xero_connected = xero and xero.is_active
        income_accounts, expense_accounts, xero_sales_accounts, xero_expense_accounts = [], [], [], []
        current_income = current_expense = current_xero_sales = current_xero_expense = None
        if qb_connected:
            income_accounts, expense_accounts = get_qb_accounts(current_user.id)
            current_income = qb.default_income_account_id
            current_expense = qb.default_expense_account_id
        if xero_connected:
            xero_sales_accounts, xero_expense_accounts = get_xero_accounts(current_user.id)
            current_xero_sales = xero.default_sales_account_code
            current_xero_expense = xero.default_expense_account_code
        return render_template('setup/step3_settings.html',
                               qb_connected=qb_connected,
                               income_accounts=income_accounts,
                               expense_accounts=expense_accounts,
                               current_income_account=current_income,
                               current_expense_account=current_expense,
                               xero_connected=xero_connected,
                               xero_sales_accounts=xero_sales_accounts,
                               xero_expense_accounts=xero_expense_accounts,
                               current_xero_sales_account=current_xero_sales,
                               current_xero_expense_account=current_xero_expense,
                               step_override=6,
                               total_steps=7,
                               platform_mode=mode)

    elif step == 7:
        mode = current_user.platform_mode or 'sync'
        # Full platform users go straight to dashboard from step 6
        if mode == 'full':
            return redirect(url_for('dashboard.index'))
        qb = QuickBooksConnection.query.filter_by(user_id=current_user.id).first()
        qb_connected = qb and qb.access_token and qb.is_active
        xero = XeroConnection.query.filter_by(user_id=current_user.id).first()
        xero_connected = xero and xero.is_active
        return render_template('setup/step4_complete.html',
                               qb_connected=qb_connected,
                               xero_connected=xero_connected)

    else:
        return redirect(url_for('setup.index'))


@bp.route('/save-business', methods=['POST'])
@login_required
def save_business():
    try:
        current_user.company_name = request.form.get('company_name', '').strip()
        current_user.first_name = request.form.get('first_name', '').strip()
        current_user.last_name = request.form.get('last_name', '').strip()
        db.session.commit()
        return redirect(url_for('setup.step', step=2))
    except Exception as e:
        logger.error(f"Error saving business info: {e}")
        flash('Error saving information. Please try again.', 'error')
        return redirect(url_for('setup.step', step=1))


@bp.route('/save-mode', methods=['POST'])
@login_required
def save_mode():
    try:
        current_user.platform_mode = request.form.get('platform_mode', 'sync')
        db.session.commit()
        return redirect(url_for('setup.step', step=3))
    except Exception as e:
        logger.error(f"Error saving mode: {e}")
        flash('Error saving. Please try again.', 'error')
        return redirect(url_for('setup.step', step=2))


@bp.route('/save-trade', methods=['POST'])
@login_required
def save_trade():
    try:
        current_user.trade_type = request.form.get('trade_type', 'other')
        db.session.commit()
        return redirect(url_for('setup.step', step=4))
    except Exception as e:
        logger.error(f"Error saving trade: {e}")
        flash('Error saving. Please try again.', 'error')
        return redirect(url_for('setup.step', step=3))


@bp.route('/save-tax', methods=['POST'])
@login_required
def save_tax():
    try:
        current_user.country = request.form.get('country', '').strip()
        tax_registered = request.form.get('tax_registered', 'false') == 'true'
        current_user.tax_registered = tax_registered
        if tax_registered:
            current_user.tax_number = request.form.get('tax_number', '').strip()
            current_user.tax_type = request.form.get('tax_type', '').strip()
            try:
                current_user.tax_rate = float(request.form.get('tax_rate', 0))
            except ValueError:
                current_user.tax_rate = 0.0
            tax_from = request.form.get('tax_registered_from', '')
            if tax_from:
                current_user.tax_registered_from = datetime.strptime(tax_from, '%Y-%m-%d')
        db.session.commit()
        # Route based on mode
        mode = current_user.platform_mode or 'sync'
        if mode == 'full':
            return redirect(url_for('setup.step', step=6))
        else:
            return redirect(url_for('setup.step', step=5))
    except Exception as e:
        logger.error(f"Error saving tax: {e}")
        flash('Error saving. Please try again.', 'error')
        return redirect(url_for('setup.step', step=4))


@bp.route('/save-settings', methods=['POST'])
@login_required
def save_settings():
    try:
        markup = request.form.get('default_markup', '50')
        current_user.default_markup = float(markup)
        qb = QuickBooksConnection.query.filter_by(user_id=current_user.id).first()
        if qb and qb.is_active:
            income_account = request.form.get('income_account')
            expense_account = request.form.get('expense_account')
            if income_account:
                qb.default_income_account_id = income_account
            if expense_account:
                qb.default_expense_account_id = expense_account
        xero = XeroConnection.query.filter_by(user_id=current_user.id).first()
        if xero and xero.is_active:
            xero_sales_account = request.form.get('xero_sales_account')
            xero_expense_account = request.form.get('xero_expense_account')
            if xero_sales_account:
                xero.default_sales_account_code = xero_sales_account
            if xero_expense_account:
                xero.default_expense_account_code = xero_expense_account
        db.session.commit()
        # Full platform users are done after settings — no accounting step needed
        if current_user.platform_mode == 'full':
            current_user.setup_completed = True
            db.session.commit()
            flash('Setup complete! Welcome to GoZappify.', 'success')
            return redirect(url_for('dashboard.index'))
        return redirect(url_for('setup.step', step=7))
    except ValueError:
        flash('Please enter a valid number for markup.', 'error')
        return redirect(url_for('setup.step', step=6))
    except Exception as e:
        logger.error(f"Error saving settings: {e}")
        flash('Error saving settings. Please try again.', 'error')
        return redirect(url_for('setup.step', step=6))


@bp.route('/complete', methods=['POST'])
@login_required
def complete():
    try:
        current_user.setup_completed = True
        db.session.commit()
        flash('Setup complete! Welcome to GoZappify.', 'success')
        return redirect(url_for('dashboard.index'))
    except Exception as e:
        logger.error(f"Error completing setup: {e}")
        flash('Error completing setup. Please try again.', 'error')
        return redirect(url_for('setup.step', step=7))


@bp.route('/skip')
@login_required
def skip():
    try:
        current_user.setup_completed = True
        db.session.commit()
        return redirect(url_for('dashboard.index'))
    except Exception as e:
        logger.error(f"Error skipping setup: {e}")
        return redirect(url_for('setup.index'))
