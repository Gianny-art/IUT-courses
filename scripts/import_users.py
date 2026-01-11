#!/usr/bin/env python3
"""Import users from CSV into the SQLite DB.
Expected input CSV (path default: data/users_to_import.csv) with columns:
- full_name,email   OR
- nom,prenom,email

Behavior:
- Deduplicates by email. If an email already exists and has_paid=1 -> skip
  (keep the existing paid user). If exists and has_paid=0 -> skip (no update by default).
- Generates matricule and default password for each inserted user.
- Assigns IDs starting from 11 if DB has no rows, otherwise starts at max(existing_id)+1.
- Inserts default values for required fields so DB constraints are satisfied.
"""
import csv
import os
import sqlite3
import re
from typing import Tuple

DB_PATH = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'database', 'iut_courses.sqbpro')
CSV_PATH = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'data', 'users_to_import.csv')

DEFAULT_FILIERE = 'Informatique'
DEFAULT_ROLE = 'student'
DEFAULT_PASSWORD_PREFIX = '2026iutGL_'


def split_name(full_name: str) -> Tuple[str,str]:
    s = full_name.strip()
    if not s:
        return '', ''
    parts = s.split()
    if len(parts) == 1:
        return parts[0], ''
    return ' '.join(parts[:-1]), parts[-1]

# Name cleaner to strip filiere suffixes, years or parenthesis notes
FILIERE_KEYS = [
    'genie informatique', 'informatique', 'gin', 'gi', 'gi2', 'gi1', 'gl', 'gl2', 'gl1', 'info', 'info2', 'info1',
    'genie civil', 'genie electrique', 'genie mecanique', 'reseau', 'reseaux', 'telecoms', 'tc', 'ipi'
]
FILIERE_REGEX = re.compile(r"(^|\s)(" + r"|".join(re.escape(k) for k in FILIERE_KEYS) + r")(\b|$)", flags=re.I)
PAREN_RE = re.compile(r"\([^)]*\)")
TRAILING_YEAR = re.compile(r"\b\d{2,4}\b")


def clean_name(s: str) -> str:
    if not s:
        return s
    orig = s
    # remove parenthesis content
    s = PAREN_RE.sub(' ', s)
    s = s.replace('/', ' ').replace('|', ' ').replace('-', ' ').strip()
    parts = [p.strip().strip(' ,;:-_/\\') for p in s.split() if p.strip()]
    while parts:
        last = parts[-1]
        if FILIERE_REGEX.search(last) or TRAILING_YEAR.search(last) or re.match(r'^[A-Za-z]{1,3}\d?$', last):
            parts.pop(); continue
        if last.lower() in ('et', 'etc', 'others', 'autres'):
            parts.pop(); continue
        break
    cleaned = ' '.join(parts).strip()
    return cleaned.title() if cleaned else re.sub(r'[^\w\s-]', '', orig).strip().title()


def main(dry_run=True):
    if not os.path.exists(CSV_PATH):
        print('CSV file not found:', CSV_PATH)
        return

    rows = []
    with open(CSV_PATH, newline='', encoding='utf-8') as f:
        reader = csv.reader(f)
        headers = next(reader, None)
        # Support both formats
        for r in reader:
            if not r: continue
            if len(r) >= 2:
                # If header looks like nom,prenom,email
                if headers and 'email' in [h.lower() for h in headers] and len(r) >= 3:
                    nom = r[0].strip()
                    prenom = r[1].strip()
                    email = r[2].strip()
                else:
                    # assume full_name,email
                    full = r[0].strip()
                    email = r[1].strip() if len(r) > 1 else ''
                    nom, prenom = split_name(full)
                if not email: continue
                # clean names to remove filiere suffixes and stray metadata
                nom = clean_name(nom)
                prenom = clean_name(prenom)
                rows.append({'nom': nom, 'prenom': prenom, 'email': email})

    print(f'Read {len(rows)} rows from CSV')

    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()

    # find starting id
    cur.execute('SELECT MAX(id) as m FROM users')
    m = cur.fetchone()['m']
    start_id = 11 if (not m or m < 11) else (m + 1)
    next_id = start_id

    inserted = 0
    skipped = 0
    kept_paid = 0

    for r in rows:
        email = r['email'].lower()
        # ensure names are normalized (idempotent)
        nom = clean_name(r['nom'] or '')
        prenom = clean_name(r['prenom'] or '')
        # check by email
        cur.execute('SELECT id, has_paid FROM users WHERE email = ?', (email,))
        existing = cur.fetchone()
        if existing:
            skipped += 1
            if existing['has_paid']:
                kept_paid += 1
            print(f"Skipping {email} (exists id={existing['id']}, has_paid={existing['has_paid']})")
            continue

        matricule = f"GI-{next_id:04d}"
        password = DEFAULT_PASSWORD_PREFIX + f"{next_id:03d}"
        role = DEFAULT_ROLE
        filiere = DEFAULT_FILIERE

        if dry_run:
            print(f"Would insert: id={next_id}, nom={nom}, prenom={prenom}, email={email}, matricule={matricule}")
        else:
            cur.execute("INSERT INTO users (id, nom, prenom, matricule, email, password, role, filiere, photo, age, sports, autres, has_paid, pending_payment) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                        (next_id, nom or 'N/A', prenom or 'N/A', matricule, email, password, role, filiere, '', None, '', '', 0, 0))
            conn.commit()
            inserted += 1
        next_id += 1

    conn.close()
    print(f'Done. Inserted: {inserted} (dry_run={dry_run}). Skipped: {skipped}. Kept paid existing: {kept_paid}.')


if __name__ == '__main__':
    import argparse
    p = argparse.ArgumentParser()
    p.add_argument('--csv', help='CSV path', default=CSV_PATH)
    p.add_argument('--execute', action='store_true', help='Perform DB inserts (default: dry run)')
    args = p.parse_args()
    if args.csv:
        CSV_PATH = args.csv
    main(dry_run=not args.execute)
