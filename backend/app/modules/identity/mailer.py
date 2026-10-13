"""Correo del segundo factor (patrón de `sample/backend/app/modules/admin/email_service.py`)."""
import smtplib
from flask import current_app
from flask_mail import Message, Connection
from app.extensions import mail


class TimedConnection(Connection):
    def configure_host(self):
        cls = smtplib.SMTP_SSL if self.mail.use_ssl else smtplib.SMTP
        host = cls(self.mail.server, self.mail.port, timeout=10)
        if self.mail.use_tls:
            host.starttls()
        if self.mail.username and self.mail.password:
            host.login(self.mail.username, self.mail.password)
        return host


def send_email(subject, recipients, html_body, text_body):
    if current_app.config.get('MAIL_SUPPRESS_SEND') and not current_app.testing:
        raise RuntimeError('Mail sending is suppressed')
    msg = Message(subject, recipients=recipients, body=text_body, html=html_body)
    if current_app.testing and current_app.config.get('MAIL_CAPTURE') is not None:
        current_app.config['MAIL_CAPTURE'].append(msg)
        return
    with TimedConnection(current_app.extensions['mail']) as connection:
        connection.send(msg)


def send_2fa_email(to_email, code):
    html = (f'<div style="font-family:Segoe UI,Arial,sans-serif;color:#22243b"><h2>Compra Clara · Lavalleja</h2>'
            f'<p>Tu código de verificación es:</p><p style="font-size:28px;letter-spacing:8px;font-weight:700">{code}</p>'
            f'<p>Vence en 10 minutos. Si no iniciaste sesión, ignorá este mensaje.</p></div>')
    send_email('[Compra Clara] Código de verificación', [to_email], html,
               f'Tu código de verificación es {code}. Vence en 10 minutos.')
