#!/usr/bin/env python3
"""Apply name_corrections_*.csv files to data/prepared_inserts.sql

Usage:
  scripts/apply_name_corrections.py [--apply]

Will produce `data/prepared_inserts.sql.fixed` (or overwrite with --apply after backup).
"""
import csv
import os
import re
import shutil

ROOT = os.path.dirname(os.path.dirname(__file__))
DATA = os.path.join(ROOT, 'data')
PREPARED_SQL = os.path.join(DATA, 'prepared_inserts.sql')

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


def load_corrections():
    corrections = {}
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
                    if new_nom == '' and new_prenom == '':
                        continue
                    corrections[idv] = (clean_name(new_nom) if new_nom else None, clean_name(new_prenom) if new_prenom else None)
    return corrections


def apply_corrections(apply=False):
    if not os.path.exists(PREPARED_SQL):
        print('prepared_inserts.sql not found at', PREPARED_SQL)
        return
    corrections = load_corrections()
    if not corrections:
        print('No corrections found in data/name_corrections_*.csv')
        return
    print('Loaded corrections for IDs:', sorted(corrections.keys())[:20])
    out_lines = []
    changed = 0
    with open(PREPARED_SQL, encoding='utf-8') as f:
        for line in f:
            m = re.search(r"VALUES\s*\((\d+),\s*'([^']*)',\s*'([^']*)'", line)
            if m:
                idv = int(m.group(1))
                if idv in corrections:
                    new_nom, new_prenom = corrections[idv]
                    nom = new_nom if new_nom else m.group(2)
                    prenom = new_prenom if new_prenom else m.group(3)
                    # escape single quotes
                    nom_esc = nom.replace("'", "''")
                    prenom_esc = prenom.replace("'", "''")
                    new_line = re.sub(r"VALUES\s*\(\d+,\s*'[^']*',\s*'[^']*'",
                                      f"VALUES({idv}, '{nom_esc}', '{prenom_esc}'", line, count=1)
                    out_lines.append(new_line)
                    changed += 1
                    continue
            out_lines.append(line)
    print(f'Prepared {len(out_lines)} lines, {changed} modifications applied.')
    out_path = PREPARED_SQL + ('.fixed' if not apply else '')
    if apply:
        bak = PREPARED_SQL + '.bak'
        print('Backing up original to', bak)
        shutil.copy2(PREPARED_SQL, bak)
        with open(PREPARED_SQL, 'w', encoding='utf-8') as f:
            f.writelines(out_lines)
        print('Written updates to', PREPARED_SQL)
    else:
        out_path = PREPARED_SQL + '.fixed'
        with open(out_path, 'w', encoding='utf-8') as f:
            f.writelines(out_lines)
        print('Wrote fixed file to', out_path)


if __name__ == '__main__':
    import argparse
    p = argparse.ArgumentParser()
    p.add_argument('--apply', action='store_true')
    args = p.parse_args()
    apply_corrections(apply=args.apply)
