#!/usr/bin/env python3
"""Clean user `nom` and `prenom` fields by removing filiere suffixes and stray metadata.
Usage:
  scripts/clean_user_names.py [--apply] [--db PATH]

--apply will perform updates (with a backup created). Default is dry-run that prints proposed fixes.
"""
import argparse
import os
import re
import shutil
import sqlite3
from typing import Tuple

ROOT = os.path.dirname(os.path.dirname(__file__))
DB_CANDIDATES = [
    os.path.join(ROOT, 'database', 'iut_courses.db'),
    os.path.join(ROOT, 'database', 'iut_courses.sqbpro'),
]

FILIERE_KEYS = [
    'genie informatique', 'informatique', 'gin', 'gi', 'gi2', 'gi1', 'gl', 'gl2', 'gl1', 'info', 'info2', 'info1',
    'genie civil', 'genie electrique', 'genie mecanique', 'reseau', 'reseaux', 'telecoms', 'tc', 'ipi'
]
FILIERE_REGEX = re.compile(r"(^|\s)(" + r"|".join(re.escape(k) for k in FILIERE_KEYS) + r")(\b|$)", flags=re.I)

# patterns to remove entirely if they appear as parentheses, trailing tokens or separated by punctuation
PAREN_RE = re.compile(r"\([^)]*\)")
TRAILING_YEAR = re.compile(r"\b\d{2,4}\b")


def normalize_token(token: str) -> str:
    # strip non alnum at ends
    return token.strip().strip(' ,;:-_/\\')


def clean_name(s: str) -> str:
    if not s:
        return s
    orig = s
    # remove parenthesis content
    s = PAREN_RE.sub(' ', s)
    # normalize separators
    s = s.replace('/', ' ').replace('|', ' ').replace('-', ' ').strip()
    parts = [normalize_token(p) for p in s.split() if p.strip()]
    # drop trailing tokens that look like filiere/abbrev/year
    while parts:
        last = parts[-1]
        if FILIERE_REGEX.search(last) or TRAILING_YEAR.search(last) or re.match(r'^[A-Za-z]{1,3}\d?$', last):
            parts.pop()
            continue
        # tokens like "et", "et al", "others" are also removable
        if last.lower() in ('et', 'etc', 'others', 'autres'):
            parts.pop(); continue
        break
    cleaned = ' '.join(parts).strip()
    # capitalise simple names
    cleaned = cleaned.title()
    if cleaned == '':
        # fallback to original but cleaned punctuation
        cleaned = re.sub(r'[^\w\s-]', '', orig).strip()
    return cleaned


def find_db(path_arg=None):
    if path_arg:
        return path_arg
    for p in DB_CANDIDATES:
        if os.path.exists(p):
            return p
    raise FileNotFoundError('No database found in expected locations. Provide --db path.')


def main(apply_changes=False, db_path=None, limit=None):
    db = find_db(db_path)
    print('Using DB:', db)
    conn = sqlite3.connect(db)
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()

    cur.execute('SELECT id, nom, prenom, email FROM users')
    rows = cur.fetchall()
    fixes = []
    for r in rows:
        nid = r['id']
        nom = r['nom'] or ''
        prenom = r['prenom'] or ''
        new_nom = clean_name(nom)
        new_prenom = clean_name(prenom)
        if new_nom != (nom or '') or new_prenom != (prenom or ''):
            fixes.append((nid, nom, prenom, new_nom, new_prenom, r['email']))
            if limit and len(fixes) >= limit:
                break

    if not fixes:
        print('No name issues detected.')
        return

    print(f'Found {len(fixes)} rows to fix (showing up to limit).')
    for nid, nom, prenom, new_nom, new_prenom, email in fixes:
        print(f'ID={nid} email={email}\n  NOM:    "{nom}" -> "{new_nom}"\n  PRENOM: "{prenom}" -> "{new_prenom}"\n')

    if apply_changes:
        # create a backup
        bak = db + '.bak'
        print('Creating DB backup at', bak)
        shutil.copy2(db, bak)
        for nid, nom, prenom, new_nom, new_prenom, email in fixes:
            cur.execute('UPDATE users SET nom=?, prenom=? WHERE id=?', (new_nom or nom, new_prenom or prenom, nid))
        conn.commit()
        print('Applied fixes to database.')
    else:
        print('\nDry-run only. Re-run with --apply to commit changes.')

    conn.close()


if __name__ == '__main__':
    p = argparse.ArgumentParser()
    p.add_argument('--apply', action='store_true', help='Apply changes to DB (creates backup).')
    p.add_argument('--db', help='Path to sqlite DB')
    p.add_argument('--limit', type=int, help='Limit number of fixes shown')
    p.add_argument('--csv', help='Path to CSV to clean (will write <csv>.cleaned.csv).')
    args = p.parse_args()
    if args.csv:
        # clean CSV file directly
        from csv import reader, writer
        csv_path = args.csv
        if not os.path.exists(csv_path):
            print('CSV not found:', csv_path)
        else:
            out_path = csv_path + '.cleaned.csv'
            print('Cleaning CSV:', csv_path, '->', out_path)
            with open(csv_path, newline='', encoding='utf-8') as fin, open(out_path, 'w', newline='', encoding='utf-8') as fout:
                r = reader(fin)
                w = writer(fout)
                headers = next(r, None)
                if headers:
                    w.writerow(headers)
                    h_low = [h.lower() for h in headers]
                    for row in r:
                        if not row: continue
                        rowd = dict(zip(h_low, row))
                        if 'nom' in h_low and 'prenom' in h_low:
                            i_nom = h_low.index('nom')
                            i_prenom = h_low.index('prenom')
                            row[i_nom] = clean_name(row[i_nom])
                            row[i_prenom] = clean_name(row[i_prenom])
                        elif len(row) >= 2:
                            # try full name in first column
                            row[0] = ' '.join(clean_name(p) for p in row[0].split())
                        w.writerow(row)
            print('Wrote cleaned CSV to', out_path)
    else:
        main(apply_changes=args.apply, db_path=args.db, limit=args.limit)
