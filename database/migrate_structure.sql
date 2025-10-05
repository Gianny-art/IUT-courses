-- Script de migration pour corriger la structure des tables unites et courses

DROP TABLE IF EXISTS courses;
DROP TABLE IF EXISTS unites;

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
