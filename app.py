from flask import Flask, render_template, request, redirect, url_for
from flask_sqlalchemy import SQLAlchemy
from flask_login import LoginManager, UserMixin, login_user, logout_user, login_required, current_user
from werkzeug.security import generate_password_hash, check_password_hash
from datetime import datetime
from collections import defaultdict
import csv
import os
from io import StringIO
from flask import Response


app = Flask(__name__)
basedir = os.path.abspath(os.path.dirname(__file__))
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///' + os.path.join(basedir, 'expenses.db')
app.config['SECRET_KEY'] = 'secret-key'
db = SQLAlchemy(app)

# Setup login manager
login_manager = LoginManager()
login_manager.login_view = 'login'
login_manager.init_app(app)

# User model
class User(UserMixin, db.Model):
    id = db.Column(db.Integer, primary_key=True)
    email = db.Column(db.String(100), unique=True, nullable=False)
    password = db.Column(db.String(100), nullable=False)

# Expense model
class Expense(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    date = db.Column(db.Date, default=datetime.utcnow)
    category = db.Column(db.String(50), nullable=False)
    description = db.Column(db.String(200))
    amount = db.Column(db.Float, nullable=False)

# Income model
class Income(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    month = db.Column(db.String(7), nullable=False)  # Format: YYYY-MM
    amount = db.Column(db.Float, nullable=False)


@login_manager.user_loader
def load_user(user_id):
    return User.query.get(int(user_id))

@app.route('/')
@login_required
def index():
    category_filter = request.args.get('category')
    start_date = request.args.get('start_date')
    end_date = request.args.get('end_date')

    # Start with all user expenses
    query = Expense.query.filter_by(user_id=current_user.id)

    # Apply filters
    if category_filter and category_filter != 'all':
        query = query.filter_by(category=category_filter)

    if start_date:
        query = query.filter(Expense.date >= datetime.strptime(start_date, '%Y-%m-%d'))
    if end_date:
        query = query.filter(Expense.date <= datetime.strptime(end_date, '%Y-%m-%d'))

    expenses = query.order_by(Expense.date.desc()).all()
    total_expenses = sum(exp.amount for exp in expenses)

    # Income
    today = datetime.today()
    current_month = today.strftime('%Y-%m')
    income_entry = Income.query.filter_by(user_id=current_user.id, month=current_month).first()
    income = income_entry.amount if income_entry else 0.0
    savings = income - total_expenses

    # Pie chart data
    category_totals = defaultdict(float)
    for exp in expenses:
        category_totals[exp.category] += exp.amount

    labels = list(category_totals.keys())
    values = list(category_totals.values())

    # Get all categories for dropdown
    all_categories = db.session.query(Expense.category).filter_by(user_id=current_user.id).distinct().all()
    all_categories = [c[0] for c in all_categories]

    return render_template('index.html', expenses=expenses, total=total_expenses,
                           income=income, savings=savings,
                           labels=labels, values=values,
                           all_categories=all_categories)

@app.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        email = request.form['email']
        password = request.form['password']
        user = User.query.filter_by(email=email).first()
        if user:
            return 'User already exists!'
        hashed_pw = generate_password_hash(password, method='pbkdf2:sha256')
        new_user = User(email=email, password=hashed_pw)
        db.session.add(new_user)
        db.session.commit()
        return redirect('/login')
    return render_template('register.html')

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        email = request.form['email']
        password = request.form['password']
        user = User.query.filter_by(email=email).first()
        if user and check_password_hash(user.password, password):
            login_user(user)
            return redirect('/')
        return 'Invalid credentials'
    return render_template('login.html')

@app.route('/logout')
@login_required
def logout():
    logout_user()
    return redirect('/login')

@app.route('/add_expense', methods=['GET', 'POST'])
@login_required
def add_expense():
    if request.method == 'POST':
        date = request.form['date']
        category = request.form['category']
        description = request.form['description']
        amount = float(request.form['amount'])

        new_expense = Expense(
            user_id=current_user.id,
            date=datetime.strptime(date, '%Y-%m-%d'),
            category=category,
            description=description,
            amount=amount
        )
        db.session.add(new_expense)
        db.session.commit()
        return redirect('/')
    return render_template('add_expense.html')

@app.route('/add_income', methods=['GET', 'POST'])
@login_required
def add_income():
    if request.method == 'POST':
        month = request.form['month']
        amount = float(request.form['amount'])

        existing = Income.query.filter_by(user_id=current_user.id, month=month).first()
        if existing:
            existing.amount = amount
        else:
            new_income = Income(user_id=current_user.id, month=month, amount=amount)
            db.session.add(new_income)

        db.session.commit()
        return redirect('/')
    return render_template('add_income.html')

@app.route('/edit_expense/<int:id>', methods=['GET', 'POST'])
@login_required
def edit_expense(id):
    expense = Expense.query.get_or_404(id)
    if expense.user_id != current_user.id:
        return "Unauthorized", 403

    if request.method == 'POST':
        expense.date = datetime.strptime(request.form['date'], '%Y-%m-%d')
        expense.category = request.form['category']
        expense.description = request.form['description']
        expense.amount = float(request.form['amount'])

        db.session.commit()
        return redirect('/')

    return render_template('edit_expense.html', expense=expense)

@app.route('/delete_expense/<int:id>')
@login_required
def delete_expense(id):
    expense = Expense.query.get_or_404(id)
    if expense.user_id != current_user.id:
        return "Unauthorized", 403

    db.session.delete(expense)
    db.session.commit()
    return redirect('/')

@app.route('/export_csv')
@login_required
def export_csv():
    # Get user's expenses
    expenses = Expense.query.filter_by(user_id=current_user.id).order_by(Expense.date.desc()).all()

    # Create CSV in memory
    si = StringIO()
    writer = csv.writer(si)
    writer.writerow(['Date', 'Category', 'Description', 'Amount'])

    for exp in expenses:
        writer.writerow([exp.date.strftime('%Y-%m-%d'), exp.category, exp.description, exp.amount])

    output = si.getvalue()
    si.close()

    # Return as downloadable file
    return Response(
        output,
        mimetype='text/csv',
        headers={"Content-disposition": "attachment; filename=expenses.csv"}
    )

if __name__ == '__main__':
    with app.app_context():
        db.create_all()
    app.run(debug=True)
