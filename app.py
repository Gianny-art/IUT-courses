

from flask import Flask, render_template, request, redirect, url_for, session, jsonify
import sqlite3
from flask_socketio import SocketIO, emit, join_room
import openai
from werkzeug.utils import secure_filename
from functools import wraps
import os
import re
from datetime import datetime
from flask_mail import Mail, Message

app = Flask(__name__)
# Use environment variables for sensitive keys in production
app.secret_key = os.getenv('FLASK_SECRET_KEY', 'dev-secret')  # set FLASK_SECRET_KEY in production
# OpenAI API key from environment (do NOT store secrets in the repo)
app.config['OPENAI_API_KEY'] = os.getenv('OPENAI_API_KEY')
socketio = SocketIO(app)

# --- Configuration upload ---
UPLOAD_FOLDER = os.path.join(os.path.dirname(__file__), 'static', 'uploads')
os.makedirs(UPLOAD_FOLDER, exist_ok=True)
app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER
# Limit upload size to 15 MB
app.config['MAX_CONTENT_LENGTH'] = 15 * 1024 * 1024
ALLOWED_EXTENSIONS = {'pdf', 'doc', 'docx', 'ppt', 'pptx', 'txt', 'zip', 'rar', 'jpg', 'jpeg', 'png', 'gif', 'mp4', 'mov'}

def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

# OpenAI key retrieval helper (supports env var, app config, or module-level constant)
def get_openai_api_key():
    # Priority: app.config > module-level OPENAI_API_KEY > environment > openai.api_key
    key = None
    try:
        key = app.config.get('OPENAI_API_KEY')
    except Exception:
        key = None
    if not key:
        key = globals().get('OPENAI_API_KEY')
    if not key:
        key = os.getenv('OPENAI_API_KEY')
    if not key:
        key = getattr(openai, 'api_key', None)
    return key

# Informational message at startup (no secret displayed)
if get_openai_api_key():
    print('OpenAI key: configured (source: env/app config/constant)')
else:
    print('OpenAI key: NOT configured; assistant endpoints will return an explanatory error')

# --- Connexion à la base de données ---

def get_db_connection():
    conn = sqlite3.connect(os.path.join(os.path.dirname(__file__), 'database', 'iut_courses.db'))
    conn.row_factory = sqlite3.Row
    return conn

# Ensure required DB schema exists (adds columns/tables when missing)
def ensure_db_schema():
    conn = get_db_connection()
    cur = conn.cursor()
    # Add image column to questions table if missing
    try:
        cur.execute("PRAGMA table_info(questions)")
        cols = [r[1] for r in cur.fetchall()]
        if 'image' not in cols:
            try:
                cur.execute("ALTER TABLE questions ADD COLUMN image TEXT")
            except Exception:
                pass
        # add answer_type column for response size/type
        if 'answer_type' not in cols:
            try:
                cur.execute("ALTER TABLE questions ADD COLUMN answer_type TEXT DEFAULT 'short'")
            except Exception:
                pass
    except Exception:
        pass

    # Create exam-related tables if they don't exist
    cur.execute("""
        CREATE TABLE IF NOT EXISTS examens (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            unite_id INTEGER,
            titre TEXT NOT NULL,
            date_debut DATETIME,
            duree INTEGER
        )
    """)

    cur.execute("""
        CREATE TABLE IF NOT EXISTS questions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            exam_id INTEGER,
            question TEXT NOT NULL,
            reponse_correcte TEXT,
            image TEXT
        )
    """)

    cur.execute("""
        CREATE TABLE IF NOT EXISTS resultats_exam (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            exam_id INTEGER,
            user_id INTEGER,
            score INTEGER,
            score_percentage REAL DEFAULT 0,
            responses TEXT,
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP
        )
    """)

    # Forum messages
    cur.execute("""
        CREATE TABLE IF NOT EXISTS forum_messages (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            unite_id INTEGER NOT NULL,
            user_id INTEGER NOT NULL,
            content TEXT NOT NULL,
            share_whatsapp INTEGER DEFAULT 0,
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP
        )
    """)

    # Chat system tables (idempotent creation)
    cur.execute("""
        CREATE TABLE IF NOT EXISTS chats (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            title TEXT,
            owner_id INTEGER,
            is_forum INTEGER DEFAULT 0,
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP
        )
    """)
    # Ensure columns exist for older DBs (ALTER TABLE ADD COLUMN is noop if column exists)
    try:
        cur.execute("PRAGMA table_info(chats)")
        cols = [r[1] for r in cur.fetchall()]
        if 'owner_id' not in cols:
            try:
                cur.execute("ALTER TABLE chats ADD COLUMN owner_id INTEGER")
            except Exception:
                pass
        if 'is_forum' not in cols:
            try:
                cur.execute("ALTER TABLE chats ADD COLUMN is_forum INTEGER DEFAULT 0")
            except Exception:
                pass
        if 'created_at' not in cols:
            try:
                cur.execute("ALTER TABLE chats ADD COLUMN created_at DATETIME DEFAULT CURRENT_TIMESTAMP")
            except Exception:
                pass
    except Exception:
        pass
    # Create index safely (older DBs may lack column until ALTER above is applied)
    try:
        cur.execute("CREATE INDEX IF NOT EXISTS idx_chats_owner ON chats(owner_id)")
    except Exception:
        pass

    cur.execute("""
        CREATE TABLE IF NOT EXISTS chat_participants (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            chat_id INTEGER NOT NULL,
            user_id INTEGER NOT NULL,
            role TEXT DEFAULT 'member',
            added_at DATETIME DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY(chat_id) REFERENCES chats(id),
            FOREIGN KEY(user_id) REFERENCES users(id)
        )
    """)
    cur.execute("CREATE INDEX IF NOT EXISTS idx_chat_participants_chat ON chat_participants(chat_id)")
    cur.execute("CREATE INDEX IF NOT EXISTS idx_chat_participants_user ON chat_participants(user_id)")

    cur.execute("""
        CREATE TABLE IF NOT EXISTS messages (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            chat_id INTEGER NOT NULL,
            user_id INTEGER NOT NULL,
            content TEXT,
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
            deleted INTEGER DEFAULT 0,
            FOREIGN KEY(chat_id) REFERENCES chats(id),
            FOREIGN KEY(user_id) REFERENCES users(id)
        )
    """)
    cur.execute("CREATE INDEX IF NOT EXISTS idx_messages_chat_created ON messages(chat_id, created_at)")

    cur.execute("""
        CREATE TABLE IF NOT EXISTS attachments (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            message_id INTEGER NOT NULL,
            filename TEXT NOT NULL,
            original_name TEXT,
            mime TEXT,
            size INTEGER,
            uploaded_at DATETIME DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY(message_id) REFERENCES messages(id)
        )
    """)
    cur.execute("CREATE INDEX IF NOT EXISTS idx_attachments_message ON attachments(message_id)")

    # Purge messages older than 7 days on startup (one-off maintenance)
    try:
        cur.execute("DELETE FROM messages WHERE created_at <= DATETIME('now','-7 days')")
    except Exception:
        pass


    # Formations table
    cur.execute("""
        CREATE TABLE IF NOT EXISTS formations (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            titre TEXT NOT NULL,
            description TEXT,
            categorie TEXT,
            filename TEXT NOT NULL,
            uploaded_by INTEGER,
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP
        )
    """)

    # Table to track currently connected users (presence)
    cur.execute("""
        CREATE TABLE IF NOT EXISTS online_users (
            user_id INTEGER PRIMARY KEY,
            connected_at DATETIME DEFAULT CURRENT_TIMESTAMP
        )
    """)

    conn.commit()
    conn.close()

# Call schema ensure on startup
ensure_db_schema()

# Expose openai key presence to templates
@app.context_processor
def inject_admin_status():
    return {'openai_key_configured': bool(get_openai_api_key())}

# --- Droits admin ---
ADMIN_EMAIL = "giannyfoapa@gmail.com"

def is_admin():
    return session.get("user_email") == ADMIN_EMAIL

def admin_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if not is_admin():
            return "Accès réservé à l'administrateur.", 403
        return f(*args, **kwargs)
    return decorated_function

# --- Page d'accueil dynamique (mur Facebook ou accueil classique) ---
@app.route("/", methods=["GET", "POST"])
def index():
    if "user_id" not in session:
        return render_template("index.html")
    conn = get_db_connection()
    # Publication d'un post étudiant (en attente de validation)
    if request.method == "POST":
        content = request.form.get("content")
        bg_color = request.form.get("bg_color")
        image = None
        if "image" in request.files:
            file = request.files["image"]
            if file and file.filename:
                filename = secure_filename(file.filename)
                file.save(os.path.join(app.config['UPLOAD_FOLDER'], filename))
                image = filename
        conn.execute(
            "INSERT INTO posts (user_id, content, image, bg_color, approved) VALUES (?, ?, ?, ?, 0)",
            (session["user_id"], content, image, bg_color)
        )
        conn.commit()
    # Affichage des posts validés
    posts = conn.execute("""
        SELECT p.*, u.nom, u.prenom, u.photo, u.email,
            (SELECT COUNT(*) FROM post_likes WHERE post_id = p.id) as likes
        FROM posts p
        JOIN users u ON p.user_id = u.id
        WHERE p.approved=1
        ORDER BY p.created_at DESC
    """).fetchall()
    # Charger les commentaires pour chaque post
    posts = [dict(post) for post in posts]
    for post in posts:
        comments = conn.execute("""
            SELECT c.*, u.nom as username FROM post_comments c
            JOIN users u ON c.user_id = u.id
            WHERE c.post_id=?
            ORDER BY c.created_at ASC
        """, (post['id'],)).fetchall()
        post['comments'] = comments
    conn.close()
    return render_template("feed.html", posts=posts, is_admin=is_admin())
# ...reste du code...
# --- Déconnexion ---
@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("login"))

# Real-time forum send/join handlers removed — forum messages are now posted via a regular POST endpoint (no Socket.IO).

# ---------- New chat system socket handlers and APIs ----------

# Real-time forum send/join handlers removed — forum messages are now posted via a regular POST endpoint (no Socket.IO).

# ---------- New chat system socket handlers and APIs ----------

# create_chat handler removed — chat feature is disabled.

@socketio.on('connect', namespace='/notifications')
def notifications_connect():
    # join the personal room so admin or other services can send targeted notifications
    if 'user_id' in session:
        uid = session['user_id']
        join_room(f'user_{uid}')
        try:
            conn = get_db_connection()
            cur = conn.cursor()
            # insert or replace presence for this user
            cur.execute("INSERT OR REPLACE INTO online_users (user_id, connected_at) VALUES (?, CURRENT_TIMESTAMP)", (uid,))
            conn.commit()
        except Exception as e:
            print('Presence insert error:', e)
        finally:
            try:
                conn.close()
            except Exception:
                pass

@socketio.on('disconnect', namespace='/notifications')
def notifications_disconnect():
    # remove presence on disconnect
    if 'user_id' in session:
        try:
            conn = get_db_connection()
            cur = conn.cursor()
            cur.execute("DELETE FROM online_users WHERE user_id=?", (session['user_id'],))
            conn.commit()
            conn.close()
        except Exception as e:
            print('Presence remove error:', e)

# ----- Chat endpoints & Socket.IO handlers -----

@app.route('/chats')
def list_chats():
    if 'user_id' not in session:
        return redirect(url_for('login'))
    return render_template('chats.html')

@app.route('/api/chats')
def api_chats():
    # Return chats the user participates in (owner or member)
    if 'user_id' not in session:
        return jsonify([])
    uid = session['user_id']
    conn = get_db_connection()
    try:
        rows = conn.execute("""
            SELECT c.id, c.title, c.owner_id, c.created_at, (
                SELECT COUNT(*) FROM chat_participants cp WHERE cp.chat_id=c.id
            ) as participants_count,
            (SELECT content FROM messages m WHERE m.chat_id=c.id ORDER BY m.created_at DESC LIMIT 1) as last_message,
            (SELECT created_at FROM messages m WHERE m.chat_id=c.id ORDER BY m.created_at DESC LIMIT 1) as last_message_at
            FROM chats c
            JOIN chat_participants cp ON cp.chat_id=c.id
            WHERE cp.user_id=?
            ORDER BY last_message_at DESC, c.created_at DESC
        """, (uid,)).fetchall()
        out = []
        for r in rows:
            out.append({'id': r['id'], 'title': r['title'], 'owner_id': r['owner_id'], 'participants': r['participants_count'], 'last_message': r['last_message'], 'last_message_at': r['last_message_at']})
        return jsonify(out)
    finally:
        conn.close()

@app.route('/chat/create', methods=['POST'])
def create_chat():
    if 'user_id' not in session:
        return jsonify({'ok': False, 'error': 'Authentication required'}), 403
    title = request.form.get('title', '').strip() or None
    participants = request.form.get('participants')
    if participants:
        try:
            participants = [int(x) for x in participants.split(',') if x.strip()]
        except Exception:
            participants = []
    else:
        participants = []
    uid = session['user_id']
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute('INSERT INTO chats (title, owner_id) VALUES (?,?)', (title, uid))
    chat_id = cur.lastrowid
    # add owner as participant with role owner
    cur.execute('INSERT INTO chat_participants (chat_id, user_id, role) VALUES (?,?,?)', (chat_id, uid, 'owner'))
    for p in participants:
        if p == uid: continue
        try:
            cur.execute('INSERT INTO chat_participants (chat_id, user_id, role) VALUES (?,?,?)', (chat_id, p, 'member'))
            # notify participants about invite
            try:
                inviter = conn.execute('SELECT nom, prenom FROM users WHERE id=?', (uid,)).fetchone()
                inviter_name = (inviter['nom'] + ' ' + (inviter['prenom'] or '')).strip() if inviter else 'Quelqu\'un'
            except Exception:
                inviter_name = 'Quelqu\'un'
            socketio.emit('chat_invite', {'chat_id': chat_id, 'from_id': uid, 'from_name': inviter_name, 'chat_title': title}, namespace='/notifications', room=f'user_{p}')
        except Exception:
            pass
    conn.commit()
    conn.close()
    return jsonify({'ok': True, 'chat_id': chat_id})

@app.route('/chat/<int:chat_id>/add_participant', methods=['POST'])
def chat_add_participant(chat_id):
    if 'user_id' not in session:
        return jsonify({'ok': False, 'error': 'Authentication required'}), 403
    uid = session['user_id']
    user_to_add = int(request.form.get('user_id'))
    conn = get_db_connection()
    cur = conn.cursor()
    # only owner or admin can add
    row = cur.execute('SELECT role FROM chat_participants WHERE chat_id=? AND user_id=?', (chat_id, uid)).fetchone()
    if not row or row['role'] not in ('owner', 'admin'):
        conn.close()
        return jsonify({'ok': False, 'error': 'Not authorized'}), 403
    cur.execute('INSERT INTO chat_participants (chat_id, user_id, role) VALUES (?,?,?)', (chat_id, user_to_add, 'member'))
    conn.commit()
    # notify the new participant with inviter name and chat title
    try:
        inviter = cur.execute('SELECT nom, prenom FROM users WHERE id=?', (uid,)).fetchone()
        inviter_name = (inviter['nom'] + ' ' + (inviter['prenom'] or '')).strip() if inviter else 'Quelqu\'un'
        # fetch chat title
        chat_row = cur.execute('SELECT title FROM chats WHERE id=?', (chat_id,)).fetchone()
        chat_title = chat_row['title'] if chat_row and 'title' in chat_row.keys() else None
        socketio.emit('chat_invite', {'chat_id': chat_id, 'from_id': uid, 'from_name': inviter_name, 'chat_title': chat_title}, namespace='/notifications', room=f'user_{user_to_add}')
    except Exception:
        pass
    conn.close()
    return jsonify({'ok': True})

@app.route('/chat/<int:chat_id>/remove_participant', methods=['POST'])
def chat_remove_participant(chat_id):
    if 'user_id' not in session:
        return jsonify({'ok': False, 'error': 'Authentication required'}), 403
    uid = session['user_id']
    user_to_remove = int(request.form.get('user_id'))
    conn = get_db_connection()
    cur = conn.cursor()
    row = cur.execute('SELECT role FROM chat_participants WHERE chat_id=? AND user_id=?', (chat_id, uid)).fetchone()
    if not row or row['role'] not in ('owner', 'admin'):
        conn.close()
        return jsonify({'ok': False, 'error': 'Not authorized'}), 403
    cur.execute('DELETE FROM chat_participants WHERE chat_id=? AND user_id=?', (chat_id, user_to_remove))
    conn.commit()
    conn.close()
    return jsonify({'ok': True})

@app.route('/chat/messages/<int:chat_id>')
def chat_messages(chat_id):
    if 'user_id' not in session:
        return jsonify({'ok': False, 'error': 'Authentication required'}), 403
    uid = session['user_id']
    conn = get_db_connection()
    # check participant
    part = conn.execute('SELECT id FROM chat_participants WHERE chat_id=? AND user_id=?', (chat_id, uid)).fetchone()
    if not part:
        conn.close()
        return jsonify({'ok': False, 'error': 'Not a participant'}), 403
    rows = conn.execute('SELECT m.*, u.nom, u.prenom FROM messages m JOIN users u ON u.id=m.user_id WHERE m.chat_id=? AND m.deleted=0 ORDER BY m.created_at DESC LIMIT 200', (chat_id,)).fetchall()
    res = []
    for r in rows:
        res.append({'id': r['id'], 'user_id': r['user_id'], 'username': (r['nom'] + ' ' + (r['prenom'] or '')).strip(), 'content': r['content'], 'created_at': r['created_at']})
    conn.close()
    return jsonify({'ok': True, 'messages': list(reversed(res))})

@app.route('/chat/message', methods=['POST'])
def chat_message_post():
    if 'user_id' not in session:
        return jsonify({'ok': False, 'error': 'Authentication required'}), 403
    uid = session['user_id']
    chat_id = int(request.form.get('chat_id'))
    content = request.form.get('content', '').strip()
    if not content and not request.files.getlist('file'):
        return jsonify({'ok': False, 'error': 'Empty message'}), 400
    conn = get_db_connection()
    cur = conn.cursor()
    # check participant
    part = cur.execute('SELECT role FROM chat_participants WHERE chat_id=? AND user_id=?', (chat_id, uid)).fetchone()
    if not part:
        conn.close()
        return jsonify({'ok': False, 'error': 'Not a participant'}), 403
    cur.execute('INSERT INTO messages (chat_id, user_id, content) VALUES (?,?,?)', (chat_id, uid, content))
    msg_id = cur.lastrowid
    files = []
    # support multiple files
    for f in request.files.getlist('file'):
        if f and f.filename and allowed_file(f.filename):
            fname = secure_filename(f.filename)
            dest = os.path.join(app.config['UPLOAD_FOLDER'], f"chat_{msg_id}_" + fname)
            f.save(dest)
            cur.execute('INSERT INTO attachments (message_id, filename, original_name, mime, size) VALUES (?,?,?,?,?)', (msg_id, os.path.basename(dest), f.filename, f.mimetype or '', os.path.getsize(dest)))
    conn.commit()
    # emit via socket.io to room
    try:
        socketio.emit('new_message', {'chat_id': chat_id, 'message_id': msg_id, 'user_id': uid, 'content': content, 'created_at': datetime.now().isoformat()}, namespace='/chat', room=f'chat_{chat_id}')
    except Exception:
        pass
    conn.close()
    return jsonify({'ok': True, 'message_id': msg_id})

# Socket.IO: join chat room
@socketio.on('join_chat', namespace='/chat')
def on_join_chat(data):
    chat_id = data.get('chat_id')
    if not chat_id or 'user_id' not in session:
        return
    uid = session['user_id']
    conn = get_db_connection()
    part = conn.execute('SELECT id FROM chat_participants WHERE chat_id=? AND user_id=?', (chat_id, uid)).fetchone()
    conn.close()
    if not part:
        return
    join_room(f'chat_{chat_id}')

# Socket.IO: send message (alternative real-time path)
@socketio.on('send_message', namespace='/chat')
def on_send_message(data):
    chat_id = data.get('chat_id')
    content = data.get('content', '')
    if 'user_id' not in session:
        return
    uid = session['user_id']
    if not content.strip():
        return
    conn = get_db_connection()
    cur = conn.cursor()
    part = cur.execute('SELECT id FROM chat_participants WHERE chat_id=? AND user_id=?', (chat_id, uid)).fetchone()
    if not part:
        conn.close()
        return
    cur.execute('INSERT INTO messages (chat_id, user_id, content) VALUES (?,?,?)', (chat_id, uid, content))
    msg_id = cur.lastrowid
    conn.commit()
    conn.close()
    emit('new_message', {'chat_id': chat_id, 'message_id': msg_id, 'user_id': uid, 'content': content, 'created_at': datetime.now().isoformat()}, room=f'chat_{chat_id}', namespace='/chat')

# --- Admin moderation endpoints for chats/messages ---
@app.route('/admin/api/chats')
@admin_required
def admin_api_chats():
    conn = get_db_connection()
    try:
        rows = conn.execute('SELECT c.*, (SELECT COUNT(*) FROM chat_participants cp WHERE cp.chat_id=c.id) as participants FROM chats c ORDER BY c.created_at DESC').fetchall()
        return jsonify([dict(r) for r in rows])
    finally:
        conn.close()

@app.route('/admin/api/chat/<int:chat_id>/participants')
@admin_required
def admin_chat_participants(chat_id):
    conn = get_db_connection()
    try:
        rows = conn.execute('SELECT u.id, (u.nom || " " || IFNULL(u.prenom,"") ) as name FROM chat_participants cp JOIN users u ON u.id=cp.user_id WHERE cp.chat_id=?', (chat_id,)).fetchall()
        return jsonify([{'id': r['id'], 'name': r['name']} for r in rows])
    finally:
        conn.close()

@app.route('/admin/chat/<int:chat_id>/delete', methods=['POST'])
@admin_required
def admin_delete_chat(chat_id):
    conn = get_db_connection()
    cur = conn.cursor()
    # delete attachments files
    atts = cur.execute('SELECT filename FROM attachments WHERE message_id IN (SELECT id FROM messages WHERE chat_id=?)', (chat_id,)).fetchall()
    for a in atts:
        try:
            os.remove(os.path.join(app.config['UPLOAD_FOLDER'], a['filename']))
        except Exception:
            pass
    cur.execute('DELETE FROM attachments WHERE message_id IN (SELECT id FROM messages WHERE chat_id=?)', (chat_id,))
    cur.execute('DELETE FROM messages WHERE chat_id=?', (chat_id,))
    cur.execute('DELETE FROM chat_participants WHERE chat_id=?', (chat_id,))
    cur.execute('DELETE FROM chats WHERE id=?', (chat_id,))
    conn.commit()
    conn.close()
    return jsonify({'ok': True})

@app.route('/admin/chat/<int:chat_id>/remove_participant', methods=['POST'])
@admin_required
def admin_remove_participant(chat_id):
    user_id = int(request.form.get('user_id'))
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute('DELETE FROM chat_participants WHERE chat_id=? AND user_id=?', (chat_id, user_id))
    conn.commit()
    conn.close()
    return jsonify({'ok': True})

@app.route('/admin/message/<int:message_id>/delete', methods=['POST'])
@admin_required
def admin_delete_message(message_id):
    conn = get_db_connection()
    cur = conn.cursor()
    # remove attachments files
    atts = cur.execute('SELECT filename FROM attachments WHERE message_id=?', (message_id,)).fetchall()
    for a in atts:
        try:
            os.remove(os.path.join(app.config['UPLOAD_FOLDER'], a['filename']))
        except Exception:
            pass
    cur.execute('DELETE FROM attachments WHERE message_id=?', (message_id,))
    cur.execute('DELETE FROM messages WHERE id=?', (message_id,))
    conn.commit()
    conn.close()
    return jsonify({'ok': True})



# API: search users for autocomplete (by nom/prenom)
@app.route('/api/users/search')
def api_users_search():
    q = request.args.get('q', '').strip()
    conn = get_db_connection()
    try:
        if q == '':
            rows = conn.execute("SELECT id, nom, prenom FROM users ORDER BY nom LIMIT 30").fetchall()
        else:
            like = f"%{q}%"
            rows = conn.execute("SELECT id, nom, prenom FROM users WHERE nom LIKE ? OR prenom LIKE ? OR (nom || ' ' || IFNULL(prenom,'')) LIKE ? ORDER BY nom LIMIT 50", (like, like, like)).fetchall()
        results = [{'id': r['id'], 'name': (r['nom'] + ' ' + (r['prenom'] or '')).strip()} for r in rows]
        return jsonify(results)
    finally:
        conn.close()

# API: list currently online users
@app.route('/api/online_users')
def api_online_users():
    conn = get_db_connection()
    try:
        rows = conn.execute("SELECT ou.user_id, u.nom, u.prenom, ou.connected_at FROM online_users ou JOIN users u ON u.id=ou.user_id ORDER BY ou.connected_at DESC").fetchall()
        return jsonify([{'id': r['user_id'], 'name': (r['nom'] + ' ' + (r['prenom'] or '')).strip(), 'connected_at': r['connected_at']} for r in rows])
    finally:
        conn.close()
    cur = conn.cursor()
    # create invite with status 'requested'
    cur.execute('INSERT INTO chat_invites (chat_id, from_user, to_user, status) VALUES (?, ?, ?, ?)', (chat_id, session['user_id'], None, 'requested'))
    conn.commit()
    conn.close()
    # notify chat owners (simple implementation: notify all members with role owner)
    try:
        # fetch owners
        conn = get_db_connection()
        owners = conn.execute('SELECT user_id FROM chat_members WHERE chat_id=? AND role="owner"', (chat_id,)).fetchall()
        conn.close()
        for owner in owners:
            socketio.emit('chat_join_request', {'chat_id': chat_id, 'from_user': session['user_id']}, namespace='/notifications', room=f'user_{owner["user_id"]}')
    except Exception:
        pass
    return jsonify({'ok': True})

# --- Assistant IA par unité (placeholder) ---
@app.route("/assistant/unit/<int:unite_id>")
@app.route("/assistant/unit/<int:unite_id>", methods=["GET", "POST"])
def assistant_unit(unite_id):
    if "user_id" not in session:
        return redirect(url_for("login"))
    conn = get_db_connection()
    unite = conn.execute("SELECT * FROM unites WHERE id=?", (unite_id,)).fetchone()
    conn.close()
    response = None
    question = request.args.get("prompt")
    if request.method == "POST":
        question = request.form.get("question")
    if question:
        key = get_openai_api_key()
        if not key:
            response = "<span style='color:#c00;font-weight:bold'>Clé OpenAI non configurée. Veuillez définir la variable d'environnement OPENAI_API_KEY ou `app.config['OPENAI_API_KEY']`.</span>"
        else:
            try:
                openai.api_key = key
                client = openai.OpenAI(api_key=openai.api_key)
                chat_completion = client.chat.completions.create(
                    model="gpt-3.5-turbo",
                    messages=[
                        {"role": "system", "content": f"Tu es un assistant pédagogique pour l'unité : {unite['nom']} du programme Génie Informatique."},
                        {"role": "user", "content": question}
                    ]
                )
                response = chat_completion.choices[0].message.content
            except Exception as e:
                err_str = str(e).lower()
                if 'insufficient_quota' in err_str or 'quota' in err_str:
                    response = "<span style='color:#c00;font-weight:bold'>Limite atteinte : Veuillez passer au mode premium pour continuer à utiliser l'assistant IA.</span>"
                elif 'invalid_api_key' in err_str or 'incorrect api key' in err_str:
                    response = "<span style='color:#c00;font-weight:bold'>Clé API OpenAI invalide : Veuillez contacter l'administrateur ou passer au mode premium.</span>"
                else:
                    response = f"Erreur lors de la réponse de l'IA : {e}"
    return render_template("assistant_unit.html", unite=unite, response=response, question=question)

# Lightweight assistant API for floating assistant
@app.route('/assistant/chat', methods=['POST'])
def assistant_chat_api():
    if 'user_id' not in session:
        return jsonify({'ok': False, 'error': 'Not authenticated'})
    payload = request.get_json() or {}
    question = payload.get('question', '')
    unite_id = payload.get('unite_id')
    try:
        key = get_openai_api_key()
        if not key:
            return jsonify({'ok': False, 'error': 'OpenAI key not configured. Définissez OPENAI_API_KEY dans l\'environnement ou `app.config["OPENAI_API_KEY"]`.'})
        openai.api_key = key
        client = openai.OpenAI(api_key=openai.api_key)
        prompt = f"You are a helpful study assistant. Answer concisely: {question}"
        comp = client.chat.completions.create(
            model='gpt-3.5-turbo',
            messages=[{'role':'system','content':'You are a helpful study assistant.'},{'role':'user','content':prompt}]
        )
        resp = comp.choices[0].message.content
        return jsonify({'ok': True, 'response': resp})
    except Exception as e:
        return jsonify({'ok': False, 'error': str(e)})

# --- Login ---
@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        email = request.form["email"]
        password = request.form["password"]
        conn = get_db_connection()
        user = conn.execute(
            "SELECT * FROM users WHERE email=? AND password=?",
            (email, password)
        ).fetchone()
        conn.close()
        if user:
            session["user_id"] = user["id"]
            session["username"] = user["nom"]
            session["user_email"] = user["email"]
            return redirect(url_for("index"))
        else:
            return "Identifiants incorrects."
    return render_template("login.html")

 
# --- Inscription ---
@app.route("/register", methods=["GET", "POST"])
def register():
    if request.method == "POST":
        nom = request.form["nom"]
        prenom = request.form["prenom"]
        matricule = request.form["matricule"]
        email = request.form["email"]
        password = request.form["password"]
        filiere = request.form["filiere"]
        conn = get_db_connection()
        try:
            conn.execute(
                "INSERT INTO users (nom, prenom, matricule, email, password, role, filiere) VALUES (?, ?, ?, ?, ?, ?, ?)",
                (nom, prenom, matricule, email, password, "student", filiere)
            )
            conn.commit()
        except sqlite3.IntegrityError:
            conn.close()
            return "Email ou matricule déjà utilisé."
        conn.close()
        return redirect(url_for("login"))
    return render_template("register.html")

# --- Like un post ---
@app.route("/like/<int:post_id>", methods=["POST"])
def like(post_id):
    if "user_id" not in session:
        return redirect(url_for("login"))
    conn = get_db_connection()
    already = conn.execute("SELECT 1 FROM post_likes WHERE post_id=? AND user_id=?", (post_id, session["user_id"])).fetchone()
    if not already:
        conn.execute("INSERT INTO post_likes (post_id, user_id) VALUES (?, ?)", (post_id, session["user_id"]))
        conn.commit()
    conn.close()
    return redirect(url_for("index"))

# --- Commenter un post ---
@app.route("/comment/<int:post_id>", methods=["POST"])
def comment(post_id):
    if "user_id" not in session:
        return redirect(url_for("login"))
    comment = request.form.get("comment")
    conn = get_db_connection()
    conn.execute("INSERT INTO post_comments (post_id, user_id, comment) VALUES (?, ?, ?)", (post_id, session["user_id"], comment))
    conn.commit()
    conn.close()
    return redirect(url_for("index"))

# --- Admin : approuver les posts ---
@app.route("/admin/posts", methods=["GET", "POST"])
@admin_required
def admin_posts():
    conn = get_db_connection()
    if request.method == "POST":
        post_id = request.form.get("post_id")
        conn.execute("UPDATE posts SET approved=1 WHERE id=?", (post_id,))
        conn.commit()
    posts = conn.execute("""
        SELECT p.*, u.nom, u.prenom, u.photo FROM posts p
        JOIN users u ON p.user_id = u.id
        WHERE p.approved=0
        ORDER BY p.created_at DESC
    """).fetchall()
    conn.close()
    return render_template("admin_posts.html", posts=posts)


@app.route('/admin/chats')
@admin_required
def admin_chats():
    # Render the admin chat moderation interface
    return render_template('admin_chats.html')

# --- Page d'actualité GI2 ---
@app.route("/gi2-news")
def gi2_news():
    conn = get_db_connection()
    news = conn.execute("SELECT * FROM gi2_news ORDER BY created_at DESC").fetchall()
    conn.close()
    return render_template("gi2_news.html", news=news, is_admin=is_admin())

# --- Admin : publier une actu GI2 ---
@app.route("/gi2-news/publish", methods=["GET", "POST"])
@admin_required
def publish_gi2_news():
    if request.method == "POST":
        title = request.form.get("title")
        content = request.form.get("content")
        image = None
        if "image" in request.files:
            file = request.files["image"]
            if file and file.filename:
                filename = secure_filename(file.filename)
                file.save(os.path.join(app.config['UPLOAD_FOLDER'], filename))
                image = filename
        conn = get_db_connection()
        conn.execute("INSERT INTO gi2_news (title, content, image) VALUES (?, ?, ?)", (title, content, image))
        conn.commit()
        conn.close()
        return redirect(url_for("gi2_news"))
    return render_template("publish_gi2_news.html")

# --- Liste des cours (Genie Info: semestres, unités dynamiques, upload documents) ---
@app.route("/courses")
def courses():
    if "user_id" not in session:
        return redirect(url_for("login"))
    conn = get_db_connection()
    user = conn.execute("SELECT * FROM users WHERE id=?", (session["user_id"],)).fetchone()
    if not is_admin() and (not user or not user['has_paid']):
        if user and user['pending_payment']:
            conn.close()
            return render_template("pay.html", message="Votre paiement est en attente de validation par l'administrateur. Vous recevrez un accès dès confirmation.", waiting=True)
        conn.close()
        return redirect(url_for("pay"))
    filiere = user["filiere"] if user else None
    semestres = []
    # Show semestres/units to admins regardless of their filiere, otherwise only show if filiere matches GI
    if is_admin() or (filiere and filiere.lower() in ["genie informatique", "informatique", "gin", "gi"]):
        sem_rows = conn.execute("SELECT * FROM semestres ORDER BY id").fetchall()
        for sem in sem_rows:
            unites = conn.execute("SELECT * FROM unites WHERE semestre_id=? ORDER BY id", (sem["id"],)).fetchall()
            unite_list = []
            for unite in unites:
                cours = [row["nom"] for row in conn.execute("SELECT * FROM courses WHERE unite_id=? AND type='cours'", (unite["id"],)).fetchall()]
                td = [row["nom"] for row in conn.execute("SELECT * FROM courses WHERE unite_id=? AND type='td'", (unite["id"],)).fetchall()]
                docs = conn.execute("SELECT * FROM unite_documents WHERE unite_id=?", (unite["id"],)).fetchall()
                unite_list.append({
                    "id": unite["id"],
                    "nom": unite["nom"],
                    "professeur": unite["professeur"] if "professeur" in unite.keys() else "",
                    "credits": unite["credits"] if "credits" in unite.keys() else "",
                    "description": unite["description"] if "description" in unite.keys() else "",
                    "cours": cours,
                    "td": td,
                    "documents": [{"filename": d["filename"], "original_name": d["original_name"]} for d in docs]
                })
            semestres.append({
                "id": sem["id"],
                "nom": sem["nom"],
                "unites": unite_list
            })
    conn.close()
    return render_template("courses.html", filiere=filiere, semestres=semestres)

# --- Paiement Orange Money ---
@app.route("/pay", methods=["GET", "POST"])
def pay():
    if "user_id" not in session:
        return redirect(url_for("login"))
    conn = get_db_connection()
    user = conn.execute("SELECT * FROM users WHERE id=?", (session["user_id"],)).fetchone()
    if is_admin() or (user and user['has_paid']):
        conn.close()
        return redirect(url_for("courses"))
    message = None
    waiting = False
    if user and user['pending_payment']:
        waiting = True
        message = "Votre paiement est en attente de validation par l'administrateur. Vous recevrez un accès dès confirmation."
    if request.method == "POST":
        try:
            amount = request.form.get("amount")
            try:
                amount = int(amount)    
            except (TypeError, ValueError):
                amount = 0
            if amount >= 1000:
                conn.execute("UPDATE users SET pending_payment=1, has_paid=0 WHERE id=?", (session["user_id"],))
                conn.commit()
                waiting = True
                message = "Votre paiement est en attente de validation par l'administrateur. Vous recevrez un accès dès confirmation."
            else:
                message = "Le montant doit être supérieur ou égal à 1000 XAF."
        except Exception as e:
            message = f"Erreur lors de la validation du paiement : {e}"
    conn.close()
    return render_template("pay.html", message=message, waiting=waiting)
#page de payement
@app.route("/admin/payments", methods=["GET", "POST"])
@admin_required
def admin_payments():
    conn = get_db_connection()
    if request.method == "POST":
        user_id = request.form.get("user_id")
        if user_id:
            conn.execute("UPDATE users SET has_paid=1, pending_payment=0 WHERE id=?", (user_id,))
            conn.commit()
    users = conn.execute("SELECT id, nom, prenom, email, filiere FROM users WHERE pending_payment=1").fetchall()
    conn.close()
    return render_template("admin_payments.html", users=users)



# --- Profil utilisateur ---
@app.route("/profile", methods=["GET", "POST"])
def profile():
    # Si un user_id est passé dans l'URL, on affiche ce profil
    user_id = request.args.get("user_id")
    if not user_id:
        # Sinon, on affiche le profil de la session (l'utilisateur connecté)
        if "user_id" not in session:
            return redirect(url_for("login"))
        user_id = session["user_id"]
    conn = get_db_connection()
    user = conn.execute("SELECT * FROM users WHERE id=?", (user_id,)).fetchone()
    # Seul l'utilisateur connecté peut modifier SON profil
    if request.method == "POST" and str(user_id) == str(session.get("user_id")):
        age = request.form.get("age")
        sports = request.form.get("sports")
        autres = request.form.get("autres")
        photo = user["photo"] if "photo" in user.keys() else None
        if "photo_file" in request.files:
            file = request.files["photo_file"]
            if file and file.filename:
                filename = secure_filename(file.filename)
                upload_path = os.path.join(app.config['UPLOAD_FOLDER'], filename)
                file.save(upload_path)
                photo = filename
        conn.execute(
            "UPDATE users SET age=?, sports=?, autres=?, photo=? WHERE id=?",
            (age, sports, autres, photo, session["user_id"])
        )
        conn.commit()
        user = conn.execute("SELECT * FROM users WHERE id=?", (session["user_id"],)).fetchone()
    conn.close()
    return render_template("profile.html", user=user)
# --- Upload de documents pour une unité ---
def allowed_doc_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

@app.route('/upload/<int:unite_id>', methods=['POST'])
def upload_file(unite_id):
    if 'user_id' not in session:
        return redirect(url_for('login'))
    if not is_admin():
        return "Seul l'administrateur peut charger des documents dans les cours.", 403
    if 'file' not in request.files:
        return redirect(url_for('courses'))
    file = request.files['file']
    if file.filename == '':
        return redirect(url_for('courses'))
    if file and allowed_doc_file(file.filename):
        filename = secure_filename(file.filename)
        save_path = os.path.join(app.config['UPLOAD_FOLDER'], filename)
        file.save(save_path)
        conn = get_db_connection()
        conn.execute("INSERT INTO unite_documents (unite_id, filename, original_name) VALUES (?, ?, ?)", (unite_id, filename, file.filename))
        conn.commit()
        conn.close()
    return redirect(url_for('courses'))

@app.route('/uploads/<filename>')
def uploaded_file(filename):
    return redirect(url_for('static', filename='uploads/' + filename))

# Ajouter ces routes après vos imports et avant if __name__ == "__main__":

@app.route("/exams")
def exams():
    if "user_id" not in session:
        return redirect(url_for("login"))
    conn = get_db_connection()
    exams = conn.execute("""
        SELECT e.*, u.nom as unite_nom 
        FROM examens e
        JOIN unites u ON e.unite_id = u.id
        ORDER BY e.date_debut
    """).fetchall()
    conn.close()
    return render_template("exams.html", exams=exams)
# ...existing code...
@app.route("/exam/<int:exam_id>", methods=["GET", "POST"])
def take_exam(exam_id):
    if "user_id" not in session:
        return redirect(url_for("login"))
    
    try:
        conn = get_db_connection()
        exam_row = conn.execute("""
            SELECT e.*, u.nom as unite_nom 
            FROM examens e
            JOIN unites u ON e.unite_id = u.id 
            WHERE e.id=?
        """, (exam_id,)).fetchone()
        if not exam_row:
            conn.close()
            return "Examen introuvable", 404

        # Convertir Row en dict pour rendre sérialisable en JSON dans le template
        exam = dict(exam_row)

        if request.method == "POST":
            score = 0
            responses = []
            total_questions = 0
            ask_ia = request.form.get('ask_ia')
            share_whatsapp = True if request.form.get('share_whatsapp') else False
            
            for q in request.form:
                if q.startswith('q_'):
                    total_questions += 1
                    question_id = q.split('_')[1]
                    reponse = request.form[q]
                    
                    question_row = conn.execute(
                        "SELECT question, reponse_correcte FROM questions WHERE id=?", 
                        (question_id,)
                    ).fetchone()
                    question = dict(question_row) if question_row else {"question": "", "reponse_correcte": ""}
                    
                    is_correct = reponse.strip().lower() == (question['reponse_correcte'] or '').strip().lower()
                    responses.append({
                        "question": question['question'],
                        "reponse": reponse,
                        "correct": is_correct
                    })
                    
                    if is_correct:
                        score += 1
            
            # Calculate percentage
            score_percentage = (score / total_questions * 100) if total_questions > 0 else 0
            
            # Save result with transaction
            conn.execute("BEGIN")
            try:
                conn.execute("""
                    INSERT INTO resultats_exam 
                    (exam_id, user_id, score, score_percentage, responses) 
                    VALUES (?, ?, ?, ?, ?)
                """, (exam_id, session["user_id"], score, score_percentage, str(responses)))
                conn.commit()
            except Exception as e:
                conn.rollback()
                raise e

            ai_feedback = None
            # If IA requested, ask OpenAI to evaluate answers
            if ask_ia:
                key = get_openai_api_key()
                if not key:
                    ai_feedback = ["AI non configurée (clé OPENAI_API_KEY manquante)."]
                else:
                    try:
                        openai.api_key = key
                        prompt = "You are an educational assistant. For each question and student's answer, give a short feedback (1-2 lines) whether correct and a brief comment. Use the format: 1) feedback line.\n" 
                        for i, r in enumerate(responses, start=1):
                            prompt += f"Question {i}: {r['question']}\nAnswer: {r['reponse']}\n\n"
                        client = openai.OpenAI(api_key=openai.api_key)
                        comp = client.chat.completions.create(
                            model="gpt-3.5-turbo",
                            messages=[{"role":"system","content":"You are a helpful grading assistant."}, {"role":"user","content":prompt}]
                        )
                        raw = comp.choices[0].message.content
                        ai_feedback = [line.strip() for line in raw.splitlines() if line.strip()]
                    except Exception as e:
                        ai_feedback = [f"Erreur IA: {str(e)}"]

            # If AJAX request
            if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
                return jsonify({
                    "score": score,
                    "total": total_questions,
                    "percentage": score_percentage,
                    "responses": responses,
                    "ai_feedback": ai_feedback,
                    "share_whatsapp": share_whatsapp
                })
            
            return redirect(url_for("exams"))

        questions_rows = conn.execute(
            "SELECT * FROM questions WHERE exam_id=? ORDER BY id", 
            (exam_id,)
        ).fetchall()
        # convertir questions en liste de dict (sécurise si besoin de JS)
        questions = [dict(q) for q in questions_rows]
        
        return render_template("take_exam.html", exam=exam, questions=questions)
        
    except Exception as e:
        return str(e), 500
    finally:
        conn.close()
# ...existing code...

@app.route("/admin/exams", methods=["GET", "POST"])
@admin_required
def admin_exams():
    conn = get_db_connection()
    
    if request.method == "POST":
        unite_id = request.form.get("unite_id")
        titre = request.form.get("titre")
        date_debut = request.form.get("date_debut")
        duree = request.form.get("duree")
        
        # Insérer l'examen
        cursor = conn.execute("""
            INSERT INTO examens (unite_id, titre, date_debut, duree)
            VALUES (?, ?, ?, ?)
        """, (unite_id, titre, date_debut, duree))
        
        exam_id = cursor.lastrowid
        
        # Insérer les questions (gestion des images et du type de réponse)
        questions = request.form.getlist("questions[]")
        reponses = request.form.getlist("reponses[]")
        answer_types = request.form.getlist("answer_type[]")
        images = request.files.getlist("question_image[]")
        
        # normaliser la longueur
        maxlen = max(len(questions), len(reponses), len(answer_types), len(images))
        for i in range(maxlen):
            q = questions[i] if i < len(questions) else ''
            r = reponses[i] if i < len(reponses) else None
            at = answer_types[i] if i < len(answer_types) else 'short'
            img_file = images[i] if i < len(images) else None
            img_filename = None
            if img_file and hasattr(img_file, 'filename') and img_file.filename:
                filename = secure_filename(img_file.filename)
                # avoid name collision
                save_name = f"{int(datetime.now().timestamp())}_{filename}"
                img_file.save(os.path.join(app.config['UPLOAD_FOLDER'], save_name))
                img_filename = save_name
            conn.execute("""
                INSERT INTO questions (exam_id, question, reponse_correcte, image, answer_type)
                VALUES (?, ?, ?, ?, ?)
            """, (exam_id, q, r, img_filename, at))
        
        conn.commit()
        return redirect(url_for("admin_exams"))
    
    # Récupérer les unités pour le formulaire
    unites = conn.execute("SELECT * FROM unites").fetchall()
    
    # Récupérer les examens existants
    examens = conn.execute("""
        SELECT e.*, u.nom as unite_nom 
        FROM examens e
        JOIN unites u ON e.unite_id = u.id
        ORDER BY e.date_debut DESC
    """).fetchall()
    
    conn.close()
    return render_template("admin_exams.html", unites=unites, examens=examens)

@app.route("/admin/exams/delete/<int:exam_id>", methods=["POST"])
@admin_required
def admin_exams_delete(exam_id):
    try:
        conn = get_db_connection()
        # Début de la transaction
        conn.execute("BEGIN")
        # Supprimer d'abord les questions associées
        conn.execute("DELETE FROM questions WHERE exam_id = ?", (exam_id,))
        # Puis supprimer l'examen
        conn.execute("DELETE FROM examens WHERE id = ?", (exam_id,))
        # Valider les changements
        conn.commit()
    except Exception as e:
        # En cas d'erreur, annuler les changements
        conn.rollback()
        raise e
    finally:
        # Toujours fermer la connexion
        conn.close()
    return redirect(url_for("admin_exams"))

# Admin chat moderation routes removed because the chat feature is disabled per request.
# Admin pages and endpoints related to chats were removed to avoid confusion.

# Route pour afficher la page Fondateur
@app.route('/fondateur')
def fondateur():
    return render_template('Fondateur.html')

# Supprimer l'ancienne route forum_unit si elle existe

@app.route("/forum/unit/<int:unite_id>")
def forum_unit(unite_id):
    if "user_id" not in session:
        return redirect(url_for("login"))
    
    try:
        conn = get_db_connection()
        # Récupérer les messages
        messages = conn.execute("""
            SELECT m.*, u.nom as username 
            FROM forum_messages m
            JOIN users u ON m.user_id = u.id
            WHERE m.unite_id = ?
            ORDER BY m.created_at DESC
        """, (unite_id,)).fetchall()
        
        # Récupérer les informations de l'unité
        unite = conn.execute("""
            SELECT * FROM unites 
            WHERE id = ?
        """, (unite_id,)).fetchone()
        
        if not unite:
            return "Unité non trouvée", 404
            
    except Exception as e:
        return str(e), 500
    finally:
        conn.close()
    
    return render_template(
        "forum.html", 
        messages=messages, 
        unite=unite, 
        unite_id=unite_id
    )


@app.route('/forum/unit/<int:unite_id>/message', methods=['POST'])
def forum_post_message(unite_id):
    if 'user_id' not in session:
        return jsonify({'ok': False, 'error': 'Not authenticated'}), 401
    data = request.get_json() or {}
    content = (data.get('content') or '').strip()
    share_whatsapp = bool(data.get('share_whatsapp'))
    if not content:
        return jsonify({'ok': False, 'error': 'Content required'})
    conn = get_db_connection()
    try:
        cur = conn.cursor()
        cur.execute("INSERT INTO forum_messages (unite_id, user_id, content, share_whatsapp) VALUES (?, ?, ?, ?)", (unite_id, session['user_id'], content, 1 if share_whatsapp else 0))
        conn.commit()
        msg_id = cur.lastrowid
        user = conn.execute("SELECT nom FROM users WHERE id=?", (session['user_id'],)).fetchone()
        username = user['nom'] if user else 'Anonyme'
        created_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        message = {'id': msg_id, 'user_id': session['user_id'], 'username': username, 'content': content, 'created_at': created_at, 'shareToWhatsApp': share_whatsapp}
        return jsonify({'ok': True, 'message': message})
    finally:
        conn.close()


def allowed_video_file(filename):
    return '.' in filename and \
           filename.rsplit('.', 1)[1].lower() in {'mp4', 'webm', 'ogg', 'mov', 'mkv'}

@app.route("/password", methods=["GET", "POST"])
def password():
    if request.method == "POST":
        entered_password = request.form.get("password")
        if entered_password == "1234":  # Remplacez par votre mot de passe
            session['access_granted'] = True
            return redirect(url_for('formations'))
        else:
            return render_template("password.html", error="Mot de passe incorrect.")
    return render_template("password.html")

# Route publique formations (renvoie vidéos + catégories)
@app.route("/formations")
def formations():
    if "user_id" not in session or not session.get('access_granted'):
        return redirect(url_for("password"))
    conn = get_db_connection()
    videos_rows = conn.execute("SELECT * FROM formations ORDER BY created_at DESC").fetchall()
    categories_rows = conn.execute("SELECT DISTINCT categorie FROM formations").fetchall()
    conn.close()
    # convertir en listes simples pour template
    videos = [dict(v) for v in videos_rows]
    categories = [c['categorie'] for c in categories_rows if c['categorie']]
    return render_template("formations.html", videos=videos, categories=categories)


@app.route("/admin/formations", methods=["GET", "POST"])
@admin_required
def admin_formations():
    conn = get_db_connection()
    if request.method == "POST":
        titre = request.form.get("titre")
        description = request.form.get("description")
        categorie = request.form.get("categorie", "General")
        file = request.files.get("video")
        if not titre or not file:
            conn.close()
            return "Titre et fichier requis", 400
        if not allowed_video_file(file.filename):
            conn.close()
            return "Format vidéo non autorisé", 400

        filename = secure_filename(file.filename)
        save_path = os.path.join(app.config['UPLOAD_FOLDER'], filename)
        # si nom en double, ajouter timestamp
        if os.path.exists(save_path):
            name, ext = os.path.splitext(filename)
            filename = f"{name}_{int(datetime.now().timestamp())}{ext}"
            save_path = os.path.join(app.config['UPLOAD_FOLDER'], filename)
        file.save(save_path)

        try:
            conn.execute("""
                INSERT INTO formations (titre, description, categorie, filename, uploaded_by, created_at)
                VALUES (?, ?, ?, ?, ?, ?)
            """, (titre, description, categorie, filename, session.get("user_id"), datetime.now()))
            conn.commit()
        finally:
            conn.close()
        return redirect(url_for("admin_formations"))

    # GET :
    categories = conn.execute("SELECT DISTINCT categorie FROM formations").fetchall()
    videos = conn.execute("SELECT * FROM formations ORDER BY created_at DESC").fetchall()
    conn.close()
    return render_template("admin_formations.html", videos=videos, categories=[c['categorie'] for c in categories])

@app.route("/admin/formations/delete/<int:video_id>", methods=["POST"])
@admin_required
def admin_formations_delete(video_id):
    conn = get_db_connection()
    try:
        row = conn.execute("SELECT filename FROM formations WHERE id = ?", (video_id,)).fetchone()
        if row:
            filepath = os.path.join(app.config['UPLOAD_FOLDER'], row['filename'])
            if os.path.exists(filepath):
                try:
                    os.remove(filepath)
                except Exception:
                    pass
        conn.execute("DELETE FROM formations WHERE id = ?", (video_id,))
        conn.commit()
    finally:
        conn.close()
    return redirect(url_for("admin_formations"))
# ...existing code...


if __name__ == "__main__":
    socketio.run(app, debug=True)