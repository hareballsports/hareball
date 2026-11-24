import json
import os
from datetime import datetime
from zoneinfo import ZoneInfo

import gspread

# Log in to Google as the robot user, using the key stored in GitHub Secrets
creds = json.loads(os.environ["GOOGLE_CREDENTIALS"])
gc = gspread.service_account_from_dict(creds)
sheet = gc.open_by_key(os.environ["SHEET_ID"])

# Find (or create) a tab called "Connection Test"
try:
    tab = sheet.worksheet("Connection Test")
except gspread.WorksheetNotFound:
    tab = sheet.add_worksheet(title="Connection Test", rows=100, cols=3)

# Write the current Central time into cells A1:B1
now = datetime.now(ZoneInfo("America/Chicago")).strftime("%Y-%m-%d %I:%M:%S %p %Z")
tab.update(range_name="A1:B1", values=[["Last successful run", now]])
print(f"Wrote {now} to '{sheet.title}'")
