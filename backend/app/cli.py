"""TaskFlow command-line administrative management interface.

Provides idempotent CLI commands for managing global superusers.
Usage:
    python -m app.cli create-superuser --email admin@taskflow.dev --password MySecretPassword123!
    python -m app.cli promote-user --email existing_user@taskflow.dev
    python -m app.cli demote-user --email existing_user@taskflow.dev
"""

from __future__ import annotations

import argparse
import asyncio
import getpass
import sys

from sqlalchemy import func, select

from app.core.database import AsyncSessionLocal
from app.core.security import hash_password
from app.modules.users.models import User


async def create_superuser(
    email: str,
    password: str | None = None,
    full_name: str = "Global Administrator",
) -> None:
    """Create a new global superuser or idempotently promote an existing user."""
    clean_email = email.strip().lower()

    if not password:
        password = getpass.getpass("Enter password for superuser: ")
        confirm = getpass.getpass("Confirm password: ")
        if password != confirm:
            print("Error: Passwords do not match.", file=sys.stderr)
            sys.exit(1)

    if len(password) < 8:
        print("Error: Password must be at least 8 characters long.", file=sys.stderr)
        sys.exit(1)

    async with AsyncSessionLocal() as session:
        stmt = (
            select(User)
            .where(
                func.lower(User.email) == clean_email,
                User.deleted_at.is_(None),
            )
            .limit(1)
        )
        result = await session.execute(stmt)
        user = result.scalar_one_or_none()

        if user:
            user.is_superuser = True
            user.is_active = True
            if password:
                user.hashed_password = hash_password(password)
            if full_name and full_name != "Global Administrator":
                user.full_name = full_name
            await session.commit()
            print(f"Existing user '{clean_email}' successfully updated and promoted to superuser.")
        else:
            new_user = User(
                email=clean_email,
                hashed_password=hash_password(password),
                full_name=full_name,
                is_active=True,
                is_superuser=True,
            )
            session.add(new_user)
            await session.commit()
            print(f"Global superuser '{clean_email}' created successfully.")


async def promote_user(email: str) -> None:
    """Promote an existing user to global superuser."""
    clean_email = email.strip().lower()
    async with AsyncSessionLocal() as session:
        stmt = (
            select(User)
            .where(
                func.lower(User.email) == clean_email,
                User.deleted_at.is_(None),
            )
            .limit(1)
        )
        result = await session.execute(stmt)
        user = result.scalar_one_or_none()

        if not user:
            print(f"Error: Active user with email '{clean_email}' not found.", file=sys.stderr)
            sys.exit(1)

        user.is_superuser = True
        user.is_active = True
        await session.commit()
        print(f"User '{clean_email}' promoted to global superuser.")


async def demote_user(email: str) -> None:
    """Demote a global superuser to ordinary user status."""
    clean_email = email.strip().lower()
    async with AsyncSessionLocal() as session:
        stmt = (
            select(User)
            .where(
                func.lower(User.email) == clean_email,
                User.deleted_at.is_(None),
            )
            .limit(1)
        )
        result = await session.execute(stmt)
        user = result.scalar_one_or_none()

        if not user:
            print(f"Error: Active user with email '{clean_email}' not found.", file=sys.stderr)
            sys.exit(1)

        user.is_superuser = False
        await session.commit()
        print(f"Superuser status removed from user '{clean_email}'.")


def main() -> None:
    parser = argparse.ArgumentParser(description="TaskFlow administrative management CLI")
    subparsers = parser.add_subparsers(dest="command", required=True)

    # create-superuser
    create_parser = subparsers.add_parser(
        "create-superuser",
        help="Create or promote a user to global superuser",
    )
    create_parser.add_argument("--email", required=True, help="Superuser email address")
    create_parser.add_argument("--password", required=False, help="Superuser password")
    create_parser.add_argument(
        "--full-name",
        default="Global Administrator",
        help="Superuser full name",
    )

    # promote-user
    promote_parser = subparsers.add_parser(
        "promote-user",
        help="Promote an existing user to superuser",
    )
    promote_parser.add_argument("--email", required=True, help="User email address to promote")

    # demote-user
    demote_parser = subparsers.add_parser(
        "demote-user",
        help="Demote an existing superuser",
    )
    demote_parser.add_argument("--email", required=True, help="User email address to demote")

    args = parser.parse_args()

    if args.command == "create-superuser":
        asyncio.run(create_superuser(args.email, args.password, args.full_name))
    elif args.command == "promote-user":
        asyncio.run(promote_user(args.email))
    elif args.command == "demote-user":
        asyncio.run(demote_user(args.email))


if __name__ == "__main__":
    main()
