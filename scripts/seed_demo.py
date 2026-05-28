"""
Creates the auth accounts needed to call the API.

This does NOT insert any business data (brands, mentions, etc.).
Brands/products come from `seed_pharma_dictionary.py`; mentions come
from the real ingestion pipeline.

Idempotent.
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from core.config import settings
from core.security import hash_password
from models.user import User, UserRole


DEMO_PASSWORD = "demopass123"

USERS = [
    ("admin@pharmawatch.eu", UserRole.admin),
    ("pharmacist@pharmawatch.eu", UserRole.pharmacist),
    ("lab@pharmawatch.eu", UserRole.lab_user),
]


def main():
    engine = create_engine(settings.DATABASE_SYNC_URL)
    with Session(engine) as db:
        created = 0
        for email, role in USERS:
            existing = db.execute(select(User).where(User.email == email)).scalar_one_or_none()
            if existing:
                continue
            db.add(User(
                email=email,
                hashed_password=hash_password(DEMO_PASSWORD),
                role=role,
                is_active=True,
            ))
            created += 1
        db.commit()
    print(f"Users ensured ({created} new). Password: {DEMO_PASSWORD}")


if __name__ == "__main__":
    main()