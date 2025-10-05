import sqlite3

DB_PATH = r"database/iut_courses.db"

conn = sqlite3.connect(DB_PATH)
c = conn.cursor()

# Supprimer les utilisateurs spécifiques
users_to_delete = ("Gianny", "Foapa", "Robert")
c.execute("DELETE FROM users WHERE username IN (?, ?, ?);", users_to_delete)

conn.commit()

# Afficher le nombre d'utilisateurs restants
remaining = c.execute("SELECT username FROM users").fetchall()
print("Utilisateurs restants :", [u[0] for u in remaining])

conn.close()
print("Utilisateurs Gianny, Foapa et Robert supprimés si présents.")
