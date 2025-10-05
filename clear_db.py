import sqlite3

DB_PATH = r"database/iut_courses.db"

conn = sqlite3.connect(DB_PATH)
c = conn.cursor()

# Désactiver les contraintes de clé étrangère pour pouvoir tout supprimer
c.execute("PRAGMA foreign_keys = OFF;")

c.execute("PRAGMA foreign_keys = ON;")
c.execute("PRAGMA foreign_keys = ON;")
# Supprimer tous les utilisateurs
c.execute("DELETE FROM users;")
conn.commit()

c.execute("PRAGMA foreign_keys = ON;")
conn.close()
print("Tous les utilisateurs ont été supprimés. La table users est vide.")
