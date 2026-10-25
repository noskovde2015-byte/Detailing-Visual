import argparse
import asyncio

from sqlalchemy import func, select

from app.db.db_helper import db_helper
from app.models.user import User


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Управление правами администратора")
    parser.add_argument("email")
    parser.add_argument("--revoke", action="store_true", help="Снять права")
    return parser.parse_args()


async def main() -> None:
    args = parse_args()
    try:
        async with db_helper.session_factory() as session:
            user = await session.scalar(
                select(User).where(func.lower(User.email) == args.email.lower())
            )
            if user is None:
                raise SystemExit(
                    f"Пользователь {args.email} не найден: сначала войдите на сайт"
                )

            user.is_admin = not args.revoke
            if user.is_admin:
                user.is_blocked = False
            await session.commit()

        action = "сняты" if args.revoke else "выданы"
        print(f"Права администратора {action}: {args.email}")
    finally:
        await db_helper.dispose()


if __name__ == "__main__":
    asyncio.run(main())
