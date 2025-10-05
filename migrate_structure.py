import sqlite3

DB_PATH = r"database/iut_courses.db"

conn = sqlite3.connect(DB_PATH)
c = conn.cursor()

# Ajout du champ pending_payment pour la gestion de la confirmation admin
try:
    c.execute("ALTER TABLE users ADD COLUMN pending_payment INTEGER DEFAULT 0;")
    print("Colonne 'pending_payment' ajoutée à la table users.")
except sqlite3.OperationalError:
    print("Colonne 'pending_payment' déjà existante.")
import sqlite3

DB_PATH = r"database/iut_courses.db"

conn = sqlite3.connect(DB_PATH)
c = conn.cursor()

# Ajouter la colonne filiere à la table users si elle n'existe pas déjà
try:
    c.execute("ALTER TABLE users ADD COLUMN filiere TEXT;")
    print("Colonne 'filiere' ajoutée à la table users.")
except sqlite3.OperationalError:
    print("Colonne 'filiere' déjà existante.")

# Créer la table unites (unités d'enseignement)
c.execute('''
CREATE TABLE IF NOT EXISTS unites (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    nom TEXT NOT NULL,
    filiere TEXT NOT NULL
);
''')


# Table d'association unite_courses (cours par unité)
c.execute('''
CREATE TABLE IF NOT EXISTS unite_courses (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    unite_id INTEGER NOT NULL,
    course_id INTEGER NOT NULL,
    FOREIGN KEY(unite_id) REFERENCES unites(id),
    FOREIGN KEY(course_id) REFERENCES courses(id)
);
''')

# Créer la table forum_unit (forum par unité)
c.execute('''
CREATE TABLE IF NOT EXISTS forum_unit (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    unite_id INTEGER,
    user_id INTEGER,
    content TEXT NOT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY(unite_id) REFERENCES unites(id),
    FOREIGN KEY(user_id) REFERENCES users(id)
);
''')


# Ajout de champs de personnalisation au profil utilisateur
try:
    c.execute("ALTER TABLE users ADD COLUMN photo TEXT;")
except sqlite3.OperationalError:
    pass
try:
    c.execute("ALTER TABLE users ADD COLUMN age INTEGER;")
except sqlite3.OperationalError:
    pass
try:
    c.execute("ALTER TABLE users ADD COLUMN sports TEXT;")
except sqlite3.OperationalError:
    pass
try:
    c.execute("ALTER TABLE users ADD COLUMN autres TEXT;")
except sqlite3.OperationalError:
    pass
# Ajout du champ has_paid pour la monétisation
try:
    c.execute("ALTER TABLE users ADD COLUMN has_paid INTEGER DEFAULT 0;")
    print("Colonne 'has_paid' ajoutée à la table users.")
except sqlite3.OperationalError:
    print("Colonne 'has_paid' déjà existante.")

conn.commit()
conn.close()
print("Migration terminée : colonne filiere, table unites et forum_unit créées.")
