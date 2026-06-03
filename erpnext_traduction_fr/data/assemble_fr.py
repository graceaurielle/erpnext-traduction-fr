"""
Assemble translations/fr.csv from:
  1. data/glossaire.csv  (authority)
  2. existing translations/fr.csv
  3. data/a_traduire.csv (worklist, filled manually + chunks)

Validates token preservation and glossaire coherence.
Run from bench root: python3 apps/erpnext_traduction_fr/.../data/assemble_fr.py
"""
import csv
import os
import re

ROOT = os.path.dirname(os.path.abspath(__file__))
APP_ROOT = os.path.dirname(ROOT)

GLOSSAIRE = os.path.join(ROOT, "glossaire.csv")
WORKLIST  = os.path.join(ROOT, "a_traduire.csv")
FR_CSV    = os.path.join(APP_ROOT, "translations", "fr.csv")

TOKEN_PATTERNS = [
    re.compile(r"\{[\w.]*\}"),
    re.compile(r"%(?:\([^)]+\))?[sdif]"),
    re.compile(r"<[^>]+>"),
    re.compile(r"`[^`]+`"),
]

def tokens_in(text):
    found = []
    for pat in TOKEN_PATTERNS:
        found.extend(pat.findall(text or ""))
    return sorted(found)

def tokens_ok(src, tr):
    return tokens_in(src) == tokens_in(tr)

def read_csv(path):
    if not os.path.exists(path):
        return []
    with open(path, encoding="utf-8", newline="") as f:
        return [r for r in csv.reader(f) if r]

def write_csv(path, rows):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="") as f:
        w = csv.writer(f)
        w.writerows(rows)

# Load glossaire
glossaire = {}
for row in read_csv(GLOSSAIRE):
    if len(row) < 2: continue
    s, t = row[0].strip(), row[1].strip()
    if s.lower() == "source": continue
    if s and t:
        glossaire[s] = t

# Load existing fr.csv
existing = {}
for row in read_csv(FR_CSV):
    if not row: continue
    src = row[0]
    tr  = row[1] if len(row) > 1 else ""
    ctx = row[2] if len(row) > 2 else ""
    if src and tr:
        existing[(src, ctx)] = tr

# Load worklist
worklist = {}
for row in read_csv(WORKLIST):
    if len(row) >= 2 and row[0] and row[1]:
        worklist[row[0].strip()] = row[1].strip()

print(f"Glossaire: {len(glossaire)} | fr.csv existant: {len(existing)} | worklist: {len(worklist)}")

merged = {}

# 1. glossaire (authority)
for src, tr in glossaire.items():
    merged[(src, "")] = tr

# 2. existing fr.csv
for (src, ctx), tr in existing.items():
    if (src, ctx) not in merged and tr:
        merged[(src, ctx)] = tr

# 3. worklist
for src, tr in worklist.items():
    if (src, "") not in merged and tr:
        merged[(src, "")] = tr

# Validate tokens
broken = [(src, tr) for (src, _), tr in merged.items() if tr and not tokens_ok(src, tr)]
if broken:
    print(f"⚠ {len(broken)} traductions cassent les tokens — non écrites")
    for src, tr in broken[:5]:
        print(f"  '{src[:60]}' -> '{tr[:60]}'")
    for src, _ in broken:
        merged.pop((src, ""), None)

final = [[src, tr, ctx] for (src, ctx), tr in sorted(merged.items()) if tr]
write_csv(FR_CSV, final)
print(f"✓ {len(final)} lignes écrites dans translations/fr.csv")
