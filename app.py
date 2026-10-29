import os
import sqlite3
from datetime import date, datetime
from functools import wraps

from flask import Flask, abort, flash, g, redirect, render_template, request, session, url_for
from werkzeug.security import check_password_hash, generate_password_hash

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATABASE = os.path.join(BASE_DIR, "emp.sqlite3")
app = Flask(__name__)
app.secret_key = os.environ.get("EMP_SECRET_KEY", "local-demo-key-change-before-deployment")


def db():
    if "db" not in g:
        g.db = sqlite3.connect(DATABASE)
        g.db.row_factory = sqlite3.Row
        g.db.execute("PRAGMA foreign_keys = ON")
    return g.db


@app.teardown_appcontext
def close_db(_error=None):
    conn = g.pop("db", None)
    if conn is not None:
        conn.close()


def init_db():
    conn = sqlite3.connect(DATABASE)
    conn.execute("PRAGMA foreign_keys = ON")
    conn.executescript("""
    CREATE TABLE IF NOT EXISTS users (
      id INTEGER PRIMARY KEY, name TEXT NOT NULL, email TEXT UNIQUE NOT NULL,
      password_hash TEXT NOT NULL, role TEXT NOT NULL CHECK(role IN ('admin','examiner','student')),
      department TEXT DEFAULT '', status TEXT NOT NULL DEFAULT 'approved'
    );
    CREATE TABLE IF NOT EXISTS courses (
      id INTEGER PRIMARY KEY, code TEXT UNIQUE NOT NULL, name TEXT NOT NULL,
      description TEXT DEFAULT '', active INTEGER NOT NULL DEFAULT 1
    );
    CREATE TABLE IF NOT EXISTS exams (
      id INTEGER PRIMARY KEY, course_id INTEGER NOT NULL REFERENCES courses(id),
      name TEXT NOT NULL, exam_type TEXT NOT NULL, duration INTEGER NOT NULL,
      max_marks INTEGER NOT NULL, slot_start TEXT NOT NULL, slot_end TEXT NOT NULL,
      booking_start TEXT NOT NULL, booking_end TEXT NOT NULL,
      status TEXT NOT NULL DEFAULT 'open', published INTEGER NOT NULL DEFAULT 0
    );
    CREATE TABLE IF NOT EXISTS examiners (
      exam_id INTEGER NOT NULL REFERENCES exams(id) ON DELETE CASCADE,
      examiner_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
      PRIMARY KEY(exam_id, examiner_id)
    );
    CREATE TABLE IF NOT EXISTS rubrics (
      id INTEGER PRIMARY KEY, exam_id INTEGER NOT NULL REFERENCES exams(id) ON DELETE CASCADE,
      criterion TEXT NOT NULL, max_marks INTEGER NOT NULL, description TEXT DEFAULT ''
    );
    CREATE TABLE IF NOT EXISTS slots (
      id INTEGER PRIMARY KEY, exam_id INTEGER NOT NULL REFERENCES exams(id),
      examiner_id INTEGER NOT NULL REFERENCES users(id), slot_date TEXT NOT NULL,
      start_time TEXT NOT NULL, end_time TEXT NOT NULL, capacity INTEGER NOT NULL CHECK(capacity > 0),
      status TEXT NOT NULL DEFAULT 'available'
    );
    CREATE TABLE IF NOT EXISTS bookings (
      id INTEGER PRIMARY KEY, student_id INTEGER NOT NULL REFERENCES users(id),
      slot_id INTEGER NOT NULL REFERENCES slots(id), booked_at TEXT NOT NULL,
      status TEXT NOT NULL DEFAULT 'booked', UNIQUE(student_id, slot_id)
    );
    CREATE TABLE IF NOT EXISTS scores (
      id INTEGER PRIMARY KEY, booking_id INTEGER NOT NULL REFERENCES bookings(id) ON DELETE CASCADE,
      rubric_id INTEGER NOT NULL REFERENCES rubrics(id), marks REAL NOT NULL, remark TEXT DEFAULT '',
      UNIQUE(booking_id, rubric_id)
    );
    """)
    admin = conn.execute("SELECT id FROM users WHERE role='admin'").fetchone()
    if admin is None:
        conn.execute("INSERT INTO users(name,email,password_hash,role,status) VALUES(?,?,?,?,?)",
                     ("Portal Admin", "admin@example.com", generate_password_hash("admin1234"), "admin", "approved"))
    if conn.execute("SELECT id FROM courses LIMIT 1").fetchone() is None:
        conn.execute("INSERT INTO courses(code,name,description) VALUES(?,?,?)",
                     ("MAD101", "Modern Application Development I", "Foundations of application development."))
        course_id = conn.execute("SELECT id FROM courses WHERE code='MAD101'").fetchone()[0]
        conn.execute("INSERT INTO exams(course_id,name,exam_type,duration,max_marks,slot_start,slot_end,booking_start,booking_end) VALUES(?,?,?,?,?,?,?,?,?)",
                     (course_id, "MAD 1 Project Viva", "Viva", 20, 100,
                      "2026-10-01", "2026-12-31", "2026-10-01", "2026-12-31"))
        exam_id = conn.execute("SELECT id FROM exams WHERE name='MAD 1 Project Viva'").fetchone()[0]
        conn.executemany("INSERT INTO rubrics(exam_id,criterion,max_marks,description) VALUES(?,?,?,?)", [
            (exam_id, "Technical understanding", 40, "Explain the design and implementation."),
            (exam_id, "Demonstration", 40, "Demonstrate the main project workflow."),
            (exam_id, "Communication", 20, "Present the work clearly."),
        ])
    conn.commit()
    conn.close()


@app.before_request
def ensure_db():
    init_db()
    if session.get("user_id"):
        g.user = db().execute("SELECT * FROM users WHERE id=?", (session["user_id"],)).fetchone()
    else:
        g.user = None


@app.context_processor
def inject_user():
    return {"current_user": getattr(g, "user", None)}


def login_required(role=None):
    def decorate(view):
        @wraps(view)
        def wrapped(*args, **kwargs):
            user = getattr(g, "user", None)
            if user is None:
                return redirect(url_for("login"))
            if role and user["role"] != role:
                abort(403)
            if user["role"] == "examiner" and user["status"] != "approved":
                flash("Your examiner account is awaiting administrator approval.", "warning")
                return redirect(url_for("logout"))
            return view(*args, **kwargs)
        return wrapped
    return decorate


def exam_window(exam, start_key, end_key):
    today = date.today().isoformat()
    return exam[start_key] <= today <= exam[end_key]


@app.route("/")
def home():
    if g.user:
        return redirect(url_for("dashboard"))
    exams = db().execute("SELECT e.*,c.name course_name FROM exams e JOIN courses c ON c.id=e.course_id WHERE e.status='open' ORDER BY e.id DESC").fetchall()
    return render_template("home.html", exams=exams)


@app.route("/register", methods=["GET", "POST"])
def register():
    if request.method == "POST":
        name, email = request.form["name"].strip(), request.form["email"].strip().lower()
        role = request.form["role"]
        if role not in ("student", "examiner"):
            abort(400)
        status = "pending" if role == "examiner" else "approved"
        try:
            db().execute("INSERT INTO users(name,email,password_hash,role,department,status) VALUES(?,?,?,?,?,?)",
                         (name, email, generate_password_hash(request.form["password"]), role,
                          request.form.get("department", "").strip(), status))
            db().commit()
        except sqlite3.IntegrityError:
            flash("That email address is already registered.", "danger")
            return render_template("register.html")
        flash("Account created. Examiner accounts need admin approval." if role == "examiner" else "Account created. You can sign in now.", "success")
        return redirect(url_for("login"))
    return render_template("register.html")


@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        user = db().execute("SELECT * FROM users WHERE email=?", (request.form["email"].strip().lower(),)).fetchone()
        if user and check_password_hash(user["password_hash"], request.form["password"]):
            session.clear()
            session["user_id"] = user["id"]
            if user["role"] == "examiner" and user["status"] != "approved":
                flash("Your account is waiting for admin approval.", "warning")
                return redirect(url_for("logout"))
            return redirect(url_for("dashboard"))
        flash("Email or password did not match.", "danger")
    return render_template("login.html")


@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("home"))


@app.route("/dashboard")
@login_required()
def dashboard():
    user = g.user
    conn = db()
    if user["role"] == "admin":
        counts = {"courses": conn.execute("SELECT COUNT(*) FROM courses").fetchone()[0],
                  "exams": conn.execute("SELECT COUNT(*) FROM exams").fetchone()[0],
                  "examiners": conn.execute("SELECT COUNT(*) FROM users WHERE role='examiner'").fetchone()[0],
                  "students": conn.execute("SELECT COUNT(*) FROM users WHERE role='student'").fetchone()[0],
                  "slots": conn.execute("SELECT COUNT(*) FROM slots").fetchone()[0],
                  "bookings": conn.execute("SELECT COUNT(*) FROM bookings WHERE status='booked'").fetchone()[0]}
        exams = conn.execute("SELECT e.*,c.name course_name FROM exams e JOIN courses c ON c.id=e.course_id ORDER BY e.id DESC").fetchall()
        pending = conn.execute("SELECT * FROM users WHERE role='examiner' AND status='pending'").fetchall()
        return render_template("admin.html", counts=counts, exams=exams, pending=pending,
                               courses=conn.execute("SELECT * FROM courses ORDER BY name").fetchall(),
                               examiners=conn.execute("SELECT id,name,email FROM users WHERE role='examiner' AND status='approved' ORDER BY name").fetchall())
    if user["role"] == "examiner":
        exams = conn.execute("SELECT e.*,c.name course_name FROM exams e JOIN examiners a ON a.exam_id=e.id JOIN courses c ON c.id=e.course_id WHERE a.examiner_id=?", (user["id"],)).fetchall()
        slots = conn.execute("SELECT s.*,e.name exam_name,(SELECT COUNT(*) FROM bookings b WHERE b.slot_id=s.id AND b.status='booked') booked FROM slots s JOIN exams e ON e.id=s.exam_id WHERE s.examiner_id=? ORDER BY s.slot_date,s.start_time", (user["id"],)).fetchall()
        return render_template("examiner.html", exams=exams, slots=slots)
    bookings = conn.execute("SELECT b.*,s.slot_date,s.start_time,s.end_time,e.name exam_name,e.published FROM bookings b JOIN slots s ON s.id=b.slot_id JOIN exams e ON e.id=s.exam_id WHERE b.student_id=? ORDER BY s.slot_date DESC,s.start_time", (user["id"],)).fetchall()
    exams = conn.execute("SELECT e.*,c.name course_name FROM exams e JOIN courses c ON c.id=e.course_id WHERE e.status='open' ORDER BY e.name").fetchall()
    return render_template("student.html", exams=exams, bookings=bookings)


@app.route("/admin/course", methods=["POST"])
@login_required("admin")
def create_course():
    try:
        db().execute("INSERT INTO courses(code,name,description) VALUES(?,?,?)",
                     (request.form["code"].strip().upper(), request.form["name"].strip(), request.form.get("description", "").strip()))
        db().commit()
        flash("Course added.", "success")
    except sqlite3.IntegrityError:
        flash("Course code must be unique.", "danger")
    return redirect(url_for("dashboard"))


@app.route("/admin/exam", methods=["POST"])
@login_required("admin")
def create_exam():
    try:
        cur = db().execute("INSERT INTO exams(course_id,name,exam_type,duration,max_marks,slot_start,slot_end,booking_start,booking_end) VALUES(?,?,?,?,?,?,?,?,?)",
                           (request.form["course_id"], request.form["name"].strip(), request.form["exam_type"],
                            request.form["duration"], request.form["max_marks"], request.form["slot_start"],
                            request.form["slot_end"], request.form["booking_start"], request.form["booking_end"]))
        exam_id = cur.lastrowid
        for examiner_id in request.form.getlist("examiner_ids"):
            db().execute("INSERT OR IGNORE INTO examiners(exam_id,examiner_id) VALUES(?,?)", (exam_id, examiner_id))
        db().commit()
        flash("Examination created.", "success")
    except (sqlite3.IntegrityError, ValueError):
        db().rollback()
        flash("Please check the examination details and dates.", "danger")
    return redirect(url_for("dashboard"))


@app.route("/admin/exam/<int:exam_id>/rubric", methods=["POST"])
@login_required("admin")
def add_rubric(exam_id):
    db().execute("INSERT INTO rubrics(exam_id,criterion,max_marks,description) VALUES(?,?,?,?)",
                 (exam_id, request.form["criterion"].strip(), request.form["max_marks"], request.form.get("description", "").strip()))
    db().commit()
    flash("Rubric criterion added.", "success")
    return redirect(url_for("dashboard"))


@app.route("/admin/examiner/<int:user_id>/approve", methods=["POST"])
@login_required("admin")
def approve_examiner(user_id):
    db().execute("UPDATE users SET status='approved' WHERE id=? AND role='examiner'", (user_id,))
    db().commit()
    flash("Examiner approved.", "success")
    return redirect(url_for("dashboard"))


@app.route("/admin/exam/<int:exam_id>/assign", methods=["POST"])
@login_required("admin")
def assign_examiner(exam_id):
    db().execute("INSERT OR IGNORE INTO examiners(exam_id,examiner_id) VALUES(?,?)", (exam_id, request.form["examiner_id"]))
    db().commit()
    flash("Examiner assigned to the examination.", "success")
    return redirect(url_for("dashboard"))


@app.route("/admin/exam/<int:exam_id>/publish", methods=["POST"])
@login_required("admin")
def publish_results(exam_id):
    db().execute("UPDATE exams SET published=1 WHERE id=?", (exam_id,))
    db().commit()
    flash("Results are now visible to students.", "success")
    return redirect(url_for("dashboard"))


@app.route("/admin/exam/<int:exam_id>/status", methods=["POST"])
@login_required("admin")
def set_exam_status(exam_id):
    status = request.form.get("status")
    if status not in ("open", "closed"):
        abort(400)
    db().execute("UPDATE exams SET status=? WHERE id=?", (status, exam_id))
    db().commit()
    flash("Examination status updated.", "success")
    return redirect(url_for("dashboard"))


@app.route("/admin/bookings")
@login_required("admin")
def all_bookings():
    rows = db().execute("SELECT b.id,b.status,s.slot_date,s.start_time,e.name exam_name,st.name student_name,ex.name examiner_name FROM bookings b JOIN users st ON st.id=b.student_id JOIN slots s ON s.id=b.slot_id JOIN exams e ON e.id=s.exam_id JOIN users ex ON ex.id=s.examiner_id ORDER BY s.slot_date,s.start_time").fetchall()
    return render_template("bookings.html", bookings=rows)


@app.route("/examiner/slot", methods=["POST"])
@login_required("examiner")
def create_slot():
    exam = db().execute("SELECT e.* FROM exams e JOIN examiners a ON a.exam_id=e.id WHERE e.id=? AND a.examiner_id=?", (request.form["exam_id"], g.user["id"])).fetchone()
    if not exam or not exam_window(exam, "slot_start", "slot_end"):
        flash("Slots can only be created during the exam's slot-creation window.", "danger")
        return redirect(url_for("dashboard"))
    if request.form["end_time"] <= request.form["start_time"]:
        flash("End time must be after start time.", "danger")
        return redirect(url_for("dashboard"))
    db().execute("INSERT INTO slots(exam_id,examiner_id,slot_date,start_time,end_time,capacity) VALUES(?,?,?,?,?,?)",
                 (exam["id"], g.user["id"], request.form["slot_date"], request.form["start_time"], request.form["end_time"], request.form["capacity"]))
    db().commit()
    flash("Examination slot created.", "success")
    return redirect(url_for("dashboard"))


@app.route("/examiner/slot/<int:slot_id>/cancel", methods=["POST"])
@login_required("examiner")
def cancel_slot(slot_id):
    slot = db().execute("SELECT * FROM slots WHERE id=? AND examiner_id=?", (slot_id, g.user["id"])).fetchone()
    if slot:
        booked = db().execute("SELECT COUNT(*) FROM bookings WHERE slot_id=? AND status='booked'", (slot_id,)).fetchone()[0]
        if not booked:
            db().execute("UPDATE slots SET status='cancelled' WHERE id=?", (slot_id,))
            db().commit()
            flash("Slot cancelled.", "success")
        else:
            flash("A slot with bookings cannot be cancelled by an examiner.", "danger")
    return redirect(url_for("dashboard"))


@app.route("/exam/<int:exam_id>/slots")
@login_required("student")
def exam_slots(exam_id):
    exam = db().execute("SELECT e.*,c.name course_name FROM exams e JOIN courses c ON c.id=e.course_id WHERE e.id=?", (exam_id,)).fetchone()
    if not exam:
        abort(404)
    slots = db().execute("SELECT s.*,u.name examiner_name,(SELECT COUNT(*) FROM bookings b WHERE b.slot_id=s.id AND b.status='booked') booked FROM slots s JOIN users u ON u.id=s.examiner_id WHERE s.exam_id=? AND s.status='available' ORDER BY s.slot_date,s.start_time", (exam_id,)).fetchall()
    return render_template("slots.html", exam=exam, slots=slots, booking_open=exam_window(exam, "booking_start", "booking_end"))


@app.route("/slot/<int:slot_id>/book", methods=["POST"])
@login_required("student")
def book_slot(slot_id):
    conn = db()
    slot = conn.execute("SELECT s.*,e.booking_start,e.booking_end,e.id exam_id,e.status exam_status FROM slots s JOIN exams e ON e.id=s.exam_id WHERE s.id=?", (slot_id,)).fetchone()
    if not slot or slot["status"] != "available" or slot["exam_status"] != "open" or not exam_window(slot, "booking_start", "booking_end"):
        flash("Booking is closed or this slot is no longer available.", "danger")
        return redirect(url_for("dashboard"))
    if conn.execute("SELECT id FROM bookings b JOIN slots s ON s.id=b.slot_id WHERE b.student_id=? AND s.exam_id=? AND b.status='booked'", (g.user["id"], slot["exam_id"])).fetchone():
        flash("You already have an active booking for this examination.", "warning")
        return redirect(url_for("exam_slots", exam_id=slot["exam_id"]))
    conn.execute("BEGIN IMMEDIATE")
    booked = conn.execute("SELECT COUNT(*) FROM bookings WHERE slot_id=? AND status='booked'", (slot_id,)).fetchone()[0]
    if booked >= slot["capacity"]:
        conn.rollback()
        conn.execute("UPDATE slots SET status='full' WHERE id=?", (slot_id,))
        conn.commit()
        flash("That slot is full.", "danger")
    else:
        conn.execute("INSERT INTO bookings(student_id,slot_id,booked_at) VALUES(?,?,?)", (g.user["id"], slot_id, datetime.now().isoformat(timespec="minutes")))
        if booked + 1 >= slot["capacity"]:
            conn.execute("UPDATE slots SET status='full' WHERE id=?", (slot_id,))
        conn.commit()
        flash("Your slot is booked.", "success")
    return redirect(url_for("dashboard"))


@app.route("/booking/<int:booking_id>/cancel", methods=["POST"])
@login_required("student")
def cancel_booking(booking_id):
    conn = db()
    booking = conn.execute("SELECT b.*,s.id slot_id,e.booking_end,e.id exam_id FROM bookings b JOIN slots s ON s.id=b.slot_id JOIN exams e ON e.id=s.exam_id WHERE b.id=? AND b.student_id=?", (booking_id, g.user["id"])).fetchone()
    if booking and booking["status"] == "booked" and date.today().isoformat() <= booking["booking_end"]:
        conn.execute("UPDATE bookings SET status='cancelled' WHERE id=?", (booking_id,))
        conn.execute("UPDATE slots SET status='available' WHERE id=? AND status='full'", (booking["slot_id"],))
        conn.commit()
        flash("Booking cancelled.", "success")
    else:
        flash("This booking can no longer be cancelled.", "danger")
    return redirect(url_for("dashboard"))


@app.route("/examiner/evaluations")
@login_required("examiner")
def evaluations():
    rows = db().execute("SELECT b.id booking_id,b.status,st.name student_name,e.name exam_name,s.slot_date,s.start_time FROM bookings b JOIN slots s ON s.id=b.slot_id JOIN exams e ON e.id=s.exam_id JOIN users st ON st.id=b.student_id WHERE s.examiner_id=? AND b.status='booked' ORDER BY s.slot_date,s.start_time", (g.user["id"],)).fetchall()
    return render_template("evaluations.html", bookings=rows)


@app.route("/examiner/evaluation/<int:booking_id>", methods=["GET", "POST"])
@login_required("examiner")
def evaluate(booking_id):
    booking = db().execute("SELECT b.*,e.id exam_id,e.name exam_name,e.max_marks,st.name student_name FROM bookings b JOIN slots s ON s.id=b.slot_id JOIN exams e ON e.id=s.exam_id JOIN users st ON st.id=b.student_id WHERE b.id=? AND s.examiner_id=?", (booking_id, g.user["id"])).fetchone()
    if not booking:
        abort(404)
    rubric = db().execute("SELECT * FROM rubrics WHERE exam_id=? ORDER BY id", (booking["exam_id"],)).fetchall()
    if request.method == "POST":
        conn = db()
        conn.execute("DELETE FROM scores WHERE booking_id=?", (booking_id,))
        for item in rubric:
            marks = float(request.form.get(f"marks_{item['id']}", 0))
            if marks < 0 or marks > item["max_marks"]:
                flash(f"Marks for {item['criterion']} must be between 0 and {item['max_marks']}.", "danger")
                conn.rollback()
                return render_template("evaluate.html", booking=booking, rubric=rubric)
            conn.execute("INSERT INTO scores(booking_id,rubric_id,marks,remark) VALUES(?,?,?,?)", (booking_id, item["id"], marks, request.form.get(f"remark_{item['id']}", "").strip()))
        conn.execute("UPDATE bookings SET status='completed' WHERE id=?", (booking_id,))
        conn.commit()
        flash("Evaluation saved. Results remain hidden until admin publishes them.", "success")
        return redirect(url_for("evaluations"))
    return render_template("evaluate.html", booking=booking, rubric=rubric)


@app.route("/results")
@login_required("student")
def results():
    rows = db().execute("SELECT e.name exam_name,e.max_marks,r.criterion,r.max_marks rubric_max,s.marks,s.remark FROM bookings b JOIN slots sl ON sl.id=b.slot_id JOIN exams e ON e.id=sl.exam_id JOIN scores s ON s.booking_id=b.id JOIN rubrics r ON r.id=s.rubric_id WHERE b.student_id=? AND e.published=1 ORDER BY e.name,r.id", (g.user["id"],)).fetchall()
    return render_template("results.html", results=rows)


if __name__ == "__main__":
    init_db()
    app.run(debug=True)
