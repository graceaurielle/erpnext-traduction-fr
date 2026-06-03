"""Reads all CSV files in data/trad_chunks/ and merges them into the worklist
(data/a_traduire.csv), filling the `traduction` column for matching sources.

Usage:
    python3 apps/erpnext_traduction_fr/erpnext_traduction_fr/data/apply_translations.py

Chunk files must be CSV with header `source,traduction` and one source per row.
"""

import csv
import glob
import os
import sys

ROOT = os.path.dirname(os.path.abspath(__file__))
CHUNKS_DIR = os.path.join(ROOT, "trad_chunks")
WORKLIST = os.path.join(ROOT, "a_traduire.csv")


def load_chunks():
    translations = {}
    files = sorted(glob.glob(os.path.join(CHUNKS_DIR, "*.csv")))
    for path in files:
        with open(path, encoding="utf-8", newline="") as f:
            reader = csv.reader(f)
            try:
                header = next(reader)
            except StopIteration:
                continue
            for row in reader:
                if len(row) >= 2 and row[0] and row[1]:
                    src = row[0]
                    tr = row[1]
                    translations[src] = tr
    return translations, files


def update_worklist(translations):
    with open(WORKLIST, encoding="utf-8", newline="") as f:
        rows = list(csv.reader(f))
    if not rows:
        return 0
    header = rows[0]
    out = [header]
    filled = 0
    for row in rows[1:]:
        if not row:
            out.append(row)
            continue
        src = row[0]
        current_tr = row[1] if len(row) > 1 else ""
        if src in translations and not current_tr:
            new_row = [src, translations[src]]
            if len(row) > 2:
                new_row.extend(row[2:])
            out.append(new_row)
            filled += 1
        else:
            out.append(row)
    with open(WORKLIST, "w", encoding="utf-8", newline="") as f:
        w = csv.writer(f)
        w.writerows(out)
    return filled


def main():
    translations, files = load_chunks()
    print(f"Loaded {len(translations)} unique translations from {len(files)} chunk file(s)")
    filled = update_worklist(translations)
    print(f"Filled {filled} rows in worklist a_traduire.csv")
    # Report remaining
    with open(WORKLIST, encoding="utf-8", newline="") as f:
        rows = list(csv.reader(f))
    missing = sum(1 for r in rows[1:] if r and r[0] and (len(r) < 2 or not r[1]))
    done = sum(1 for r in rows[1:] if r and r[0] and len(r) >= 2 and r[1])
    print(f"Worklist status: {done} traduites, {missing} encore vides")


if __name__ == "__main__":
    main()
