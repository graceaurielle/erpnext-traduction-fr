"""
Install hooks for erpnext_traduction_fr.

The single goal here is to make sure that as soon as the app is installed,
the user gets French labels — without any manual step. We do two things:

1. clear the translation cache so the new fr.csv shipped with this app is
   picked up immediately ;
2. nudge the site's default language to "fr" *only if it has never been set*
   (we never overwrite an existing choice).
"""

import frappe
from frappe.translate import clear_cache


def after_install():
    try:
        clear_cache()
    except Exception:
        # The cache might not exist yet on a brand new site — that's fine.
        pass

    try:
        current = frappe.db.get_single_value("System Settings", "language")
        if not current:
            frappe.db.set_single_value("System Settings", "language", "fr")
            frappe.db.commit()
    except Exception:
        pass

    print("erpnext_traduction_fr : cache vidé, traductions FR actives.")
