from flask import Flask, render_template, request, redirect, flash, jsonify, session, g, url_for, Blueprint
from flask_sqlalchemy import SQLAlchemy
from flask_wtf.csrf import CSRFProtect, generate_csrf, validate_csrf
from werkzeug.security import generate_password_hash, check_password_hash
from flask_migrate import Migrate
import os
import secrets
import re
from datetime import datetime, timedelta, timezone
from functools import wraps
import logging
from logging.handlers import RotatingFileHandler
from sqlalchemy import func, case, text, and_, or_, extract
from sqlalchemy.exc import SQLAlchemyError, DatabaseError
from werkzeug.exceptions import BadRequest
from contextlib import contextmanager
from flask_wtf import FlaskForm
from wtforms import StringField, PasswordField
from wtforms.validators import DataRequired
from flask_wtf.csrf import CSRFError

# ✅ تهيئة تطبيق Flask
app = Flask(__name__)

def get_current_utc_time():
    return datetime.now(timezone.utc).isoformat()

# ✅ تأمين المفتاح السري تلقائيًا
app.secret_key = secrets.token_hex(32)
app.config['WTF_CSRF_ENABLED'] = True
app.config['WTF_CSRF_SECRET_KEY'] = secrets.token_hex(32)  # مفتاح سري مختلف

# ✅ تهيئة حماية CSRF
csrf = CSRFProtect(app)

# ✅ إعدادات الأمان الإضافية
app.config.update(
    SESSION_COOKIE_SECURE=True,
    SESSION_COOKIE_HTTPONLY=True,
    SESSION_COOKIE_SAMESITE='Lax',
    WTF_CSRF_TIME_LIMIT=3600,  # صلاحية التوكن لمدة ساعة
    SQLALCHEMY_POOL_RECYCLE=299,  # إعادة استخدام اتصالات قاعدة البيانات
    SQLALCHEMY_POOL_TIMEOUT=20
)

# ✅ تهيئة قاعدة البيانات
basedir = os.path.abspath(os.path.dirname(__file__))
db_path = os.path.join(basedir, 'data', 'database.db')
os.makedirs(os.path.dirname(db_path), exist_ok=True)

app.config['SQLALCHEMY_DATABASE_URI'] = f'sqlite:///{db_path}'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
app.config['SQLALCHEMY_ENGINE_OPTIONS'] = {
    'pool_size': 10,
    'pool_recycle': 300,
    'pool_pre_ping': True
}

# ✅ تهيئة SQLAlchemy
db = SQLAlchemy(app)
migrate = Migrate(app, db)

# تعريف مدير السياق لإدارة جلسات قاعدة البيانات
@contextmanager
def db_session():
    session = db.session
    try:
        yield session
        session.commit()
    except Exception as e:
        session.rollback()
        raise e
    finally:
        session.close()

# ✅ إعداد السجلات (Logging)
log_path = os.path.join(basedir, 'inventory.log')
logging.basicConfig(level=logging.INFO)

log_handler = RotatingFileHandler(log_path, maxBytes=10000, backupCount=3)
log_handler.setLevel(logging.INFO)
formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')
log_handler.setFormatter(formatter)
app.logger.addHandler(log_handler)

# ======== تعريف النماذج المحدثة ========
#class LoginForm(FlaskForm):
#    username = StringField('اسم المستخدم', validators=[DataRequired()])
#    password = PasswordField('كلمة المرور', validators=[DataRequired()])

class Currency(db.Model):
    __tablename__ = 'currencies'
    currency_id = db.Column(db.Integer, primary_key=True)
    currency_code = db.Column(db.String(3), nullable=False)
    currency_name = db.Column(db.String(50), nullable=False)
    symbol = db.Column(db.String(10))
    is_base_currency = db.Column(db.Boolean, default=False)
    decimal_places = db.Column(db.Integer, default=2)
    is_active = db.Column(db.Boolean, default=True)
    created_at = db.Column(db.Text)
    archived = db.Column(db.Boolean, default=False)

class ExchangeRate(db.Model):
    __tablename__ = 'exchange_rates'
    rate_id = db.Column(db.Integer, primary_key=True)
    base_currency_id = db.Column(db.Integer, db.ForeignKey('currencies.currency_id'))
    target_currency_id = db.Column(db.Integer, db.ForeignKey('currencies.currency_id'))
    exchange_rate = db.Column(db.Float, nullable=False)
    effective_date = db.Column(db.Text, nullable=False)
    is_active = db.Column(db.Boolean, default=True)
    created_at = db.Column(db.Text)
    archived = db.Column(db.Boolean, default=False)

    base_currency = db.relationship('Currency', foreign_keys=[base_currency_id])
    target_currency = db.relationship('Currency', foreign_keys=[target_currency_id])

class Category(db.Model):
    __tablename__ = 'categories'
    category_id = db.Column(db.Integer, primary_key=True)
    category_name = db.Column(db.String(100), nullable=False)
    category_type = db.Column(db.String(50))
    parent_category_id = db.Column(db.Integer, db.ForeignKey('categories.category_id'))
    description = db.Column(db.Text)
    tax_rate = db.Column(db.Float, default=0.0)
    is_active = db.Column(db.Boolean, default=True)
    created_at = db.Column(db.Text)
    updated_at = db.Column(db.Text)
    archived = db.Column(db.Boolean, default=False)
    version = db.Column(db.Integer)

    parent = db.relationship('Category', remote_side=[category_id], backref='child_categories')

class Unit(db.Model):
    __tablename__ = 'units'
    unit_id = db.Column(db.Integer, primary_key=True)
    unit_name = db.Column(db.String(50), nullable=False)
    unit_symbol = db.Column(db.String(10), nullable=False)
    is_decimal = db.Column(db.Boolean, default=False)
    base_unit_id = db.Column(db.Integer, db.ForeignKey('units.unit_id'))
    conversion_factor = db.Column(db.Float)
    created_at = db.Column(db.Text)
    archived = db.Column(db.Boolean, default=False)

    base_unit = db.relationship('Unit', remote_side=[unit_id], backref='derived_units')

class Warehouse(db.Model):
    __tablename__ = 'warehouses'
    warehouse_id = db.Column(db.Integer, primary_key=True)
    warehouse_name = db.Column(db.String(100), nullable=False)
    location_country = db.Column(db.String(100))
    location_region = db.Column(db.String(100))
    location_details = db.Column(db.String(255))
    is_default = db.Column(db.Boolean, default=False)
    is_active = db.Column(db.Boolean, default=True)
    created_at = db.Column(db.Text)
    archived = db.Column(db.Boolean, default=False)
    description = db.Column(db.Text)
    location = db.Column(db.Text)

class Product(db.Model):
    __tablename__ = 'products'
    product_id = db.Column(db.Integer, primary_key=True)
    product_code = db.Column(db.String(50), unique=True, nullable=False)
    barcode = db.Column(db.String(50), unique=True)
    product_name = db.Column(db.String(255), nullable=False)
    description = db.Column(db.Text)
    category_id = db.Column(db.Integer, db.ForeignKey('categories.category_id'), nullable=False)
    unit_id = db.Column(db.Integer, db.ForeignKey('units.unit_id'), nullable=False)
    unit_price = db.Column(db.Float, default=0.0)
    tax_class = db.Column(db.String(20))
    is_active = db.Column(db.Boolean, default=True)
    is_service = db.Column(db.Boolean, default=False)
    is_serialized = db.Column(db.Boolean, default=False)
    is_batch_tracked = db.Column(db.Boolean, default=False)
    has_expiry = db.Column(db.Boolean, default=False)
    min_stock_level = db.Column(db.Float, default=0.0)
    created_at = db.Column(db.Text)
    updated_at = db.Column(db.Text)
    archived = db.Column(db.Boolean, default=False)
    version = db.Column(db.Integer)
    sale_type = db.Column(db.String(50))
    invoice_type = db.Column(db.String(50))
    supplier_id = db.Column(db.Integer, db.ForeignKey('entities.entity_id'))
    customer_id = db.Column(db.Integer, db.ForeignKey('entities.entity_id'))
    stock_qty = db.Column(db.Float, default=0.0)
    purchase_price = db.Column(db.Float, default=0.0)
    min_stock_qty = db.Column(db.Float, default=0.0)
        
    category = db.relationship('Category', backref='products_in_category')
    unit = db.relationship('Unit', backref='products_in_unit')
    supplier = db.relationship('Entity', foreign_keys=[supplier_id], back_populates='supplier_products', overlaps="product_supplier")
    customer = db.relationship('Entity', foreign_keys=[customer_id], back_populates='customer_products', overlaps="product_customer")

class InventoryLevel(db.Model):
    __tablename__ = 'inventory_levels'
    inventory_id = db.Column(db.Integer, primary_key=True)
    product_id = db.Column(db.Integer, db.ForeignKey('products.product_id'), nullable=False)
    warehouse_id = db.Column(db.Integer, db.ForeignKey('warehouses.warehouse_id'), nullable=False)
    quantity_on_hand = db.Column(db.Float, default=0.0)
    quantity_committed = db.Column(db.Float, default=0.0)
    average_cost = db.Column(db.Float, default=0.0)
    last_count_date = db.Column(db.Text)
    last_transaction_id = db.Column(db.Integer)
    created_at = db.Column(db.Text)
    archived = db.Column(db.Boolean, default=False)
    version = db.Column(db.Integer)
    expiry_date = db.Column(db.Text)
    stock_qty = db.Column(db.Float, default=0.0)

    product = db.relationship('Product', backref='inventory_records')
    warehouse = db.relationship('Warehouse', backref='inventory_data')

class InventoryMovement(db.Model):
    __tablename__ = 'inventory_movements'
    movement_id = db.Column(db.Integer, primary_key=True)
    product_id = db.Column(db.Integer, db.ForeignKey('products.product_id'), nullable=False)
    warehouse_id = db.Column(db.Integer, db.ForeignKey('warehouses.warehouse_id'), nullable=False)
    movement_type = db.Column(db.String(50), nullable=False)
    transaction_id = db.Column(db.Integer)
    movement_date = db.Column(db.Text)
    quantity_before = db.Column(db.Float)
    quantity_change = db.Column(db.Float)
    quantity_after = db.Column(db.Float)
    unit_cost = db.Column(db.Float)
    total_cost = db.Column(db.Float)
    reference = db.Column(db.String(100))
    notes = db.Column(db.Text)
    created_by = db.Column(db.Integer)
    created_at = db.Column(db.Text)
    archived = db.Column(db.Boolean, default=False)
    quantity = db.Column(db.Float)
    unit_price = db.Column(db.Float)
    sale_type = db.Column(db.String(50))
    invoice_type = db.Column(db.String(50))
    supplier_id = db.Column(db.Integer, db.ForeignKey('entities.entity_id'))
    customer_id = db.Column(db.Integer, db.ForeignKey('entities.entity_id'))

    product = db.relationship('Product', backref='movement_history')
    warehouse = db.relationship('Warehouse', backref='movement_logs')
    supplier = db.relationship('Entity', foreign_keys=[supplier_id])
    customer = db.relationship('Entity', foreign_keys=[customer_id])

class Stocktake(db.Model):
    __tablename__ = 'stocktakes'
    stocktake_id = db.Column(db.Integer, primary_key=True)
    warehouse_id = db.Column(db.Integer, db.ForeignKey('warehouses.warehouse_id'))
    start_date = db.Column(db.Text)
    end_date = db.Column(db.Text)
    status = db.Column(db.String(50), nullable=False)
    total_variance = db.Column(db.Float)
    notes = db.Column(db.Text)
    created_by = db.Column(db.Integer)
    created_at = db.Column(db.Text)
    archived = db.Column(db.Boolean, default=False)

    warehouse = db.relationship('Warehouse', backref='stocktake_activities')

class StocktakeDetail(db.Model):
    __tablename__ = 'stocktake_details'
    detail_id = db.Column(db.Integer, primary_key=True)
    stocktake_id = db.Column(db.Integer, db.ForeignKey('stocktakes.stocktake_id'), nullable=False)
    product_id = db.Column(db.Integer, db.ForeignKey('products.product_id'), nullable=False)
    system_quantity = db.Column(db.Float, default=0.0)
    counted_quantity = db.Column(db.Float, default=0.0)
    variance_value = db.Column(db.Float)
    notes = db.Column(db.String(255))
    created_at = db.Column(db.Text)
    archived = db.Column(db.Boolean, default=False)

    stocktake = db.relationship('Stocktake', backref='details')
    product = db.relationship('Product', backref='stocktake_records')

class EntityType(db.Model):
    __tablename__ = 'entity_types'
    type_id = db.Column(db.Integer, primary_key=True)
    type_name = db.Column(db.String(50), nullable=False)
    type_class = db.Column(db.String(50))
    archived = db.Column(db.Boolean, default=False)

class Entity(db.Model):
    __tablename__ = 'entities'
    entity_id = db.Column(db.Integer, primary_key=True)
    entity_type_id = db.Column(db.Integer, db.ForeignKey('entity_types.type_id'), nullable=False)
    entity_code = db.Column(db.String(20), unique=True)
    legal_name = db.Column(db.String(255))
    commercial_name = db.Column(db.String(255))
    tax_number = db.Column(db.String(50))
    commercial_registration = db.Column(db.String(50))
    vat_number = db.Column(db.String(50))
    credit_limit = db.Column(db.Float, default=0.0)
    current_balance = db.Column(db.Float, default=0.0)
    currency_id = db.Column(db.Integer, db.ForeignKey('currencies.currency_id'))
    payment_terms = db.Column(db.String(50))
    is_active = db.Column(db.Boolean, default=True)
    created_at = db.Column(db.Text)
    updated_at = db.Column(db.Text)
    archived = db.Column(db.Boolean, default=False)
    version = db.Column(db.Integer)
    entity_type = db.Column(db.String(50))

    entity_type_rel = db.relationship('EntityType')
    currency = db.relationship('Currency')
    supplier_products = db.relationship('Product', foreign_keys='Product.supplier_id', back_populates='supplier', overlaps="product_supplier")
    customer_products = db.relationship('Product', foreign_keys='Product.customer_id', back_populates='customer', overlaps="product_customer")
    contacts = db.relationship('EntityContact', backref='entity', cascade='all, delete-orphan')
    addresses = db.relationship('EntityAddress', backref='entity', cascade='all, delete-orphan')

class EntityContact(db.Model):
    __tablename__ = 'entity_contacts'
    contact_id = db.Column(db.Integer, primary_key=True)
    entity_id = db.Column(db.Integer, db.ForeignKey('entities.entity_id', ondelete='CASCADE'), nullable=False)
    contact_name = db.Column(db.String(100))
    position = db.Column(db.String(100))
    primary_phone = db.Column(db.String(20))
    secondary_phone = db.Column(db.String(20))
    email = db.Column(db.String(100))
    is_primary = db.Column(db.Boolean, default=False)
    created_at = db.Column(db.Text)
    archived = db.Column(db.Boolean, default=False)

class EntityAddress(db.Model):
    __tablename__ = 'entity_addresses'
    address_id = db.Column(db.Integer, primary_key=True)
    entity_id = db.Column(db.Integer, db.ForeignKey('entities.entity_id', ondelete='CASCADE'), nullable=False)
    address_type = db.Column(db.String(50))
    address_line1 = db.Column(db.String(255))
    address_line2 = db.Column(db.String(255))
    city = db.Column(db.String(100))
    state = db.Column(db.String(100))
    postal_code = db.Column(db.String(20))
    country = db.Column(db.String(100))
    is_default = db.Column(db.Boolean, default=False)
    created_at = db.Column(db.Text)
    archived = db.Column(db.Boolean, default=False)

class FinancialTransaction(db.Model):
    __tablename__ = 'financial_transactions'
    transaction_id = db.Column(db.Integer, primary_key=True)
    transaction_code = db.Column(db.String(20))
    transaction_type = db.Column(db.String(50))
    entity_id = db.Column(db.Integer, db.ForeignKey('entities.entity_id'))
    currency_id = db.Column(db.Integer, db.ForeignKey('currencies.currency_id'))
    exchange_rate_id = db.Column(db.Integer, db.ForeignKey('exchange_rates.rate_id'))
    transaction_date = db.Column(db.Text, nullable=False)
    due_date = db.Column(db.Text)
    reference_number = db.Column(db.String(50))
    subtotal = db.Column(db.Float, default=0.0)
    discount_amount = db.Column(db.Float, default=0.0)
    tax_amount = db.Column(db.Float, default=0.0)
    shipping_amount = db.Column(db.Float, default=0.0)
    total_amount = db.Column(db.Float, default=0.0)
    amount_paid = db.Column(db.Float, default=0.0)
    payment_status = db.Column(db.String(50))
    status = db.Column(db.String(50))
    notes = db.Column(db.Text)
    created_by = db.Column(db.Integer)
    created_at = db.Column(db.Text)
    updated_at = db.Column(db.Text)
    archived = db.Column(db.Boolean, default=False)
    version = db.Column(db.Integer)

    entity = db.relationship('Entity', backref='financial_transactions')
    currency = db.relationship('Currency')
    exchange_rate = db.relationship('ExchangeRate')

class TransactionDetail(db.Model):
    __tablename__ = 'transaction_details'
    detail_id = db.Column(db.Integer, primary_key=True)
    transaction_id = db.Column(db.Integer, db.ForeignKey('financial_transactions.transaction_id'), nullable=False)
    product_id = db.Column(db.Integer, db.ForeignKey('products.product_id'))
    item_description = db.Column(db.String(255))
    quantity = db.Column(db.Float, default=0.0)
    unit_price = db.Column(db.Float, default=0.0)
    discount_percentage = db.Column(db.Float, default=0.0)
    discount_amount = db.Column(db.Float, default=0.0)
    tax_amount = db.Column(db.Float, default=0.0)
    batch_number = db.Column(db.String(50))
    expiry_date = db.Column(db.Text)
    serial_number = db.Column(db.String(100))
    notes = db.Column(db.String(255))
    created_at = db.Column(db.Text)
    archived = db.Column(db.Boolean, default=False)

    transaction = db.relationship('FinancialTransaction', backref='line_items')
    product = db.relationship('Product', backref='transaction_items')

class Payment(db.Model):
    __tablename__ = 'payments'
    payment_id = db.Column(db.Integer, primary_key=True)
    transaction_id = db.Column(db.Integer, db.ForeignKey('financial_transactions.transaction_id'))
    payment_date = db.Column(db.Text)
    amount = db.Column(db.Float, default=0.0)
    payment_method = db.Column(db.String(50))
    currency_id = db.Column(db.Integer, db.ForeignKey('currencies.currency_id'))
    exchange_rate_id = db.Column(db.Integer, db.ForeignKey('exchange_rates.rate_id'))
    reference_number = db.Column(db.String(50))
    notes = db.Column(db.Text)
    created_by = db.Column(db.Integer)
    created_at = db.Column(db.Text)
    archived = db.Column(db.Boolean, default=False)

    transaction = db.relationship('FinancialTransaction', backref='payments')
    currency = db.relationship('Currency')
    exchange_rate = db.relationship('ExchangeRate')

class Account(db.Model):
    __tablename__ = 'accounts'
    account_id = db.Column(db.Integer, primary_key=True)
    account_number = db.Column(db.String(20))
    account_name = db.Column(db.String(100))
    account_type = db.Column(db.String(50))
    parent_account_id = db.Column(db.Integer, db.ForeignKey('accounts.account_id'))
    currency_id = db.Column(db.Integer, db.ForeignKey('currencies.currency_id'))
    opening_balance = db.Column(db.Float, default=0.0)
    current_balance = db.Column(db.Float, default=0.0)
    is_active = db.Column(db.Boolean, default=True)
    description = db.Column(db.Text)
    created_at = db.Column(db.Text)
    archived = db.Column(db.Boolean, default=False)
    depth = db.Column(db.Integer)
    version = db.Column(db.Integer)

    parent_account = db.relationship('Account', remote_side=[account_id], backref='child_accounts')

class JournalEntry(db.Model):
    __tablename__ = 'journal_entries'
    entry_id = db.Column(db.Integer, primary_key=True)
    entry_date = db.Column(db.Text)
    reference_number = db.Column(db.String(50))
    description = db.Column(db.Text)
    transaction_id = db.Column(db.Integer, db.ForeignKey('financial_transactions.transaction_id'))
    created_by = db.Column(db.Integer)
    created_at = db.Column(db.Text)
    archived = db.Column(db.Boolean, default=False)

    transaction = db.relationship('FinancialTransaction', backref='journal_entries')

class JournalEntryLine(db.Model):
    __tablename__ = 'journal_entry_lines'
    line_id = db.Column(db.Integer, primary_key=True)
    entry_id = db.Column(db.Integer, db.ForeignKey('journal_entries.entry_id'), nullable=False)
    account_id = db.Column(db.Integer, db.ForeignKey('accounts.account_id'), nullable=False)
    debit = db.Column(db.Float, default=0.0)
    credit = db.Column(db.Float, default=0.0)
    currency_id = db.Column(db.Integer, db.ForeignKey('currencies.currency_id'))
    exchange_rate_id = db.Column(db.Integer, db.ForeignKey('exchange_rates.rate_id'))
    description = db.Column(db.String(255))
    created_at = db.Column(db.Text)
    archived = db.Column(db.Boolean, default=False)

    journal_entry = db.relationship('JournalEntry', backref='journal_lines')
    account = db.relationship('Account', backref='account_entries')
    currency = db.relationship('Currency')
    exchange_rate = db.relationship('ExchangeRate')

class Employee(db.Model):
    __tablename__ = 'employees'
    employee_id = db.Column(db.Integer, primary_key=True)
    entity_id = db.Column(db.Integer, db.ForeignKey('entities.entity_id'))
    national_id = db.Column(db.String(20))
    hire_date = db.Column(db.Text)
    termination_date = db.Column(db.Text)
    salary = db.Column(db.Float)
    salary_currency = db.Column(db.Integer, db.ForeignKey('currencies.currency_id'))
    bank_account = db.Column(db.String(50))
    is_active = db.Column(db.Boolean, default=True)
    created_at = db.Column(db.Text)
    archived = db.Column(db.Boolean, default=False)

    entity = db.relationship('Entity', backref='employee_records')
    salary_currency_rel = db.relationship('Currency')
    deductions = db.relationship('EmployeeDeduction', back_populates='employee', overlaps="deduction_records")

class Payroll(db.Model):
    __tablename__ = 'payroll'
    payroll_id = db.Column(db.Integer, primary_key=True)
    employee_id = db.Column(db.Integer, db.ForeignKey('employees.employee_id'))
    pay_period_start = db.Column(db.Text)
    pay_period_end = db.Column(db.Text)
    basic_salary = db.Column(db.Float, default=0.0)
    overtime = db.Column(db.Float, default=0.0)
    bonuses = db.Column(db.Float, default=0.0)
    deductions = db.Column(db.Float, default=0.0)
    net_salary = db.Column(db.Float, default=0.0)
    payment_date = db.Column(db.Text)
    payment_method = db.Column(db.String(50))
    currency_id = db.Column(db.Integer, db.ForeignKey('currencies.currency_id'))
    exchange_rate_id = db.Column(db.Integer, db.ForeignKey('exchange_rates.rate_id'))
    notes = db.Column(db.Text)
    created_by = db.Column(db.Integer)
    created_at = db.Column(db.Text)
    archived = db.Column(db.Boolean, default=False)

    employee = db.relationship('Employee', backref='payrolls')
    currency = db.relationship('Currency')
    exchange_rate = db.relationship('ExchangeRate')

class EmployeeDeduction(db.Model):
    __tablename__ = 'employee_deductions'
    deduction_id = db.Column(db.Integer, primary_key=True)
    employee_id = db.Column(db.Integer, db.ForeignKey('employees.employee_id'))
    deduction_date = db.Column(db.Text)
    amount = db.Column(db.Float, default=0.0)
    deduction_type = db.Column(db.String(50))
    reason = db.Column(db.Text)
    currency_id = db.Column(db.Integer, db.ForeignKey('currencies.currency_id'))
    exchange_rate_id = db.Column(db.Integer, db.ForeignKey('exchange_rates.rate_id'))
    payroll_id = db.Column(db.Integer, db.ForeignKey('payroll.payroll_id'))
    created_by = db.Column(db.Integer)
    created_at = db.Column(db.Text)
    archived = db.Column(db.Boolean, default=False)

    employee = db.relationship('Employee', back_populates='deductions', overlaps="deduction_records")
    currency = db.relationship('Currency')
    exchange_rate = db.relationship('ExchangeRate')
    payroll = db.relationship('Payroll', backref='deduction_records')

class FixedAsset(db.Model):
    __tablename__ = 'fixed_assets'
    asset_id = db.Column(db.Integer, primary_key=True)
    asset_code = db.Column(db.String(20), unique=True)
    asset_name = db.Column(db.String(255))
    category_id = db.Column(db.Integer, db.ForeignKey('categories.category_id'))
    purchase_date = db.Column(db.Text)
    purchase_cost = db.Column(db.Float)
    current_value = db.Column(db.Float)
    useful_life = db.Column(db.Integer)
    salvage_value = db.Column(db.Float)
    depreciation_method = db.Column(db.String(50))
    is_active = db.Column(db.Boolean, default=True)
    location = db.Column(db.String(255))
    notes = db.Column(db.Text)
    created_at = db.Column(db.Text)
    archived = db.Column(db.Boolean, default=False)

    category = db.relationship('Category', backref='assets_in_category')

class Depreciation(db.Model):
    __tablename__ = 'depreciation'
    depreciation_id = db.Column(db.Integer, primary_key=True)
    asset_id = db.Column(db.Integer, db.ForeignKey('fixed_assets.asset_id'))
    depreciation_date = db.Column(db.Text)
    depreciation_amount = db.Column(db.Float)
    accumulated_depreciation = db.Column(db.Float)
    remaining_value = db.Column(db.Float)
    journal_entry_id = db.Column(db.Integer, db.ForeignKey('journal_entries.entry_id'))
    created_by = db.Column(db.Integer)
    created_at = db.Column(db.Text)
    archived = db.Column(db.Boolean, default=False)

    asset = db.relationship('FixedAsset', backref='depreciations')
    journal_entry = db.relationship('JournalEntry', backref='depreciation_entries')

class OperationalExpense(db.Model):
    __tablename__ = 'operational_expenses'
    expense_id = db.Column(db.Integer, primary_key=True)
    expense_date = db.Column(db.Text)
    expense_type = db.Column(db.String(50))
    amount = db.Column(db.Float)
    currency_id = db.Column(db.Integer, db.ForeignKey('currencies.currency_id'))
    exchange_rate_id = db.Column(db.Integer, db.ForeignKey('exchange_rates.rate_id'))
    description = db.Column(db.Text)
    reference_number = db.Column(db.String(50))
    paid_to_entity = db.Column(db.Integer, db.ForeignKey('entities.entity_id'))
    journal_entry_id = db.Column(db.Integer, db.ForeignKey('journal_entries.entry_id'))
    created_by = db.Column(db.Integer)
    created_at = db.Column(db.Text)
    archived = db.Column(db.Boolean, default=False)

    currency = db.relationship('Currency')
    exchange_rate = db.relationship('ExchangeRate')
    paid_to = db.relationship('Entity', backref='expenses')
    journal_entry = db.relationship('JournalEntry', backref='expense_entries')

class DailyWithdrawal(db.Model):
    __tablename__ = 'daily_withdrawals'
    withdrawal_id = db.Column(db.Integer, primary_key=True)
    withdrawal_date = db.Column(db.Text)
    amount = db.Column(db.Float)
    currency_id = db.Column(db.Integer, db.ForeignKey('currencies.currency_id'))
    exchange_rate_id = db.Column(db.Integer, db.ForeignKey('exchange_rates.rate_id'))
    reason = db.Column(db.Text)
    approved_by = db.Column(db.Integer)
    created_by = db.Column(db.Integer)
    created_at = db.Column(db.Text)
    archived = db.Column(db.Boolean, default=False)

    currency = db.relationship('Currency')
    exchange_rate = db.relationship('ExchangeRate')

class Budget(db.Model):
    __tablename__ = 'budgets'
    budget_id = db.Column(db.Integer, primary_key=True)
    budget_name = db.Column(db.String(100))
    budget_period = db.Column(db.String(50))
    start_date = db.Column(db.Text, nullable=False)
    end_date = db.Column(db.Text, nullable=False)
    total_amount = db.Column(db.Float)
    currency_id = db.Column(db.Integer, db.ForeignKey('currencies.currency_id'))
    status = db.Column(db.String(50))
    created_by = db.Column(db.Integer)
    created_at = db.Column(db.Text)
    archived = db.Column(db.Boolean, default=False)

    currency = db.relationship('Currency')

class BudgetDetail(db.Model):
    __tablename__ = 'budget_details'
    detail_id = db.Column(db.Integer, primary_key=True)
    budget_id = db.Column(db.Integer, db.ForeignKey('budgets.budget_id'))
    category_id = db.Column(db.Integer, db.ForeignKey('categories.category_id'))
    allocated_amount = db.Column(db.Float)
    actual_amount = db.Column(db.Float)
    notes = db.Column(db.String(255))
    created_at = db.Column(db.Text)
    archived = db.Column(db.Boolean, default=False)

    budget = db.relationship('Budget', backref='budget_details')
    category = db.relationship('Category', backref='budget_allocations')

class BalanceSheet(db.Model):
    __tablename__ = 'balance_sheets'
    sheet_id = db.Column(db.Integer, primary_key=True)
    report_date = db.Column(db.Text)
    assets_total = db.Column(db.Float)
    liabilities_total = db.Column(db.Float)
    equity_total = db.Column(db.Float)
    net_income = db.Column(db.Float)
    currency_id = db.Column(db.Integer, db.ForeignKey('currencies.currency_id'))
    generated_by = db.Column(db.Integer)
    generated_at = db.Column(db.Text)
    archived = db.Column(db.Boolean, default=False)

    currency = db.relationship('Currency')

class User(db.Model):
    __tablename__ = 'users'
    user_id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(50), unique=True, nullable=False)
    password_hash = db.Column(db.String(255), nullable=False)
    entity_id = db.Column(db.Integer)
    is_active = db.Column(db.Boolean, default=True)
    last_login = db.Column(db.Text)
    created_at = db.Column(db.Text)
    archived = db.Column(db.Boolean, default=False)
    version = db.Column(db.Integer)
    full_name = db.Column(db.String)
    role = db.Column(db.String)
    password = db.Column(db.String)  # حقل مؤقت، يجب إزالته في الإنتاج

class Permission(db.Model):
    __tablename__ = 'permissions'
    permission_id = db.Column(db.Integer, primary_key=True)
    permission_name = db.Column(db.String(50))
    description = db.Column(db.Text)
    module = db.Column(db.String(50))
    action_type = db.Column(db.String(50))
    screen_name = db.Column(db.String(50))
    created_at = db.Column(db.Text)
    archived = db.Column(db.Boolean, default=False)
    user_id = db.Column(db.Integer, db.ForeignKey('users.user_id'))
    can_read = db.Column(db.Boolean, default=False)
    can_write = db.Column(db.Boolean, default=False)
    can_delete = db.Column(db.Boolean, default=False)
    
    assigned_users = db.relationship('UserPermission', backref='permission')

class UserPermission(db.Model):
    __tablename__ = 'user_permissions'
    user_permission_id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.user_id'))
    permission_id = db.Column(db.Integer, db.ForeignKey('permissions.permission_id'))
    granted_at = db.Column(db.Text)
    granted_by = db.Column(db.Integer, db.ForeignKey('users.user_id'))
    archived = db.Column(db.Boolean, default=False)

    user = db.relationship('User', foreign_keys=[user_id], backref='user_permissions')
    granter = db.relationship('User', foreign_keys=[granted_by])

class UserSession(db.Model):
    __tablename__ = 'user_sessions'
    session_id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.user_id'))
    session_token = db.Column(db.String(255))
    login_time = db.Column(db.Text)
    expiry_time = db.Column(db.Text)
    ip_address = db.Column(db.String(45))
    is_active = db.Column(db.Boolean, default=True)
    created_at = db.Column(db.Text)

    user = db.relationship('User', backref='sessions')

class AuditLog(db.Model):
    __tablename__ = 'audit_log'
    log_id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.user_id'))
    action_type = db.Column(db.String(50))
    action_table = db.Column(db.String(50))
    record_id = db.Column(db.Integer)
    action_details = db.Column(db.Text)
    ip_address = db.Column(db.String(45))
    action_timestamp = db.Column(db.Text)
    archived = db.Column(db.Boolean, default=False)

    user = db.relationship('User', backref='audit_logs')

class SystemSetting(db.Model):
    __tablename__ = 'system_settings'
    setting_id = db.Column(db.Integer, primary_key=True)
    setting_key = db.Column(db.String(50))
    setting_value = db.Column(db.Text)
    setting_group = db.Column(db.String(50))
    is_public = db.Column(db.Boolean, default=False)
    description = db.Column(db.String(255))
    updated_at = db.Column(db.Text)
    archived = db.Column(db.Boolean, default=False)

class PriceHistory(db.Model):
    __tablename__ = 'price_history'
    history_id = db.Column(db.Integer, primary_key=True)
    product_id = db.Column(db.Integer, db.ForeignKey('products.product_id'))
    old_price = db.Column(db.Float)
    new_price = db.Column(db.Float)
    change_date = db.Column(db.Text)
    created_by = db.Column(db.Integer)
    archived = db.Column(db.Boolean, default=False)

    product = db.relationship('Product', backref='price_history')

class SchemaChange(db.Model):
    __tablename__ = 'schema_changes'
    change_id = db.Column(db.Integer, primary_key=True)
    change_description = db.Column(db.Text)
    changed_by = db.Column(db.Integer)
    change_date = db.Column(db.Text)
    archived = db.Column(db.Boolean, default=False)

class InitialInventory(db.Model):
    __tablename__ = 'initial_inventory'
    entry_id = db.Column(db.Integer, primary_key=True)
    warehouse_id = db.Column(db.Integer, db.ForeignKey('warehouses.warehouse_id'))
    product_id = db.Column(db.Integer, db.ForeignKey('products.product_id'))
    quantity = db.Column(db.Float)
    unit_cost = db.Column(db.Float)
    entry_date = db.Column(db.Text)
    archived = db.Column(db.Boolean, default=False)

    warehouse = db.relationship('Warehouse', backref='initial_inventory')
    product = db.relationship('Product', backref='initial_inventory')

# ======== وظائف مساعدة لإدارة الصلاحيات ========
def get_all_permissions():
    """الحصول على جميع أسماء الصلاحيات"""
    return [p.permission_name for p in Permission.query.all()]

def load_user_permissions(user_id):
    """تحميل صلاحيات المستخدم من قاعدة البيانات"""
    permissions = {}
    try:
        user_perms = db.session.query(
            Permission.permission_name,
            Permission.can_read,
            Permission.can_write,
            Permission.can_delete
        ).join(UserPermission).filter(
            UserPermission.user_id == user_id,
            UserPermission.archived == False
        ).all()
        
        for perm in user_perms:
            permissions[perm.permission_name] = {
                'can_read': perm.can_read,
                'can_write': perm.can_write,
                'can_delete': perm.can_delete
            }
    except Exception as e:
        app.logger.error(f"خطأ في تحميل الصلاحيات: {e}")
    
    return permissions

# ======== إنشاء Blueprint لإدارة الصلاحيات ========
permissions_bp = Blueprint('permissions', __name__, url_prefix='/auth')

# ======== وظائف المساعدين المحدثة ========

# ===== ديكورات التحقق =====
def role_required(roles):
    def decorator(f):
        @wraps(f)
        def decorated_function(*args, **kwargs):
            if 'user_id' not in session:
                flash('يجب تسجيل الدخول أولاً', 'error')
                return redirect('/login')
            if session.get('role') == 'admin':
                return f(*args, **kwargs)
            user_role = session.get('role')
            if user_role not in roles:
                flash('غير مصرح لك بالوصول إلى هذه الصفحة', 'error')
                return redirect('/')
            return f(*args, **kwargs)
        return decorated_function
    return decorator

def permission_required(permission_name, access_type='read'):
    def decorator(f):
        @wraps(f)
        def decorated_function(*args, **kwargs):
            if 'user_id' not in session:
                flash('يجب تسجيل الدخول أولاً', 'error')
                return redirect('/login')
            if session.get('role') == 'admin':
                return f(*args, **kwargs)
            user_permissions = session.get('permissions', {})
            perm = user_permissions.get(permission_name, {})
            has_access = False
            if access_type == 'read' and perm.get('can_read'):
                has_access = True
            elif access_type == 'write' and perm.get('can_write'):
                has_access = True
            elif access_type == 'delete' and perm.get('can_delete'):
                has_access = True
            if not has_access:
                flash('غير مصرح لك بهذا الإجراء', 'error')
                return redirect('/')
            return f(*args, **kwargs)
        return decorated_function
    return decorator

# ======== صفحة عرض شاشة الصلاحيات ========
@permissions_bp.route('/permissions')
@role_required(['manager', 'admin'])
def permissions_page():
    try:
        csrf_token = generate_csrf()
        return render_template('permissions.html', csrf_token=csrf_token)
    except Exception as e:
        app.logger.error(f"خطأ في عرض صفحة الصلاحيات: {e}", exc_info=True)
        flash('حدث خطأ أثناء تحميل الصفحة', 'error')
        return redirect('/')

# ======== API جلب الشاشات ========
@permissions_bp.route('/api/screens')
@permission_required('can_manage_permissions', 'read')
def api_get_screens():
    try:
        # استبدال الاستعلام لاستخدام النموذج الموجود
        screens = db.session.execute(text("""
            SELECT DISTINCT screen_name, module 
            FROM permissions 
            WHERE archived = 0
        """)).fetchall()
        
        screens_data = [
            {
                'screen_name': s.screen_name,
                'module': s.module
            } for s in screens
        ]
        return jsonify(screens_data)
    except Exception as e:
        app.logger.error(f"خطأ في جلب الشاشات: {e}", exc_info=True)
        return jsonify([]), 500

# ======== API جلب المستخدمين ========
@permissions_bp.route('/api/users')
@permission_required('can_manage_permissions', 'read')
def api_get_users():
    try:
        users = db.session.query(User).filter_by(archived=False, is_active=True).all()
        users_data = [
            {
                'user_id': u.user_id,
                'username': u.username,
                'full_name': u.full_name,
                'role': u.role
            } for u in users
        ]
        return jsonify(users_data)
    except Exception as e:
        app.logger.error(f"خطأ في جلب المستخدمين: {e}", exc_info=True)
        return jsonify([]), 500

# ======== API جلب الصلاحيات ========
@permissions_bp.route('/api/permissions')
@permission_required('can_manage_permissions', 'read')
def api_get_permissions():
    try:
        permissions = db.session.query(Permission).filter_by(archived=False).all()
        permissions_data = [
            {
                'permission_id': p.permission_id,
                'permission_name': p.permission_name,
                'description': p.description,
                'module': p.module,
                'action_type': p.action_type,
                'screen_name': p.screen_name,
                'can_read': p.can_read,
                'can_write': p.can_write,
                'can_delete': p.can_delete,
            } for p in permissions
        ]
        return jsonify(permissions_data)
    except Exception as e:
        app.logger.error(f"خطأ في جلب الصلاحيات: {e}", exc_info=True)
        return jsonify([]), 500

# ======== API جلب صلاحيات مستخدم معين ========
@permissions_bp.route('/api/user-permissions/<int:user_id>')
@permission_required('can_manage_permissions', 'read')
def api_get_user_permissions(user_id):
    try:
        perms = db.session.query(
            Permission.permission_name,
            Permission.screen_name,
            Permission.module
        ).join(UserPermission).filter(
            UserPermission.user_id == user_id,
            UserPermission.archived == False
        ).all()
        
        perms_data = [
            {
                'permission_name': p.permission_name,
                'screen_name': p.screen_name,
                'module': p.module
            } for p in perms
        ]
        return jsonify(perms_data)
    except Exception as e:
        app.logger.error(f"خطأ في جلب صلاحيات المستخدم {user_id}: {e}", exc_info=True)
        return jsonify([]), 500

# ======== API جلب صلاحية محددة ========
@permissions_bp.route('/api/permission/<int:permission_id>')
@permission_required('can_manage_permissions', 'read')
def api_get_permission(permission_id):
    try:
        p = db.session.query(Permission).filter_by(permission_id=permission_id, archived=False).first()
        if not p:
            return jsonify({'error': 'الصلاحية غير موجودة'}), 404
        permission_data = {
            'permission_id': p.permission_id,
            'permission_name': p.permission_name,
            'description': p.description,
            'module': p.module,
            'action_type': p.action_type,
            'screen_name': p.screen_name,
            'can_read': p.can_read,
            'can_write': p.can_write,
            'can_delete': p.can_delete,
        }
        return jsonify(permission_data)
    except Exception as e:
        app.logger.error(f"خطأ في جلب بيانات الصلاحية {permission_id}: {e}", exc_info=True)
        return jsonify({'error': 'حدث خطأ داخلي'}), 500

# ======== API البحث عن صلاحية ========
@permissions_bp.route('/api/permission')
@permission_required('can_manage_permissions', 'read')
def api_search_permission():
    identifier = request.args.get('identifier', '').strip()
    if not identifier:
        return jsonify({'error': 'المعرف مطلوب'}), 400
    try:
        # بحث إما بالمعرف أو بالاسم
        p = db.session.query(Permission).filter(
            (Permission.permission_id == identifier) | (Permission.permission_name == identifier),
            Permission.archived == False
        ).first()
        if not p:
            return jsonify({'error': 'الصلاحية غير موجودة'}), 404
        permission_data = {
            'permission_id': p.permission_id,
            'permission_name': p.permission_name,
            'description': p.description,
            'module': p.module,
            'action_type': p.action_type,
            'screen_name': p.screen_name,
            'can_read': p.can_read,
            'can_write': p.can_write,
            'can_delete': p.can_delete,
        }
        return jsonify(permission_data)
    except Exception as e:
        app.logger.error(f"خطأ في البحث عن الصلاحية: {e}", exc_info=True)
        return jsonify({'error': 'حدث خطأ داخلي'}), 500

# ======== API إنشاء صلاحية جديدة ========
@permissions_bp.route('/api/permission/create', methods=['POST'])
@permission_required('can_manage_permissions', 'write')
def api_create_permission():
    try:
        data = request.get_json()
        validate_csrf(data.get('csrf_token', ''))
        # التحقق من البيانات المطلوبة
        required_fields = ['permission_name', 'module', 'action_type', 'screen_name', 
                           'can_read', 'can_write', 'can_delete']
        if not all(field in data for field in required_fields):
            return jsonify({'success': False, 'message': 'بيانات ناقصة'}), 400
            
        new_perm = Permission(
            permission_name=data['permission_name'],
            description=data.get('description', ''),
            module=data['module'],
            action_type=data['action_type'],
            screen_name=data['screen_name'],
            can_read=bool(data['can_read']),
            can_write=bool(data['can_write']),
            can_delete=bool(data['can_delete']),
            archived=False
        )
        db.session.add(new_perm)
        db.session.commit()
        return jsonify({'success': True, 'message': 'تم إنشاء الصلاحية بنجاح'})
    except CSRFError:
        return jsonify({'success': False, 'message': 'رمز CSRF غير صالح'}), 400
    except Exception as e:
        app.logger.error(f"خطأ في إنشاء الصلاحية: {e}", exc_info=True)
        return jsonify({'success': False, 'message': 'حدث خطأ أثناء إنشاء الصلاحية'}), 500

# ======== API تحديث صلاحية موجودة ========
@permissions_bp.route('/api/permission/update', methods=['POST'])
@permission_required('can_manage_permissions', 'write')
def api_update_permission():
    try:
        data = request.get_json()
        validate_csrf(data.get('csrf_token', ''))
        if 'permission_id' not in data:
            return jsonify({'success': False, 'message': 'معرف الصلاحية مطلوب'}), 400
            
        p = db.session.query(Permission).filter_by(permission_id=data['permission_id'], archived=False).first()
        if not p:
            return jsonify({'success': False, 'message': 'الصلاحية غير موجودة'}), 404
            
        p.permission_name = data.get('permission_name', p.permission_name)
        p.description = data.get('description', p.description)
        p.module = data.get('module', p.module)
        p.action_type = data.get('action_type', p.action_type)
        p.screen_name = data.get('screen_name', p.screen_name)
        p.can_read = bool(data.get('can_read', p.can_read))
        p.can_write = bool(data.get('can_write', p.can_write))
        p.can_delete = bool(data.get('can_delete', p.can_delete))
        
        db.session.commit()
        return jsonify({'success': True, 'message': 'تم تحديث الصلاحية بنجاح'})
    except CSRFError:
        return jsonify({'success': False, 'message': 'رمز CSRF غير صالح'}), 400
    except Exception as e:
        app.logger.error(f"خطأ في تحديث الصلاحية: {e}", exc_info=True)
        return jsonify({'success': False, 'message': 'حدث خطأ أثناء تحديث الصلاحية'}), 500

# ======== API حذف صلاحية ========
@permissions_bp.route('/api/permission/delete/<int:permission_id>', methods=['DELETE'])
@permission_required('can_manage_permissions', 'delete')
def api_delete_permission(permission_id):
    try:
        p = db.session.query(Permission).filter_by(permission_id=permission_id, archived=False).first()
        if not p:
            return jsonify({'success': False, 'message': 'الصلاحية غير موجودة'}), 404
            
        p.archived = True
        db.session.commit()
        return jsonify({'success': True, 'message': 'تم حذف الصلاحية بنجاح'})
    except Exception as e:
        app.logger.error(f"خطأ في حذف الصلاحية: {e}", exc_info=True)
        return jsonify({'success': False, 'message': 'حدث خطأ أثناء حذف الصلاحية'}), 500

# ======== API حفظ صلاحيات الشاشات للمستخدم ========
@permissions_bp.route('/api/screen-access', methods=['POST'])
@permission_required('can_manage_permissions', 'write')
def api_save_screen_access():
    try:
        data = request.get_json()
        validate_csrf(data.get('csrf_token', ''))
        user_id = data.get('user_id')
        screen_permissions = data.get('screen_permissions', [])
        if not user_id or not isinstance(screen_permissions, list):
            return jsonify({'success': False, 'message': 'بيانات غير صحيحة'}), 400
        
        # معالجة حفظ الصلاحيات
        for sp in screen_permissions:
            # البحث عن الصلاحية المرتبطة بهذه الشاشة
            permission = db.session.query(Permission).filter_by(
                screen_name=sp['screen_name'],
                archived=False
            ).first()
            
            if permission and sp['has_access']:
                # التحقق إذا كانت الصلاحية ممنوحة بالفعل
                existing = db.session.query(UserPermission).filter_by(
                    user_id=user_id,
                    permission_id=permission.permission_id,
                    archived=False
                ).first()
                
                if not existing:
                    # منح الصلاحية
                    new_assignment = UserPermission(
                        user_id=user_id,
                        permission_id=permission.permission_id,
                        granted_by=session.get('user_id'),
                        granted_at=get_current_utc_time()
                    )
                    db.session.add(new_assignment)
            elif permission and not sp['has_access']:
                # سحب الصلاحية (أرشفة)
                assignment = db.session.query(UserPermission).filter_by(
                    user_id=user_id,
                    permission_id=permission.permission_id,
                    archived=False
                ).first()
                
                if assignment:
                    assignment.archived = True
        
        db.session.commit()
        return jsonify({'success': True, 'message': 'تم حفظ صلاحيات الشاشات بنجاح'})
    except CSRFError:
        return jsonify({'success': False, 'message': 'رمز CSRF غير صالح'}), 400
    except Exception as e:
        app.logger.error(f"خطأ في حفظ صلاحيات الشاشات: {e}", exc_info=True)
        return jsonify({'success': False, 'message': 'حدث خطأ أثناء حفظ الصلاحيات'}), 500

# ======== معالجات السياق العام ========
@app.context_processor
def inject_global_vars():
    """حقن متغيرات عامة في جميع القوالب"""
    return dict(
        current_year=datetime.now(timezone.utc).year,
        app_name='نظام إدارة المخزون',
        user_permissions=session.get('permissions', {})
    )

# ======== معالجات الأخطاء ========
@app.errorhandler(404)
def page_not_found(e):
    app.logger.warning(f'404 Error: {request.url}')
    return render_template('404.html'), 404

@app.errorhandler(500)
def internal_server_error(e):
    app.logger.error(f'500 Error: {e}', exc_info=True)
    return render_template('500.html'), 500

@app.errorhandler(SQLAlchemyError)
def handle_db_errors(e):
    app.logger.error(f'خطأ في قاعدة البيانات: {e}', exc_info=True)
    flash('حدث خطأ في قاعدة البيانات. يرجى المحاولة مرة أخرى.', 'error')
    return redirect(request.referrer or '/')

@app.errorhandler(CSRFError)
def handle_csrf_error(e):
    app.logger.warning(f'خطأ CSRF: {e.description}')
    flash('انتهت صلاحية الجلسة أو رمز الأمان غير صالح. يرجى إعادة المحاولة.', 'error')
    return redirect(request.referrer or '/login')

# ======== مسارات المستخدم ========

@app.route('/')
def index():
    if 'user_id' in session:
        return redirect('/main')
    return redirect('/login')

@app.route('/test-db')
def test_db():
    """اختبار اتصال قاعدة البيانات"""
    try:
        db.session.execute(text('SELECT 1'))
        return "اتصال قاعدة البيانات ناجح"
    except Exception as e:
        return f"فشل اتصال قاعدة البيانات: {str(e)}"

#@app.route('/get-csrf-token')
#def get_csrf_token():
    """إنشاء وتقديم توكن CSRF"""
#    try:
#        token = generate_csrf()
#        return jsonify({'csrf_token': token})
#    except Exception as e:
#        app.logger.error(f"خطأ في توليد توكن CSRF: {e}", exc_info=True)
#        return jsonify({'error': 'خطأ داخلي في الخادم'}), 500

@app.route('/login', methods=['GET'])
def login_page():
    """صفحة تسجيل الدخول"""
    return render_template('login.html')

@app.route('/login', methods=['POST'])
def login():
    """معالجة تسجيل الدخول"""
    try:
        if not request.is_json:
            return jsonify({'success': False, 'message': 'تنسيق الطلب غير صالح'}), 400

        data = request.get_json(force=True, silent=True) or {}
        username = data.get('username', '').strip()
        password = data.get('password', '')
        remember = data.get('remember', False)
        csrf_token = request.headers.get('X-CSRFToken', '')

        try:
            validate_csrf(csrf_token)
        except CSRFError:
            return jsonify({'success': False, 'message': 'رمز CSRF غير صالح'}), 400

        with db_session() as session_db:
            user = session_db.query(User).filter_by(username=username, archived=False).first()
            
            if not user:
                return jsonify({'success': False, 'message': 'اسم المستخدم أو كلمة المرور غير صحيحة'}), 401
                
            if not check_password_hash(user.password_hash, password):
                return jsonify({'success': False, 'message': 'اسم المستخدم أو كلمة المرور غير صحيحة'}), 401

            if not user.is_active:
                return jsonify({'success': False, 'message': 'تم تعطيل حسابك، راجع الإدارة'}), 403

            user_data = {
                'user_id': user.user_id,
                'username': user.username,
                'full_name': user.full_name,
                'role': user.role
            }

            user.last_login = get_current_utc_time()
            session_db.commit()

        session['user_id'] = user_data['user_id']
        session['username'] = user_data['username']
        session['full_name'] = user_data['full_name']
        session['role'] = user_data['role']
        
        if user_data['role'] == 'admin':
            # جلب جميع أسماء الصلاحيات
            all_perms = [p.permission_name for p in Permission.query.all()]
            session['permissions'] = {perm: {
                'can_read': True,
                'can_write': True,
                'can_delete': True
            } for perm in all_perms}
        else:
            # تحميل صلاحيات المستخدم
            session['permissions'] = load_user_permissions(user_data['user_id'])

        if remember:
            session.permanent = True

        return jsonify({
            'success': True,
            'user': {
                'username': user_data['username'],
                'full_name': user_data['full_name'],
                'role': user_data['role']
            },
            'redirect': '/main'
        })

    except Exception as e:
        app.logger.error(f"خطأ في تسجيل الدخول: {e}", exc_info=True)
        return jsonify({'success': False, 'message': 'حدث خطأ أثناء تسجيل الدخول'}), 500

@app.route('/logout')
def logout():
    """تسجيل الخروج"""
    session.clear()
    flash('تم تسجيل الخروج بنجاح', 'success')
    return redirect('/login')

# ======== الشاشة الرئيسية ========
@app.route('/main')
@role_required(['admin', 'manager', 'user'])
def main_dashboard():
    """لوحة التحكم الرئيسية"""
    try:
        today = datetime.now(timezone.utc).date()
        stats = get_dashboard_stats(today)
        recommendations = get_system_recommendations(today)
        charts = get_dashboard_charts(today)
        top_selling = get_top_selling_products(today)
        top_customers = get_top_customers(today)

        stats['total_sales_today'] = f"{stats['total_sales_today']:,.2f}"
        stats['total_inventory_value'] = f"{stats['total_inventory_value']:,.2f}"

        return render_template(
            "main.html",
            username=session.get('username'),
            full_name=session.get('full_name'),
            role=session.get('role'),
            today=today.isoformat(),
            stats=stats,
            recommendations=recommendations,
            charts=charts,
            top_selling=top_selling,
            top_customers=top_customers
        )

    except Exception as e:
        app.logger.error(f"خطأ غير متوقع في لوحة التحكم: {e}", exc_info=True)
        flash("حدث خطأ غير متوقع في تحضير لوحة التحكم. يرجى إبلاغ الدعم الفني.", "error")
        return redirect('/')

def get_dashboard_stats(today):
    """الحصول على إحصائيات لوحة التحكم"""
    try:
        with db_session() as session_db:
            result = session_db.execute(text("""
                SELECT 
                    (SELECT COUNT(*) FROM products WHERE archived = 0) AS total_products,
                    (SELECT COALESCE(SUM(total_amount), 0) 
                     FROM financial_transactions 
                     WHERE transaction_type = 'sale' AND DATE(transaction_date) = :today) AS total_sales_today,
                    (SELECT COUNT(DISTINCT entity_id) 
                     FROM financial_transactions 
                     WHERE transaction_type = 'sale' AND transaction_date >= DATE(:today, '-30 days')) AS active_customers,
                    (SELECT COUNT(*) 
                     FROM inventory_levels 
                     WHERE expiry_date BETWEEN DATE('now') AND DATE('now', '+30 days')) AS expiry_soon,
                    (SELECT COUNT(*) 
                     FROM inventory_levels il
                     JOIN products p ON il.product_id = p.product_id
                     WHERE il.quantity_on_hand < p.min_stock_level) AS low_stock,
                    (SELECT COUNT(*) 
                     FROM financial_transactions 
                     WHERE due_date BETWEEN DATE('now') AND DATE('now', '+7 days')
                     AND payment_status != 'paid') AS due_soon,
                    (SELECT COALESCE(SUM(il.quantity_on_hand * il.average_cost), 0) 
                     FROM inventory_levels il
                     JOIN products p ON il.product_id = p.product_id) AS total_inventory_value,
                    (SELECT COUNT(*) 
                     FROM stocktakes 
                     WHERE status = 'in_progress') AS pending_tasks,
                    (SELECT COUNT(*) 
                     FROM inventory_movements 
                     WHERE movement_type IN ('damaged', 'returned') 
                     AND DATE(movement_date) = DATE(:today)) AS damaged_returned,
                    (SELECT COALESCE(SUM(current_balance), 0) 
                     FROM entities 
                     WHERE entity_type = 'customer' AND current_balance < 0) AS customer_debts,
                    (SELECT COALESCE(SUM(current_balance), 0) 
                     FROM entities 
                     WHERE entity_type = 'supplier' AND current_balance < 0) AS supplier_debts
            """), {'today': today.isoformat()}).fetchone()
            
            if result:
                return {
                    'total_products': result[0] or 0,
                    'total_sales_today': result[1] or 0,
                    'active_customers': result[2] or 0,
                    'expiry_soon': result[3] or 0,
                    'low_stock': result[4] or 0,
                    'due_soon': result[5] or 0,
                    'total_inventory_value': result[6] or 0,
                    'pending_tasks': result[7] or 0,
                    'damaged_returned': result[8] or 0,
                    'customer_debts': abs(result[9] or 0),
                    'supplier_debts': abs(result[10] or 0)
                }
            return {}
    except Exception as e:
        app.logger.error(f"خطأ في جلب إحصائيات لوحة التحكم: {e}", exc_info=True)
        return {}

@app.route('/api/dashboard-stats')
@role_required(['admin', 'manager', 'user'])
def api_dashboard_stats():
    """نقطة نهاية لإحصائيات لوحة التحكم"""
    try:
        today = datetime.now(timezone.utc).date()
        stats = get_dashboard_stats(today)
        
        stats['products_trend'] = "+12% عن الشهر الماضي"
        stats['sales_trend'] = "+8% عن الأمس"
        
        return jsonify({
            'success': True,
            'data': stats
        })
    except Exception as e:
        app.logger.error(f"خطأ في جلب إحصائيات لوحة التحكم: {e}", exc_info=True)
        return jsonify({
            'success': False,
            'message': 'حدث خطأ في جلب البيانات'
        }), 500

def get_system_recommendations(today):
    """الحصول على التوصيات الذكية للنظام"""
    recommendations = []
    
    try:
        with db_session() as session_db:
            current_month = today.month
            seasonal_products = session_db.query(
                Product.product_id,
                Product.product_name,
                func.sum(func.abs(InventoryMovement.quantity)).label('total_sold')
            ).join(InventoryMovement, Product.product_id == InventoryMovement.product_id
            ).filter(
                InventoryMovement.movement_type == 'sale',
                extract('month', InventoryMovement.movement_date) == current_month
            ).group_by(Product.product_id
            ).order_by(text('total_sold DESC')
            ).limit(3).all()

            for product in seasonal_products:
                inventory = session_db.query(
                    func.sum(InventoryLevel.quantity_on_hand)
                ).filter(
                    InventoryLevel.product_id == product.product_id
                ).scalar() or 0
                
                if inventory < product.total_sold * 0.5:
                    recommendations.append({
                        'type': 'seasonal',
                        'product_id': product.product_id,
                        'product_name': product.product_name,
                        'message': f'زيادة المخزون تحسباً للموسم القادم (مبيعات تاريخية: {int(product.total_sold)})',
                        'priority': 'high'
                    })

            low_stock_products = session_db.query(
                Product.product_id,
                Product.product_name,
                func.sum(InventoryLevel.quantity_on_hand).label('current_qty'),
                Product.min_stock_qty
            ).join(InventoryLevel, Product.product_id == InventoryLevel.product_id
            ).filter(
                InventoryLevel.quantity_on_hand < Product.min_stock_qty * 0.5,
                Product.archived == False
            ).group_by(Product.product_id).limit(3).all()

            for product in low_stock_products:
                recommendations.append({
                    'type': 'low_stock',
                    'product_id': product.product_id,
                    'product_name': product.product_name,
                    'message': f'مخزون منخفض جداً ({product.current_qty} مقابل حد أدنى {product.min_stock_qty})',
                    'priority': 'critical'
                })
                
    except Exception as e:
        app.logger.error(f"خطأ في توليد التوصيات: {e}", exc_info=True)
    
    priority_order = {'critical': 1, 'high': 2, 'medium': 3}
    recommendations.sort(key=lambda x: priority_order.get(x.get('priority', 'medium'), 3))
    
    return recommendations

def get_dashboard_charts(today):
    """الحصول على بيانات المخططات للوحة التحكم"""
    charts = {
        'sales': {'labels': [], 'data': []},
        'stock': {'labels': [], 'data': []}
    }
    
    try:
        with db_session() as session_db:
            week_dates = [today - timedelta(days=i) for i in range(6, -1, -1)]
            sales_data = session_db.query(
                func.date(InventoryMovement.movement_date).label('date'),
                func.sum(InventoryMovement.quantity * InventoryMovement.unit_price).label('total_sales')
            ).filter(
                InventoryMovement.movement_type == 'sale',
                InventoryMovement.movement_date.between(today - timedelta(days=7), today),
                InventoryMovement.archived == False
            ).group_by(func.date(InventoryMovement.movement_date)
            ).all()

            sales_dict = {str(row.date): row.total_sales for row in sales_data}
            for date in week_dates:
                date_str = date.isoformat()
                charts['sales']['labels'].append(date_str)
                charts['sales']['data'].append(float(sales_dict.get(date_str, 0)))

            categories_stock = session_db.query(
                Category.category_name,
                func.sum(InventoryLevel.quantity_on_hand * InventoryLevel.average_cost).label('value')
            ).join(Product, Product.category_id == Category.category_id
            ).join(InventoryLevel, InventoryLevel.product_id == Product.product_id
            ).filter(
                Category.archived == False,
                Product.archived == False,
                InventoryLevel.archived == False
            ).group_by(Category.category_name).limit(8).all()

            for category in categories_stock:
                charts['stock']['labels'].append(category.category_name)
                charts['stock']['data'].append(float(category.value) if category.value else 0)
                
    except Exception as e:
        app.logger.error(f"خطأ في جلب بيانات المخططات: {e}", exc_info=True)
    
    return charts

def get_top_selling_products(today):
    """الحصول على المنتجات الأكثر مبيعاً"""
    top_selling = []
    try:
        with db_session() as session_db:
            top_selling = session_db.query(
                Product.product_name,
                func.sum(func.abs(InventoryMovement.quantity)).label('total_sold')
            ).join(InventoryMovement, Product.product_id == InventoryMovement.product_id
            ).filter(
                InventoryMovement.movement_type == 'sale',
                InventoryMovement.movement_date >= today - timedelta(days=30),
                InventoryMovement.archived == False
            ).group_by(Product.product_name
            ).order_by(text('total_sold DESC')
            ).limit(5).all()
    except Exception as e:
        app.logger.error(f"خطأ في جلب أفضل المنتجات مبيعاً: {e}", exc_info=True)
    
    return top_selling

def get_top_customers(today):
    """الحصول على أفضل العملاء"""
    top_customers = []
    try:
        with db_session() as session_db:
            top_customers = session_db.query(
                Entity.commercial_name,
                func.sum(FinancialTransaction.total_amount).label('total_purchases')
            ).join(FinancialTransaction, FinancialTransaction.entity_id == Entity.entity_id
            ).filter(
                FinancialTransaction.transaction_type == 'sale',
                FinancialTransaction.transaction_date >= today - timedelta(days=30),
                FinancialTransaction.archived == False
            ).group_by(Entity.entity_id
            ).order_by(text('total_purchases DESC')
            ).limit(5).all()
    except Exception as e:
        app.logger.error(f"خطأ في جلب أفضل العملاء: {e}", exc_info=True)
    
    return top_customers


# ======== مسارات شاشة إدارة المستخدمين ========
@app.route('/users/')
@role_required(['admin', 'manager'])
def users_page():
    """صفحة إدارة المستخدمين"""
    try:
        csrf_token = generate_csrf()
        return render_template('users.html', csrf_token=csrf_token)
    except Exception as e:
        app.logger.error(f"خطأ في تحميل صفحة المستخدمين: {e}", exc_info=True)
        flash('حدث خطأ أثناء تحميل الصفحة', 'error')
        return redirect('/')


# ======== مسارات API إدارة المستخدمين ========
users_bp = Blueprint('users', __name__, url_prefix='/api/users')

VALID_ROLES = ['admin', 'manager', 'user']

def json_response(success=True, message=None, data=None, status_code=200):
    response = {'success': success}
    if message:
        response['message'] = message
    if data is not None:
        response['data'] = data
    return jsonify(response), status_code

def validate_password(password):
    if len(password) < 8:
        return False, "كلمة المرور يجب أن تكون 8 أحرف على الأقل"
    if not re.search(r'[A-Z]', password):
        return False, "كلمة المرور يجب أن تحتوي على حرف كبير واحد على الأقل"
    if not re.search(r'[a-z]', password):
        return False, "كلمة المرور يجب أن تحتوي على حرف صغير واحد على الأقل"
    if not re.search(r'\d', password):
        return False, "كلمة المرور يجب أن تحتوي على رقم واحد على الأقل"
    if not re.search(r'[!@#$%^&*]', password):
        return False, "كلمة المرور يجب أن تحتوي على رمز خاص واحد على الأقل"
    return True, ""

def log_audit_action(user_id, action_type, action_table, record_id, details):
    try:
        with db_session() as session_db:
            audit_log = AuditLog(
                user_id=user_id,
                action_type=action_type,
                action_table=action_table,
                record_id=record_id,
                action_details=details,
                ip_address=request.remote_addr,
                action_timestamp=get_current_utc_time(),
                archived=False
            )
            session_db.add(audit_log)
            session_db.commit()
    except Exception as e:
        app.logger.error(f"خطأ في تسجيل النشاط: {e}", exc_info=True)

@users_bp.route('', methods=['GET'])
@permission_required('can_manage_users', 'read')
def api_get_users_main():
    """نقطة نهاية رئيسية لجلب المستخدمين"""
    return api_get_users()

@users_bp.route('/list', methods=['GET'])
@permission_required('can_manage_users', 'read')
def api_get_users():
    """جلب جميع المستخدمين من قاعدة البيانات"""
    try:
        page = request.args.get('page', 1, type=int)
        per_page = request.args.get('per_page', 10, type=int)
        
        with db_session() as session_db:
            users_query = session_db.query(User).filter_by(archived=False)
            pagination = users_query.paginate(page=page, per_page=per_page, error_out=False)
            
            users_data = [{
                'user_id': u.user_id,
                'username': u.username,
                'full_name': u.full_name,
                'role': u.role,
                'is_active': u.is_active,
                'last_login': u.last_login
            } for u in pagination.items]
            
            return json_response(
                success=True,
                data={
                    'users': users_data,
                    'total': pagination.total,
                    'pages': pagination.pages,
                    'current_page': page
                }
            )
    except Exception as e:
        app.logger.error(f"خطأ في جلب المستخدمين: {e}", exc_info=True)
        return json_response(success=False, message="حدث خطأ في جلب البيانات", status_code=500)

@users_bp.route('/<int:user_id>', methods=['GET'])
@permission_required('can_manage_users', 'read')
def api_get_user(user_id):
    """جلب بيانات مستخدم معين"""
    try:
        with db_session() as session_db:
            user = session_db.query(User).get(user_id)
            if not user or user.archived:
                return json_response(success=False, message="المستخدم غير موجود", status_code=404)
            
            return json_response(success=True, data={
                'user_id': user.user_id,
                'username': user.username,
                'full_name': user.full_name,
                'role': user.role,
                'is_active': user.is_active,
                'entity_id': user.entity_id
            })
    except Exception as e:
        app.logger.error(f"خطأ في جلب بيانات المستخدم: {e}", exc_info=True)
        return json_response(success=False, message="حدث خطأ في جلب البيانات", status_code=500)

@users_bp.route('/save', methods=['POST'])
@permission_required('can_manage_users', 'write')
def api_save_user():
    """إنشاء أو تحديث مستخدم"""
    try:
        data = request.get_json()
        validate_csrf(data.get('csrf_token', ''))
        
        user_id = data.get('user_id', 0)
        username = data.get('username', '').strip()
        full_name = data.get('full_name', '').strip()
        role = data.get('role', '').strip()
        is_active = bool(data.get('is_active', True))
        password = data.get('password', '')
        confirm_password = data.get('confirm_password', '')
        
        if not username or not full_name or not role:
            return json_response(success=False, message="جميع الحقول مطلوبة", status_code=400)
        
        if role not in VALID_ROLES:
            return json_response(success=False, message="الدور غير صالح", status_code=400)
        
        if password:
            if password != confirm_password:
                return json_response(success=False, message="كلمة المرور وتأكيدها غير متطابقين", status_code=400)
            is_valid, error_message = validate_password(password)
            if not is_valid:
                return json_response(success=False, message=error_message, status_code=400)
        
        with db_session() as session_db:
            if user_id:
                user = session_db.query(User).get(user_id)
                if not user or user.archived:
                    return json_response(success=False, message="المستخدم غير موجود", status_code=404)
                
                if user.username != username:
                    existing = session_db.query(User).filter(
                        func.lower(User.username) == func.lower(username),
                        User.user_id != user_id,
                        User.archived == False
                    ).first()
                    if existing:
                        return json_response(success=False, message="اسم المستخدم موجود مسبقاً", status_code=400)
                
                user.username = username
                user.full_name = full_name
                user.role = role
                user.is_active = is_active
                if password:
                    user.password_hash = generate_password_hash(password)
                user.updated_at = get_current_utc_time()
                user.version = (user.version or 0) + 1
                
                action_type = 'update'
                message = "تم تحديث المستخدم بنجاح"
                details = f"تحديث المستخدم: {username}, الدور: {role}, الحالة: {is_active}"
            else:
                if not password:
                    return json_response(success=False, message="كلمة المرور مطلوبة لإنشاء مستخدم جديد", status_code=400)
                
                existing = session_db.query(User).filter(
                    func.lower(User.username) == func.lower(username),
                    User.archived == False
                ).first()
                if existing:
                    return json_response(success=False, message="اسم المستخدم موجود مسبقاً", status_code=400)
                
                user = User(
                    username=username,
                    full_name=full_name,
                    role=role,
                    is_active=is_active,
                    password_hash=generate_password_hash(password),
                    created_at=get_current_utc_time(),
                    version=1
                )
                session_db.add(user)
                session_db.flush()
                
                action_type = 'create'
                message = "تم إنشاء المستخدم بنجاح"
                details = f"إنشاء مستخدم جديد: {username}, الدور: {role}"
            
            session_db.commit()
            
            log_audit_action(
                user_id=session.get('user_id'),
                action_type=action_type,
                action_table='users',
                record_id=user.user_id,
                details=details
            )
            
            return json_response(success=True, message=message, data={'user_id': user.user_id})
    except CSRFError:
        return json_response(success=False, message="رمز الحماية غير صالح", status_code=400)
    except Exception as e:
        app.logger.error(f"خطأ في حفظ المستخدم: {e}", exc_info=True)
        return json_response(success=False, message="حدث خطأ أثناء الحفظ", status_code=500)

@users_bp.route('/archive/<int:user_id>', methods=['POST'])
@permission_required('can_manage_users', 'delete')
def api_archive_user(user_id):
    """أرشفة مستخدم (تعطيل)"""
    try:
        validate_csrf(request.get_json().get('csrf_token', ''))
        
        with db_session() as session_db:
            user = session_db.query(User).get(user_id)
            if not user:
                return json_response(success=False, message="المستخدم غير موجود", status_code=404)
                
            if user.user_id == session.get('user_id'):
                return json_response(success=False, message="لا يمكن تعطيل حسابك الخاص", status_code=400)
                
            user.is_active = False
            user.archived = True
            user.updated_at = get_current_utc_time()
            user.version = (user.version or 0) + 1
            
            sessions = session_db.query(UserSession).filter_by(user_id=user_id, is_active=True).all()
            for sess in sessions:
                sess.is_active = False
                sess.expiry_time = get_current_utc_time()
            
            session_db.commit()
            
            log_audit_action(
                user_id=session.get('user_id'),
                action_type='archive',
                action_table='users',
                record_id=user.user_id,
                details=f"أرشفة المستخدم: {user.username}"
            )
            
            return json_response(success=True, message="تم تعطيل المستخدم بنجاح")
    except CSRFError:
        return json_response(success=False, message="رمز الحماية غير صالح", status_code=400)
    except Exception as e:
        app.logger.error(f"خطأ في تعطيل المستخدم: {e}", exc_info=True)
        return json_response(success=False, message="حدث خطأ في التعطيل", status_code=500)

@users_bp.route('/permanent-delete/<int:user_id>', methods=['DELETE'])
@permission_required('can_manage_users', 'delete')
def api_permanent_delete_user(user_id):
    """حذف مستخدم نهائيًا"""
    try:
        with db_session() as session_db:
            user = session_db.query(User).get(user_id)
            if not user:
                return json_response(success=False, message="المستخدم غير موجود", status_code=404)
                
            permissions_count = session_db.query(UserPermission).filter_by(user_id=user_id, archived=False).count()
            active_sessions = session_db.query(UserSession).filter_by(user_id=user_id, is_active=True).count()
            audit_logs = session_db.query(AuditLog).filter_by(user_id=user_id, archived=False).count()
            
            if permissions_count > 0 or active_sessions > 0 or audit_logs > 0:
                return json_response(
                    success=False,
                    message="لا يمكن حذف المستخدم بسبب وجود صلاحيات، جلسات نشطة، أو سجلات تتبع مرتبطة",
                    status_code=400
                )
            
            session_db.delete(user)
            session_db.commit()
            
            log_audit_action(
                user_id=session.get('user_id'),
                action_type='delete',
                action_table='users',
                record_id=user_id,
                details=f"حذف نهائي للمستخدم: {user.username}"
            )
            
            return json_response(success=True, message="تم حذف المستخدم نهائياً بنجاح")
    except Exception as e:
        app.logger.error(f"خطأ في حذف المستخدم: {e}", exc_info=True)
        return json_response(success=False, message="حدث خطأ أثناء الحذف", status_code=500)

@users_bp.route('/permissions/<int:user_id>', methods=['GET'])
@permission_required('can_manage_users', 'read')
def api_get_user_permissions(user_id):
    """جلب صلاحيات مستخدم معين"""
    try:
        permissions = load_user_permissions(user_id)
        perms_data = [{
            'name': perm_name,
            'can_read': details['can_read'],
            'can_write': details['can_write'],
            'can_delete': details['can_delete']
        } for perm_name, details in permissions.items()]
        
        return json_response(success=True, data=perms_data)
    except Exception as e:
        app.logger.error(f"خطأ في جلب الصلاحيات: {e}", exc_info=True)
        return json_response(success=False, message="حدث خطأ في جلب البيانات", status_code=500)

@users_bp.route('/assign-permission', methods=['POST'])
@permission_required('can_manage_users', 'write')
def api_assign_permission():
    """منح صلاحية لمستخدم"""
    try:
        data = request.get_json()
        validate_csrf(data.get('csrf_token', ''))
        
        required_fields = ['user_id', 'permission_id']
        if not all(field in data for field in required_fields):
            return json_response(success=False, message="بيانات ناقصة", status_code=400)
            
        with db_session() as session_db:
            user = session_db.query(User).get(data['user_id'])
            permission = session_db.query(Permission).get(data['permission_id'])
            
            if not user or user.archived:
                return json_response(success=False, message="المستخدم غير موجود", status_code=404)
            if not permission or permission.archived:
                return json_response(success=False, message="الصلاحية غير موجودة", status_code=404)
                
            existing = session_db.query(UserPermission).filter_by(
                user_id=data['user_id'],
                permission_id=data['permission_id'],
                archived=False
            ).first()
            
            if existing:
                return json_response(success=False, message="الصلاحية ممنوحة مسبقاً", status_code=400)
                
            new_assignment = UserPermission(
                user_id=data['user_id'],
                permission_id=data['permission_id'],
                granted_by=session.get('user_id'),
                granted_at=get_current_utc_time(),
                archived=False
            )
            
            session_db.add(new_assignment)
            session_db.commit()
            
            log_audit_action(
                user_id=session.get('user_id'),
                action_type='assign_permission',
                action_table='user_permissions',
                record_id=new_assignment.user_permission_id,
                details=f"منح صلاة {permission.permission_name} للمستخدم {user.username}"
            )
            
            return json_response(success=True, message="تم منح الصلاحية بنجاح")
    except CSRFError:
        return json_response(success=False, message="رمز الحماية غير صالح", status_code=400)
    except Exception as e:
        app.logger.error(f"خطأ في منح الصلاحية: {e}", exc_info=True)
        return json_response(success=False, message="حدث خطأ في العملية", status_code=500)

@users_bp.route('/revoke-permission/<int:assignment_id>', methods=['DELETE'])
@permission_required('can_manage_users', 'write')
def api_revoke_permission(assignment_id):
    """سحب صلاحية من مستخدم"""
    try:
        with db_session() as session_db:
            assignment = session_db.query(UserPermission).get(assignment_id)
            if not assignment:
                return json_response(success=False, message="التخصيص غير موجود", status_code=404)
                
            permission = session_db.query(Permission).get(assignment.permission_id)
            user = session_db.query(User).get(assignment.user_id)
            
            assignment.archived = True
            session_db.commit()
            
            log_audit_action(
                user_id=session.get('user_id'),
                action_type='revoke_permission',
                action_table='user_permissions',
                record_id=assignment_id,
                details=f"سحب صلاحية {permission.permission_name} من المستخدم {user.username}"
            )
            
            return json_response(success=True, message="تم سحب الصلاحية بنجاح")
    except Exception as e:
        app.logger.error(f"خطأ في سحب الصلاحية: {e}", exc_info=True)
        return json_response(success=False, message="حدث خطأ في العمليات", status_code=500)

# ======== مسارات إضافية لمعالجة الأخطاء ========
@app.route('/users')
def redirect_users():
    """تحويل الطلبات القديمة إلى المسار الصحيح"""
    return redirect('/users/')

# ======== تسجيل الـ Blueprints ========
app.register_blueprint(users_bp)

# ======== مسارات إدارة الصلاحيات ========
@permissions_bp.route('/api/permissions', methods=['GET'])
def permissions_get_all():
    try:
        with db_session() as session_db:
            permissions = session_db.query(Permission).filter_by(archived=False).all()
            result = [{
                'permission_id': p.permission_id,
                'permission_name': p.permission_name,
                'description': p.description,
                'module': p.module,
                'action_type': p.action_type,
                'screen_name': p.screen_name,
                'can_read': p.can_read,
                'can_write': p.can_write,
                'can_delete': p.can_delete,
                'created_at': p.created_at
            } for p in permissions]
            
            return jsonify(result), 200
    except Exception as e:
        app.logger.error(f"خطأ في جلب الأذونات: {e}", exc_info=True)
        return jsonify({'error': 'خطأ في الخادم'}), 500

@permissions_bp.route('/api/permission/<int:permission_id>', methods=['GET'])
def permissions_get_one(permission_id):
    try:
        with db_session() as session_db:
            permission = session_db.query(Permission).get(permission_id)
            if not permission or permission.archived:
                return jsonify({'error': 'لم يتم العثور على الصلاحية'}), 404
            
            result = {
                'permission_id': permission.permission_id,
                'permission_name': permission.permission_name,
                'description': permission.description,
                'module': permission.module,
                'action_type': permission.action_type,
                'screen_name': permission.screen_name,
                'can_read': permission.can_read,
                'can_write': permission.can_write,
                'can_delete': permission.can_delete,
                'created_at': permission.created_at
            }
            
            return jsonify(result), 200
    except Exception as e:
        app.logger.error(f"خطأ في جلب الصلاحية: {e}", exc_info=True)
        return jsonify({'error': 'خطأ في الخادم'}), 500

@permissions_bp.route('/api/permission', methods=['GET'])
def permissions_search():
    identifier = request.args.get('identifier', '')
    if not identifier:
        return jsonify({'error': 'يجب تقديم معرّف للبحث'}), 400
    
    try:
        with db_session() as session_db:
            if identifier.isdigit():
                permission = session_db.query(Permission).get(int(identifier))
            else:
                permission = session_db.query(Permission).filter(
                    Permission.permission_name.ilike(f'%{identifier}%'),
                    Permission.archived == False
                ).first()
            
            if not permission:
                return jsonify({'error': 'لم يتم العثور على الصلاحية'}), 404
            
            result = {
                'permission_id': permission.permission_id,
                'permission_name': permission.permission_name,
                'description': permission.description,
                'module': permission.module,
                'action_type': permission.action_type,
                'screen_name': permission.screen_name
            }
            
            return jsonify(result), 200
    except Exception as e:
        app.logger.error(f"خطأ في البحث عن الصلاحية: {e}", exc_info=True)
        return jsonify({'error': 'خطأ في الخادم'}), 500

@permissions_bp.route('/api/permission/create', methods=['POST'])
@permission_required('can_manage_permissions', 'write')
def permissions_create():
    data = request.get_json()
    required_fields = ['permission_name', 'module', 'action_type', 
                       'screen_name', 'can_read', 'can_write', 'can_delete']
    
    if not all(field in data for field in required_fields):
        return jsonify({'error': 'بيانات ناقصة'}), 400
    
    try:
        with db_session() as session_db:
            new_permission = Permission(
                permission_name=data['permission_name'],
                description=data.get('description', ''),
                module=data['module'],
                action_type=data['action_type'],
                screen_name=data['screen_name'],
                can_read=bool(data['can_read']),
                can_write=bool(data['can_write']),
                can_delete=bool(data['can_delete']),
                created_at=get_current_utc_time()
            )
            
            session_db.add(new_permission)
            session_db.commit()
            
            return jsonify({
                'success': True,
                'message': 'تم إنشاء الصلاحية بنجاح',
                'permission_id': new_permission.permission_id
            }), 201
    except Exception as e:
        app.logger.error(f"خطأ في إنشاء الصلاحية: {e}", exc_info=True)
        return jsonify({'error': 'خطأ في الخادم'}), 500

@permissions_bp.route('/api/permission/update', methods=['POST'])
@permission_required('can_manage_permissions', 'write')
def permissions_update():
    data = request.get_json()
    if 'permission_id' not in data:
        return jsonify({'error': 'معرّف الصلاحية مطلوب'}), 400
    
    try:
        with db_session() as session_db:
            permission = session_db.query(Permission).get(data['permission_id'])
            if not permission or permission.archived:
                return jsonify({'error': 'لم يتم العثور على الصلاحية'}), 404
            
            permission.permission_name = data.get('permission_name', permission.permission_name)
            permission.description = data.get('description', permission.description)
            permission.module = data.get('module', permission.module)
            permission.action_type = data.get('action_type', permission.action_type)
            permission.screen_name = data.get('screen_name', permission.screen_name)
            permission.can_read = bool(data.get('can_read', permission.can_read))
            permission.can_write = bool(data.get('can_write', permission.can_write))
            permission.can_delete = bool(data.get('can_delete', permission.can_delete))
            
            session_db.commit()
            
            return jsonify({
                'success': True,
                'message': 'تم تحديث الصلاحية بنجاح'
            }), 200
    except Exception as e:
        app.logger.error(f"خطأ في تحديث الصلاحية: {e}", exc_info=True)
        return jsonify({'error': 'خطأ في الخادم'}), 500

@permissions_bp.route('/api/permission/delete/<int:permission_id>', methods=['DELETE'])
@permission_required('can_manage_permissions', 'delete')
def permissions_delete(permission_id):
    try:
        with db_session() as session_db:
            permission = session_db.query(Permission).get(permission_id)
            if not permission:
                return jsonify({'error': 'لم يتم العثور على الصلاحية'}), 404
            
            permission.archived = True
            session_db.commit()
            
            return jsonify({
                'success': True,
                'message': 'تم أرشفة الصلاحية بنجاح'
            }), 200
    except Exception as e:
        app.logger.error(f"خطأ في حذف الصلاحية: {e}", exc_info=True)
        return jsonify({'error': 'خطأ في الخادم'}), 500

@permissions_bp.route('/api/users', methods=['GET'])
def permissions_list_users():
    try:
        with db_session() as session_db:
            users = session_db.query(User).filter_by(archived=False, is_active=True).all()
            result = [{
                'user_id': u.user_id,
                'username': u.username,
                'full_name': u.full_name,
                'role': u.role
            } for u in users]
            
            return jsonify(result), 200
    except Exception as e:
        app.logger.error(f"خطأ في جلب المستخدمين: {e}", exc_info=True)
        return jsonify({'error': 'خطأ في الخادم'}), 500

@permissions_bp.route('/api/user-permissions/<int:user_id>', methods=['GET'])
def permissions_get_user(user_id):
    try:
        with db_session() as session_db:
            permissions = session_db.query(
                UserPermission, Permission
            ).join(
                Permission, UserPermission.permission_id == Permission.permission_id
            ).filter(
                UserPermission.user_id == user_id,
                UserPermission.archived == False
            ).all()
            
            result = []
            for up, perm in permissions:
                result.append({
                    'user_permission_id': up.user_permission_id,
                    'permission_id': perm.permission_id,
                    'permission_name': perm.permission_name,
                    'screen_name': perm.screen_name,
                    'module': perm.module,
                    'granted_at': up.granted_at,
                    'granted_by': up.granted_by
                })
            
            return jsonify(result), 200
    except Exception as e:
        app.logger.error(f"خطأ في جلب صلاحيات المستخدم: {e}", exc_info=True)
        return jsonify({'error': 'خطأ في الخادم'}), 500

@permissions_bp.route('/api/user-permissions', methods=['POST'])
@permission_required('can_manage_permissions', 'write')
def permissions_assign():
    data = request.get_json()
    required_fields = ['user_id', 'permission_id', 'granted_by']
    
    if not all(field in data for field in required_fields):
        return jsonify({'error': 'بيانات ناقصة'}), 400
    
    try:
        with db_session() as session_db:
            user = session_db.query(User).get(data['user_id'])
            if not user or user.archived:
                return jsonify({'error': 'لم يتم العثور على المستخدم'}), 404
            
            permission = session_db.query(Permission).get(data['permission_id'])
            if not permission or permission.archived:
                return jsonify({'error': 'لم يتم العثور على الصلاحية'}), 404
            
            existing = session_db.query(UserPermission).filter_by(
                user_id=data['user_id'],
                permission_id=data['permission_id'],
                archived=False
            ).first()
            
            if existing:
                return jsonify({'error': 'الصلاحية ممنوحة بالفعل للمستخدم'}), 400
            
            new_assignment = UserPermission(
                user_id=data['user_id'],
                permission_id=data['permission_id'],
                granted_by=data['granted_by'],
                granted_at=get_current_utc_time()
            )
            
            session_db.add(new_assignment)
            session_db.commit()
            
            return jsonify({
                'success': True,
                'message': 'تم منح الصلاحية للمستخدم بنجاح',
                'user_permission_id': new_assignment.user_permission_id
            }), 201
    except Exception as e:
        app.logger.error(f"خطأ في منح الصلاحية: {e}", exc_info=True)
        return jsonify({'error': 'خطأ في الخادم'}), 500

@permissions_bp.route('/api/user-permissions/<int:user_permission_id>', methods=['DELETE'])
@permission_required('can_manage_permissions', 'delete')
def permissions_revoke(user_permission_id):
    try:
        with db_session() as session_db:
            assignment = session_db.query(UserPermission).get(user_permission_id)
            if not assignment:
                return jsonify({'error': 'لم يتم العثور على التخصيص'}), 404
            
            assignment.archived = True
            session_db.commit()
            
            return jsonify({
                'success': True,
                'message': 'تم سحب الصلاحية من المستخدم بنجاح'
            }), 200
    except Exception as e:
        app.logger.error(f"خطأ في سحب الصلاحية: {e}", exc_info=True)
        return jsonify({'error': 'خطأ في الخادم'}), 500

@permissions_bp.route('/api/screens', methods=['GET'])
def permissions_get_screens():
    try:
        with db_session() as session_db:
            screens = session_db.query(
                Permission.screen_name,
                Permission.module
            ).filter_by(
                archived=False
            ).distinct().all()
            
            result = [{
                'screen_name': s.screen_name,
                'module': s.module
            } for s in screens]
            
            return jsonify(result), 200
    except Exception as e:
        app.logger.error(f"خطأ في جلب الشاشات: {e}", exc_info=True)
        return jsonify({'error': 'خطأ في الخادم'}), 500

def check_permission(screen_name):
    def decorator(view_func):
        @wraps(view_func)
        def wrapper(*args, **kwargs):
            if 'user_id' not in session:
                return jsonify({'error': 'يجب تسجيل الدخول'}), 401
            
            user_id = session['user_id']
            
            try:
                with db_session() as session_db:
                    if session.get('role') == 'admin':
                        return view_func(*args, **kwargs)
                    
                    permission_exists = session_db.query(UserPermission).join(
                        Permission, UserPermission.permission_id == Permission.permission_id
                    ).filter(
                        UserPermission.user_id == user_id,
                        Permission.screen_name == screen_name,
                        UserPermission.archived == False,
                        Permission.archived == False
                    ).first()
                    
                    if not permission_exists:
                        return jsonify({
                            'error': 'غير مصرح بالوصول',
                            'message': 'ليست لديك الصلاحية للوصول إلى هذه الشاشة'
                        }), 403
                    
                    return view_func(*args, **kwargs)
            except Exception as e:
                app.logger.error(f"خطأ في التحقق من الصلاحية: {e}", exc_info=True)
                return jsonify({'error': 'خطأ في الخادم'}), 500
        return wrapper
    return decorator

app.register_blueprint(permissions_bp)
#750
# ======== مسارات شاشة إدارة المنتجات ========
@app.route('/product_management')
@permission_required('can_manage_products', 'read')
def product_management():
    try:
        csrf_token = generate_csrf()
        
        with db_session() as session_db:
            categories = session_db.query(
                Category.category_id,
                Category.category_name
            ).filter(Category.archived == False).all()
            
            units = session_db.query(
                Unit.unit_id,
                Unit.unit_name
            ).filter(Unit.archived == False).all()
            
            products = session_db.query(
                Product.product_id,
                Product.product_code,
                Product.product_name,
                Category.category_name,
                Unit.unit_name,
                Product.unit_price,
                Product.min_stock_qty
            ).join(Category, Product.category_id == Category.category_id
            ).join(Unit, Product.unit_id == Unit.unit_id
            ).filter(Product.archived == False).all()
        
        return render_template(
            'product_management.html',
            csrf_token=csrf_token,
            categories=categories,
            units=units,
            products=products
        )
    except Exception as e:
        app.logger.error(f"خطأ في تحميل صفحة إدارة المنتجات: {e}", exc_info=True)
        return render_template('error.html', 
                              error_title="خطأ في تحميل الصفحة",
                              error_message="حدث خطأ أثناء تحميل صفحة إدارة المنتجات",
                              error_details=str(e)), 500

@app.route('/api/products', methods=['GET'])
@permission_required('can_manage_products', 'read')
def api_get_products():
    try:
        with db_session() as session_db:
            products = session_db.query(
                Product.product_id,
                Product.product_code,
                Product.product_name,
                Product.unit_price,
                Product.stock_qty,
                Category.category_name,
                Unit.unit_name,
                Product.min_stock_qty,
                Product.is_active
            ).outerjoin(Category, Product.category_id == Category.category_id
            ).outerjoin(Unit, Product.unit_id == Unit.unit_id
            ).filter(Product.archived == False
            ).all()
            
            products_data = [{
                'id': p.product_id,
                'code': p.product_code,
                'name': p.product_name,
                'price': p.unit_price,
                'stock': p.stock_qty,
                'category': p.category_name,
                'unit': p.unit_name,
                'min_stock': p.min_stock_qty,
                'active': p.is_active
            } for p in products]
            
            return jsonify({
                'success': True,
                'data': products_data
            })
    except Exception as e:
        app.logger.error(f"خطأ في جلب المنتجات: {e}", exc_info=True)
        return jsonify({
            'success': False,
            'message': 'حدث خطأ أثناء جلب بيانات المنتجات'
        }), 500

@app.route('/api/product/<int:product_id>', methods=['GET'])
@permission_required('can_manage_products', 'read')
def api_get_product(product_id):
    try:
        with db_session() as session_db:
            product = session_db.query(
                Product.product_id,
                Product.product_code,
                Product.product_name,
                Product.description,
                Product.unit_price,
                Product.stock_qty,
                Product.min_stock_qty,
                Product.purchase_price,
                Product.is_active,
                Product.is_service,
                Product.has_expiry,
                Product.is_serialized,
                Product.is_batch_tracked,
                Category.category_name.label('category'),
                Unit.unit_name.label('unit')
            ).outerjoin(Category, Product.category_id == Category.category_id
            ).outerjoin(Unit, Product.unit_id == Unit.unit_id
            ).filter(Product.product_id == product_id, Product.archived == False
            ).first()
            
            if not product:
                return jsonify({
                    'success': False,
                    'message': 'المنتج غير موجود'
                }), 404
                
            return jsonify({
                'success': True,
                'data': {
                    'id': product.product_id,
                    'code': product.product_code,
                    'name': product.product_name,
                    'description': product.description,
                    'price': product.unit_price,
                    'stock': product.stock_qty,
                    'min_stock': product.min_stock_qty,
                    'purchase_price': product.purchase_price,
                    'active': product.is_active,
                    'is_service': product.is_service,
                    'has_expiry': product.has_expiry,
                    'is_serialized': product.is_serialized,
                    'is_batch_tracked': product.is_batch_tracked,
                    'category': product.category,
                    'unit': product.unit
                }
            })
    except Exception as e:
        app.logger.error(f"خطأ في جلب بيانات المنتج: {e}", exc_info=True)
        return jsonify({
            'success': False,
            'message': 'حدث خطأ أثناء جلب بيانات المنتج'
        }), 500

@app.route('/api/product/create', methods=['POST'])
@permission_required('can_manage_products', 'write')
def api_create_product():
    try:
        data = request.get_json()
        validate_csrf(data.get('csrf_token', ''))
        
        required_fields = ['code', 'name', 'price', 'category_id', 'unit_id']
        if not all(field in data for field in required_fields):
            return jsonify({
                'success': False,
                'message': 'بيانات ناقصة للمنتج'
            }), 400
            
        with db_session() as session_db:
            existing = session_db.query(Product).filter_by(
                product_code=data['code'],
                archived=False
            ).first()
            
            if existing:
                return jsonify({
                    'success': False,
                    'message': 'كود المنتج موجود مسبقاً'
                }), 400
                
            new_product = Product(
                product_code=data['code'],
                product_name=data['name'],
                description=data.get('description', ''),
                category_id=data['category_id'],
                unit_id=data['unit_id'],
                unit_price=data['price'],
                purchase_price=data.get('purchase_price', 0),
                stock_qty=data.get('stock', 0),
                min_stock_qty=data.get('min_stock', 0),
                is_active=bool(data.get('active', True)),
                is_service=bool(data.get('is_service', False)),
                has_expiry=bool(data.get('has_expiry', False)),
                is_serialized=bool(data.get('is_serialized', False)),
                is_batch_tracked=bool(data.get('is_batch_tracked', False)),
                created_at=get_current_utc_time()
            )
            
            session_db.add(new_product)
            session_db.commit()
            
            app.logger.info(f"تم إنشاء منتج جديد: {new_product.product_name} (ID: {new_product.product_id})")
            
            return jsonify({
                'success': True,
                'message': 'تم إنشاء المنتج بنجاح',
                'product_id': new_product.product_id
            })
    except CSRFError:
        return jsonify({
            'success': False,
            'message': 'رمز CSRF غير صالح'
        }), 400
    except Exception as e:
        app.logger.error(f"خطأ في إنشاء المنتج: {e}", exc_info=True)
        return jsonify({
            'success': False,
            'message': 'حدث خطأ أثناء إنشاء المنتج'
        }), 500

@app.route('/api/product/update/<int:product_id>', methods=['POST'])
@permission_required('can_manage_products', 'write')
def api_update_product(product_id):
    try:
        data = request.get_json()
        validate_csrf(data.get('csrf_token', ''))
        
        with db_session() as session_db:
            product = session_db.query(Product).filter_by(
                product_id=product_id,
                archived=False
            ).first()
            
            if not product:
                return jsonify({
                    'success': False,
                    'message': 'المنتج غير موجود'
                }), 404
                
            old_data = {
                'name': product.product_name,
                'price': product.unit_price,
                'stock': product.stock_qty,
                'min_stock': product.min_stock_qty
            }
                
            product.product_code = data.get('code', product.product_code)
            product.product_name = data.get('name', product.product_name)
            product.description = data.get('description', product.description)
            product.category_id = data.get('category_id', product.category_id)
            product.unit_id = data.get('unit_id', product.unit_id)
            product.unit_price = data.get('price', product.unit_price)
            product.purchase_price = data.get('purchase_price', product.purchase_price)
            product.stock_qty = data.get('stock', product.stock_qty)
            product.min_stock_qty = data.get('min_stock', product.min_stock_qty)
            product.is_active = bool(data.get('active', product.is_active))
            product.is_service = bool(data.get('is_service', product.is_service))
            product.has_expiry = bool(data.get('has_expiry', product.has_expiry))
            product.is_serialized = bool(data.get('is_serialized', product.is_serialized))
            product.is_batch_tracked = bool(data.get('is_batch_tracked', product.is_batch_tracked))
            product.updated_at = get_current_utc_time()
            
            session_db.commit()
            
            changes = []
            if old_data['name'] != product.product_name:
                changes.append(f"الاسم: {old_data['name']} → {product.product_name}")
            if old_data['price'] != product.unit_price:
                changes.append(f"السعر: {old_data['price']} → {product.unit_price}")
            if old_data['stock'] != product.stock_qty:
                changes.append(f"المخزون: {old_data['stock']} → {product.stock_qty}")
            if old_data['min_stock'] != product.min_stock_qty:
                changes.append(f"الحد الأدنى: {old_data['min_stock']} → {product.min_stock_qty}")
                
            if changes:
                app.logger.info(f"تم تحديث المنتج {product.product_code}: {', '.join(changes)}")
            
            return jsonify({
                'success': True,
                'message': 'تم تحديث المنتج بنجاح'
            })
    except CSRFError:
        return jsonify({
            'success': False,
            'message': 'رمز CSRF غير صالح'
        }), 400
    except Exception as e:
        app.logger.error(f"خطأ في تحديث المنتج: {e}", exc_info=True)
        return jsonify({
            'success': False,
            'message': 'حدث خطأ أثناء تحديث المنتج'
        }), 500

@app.route('/api/product/delete/<int:product_id>', methods=['DELETE'])
@permission_required('can_manage_products', 'delete')
def api_delete_product(product_id):
    try:
        with db_session() as session_db:
            product = session_db.query(Product).filter_by(
                product_id=product_id,
                archived=False
            ).first()
            
            if not product:
                return jsonify({
                    'success': False,
                    'message': 'المنتج غير موجود'
                }), 404
                
            app.logger.info(f"تم حذف المنتج: {product.product_name} (ID: {product_id})")
                
            product.archived = True
            product.updated_at = get_current_utc_time()
            session_db.commit()
            
            return jsonify({
                'success': True,
                'message': 'تم حذف المنتج بنجاح'
            })
    except Exception as e:
        app.logger.error(f"خطأ في حذف المنتج: {e}", exc_info=True)
        return jsonify({
            'success': False,
            'message': 'حدث خطأ أثناء حذف المنتج'
        }), 500

@app.route('/api/product/search', methods=['GET'])
@permission_required('can_manage_products', 'read')
def api_search_products():
    query = request.args.get('q', '').strip()
    if not query:
        return jsonify({
            'success': False,
            'message': 'يرجى إدخال مصطلح البحث'
        }), 400
        
    try:
        with db_session() as session_db:
            products = session_db.query(
                Product.product_id,
                Product.product_code,
                Product.product_name,
                Product.unit_price,
                Category.category_name
            ).outerjoin(Category, Product.category_id == Category.category_id
            ).filter(
                or_(
                    Product.product_name.ilike(f'%{query}%'),
                    Product.product_code.ilike(f'%{query}%')
                ),
                Product.archived == False
            ).limit(10).all()
            
            results = [{
                'id': p.product_id,
                'code': p.product_code,
                'name': p.product_name,
                'price': p.unit_price,
                'category': p.category_name
            } for p in products]
            
            return jsonify({
                'success': True,
                'results': results
            })
    except Exception as e:
        app.logger.error(f"خطأ في البحث عن المنتجات: {e}", exc_info=True)
        return jsonify({
            'success': False,
            'message': 'حدث خطأ أثناء البحث'
        }), 500

@app.route('/api/product/options', methods=['GET'])
@permission_required('can_manage_products', 'read')
def api_get_product_options():
    try:
        with db_session() as session_db:
            categories = session_db.query(
                Category.category_id,
                Category.category_name
            ).filter(Category.archived == False).all()
            
            units = session_db.query(
                Unit.unit_id,
                Unit.unit_name
            ).filter(Unit.archived == False).all()
            
            return jsonify({
                'success': True,
                'categories': [{'id': c.category_id, 'name': c.category_name} for c in categories],
                'units': [{'id': u.unit_id, 'name': u.unit_name} for u in units]
            })
    except Exception as e:
        app.logger.error(f"خطأ في جلب خيارات المنتجات: {e}", exc_info=True)
        return jsonify({
            'success': False,
            'message': 'حدث خطأ أثناء جلب الخيارات'
        }), 500

@app.route('/test-products')
def test_products():
    try:
        with db_session() as session_db:
            products = session_db.query(Product).filter_by(archived=False).limit(5).all()
            return jsonify([{
                'id': p.product_id,
                'code': p.product_code,
                'name': p.product_name
            } for p in products])
    except Exception as e:
        return jsonify({'error': str(e)}), 500

# ======== مسارات الشاشة الرئيسية ========
@app.route('/financial_summary')
@permission_required('can_view_reports')
def financial_summary():
    return render_template('financial_summary.html')

# ======== مسارات شاشة التنبيهات والأنشطة ========
@app.route('/alerts_activities')
@permission_required('can_view_reports')
def alerts_activities():
    return render_template('alerts_activities.html')

# ======== مسارات شاشة فئات المنتجات ========
@app.route('/product_categories')
@permission_required('can_manage_categories')
def product_categories():
    try:
        with db_session() as session_db:
            categories = session_db.execute(text("""
                SELECT 
                    c.category_id,
                    c.category_name,
                    c.category_type,
                    c.description,
                    c.tax_rate,
                    c.is_active,
                    p.category_name AS parent_name
                FROM categories c
                LEFT JOIN categories p ON c.parent_category_id = p.category_id
                WHERE c.archived = 0
                ORDER BY c.category_name
            """)).fetchall()
            
            parent_categories = session_db.execute(text("""
                SELECT category_id, category_name 
                FROM categories 
                WHERE archived = 0 AND parent_category_id IS NULL
            """)).fetchall()
            
            return render_template('product_categories.html', 
                                  categories=categories,
                                  all_categories=parent_categories)
    except Exception as e:
        app.logger.error(f"خطأ في جلب فئات المنتجات: {e}", exc_info=True)
        flash('حدث خطأ أثناء جلب البيانات', 'error')
        return render_template('product_categories.html', categories=[], all_categories=[])

# ======== مسارات شاشة وحدات القياس ========
@app.route('/units')
@role_required(['admin', 'manager', 'user'])
def units():
    units = Unit.query.filter_by(archived=False).all()
    return render_template("units.html", units=units)

# ======== مسارات إدارة المخزون ========
@app.route('/inventory')
@permission_required('can_manage_inventory')
def inventory_overview():
    try:
        with db_session() as session_db:
            stats = session_db.execute(text("""
                SELECT 
                    COUNT(DISTINCT p.product_id) AS total_products,
                    COUNT(CASE WHEN il.quantity_on_hand <= 0 THEN 1 END) AS out_of_stock,
                    SUM(il.quantity_on_hand) AS total_quantity,
                    SUM(il.quantity_on_hand * il.average_cost) AS total_value
                FROM inventory_levels il
                JOIN products p ON il.product_id = p.product_id
                WHERE il.archived = 0 AND p.archived = 0
            """)).fetchone()
        
        return render_template("inventory.html", stats=stats)
    except Exception as e:
        app.logger.error(f"خطأ في جلب بيانات المخزون: {e}", exc_info=True)
        flash("❌ حدث خطأ أثناء جلب بيانات المخزون", "error")
        return redirect('/')

# ======== مسارات الحركات المخزنية ========
MOVEMENT_TYPES = {
    'purchase': {'name': 'شراء', 'direction': 1},
    'sale': {'name': 'بيع', 'direction': -1},
    'return': {'name': 'مرتجع', 'direction': 1},
    'damage': {'name': 'تالف', 'direction': -1},
    'adjustment': {'name': 'تعديل', 'direction': 1},
    'transfer': {'name': 'تحويل', 'direction': 0}
}

@app.route('/inventory_movements')
@permission_required('can_manage_inventory')
def inventory_movements():
    try:
        with db_session() as session_db:
            movements = session_db.query(
                InventoryMovement, Product, Warehouse
            ).join(Product, InventoryMovement.product_id == Product.product_id
            ).join(Warehouse, InventoryMovement.warehouse_id == Warehouse.warehouse_id
            ).filter(InventoryMovement.archived == False
            ).order_by(InventoryMovement.movement_date.desc()).all()
            
            for movement, product, warehouse in movements:
                movement.type_name = MOVEMENT_TYPES.get(movement.movement_type, {}).get('name', movement.movement_type)
        
        return render_template("inventory_movements.html", movements=movements)
    except Exception as e:
        app.logger.error(f"خطأ في جلب الحركات المخزنية: {e}", exc_info=True)
        flash("❌ حدث خطأ أثناء جلب بيانات الحركات", "error")
        return redirect('/')

# ======== مسارات شاشة الجرد ========
@app.route('/stocktake')
@permission_required('can_manage_stocktake')
def stocktake():
    return render_template('stocktake.html')

# ======== مسارات التقارير ========
@app.route('/reports')
@permission_required('can_view_reports')
def reports():
    return render_template("reports.html")

@app.route('/low-stock-report')
@permission_required('can_view_reports')
def low_stock_report():
    try:
        with db_session() as session_db:
            alerts = session_db.query(
                Product.product_id,
                Product.product_code,
                Product.product_name,
                Product.min_stock_level,
                InventoryLevel.quantity_on_hand,
                Warehouse.warehouse_name,
                case(
                    [(InventoryLevel.quantity_on_hand <= 0, 'نفاذ')],
                    [(InventoryLevel.quantity_on_hand < Product.min_stock_level, 'تحذير')],
                    else_='طبيعي'
                ).label('alert_level')
            ).join(InventoryLevel, Product.product_id == InventoryLevel.product_id
            ).join(Warehouse, InventoryLevel.warehouse_id == Warehouse.warehouse_id
            ).filter(
                or_(
                    InventoryLevel.quantity_on_hand <= 0,
                    InventoryLevel.quantity_on_hand < Product.min_stock_level
                ),
                Product.archived == False,
                InventoryLevel.archived == False,
                Warehouse.archived == False
            ).order_by(text('alert_level DESC, quantity_on_hand ASC')).all()
        
        return render_template("low_stock_report.html", alerts=alerts)
    except Exception as e:
        app.logger.error(f"خطأ في جلب تقرير المخزون المنخفض: {e}", exc_info=True)
        flash("❌ حدث خطأ أثناء جلب التقرير", "error")
        return redirect('/reports')

#@app.route('/users/')
#def users_page():
#    return render_template('users.html')

# ======== تشغيل التطبيق ========
if __name__ == '__main__':
    os.makedirs(os.path.join(basedir, 'data'), exist_ok=True)
    
    with app.app_context():
        db.create_all()
    
    app.run(host='0.0.0.0', port=5001, debug=True)