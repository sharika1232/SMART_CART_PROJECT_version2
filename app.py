from flask import Flask, render_template, request, redirect, session, flash, jsonify, url_for
from flask_mail import Mail, Message
import sqlite3
from email.mime.text import MIMEText
import smtplib
import bcrypt
import random
import razorpay
import traceback
import config
import os
import requests
import resend
from dotenv import load_dotenv

load_dotenv()

app = Flask(__name__)

# ---------------- SECRET KEY ----------------
app.secret_key = config.SECRET_KEY

# ---------------- ADMIN PROFILE IMAGE FOLDER ----------------
ADMIN_UPLOAD_FOLDER = os.path.join(
    app.root_path,
    "static",
    "uploads",
    "admin_profiles"
)

app.config["ADMIN_UPLOAD_FOLDER"] = ADMIN_UPLOAD_FOLDER
os.makedirs(ADMIN_UPLOAD_FOLDER, exist_ok=True)

# ---------------- PRODUCT IMAGE FOLDER ----------------
UPLOAD_FOLDER = os.path.join(
    app.root_path,
    "static",
    "uploads",
    "product_images"
)

app.config["UPLOAD_FOLDER"] = UPLOAD_FOLDER
os.makedirs(UPLOAD_FOLDER, exist_ok=True)

# ---------------- SQLITE DATABASE PATH ----------------
DATABASE = os.path.join(
    app.root_path,
    "smartcart.db"
)

# ---------------- RAZORPAY ----------------
razorpay_client = razorpay.Client(
    auth=(config.RAZORPAY_KEY_ID, config.RAZORPAY_KEY_SECRET)
)

# ---------------- MAIL CONFIGURATION ----------------
app.config["MAIL_SERVER"] = config.MAIL_SERVER
app.config["MAIL_PORT"] = config.MAIL_PORT
app.config["MAIL_USE_TLS"] = config.MAIL_USE_TLS
app.config["MAIL_USE_SSL"] = config.MAIL_USE_SSL
app.config["MAIL_USERNAME"] = config.MAIL_USERNAME
app.config["MAIL_PASSWORD"] = config.MAIL_PASSWORD
app.config["MAIL_DEFAULT_SENDER"] = config.MAIL_USERNAME

mail = Mail(app)

# ---------------- DATABASE CONNECTION ----------------
def get_db_connection():
    conn = sqlite3.connect(
        DATABASE,
        timeout=20
    )

    # Allows:
    # row["email"]
    # row["admin_id"]
    # row["name"]
    #
    # Similar to MySQL dictionary=True
    conn.row_factory = sqlite3.Row

    # Enable foreign key support
    conn.execute("PRAGMA foreign_keys = ON")

    class ConnectionProxy:
        def __init__(self, real_conn):
            self._conn = real_conn

        def cursor(self, *args, **kwargs):
            real_cur = self._conn.cursor()

            class CursorProxy:
                def __init__(self, cur):
                    self._cur = cur

                def execute(self, query, params=None):
                    if isinstance(query, str) and "%s" in query:
                        query = query.replace("%s", "?")
                    if params is None:
                        return self._cur.execute(query)
                    return self._cur.execute(query, params)

                def executemany(self, query, seq):
                    if isinstance(query, str) and "%s" in query:
                        query = query.replace("%s", "?")
                    return self._cur.executemany(query, seq)

                def __getattr__(self, name):
                    return getattr(self._cur, name)

            return CursorProxy(real_cur)

        def __getattr__(self, name):
            return getattr(self._conn, name)

    return ConnectionProxy(conn)

# ==========================================================
# USER HOME PAGE
# ==========================================================
@app.route("/")
def home():
    return render_template("user/user_home.html")


@app.route('/user-home')
def user_home():
    return redirect(url_for('home'))

@app.route('/admin-home')
def admin_home():
    return render_template('admin/admin_home.html')
# ==========================================================
# ADMIN ABOUT PAGE
# ==========================================================
@app.route("/admin-about")
def admin_about():
    return render_template("admin/admin_about.html")

# ==========================================================
# ADMIN CONTACT
# ==========================================================
@app.route('/admin-contact', methods=['GET', 'POST'])
def admin_contact():

    if request.method == 'POST':

        name = request.form.get('name')
        email = request.form.get('email')
        subject = request.form.get('subject')
        message = request.form.get('message')

        try:
            response = requests.post(
                "https://api.resend.com/emails",
                headers={
                    "Authorization": f"Bearer {os.environ.get('RESEND_API_KEY')}",
                    "Content-Type": "application/json"
                },
                json={
                    "from": "SmartCart <onboarding@resend.dev>",
                    "to": ["YOUR_RESEND_EMAIL@gmail.com"],
                    "subject": subject or f"SmartCart Admin Contact - {name}",
                    "html": f"""
                        <h2>New Admin Contact Message</h2>

                        <p><strong>Name:</strong> {name}</p>
                        <p><strong>Email:</strong> {email}</p>

                        <p><strong>Message:</strong></p>
                        <p>{message}</p>
                    """
                },
                timeout=15
            )

            response.raise_for_status()

            flash(
                "Message sent successfully!",
                "success"
            )

        except Exception as e:

            print(
                "Admin Contact Resend Error:",
                e
            )

            flash(
                "Unable to send message. Please try again.",
                "danger"
            )

        return redirect(
            url_for('admin_contact')
        )

    return render_template(
        "admin/admin_contact.html"
    )

# ==========================================================
# ADMIN SIGNUP
# ==========================================================
@app.route("/admin-signup", methods=["GET", "POST"])
def admin_signup():

    if request.method == "GET":
        return render_template("admin/admin_signup.html")

    name = request.form["name"]
    email = request.form["email"]

    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)

    cursor.execute(
        "SELECT admin_id FROM admin WHERE email=%s",
        (email,)
    )

    existing_admin = cursor.fetchone()

    cursor.close()
    conn.close()

    if existing_admin:
        flash("Email already registered.", "danger")
        return redirect(url_for("admin_signup"))

    session["signup_name"] = name
    session["signup_email"] = email

    otp = random.randint(100000, 999999)
    session["otp"] = otp

    message = Message(
        subject="SmartCart Admin OTP",
        sender=config.MAIL_USERNAME,
        recipients=[email]
    )

    message.body = f"Your OTP is {otp}"

    mail.send(message)

    flash("OTP sent successfully.", "success")

    return redirect(url_for("verify_otp_get"))

# ==========================================================
# VERIFY OTP PAGE
# ==========================================================
@app.route("/verify-otp", methods=["GET"])
def verify_otp_get():
    return render_template("admin/verify-otp.html")

# ==========================================================
# VERIFY OTP + SAVE ADMIN
# ==========================================================
@app.route('/verify-otp', methods=['POST'])
def verify_otp_post():

    user_otp = request.form['otp']
    password = request.form['password']

    # Verify OTP
    if str(session.get('otp')) != str(user_otp):
        flash("Invalid OTP. Try again!", "danger")
        return redirect(url_for('verify_otp_get'))

    # Hash Password
    hashed_password = bcrypt.hashpw(
        password.encode('utf-8'),
        bcrypt.gensalt()
    ).decode('utf-8')

    # Save Admin
    conn = get_db_connection()
    cursor = conn.cursor()

    cursor.execute("""
        INSERT INTO admin(name,email,password)
        VALUES(%s,%s,%s)
    """, (
        session['signup_name'],
        session['signup_email'],
        hashed_password
    ))

    conn.commit()
    cursor.close()
    conn.close()

    # Clear Session
    session.pop('otp', None)
    session.pop('signup_name', None)
    session.pop('signup_email', None)

    flash("Admin Registered Successfully!", "success")
    return redirect(url_for('admin_login'))


# ==========================================================
# ADMIN LOGIN
# ==========================================================
@app.route('/admin-login', methods=['GET', 'POST'])
def admin_login():

    if request.method == 'GET':
        return render_template("admin/admin_login.html")

    email = request.form['email']
    password = request.form['password']

    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)

    cursor.execute(
        "SELECT * FROM admin WHERE email=%s",
        (email,)
    )

    admin = cursor.fetchone()

    cursor.close()
    conn.close()

    if admin is None:
        flash("Email not found!", "danger")
        return redirect(url_for('admin_login'))

    if not bcrypt.checkpw(
        password.encode('utf-8'),
        admin['password'].encode('utf-8')
    ):
        flash("Incorrect Password!", "danger")
        return redirect(url_for('admin_login'))

    session['admin_id'] = admin['admin_id']
    session['admin_name'] = admin['name']
    session['admin_email'] = admin['email']

    flash("Login Successful!", "success")

    return redirect(url_for('admin_dashboard'))


# ==========================================================
# ADMIN DASHBOARD
# ==========================================================
@app.route('/admin-dashboard')
def admin_dashboard():

    if 'admin_id' not in session:
        flash("Please login first!", "danger")
        return redirect(url_for('admin_login'))

    return render_template(
        "admin/dashboard.html",
        admin_name=session['admin_name']
    )


# ==========================================================
# ADMIN LOGOUT
# ==========================================================
@app.route('/admin-logout')
def admin_logout():

    session.clear()

    flash("Logged Out Successfully!", "success")

    return redirect(url_for('admin_login'))


# ==========================================================
# ADD PRODUCT PAGE
# ==========================================================
@app.route('/admin/add-item', methods=['GET'])
def add_item_page():

    if 'admin_id' not in session:
        flash("Please login first!", "danger")
        return redirect(url_for('admin_login'))

    return render_template("admin/add_item.html")


# ==========================================================
# ADD PRODUCT
# ==========================================================
from werkzeug.utils import secure_filename

@app.route('/admin/add-item', methods=['POST'])
def add_item():

    if 'admin_id' not in session:
        flash("Please login first!", "danger")
        return redirect(url_for('admin_login'))

    name = request.form['name']
    description = request.form['description']
    category = request.form['category']
    price = request.form['price']
    image_file = request.files['image']

    if image_file.filename == "":
        flash("Please select an image!", "danger")
        return redirect(url_for('add_item_page'))

    filename = secure_filename(image_file.filename)

    image_path = os.path.join(
        app.config['UPLOAD_FOLDER'],
        filename
    )

    image_file.save(image_path)

    conn = get_db_connection()
    cursor = conn.cursor()

    cursor.execute("""
        INSERT INTO products
        (name,description,category,price,image)
        VALUES(%s,%s,%s,%s,%s)
    """, (
        name,
        description,
        category,
        price,
        filename
    ))

    conn.commit()
    cursor.close()
    conn.close()

    flash("Product Added Successfully!", "success")

    return redirect(url_for('item_list'))


# ==========================================================
# ADMIN PRODUCT LIST
# ==========================================================
@app.route('/admin/item-list')
def item_list():

    if 'admin_id' not in session:
        flash("Please login first!", "danger")
        return redirect(url_for('admin_login'))

    search = request.args.get('search', '')
    category_filter = request.args.get('category', '')

    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)

    # Categories
    cursor.execute("SELECT DISTINCT category FROM products")
    categories = cursor.fetchall()

    # Product Query
    query = "SELECT * FROM products WHERE 1=1"
    params = []

    if search:
        query += " AND name LIKE %s"
        params.append(f"%{search}%")

    if category_filter:
        query += " AND category=%s"
        params.append(category_filter)

    cursor.execute(query, params)
    products = cursor.fetchall()

    cursor.close()
    conn.close()

    return render_template(
        "admin/item_list.html",
        products=products,
        categories=categories,
        search=search,
        category_filter=category_filter
    )


# ==========================================================
# VIEW PRODUCT DETAILS
# ==========================================================
@app.route('/admin/view-item/<int:item_id>')
def view_item(item_id):

    if 'admin_id' not in session:
        flash("Please login first!", "danger")
        return redirect(url_for('admin_login'))

    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)

    cursor.execute(
        "SELECT * FROM products WHERE product_id=%s",
        (item_id,)
    )

    product = cursor.fetchone()

    cursor.close()
    conn.close()

    if not product:
        flash("Product not found!", "danger")
        return redirect(url_for('item_list'))

    return render_template(
        "admin/view_item.html",
        product=product
    )


# ==========================================================
# UPDATE PRODUCT PAGE
# ==========================================================
@app.route('/admin/update-item/<int:item_id>', methods=['GET'])
def update_item_page(item_id):

    if 'admin_id' not in session:
        flash("Please login first!", "danger")
        return redirect(url_for('admin_login'))

    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)

    cursor.execute(
        "SELECT * FROM products WHERE product_id=%s",
        (item_id,)
    )

    product = cursor.fetchone()

    cursor.close()
    conn.close()

    if not product:
        flash("Product not found!", "danger")
        return redirect(url_for('item_list'))

    return render_template(
        "admin/update_item.html",
        product=product
    )


# ==========================================================
# ADMIN FORGOT PASSWORD
# ==========================================================
# ==========================================================
# ADMIN FORGOT PASSWORD
# ==========================================================
@app.route('/admin/forgot-password', methods=['GET', 'POST'])
def admin_forgot_password():

    if request.method == 'GET':
        return render_template("admin/forgot_password.html")

    email = request.form['email']

    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)

    cursor.execute(
        "SELECT * FROM admin WHERE email=%s",
        (email,)
    )

    admin = cursor.fetchone()

    cursor.close()
    conn.close()
    if not admin:
        flash(
            "Email not found! Please register first.",
            "danger"
        )
        return redirect(url_for('admin_forgot_password'))

    otp = random.randint(100000, 999999)

    session['admin_reset_otp'] = otp
    session['admin_reset_email'] = email

    try:
        resend.api_key = os.environ.get("RESEND_API_KEY")

        params = {
            "from": "SmartCart <onboarding@resend.dev>",
            "to": [email],
            "subject": "SmartCart Admin Password Reset OTP",
            "html": f"""
                <h2>SmartCart Admin Password Reset</h2>
                <p>Hello Admin,</p>
                <p>Your password reset OTP is:</p>
                <h1>{otp}</h1>
                <p>Please do not share this OTP with anyone.</p>
            """
        }

        resend.Emails.send(params)

        flash("OTP sent successfully!", "success")

    except Exception as e:
        print("Resend Admin OTP Error:", e)
        flash(f"Mail Error: {e}", "danger")
        return redirect(url_for('admin_forgot_password'))

    return redirect(url_for('admin_reset_password'))


# ==========================================================
# ADMIN RESET PASSWORD
# ==========================================================
# ==========================================================
# ADMIN RESET PASSWORD
# ==========================================================
@app.route('/admin-reset-password', methods=['GET', 'POST'])
def admin_reset_password():

    # -------------------------
    # GET Request
    # -------------------------
    if request.method == 'GET':

        # Reset flow start kakunda direct URL open chesthe
        if not session.get('admin_reset_email'):
            flash(
                "Please request a password reset first.",
                "danger"
            )
            return redirect(
                url_for('admin_forgot_password')
            )

        return render_template(
            "admin/reset_password.html"
        )


    # -------------------------
    # Get Form Data
    # -------------------------
    otp = request.form.get(
        'otp',
        ''
    ).strip()

    new_password = request.form.get(
        'new_password',
        ''
    )

    confirm_password = request.form.get(
        'confirm_password',
        ''
    )


    # -------------------------
    # Get Session Data
    # -------------------------
    stored_otp = session.get(
        'admin_reset_otp'
    )

    admin_email = session.get(
        'admin_reset_email'
    )


    # -------------------------
    # Check Reset Session
    # -------------------------
    if not stored_otp or not admin_email:

        flash(
            "Password reset session expired. Please request a new OTP.",
            "danger"
        )

        return redirect(
            url_for('admin_forgot_password')
        )


    # -------------------------
    # Validate OTP
    # -------------------------
    if str(stored_otp) != str(otp):

        flash(
            "Invalid OTP!",
            "danger"
        )

        return redirect(
            url_for('admin_reset_password')
        )


    # -------------------------
    # Validate Password Fields
    # -------------------------
    if not new_password or not confirm_password:

        flash(
            "Please enter all password fields.",
            "danger"
        )

        return redirect(
            url_for('admin_reset_password')
        )


    # -------------------------
    # Password Length
    # -------------------------
    if len(new_password) < 6:

        flash(
            "Password must be at least 6 characters.",
            "danger"
        )

        return redirect(
            url_for('admin_reset_password')
        )


    # -------------------------
    # Password Match
    # -------------------------
    if new_password != confirm_password:

        flash(
            "Passwords do not match!",
            "danger"
        )

        return redirect(
            url_for('admin_reset_password')
        )


    # -------------------------
    # Hash New Password
    # -------------------------
    hashed_password = bcrypt.hashpw(
        new_password.encode('utf-8'),
        bcrypt.gensalt()
    ).decode('utf-8')


    conn = None
    cursor = None

    try:

        # -------------------------
        # Database Connection
        # -------------------------
        conn = get_db_connection()

        cursor = conn.cursor()


        # -------------------------
        # Update Password
        # -------------------------
        cursor.execute(
            """
            UPDATE admin
            SET password = %s
            WHERE email = %s
            """,
            (
                hashed_password,
                admin_email
            )
        )


        # Check admin exists
        if cursor.rowcount == 0:

            conn.rollback()

            flash(
                "Admin account not found.",
                "danger"
            )

            return redirect(
                url_for('admin_forgot_password')
            )


        # -------------------------
        # Commit Changes
        # -------------------------
        conn.commit()


    except Exception as e:

        if conn:
            conn.rollback()

        print(
            "Admin password reset error:",
            e
        )

        flash(
            "Something went wrong while resetting the password.",
            "danger"
        )

        return redirect(
            url_for('admin_reset_password')
        )


    finally:

        if cursor:
            cursor.close()

        if conn:
            conn.close()


    # -------------------------
    # Clear Reset Session
    # -------------------------
    session.pop(
        'admin_reset_otp',
        None
    )

    session.pop(
        'admin_reset_email',
        None
    )


    # -------------------------
    # Success Message
    # -------------------------
    flash(
        "Password Reset Successfully! Please login with your new password.",
        "success"
    )


    return redirect(
        url_for('admin_login')
    )


# ==========================================================
# UPDATE PRODUCT
# ==========================================================
@app.route('/admin/update-item/<int:item_id>', methods=['POST'])
def update_item(item_id):

    if 'admin_id' not in session:
        flash("Please login first!", "danger")
        return redirect(url_for('admin_login'))

    name = request.form['name']
    description = request.form['description']
    category = request.form['category']
    price = request.form['price']

    new_image = request.files['image']

    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)

    cursor.execute(
        "SELECT * FROM products WHERE product_id=%s",
        (item_id,)
    )

    product = cursor.fetchone()

    if not product:
        cursor.close()
        conn.close()

        flash("Product not found!", "danger")
        return redirect(url_for('item_list'))

    image_name = product['image']

    # Upload New Image
    if new_image and new_image.filename != "":

        from werkzeug.utils import secure_filename

        filename = secure_filename(new_image.filename)

        new_path = os.path.join(
            app.config['UPLOAD_FOLDER'],
            filename
        )

        new_image.save(new_path)

        old_path = os.path.join(
            app.config['UPLOAD_FOLDER'],
            image_name
        )

        if os.path.exists(old_path):
            os.remove(old_path)

        image_name = filename

    cursor.execute("""
        UPDATE products
        SET
            name=%s,
            description=%s,
            category=%s,
            price=%s,
            image=%s
        WHERE product_id=%s
    """,
    (
        name,
        description,
        category,
        price,
        image_name,
        item_id
    ))

    conn.commit()

    cursor.close()
    conn.close()

    flash("Product Updated Successfully!", "success")

    return redirect(url_for('item_list'))

# ==========================================================
# DELETE PRODUCT
# ==========================================================
@app.route('/admin/delete-item/<int:item_id>')
def delete_item(item_id):

    if 'admin_id' not in session:
        flash("Please login first!", "danger")
        return redirect(url_for('admin_login'))

    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)

    # Get Product
    cursor.execute(
        "SELECT * FROM products WHERE product_id=%s",
        (item_id,)
    )
    product = cursor.fetchone()

    if not product:
        cursor.close()
        conn.close()

        flash("Product not found!", "danger")
        return redirect(url_for('item_list'))

    image_name = product['image']

    # Delete Product
    cursor.execute(
        "DELETE FROM products WHERE product_id=%s",
        (item_id,)
    )

    conn.commit()
    cursor.close()
    conn.close()

    # Delete Image
    if image_name:
        image_path = os.path.join(
            app.config['UPLOAD_FOLDER'],
            image_name
        )

        if os.path.exists(image_path):
            os.remove(image_path)

    flash("Product deleted successfully!", "success")

    return redirect(url_for('item_list'))


# ==========================================================
# ADMIN PROFILE PAGE
# ==========================================================
@app.route('/admin/profile')
def admin_profile():

    if 'admin_id' not in session:
        flash("Please login first!", "danger")
        return redirect(url_for('admin_login'))

    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)

    cursor.execute(
        "SELECT * FROM admin WHERE admin_id=%s",
        (session['admin_id'],)
    )

    admin = cursor.fetchone()

    cursor.close()
    conn.close()

    return render_template(
        "admin/admin_profile.html",
        admin=admin
    )


# ==========================================================
# UPDATE ADMIN PROFILE
# ==========================================================
@app.route('/admin/profile', methods=['POST'])
def admin_profile_update():

    if 'admin_id' not in session:
        flash("Please login first!", "danger")
        return redirect(url_for('admin_login'))

    admin_id = session['admin_id']

    name = request.form['name']
    email = request.form['email']
    password = request.form['password']
    profile_image = request.files['profile_image']

    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)

    cursor.execute(
        "SELECT * FROM admin WHERE admin_id=%s",
        (admin_id,)
    )

    admin = cursor.fetchone()

    old_image = admin['profile_image']

    # Password
    if password:
        hashed_password = bcrypt.hashpw(
            password.encode('utf-8'),
            bcrypt.gensalt()
        ).decode('utf-8')
    else:
        hashed_password = admin['password']

    # Image Upload
    if profile_image and profile_image.filename != "":

        from werkzeug.utils import secure_filename

        filename = secure_filename(profile_image.filename)

        save_path = os.path.join(
            app.config['ADMIN_UPLOAD_FOLDER'],
            filename
        )

        profile_image.save(save_path)

        # Delete Old Image
        if old_image:

            old_path = os.path.join(
                app.config['ADMIN_UPLOAD_FOLDER'],
                old_image
            )

            if os.path.exists(old_path):
                os.remove(old_path)

        final_image = filename

    else:
        final_image = old_image

    cursor.execute("""
        UPDATE admin
        SET
            name=%s,
            email=%s,
            password=%s,
            profile_image=%s
        WHERE admin_id=%s
    """,
    (
        name,
        email,
        hashed_password,
        final_image,
        admin_id
    ))

    conn.commit()

    cursor.close()
    conn.close()

    # Update Session
    session['admin_name'] = name
    session['admin_email'] = email

    flash("Profile updated successfully!", "success")

    return redirect(url_for('admin_profile'))

# ==========================================================
# USER ABOUT
# ==========================================================
@app.route('/user-about')
def user_about():
    return render_template("user/user_about.html")

# ==========================================================
# USER CONTACT
# ==========================================================
@app.route('/user-contact', methods=['GET', 'POST'])
def user_contact():

    if request.method == 'POST':

        name = request.form.get('name')
        email = request.form.get('email')
        subject = request.form.get('subject')
        message = request.form.get('message')

        try:
            response = requests.post(
                "https://api.resend.com/emails",
                headers={
                    "Authorization": f"Bearer {os.environ.get('RESEND_API_KEY')}",
                    "Content-Type": "application/json"
                },
                json={
                    "from": "SmartCart <onboarding@resend.dev>",
                    "to": ["ammulucky506@gmail.com"],
                    "subject": subject or f"SmartCart User Contact - {name}",
                    "html": f"""
                        <h2>New User Contact Message</h2>

                        <p><strong>Name:</strong> {name}</p>
                        <p><strong>Email:</strong> {email}</p>

                        <p><strong>Message:</strong></p>
                        <p>{message}</p>
                    """
                },
                timeout=15
            )

            response.raise_for_status()

            flash(
                "Message sent successfully!",
                "success"
            )

        except Exception as e:

            print(
                "User Contact Resend Error:",
                e
            )

            flash(
                "Unable to send message. Please try again.",
                "danger"
            )

        return redirect(
            url_for('user_contact')
        )

    return render_template(
        "user/user_contact.html"
    )

# ==========================================================
# USER REGISTER
# ==========================================================
@app.route('/user-register', methods=['GET', 'POST'])
def user_register():

    if request.method == 'GET':
        return render_template("user/user_register.html")

    name = request.form['name']
    email = request.form['email']
    password = request.form['password']

    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)

    cursor.execute(
        "SELECT * FROM users WHERE email=%s",
        (email,)
    )

    user = cursor.fetchone()

    if user:
        cursor.close()
        conn.close()

        flash("Email already registered!", "danger")
        return redirect(url_for('user_register'))

    hashed_password = bcrypt.hashpw(
        password.encode('utf-8'),
        bcrypt.gensalt()
    ).decode('utf-8')

    cursor.execute("""
        INSERT INTO users(name,email,password)
        VALUES(%s,%s,%s)
    """,
    (
        name,
        email,
        hashed_password
    ))

    conn.commit()

    cursor.close()
    conn.close()

    flash("Registration Successful!", "success")

    return redirect(url_for('user_login'))


# ==========================================================
# USER LOGIN
# ==========================================================
@app.route('/user-login', methods=['GET', 'POST'])
def user_login():

    if request.method == 'GET':
        return render_template("user/user_login.html")

    email = request.form['email']
    password = request.form['password']

    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)

    cursor.execute(
        "SELECT * FROM users WHERE email=%s",
        (email,)
    )

    user = cursor.fetchone()

    cursor.close()
    conn.close()

    if not user:
        flash("Email not found!", "danger")
        return redirect(url_for('user_login'))

    if not bcrypt.checkpw(
        password.encode('utf-8'),
        user['password'].encode('utf-8')
    ):
        flash("Incorrect password!", "danger")
        return redirect(url_for('user_login'))

    session['user_id'] = user['user_id']
    session['user_name'] = user['name']
    session['user_email'] = user['email']

    flash("Login Successful!", "success")

    return redirect(url_for('user_dashboard'))

# ==========================================================
# USER DASHBOARD
# ==========================================================
@app.route('/user-dashboard')
def user_dashboard():

    if 'user_id' not in session:
        flash("Please login first!", "danger")
        return redirect(url_for('user_login'))

    return render_template(
        "user/user_dashboard.html",
        user_name=session['user_name']
    )


# ==========================================================
# USER LOGOUT
# ==========================================================
@app.route('/user-logout')
def user_logout():

    session.pop('user_id', None)
    session.pop('user_name', None)
    session.pop('user_email', None)

    flash("Logged out successfully!", "success")

    return redirect(url_for('user_login'))


# ==========================================================
# USER FORGOT PASSWORD
# ==========================================================
@app.route('/user-forgot-password', methods=['GET', 'POST'])
def user_forgot_password():

    if request.method == 'GET':
        return render_template("user/forgot_password.html")

    email = request.form['email']

    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)

    cursor.execute(
        "SELECT * FROM users WHERE email=%s",
        (email,)
    )

    user = cursor.fetchone()

    cursor.close()
    conn.close()

    if not user:
        flash("Email not found! Please register first.", "danger")
        return redirect(url_for('user_forgot_password'))

    # Generate OTP
            # Generate OTP
    otp = random.randint(100000, 999999)

    session['reset_otp'] = otp
    session['reset_email'] = email

    try:
        response = requests.post(
            "https://api.resend.com/emails",
            headers={
                "Authorization": f"Bearer {os.environ.get('RESEND_API_KEY')}",
                "Content-Type": "application/json"
            },
            json={
                "from": "SmartCart <onboarding@resend.dev>",
                "to": [email],
                "subject": "SmartCart Password Reset OTP",
                "html": f"""
                <h2>SmartCart Password Reset</h2>
                <p>Your OTP is:</p>
                <h1>{otp}</h1>
                <p>Do not share this OTP with anyone.</p>
                """
            },
            timeout=15
        )

        response.raise_for_status()
        flash("OTP sent successfully!", "success")

    except Exception as e:
        print("Resend error:", e)
        flash(f"Mail Error: {e}", "danger")
        return redirect(url_for('user_forgot_password'))

    return redirect(url_for('user_reset_password'))

    return redirect(url_for('user_reset_password'))


# ==========================================================
# USER RESET PASSWORD
# ==========================================================
@app.route('/user-reset-password', methods=['GET', 'POST'])
def user_reset_password():

    if request.method == 'GET':

        if 'reset_email' not in session:
            flash("Please request password reset first!", "danger")
            return redirect(url_for('user_forgot_password'))

        return render_template("user/reset_password.html")

    otp = request.form['otp']
    password = request.form['password']
    confirm_password = request.form['confirm_password']

    # Verify OTP
    if str(session.get('reset_otp')) != str(otp):
        flash("Invalid OTP!", "danger")
        return redirect(url_for('user_reset_password'))

    # Password Match
    if password != confirm_password:
        flash("Passwords do not match!", "danger")
        return redirect(url_for('user_reset_password'))

    hashed_password = bcrypt.hashpw(
        password.encode('utf-8'),
        bcrypt.gensalt()
    ).decode('utf-8')

    conn = get_db_connection()
    cursor = conn.cursor()

    cursor.execute(
        "UPDATE users SET password=%s WHERE email=%s",
        (
            hashed_password,
            session['reset_email']
        )
    )

    conn.commit()

    cursor.close()
    conn.close()

    # Clear Session
    session.pop('reset_otp', None)
    session.pop('reset_email', None)

    flash("Password reset successfully! Please login.", "success")

    return redirect(url_for('user_login'))

# ==========================================================
# USER PRODUCTS
# ==========================================================
@app.route('/user/products')
def user_products():

    if 'user_id' not in session:
        flash("Please login to view products!", "danger")
        return redirect(url_for('user_login'))

    search = request.args.get('search', '')
    category_filter = request.args.get('category', '')

    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)

    # Categories
    cursor.execute("SELECT DISTINCT category FROM products")
    categories = cursor.fetchall()

    # Search Query
    query = "SELECT * FROM products WHERE 1=1"
    params = []

    if search:
        query += " AND name LIKE %s"
        params.append(f"%{search}%")

    if category_filter:
        query += " AND category=%s"
        params.append(category_filter)

    cursor.execute(query, params)
    products = cursor.fetchall()

    cursor.close()
    conn.close()

    return render_template(
        "user/user_products.html",
        products=products,
        categories=categories,
        search=search,
        category_filter=category_filter
    )


# ==========================================================
# PRODUCT DETAILS
# ==========================================================
@app.route('/user/product/<int:product_id>')
def user_product_details(product_id):

    if 'user_id' not in session:
        flash("Please login first!", "danger")
        return redirect(url_for('user_login'))

    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)

    cursor.execute(
        "SELECT * FROM products WHERE product_id=%s",
        (product_id,)
    )

    product = cursor.fetchone()

    cursor.close()
    conn.close()

    if not product:
        flash("Product not found!", "danger")
        return redirect(url_for('user_products'))

    return render_template(
        "user/product_details.html",
        product=product
    )


# ==========================================================
# ADD TO CART
# ==========================================================
@app.route('/user/add-to-cart/<int:product_id>')
def add_to_cart(product_id):

    if 'user_id' not in session:
        flash("Please login first!", "danger")
        return redirect(url_for('user_login'))

    if 'cart' not in session:
        session['cart'] = {}

    cart = session['cart']

    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)

    cursor.execute(
        "SELECT * FROM products WHERE product_id=%s",
        (product_id,)
    )

    product = cursor.fetchone()

    cursor.close()
    conn.close()

    if not product:
        flash("Product not found!", "danger")
        return redirect(url_for('user_products'))

    pid = str(product_id)

    if pid in cart:
        cart[pid]['quantity'] += 1
    else:
        cart[pid] = {
            "name": product["name"],
            "price": float(product["price"]),
            "image": product["image"],
            "quantity": 1
        }

    session['cart'] = cart
    session.modified = True

    flash("Item added to cart successfully!", "success")

    return redirect(url_for('view_cart'))


# ==========================================================
# VIEW CART
# ==========================================================
@app.route('/user/cart')
def view_cart():

    if 'user_id' not in session:
        flash("Please login first!", "danger")
        return redirect(url_for('user_login'))

    cart = session.get('cart', {})

    grand_total = sum(
        item['price'] * item['quantity']
        for item in cart.values()
    )

    return render_template(
        "user/cart.html",
        cart=cart,
        grand_total=grand_total
    )


# ==========================================================
# INCREASE QUANTITY
# ==========================================================
@app.route('/user/cart/increase/<pid>')
def increase_quantity(pid):

    if 'user_id' not in session:
        return redirect(url_for('user_login'))

    cart = session.get('cart', {})

    if pid in cart:
        cart[pid]['quantity'] += 1

    session['cart'] = cart
    session.modified = True

    return redirect(url_for('view_cart'))


# ==========================================================
# DECREASE QUANTITY
# ==========================================================
@app.route('/user/cart/decrease/<pid>')
def decrease_quantity(pid):

    if 'user_id' not in session:
        return redirect(url_for('user_login'))

    cart = session.get('cart', {})

    if pid in cart:

        cart[pid]['quantity'] -= 1

        if cart[pid]['quantity'] <= 0:
            del cart[pid]

    session['cart'] = cart
    session.modified = True

    return redirect(url_for('view_cart'))

# ==========================================================
# BUY NOW
# ==========================================================
@app.route('/user/buy-now/<int:product_id>', methods=['GET'])
def user_buy_now(product_id):

    if 'user_id' not in session:
        flash("Please login first!", "danger")
        return redirect(url_for('user_login'))

    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)

    cursor.execute(
        "SELECT * FROM products WHERE product_id=%s",
        (product_id,)
    )
    product = cursor.fetchone()

    cursor.execute(
        "SELECT * FROM addresses WHERE user_id=%s LIMIT 1",
        (session['user_id'],)
    )
    address = cursor.fetchone()

    cursor.close()
    conn.close()

    if not product:
        flash("Product not found!", "danger")
        return redirect(url_for('user_products'))

    return render_template(
        "user/checkout.html",
        product=product,
        address=address,
        user_name=session.get("user_name")
    )


# ==========================================================
# ADD ADDRESS
# ==========================================================
@app.route('/user/add-address', methods=['GET', 'POST'])
def add_address():

    if 'user_id' not in session:
        flash("Please login first!", "danger")
        return redirect(url_for('user_login'))

    if request.method == 'GET':
        return render_template("user/add_address.html")

    full_name = request.form['full_name']
    phone = request.form['phone']
    address = request.form['address']
    city = request.form['city']
    state = request.form['state']
    pincode = request.form['pincode']

    conn = get_db_connection()
    cursor = conn.cursor()

    cursor.execute("""
        INSERT INTO addresses
        (user_id, full_name, phone, address, city, state, pincode)
        VALUES (%s,%s,%s,%s,%s,%s,%s)
    """,
    (
        session['user_id'],
        full_name,
        phone,
        address,
        city,
        state,
        pincode
    ))

    conn.commit()

    cursor.close()
    conn.close()

    flash("Address added successfully!", "success")

    return redirect(url_for('view_address'))


# ==========================================================
# VIEW ADDRESS
# ==========================================================
@app.route('/user/address')
def view_address():

    if 'user_id' not in session:
        flash("Please login first!", "danger")
        return redirect(url_for('user_login'))

    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)

    cursor.execute(
        "SELECT * FROM addresses WHERE user_id=%s",
        (session['user_id'],)
    )

    addresses = cursor.fetchall()

    cursor.close()
    conn.close()

    return render_template(
        "user/address_list.html",
        addresses=addresses
    )


# ==========================================================
# CHECKOUT
# ==========================================================
@app.route('/checkout/<int:product_id>')
def checkout(product_id):

    if 'user_id' not in session:
        flash("Please login first!", "danger")
        return redirect(url_for('user_login'))

    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)

    cursor.execute(
        "SELECT * FROM products WHERE product_id=%s",
        (product_id,)
    )

    product = cursor.fetchone()

    cursor.execute(
        "SELECT * FROM addresses WHERE user_id=%s LIMIT 1",
        (session['user_id'],)
    )

    address = cursor.fetchone()

    cursor.close()
    conn.close()

    if not product:
        flash("Product not found!", "danger")
        return redirect(url_for('user_products'))

    return render_template(
        "user/checkout.html",
        product=product,
        address=address,
        user_name=session.get("user_name")
    )
# =================================================================
# ROUTE: CREATE RAZORPAY ORDER
# =================================================================
# ==========================================================
# USER PAYMENT
# ==========================================================
@app.route('/user/pay')
def user_pay():

    if 'user_id' not in session:
        flash("Please login first!", "danger")
        return redirect(url_for('user_login'))

    cart = session.get('cart', {})

    if not cart:
        flash("Your cart is empty!", "danger")
        return redirect(url_for('user_products'))

    total_amount = sum(
        item['price'] * item['quantity']
        for item in cart.values()
    )

    razorpay_amount = int(total_amount * 100)

    razorpay_order = razorpay_client.order.create({
        "amount": razorpay_amount,
        "currency": "INR",
        "payment_capture": 1
    })

    session['razorpay_order_id'] = razorpay_order['id']

    return render_template(
        "user/payment.html",
        amount=total_amount,
        key_id=config.RAZORPAY_KEY_ID,
        order_id=razorpay_order['id']
    )


# ==========================================================
# PAYMENT SUCCESS
# ==========================================================
@app.route('/payment-success')
def payment_success():

    payment_id = request.args.get("payment_id")
    order_id = request.args.get("order_id")

    if not payment_id:
        flash("Payment Failed!", "danger")
        return redirect(url_for('view_cart'))

    return render_template(
        "user/payment_success.html",
        payment_id=payment_id,
        order_id=order_id
    )


# ==========================================================
# PROCESS SELECTED ITEMS
# ==========================================================
@app.route('/process_selection', methods=['POST'])
def process_selection():

    selected_ids = request.form.getlist('selected_items')

    if not selected_ids:
        flash("Please select at least one item.", "danger")
        return redirect(url_for('view_cart'))

    return f"Selected Items: {', '.join(selected_ids)}"


# ==========================================================
# VERIFY PAYMENT
# ==========================================================
@app.route('/verify-payment', methods=['POST'])
def verify_payment():

    if 'user_id' not in session:
        flash("Please login first!", "danger")
        return redirect(url_for('user_login'))

    razorpay_payment_id = request.form.get('razorpay_payment_id')
    razorpay_order_id = request.form.get('razorpay_order_id')
    razorpay_signature = request.form.get('razorpay_signature')

    if not (
        razorpay_payment_id
        and razorpay_order_id
        and razorpay_signature
    ):
        flash("Payment verification failed!", "danger")
        return redirect(url_for('view_cart'))

    payload = {
        "razorpay_order_id": razorpay_order_id,
        "razorpay_payment_id": razorpay_payment_id,
        "razorpay_signature": razorpay_signature
    }

    try:
        razorpay_client.utility.verify_payment_signature(payload)

    except Exception as e:

        app.logger.error(str(e))

        flash("Payment verification failed.", "danger")

        return redirect(url_for('view_cart'))

    cart = session.get('cart', {})

    if not cart:
        flash("Cart is empty.", "danger")
        return redirect(url_for('user_products'))

    total_amount = sum(
        item['price'] * item['quantity']
        for item in cart.values()
    )

    conn = get_db_connection()
    cursor = conn.cursor()

    try:

        first_product_id = int(next(iter(cart.keys())))
        first_item = next(iter(cart.values()))

        cursor.execute("""
            INSERT INTO orders
            (
                user_id,
                product_id,
                quantity,
                total_price,
                status,
                razorpay_order_id,
                razorpay_payment_id
            )
            VALUES(%s,%s,%s,%s,%s,%s,%s)
        """,
        (
            session['user_id'],
            first_product_id,
            first_item['quantity'],
            total_amount,
            "Paid",
            razorpay_order_id,
            razorpay_payment_id
        ))

        order_id = cursor.lastrowid

        for pid, item in cart.items():

            cursor.execute("""
                INSERT INTO order_items
                (
                    order_id,
                    product_id,
                    product_name,
                    quantity,
                    price
                )
                VALUES(%s,%s,%s,%s,%s)
            """,
            (
                order_id,
                int(pid),
                item['name'],
                item['quantity'],
                item['price']
            ))

        conn.commit()

        session.pop('cart', None)
        session.pop('razorpay_order_id', None)

        flash("Order placed successfully!", "success")

        return redirect(url_for('order_success', order_id=order_id))

    except Exception as e:

        conn.rollback()

        app.logger.error(traceback.format_exc())

        flash("Unable to save order.", "danger")

        return redirect(url_for('view_cart'))

    finally:

        cursor.close()
        conn.close()

# ==========================================================
# USER ORDERS
# ==========================================================
@app.route('/user/orders')
def user_orders():

    if 'user_id' not in session:
        flash("Please login first!", "danger")
        return redirect(url_for('user_login'))

    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)

    cursor.execute("""
        SELECT *, created_at AS order_date
        FROM orders
        WHERE user_id=?
        ORDER BY order_id DESC
    """, (session['user_id'],))

    orders = cursor.fetchall()

    cursor.close()
    conn.close()

    return render_template(
        "user/my_orders.html",
        orders=orders
    )


# ==========================================================
# ORDER SUCCESS
# ==========================================================
@app.route('/user/order-success/<int:order_id>')
def order_success(order_id):

    if 'user_id' not in session:
        flash("Please login first!", "danger")
        return redirect(url_for('user_login'))

    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)

    cursor.execute(
        "SELECT *, created_at AS order_date FROM orders WHERE order_id=? AND user_id=?",
        (order_id, session['user_id'])
    )
    order = cursor.fetchone()

    if not order:
        cursor.close()
        conn.close()

        flash("Order not found!", "danger")
        return redirect(url_for('user_products'))

    cursor.execute(
        "SELECT * FROM order_items WHERE order_id=%s",
        (order_id,)
    )

    items = cursor.fetchall()

    cursor.close()
    conn.close()

    return render_template(
        "user/order_success.html",
        order=order,
        items=items
    )


# ==========================================================
# INVOICE PAGE
@app.route('/user/invoice/<int:order_id>')
def invoice(order_id):

    if 'user_id' not in session:
        flash("Please login first!", "danger")
        return redirect(url_for('user_login'))

    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)

    cursor.execute(
        "SELECT *, created_at AS order_date FROM orders WHERE order_id=? AND user_id=?",
        (order_id, session['user_id'])
    )
    order = cursor.fetchone()

    if not order:
        cursor.close()
        conn.close()

        flash("Invoice not found!", "danger")
        return redirect(url_for('user_orders'))

    cursor.execute(
        "SELECT * FROM order_items WHERE order_id=%s",
        (order_id,)
    )
    items = cursor.fetchall()

    cursor.close()
    conn.close()

    return render_template(
        "user/invoice.html",
        order=order,
        items=items
    )


# ==========================================================
# MY ORDERS
# ==========================================================
@app.route('/user/my-orders')
def my_orders():

    if 'user_id' not in session:
        flash("Please login first!", "danger")
        return redirect(url_for('user_login'))

    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)

    cursor.execute("""
        SELECT *, created_at AS order_date
        FROM orders
        WHERE user_id=?
        ORDER BY order_date DESC
    """, (session['user_id'],))

    orders = cursor.fetchall()

    cursor.close()
    conn.close()

    return render_template(
        "user/my_orders.html",
        orders=orders
    )


# ==========================================================
# EDIT ADDRESS
# ==========================================================
@app.route('/user/edit-address/<int:address_id>', methods=['GET', 'POST'])
def edit_address(address_id):

    if 'user_id' not in session:
        flash("Please login first!", "danger")
        return redirect(url_for('user_login'))

    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)

    if request.method == "POST":

        cursor.execute("""
            UPDATE addresses
            SET
                full_name=%s,
                phone=%s,
                address=%s,
                city=%s,
                state=%s,
                pincode=%s
            WHERE address_id=%s
        """,
        (
            request.form['full_name'],
            request.form['phone'],
            request.form['address'],
            request.form['city'],
            request.form['state'],
            request.form['pincode'],
            address_id
        ))

        conn.commit()

        cursor.close()
        conn.close()

        flash("Address updated successfully!", "success")

        return redirect(url_for('view_address'))

    cursor.execute(
        "SELECT * FROM addresses WHERE address_id=%s",
        (address_id,)
    )

    address = cursor.fetchone()

    cursor.close()
    conn.close()

    return render_template(
        "user/edit_address.html",
        address=address
    )


# ==========================================================
# DELETE ADDRESS
# ==========================================================
@app.route('/user/delete-address/<int:address_id>')
def delete_address(address_id):

    if 'user_id' not in session:
        flash("Please login first!", "danger")
        return redirect(url_for('user_login'))

    conn = get_db_connection()
    cursor = conn.cursor()

    cursor.execute(
        "DELETE FROM addresses WHERE address_id=%s",
        (address_id,)
    )

    conn.commit()

    cursor.close()
    conn.close()

    flash("Address deleted successfully!", "success")

    return redirect(url_for('view_address'))


# ==========================================================
# RUN APPLICATION
# ==========================================================
if __name__ == '__main__':
    app.run(debug=True)
