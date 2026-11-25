"""Write tables to the Google Sheet and create the tabs you edit by hand.

Each data tab is only rewritten when its contents actually changed. A hidden
"_sync" tab remembers a fingerprint of what was last written, so if one run
fails to update the Sheet, the next run notices and catches it up.
"""

import hashlib
import json
import os

import gspread

CHUNK_ROWS = 5000  # send big tables in pieces so no single request is too large
SYNC_TAB = "_sync"


def open_sheet(env_name):
    creds = json.loads(os.environ["GOOGLE_CREDENTIALS"])
    client = gspread.service_account_from_dict(creds)
    return client.open_by_key(os.environ[env_name])


def _get_or_create(sheet, title, rows, cols):
    try:
        return sheet.worksheet(title), False
    except gspread.WorksheetNotFound:
        return sheet.add_worksheet(title=title, rows=max(rows, 10), cols=max(cols, 5)), True


def _cell(value):
    if value is None:
        return ""
    if isinstance(value, bool):
        return "TRUE" if value else "FALSE"
    return value


def to_values(header, rows):
    values = [list(header)]
    for r in rows:
        values.append([_cell(r.get(h, "")) for h in header] if isinstance(r, dict) else [_cell(v) for v in r])
    return values


def fingerprint(values):
    return hashlib.sha1(json.dumps(values, default=str).encode("utf-8")).hexdigest()


def write_values(sheet, title, values):
    """Replace a whole tab with these values (header first). For data tabs only."""
    ws, _ = _get_or_create(sheet, title, len(values), len(values[0]))
    ws.clear()
    ws.resize(rows=max(len(values), 2), cols=max(len(values[0]), 1))
    for start in range(0, len(values), CHUNK_ROWS):
        ws.update(values=values[start:start + CHUNK_ROWS], range_name=f"A{start + 1}",
                  value_input_option="USER_ENTERED")
    ws.freeze(rows=1)


def ensure_table(sheet, title, header, starter_rows=()):
    """Create a tab you edit by hand, only if it doesn't exist yet. Never overwrites your edits."""
    ws, created = _get_or_create(sheet, title, len(starter_rows) + 1, len(header))
    if created:
        ws.update(values=[list(header)] + [list(r) for r in starter_rows], range_name="A1",
                  value_input_option="USER_ENTERED")
        ws.freeze(rows=1)
    return ws


def read_sync(sheet):
    try:
        rows = sheet.worksheet(SYNC_TAB).get_all_values()
    except gspread.WorksheetNotFound:
        return {}
    return {r[0]: r[1] for r in rows[1:] if len(r) >= 2}


def write_sync(sheet, sync):
    values = [["tab", "fingerprint"]] + sorted([k, v] for k, v in sync.items())
    write_values(sheet, SYNC_TAB, values)
    try:
        sheet.worksheet(SYNC_TAB).hide()
    except Exception:  # hiding is cosmetic; never fail a run over it
        pass
