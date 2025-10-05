import sqlite3

# Chemin vers la base de données et le fichier SQL
DB_PATH = r"database/iut_courses.db"
SCHEMA_PATH = r"database/schema.sql"

# Connexion à la base de données
conn = sqlite3.connect(DB_PATH)

# Lecture et exécution du schéma SQL
with open(SCHEMA_PATH, 'r', encoding='utf-8') as f:
    schema = f.read()
    conn.executescript(schema)

conn.close()
print("Base de données initialisée avec succès !")
