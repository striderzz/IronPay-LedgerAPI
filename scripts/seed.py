"""Demo data: two users with funded wallets. Safe to run more than once.

Usage: python -m scripts.seed
"""

import uuid

from sqlalchemy import select

from app.db import SessionLocal
from app.models import Account, User
from app.security import hash_password
from app.services.ledger import deposit

DEMO_PASSWORD = "demo-password-123"  # local demo only
DEMO_USERS = [("asha", 1_000_000), ("riya", 1_000_000)]  # 10,000 rupees each


def main() -> None:
    with SessionLocal() as session:
        for name, opening_minor in DEMO_USERS:
            email = f"{name}@example.com"
            if session.execute(select(User).where(User.email == email)).scalar_one_or_none():
                print(f"{email} exists, skipping")
                continue
            user = User(id=uuid.uuid4(), email=email, password_hash=hash_password(DEMO_PASSWORD))
            session.add(user)
            session.flush()
            account = Account(
                id=uuid.uuid4(), user_id=user.id, handle=f"{name}@ironpay", kind="wallet"
            )
            session.add(account)
            session.flush()
            deposit(session, to_account_id=account.id, amount_minor=opening_minor)
            print(f"created {email} with wallet {account.handle} ({account.id})")
        session.commit()


if __name__ == "__main__":
    main()
