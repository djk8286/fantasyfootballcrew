"""
Outbound transactional email, sent via Resend (see RESEND_API_KEY /
RESEND_FROM_EMAIL in config -- domain is verified as of the Auth
Security Hardening follow-up, so sends aren't limited to Resend's
sandbox-only "your own signup address" restriction anymore). With no
RESEND_API_KEY set, this still degrades gracefully: it logs the email's
content (including the link) to stdout instead of sending it -- visible
in `railway logs` in production, so a link can still be delivered
manually if the key is ever unset.

Every email is sent as both HTML (branded, see _render_email below) and
a plain-text fallback in the same request -- Resend/every real mail
client picks whichever it can render; the plain-text body remains the
source of truth for the actual copy, the HTML just dresses it up.
"""
import html as html_module
import httpx
from sqlalchemy.ext.asyncio import AsyncSession
from app.core.config import settings
from app.models.email_send_log import EmailSendLog

# Matches the app's own theme (frontend/src/app/globals.css) so the email
# doesn't look like a different product from the site the link lands on.
_GOLD = "#d4af37"
_SURFACE_900 = "#0a0a0a"  # page background
_SURFACE_800 = "#1a1a2e"  # card background
_SURFACE_700 = "#33333f"  # border (lightened slightly from the site's
                           # #212529 -- that's nearly invisible against
                           # #1a1a2e without the site's other layered
                           # surfaces around it to create contrast)
_SURFACE_400 = "#9ea5ac"  # muted text


def _render_email(heading: str, body_lines: list[str], cta_label: str, cta_url: str, footnote: str) -> str:
    """Shared branded shell for every transactional email. Table-based
    layout with inline styles throughout -- not for lack of taste, but
    because Outlook desktop (still Word's rendering engine) and a good
    chunk of webmail clients strip <style> blocks and ignore flexbox/grid
    entirely. Inline styles + tables is the actual state of the art for
    HTML email, unfortunately.

    body_lines are rendered as separate paragraphs, already-escaped by
    the caller only where they contain user-authored text (personal
    invite messages) -- everything else here is our own copy."""
    paragraphs = "".join(
        f'<p style="margin:0 0 16px;color:#d5d7db;font-size:15px;line-height:1.6;">{line}</p>'
        for line in body_lines
    )
    return f"""\
<!doctype html>
<html>
  <body style="margin:0;padding:0;background-color:{_SURFACE_900};">
    <div style="display:none;max-height:0;overflow:hidden;opacity:0;">{html_module.escape(footnote)}</div>
    <table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="background-color:{_SURFACE_900};padding:32px 16px;">
      <tr>
        <td align="center">
          <table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="max-width:480px;">
            <tr>
              <td align="center" style="padding-bottom:24px;">
                <span style="font-size:20px;font-weight:700;color:{_GOLD};letter-spacing:0.3px;">
                  &#127944; FantasyFootballCrew
                </span>
              </td>
            </tr>
            <tr>
              <td style="background-color:{_SURFACE_800};border:1px solid {_SURFACE_700};border-radius:16px;padding:32px;">
                <h1 style="margin:0 0 16px;color:#ffffff;font-size:20px;font-weight:700;font-family:Arial,Helvetica,sans-serif;">
                  {html_module.escape(heading)}
                </h1>
                {paragraphs}
                <table role="presentation" cellpadding="0" cellspacing="0" style="margin:8px 0 4px;">
                  <tr>
                    <td align="center" style="border-radius:10px;background-color:{_GOLD};">
                      <a href="{cta_url}" style="display:inline-block;padding:12px 28px;font-size:14px;font-weight:700;color:{_SURFACE_900};text-decoration:none;font-family:Arial,Helvetica,sans-serif;">
                        {html_module.escape(cta_label)}
                      </a>
                    </td>
                  </tr>
                </table>
              </td>
            </tr>
            <tr>
              <td align="center" style="padding-top:20px;">
                <p style="margin:0;color:{_SURFACE_400};font-size:12px;font-family:Arial,Helvetica,sans-serif;">
                  {html_module.escape(footnote)}
                </p>
              </td>
            </tr>
          </table>
        </td>
      </tr>
    </table>
  </body>
</html>"""


async def _log_send(db: AsyncSession, to_email: str, email_type: str, subject: str, status: str, error_detail: str | None = None) -> None:
    """Persist an EmailSendLog row and commit it on its own -- deliberately
    NOT part of whatever transaction the caller's request is mid-way
    through (a password-reset token, a league invite row, ...), so this
    is never rolled back by an unrelated failure later in that request,
    and a send outcome is recorded the instant it's known rather than
    whenever the caller happens to commit. See EmailSendLog's docstring
    for why this table exists at all (2026-09-08: weeks of silently
    failing sends, visible only in `railway logs`)."""
    db.add(EmailSendLog(to_email=to_email, email_type=email_type, subject=subject, status=status, error_detail=error_detail))
    await db.commit()


async def _send(
    to_email: str, subject: str, text_body: str, html_body: str, log_label: str, log_link: str,
    db: AsyncSession, email_type: str,
) -> None:
    """Shared send/stub/failure-swallow plumbing for all three email
    functions below -- extracted once the HTML template gave every send
    the exact same shape (was "not worth extracting for just two email
    types" back when there were only two; a third one plus this template
    tipped it)."""
    if not settings.RESEND_API_KEY:
        print(f"[email stub -- no RESEND_API_KEY configured] {log_label} for {to_email}: {log_link}", flush=True)
        await _log_send(db, to_email, email_type, subject, "stubbed")
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
                    "html": html_body,
                },
            )
            resp.raise_for_status()
            await _log_send(db, to_email, email_type, subject, "sent")
        except Exception as e:
            # Don't let an email-provider hiccup surface as a 500 to the
            # user on a request that already succeeded server-side (the
            # underlying token/invite is created either way) -- log it and
            # move on. Falling back to the stub log means the link is
            # still recoverable from `railway logs`.
            print(f"[email send FAILED, falling back to log] {to_email}: {log_link} -- {e}", flush=True)
            await _log_send(db, to_email, email_type, subject, "failed", error_detail=str(e)[:2000])


async def send_password_reset_email(to_email: str, reset_link: str, db: AsyncSession) -> None:
    subject = "Reset your FantasyFootballCrew password"
    text_body = (
        f"Someone (hopefully you) requested a password reset.\n\n"
        f"Reset your password: {reset_link}\n\n"
        f"This link expires in 1 hour. If you didn't request this, you can ignore this email."
    )
    html_body = _render_email(
        heading="Reset your password",
        body_lines=[
            "Someone (hopefully you) requested a password reset for your FantasyFootballCrew account.",
            "This link expires in <strong>1 hour</strong>. If you didn't request this, you can safely ignore this email.",
        ],
        cta_label="Reset Password",
        cta_url=reset_link,
        footnote="If the button doesn't work, copy and paste this link: " + reset_link,
    )
    await _send(to_email, subject, text_body, html_body, "Password reset", reset_link, db, "password_reset")


async def send_verification_email(to_email: str, verify_link: str, db: AsyncSession) -> None:
    """Sent once, right after registration -- track-only (Auth Security
    Hardening, Step 3): nothing in the app blocks on this being clicked,
    it just flips User.email_verified when it is."""
    subject = "Verify your email for FantasyFootballCrew"
    text_body = (
        f"Welcome to FantasyFootballCrew! Verify your email address:\n\n"
        f"{verify_link}\n\n"
        f"This link expires in 48 hours. Your account already works without "
        f"verifying -- this is just so we have a confirmed way to reach you."
    )
    html_body = _render_email(
        heading="Welcome to FantasyFootballCrew! \U0001f3c8",
        body_lines=[
            "Verify your email address to confirm we have a working way to reach you.",
            "This link expires in <strong>48 hours</strong>. Your account already works without verifying -- there's no rush.",
        ],
        cta_label="Verify Email",
        cta_url=verify_link,
        footnote="If the button doesn't work, copy and paste this link: " + verify_link,
    )
    await _send(to_email, subject, text_body, html_body, "Verification email", verify_link, db, "verification")


async def send_league_invite_email(
    to_email: str,
    league_name: str,
    inviter_name: str,
    personal_message: str | None,
    invite_link: str,
    db: AsyncSession,
) -> None:
    subject = f"{inviter_name} invited you to join {league_name} on FantasyFootballCrew"
    message_block = f"\n\n\"{personal_message}\"\n" if personal_message else ""
    text_body = (
        f"{inviter_name} invited you to join their fantasy football league, {league_name}.\n"
        f"{message_block}\n"
        f"Join here: {invite_link}\n\n"
        f"This link expires in 14 days."
    )
    body_lines = [
        f"<strong>{html_module.escape(inviter_name)}</strong> invited you to join their fantasy football league, "
        f"<strong>{html_module.escape(league_name)}</strong>.",
    ]
    if personal_message:
        # This is the one piece of user-authored text in any of these
        # templates (the inviter's own words) -- escape it explicitly
        # even though _render_email's other body_lines are our own copy
        # and don't need it.
        body_lines.append(
            f'<span style="display:block;margin-top:-4px;padding:12px 16px;background-color:{_SURFACE_900};'
            f'border-left:3px solid {_GOLD};border-radius:4px;font-style:italic;color:{_SURFACE_400};">'
            f"&ldquo;{html_module.escape(personal_message)}&rdquo;</span>"
        )
    body_lines.append("This invite link expires in <strong>14 days</strong>.")
    html_body = _render_email(
        heading="You're invited to a league! \U0001f3c6",
        body_lines=body_lines,
        cta_label="Join League",
        cta_url=invite_link,
        footnote="If the button doesn't work, copy and paste this link: " + invite_link,
    )
    await _send(to_email, subject, text_body, html_body, f"League invite for '{league_name}'", invite_link, db, "league_invite")
