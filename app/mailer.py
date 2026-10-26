"""Optional SMTP delivery; TLS is mandatory."""
import smtplib
import ssl
from email.message import EmailMessage

def send_report(config, path, run_id):
    if not config.email_to:
        return False
    message = EmailMessage()
    message['Subject'] = f'IntelligenceOS opportunity report — run {run_id}'
    message['From'] = config.email_from
    message['To'] = ', '.join(config.email_to)
    message.set_content('Attached is the sourcing analysis. All opportunities require manual validation before purchase.')
    message.add_attachment(path.read_bytes(), maintype='application',
                           subtype='vnd.openxmlformats-officedocument.spreadsheetml.sheet', filename=path.name)
    if config.email_transport == 'gmail_api':
        from app.gmail_api import send_message
        if config.gmail_stage_file is not None:
            from ops.gmail_stage_tracking import StageTracker
            send_message(message, config.gmail_token_file, observe=StageTracker(config.gmail_stage_file))
        else:
            send_message(message, config.gmail_token_file)
        return True
    context = ssl.create_default_context()
    factory = smtplib.SMTP_SSL if config.smtp_security == 'ssl' else smtplib.SMTP
    kwargs = {'timeout': 30}
    if config.smtp_security == 'ssl': kwargs['context'] = context
    with factory(config.smtp_host, config.smtp_port, **kwargs) as client:
        if config.smtp_security == 'starttls': client.starttls(context=context)
        if config.smtp_user: client.login(config.smtp_user, config.smtp_password)
        client.send_message(message)
    return True
