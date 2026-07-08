"""
Bench commands for erpnext_traduction_fr.

Convention v16 : frappe.utils.bench_helper.get_app_commands() looks for
`{app}.commands` and reads its `commands` list. Each item is a click.Command.

Usage:
    bench --site <site> build-fr-translations           # extract + worklist
    bench --site <site> build-fr-translations --auto    # + Anthropic auto-translate
    bench --site <site> build-fr-translations --assemble# merge glossaire+worklist -> translations/fr.csv
    bench --site <site> build-fr-translations --app erpnext --assemble
"""

import csv
import os
import re

import click

APP_NAME = "erpnext_traduction_fr"

# Tokens that MUST be preserved verbatim in any translation:
#   {0} {name}  → placeholders
#   %s %(name)s → printf style
#   HTML tags <a href="..."> </a>
#   Code spans `foo`
_TOKEN_PATTERNS = [
    re.compile(r"\{[\w.]*\}"),
    re.compile(r"%(?:\([^)]+\))?[sdif]"),
    re.compile(r"<[^>]+>"),
    re.compile(r"`[^`]+`"),
]


# ─────────────────────────────────────────────────────────────────────
# Path helpers
# ─────────────────────────────────────────────────────────────────────
def _app_root():
    import frappe

    return frappe.get_app_path(APP_NAME)


def _glossaire_path():
    return os.path.join(_app_root(), "data", "glossaire.csv")


def _fr_csv_path():
    return os.path.join(_app_root(), "translations", "fr.csv")


def _worklist_path():
    return os.path.join(_app_root(), "data", "a_traduire.csv")


# ─────────────────────────────────────────────────────────────────────
# CSV I/O
# ─────────────────────────────────────────────────────────────────────
def _read_csv(path):
    """Return list of rows (lists)."""
    if not os.path.exists(path):
        return []
    with open(path, "r", encoding="utf-8", newline="") as f:
        return [row for row in csv.reader(f) if row]


def _write_csv(path, rows):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="") as f:
        w = csv.writer(f)
        w.writerows(rows)


def _load_glossaire():
    """Return dict source → traduction (header skipped if present)."""
    rows = _read_csv(_glossaire_path())
    out = {}
    for row in rows:
        if len(row) < 2:
            continue
        src, tr = row[0].strip(), row[1].strip()
        if src.lower() == "source" and tr.lower() == "traduction":
            continue  # header
        if src and tr:
            out[src] = tr
    return out


def _load_fr_csv():
    """Return dict (source, contexte) → traduction from current translations/fr.csv."""
    rows = _read_csv(_fr_csv_path())
    out = {}
    for row in rows:
        if not row:
            continue
        src = row[0]
        tr  = row[1] if len(row) > 1 else ""
        ctx = row[2] if len(row) > 2 else ""
        if src:
            out[(src, ctx)] = tr
    return out


# ─────────────────────────────────────────────────────────────────────
# Token / glossaire checks
# ─────────────────────────────────────────────────────────────────────
def _tokens_in(text):
    found = []
    for pat in _TOKEN_PATTERNS:
        found.extend(pat.findall(text or ""))
    return sorted(found)


def _tokens_preserved(src, tr):
    return _tokens_in(src) == _tokens_in(tr)


# ─────────────────────────────────────────────────────────────────────
# Extraction (uses real v16 frappe.translate API)
# ─────────────────────────────────────────────────────────────────────
def _collect_messages(apps):
    """Run frappe.translate.get_messages_for_app() per app and return the
    set of unique English source strings."""
    import frappe
    from frappe.translate import deduplicate_messages, get_messages_for_app

    messages = []
    for app in apps:
        try:
            messages.extend(get_messages_for_app(app))
        except Exception as exc:
            click.secho(f"  ⚠ {app}: extraction failed ({exc})", fg="yellow")

    messages = deduplicate_messages(messages)

    # frappe.translate yields tuples (path_or_None, message, context_or_None, ...)
    sources = set()
    for m in messages:
        if isinstance(m, tuple) and len(m) >= 2 and m[1]:
            sources.add(m[1])
    return sources


def _missing_for_lang(sources, lang="fr"):
    """Strings still without a French translation in the current Frappe state."""
    import frappe
    from frappe.translate import get_all_translations

    full = get_all_translations(lang) or {}
    missing = []
    for src in sources:
        if not full.get(src):
            missing.append(src)
    return missing


# ─────────────────────────────────────────────────────────────────────
# Optional Anthropic auto-translation (maintainer tool, never commits keys)
# ─────────────────────────────────────────────────────────────────────
def _auto_translate(missing, glossaire):
    """Call Anthropic API. Returns dict source → traduction (may be empty
    if API key is missing or batch fails). Strings the model is unsure
    about must stay empty."""
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        click.secho(
            "  ⚠ ANTHROPIC_API_KEY non défini — auto-traduction ignorée",
            fg="yellow",
        )
        return {}

    try:
        import anthropic
    except ImportError:
        click.secho(
            "  ⚠ pip install anthropic — auto-traduction ignorée",
            fg="yellow",
        )
        return {}

    client = anthropic.Anthropic(api_key=api_key)
    out = {}
    glossary_lines = "\n".join(f"  {s} -> {t}" for s, t in glossaire.items())

    BATCH = 40
    for i in range(0, len(missing), BATCH):
        chunk = missing[i : i + BATCH]
        items = "\n".join(f"{n+1}. {s}" for n, s in enumerate(chunk))

        prompt = (
            "Tu es un traducteur EN→FR pour une ERP (Frappe/ERPNext).\n"
            "Glossaire de référence à respecter strictement :\n"
            f"{glossary_lines}\n\n"
            "Règles absolues :\n"
            "- Préserve {0} {nom} %s %(x)s, balises HTML, codes `…`, noms propres.\n"
            "- Pas de ponctuation supplémentaire en fin.\n"
            "- Si tu doutes pour une chaîne, laisse-la VIDE.\n"
            "- Réponds en CSV pur : numéro,traduction. Une ligne par item.\n\n"
            f"Chaînes à traduire :\n{items}"
        )
        try:
            msg = client.messages.create(
                model="claude-opus-4-7",
                max_tokens=4096,
                messages=[{"role": "user", "content": prompt}],
            )
            text = msg.content[0].text
        except Exception as exc:
            click.secho(f"    ⚠ Anthropic error: {exc}", fg="yellow")
            continue

        for line in text.splitlines():
            m = re.match(r"^\s*(\d+)\s*,\s*(.*)$", line)
            if not m:
                continue
            idx = int(m.group(1)) - 1
            tr  = m.group(2).strip().strip('"')
            if 0 <= idx < len(chunk) and tr:
                src = chunk[idx]
                if _tokens_preserved(src, tr):
                    out[src] = tr

        click.echo(f"    auto-traduit batch {i // BATCH + 1}: {len(out)} cumul")

    return out


# ─────────────────────────────────────────────────────────────────────
# Click command
# ─────────────────────────────────────────────────────────────────────
@click.command("build-fr-translations")
@click.option("--app", default=None, help="Restreint à une seule app.")
@click.option("--auto", is_flag=True, help="Auto-traduit via Anthropic (clé en ENV).")
@click.option(
    "--assemble",
    is_flag=True,
    help="Fusionne glossaire + a_traduire.csv dans translations/fr.csv.",
)
@click.pass_context
def build_fr_translations(ctx, app, auto, assemble):
    """Build/refresh the FR overlay translations for this site's apps."""
    import frappe
    from frappe.translate import clear_cache

    sites = ctx.obj.sites if hasattr(ctx.obj, "sites") else None
    if not sites:
        click.secho("Aucun site (utilise --site).", fg="red")
        ctx.exit(1)

    for site in sites:
        click.echo(f"\n══ Site: {site} ══")
        frappe.init(site=site)
        frappe.connect()
        try:
            installed = frappe.get_installed_apps()
            apps = [app] if app else installed
            apps = [a for a in apps if a in installed]
            click.echo(f"Apps scannées : {', '.join(apps)}")

            click.echo("  → extraction des chaînes …")
            sources = _collect_messages(apps)
            click.echo(f"    {len(sources)} chaînes uniques")

            click.echo("  → calcul des manquantes (fr) …")
            missing = _missing_for_lang(sources, "fr")
            click.echo(f"    {len(missing)} sans traduction française")

            glossaire = _load_glossaire()
            current   = _load_fr_csv()
            click.echo(
                f"  glossaire: {len(glossaire)} entrées • "
                f"fr.csv actuel: {len(current)} lignes"
            )

            still_missing = [s for s in missing if s not in glossaire]
            click.echo(f"  → worklist a_traduire.csv : {len(still_missing)} lignes")
            _write_csv(
                _worklist_path(),
                [["source", "traduction"]] + [[s, ""] for s in sorted(still_missing)],
            )

            auto_results = {}
            if auto and still_missing:
                click.echo("  → auto-traduction Anthropic …")
                auto_results = _auto_translate(still_missing, glossaire)
                click.echo(f"    {len(auto_results)} chaînes auto-traduites")
                # rewrite worklist with auto results, marked "à relire"
                _write_csv(
                    _worklist_path(),
                    [["source", "traduction", "statut"]]
                    + [
                        [s, auto_results.get(s, ""), "à relire" if s in auto_results else ""]
                        for s in sorted(still_missing)
                    ],
                )

            if assemble:
                click.echo("  → assemblage translations/fr.csv …")
                merged = {}

                # 1. glossaire d'abord (autorité)
                for src, tr in glossaire.items():
                    merged[(src, "")] = tr

                # 2. fr.csv existant (préserve les contextes)
                for (src, ctxt), tr in current.items():
                    if (src, ctxt) not in merged and tr:
                        merged[(src, ctxt)] = tr

                # 3. worklist relue (3 colonnes : source, traduction, statut)
                wl = _read_csv(_worklist_path())
                for row in wl[1:]:
                    if len(row) >= 2 and row[0] and row[1]:
                        src, tr = row[0], row[1]
                        if (src, "") not in merged:
                            merged[(src, "")] = tr

                # 4. contrôle cohérence : un terme du glossaire ne doit pas être
                #    traduit autrement ailleurs
                conflicts = []
                for (src, ctxt), tr in merged.items():
                    if src in glossaire and ctxt == "" and tr != glossaire[src]:
                        conflicts.append((src, tr, glossaire[src]))
                if conflicts:
                    click.secho(
                        f"  ⚠ {len(conflicts)} incohérences glossaire :", fg="yellow"
                    )
                    for src, tr, gtr in conflicts[:10]:
                        click.echo(f"      « {src} » → « {tr} » ≠ glossaire « {gtr} »")

                # 5. contrôle tokens
                broken = [
                    (src, tr)
                    for (src, _), tr in merged.items()
                    if tr and not _tokens_preserved(src, tr)
                ]
                if broken:
                    click.secho(
                        f"  ⚠ {len(broken)} traductions cassent les tokens "
                        "({0}, %s, HTML) — non écrites",
                        fg="yellow",
                    )
                    for src, tr in broken:
                        merged.pop((src, ""), None)

                # 6. écriture finale
                final_rows = [
                    [src, tr, ctxt]
                    for (src, ctxt), tr in sorted(merged.items())
                    if tr
                ]
                _write_csv(_fr_csv_path(), final_rows)
                click.echo(f"    {len(final_rows)} lignes écrites dans translations/fr.csv")

                clear_cache()
                click.echo("  cache vidé.")

            click.secho(
                f"\nRécap : scannées={len(sources)} • manquantes={len(missing)} • "
                f"auto={len(auto_results)} • worklist={len(still_missing)}",
                fg="green",
            )
        finally:
            frappe.destroy()


commands = [build_fr_translations]
