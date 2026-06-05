"""Athlete profile, equipment, and session targets.

Single source of truth for who we're programming for. Edit here to retune.
"""

ATHLETE = {
    "discipline": "gravel cycling + downhill MTB racing",
    "training_role": "cyclist who lifts for shoulder health and on-bike power",
    "experience": "advanced lifter",
    "session_minutes": 55,  # hard ceiling ~60
}

# Left shoulder: anterior labrum repair ~5 years ago, 3 major dislocations since
# (crashes). Light overhead OK and building toward more. The at-risk position is
# abduction + external rotation (the "cocking"/throwing position).
SHOULDER = {
    "side": "left",
    "history": "anterior labrum repair 5y ago, 3 recurrent anterior dislocations from crashes",
    "status": "light overhead cleared, progressing load gradually",
    "always_include_rehab": True,
}

EQUIPMENT_NOTES = "No bench available — avoid hip thrusts and bench press variations. Use floor-based alternatives (glute bridge, floor press if needed)."

EQUIPMENT = [
    "olympic barbell + full plate set",
    "45lb kettlebell",
    "70lb kettlebell",
    "light dumbbells / fixed free weights (~10lb and up)",
    "BOSU ball",
    "stability / yoga ball",
    "pull-up bar",
    "TRX straps",
    "plyo / jump box",
    "elastic resistance bands",
]

# Day -> primary focus. Both days always open with the shoulder rehab block.
SCHEDULE = {
    "monday": "lower body power + posterior chain (core woven in)",
    "friday": "upper body pulling + scapular strength + light overhead progression",
}

# Cycling-relevant finisher pool the generator/LLM can draw from.
FINISHER_THEMES = [
    "hip hinge",
    "single-leg stability",
    "loaded carry",
    "anti-rotation core",
]
