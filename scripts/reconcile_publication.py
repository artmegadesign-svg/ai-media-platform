"""Inspect or reconcile exactly one publication. Never sends or enqueues work."""

import argparse
import json
import os
from pathlib import Path
import sys


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("content_id", type=int)
    parser.add_argument("--database-env", default="AMP_RECONCILE_DATABASE_URL")
    parser.add_argument("--resolve", choices=["published", "failed", "unknown"])
    parser.add_argument("--expected-status", choices=["publishing", "unknown"])
    parser.add_argument("--expected-claim-token", help="Use legacy-none only for a NULL claim")
    parser.add_argument("--operator")
    parser.add_argument("--reason", help="Evidence; message absence alone is insufficient")
    parser.add_argument("--message-id", type=int)
    parser.add_argument("--confirm-no-inflight", action="store_true")
    args = parser.parse_args(argv)
    if args.content_id <= 0:
        parser.error("content_id must be positive")
    url = os.environ.get(args.database_env)
    if not url:
        parser.error("An explicit administrative database environment variable is required")
    if args.resolve and not all((args.expected_status, args.expected_claim_token,
                                 args.operator, args.reason, args.confirm_no_inflight)):
        parser.error("Resolution requires expected state/claim, operator, evidence and no-inflight confirmation")
    if not args.resolve and any((args.expected_status, args.expected_claim_token,
                                  args.operator, args.reason, args.message_id, args.confirm_no_inflight)):
        parser.error("Resolution options require --resolve")
    # Never implicitly choose DATABASE_URL or a dotenv production database.
    os.environ["DATABASE_URL"] = url
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker
    from services.publisher.publisher_service import PublisherService

    engine = create_engine(url.replace("postgresql+asyncpg://", "postgresql+psycopg2://"))
    service = PublisherService(session_factory=sessionmaker(bind=engine, autoflush=False))
    try:
        if args.resolve:
            result = service.reconcile(
                args.content_id, expected_status=args.expected_status,
                expected_claim_token=None if args.expected_claim_token == "legacy-none" else args.expected_claim_token,
                outcome=args.resolve, operator=args.operator, reason=args.reason,
                confirm_no_inflight=args.confirm_no_inflight, message_id=args.message_id,
            )
        else:
            result = service.inspect(args.content_id)
        print(json.dumps(result, ensure_ascii=False, default=str))
    finally:
        engine.dispose()


if __name__ == "__main__":
    main()
