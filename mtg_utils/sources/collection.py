"""ManaBox collection export: the authoritative ownership source."""
import csv
import os
from collections import defaultdict

from mtg_utils.cards import front_name

# Where the export is read from: `--collection`, else $MTG_COLLECTION, else
# this default. Read at CALL time, so the CLI can set it after import.
COLLECTION = os.environ.get("MTG_COLLECTION",
                            "/mnt/project/ManaBox_Collection.csv")


# ============================================================ collection
def load_collection(path=None):
    path = path or COLLECTION
    if not os.path.exists(path):
        # A bare FileNotFoundError here used to end `audit` halfway through,
        # after verify and mana had printed, as a traceback.
        raise SystemExit(
            f"no ManaBox collection export at {path}. Ownership (own, roster, "
            f"ceiling, contention, audit) needs one: pass --collection PATH "
            f"or set MTG_COLLECTION.")
    owned = defaultdict(int)
    with open(path, encoding="utf-8-sig") as f:
        for r in csv.DictReader(f):
            q = int(r["Quantity"])
            n = r["Name"].strip().lower()
            owned[n] += q
            fn = front_name(n)
            if fn != n:
                owned[fn] += q
    return owned
