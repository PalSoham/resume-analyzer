import os
import json
import io
from datetime import datetime, timezone

import pdfplumber
import fitz  # pymupdf
import docx
from flask import (
    Flask, render_template, request,
    redirect, session, flash, url_for
)
from werkzeug.security import generate_password_hash, check_password_hash
from werkzeug.utils import secure_filename
from dotenv import load_dotenv

from db import Base, engine, SessionLocal
import models
from ai import analyze_resume

load_dotenv()

app = Flask(__name__)
app.secret_key = os.environ["FLASK_SECRET_KEY"]

Base.metadata.create_all(bind=engine)

ALLOWED_EXTENSIONS = {"pdf", "docx"}
MAX_FILE_BYTES = 5 * 1024 * 1024  # 5 MB


# ── Helpers ──────────────────────────────────────────────────────────────────

def allowed_file(filename: str) -> bool:
    return "." in filename and filename.rsplit(".", 1)[1].lower() in ALLOWED_EXTENSIONS


def _extract_pdf(data: bytes) -> str | None:
    """
    Try two extraction strategies in order of reliability:
      1. pdfplumber  — best for text-layer PDFs with complex layouts
      2. pymupdf     — handles more encoding edge cases, good fallback
      3. Return None — genuinely image-only / scanned document
    """
    # Strategy 1: pdfplumber
    try:
        with pdfplumber.open(io.BytesIO(data)) as pdf:
            pages = [page.extract_text() or "" for page in pdf.pages]
            text = "\n".join(pages).strip()
            if len(text) > 100:
                return text
    except Exception:
        pass

    # Strategy 2: pymupdf (fitz)
    try:
        doc = fitz.open(stream=data, filetype="pdf")
        pages = [page.get_text("text") for page in doc]
        doc.close()
        text = "\n".join(pages).strip()
        if len(text) > 100:
            return text
    except Exception:
        pass

    return None


def extract_text_from_file(file) -> tuple[str | None, str | None]:
    """Return (text, error_message). Reads file bytes once, routes by extension."""
    filename = secure_filename(file.filename)
    ext = filename.rsplit(".", 1)[1].lower()
    data = file.read()

    if len(data) > MAX_FILE_BYTES:
        return None, "File exceeds the 5 MB limit."

    if ext == "pdf":
        text = _extract_pdf(data)
        if not text:
            return None, (
                "Could not extract text from this PDF. "
                "It may be a scanned image — please copy-paste the text directly instead."
            )
        return text, None

    if ext == "docx":
        try:
            doc = docx.Document(io.BytesIO(data))
            text = "\n".join(p.text for p in doc.paragraphs).strip()
            if not text:
                return None, "Could not extract text from DOCX."
            return text, None
        except Exception as e:
            return None, f"Failed to parse DOCX: {str(e)}"

    return None, "Unsupported file type."


# ── Routes ───────────────────────────────────────────────────────────────────

@app.route("/")
def home():
    return redirect(url_for("dashboard") if "user" in session else url_for("login"))


@app.route("/signup", methods=["GET", "POST"])
def signup():
    if "user" in session:
        return redirect(url_for("dashboard"))

    if request.method == "POST":
        email = request.form.get("email", "").strip().lower()
        password = request.form.get("password", "")

        if not email or not password:
            flash("Email and password are required.", "error")
            return render_template("signup.html")

        if len(password) < 6:
            flash("Password must be at least 6 characters.", "error")
            return render_template("signup.html")

        db = SessionLocal()
        try:
            if db.query(models.User).filter_by(email=email).first():
                flash("An account with that email already exists.", "error")
                return render_template("signup.html")

            user = models.User(
                email=email,
                password=generate_password_hash(password),
            )
            db.add(user)
            db.commit()
            flash("Account created. Please log in.", "success")
            return redirect(url_for("login"))
        finally:
            db.close()

    return render_template("signup.html")


@app.route("/login", methods=["GET", "POST"])
def login():
    if "user" in session:
        return redirect(url_for("dashboard"))

    if request.method == "POST":
        email = request.form.get("email", "").strip().lower()
        password = request.form.get("password", "")

        db = SessionLocal()
        try:
            user = db.query(models.User).filter_by(email=email).first()
            if user and check_password_hash(user.password, password):
                session["user"] = user.email
                return redirect(url_for("dashboard"))
            flash("Invalid email or password.", "error")
        finally:
            db.close()

    return render_template("login.html")


@app.route("/dashboard", methods=["GET", "POST"])
def dashboard():
    if "user" not in session:
        return redirect(url_for("login"))

    result = None
    role = ""

    if request.method == "POST":
        role = request.form.get("role", "").strip()
        resume_text = request.form.get("resume", "").strip()
        file = request.files.get("file")

        # File upload takes precedence over pasted text
        if file and file.filename:
            if not allowed_file(file.filename):
                flash("Only PDF and DOCX files are supported.", "error")
                return render_template("dashboard.html", user=session["user"], result=None, role=role)

            extracted, err = extract_text_from_file(file)
            if err:
                flash(err, "error")
                return render_template("dashboard.html", user=session["user"], result=None, role=role)
            resume_text = extracted

        if not resume_text:
            flash("Please paste your resume or upload a file.", "error")
            return render_template("dashboard.html", user=session["user"], result=None, role=role)

        if not role:
            flash("Please specify your target role.", "error")
            return render_template("dashboard.html", user=session["user"], result=None, role=role)

        result = analyze_resume(resume_text, role)

        if "error" not in result:
            db = SessionLocal()
            try:
                user = db.query(models.User).filter_by(email=session["user"]).first()
                report = models.Report(
                    user_id=user.id,
                    resume_text=resume_text[:5000],
                    result=json.dumps(result),
                    role=role,
                )
                db.add(report)
                db.commit()
            finally:
                db.close()

    return render_template("dashboard.html", user=session["user"], result=result, role=role)


@app.route("/history")
def history():
    if "user" not in session:
        return redirect(url_for("login"))

    db = SessionLocal()
    try:
        user = db.query(models.User).filter_by(email=session["user"]).first()
        raw_reports = (
            db.query(models.Report)
            .filter_by(user_id=user.id)
            .order_by(models.Report.created_at.desc())
            .all()
        )

        reports = []
        for r in raw_reports:
            try:
                parsed = json.loads(r.result)
            except Exception:
                parsed = {}
            reports.append({
                "id": r.id,
                "role": r.role or "Unknown Role",
                "resume_preview": r.resume_text[:200],
                "result": parsed,
                "created_at": r.created_at,
            })
    finally:
        db.close()

    return render_template("history.html", reports=reports)


@app.route("/logout")
def logout():
    session.pop("user", None)
    return redirect(url_for("login"))


if __name__ == "__main__":
    app.run(debug=os.environ.get("FLASK_DEBUG", "false").lower() == "true")