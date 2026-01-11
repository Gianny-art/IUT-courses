#!/usr/bin/env python3
"""Generate SQL updates from name_corrections_*.csv to apply to the DB later.
Output: data/name_corrections_updates.sql
"""
import os
import csv
import re

ROOT = os.path.dirname(os.path.dirname(__file__))
DATA = os.path.join(ROOT, 'data')
OUT = os.path.join(DATA, 'name_corrections_updates.sql')

PAREN_RE = re.compile(r"\([^)]*\)")
TRAILING_YEAR = re.compile(r"\b\d{2,4}\b")
FILIERE_KEYS = [
    'genie informatique', 'informatique', 'gin', 'gi', 'gi2', 'gi1', 'gl', 'gl2', 'gl1', 'info', 'info2', 'info1',
    'genie civil', 'genie electrique', 'genie mecanique', 'reseau', 'reseaux', 'telecoms', 'tc', 'ipi'
]
FILIERE_REGEX = re.compile(r"(^|\s)(" + r"|".join(re.escape(k) for k in FILIERE_KEYS) + r")(\b|$)", flags=re.I)


def clean_name(s: str) -> str:
    if not s: return s
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
    return cleaned.title() if cleaned else s


def main():
    corrections = []
    for fname in os.listdir(DATA):
        if fname.startswith('name_corrections') and fname.endswith('.csv'):
            path = os.path.join(DATA, fname)
            with open(path, newline='', encoding='utf-8') as f:
                r = csv.DictReader(f)
                for row in r:
                    try:
                        idv = int(row.get('id') or 0)
                    except ValueError:
                        continue
                    if idv == 0: continue
                    new_nom = (row.get('new_nom') or '').strip()
                    new_prenom = (row.get('new_prenom') or '').strip()
                    if not new_nom and not new_prenom:
                        continue
                    new_nom = clean_name(new_nom) if new_nom else None
                    new_prenom = clean_name(new_prenom) if new_prenom else None
                    corrections.append((idv, new_nom, new_prenom))
    if not corrections:
        print('No corrections found')
        return
    with open(OUT, 'w', encoding='utf-8') as f:
        for idv, nom, prenom in corrections:
            parts = []
            if nom:
                parts.append(f"nom='{nom.replace("'","''")}'")
            if prenom:
                parts.append(f"prenom='{prenom.replace("'","''")}'")
            if not parts: continue
            f.write(f"UPDATE users SET {', '.join(parts)} WHERE id={idv};\n")
    print('Wrote', OUT, 'with', len(corrections), 'updates')

if __name__ == '__main__':
    main()
