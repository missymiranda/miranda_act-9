import os
import sqlite3
from pathlib import Path
from urllib.parse import urlparse


from flask import Flask, jsonify, request, render_template

app = Flask(__name__)
DB_PATH = Path(__file__).with_name("students.db")


def get_db_connection():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def ensure_database():
    """Create the table and safely add source to databases from earlier activities."""
    conn = get_db_connection()
    try:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS students (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                student_id TEXT NOT NULL,
                name TEXT NOT NULL,
                program TEXT NOT NULL,
                year INTEGER NOT NULL,
                section TEXT NOT NULL,
                source TEXT DEFAULT 'Local'
            )
        """)
        columns = {
            row["name"] for row in conn.execute("PRAGMA table_info(students)").fetchall()
        }
        if "source" not in columns:
            conn.execute("ALTER TABLE students ADD COLUMN source TEXT DEFAULT 'Local'")
            conn.execute(
                "UPDATE students SET source = 'Local' WHERE source IS NULL OR source = ''"
            )
        conn.commit()
    finally:
        conn.close()


def validate_student(data):
    if not isinstance(data, dict):
        return None, "Send student data as a JSON object."
    student_id = str(data.get("student_id", "")).strip()
    name = str(data.get("name", "")).strip()
    program = str(data.get("program", "")).strip()
    section = str(data.get("section", "")).strip()
    try:
        year = int(data.get("year", ""))
    except (TypeError, ValueError):
        return None, "Year must be a whole number."
    if not all([student_id, name, program, section]):
        return None, "All fields are required: student_id, name, program, year, section."
    if year < 1 or year > 6:
        return None, "Year must be between 1 and 6."
    return {
        "student_id": student_id,
        "name": name,
        "program": program,
        "year": year,
        "section": section,
        "source": str(data.get("source", "External API")).strip() or "External API"
    }, None


def validate_partner_url(api_url):
    """Only accept an HTTPS Render URL ending in /api/students."""
    parsed = urlparse(api_url)
    return (
        parsed.scheme == "https"
        and bool(parsed.hostname)
        and (parsed.hostname == "onrender.com" or parsed.hostname.endswith(".onrender.com"))
        and parsed.path.rstrip("/") == "/api/students"
        and not parsed.query
        and not parsed.username
        and not parsed.password
    )


def fetch_partner_records(api_url):
    if not validate_partner_url(api_url):
        return None, "Enter an HTTPS Render API URL ending in /api/students."
    try:
        response = requests.get(api_url, timeout=15)
        response.raise_for_status()
        data = response.json()
        if not isinstance(data, list):
            return None, "The partner API did not return a JSON list."
        return data, None
    except (requests.RequestException, ValueError):
        return None, "Unable to retrieve partner data. Check the URL and try again."


@app.route("/")
def home():
    ensure_database()
    return render_template("index.html")


# Earlier activity routes retained for compatibility.
@app.route("/student")
def student():
    return jsonify({
        "student_id": "2024-00076", "name": "Sample Student",
        "program": "BSIT", "year": 3, "section": "3B"
    })


@app.route("/hello")
def hello():
    name = request.args.get("name", "Student")
    return jsonify({"message": f"Hello, {name}!"})


@app.route("/campus")
def campus():
    return jsonify({
        "campus": "San Enrique-Campus", "location": "Iloilo",
        "status": "Open", "type": "University Campus"
    })


@app.route("/grade")
def grade():
    score = request.args.get("score", type=float)
    if score is None or not 0 <= score <= 100:
        return jsonify({"error": "Provide a score from 0 to 100, e.g. ?score=95."}), 400
    if score >= 90:
        remarks = "Excellent"
    elif score >= 80:
        remarks = "Very Good"
    elif score >= 75:
        remarks = "Passed"
    else:
        remarks = "Needs Improvement"
    return jsonify({"subject": "IT 3120", "grade": score, "remarks": remarks})


@app.route("/students", methods=["GET"])
def legacy_students():
    return get_all_students()


@app.route("/students/<int:student_record_id>", methods=["GET"])
def legacy_student_detail(student_record_id):
    return get_student_detail(student_record_id)


@app.route("/students/section/<section>", methods=["GET"])
def legacy_students_section(section):
    ensure_database()
    conn = get_db_connection()
    try:
        rows = conn.execute(
            "SELECT * FROM students WHERE UPPER(section) = UPPER(?) ORDER BY id",
            (section,)
        ).fetchall()
        return jsonify([dict(row) for row in rows])
    finally:
        conn.close()


def get_all_students():
    ensure_database()
    conn = get_db_connection()
    try:
        rows = conn.execute("SELECT * FROM students ORDER BY id").fetchall()
        return jsonify([dict(row) for row in rows])
    finally:
        conn.close()


def get_student_detail(student_record_id):
    ensure_database()
    conn = get_db_connection()
    try:
        row = conn.execute(
            "SELECT * FROM students WHERE id = ?", (student_record_id,)
        ).fetchone()
        if row is None:
            return jsonify({"error": "Student not found."}), 404
        return jsonify(dict(row))
    finally:
        conn.close()


@app.route("/api/students", methods=["GET", "POST"])
def api_students():
    ensure_database()
    if request.method == "GET":
        return get_all_students()

    student_data, error = validate_student(request.get_json(silent=True))
    if error:
        return jsonify({"error": error}), 400

    conn = get_db_connection()
    try:
        cursor = conn.execute("""
            INSERT INTO students (student_id, name, program, year, section, source)
            VALUES (?, ?, ?, ?, ?, ?)
        """, (
            student_data["student_id"], student_data["name"],
            student_data["program"], student_data["year"],
            student_data["section"], student_data["source"]
        ))
        conn.commit()
        created = conn.execute(
            "SELECT * FROM students WHERE id = ?", (cursor.lastrowid,)
        ).fetchone()
        return jsonify({
            "message": "Student added successfully.",
            "student": dict(created)
        }), 201
    finally:
        conn.close()


@app.route("/api/students/<int:student_record_id>", methods=["GET", "PUT", "DELETE"])
def api_student_detail(student_record_id):
    ensure_database()
    conn = get_db_connection()
    try:
        existing = conn.execute(
            "SELECT * FROM students WHERE id = ?", (student_record_id,)
        ).fetchone()
        if existing is None:
            return jsonify({"error": "Student not found."}), 404

        if request.method == "GET":
            return jsonify(dict(existing))

        if request.method == "DELETE":
            conn.execute("DELETE FROM students WHERE id = ?", (student_record_id,))
            conn.commit()
            return jsonify({"message": "Student deleted successfully.", "id": student_record_id})

        student_data, error = validate_student(request.get_json(silent=True))
        if error:
            return jsonify({"error": error}), 400
        conn.execute("""
            UPDATE students
            SET student_id = ?, name = ?, program = ?, year = ?, section = ?
            WHERE id = ?
        """, (
            student_data["student_id"], student_data["name"],
            student_data["program"], student_data["year"],
            student_data["section"], student_record_id
        ))
        conn.commit()
        updated = conn.execute(
            "SELECT * FROM students WHERE id = ?", (student_record_id,)
        ).fetchone()
        return jsonify({"message": "Student updated successfully.", "student": dict(updated)})
    finally:
        conn.close()


@app.route("/partner-records", methods=["GET"])
def partner_records():
    api_url = request.args.get("url", "").strip()
    data, error = fetch_partner_records(api_url)
    if error:
        return jsonify({"error": error}), 400 if "Enter an HTTPS" in error else 502
    return jsonify(data)


# Backward-compatible route name used in the earlier Activity 8 page.
@app.route("/api/classmate-students", methods=["GET"])
def classmate_students():
    return partner_records()


@app.route("/import-student", methods=["POST"])
def import_student():
    ensure_database()
    data = request.get_json(silent=True)
    student_data, error = validate_student(data)
    if error:
        return jsonify({"error": error}), 400

    conn = get_db_connection()
    try:
        cursor = conn.execute("""
            INSERT INTO students (student_id, name, program, year, section, source)
            VALUES (?, ?, ?, ?, ?, 'Classmate API')
        """, (
            student_data["student_id"], student_data["name"],
            student_data["program"], student_data["year"], student_data["section"]
        ))
        conn.commit()
        saved = conn.execute(
            "SELECT * FROM students WHERE id = ?", (cursor.lastrowid,)
        ).fetchone()
        return jsonify({"message": "Remote record saved.", "student": dict(saved)}), 201
    finally:
        conn.close()


@app.route("/send-to-partner", methods=["POST"])
def send_to_partner():
    payload = request.get_json(silent=True)
    if not isinstance(payload, dict):
        return jsonify({"error": "Send a JSON object containing url and record."}), 400

    api_url = str(payload.get("url", "")).strip()
    record, error = validate_student(payload.get("record"))
    if error:
        return jsonify({"error": error}), 400
    if not validate_partner_url(api_url):
        return jsonify({"error": "Enter an HTTPS Render API URL ending in /api/students."}), 400

    record["source"] = "Partner API"
    try:
        response = requests.post(api_url, json=record, timeout=15)
        try:
            partner_response = response.json()
        except ValueError:
            partner_response = {"response": response.text[:500]}
        return jsonify({
            "message": "Partner API responded.",
            "partner_status": response.status_code,
            "partner_response": partner_response
        }), (200 if response.ok else 502)
    except requests.RequestException:
        return jsonify({"error": "Unable to send record to partner API."}), 502


if __name__ == "__main__":
    ensure_database()
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 5000)), debug=False)
