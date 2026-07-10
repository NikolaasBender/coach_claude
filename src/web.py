"""Feedback web app (Flask).

A small always-on service on the home server. Shows recent sessions and lets the
athlete log, per session: a 1-5 rating, which model's version they preferred, and
free-text notes. Everything lands in feedback.json on the shared /data volume,
which the generator reads back into the prompt (see src/feedback.py).

Run: python -m src.web   (or `docker compose run --service-ports web`)
"""

import html
import os

from flask import Flask, redirect, request, url_for

from . import feedback, history

app = Flask(__name__)

STAR = "★"
STAR_EMPTY = "☆"


def _esc(s):
    return html.escape(str(s or ""))


def _session_models(entry):
    if entry.get("variants"):
        return [v.get("model", "Model") for v in entry["variants"]]
    return [entry.get("model") or "Workout"]


def _session_focus(entry):
    if entry.get("variants"):
        w = entry["variants"][0].get("workout", {})
    else:
        w = entry
    return w.get("focus", "")


def _main_exercises(workout):
    for block in workout.get("blocks", []):
        if block.get("name", "").lower() == "main":
            return [ex.get("name", "") for ex in block.get("exercises", [])]
    return []


def _feedback_index():
    """Map session_date -> list of feedback entries for that date."""
    idx = {}
    for e in feedback.load():
        idx.setdefault(e.get("session_date", ""), []).append(e)
    return idx


PAGE = """<!doctype html>
<html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>coach_claude — feedback</title>
<style>
  body {{ font-family:-apple-system,Segoe UI,Arial,sans-serif; max-width:760px; margin:0 auto;
         padding:16px; color:#1c1c1c; background:#fafafa; }}
  h1 {{ color:#1a5; }}
  .card {{ background:#fff; border:1px solid #e6e6e6; border-radius:10px; padding:16px 18px;
          margin:16px 0; box-shadow:0 1px 3px rgba(0,0,0,.05); }}
  .muted {{ color:#777; font-size:13px; }}
  .models {{ font-size:13px; color:#444; margin:6px 0; }}
  .ex {{ font-size:13px; color:#555; }}
  label {{ display:block; margin:10px 0 4px; font-weight:600; font-size:14px; }}
  input[type=text], textarea, select {{ width:100%; padding:8px; border:1px solid #ccc;
          border-radius:6px; font-size:14px; box-sizing:border-box; }}
  .row {{ display:flex; gap:14px; flex-wrap:wrap; align-items:center; }}
  .row > div {{ flex:1; min-width:140px; }}
  button {{ margin-top:12px; padding:10px 20px; background:#1a5; color:#fff; border:0;
           border-radius:6px; font-weight:600; font-size:14px; cursor:pointer; }}
  .logged {{ background:#f0f7f0; border-left:4px solid #1a5; padding:8px 10px; border-radius:4px;
            margin:8px 0; font-size:13px; }}
  .stars {{ color:#e8a500; }}
</style></head><body>
<h1>coach_claude</h1>
<p class="muted">Log how each session went. It feeds straight back into how the next one is designed.</p>
{cards}
</body></html>"""


def _rating_stars(n):
    try:
        n = int(n)
    except (TypeError, ValueError):
        return ""
    return STAR * n + STAR_EMPTY * (5 - n)


def _render_card(entry, fb_for_session):
    date = entry.get("date", "?")
    day = (entry.get("day") or "").title()
    deload = " · deload" if entry.get("deload") else ""
    models = _session_models(entry)
    focus = _session_focus(entry)

    ex_html = ""
    if entry.get("variants"):
        for v in entry["variants"]:
            names = _main_exercises(v.get("workout", {}))
            ex_html += f'<div class="ex"><b>{_esc(v.get("model",""))}:</b> {_esc(", ".join(names))}</div>'

    logged_html = ""
    for fb in fb_for_session:
        stars = f'<span class="stars">{_rating_stars(fb.get("rating"))}</span>'
        pref = f' · preferred <b>{_esc(fb.get("preferred_model"))}</b>' if fb.get("preferred_model") else ""
        note = f' — {_esc(fb.get("notes"))}' if fb.get("notes") else ""
        logged_html += f'<div class="logged">{stars}{pref}{note}</div>'

    model_options = "".join(
        f'<option value="{_esc(m)}">{_esc(m)}</option>' for m in models
    )

    return f"""
    <div class="card">
      <div class="row">
        <div><strong>{_esc(day)} — {_esc(date)}{deload}</strong><br>
        <span class="muted">{_esc(focus)}</span></div>
      </div>
      <div class="models">Designed by: {_esc(", ".join(models))}</div>
      {ex_html}
      {logged_html}
      <form method="post" action="/feedback">
        <input type="hidden" name="session_date" value="{_esc(date)}">
        <input type="hidden" name="day" value="{_esc(entry.get('day',''))}">
        <div class="row">
          <div>
            <label>Rating</label>
            <select name="rating">
              <option value="">—</option>
              <option value="5">5 — great</option>
              <option value="4">4 — good</option>
              <option value="3">3 — ok</option>
              <option value="2">2 — rough</option>
              <option value="1">1 — bad</option>
            </select>
          </div>
          <div>
            <label>Preferred coach</label>
            <select name="preferred_model">
              <option value="">—</option>
              {model_options}
            </select>
          </div>
        </div>
        <label>Notes (how it felt, shoulder, what to change)</label>
        <textarea name="notes" rows="2" placeholder="e.g. swings felt heavy, shoulder fine, want more single-leg"></textarea>
        <button type="submit">Save feedback</button>
      </form>
    </div>"""


@app.route("/")
def index():
    fb_idx = _feedback_index()
    entries = list(reversed(history.load()))[:12]
    if not entries:
        cards = '<div class="card">No sessions recorded yet. Check back after the next workout email.</div>'
    else:
        cards = "".join(_render_card(e, fb_idx.get(e.get("date", ""), [])) for e in entries)
    return PAGE.format(cards=cards)


@app.route("/feedback", methods=["POST"])
def submit_feedback():
    entry = {
        "session_date": request.form.get("session_date", "").strip(),
        "day": request.form.get("day", "").strip(),
        "preferred_model": request.form.get("preferred_model", "").strip(),
        "notes": request.form.get("notes", "").strip(),
    }
    rating = request.form.get("rating", "").strip()
    if rating.isdigit():
        entry["rating"] = int(rating)
    # Ignore empty submissions (nothing meaningful entered).
    if entry["preferred_model"] or entry["notes"] or entry.get("rating"):
        feedback.append(entry)
    return redirect(url_for("index"))


@app.route("/healthz")
def healthz():
    return {"ok": True}


if __name__ == "__main__":
    port = int(os.environ.get("WEB_PORT", "8080"))
    app.run(host="0.0.0.0", port=port)
