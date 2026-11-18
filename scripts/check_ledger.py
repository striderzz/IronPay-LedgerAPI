"""Ledger invariant checker. Prints a JSON report and exits 1 if anything is off.

Usage: python -m scripts.check_ledger
"""

import json
import sys

from app.db import SessionLocal
from app.services.checker import run_checks


def main() -> int:
    with SessionLocal() as session:
        report = run_checks(session)
    print(json.dumps(report, indent=2))
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    sys.exit(main())
