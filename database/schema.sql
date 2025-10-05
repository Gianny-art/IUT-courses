-- Ajout des tables manquantes pour la navigation dynamique et l'upload de documents

CREATE TABLE IF NOT EXISTS semestres (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    nom TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS unites (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    nom TEXT NOT NULL,
    semestre_id INTEGER NOT NULL,
    professeur TEXT,
    credits INTEGER,
    description TEXT,
    FOREIGN KEY(semestre_id) REFERENCES semestres(id)
);

CREATE TABLE IF NOT EXISTS courses (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    nom TEXT NOT NULL,
    unite_id INTEGER NOT NULL,
    type TEXT NOT NULL, -- 'cours' ou 'td'
    FOREIGN KEY(unite_id) REFERENCES unites(id)
);

CREATE TABLE IF NOT EXISTS unite_documents (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    unite_id INTEGER NOT NULL,
    filename TEXT NOT NULL,
    original_name TEXT NOT NULL,
    FOREIGN KEY(unite_id) REFERENCES unites(id)
);

-- Table users (maintenant avec des champs supplémentaires pour la navigation)

CREATE TABLE IF NOT EXISTS users (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    nom TEXT NOT NULL,
    prenom TEXT NOT NULL,
    matricule TEXT UNIQUE NOT NULL,
    email TEXT UNIQUE NOT NULL,
    password TEXT NOT NULL,
    role TEXT NOT NULL,
    filiere TEXT
);

-- Table forum_posts (maintenant avec des champs supplémentaires pour la navigation)

CREATE TABLE IF NOT EXISTS forum_posts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER,
    course_id INTEGER,
    content TEXT NOT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY(user_id) REFERENCES users(id),
    FOREIGN KEY(course_id) REFERENCES courses(id)
);

-- Table pour les posts étudiants (mur social)
CREATE TABLE IF NOT EXISTS posts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER,
    content TEXT,
    image TEXT,
    bg_color TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    approved INTEGER DEFAULT 0,
    FOREIGN KEY(user_id) REFERENCES users(id)
);

-- Table pour les likes
CREATE TABLE IF NOT EXISTS post_likes (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    post_id INTEGER,
    user_id INTEGER,
    FOREIGN KEY(post_id) REFERENCES posts(id),
    FOREIGN KEY(user_id) REFERENCES users(id)
);

-- Table pour les commentaires
CREATE TABLE IF NOT EXISTS post_comments (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    post_id INTEGER,
    user_id INTEGER,
    comment TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY(post_id) REFERENCES posts(id),
    FOREIGN KEY(user_id) REFERENCES users(id)
);

-- Table pour les actualités GI2
CREATE TABLE IF NOT EXISTS gi2_news (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    title TEXT,
    content TEXT,
    image TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Table pour les posts étudiants (mur social)
CREATE TABLE IF NOT EXISTS posts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER,
    content TEXT,
    image TEXT,
    bg_color TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    approved INTEGER DEFAULT 0,
    FOREIGN KEY(user_id) REFERENCES users(id)
);

-- Table pour les likes
CREATE TABLE IF NOT EXISTS post_likes (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    post_id INTEGER,
    user_id INTEGER,
    FOREIGN KEY(post_id) REFERENCES posts(id),
    FOREIGN KEY(user_id) REFERENCES users(id)
);

-- Table pour les commentaires
CREATE TABLE IF NOT EXISTS post_comments (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    post_id INTEGER,
    user_id INTEGER,
    comment TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY(post_id) REFERENCES posts(id),
    FOREIGN KEY(user_id) REFERENCES users(id)
);

-- Table pour les actualités GI2
CREATE TABLE IF NOT EXISTS gi2_news (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    title TEXT,
    content TEXT,
    image TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);