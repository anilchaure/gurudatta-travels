import os
from datetime import datetime
from flask import Flask, render_template, redirect, url_for, flash, request
from flask_sqlalchemy import SQLAlchemy
from flask_login import LoginManager, UserMixin, login_user, logout_user, login_required, current_user
from werkzeug.security import generate_password_hash, check_password_hash
from werkzeug.utils import secure_filename

app = Flask(__name__)

# --- CONFIGURATION ---
app.config['SECRET_KEY'] = os.environ.get('SECRET_KEY', 'gurudatta-travels-2026-secure-key')

# DATABASE LOGIC: Uses Render's Database if available, otherwise local SQLite
db_url = os.environ.get('DATABASE_URL', 'sqlite:///gurudatta_agency.db')
if db_url.startswith("postgres://"):
    db_url = db_url.replace("postgres://", "postgresql://", 1)
app.config['SQLALCHEMY_DATABASE_URI'] = db_url
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

# IMAGE UPLOAD CONFIG
UPLOAD_FOLDER = os.path.join('static', 'uploads')
app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER
ALLOWED_EXTENSIONS = {'png', 'jpg', 'jpeg'}

if not os.path.exists(UPLOAD_FOLDER):
    os.makedirs(UPLOAD_FOLDER)

db = SQLAlchemy(app)
login_manager = LoginManager(app)
login_manager.login_view = 'login'

# --- MODELS ---
class User(db.Model, UserMixin):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(50), unique=True, nullable=False)
    password = db.Column(db.String(255), nullable=False)
    role = db.Column(db.String(20), default='customer') 
    bookings = db.relationship('Booking', backref='customer', lazy=True)

class Destination(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    location = db.Column(db.String(100), nullable=False)
    description = db.Column(db.Text)
    best_season = db.Column(db.String(50))
    is_active = db.Column(db.Boolean, default=True)
    packages = db.relationship('Package', backref='dest', cascade="all, delete-orphan", lazy=True)

class Package(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    duration = db.Column(db.String(50)) 
    price = db.Column(db.Float, nullable=False)
    max_capacity = db.Column(db.Integer, nullable=False)
    image_file = db.Column(db.String(100), default='default.jpg')
    dest_id = db.Column(db.Integer, db.ForeignKey('destination.id'))
    bookings = db.relationship('Booking', backref='pkg', cascade="all, delete-orphan", lazy=True)

class Booking(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'))
    package_id = db.Column(db.Integer, db.ForeignKey('package.id'))
    travelers = db.Column(db.Integer, nullable=False)
    total_price = db.Column(db.Float)
    status = db.Column(db.String(20), default='Pending') 
    date_booked = db.Column(db.DateTime, default=datetime.utcnow)

@login_manager.user_loader
def load_user(user_id):
    return User.query.get(int(user_id))

def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

# --- ROUTES ---
@app.route('/')
def index():
    active_packages = Package.query.join(Destination).filter(Destination.is_active == True).all()
    return render_template('index.html', packages=active_packages)

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        user = User.query.filter_by(username=request.form.get('username')).first()
        if user and check_password_hash(user.password, request.form.get('password')):
            login_user(user)
            return redirect(url_for('admin_dashboard') if user.role == 'admin' else url_for('index'))
        flash('Invalid Credentials', 'danger')
    return render_template('login.html')

@app.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        hashed_pw = generate_password_hash(request.form.get('password'))
        new_user = User(username=request.form.get('username'), password=hashed_pw)
        db.session.add(new_user)
        db.session.commit()
        return redirect(url_for('login'))
    return render_template('register.html')

@app.route('/logout')
def logout():
    logout_user()
    return redirect(url_for('index'))

@app.route('/admin/dashboard')
@login_required
def admin_dashboard():
    if current_user.role != 'admin': return redirect(url_for('index'))
    revenue = db.session.query(db.func.sum(Booking.total_price)).filter_by(status='Confirmed').scalar() or 0
    popular = db.session.query(Destination.name, db.func.count(Booking.id)).select_from(Destination).join(Package).join(Booking).group_by(Destination.id).order_by(db.func.count(Booking.id).desc()).first()
    popular_dest = popular[0] if popular else "No Bookings"
    bookings = Booking.query.order_by(Booking.date_booked.desc()).all()
    return render_template('admin/dashboard.html', revenue=revenue, count=Booking.query.count(), popular=popular_dest, bookings=bookings)

@app.route('/admin/add-destination', methods=['GET', 'POST'])
@login_required
def add_destination():
    if request.method == 'POST':
        dest = Destination(name=request.form.get('name'), location=request.form.get('location'), description=request.form.get('description'), best_season=request.form.get('best_season'))
        db.session.add(dest)
        db.session.commit()
        return redirect(url_for('admin_dashboard'))
    return render_template('admin/add_destination.html')

@app.route('/admin/add-package', methods=['GET', 'POST'])
@login_required
def add_package():
    dests = Destination.query.all()
    if request.method == 'POST':
        file = request.files.get('image')
        filename = 'default.jpg'
        if file and allowed_file(file.filename):
            filename = secure_filename(file.filename)
            file.save(os.path.join(app.config['UPLOAD_FOLDER'], filename))
        
        pkg = Package(name=request.form.get('name'), duration=request.form.get('duration'), price=float(request.form.get('price')), max_capacity=int(request.form.get('capacity')), dest_id=int(request.form.get('dest_id')), image_file=filename)
        db.session.add(pkg)
        db.session.commit()
        return redirect(url_for('admin_dashboard'))
    return render_template('admin/add_package.html', destinations=dests)

@app.route('/book/<int:pkg_id>', methods=['POST'])
@login_required
def book_package(pkg_id):
    pkg = Package.query.get_or_404(pkg_id)
    num = int(request.form.get('travelers', 1))
    booking = Booking(user_id=current_user.id, package_id=pkg_id, travelers=num, total_price=pkg.price * num)
    db.session.add(booking)
    db.session.commit()
    flash('Booking request submitted!', 'success')
    return redirect(url_for('my_bookings'))

@app.route('/my-bookings')
@login_required
def my_bookings():
    bookings = Booking.query.filter_by(user_id=current_user.id).all()
    return render_template('customer_dash.html', bookings=bookings)

@app.route('/admin/confirm/<int:id>')
@login_required
def confirm_booking(id):
    booking = Booking.query.get(id)
    booking.status = 'Confirmed'
    db.session.commit()
    return redirect(url_for('admin_dashboard'))

# --- STARTUP ---
if __name__ == '__main__':
    with app.app_context():
        db.create_all()
        # Seed Admin
        if not User.query.filter_by(username='admin').first():
            admin = User(username='admin', password=generate_password_hash('admin123'), role='admin')
            db.session.add(admin)
            db.session.commit()
    
    # RENDER COMPATIBLE PORT LOGIC
    port = int(os.environ.get("PORT", 5000))
    app.run(host='0.0.0.0', port=port)