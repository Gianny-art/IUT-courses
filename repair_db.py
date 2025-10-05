import sqlite3

DB_PATH = r"database/iut_courses.db"
try:
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    # Vérifier l'accès à la table users
    c.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='users';")
    if c.fetchone():
        try:
            c.execute("INSERT INTO users (username, password, role, filiere) VALUES (?, ?, ?, ?)", ("admin", "admin", "admin", "Administration"))
            conn.commit()
            print("Utilisateur admin recréé avec succès.")
        except Exception as e:
            print("Impossible d'ajouter l'admin :", e)
    else:
        print("La table users n'existe pas ou est inaccessible.")
    conn.close()
except Exception as e:
    print("Erreur d'accès à la base :", e)
