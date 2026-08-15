"""ManaBox collection export: the authoritative ownership source."""
import csv
from collections import defaultdict

COLLECTION = "/mnt/project/ManaBox_Collection.csv"


# ============================================================ collection
def load_collection(path=COLLECTION):
    owned = defaultdict(int)
    with open(path, encoding="utf-8-sig") as f:
        for r in csv.DictReader(f):
            q = int(r["Quantity"])
            n = r["Name"].strip().lower()
            owned[n] += q
            front_name = n.split(" // ")[0]
            if front_name != n:
                owned[front_name] += q
    return owned
