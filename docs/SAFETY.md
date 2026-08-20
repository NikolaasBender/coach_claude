# Shoulder Safety Documentation

## Medical Context

**Athlete**: Left shoulder, anterior labrum repair (~5 years ago), 3 recurrent anterior dislocations from cycling crashes.

**Current Status**: Light overhead pressing cleared and progressing gradually. The at-risk position is **abduction + external rotation** (the "cocking"/throwing position) and end-range anterior translation.

**Training Role**: Cyclist who lifts for shoulder health and on-bike power. Advanced lifter, ~55 min sessions.

## Safety Philosophy

> **The model proposes; the code disposes.**

No LLM output reaches the athlete without passing the hard guardrail in `exclusions.py`. The validation runs on *exercise name* via regex substring match — false positives (safe exercise blocked) are acceptable; false negatives (dangerous exercise passes) are not.

## Exclusion Rules (`src/exclusions.py`)

Each rule: `(human_reason, [regex_patterns])`. Patterns matched case-insensitively against exercise name.

| # | Category | Patterns | Reason |
|---|----------|----------|--------|
| 1 | **Flys / loaded horizontal abduction** | `\bfly`, `\bflye`, `lateral raise`, `reverse pec`, `pec deck`, `horizontal abduction` | Direct anterior strain on repaired labrum |
| 2 | **Behind-the-neck** | `behind[\s-]*the[\s-]*neck`, `\bbtn\b` | Forces external rotation at abduction (cocking position) |
| 3 | **Dips** | `\bdip\b`, `\bdips\b` | Heavy anterior loading at end range |
| 4 | **Upright rows** | `upright row` | Impingement risk, anterior translation |
| 5 | **Kipping / ballistic pull-ups** | `kipping`, `butterfly pull`, `ballistic pull` | Uncontrolled end-range ER strain |
| 6 | **Wide-grip / deep bench** | `wide[\s-]*grip bench`, `wide[\s-]*grip press` | Anterior translation at end range |
| 7 | **Explicit cocking cues** | `cocking position`, `abduction.*external rotation`, `external rotation.*abduction` | Abduction + ER under load |

## Validation Flow

```
LLM proposes workout JSON
        │
        ▼
exclusions.validate_workout(workout)
        │
        ├── PASS ──▶ Keep proposal
        │
        └── FAIL ──▶ One corrective retry (LLM asked to swap bad exercises)
                │
                ├── PASS ──▶ Keep corrected proposal
                │
                └── FAIL ──▶ Fallback to templates.generate() (pre-vetted, always safe)
```

**Key invariant**: `templates.py` exercises are hand-picked and pre-vetted against the same exclusion list. The fallback path is guaranteed safe.

## Prompt Constraints (`PROMPT_CONSTRAINTS`)

Injected into every LLM prompt to reduce rejections:

```
HARD SHOULDER RULES (left shoulder, anterior labrum repair, recurrent dislocations):
- NO flys, lateral raises, reverse-pec, or any loaded horizontal abduction.
- NO behind-the-neck pressing or pulldowns.
- NO dips. NO upright rows. NO kipping/ballistic pull-ups.
- NO wide-grip or deep end-range barbell bench (limit ROM, neutral/close grip only).
- AVOID loading the abduction + external-rotation ("cocking") position.
- Overhead pressing is ALLOWED but must start light (band/TRX/landmine/KB) and progress slowly.
- ALWAYS open with a shoulder rehab block: band external rotation, scapular control,
  controlled TRX/row patterning.
```

## Allowed / Encouraged Movements

| Category | Examples | Notes |
|----------|----------|-------|
| **Shoulder rehab** | Band external rotation (elbow at side), band pull-apart, face pull, TRX Y/T/W, scapular push-up, prone Y/T, serratus work | **Mandatory every session** |
| **Overhead press** | Landmine press, half-kneeling KB press (light), neutral-grip DB floor press | Start light, progress slowly, neutral/close grip |
| **Horizontal push** | Floor press, push-up variations | Limit ROM, avoid end-range abduction |
| **Vertical pull** | Chin-up (controlled, neutral/supinated), pull-up (controlled) | No kipping, no wide grip |
| **Horizontal pull** | TRX row, single-arm KB/DB row, barbell row, chest-supported row | Scapular control emphasis |
| **Lower body** | Squat variations, deadlift variations, KB swing, box jump, lunge/step-up, glute bridge | Posterior chain priority |
| **Core** | Dead bug, plank/RKC/side plank, leg raises, reverse crunch, Pallof press, suitcase carry, farmer carry | **Lower-core every session** |
| **Hip bridge** | Single-leg glute bridge, weighted glute bridge (floor), bodyweight glute bridge | **Rotating mandatory every session** |

## Equipment Constraints (`src/profile.py`)

**No bench available** — this eliminates:
- Bench press variations
- Hip thrusts (use floor-based glute bridge instead)
- Incline/decline pressing

Available: barbell, kettlebells (45lb, 70lb), dumbbells, BOSU, stability ball, pull-up bar, TRX, plyo box, bands.

## Mandatory Session Structure

Every workout (LLM or template) **guarantees**:

1. **Shoulder rehab block** (band ER, scapular control, TRX/row patterning)
2. **Rotating hip bridge variant**:
   - Session 0: Single-leg glute bridge
   - Session 1: Weighted glute bridge (barbell/KB on hips, floor)
   - Session 2: Bodyweight glute bridge (paused)
   - Session 3: repeats cycle...
3. **Dedicated lower-core movement** (leg raises, dead bugs, reverse crunch, etc.)

## Deload Protocol

- Every 5th session (configurable via `DELOAD_EVERY`)
- Reduces volume/intensity while maintaining movement patterns
- Still includes mandatory rehab + hip bridge + lower-core

## PT Review Checklist

**Before trusting this system with an unstable joint, have your PT verify:**

- [ ] Exclusion list covers your specific contraindications
- [ ] Allowed overhead progression matches your clearance
- [ ] Hip bridge rotation appropriate for your glute/hamstring capacity
- [ ] Lower-core selection doesn't irritate your lumbar spine
- [ ] Session volume (~55 min) matches your recovery capacity
- [ ] Email feedback loop works for you to flag issues quickly

## Emergency Stop

If any movement **pinches, clicks, or feels unstable** — stop immediately. Log feedback via web app (rating 1, notes "shoulder pinch on X") so next session adapts.

## Modifying Exclusions

**Only with PT approval.** Edit `src/exclusions.py`:

```python
EXCLUSIONS = [
    ("your reason", [r"pattern1", r"pattern2"]),
    # ...
]
```

After editing:
1. Rebuild: `docker compose up -d --build`
2. Test: `docker compose run --rm coach python -m src.main monday`
3. Verify rejected exercises in logs

## Validation Testing

To verify the guardrail catches a specific exercise:

```bash
docker compose run --rm coach python -c "
from src.exclusions import check
print(check('dumbbell fly'))          # Should catch
print(check('behind the neck press')) # Should catch
print(check('weighted glute bridge')) # Should be empty (safe)
"
```

Expected output:
```
['outward/lateral fly and loaded horizontal abduction — direct anterior strain']
['behind-the-neck press/pulldown — forces ER at abduction (cocking position)']
[]
```