import smtplib
import ssl

TIMEOUT_SECONDS = 60


class SmtpError(Exception):
    pass


class SmtpAuthError(SmtpError):
    pass


class SmtpRecipientError(SmtpError):
    pass


def send_mail(account, password, recipients, raw):
    """Wysyła wiadomość. Zwraca odbiorców, których serwer odrzucił."""
    provider = account.provider
    try:
        with smtplib.SMTP(
            provider.smtp_host, provider.smtp_port, timeout=TIMEOUT_SECONDS
        ) as smtp:
            smtp.starttls(context=ssl.create_default_context())
            smtp.login(account.email, password)
            return smtp.sendmail(account.email, recipients, raw)
    except smtplib.SMTPAuthenticationError as error:
        raise SmtpAuthError(str(error)) from error
    except smtplib.SMTPRecipientsRefused as error:
        raise SmtpRecipientError(str(error)) from error
    except (smtplib.SMTPException, OSError, UnicodeError) as error:
        raise SmtpError(str(error)) from error
