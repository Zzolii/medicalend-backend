# Path: backend/app/services/appointment_reminders.py

from datetime import datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo

from sqlalchemy.orm import Session

from app import models
from app.utils.mail import send_email

APP_TIMEZONE = ZoneInfo("Europe/Bucharest")


def _patient_name(patient: models.Patient) -> str:
    first_name = getattr(patient, "first_name", None) or ""
    last_name = getattr(patient, "last_name", None) or ""
    full_name = f"{first_name} {last_name}".strip()
    return full_name or "pacient"


def _provider_name(provider: models.Provider | None) -> str:
    if not provider:
        return "furnizorul medical"
    return getattr(provider, "name", None) or "furnizorul medical"


def _doctor_name(doctor) -> str | None:
    if not doctor:
        return None

    title = getattr(doctor, "title", None) or ""
    name = getattr(doctor, "name", None) or ""
    full_name = f"{title} {name}".strip()
    return full_name or None


def _as_bucharest_datetime(value: datetime) -> datetime:
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(APP_TIMEZONE)


def _build_reminder_email(appointment: models.Appointment) -> tuple[str, str, str]:
    patient = appointment.patient
    provider = appointment.provider
    doctor = appointment.doctor

    patient_name = _patient_name(patient)
    provider_name = _provider_name(provider)
    doctor_name = _doctor_name(doctor)

    start_local = _as_bucharest_datetime(appointment.start_time)
    date_text = start_local.strftime("%d.%m.%Y")
    time_text = start_local.strftime("%H:%M")

    subject = "Memento programare – MediCalend"

    doctor_line = f"\nMedic: {doctor_name}" if doctor_name else ""
    notes_line = f"\nObservații: {appointment.notes}" if appointment.notes else ""

    text_body = (
        f"Bună, {patient_name}!\n\n"
        "Îți reamintim că ai o programare astăzi prin MediCalend.\n\n"
        f"Data: {date_text}\n"
        f"Ora: {time_text}\n"
        f"Clinică / furnizor: {provider_name}"
        f"{doctor_line}"
        f"{notes_line}\n\n"
        "Te rugăm să ajungi la timp. Dacă nu mai poți ajunge, contactează clinica.\n\n"
        "Acest mesaj este trimis automat de MediCalend."
    )

    html_doctor_line = f"<p><strong>Medic:</strong> {doctor_name}</p>" if doctor_name else ""
    html_notes_line = f"<p><strong>Observații:</strong> {appointment.notes}</p>" if appointment.notes else ""

    html_body = f"""
    <html>
      <body>
        <p>Bună, {patient_name}!</p>
        <p>Îți reamintim că ai o programare astăzi prin <strong>MediCalend</strong>.</p>
        <p><strong>Data:</strong> {date_text}</p>
        <p><strong>Ora:</strong> {time_text}</p>
        <p><strong>Clinică / furnizor:</strong> {provider_name}</p>
        {html_doctor_line}
        {html_notes_line}
        <p>Te rugăm să ajungi la timp. Dacă nu mai poți ajunge, contactează clinica.</p>
        <p>Acest mesaj este trimis automat de MediCalend.</p>
      </body>
    </html>
    """

    return subject, text_body, html_body


def send_due_appointment_email_reminders(db: Session, now: datetime | None = None) -> dict:
    current_local = now.astimezone(APP_TIMEZONE) if now else datetime.now(APP_TIMEZONE)

    day_start_local = datetime.combine(current_local.date(), time.min, tzinfo=APP_TIMEZONE)
    day_end_local = day_start_local + timedelta(days=1)

    day_start_utc_naive = day_start_local.astimezone(timezone.utc).replace(tzinfo=None)
    day_end_utc_naive = day_end_local.astimezone(timezone.utc).replace(tzinfo=None)

    appointments = (
        db.query(models.Appointment)
        .filter(
            models.Appointment.status == "scheduled",
            models.Appointment.start_time >= day_start_utc_naive,
            models.Appointment.start_time < day_end_utc_naive,
            models.Appointment.reminder_email_sent_at.is_(None),
        )
        .order_by(models.Appointment.start_time.asc())
        .all()
    )

    sent = 0
    skipped = 0
    failed = 0

    for appointment in appointments:
        patient = appointment.patient

        recipient = None
        if patient:
            recipient = getattr(patient, "email", None)

        if not recipient and patient and patient.user:
            recipient = getattr(patient.user, "email", None)

        if not recipient:
            skipped += 1
            continue

        try:
            subject, text_body, html_body = _build_reminder_email(appointment)
            send_email(recipient, subject, text_body, html_body)

            appointment.reminder_email_sent_at = datetime.now(timezone.utc)
            db.add(appointment)
            db.commit()
            sent += 1
        except Exception as exc:
            db.rollback()
            failed += 1
            print(
                "[APPOINTMENT REMINDER] send failed "
                f"appointment_id={appointment.id} recipient={recipient} error={exc}"
            )

    return {
        "checked": len(appointments),
        "sent": sent,
        "skipped": skipped,
        "failed": failed,
    }