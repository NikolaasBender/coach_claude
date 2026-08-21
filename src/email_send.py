"""Render a workout session to HTML and send it via Gmail SMTP.

A session now carries one proposal per model (Nemotron, DeepSeek). The email
renders them side by side so the athlete can compare and pick, with a link to
the feedback web app to log which one they preferred and how it felt.

Uses a Gmail App Password (16 chars), NOT the account password — Google blocks
basic auth otherwise. Port 587 + STARTTLS.
"""

import html
import os
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

from .exercise_links import get_url


def _variants(session):
    """Normalize to a list of (model_label, workout). Tolerates a bare workout."""
    if session.get("variants"):
        return [(v.get("model", "Model"), v.get("workout", {})) for v in session["variants"]]
    return [(session.get("model", ""), session)]


def _table(workout: dict) -> str:
    blocks_html = ""
    for block in workout.get("blocks", []):
        rows = ""
        for ex in block.get("exercises", []):
            name = ex.get("name", "")
            url = get_url(name)
            linked_name = f'<a href="{url}" style="color:#1a5;text-decoration:none;">{name} ▶</a>'
            rows += f"""
              <tr>
                <td style="padding:6px 10px;border-bottom:1px solid #eee;">{linked_name}</td>
                <td style="padding:6px 10px;border-bottom:1px solid #eee;text-align:center;">{ex.get('sets','')}</td>
                <td style="padding:6px 10px;border-bottom:1px solid #eee;text-align:center;">{ex.get('reps','')}</td>
                <td style="padding:6px 10px;border-bottom:1px solid #eee;">{ex.get('load','')}</td>
                <td style="padding:6px 10px;border-bottom:1px solid #eee;text-align:center;">{ex.get('rpe','')}</td>
                <td style="padding:6px 10px;border-bottom:1px solid #eee;color:#555;font-size:13px;">{ex.get('notes','')}</td>
              </tr>"""
        blocks_html += f"""
          <h4 style="margin:18px 0 6px;color:#1a5">{block.get('name','')}</h4>
          <table style="border-collapse:collapse;width:100%;font-size:14px;">
            <tr style="background:#f4f4f4;text-align:left;">
              <th style="padding:6px 10px;">Exercise</th>
              <th style="padding:6px 10px;">Sets</th>
              <th style="padding:6px 10px;">Reps</th>
              <th style="padding:6px 10px;">Load</th>
              <th style="padding:6px 10px;">RPE</th>
              <th style="padding:6px 10px;">Notes</th>
            </tr>
            {rows}
          </table>"""
    return blocks_html


def _context_box(title: str, text: str) -> str:
    """Monospace context block (recovery snapshot, pattern analysis)."""
    escaped = html.escape(text).replace("\n", "<br>")
    return f"""
      <div style="margin-bottom:18px;padding:14px 16px;background:#f5f5f5;border-left:4px solid #555;border-radius:4px;font-family:monospace;font-size:13px;line-height:1.5;white-space:pre-wrap;">
        <strong>{title}</strong><br>
        {escaped}
      </div>"""


# Effort colors for the weekly volume graph (email-safe hex, rendered order).
_EFFORT_COLORS = (
    ("easy", "#7fb069"),
    ("moderate", "#f2c14e"),
    ("hard", "#f4845f"),
    ("very hard", "#c9484f"),
)


def _pattern_graph(weeks: list, trend: str) -> str:
    """Email-safe 3-week volume graph plus the trend lines.

    Table-based stacked bars with inline styles only — no JS, no external CSS,
    no images — so it survives Gmail. Bar length ∝ weekly hours (scaled to the
    biggest week); segments colored by effort-hours share.
    """
    max_hours = max((w.get("hours", 0) for w in weeks), default=0)
    if max_hours <= 0:
        return ""

    bar_rows = ""
    for w in weeks:
        hours = w.get("hours", 0)
        fill_pct = max(hours / max_hours * 100, 2)
        segs = ""
        for effort, color in _EFFORT_COLORS:
            eh = (w.get("effort_hours") or {}).get(effort, 0)
            if eh <= 0 or hours <= 0:
                continue
            segs += (f'<td width="{eh / hours * 100:.1f}%" bgcolor="{color}" '
                     f'style="line-height:14px;font-size:2px;">&nbsp;</td>')
        label = html.escape(w.get("label") or w.get("range") or "?")
        stats = html.escape(
            f"{hours:.1f}h · {w.get('count', 0)} activities · "
            f"{w.get('km', 0):.0f}km · {w.get('elev', 0):.0f}m{w.get('delta', '')}"
        )
        bar_rows += f"""
          <tr>
            <td style="font-family:monospace;font-size:12px;padding:6px 8px 0 0;white-space:nowrap;vertical-align:middle;">{label}</td>
            <td style="width:100%;padding:6px 0 0;vertical-align:middle;">
              <table cellpadding="0" cellspacing="0" border="0" width="100%"><tr>
                <td width="{fill_pct:.1f}%">
                  <table cellpadding="0" cellspacing="0" border="0" width="100%"><tr>{segs}</tr></table>
                </td>
                <td bgcolor="#e9e9e9" style="line-height:14px;font-size:2px;">&nbsp;</td>
              </tr></table>
            </td>
          </tr>
          <tr>
            <td></td>
            <td style="font-family:monospace;font-size:11px;color:#777;padding:1px 0 2px;">{stats}</td>
          </tr>"""

    legend = " &nbsp;".join(
        f'<span style="color:{color};">■</span> {effort}' for effort, color in _EFFORT_COLORS
    )
    trend_html = ""
    if trend:
        trend_html = "<br>" + html.escape(trend).replace("\n", "<br>")
    return f"""
      <div style="margin-bottom:18px;padding:14px 16px;background:#f5f5f5;border-left:4px solid #555;border-radius:4px;font-family:monospace;font-size:13px;line-height:1.5;">
        <strong>3-WEEK TRAINING PATTERN</strong>
        <table cellpadding="0" cellspacing="0" border="0" width="100%" style="margin-top:6px;">{bar_rows}
        </table>
        <div style="font-size:11px;color:#555;margin-top:6px;">{legend}</div>
        {trend_html}
      </div>"""


def render_html(session: dict) -> str:
    day = session.get("day", "").title()
    deload = " · DELOAD WEEK" if session.get("deload") else ""
    variants = _variants(session)
    web_url = os.environ.get("WEB_URL", "").rstrip("/")
    pattern_analysis = session.get("pattern_analysis", "").strip()
    recovery = session.get("recovery", "").strip()
    trend = session.get("trend_analysis", "").strip()
    pattern_weeks = session.get("pattern_weeks") or []
    pattern_trend = session.get("pattern_trend", "").strip()

    sections = ""
    for label, workout in variants:
        focus = workout.get("focus", "")
        notes = workout.get("coach_notes", "")
        source = workout.get("source", "")
        header = label or source or "Workout"
        sections += f"""
          <div style="margin-top:26px;padding-top:8px;border-top:3px solid #1a5;">
            <h3 style="margin:6px 0 0;">{header}</h3>
            <p style="margin:2px 0 0;color:#666;">{focus}</p>
            {_table(workout)}
            <div style="margin-top:14px;padding:10px 12px;background:#f0f7f0;border-left:4px solid #1a5;border-radius:4px;">
              <strong>Coach notes:</strong> {notes}
            </div>
          </div>"""

    compare_hint = (
        "<p style='color:#666;'>Two coaches designed today's session independently — "
        "pick the one you like, or mix and match.</p>"
        if len(variants) > 1 else ""
    )

    feedback_cta = ""
    if web_url:
        feedback_cta = f"""
          <div style="margin-top:26px;text-align:center;">
            <a href="{web_url}" style="display:inline-block;padding:12px 22px;background:#1a5;color:#fff;
               text-decoration:none;border-radius:6px;font-weight:600;">
              Log how it went ▸
            </a>
            <p style="margin-top:8px;color:#999;font-size:12px;">
              Rate the session, say which coach you preferred, leave notes — it feeds back into next time.
            </p>
          </div>"""

    trend_section = ""
    if trend:
        escaped_trend = html.escape(trend).replace("\n", "<br>")
        trend_section = f"""
      <div style="margin-bottom:18px;padding:14px 16px;background:#f0f7f0;border-left:4px solid #1a5;border-radius:4px;font-size:14px;line-height:1.55;">
        <strong>COACH'S TREND READ</strong><br>
        {escaped_trend}
      </div>"""

    recovery_section = _context_box("RECOVERY (GARMIN)", recovery) if recovery else ""
    # Graph when structured week data exists; text box for legacy sessions.
    pattern_section = _pattern_graph(pattern_weeks, pattern_trend)
    if not pattern_section and pattern_analysis:
        pattern_section = _context_box("3-WEEK PATTERN ANALYSIS", pattern_analysis)

    return f"""<html><body style="font-family:-apple-system,Segoe UI,Arial,sans-serif;max-width:760px;margin:0 auto;color:#222;">
      <h2 style="margin-bottom:0;">{day} Strength{deload}</h2>
      {trend_section}{recovery_section}{pattern_section}
      {compare_hint}
      {sections}
      {feedback_cta}
      <p style="margin-top:22px;color:#999;font-size:12px;">
        Generated by coach_claude. Stop any shoulder movement that pinches.
      </p>
    </body></html>"""


def send(session: dict):
    user = os.environ["GMAIL_ADDRESS"]
    app_pw = os.environ["GMAIL_APP_PASSWORD"]
    to = os.environ.get("EMAIL_TO", user)

    day = session.get("day", "").title()
    deload = " (deload)" if session.get("deload") else ""

    msg = MIMEMultipart("alternative")
    msg["Subject"] = f"{day} Strength{deload} — coach_claude"
    msg["From"] = user
    msg["To"] = to
    msg.attach(MIMEText(render_html(session), "html"))

    with smtplib.SMTP("smtp.gmail.com", 587) as server:
        server.starttls()
        server.login(user, app_pw)
        server.sendmail(user, [to], msg.as_string())
