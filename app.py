from flask import Flask, render_template, request, redirect, url_for, session
import sqlite3
from flask_socketio import SocketIO, emit, join_room
import openai
from werkzeug.utils import secure_filename
from functools import wraps
import os

app = Flask(__name__)
app.secret_key = "supersecretkey"
socketio = SocketIO(app)

# --- Configuration upload ---
UPLOAD_FOLDER = os.path.join(os.path.dirname(__file__), 'static', 'uploads')
os.makedirs(UPLOAD_FOLDER, exist_ok=True)
app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER
ALLOWED_EXTENSIONS = {'pdf', 'doc', 'docx', 'ppt', 'pptx', 'txt', 'zip', 'rar', 'jpg', 'jpeg', 'png'}

# --- Connexion à la base de données ---
def get_db_connection():
    conn = sqlite3.connect(r"D:\IUT-courses\database\iut_courses.db")
    conn.row_factory = sqlite3.Row
    return conn

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

# --- Forum par unité (chat instantané) ---
@app.route("/forum/unit/<int:unite_id>")
def forum_unit(unite_id):
    if "user_id" not in session:
        return redirect(url_for("login"))
    conn = get_db_connection()
    unite = conn.execute("SELECT * FROM unites WHERE id=?", (unite_id,)).fetchone()
    posts = conn.execute(
        "SELECT f.*, u.nom as username FROM forum_unit f JOIN users u ON f.user_id = u.id WHERE unite_id=? ORDER BY created_at ASC",
        (unite_id,)
    ).fetchall()
    conn.close()
    return render_template("forum_unit.html", unite=unite, posts=posts, unite_id=unite_id)

# --- SocketIO events for chat ---
@socketio.on('join', namespace='/chat')
def join(data):
    unite_id = data.get('unite_id')
    username = data.get('username')
    room = f"unite_{unite_id}"
    join_room(room)
    emit('status', {'msg': f"{username} a rejoint le chat."}, room=room)

@socketio.on('send_message', namespace='/chat')
def handle_message(data):
    unite_id = data.get('unite_id')
    user_id = data.get('user_id')
    username = data.get('username')
    content = data.get('content')
    room = f"unite_{unite_id}"
    # Save to DB
    conn = get_db_connection()
    conn.execute(
        "INSERT INTO forum_unit (unite_id, user_id, content) VALUES (?, ?, ?)",
        (unite_id, user_id, content)
    )
    conn.commit()
    conn.close()
    emit('receive_message', {'username': username, 'content': content}, room=room)

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
        try:
            openai.api_key = "VOTRE_CLE_OPENAI"  # Remplacez par votre clé OpenAI
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
    if filiere and filiere.lower() in ["genie informatique", "informatique", "gin", "gi"]:
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
            if amount >= 2000:
                conn.execute("UPDATE users SET pending_payment=1, has_paid=0 WHERE id=?", (session["user_id"],))
                conn.commit()
                waiting = True
                message = "Votre paiement est en attente de validation par l'administrateur. Vous recevrez un accès dès confirmation."
            else:
                message = "Le montant doit être supérieur ou égal à 2000 XAF."
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
    if "user_id" not in session:
        return redirect(url_for("login"))
    conn = get_db_connection()
    user = conn.execute("SELECT * FROM users WHERE id=?", (session["user_id"],)).fetchone()
    if request.method == "POST":
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
def allowed_file(filename):
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
    if file and allowed_file(file.filename):
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

if __name__ == "__main__":
    socketio.run(app, debug=True)