"""
Outbound transactional email.

No email provider is configured for this project yet (checked -- no SMTP,
no SendGrid/Resend/Mailgun, nothing). Rather than block the whole
password-reset feature on that, this degrades gracefully: with no
RESEND_API_KEY set, it logs the email's content (including the reset
link) to stdout instead of sending it -- visible in `railway logs` in
production, so a reset can still be completed manually by whoever runs
the app until a real provider is wired up. The moment RESEND_API_KEY is
set, this starts actually sending, no other code changes needed.

Resend specifically because its free tier (3,000 emails/month) needs no
domain verification if you send from their shared onboarding@resend.dev
address (see RESEND_FROM_EMAIL in config) -- signing up for a key is the
only setup step. Swap providers later by rewriting just this file.
"""
import httpx
from app.core.config import settings


async def send_password_reset_email(to_email: str, reset_link: str) -> None:
    subject = "Reset your FantasyFootballCrew password"
    text_body = (
        f"Someone (hopefully you) requested a password reset.\n\n"
        f"Reset your password: {reset_link}\n\n"
        f"This link expires in 1 hour. If you didn't request this, you can ignore this email."
    )

    if not settings.RESEND_API_KEY:
        print(
            f"[email stub -- no RESEND_API_KEY configured] "
            f"Password reset for {to_email}: {reset_link}",
            flush=True,
        )
        return

    async with httpx.AsyncClient(timeout=10) as client:
        try:
            resp = await client.post(
                "https://api.resend.com/emails",
                headers={"Authorization": f"Bearer {settings.RESEND_API_KEY}"},
                json={
                    "from": settings.RESEND_FROM_EMAIL,
                    "to": [to_email],
                    "subject": subject,
                    "text": text_body,
                },
            )
            resp.raise_for_status()
        except Exception as e:
            # Don't let an email-provider hiccup surface as a 500 to the
            # user on a request that already succeeded server-side (the
            # token is created either way) -- log it and move on. Falling
            # back to the stub log means the link is still recoverable.
            print(f"[email send FAILED, falling back to log] {to_email}: {reset_link} -- {e}", flush=True)


async def send_league_invite_email(
    to_email: str,
    league_name: str,
    inviter_name: str,
    personal_message: str | None,
    invite_link: str,
) -> None:
    """Second single-purpose email function, same shape as
    send_password_reset_email above (graceful no-key stub, swallow-and-
    log send failures) -- not worth extracting a shared low-level sender
    for just two email types; revisit if a third one shows up."""
    subject = f"{inviter_name} invited you to join {league_name} on FantasyFootballCrew"
    message_block = f"\n\n\"{personal_message}\"\n" if personal_message else ""
    text_body = (
        f"{inviter_name} invited you to join their fantasy football league, {league_name}.\n"
        f"{message_block}\n"
        f"Join here: {invite_link}\n\n"
        f"This link expires in 14 days."
    )

    if not settings.RESEND_API_KEY:
        print(
            f"[email stub -- no RESEND_API_KEY configured] "
            f"League invite for {to_email} to '{league_name}': {invite_link}",
            flush=True,
        )
        return

    async with httpx.AsyncClient(timeout=10) as client:
        try:
            resp = await client.post(
                "https://api.resend.com/emails",
                headers={"Authorization": f"Bearer {settings.RESEND_API_KEY}"},
                json={
                    "from": settings.RESEND_FROM_EMAIL,
                    "to": [to_email],
                    "subject": subject,
                    "text": text_body,
                },
            )
            resp.raise_for_status()
        except Exception as e:
            print(f"[email send FAILED, falling back to log] {to_email}: {invite_link} -- {e}", flush=True)
