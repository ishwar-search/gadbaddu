import os
import re
import secrets
import sqlite3
from datetime import datetime
from functools import wraps
from pathlib import Path
from urllib.parse import urlparse

from flask import (
    Flask, render_template, request, redirect,
    url_for, session, flash, abort
)
from werkzeug.security import generate_password_hash, check_password_hash
from werkzeug.utils import secure_filename


# --------------------------------------------------
# GADBADDU - MAIN APPLICATION
# --------------------------------------------------

BASE_DIR = Path(__file__).resolve().parent
INSTANCE_DIR = BASE_DIR / "instance"
UPLOAD_DIR = BASE_DIR / "static" / "uploads"

INSTANCE_DIR.mkdir(exist_ok=True)
UPLOAD_DIR.mkdir(parents=True, exist_ok=True)

app = Flask(__name__)

app.config["SECRET_KEY"] = os.environ.get(
    "SECRET_KEY", "change-this-before-production"
)
app.config["MAX_CONTENT_LENGTH"] = 25 * 1024 * 1024
app.config["UPLOAD_FOLDER"] = str(UPLOAD_DIR)

DATABASE = INSTANCE_DIR / "gadbaddu.db"

ALLOWED_EXTENSIONS = {
    "png", "jpg", "jpeg", "gif", "webp",
    "mp4", "webm", "mov"
}

IMAGE_EXTENSIONS = {"png", "jpg", "jpeg", "gif", "webp"}
VIDEO_EXTENSIONS = {"mp4", "webm", "mov"}


@app.context_processor
def inject_current_user():
    user = current_user()
    return {"user": user, "current_user": user}


# --------------------------------------------------
# DATABASE
# --------------------------------------------------

def get_db():
    conn = sqlite3.connect(DATABASE)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def init_db():
    with get_db() as db:
        db.executescript("""
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT UNIQUE NOT NULL,
            email TEXT UNIQUE NOT NULL,
            password TEXT NOT NULL,
            bio TEXT DEFAULT '',
            avatar TEXT DEFAULT '',
            referral_code TEXT UNIQUE NOT NULL,
            referred_by INTEGER,
            points INTEGER DEFAULT 0,
            created_at TEXT NOT NULL,
            FOREIGN KEY (referred_by) REFERENCES users(id)
        );

        CREATE TABLE IF NOT EXISTS posts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            caption TEXT DEFAULT '',
            media TEXT NOT NULL,
            media_type TEXT NOT NULL,
            created_at TEXT NOT NULL,
            FOREIGN KEY (user_id) REFERENCES users(id)
        );

        CREATE TABLE IF NOT EXISTS follows (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            follower_id INTEGER NOT NULL,
            following_id INTEGER NOT NULL,
            created_at TEXT NOT NULL,
            UNIQUE(follower_id, following_id),
            CHECK(follower_id != following_id),
            FOREIGN KEY (follower_id) REFERENCES users(id),
            FOREIGN KEY (following_id) REFERENCES users(id)
        );

        CREATE TABLE IF NOT EXISTS likes (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            post_id INTEGER NOT NULL,
            created_at TEXT NOT NULL,
            UNIQUE(user_id, post_id),
            FOREIGN KEY (user_id) REFERENCES users(id),
            FOREIGN KEY (post_id) REFERENCES posts(id)
        );

        CREATE TABLE IF NOT EXISTS comments (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            post_id INTEGER NOT NULL,
            comment TEXT NOT NULL,
            created_at TEXT NOT NULL,
            FOREIGN KEY (user_id) REFERENCES users(id),
            FOREIGN KEY (post_id) REFERENCES posts(id)
        );

        CREATE TABLE IF NOT EXISTS messages (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            sender_id INTEGER NOT NULL,
            receiver_id INTEGER NOT NULL,
            message TEXT NOT NULL,
            created_at TEXT NOT NULL,
            FOREIGN KEY (sender_id) REFERENCES users(id),
            FOREIGN KEY (receiver_id) REFERENCES users(id)
        );

        CREATE TABLE IF NOT EXISTS reports (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            reporter_id INTEGER NOT NULL,
            post_id INTEGER NOT NULL,
            reason TEXT NOT NULL,
            created_at TEXT NOT NULL,
            FOREIGN KEY (reporter_id) REFERENCES users(id),
            FOREIGN KEY (post_id) REFERENCES posts(id)
        );

        CREATE TABLE IF NOT EXISTS blocks (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            blocker_id INTEGER NOT NULL,
            blocked_id INTEGER NOT NULL,
            created_at TEXT NOT NULL,
            UNIQUE(blocker_id, blocked_id),
            CHECK(blocker_id != blocked_id),
            FOREIGN KEY (blocker_id) REFERENCES users(id),
            FOREIGN KEY (blocked_id) REFERENCES users(id)
        );

        CREATE TABLE IF NOT EXISTS referrals (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            referrer_id INTEGER NOT NULL,
            referred_id INTEGER UNIQUE NOT NULL,
            points_awarded INTEGER DEFAULT 5,
            created_at TEXT NOT NULL,
            FOREIGN KEY (referrer_id) REFERENCES users(id),
            FOREIGN KEY (referred_id) REFERENCES users(id)
        );

        CREATE INDEX IF NOT EXISTS idx_posts_user
        ON posts(user_id);

        CREATE INDEX IF NOT EXISTS idx_messages_users
        ON messages(sender_id, receiver_id);
        """)


# --------------------------------------------------
# HELPERS
# --------------------------------------------------

def now():
    return datetime.utcnow().isoformat(timespec="seconds")


def current_user():
    user_id = session.get("user_id")

    if not user_id:
        return None

    with get_db() as db:
        return db.execute(
            "SELECT * FROM users WHERE id = ?", (user_id,)
        ).fetchone()


def safe_next_url(target):
    if not target:
        return url_for("index")

    parsed = urlparse(target)

    if parsed.scheme or parsed.netloc:
        return url_for("index")

    if not target.startswith("/") or target.startswith("//"):
        return url_for("index")

    return target


def login_required(function):
    @wraps(function)
    def wrapper(*args, **kwargs):
        if not session.get("user_id"):
            flash("Please login first.", "warning")

            if request.method == "GET":
                next_url = request.full_path

                if next_url.endswith("?"):
                    next_url = next_url[:-1]
            else:
                next_url = request.referrer or url_for("index")

            return redirect(
                url_for("login", next=safe_next_url(next_url))
            )

        return function(*args, **kwargs)

    return wrapper


def allowed_file(filename):
    return (
        "." in filename and
        filename.rsplit(".", 1)[1].lower() in ALLOWED_EXTENSIONS
    )


def blocked_between(db, user_a, user_b):
    result = db.execute("""
        SELECT id FROM blocks
        WHERE (blocker_id = ? AND blocked_id = ?)
           OR (blocker_id = ? AND blocked_id = ?)
    """, (user_a, user_b, user_b, user_a)).fetchone()

    return result is not None


def post_query(db, extra_where="", params=()):
    query = """
        SELECT
            posts.*,
            users.username,
            users.avatar,
            (SELECT COUNT(*) FROM likes
             WHERE likes.post_id = posts.id) AS like_count,
            (SELECT COUNT(*) FROM comments
             WHERE comments.post_id = posts.id) AS comment_count
        FROM posts
        JOIN users ON users.id = posts.user_id
    """

    if extra_where:
        query += " WHERE " + extra_where

    query += " ORDER BY posts.id DESC"

    return db.execute(query, params).fetchall()


# --------------------------------------------------
# HOME / FEED
# --------------------------------------------------

@app.route("/")
def index():
    user = current_user()

    with get_db() as db:
        if user:
            blocked_ids = db.execute("""
                SELECT blocked_id FROM blocks WHERE blocker_id = ?
                UNION
                SELECT blocker_id FROM blocks WHERE blocked_id = ?
            """, (user["id"], user["id"])).fetchall()

            excluded = [row["blocked_id"] for row in blocked_ids]

            if excluded:
                marks = ",".join("?" for _ in excluded)

                posts = post_query(
                    db,
                    f"posts.user_id NOT IN ({marks})",
                    excluded
                )
            else:
                posts = post_query(db)
        else:
            posts = post_query(db)

    return render_template(
        "index.html",
        posts=posts,
        user=user,
        current_user=user
    )


# --------------------------------------------------
# REGISTER
# --------------------------------------------------

@app.route("/register", methods=["GET", "POST"])
def register():
    if session.get("user_id"):
        return redirect(url_for("index"))

    if request.method == "POST":
        username = request.form.get(
            "username", ""
        ).strip().lower()

        email = request.form.get(
            "email", ""
        ).strip().lower()

        password = request.form.get("password", "")

        referral_input = request.form.get(
            "referral_code", ""
        ).strip().upper()

        if not re.fullmatch(r"[a-z0-9_]{3,20}", username):
            flash(
                "Username must be 3-20 characters "
                "and contain only letters, numbers or underscore.",
                "danger"
            )
            return redirect(url_for("register"))

        if len(email) > 150 or "@" not in email:
            flash("Please enter a valid email.", "danger")
            return redirect(url_for("register"))

        if len(password) < 8:
            flash("Password must be at least 8 characters.", "danger")
            return redirect(url_for("register"))

        if len(password) > 128:
            flash("Password is too long.", "danger")
            return redirect(url_for("register"))

        with get_db() as db:
            existing = db.execute("""
                SELECT id FROM users
                WHERE username = ? OR email = ?
            """, (username, email)).fetchone()

            if existing:
                flash("Username or email already exists.", "danger")
                return redirect(url_for("register"))

            referrer = None

            if referral_input:
                referrer = db.execute("""
                    SELECT id FROM users WHERE referral_code = ?
                """, (referral_input,)).fetchone()

                if not referrer:
                    flash("Referral code is not valid.", "danger")
                    return redirect(url_for("register"))

            referral_code = secrets.token_hex(4).upper()

            db.execute("""
                INSERT INTO users
                (username, email, password, referral_code,
                 referred_by, created_at)
                VALUES (?, ?, ?, ?, ?, ?)
            """, (
                username,
                email,
                generate_password_hash(password),
                referral_code,
                referrer["id"] if referrer else None,
                now()
            ))

            new_user = db.execute(
                "SELECT id FROM users WHERE username = ?",
                (username,)
            ).fetchone()

            if referrer:
                db.execute("""
                    INSERT INTO referrals
                    (referrer_id, referred_id, points_awarded, created_at)
                    VALUES (?, ?, 5, ?)
                """, (referrer["id"], new_user["id"], now()))

                db.execute("""
                    UPDATE users SET points = points + 5
                    WHERE id = ?
                """, (referrer["id"],))

        flash("Account created successfully. Please login.", "success")
        return redirect(url_for("login"))

    return render_template("register.html")


# --------------------------------------------------
# LOGIN / LOGOUT
# --------------------------------------------------

@app.route("/login", methods=["GET", "POST"])
def login():
    if session.get("user_id"):
        return redirect(url_for("index"))

    if request.method == "GET":
        session["login_next"] = safe_next_url(
            request.args.get("next", "")
        )

    if request.method == "POST":
        next_url = safe_next_url(
            request.form.get("next")
            or session.get("login_next", "")
        )

        username_or_email = request.form.get(
            "username", ""
        ).strip().lower()

        if not username_or_email:
            username_or_email = request.form.get(
                "email", ""
            ).strip().lower()

        password = request.form.get("password", "")

        with get_db() as db:
            user = db.execute("""
                SELECT * FROM users
                WHERE username = ? OR email = ?
            """, (username_or_email, username_or_email)).fetchone()

        if user and check_password_hash(user["password"], password):
            session.clear()
            session["user_id"] = user["id"]

            flash("Welcome to Gadbaddu!", "success")
            return redirect(next_url)

        flash("Incorrect username/email or password.", "danger")

    return render_template("login.html")


@app.route("/logout")
def logout():
    session.clear()
    flash("You have been logged out.", "success")
    return redirect(url_for("index"))


# --------------------------------------------------
# EXPLORE / SEARCH
# --------------------------------------------------

@app.route("/explore")
def explore():
    user = current_user()
    search_query = request.args.get("q", "").strip()

    with get_db() as db:
        if search_query:
            users = db.execute("""
                SELECT id, username, bio, avatar
                FROM users
                WHERE username LIKE ?
                ORDER BY username
                LIMIT 50
            """, (f"%{search_query}%",)).fetchall()

            posts = post_query(
                db,
                "posts.caption LIKE ?",
                (f"%{search_query}%",)
            )
        else:
            users = db.execute("""
                SELECT id, username, bio, avatar
                FROM users
                ORDER BY id DESC LIMIT 50
            """).fetchall()

            posts = post_query(db)

    return render_template(
        "explore.html",
        users=users,
        posts=posts,
        user=user,
        current_user=user,
        search_query=search_query
    )


@app.route("/search")
def search():
    return redirect(
        url_for("explore", q=request.args.get("q", ""))
    )


# --------------------------------------------------
# PROFILE
# --------------------------------------------------

@app.route("/profile")
@login_required
def my_profile():
    user = current_user()

    return redirect(
        url_for("profile", username=user["username"])
    )


@app.route("/profile/<username>")
@login_required
def profile(username):
    viewer = current_user()

    with get_db() as db:
        profile_user = db.execute("""
            SELECT * FROM users WHERE username = ?
        """, (username.lower(),)).fetchone()

        if not profile_user:
            abort(404)

        if blocked_between(
            db, viewer["id"], profile_user["id"]
        ):
            flash("This profile is unavailable.", "warning")
            return redirect(url_for("index"))

        posts = post_query(
            db,
            "posts.user_id = ?",
            (profile_user["id"],)
        )

        followers = db.execute("""
            SELECT COUNT(*) AS total FROM follows
            WHERE following_id = ?
        """, (profile_user["id"],)).fetchone()["total"]

        following = db.execute("""
            SELECT COUNT(*) AS total FROM follows
            WHERE follower_id = ?
        """, (profile_user["id"],)).fetchone()["total"]

        is_following = db.execute("""
            SELECT id FROM follows
            WHERE follower_id = ? AND following_id = ?
        """, (viewer["id"], profile_user["id"])).fetchone() is not None

    return render_template(
        "profile.html",
        profile_user=profile_user,
        profile=profile_user,
        user=viewer,
        current_user=viewer,
        posts=posts,
        followers=followers,
        following=following,
        is_following=is_following
    )


# --------------------------------------------------
# EDIT PROFILE
# --------------------------------------------------

@app.route("/edit-profile", methods=["GET", "POST"])
@login_required
def edit_profile():
    user = current_user()

    if request.method == "POST":
        username = request.form.get(
            "username", ""
        ).strip().lower()

        bio = request.form.get(
            "bio", ""
        ).strip()[:250]

        if not re.fullmatch(r"[a-z0-9_]{3,20}", username):
            flash(
                "Username must be 3-20 characters and use only letters, numbers or underscore.",
                "danger"
            )
            return redirect(url_for("edit_profile"))

        with get_db() as db:
            existing = db.execute(
                "SELECT id FROM users WHERE username = ? AND id != ?",
                (username, session["user_id"])
            ).fetchone()

            if existing:
                flash("That username is already taken.", "danger")
                return redirect(url_for("edit_profile"))

            db.execute(
                "UPDATE users SET username = ?, bio = ? WHERE id = ?",
                (username, bio, session["user_id"])
            )

        flash("Profile updated successfully.", "success")

        return redirect(
            url_for("profile", username=username)
        )

    return render_template(
        "edit_profile.html",
        user=user,
        current_user=user,
        profile_user=user
    )
    # --------------------------------------------------
# FOLLOW / UNFOLLOW
# --------------------------------------------------

@app.route("/follow/<username>", methods=["POST"])
@login_required
def follow(username):
    with get_db() as db:
        target = db.execute(
            "SELECT id FROM users WHERE username = ?",
            (username.lower(),)
        ).fetchone()

        if not target:
            abort(404)

        my_id = session["user_id"]
        target_id = target["id"]

        if my_id == target_id:
            flash("You cannot follow yourself.", "warning")

        elif blocked_between(db, my_id, target_id):
            flash("Follow is unavailable.", "warning")

        else:
            existing = db.execute("""
                SELECT id FROM follows
                WHERE follower_id = ? AND following_id = ?
            """, (my_id, target_id)).fetchone()

            if existing:
                db.execute(
                    "DELETE FROM follows WHERE id = ?",
                    (existing["id"],)
                )
                flash("You unfollowed this user.", "success")
            else:
                db.execute("""
                    INSERT INTO follows
                    (follower_id, following_id, created_at)
                    VALUES (?, ?, ?)
                """, (my_id, target_id, now()))

                flash("You are now following this user.", "success")

    return redirect(url_for("profile", username=username))


# --------------------------------------------------
# CREATE POST / UPLOAD
# --------------------------------------------------

@app.route("/upload", methods=["GET", "POST"])
@login_required
def upload():
    if request.method == "POST":
        file = request.files.get("media")
        caption = request.form.get(
            "caption", ""
        ).strip()[:2000]

        if not file or not file.filename:
            flash("Please select an image or video.", "danger")
            return redirect(url_for("upload"))

        if not allowed_file(file.filename):
            flash("This file type is not allowed.", "danger")
            return redirect(url_for("upload"))

        extension = file.filename.rsplit(".", 1)[1].lower()

        if extension in IMAGE_EXTENSIONS:
            media_type = "image"
        elif extension in VIDEO_EXTENSIONS:
            media_type = "video"
        else:
            flash("Unsupported file.", "danger")
            return redirect(url_for("upload"))

        safe_name = secure_filename(file.filename)

        if not safe_name:
            flash("Invalid filename.", "danger")
            return redirect(url_for("upload"))

        filename = f"{secrets.token_hex(16)}_{safe_name}"

        save_path = UPLOAD_DIR / filename
        file.save(save_path)

        with get_db() as db:
            db.execute("""
                INSERT INTO posts
                (user_id, caption, media, media_type, created_at)
                VALUES (?, ?, ?, ?, ?)
            """, (
                session["user_id"],
                caption,
                filename,
                media_type,
                now()
            ))

        flash("Your post has been published!", "success")
        return redirect(url_for("index"))

    return render_template("upload.html")


# --------------------------------------------------
# LIKE / UNLIKE
# --------------------------------------------------

@app.route("/like/<int:post_id>", methods=["POST"])
@login_required
def like(post_id):
    with get_db() as db:
        post = db.execute(
            "SELECT id FROM posts WHERE id = ?",
            (post_id,)
        ).fetchone()

        if not post:
            abort(404)

        existing = db.execute("""
            SELECT id FROM likes
            WHERE user_id = ? AND post_id = ?
        """, (session["user_id"], post_id)).fetchone()

        if existing:
            db.execute(
                "DELETE FROM likes WHERE id = ?",
                (existing["id"],)
            )
        else:
            db.execute("""
                INSERT INTO likes (user_id, post_id, created_at)
                VALUES (?, ?, ?)
            """, (session["user_id"], post_id, now()))

    return redirect(request.referrer or url_for("index"))


# --------------------------------------------------
# COMMENTS
# --------------------------------------------------

@app.route("/comment/<int:post_id>", methods=["POST"])
@login_required
def comment(post_id):
    comment_text = request.form.get(
        "comment", ""
    ).strip()

    if not comment_text or len(comment_text) > 1000:
        flash(
            "Comment must be between 1 and 1000 characters.",
            "warning"
        )
        return redirect(request.referrer or url_for("index"))

    with get_db() as db:
        post = db.execute(
            "SELECT id FROM posts WHERE id = ?",
            (post_id,)
        ).fetchone()

        if not post:
            abort(404)

        db.execute("""
            INSERT INTO comments (user_id, post_id, comment, created_at)
            VALUES (?, ?, ?, ?)
        """, (
            session["user_id"],
            post_id,
            comment_text,
            now()
        ))

    flash("Comment added.", "success")

    return redirect(request.referrer or url_for("index"))


# --------------------------------------------------
# MESSAGES
# --------------------------------------------------

@app.route("/messages")
@login_required
def messages():
    my_id = session["user_id"]

    with get_db() as db:
        contacts = db.execute("""
            SELECT users.id, users.username, users.avatar,
                   MAX(messages.id) AS last_message_id
            FROM messages
            JOIN users ON
                users.id = CASE
                    WHEN messages.sender_id = ?
                    THEN messages.receiver_id
                    ELSE messages.sender_id
                END
            WHERE messages.sender_id = ? OR messages.receiver_id = ?
            GROUP BY users.id
            ORDER BY last_message_id DESC
        """, (my_id, my_id, my_id)).fetchall()

    return render_template(
        "messages.html",
        contacts=contacts,
        messages=[],
        selected_user=None,
        user=current_user(),
        current_user=current_user()
    )


@app.route("/messages/<username>", methods=["GET", "POST"])
@login_required
def chat(username):
    my_id = session["user_id"]

    with get_db() as db:
        other = db.execute(
            "SELECT id, username, avatar FROM users WHERE username = ?",
            (username.lower(),)
        ).fetchone()

        if not other:
            abort(404)

        other_id = other["id"]

        if blocked_between(db, my_id, other_id):
            flash("Messaging is unavailable.", "warning")
            return redirect(url_for("messages"))

        if request.method == "POST":
            message_text = request.form.get(
                "message", ""
            ).strip()

            if not message_text or len(message_text) > 2000:
                flash(
                    "Message must be between 1 and 2000 characters.",
                    "warning"
                )
            else:
                db.execute("""
                    INSERT INTO messages
                    (sender_id, receiver_id, message, created_at)
                    VALUES (?, ?, ?, ?)
                """, (
                    my_id,
                    other_id,
                    message_text,
                    now()
                ))

                return redirect(
                    url_for("chat", username=username)
                )

        conversation = db.execute("""
            SELECT messages.*, sender.username AS sender_username
            FROM messages
            JOIN users AS sender ON sender.id = messages.sender_id
            WHERE
                (messages.sender_id = ? AND messages.receiver_id = ?)
                OR
                (messages.sender_id = ? AND messages.receiver_id = ?)
            ORDER BY messages.id ASC
            LIMIT 300
        """, (
            my_id,
            other_id,
            other_id,
            my_id
        )).fetchall()

    return render_template(
        "messages.html",
        contacts=[],
        messages=conversation,
        selected_user=other,
        user=current_user(),
        current_user=current_user()
    )


# --------------------------------------------------
# REPORT POST
# --------------------------------------------------

@app.route("/report/<int:post_id>", methods=["POST"])
@login_required
def report_post(post_id):
    reason = request.form.get(
        "reason", ""
    ).strip()[:500]

    if not reason:
        reason = "User reported this post"

    with get_db() as db:
        post = db.execute(
            "SELECT id FROM posts WHERE id = ?",
            (post_id,)
        ).fetchone()

        if not post:
            abort(404)

        db.execute("""
            INSERT INTO reports (reporter_id, post_id, reason, created_at)
            VALUES (?, ?, ?, ?)
        """, (
            session["user_id"],
            post_id,
            reason,
            now()
        ))

    flash("Report submitted for review.", "success")

    return redirect(request.referrer or url_for("index"))


# --------------------------------------------------
# BLOCK / UNBLOCK USER
# --------------------------------------------------

@app.route("/block/<username>", methods=["POST"])
@login_required
def block_user(username):
    with get_db() as db:
        target = db.execute(
            "SELECT id FROM users WHERE username = ?",
            (username.lower(),)
        ).fetchone()

        if not target:
            abort(404)

        my_id = session["user_id"]
        target_id = target["id"]

        if my_id == target_id:
            flash("You cannot block yourself.", "warning")
        else:
            db.execute("""
                INSERT OR IGNORE INTO blocks
                (blocker_id, blocked_id, created_at)
                VALUES (?, ?, ?)
            """, (my_id, target_id, now()))

            db.execute("""
                DELETE FROM follows
                WHERE (follower_id = ? AND following_id = ?)
                   OR (follower_id = ? AND following_id = ?)
            """, (my_id, target_id, target_id, my_id))

            flash("User blocked.", "success")

    return redirect(url_for("index"))


@app.route("/unblock/<username>", methods=["POST"])
@login_required
def unblock_user(username):
    with get_db() as db:
        target = db.execute(
            "SELECT id FROM users WHERE username = ?",
            (username.lower(),)
        ).fetchone()

        if target:
            db.execute("""
                DELETE FROM blocks
                WHERE blocker_id = ? AND blocked_id = ?
            """, (session["user_id"], target["id"]))

    flash("User unblocked.", "success")

    return redirect(
        url_for("profile", username=username)
    )
    # --------------------------------------------------
# REFERRAL / POINTS
# --------------------------------------------------

@app.route("/referrals")
@login_required
def referrals():
    my_id = session["user_id"]

    with get_db() as db:
        user = db.execute(
            "SELECT * FROM users WHERE id = ?",
            (my_id,)
        ).fetchone()

        referral_list = db.execute("""
            SELECT users.username, referrals.points_awarded,
                   referrals.created_at
            FROM referrals
            JOIN users ON users.id = referrals.referred_id
            WHERE referrals.referrer_id = ?
            ORDER BY referrals.id DESC
        """, (my_id,)).fetchall()

    return render_template(
        "profile.html",
        profile_user=user,
        profile=user,
        user=user,
        current_user=user,
        posts=[],
        followers=0,
        following=0,
        is_following=False,
        referral_list=referral_list,
        referral_code=user["referral_code"],
        points=user["points"]
    )


# --------------------------------------------------
# SETTINGS
# --------------------------------------------------

@app.route("/settings")
@login_required
def settings():
    user = current_user()

    return render_template(
        "settings.html",
        user=user,
        current_user=user
    )


# --------------------------------------------------
# NOTIFICATIONS
# --------------------------------------------------

@app.route("/notifications")
@login_required
def notifications():
    user = current_user()

    return render_template(
        "notifications.html",
        notifications=[],
        user=user,
        current_user=user
    )


# --------------------------------------------------
# TERMS AND CONDITIONS
# --------------------------------------------------

@app.route("/terms")
def terms():
    user = current_user()

    return render_template(
        "terms.html",
        user=user,
        current_user=user
    )


# --------------------------------------------------
# PRIVACY POLICY
# --------------------------------------------------

@app.route("/privacy")
def privacy():
    user = current_user()

    return render_template(
        "privacy.html",
        user=user,
        current_user=user
    )


# --------------------------------------------------
# ERROR HANDLERS
# --------------------------------------------------

@app.errorhandler(404)
def page_not_found(error):
    return "Gadbaddu: Page not found (404)", 404


@app.errorhandler(413)
def file_too_large(error):
    flash(
        "File is too large. Maximum size is 25 MB.",
        "danger"
    )

    return redirect(
        request.referrer or url_for("index")
    )


@app.errorhandler(500)
def server_error(error):
    return "Something went wrong. Please try again later.", 500


# --------------------------------------------------
# START APPLICATION
# --------------------------------------------------

init_db()


if __name__ == "__main__":
    app.run(debug=False)
