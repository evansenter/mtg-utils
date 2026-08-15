"""ManaBox collection export: the authoritative ownership source."""
import csv
from collections import defaultdict

from mtg_utils.cards import front_name

COLLECTION = "/mnt/project/ManaBox_Collection.csv"


# ============================================================ collection
def load_collection(path=COLLECTION):
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
