from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.database import SessionLocal
from app.services.whatsapp_tenant_relink import relink_whatsapp_communications_to_email_tenant


def main() -> int:
    parser = argparse.ArgumentParser(description="Repair WhatsApp communications linked to the wrong tenant row")
    parser.add_argument("--apply", action="store_true", help="Persist relinks instead of dry-running")
    parser.add_argument("--tenant-id", type=int, default=None, help="Limit repair to a single tenant id")
    parser.add_argument("--limit", type=int, default=None, help="Limit scanned communications")
    args = parser.parse_args()

    db = SessionLocal()
    try:
        results = relink_whatsapp_communications_to_email_tenant(
            db,
            tenant_id=args.tenant_id,
            apply=args.apply,
            limit=args.limit,
        )
        print(json.dumps({
            "apply": args.apply,
            "tenant_id": args.tenant_id,
            "limit": args.limit,
            "relinked_count": len(results),
            "relinks": [result.__dict__ for result in results],
        }, indent=2, default=str))
        return 0
    finally:
        db.close()


if __name__ == "__main__":
    raise SystemExit(main())
