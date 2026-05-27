from dotenv import load_dotenv
import pymysql
import os
import hashlib
from flask import Flask, render_template, request, redirect, session, url_for, flash
from functools import wraps

load_dotenv()

# Match your exact layout image where templates and static files live in the same root folder
BASE_DIR = os.path.dirname(os.path.abspath(__file__))

app = Flask(
    __name__,
    template_folder=os.path.join(BASE_DIR, "templates"),
    static_folder=BASE_DIR,      # Crucial fix: style.css is directly in your root folder!
    static_url_path=""           # Allows direct access to root static elements
)

app.secret_key = os.getenv("SECRET_KEY", "ccs_key_nexus_secret_key_2026")

# ─── SECURE AIVEN CLOUD SERVER CONFIGURATIONS ──────────────────────────
DB_HOST = os.getenv("MYSQLHOST", "mysql-2a3b32b8-riddikdeleon62-6e4a.c.aivencloud.com")
DB_USER = os.getenv("MYSQLUSER", "avnadmin")
DB_PASSWORD = os.getenv("MYSQLPASSWORD", "AVNS_yFHdFftkeZK6H5dGIip")
DB_NAME = os.getenv("MYSQLDATABASE", "defaultdb") 
DB_PORT = int(os.getenv("MYSQLPORT", 11031))


def get_db_connection():
    """Establishes a secure connection directly to your live cloud database cluster."""
    try:
        connection = pymysql.connect(
            host=DB_HOST,
            user=DB_USER,
            password=DB_PASSWORD,
            database=DB_NAME,
            port=DB_PORT,
            cursorclass=pymysql.cursors.DictCursor,
            ssl={'ssl': {}} # Secure verification layer required by Aiven Cloud
        )
        return connection
    except pymysql.MySQLError as e:
        print(f"❌ CLOUD DATABASE CONNECTION CRITICAL ERROR: {e}")
        return None

def login_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'username' not in session:
            return redirect(url_for('index'))
        return f(*args, **kwargs)
    return decorated_function


# HOME / LOGIN ROUTE PORTAL
@app.route('/')
def index():
    if 'username' in session:
        return redirect(url_for('dashboard'))
    return render_template('login.html')


@app.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        name = request.form.get('name')
        age = request.form.get('age')
        gmail = request.form.get('gmail')
        username = request.form.get('username')
        raw_password = request.form.get('pass') 
        role = request.form.get('role')

        hashed_password = hashlib.sha256(raw_password.encode('utf-8')).hexdigest()

        print(f"DEBUG REGISTER: Trying to register username '{username}'...")

        conn = get_db_connection()
        if conn:
            try:
                with conn.cursor() as cursor:
                    cursor.execute(
                        """
                        INSERT INTO users (name, age, gmail, username, password, role)
                        VALUES (%s,%s,%s,%s,%s,%s)
                        """,
                        (name, age, gmail, username, hashed_password, role)
                    )
                    conn.commit()
                    print(f"✅ DEBUG REGISTER: Successfully inserted '{username}' into cloud database!")
                    flash("Account registered successfully! Please log in.", "success")
            except pymysql.MySQLError as e:
                print(f"❌ DEBUG REGISTER ERROR: SQL Insertion Failed: {e}")
                flash(f"Database registration error: {e}", "error")
            finally:
                conn.close()
        else:
            print("❌ DEBUG REGISTER ERROR: Cloud database server unreachable.")
            flash("Database server is currently unreachable.", "error")

        return redirect(url_for('index'))

    return render_template('register.html')


@app.route('/login', methods=['POST'])
def login():
    username = request.form.get('username')
    password = request.form.get('password')

    incoming_hashed_password = hashlib.sha256(password.encode('utf-8')).hexdigest()

    print(f"DEBUG LOGIN: Attempting login for username '{username}'...")

    conn = get_db_connection()
    if conn:
        try:
            with conn.cursor() as cursor:
                cursor.execute("SELECT * FROM users WHERE username=%s", (username,))
                user = cursor.fetchone()

                if user:
                    print(f"DEBUG LOGIN: Found user tracking row for '{username}'. Checking password hash match...")
                    if user['password'] == incoming_hashed_password:
                        print(f"✅ DEBUG LOGIN: Password verified for '{username}'! Setting session tokens.")
                        session['user_id'] = user['id']
                        session['username'] = user['username']
                        session['role'] = user['role']
                        return redirect(url_for('dashboard'))
                    else:
                        print("❌ DEBUG LOGIN FAILED: Entered password hash does not match cloud database record.")
                        flash("Incorrect password. Please try again.", "error")
                else:
                    print(f"❌ DEBUG LOGIN FAILED: Username '{username}' does not exist in the cloud database.")
                    flash("Username not found. Please register first.", "error")
        except pymysql.MySQLError as e:
            print(f"❌ DEBUG LOGIN ERROR: Cloud database operation crashed: {e}")
            flash(f"Internal login database error: {e}", "error")
        finally:
            conn.close()
    else:
        print("❌ DEBUG LOGIN ERROR: Cloud database link completely offline.")
        flash("Database offline. Could not complete verification.", "error")

    return redirect(url_for('index'))


@app.route('/dashboard')
@login_required
def dashboard():
    pending_requests = []
    user_requests = []
    pending_count = 0
    items = []

    conn = get_db_connection()
    if conn:
        try:
            with conn.cursor() as cursor:
                cursor.execute(
                    "SELECT id, pname AS name, quantity, created_at FROM items ORDER BY id DESC"
                )
                items = cursor.fetchall()

                if session.get('role') == 'admin':
                    cursor.execute("""
                        SELECT
                            r.id,
                            r.name,
                            r.quantity,
                            r.status,
                            r.created_at,
                            u.username AS requester
                        FROM item_requests r
                        JOIN users u ON r.user_id = u.id
                        WHERE r.status='pending'
                        ORDER BY r.created_at DESC
                    """)
                    pending_requests = cursor.fetchall()
                    pending_count = len(pending_requests)
                else:
                    cursor.execute("""
                        SELECT
                            id,
                            name,
                            quantity,
                            status,
                            created_at
                        FROM item_requests
                        WHERE user_id=%s
                        ORDER BY created_at DESC
                    """, (session.get('user_id'),))
                    user_requests = cursor.fetchall()
        except pymysql.MySQLError as e:
            print(f"Dashboard Data Pull Failure: {e}")
        finally:
            conn.close()

    return render_template(
        'dashboard.html',
        items=items,
        pending_requests=pending_requests,
        user_requests=user_requests,
        pending_count=pending_count
    )



@app.route('/add', methods=['GET', 'POST'])
@login_required
def add():
    if session.get('role') != 'admin':
        return redirect(url_for('dashboard'))
        
    if request.method == 'POST':
        pname = request.form.get('pname')  
        quantity = request.form.get('quantity')
        
        conn = get_db_connection()
        if conn:
            try:
                with conn.cursor() as cursor:
                    cursor.execute("INSERT INTO items (pname, quantity) VALUES (%s, %s)", (pname, quantity))
                    conn.commit()
            except pymysql.MySQLError as e:
                print(f"Failed to add inventory item: {e}")
            finally:
                conn.close()
        return redirect(url_for('dashboard'))
        
    return render_template('add.html')  


@app.route('/edit/<int:item_id>', methods=['GET', 'POST'])
@login_required
def edit(item_id):
    if session.get('role') != 'admin':
        return redirect(url_for('dashboard'))
        
    conn = get_db_connection()
    item = None
    
    if request.method == 'POST':
        pname = request.form.get('pname')  
        quantity = request.form.get('quantity')
        if conn:
            try:
                with conn.cursor() as cursor:
                    cursor.execute("UPDATE items SET pname=%s, quantity=%s WHERE id=%s", (pname, quantity, item_id))
                    conn.commit()
            except pymysql.MySQLError as e:
                print(f"Update execution failure: {e}")
            finally:
                conn.close()
        return redirect(url_for('dashboard'))

    if conn:
        try:
            with conn.cursor() as cursor:
                cursor.execute("SELECT id, pname AS name, quantity FROM items WHERE id=%s", (item_id,))
                item = cursor.fetchone()
        finally:
            conn.close()
            
    return render_template('edit.html', item=item)


@app.route('/delete/<int:item_id>')
@login_required
def delete(item_id):
    if session.get('role') != 'admin':
        return redirect(url_for('dashboard'))
        
    conn = get_db_connection()
    if conn:
        try:
            with conn.cursor() as cursor:
                cursor.execute("DELETE FROM items WHERE id=%s", (item_id,))
                conn.commit()
        except pymysql.MySQLError as e:
            print(f"Deletion execution failure: {e}")
        finally:
            conn.close()
            
    return redirect(url_for('dashboard'))


@app.route('/approve/<int:request_id>')
@login_required
def approve(request_id):
    if session.get('role') != 'admin':
        return redirect(url_for('dashboard'))
        
    conn = get_db_connection()
    if conn:
        try:
            with conn.cursor() as cursor:
                cursor.execute("UPDATE item_requests SET status='approved' WHERE id=%s", (request_id,))
                conn.commit()
        except pymysql.MySQLError as e:
            print(f"Approval handling processing failure: {e}")
        finally:
            conn.close()
            
    return redirect(url_for('dashboard'))


@app.route('/reject/<int:request_id>')
@login_required
def reject(request_id):
    if session.get('role') != 'admin':
        return redirect(url_for('dashboard'))
        
    conn = get_db_connection()
    if conn:
        try:
            with conn.cursor() as cursor:
                cursor.execute("UPDATE item_requests SET status='rejected' WHERE id=%s", (request_id,))
                conn.commit()
        except pymysql.MySQLError as e:
            print(f"Rejection processing failure: {e}")
        finally:
            conn.close()
            
    return redirect(url_for('dashboard'))


@app.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('index'))

app = app

if __name__ == "__main__":
    app.run(debug=True, host='0.0.0.0', port=5000)