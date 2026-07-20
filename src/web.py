"""Feedback web app (Flask).

A small always-on service on the home server. Shows recent sessions and lets the
athlete log, per session: a 1-5 rating, which model's version they preferred, and
free-text notes. Everything lands in feedback.json on the shared /data volume,
which the generator reads back into the prompt (see src/feedback.py).

Run: python -m src.web   (or `docker compose run --service-ports web`)
"""

import html
import os
import threading
import traceback

from flask import Flask, redirect, request, url_for

from . import feedback, history

app = Flask(__name__)

# Guards against double-submits / overlapping generations (LLM calls take a
# while and this is a single-athlete home app — one generation at a time).
_generate_lock = threading.Lock()
_generating = False
_generate_error = None

STAR = "★"
STAR_EMPTY = "☆"


def _esc(s):
    return html.escape(str(s or ""))


def _session_models(entry):
    if entry.get("variants"):
        return [v.get("model", "Model") for v in entry["variants"]]
    # Legacy flat entries (pre-multi-model) carry the origin as "source"
    # ("llm"/"template") on the entry itself rather than a "model" field.
    return [entry.get("model") or entry.get("source") or "Workout"]


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


def _session_workouts(entry):
    """Return [(model_label, workout_dict), ...] for an entry, tolerating both
    the multi-model "variants" shape and legacy flat single-workout entries."""
    if entry.get("variants"):
        return [(v.get("model", "Model"), v.get("workout", {})) for v in entry["variants"]]
    return [(entry.get("model") or entry.get("source") or "Workout", entry)]


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
  h2 {{ font-size:16px; margin:24px 0 4px; }}
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
  button.secondary {{ background:#444; }}
  button:disabled {{ background:#aaa; cursor:not-allowed; }}
  .logged {{ background:#f0f7f0; border-left:4px solid #1a5; padding:8px 10px; border-radius:4px;
            margin:8px 0; font-size:13px; }}
  .stars {{ color:#e8a500; }}
  .generate-bar {{ display:flex; justify-content:space-between; align-items:center; gap:10px;
                   margin:12px 0 20px; }}
  .variant {{ border-top:1px solid #eee; margin-top:10px; padding-top:10px; }}
  .variant:first-child {{ border-top:0; margin-top:0; padding-top:0; }}
  .block-name {{ font-weight:600; font-size:13px; color:#1a5; margin:10px 0 4px; }}
  table {{ width:100%; border-collapse:collapse; font-size:13px; }}
  td {{ padding:3px 6px 3px 0; vertical-align:top; }}
  td.rpe {{ color:#888; white-space:nowrap; }}
  .error {{ background:#fdecec; border-left:4px solid #c33; color:#900; padding:8px 10px;
           border-radius:4px; margin:8px 0; font-size:13px; }}
</style></head><body>
<h1>coach_claude</h1>
<p class="muted">Log how each session went. It feeds straight back into how the next one is designed.</p>
<div class="generate-bar">
  <form method="post" action="/generate" style="margin:0;">
    <button type="submit" class="secondary"{gen_disabled}>{gen_label}</button>
  </form>
</div>
{gen_error}
{latest}
<h2>History</h2>
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
    for model_label, workout in _session_workouts(entry):
        names = _main_exercises(workout)
        if names:
            ex_html += f'<div class="ex"><b>{_esc(model_label)}:</b> {_esc(", ".join(names))}</div>'

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


def _render_exercise_rows(exercises):
    rows = ""
    for ex in exercises:
        sets, reps, load = ex.get("sets"), ex.get("reps", ""), ex.get("load", "")
        set_rep = f"{sets}x{reps}" if sets else reps
        bits = " / ".join(x for x in [set_rep, load] if x)
        rpe = f'RPE {ex.get("rpe")}' if ex.get("rpe") is not None else ""
        notes = ex.get("notes", "")
        notes_html = f'<br><span class="muted">{_esc(notes)}</span>' if notes else ""
        rows += (
            f'<tr><td><b>{_esc(ex.get("name",""))}</b>{notes_html}</td>'
            f'<td>{_esc(bits)}</td><td class="rpe">{_esc(rpe)}</td></tr>'
        )
    return rows


def _render_workout_detail(model_label, workout):
    blocks_html = ""
    for block in workout.get("blocks", []):
        exs = block.get("exercises", [])
        if not exs:
            continue
        blocks_html += (
            f'<div class="block-name">{_esc(block.get("name",""))}</div>'
            f'<table>{_render_exercise_rows(exs)}</table>'
        )
    notes = workout.get("coach_notes", "")
    notes_html = f'<p class="muted">{_esc(notes)}</p>' if notes else ""
    return f'<div class="variant"><div class="models"><b>{_esc(model_label)}</b></div>{blocks_html}{notes_html}</div>'


def _render_latest(entry):
    date = entry.get("date", "?")
    day = (entry.get("day") or "").title()
    deload = " · deload" if entry.get("deload") else ""
    focus = _session_focus(entry)
    variants_html = "".join(
        _render_workout_detail(model_label, workout)
        for model_label, workout in _session_workouts(entry)
    )
    return f"""
    <div class="card">
      <strong>Latest — {_esc(day)} {_esc(date)}{deload}</strong><br>
      <span class="muted">{_esc(focus)}</span>
      {variants_html}
    </div>"""


@app.route("/")
def index():
    fb_idx = _feedback_index()
    all_entries = history.load()
    entries = list(reversed(all_entries))[:12]
    if not entries:
        latest = ""
        cards = '<div class="card">No sessions recorded yet. Check back after the next workout email.</div>'
    else:
        latest = _render_latest(entries[0])
        cards = "".join(_render_card(e, fb_idx.get(e.get("date", ""), [])) for e in entries)

    gen_disabled = " disabled" if _generating else ""
    gen_label = "Generating…" if _generating else "Generate new workout"
    gen_error = f'<div class="error">Generation failed: {_esc(_generate_error)}</div>' if _generate_error else ""

    return PAGE.format(
        cards=cards, latest=latest, gen_disabled=gen_disabled,
        gen_label=gen_label, gen_error=gen_error,
    )


def _run_generate():
    global _generating, _generate_error
    from . import main as coach_main
    try:
        coach_main.main()
        _generate_error = None
    except Exception as e:
        traceback.print_exc()
        _generate_error = str(e)
    finally:
        _generating = False


@app.route("/generate", methods=["POST"])
def generate():
    global _generating
    with _generate_lock:
        if not _generating:
            _generating = True
            threading.Thread(target=_run_generate, daemon=True).start()
    return redirect(url_for("index"))


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
    app.run(host="0.0.0.0", port=port, threaded=True)
