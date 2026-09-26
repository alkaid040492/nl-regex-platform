"""
Generate a large synthetic CSV for load testing (default 2,000,000 rows, ~180 MB).

    python scripts/generate_large_csv.py --rows 2000000 --out scripts/out/large.csv

Columns: ID, Name, Email, Phone, JoinDate, Notes. Roughly 70% of rows contain an email
in the Email column and 30% of Notes mention a second email, so matched-row counts are
non-trivial.
"""
from __future__ import annotations

import argparse
import csv
import os
import random
import time

FIRST = ["john", "jane", "alice", "bob", "carol", "dave", "eve", "frank", "grace", "heidi", "ivan", "judy"]
LAST = ["doe", "smith", "brown", "lee", "king", "patel", "garcia", "nguyen", "kim", "chen", "wang", "muller"]
DOMAINS = ["example.com", "domain.com", "website.org", "mail.co.uk", "corp.io", "test.net"]
NOTES = ["Prefers SMS", "Call after 5pm", "", "VIP customer", "Do not contact", "Alt contact {email}", "Ref #{n}"]


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--rows", type=int, default=2_000_000)
    ap.add_argument("--out", default="scripts/out/large.csv")
    ap.add_argument("--seed", type=int, default=42)
    args = ap.parse_args()

    random.seed(args.seed)
    os.makedirs(os.path.dirname(args.out) or ".", exist_ok=True)
    start = time.time()
    with open(args.out, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["ID", "Name", "Email", "Phone", "JoinDate", "Notes"])
        for i in range(1, args.rows + 1):
            fn, ln = random.choice(FIRST), random.choice(LAST)
            email = f"{fn}.{ln}{random.randint(1, 999)}@{random.choice(DOMAINS)}" if random.random() < 0.7 else ""
            phone = f"+1-{random.randint(200, 999)}-{random.randint(200, 999)}-{random.randint(1000, 9999)}"
            date = f"{random.randint(2015, 2024)}/{random.randint(1, 12):02d}/{random.randint(1, 28):02d}"
            note = random.choice(NOTES).format(email=f"{ln}@{random.choice(DOMAINS)}", n=random.randint(1000, 99999))
            w.writerow([i, f"{fn.title()} {ln.title()}", email, phone, date, note])
            if i % 500_000 == 0:
                print(f"  {i:,} rows...", flush=True)
    size_mb = os.path.getsize(args.out) / 1024 / 1024
    print(f"wrote {args.rows:,} rows to {args.out} ({size_mb:.1f} MB) in {time.time() - start:.1f}s")


if __name__ == "__main__":
    main()
