from app.config import settings
from app.database import Database


def main() -> None:
    db = Database(settings.database_url, settings.data_dir)
    try:
        print(db.create_backup(settings.backup_dir))
    finally:
        db.close()


if __name__ == "__main__":
    main()
