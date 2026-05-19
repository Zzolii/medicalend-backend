# Path: backend/app/scripts/send_appointment_reminders.py

from app.db import SessionLocal
from app.services.appointment_reminders import send_due_appointment_email_reminders


def main() -> None:
    db = SessionLocal()
    try:
        result = send_due_appointment_email_reminders(db)
        print("[APPOINTMENT REMINDERS]", result)
    finally:
        db.close()


if __name__ == "__main__":
    main()