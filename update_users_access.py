import sqlite3

db_path = 'F:\\IUT-courses\\database\\iut_courses.db'
conn = sqlite3.connect(db_path)
cursor = conn.cursor()

# Mettre à jour tous les utilisateurs à has_paid=1
cursor.execute('UPDATE users SET has_paid=1 WHERE has_paid IS NULL OR has_paid=0')
conn.commit()

# Vérifier les résultats
cursor.execute('SELECT COUNT(*) FROM users')
total = cursor.fetchone()[0]
cursor.execute('SELECT COUNT(*) FROM users WHERE has_paid=1')
paid = cursor.fetchone()[0]

print(f'Total utilisateurs: {total}')
print(f'Utilisateurs avec accès (has_paid=1): {paid}')

conn.close()
