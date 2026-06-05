"""Exercise name -> YouTube search URL lookup.

Used to make exercise names clickable in the email. Falls back to a generic
YouTube search so even LLM-invented exercise names get something useful.
"""

import urllib.parse

# Common exercises -> YouTube search query tuned for form/tutorial results.
_QUERIES = {
    # Shoulder rehab
    "band external rotation (elbow at side)": "band external rotation shoulder rehab",
    "band external rotation": "band external rotation shoulder rehab",
    "trx scapular retraction": "trx Y T W scapular exercise",
    "band pull-apart": "band pull apart shoulder exercise",
    "face pull (band)": "face pull band technique",
    "face pull": "face pull cable band technique",
    "trx y/t/w": "trx Y T W scapular exercise",
    "prone y/t": "prone Y T shoulder exercise",
    "serratus anterior": "serratus anterior exercise",
    "scapular push-up": "scapular push up exercise",

    # Lower body
    "back squat": "back squat form tutorial",
    "front squat": "front squat form tutorial",
    "goblet squat": "goblet squat form",
    "box jump": "box jump technique form",
    "kettlebell swing": "kettlebell swing form hip hinge",
    "kettlebell swing (70lb)": "kettlebell swing form hip hinge",
    "bulgarian split squat": "bulgarian split squat form tutorial",
    "romanian deadlift": "romanian deadlift form tutorial",
    "conventional deadlift": "conventional deadlift form tutorial",
    "deadlift": "deadlift form tutorial",
    "single-leg rdl": "single leg romanian deadlift form",
    "single-leg romanian deadlift": "single leg romanian deadlift form",
    "step-up": "weighted step up exercise form",
    "lateral lunge": "lateral lunge exercise form",
    "reverse lunge": "reverse lunge form tutorial",
    "glute bridge": "glute bridge form technique",
    "single-leg glute bridge": "single leg glute bridge exercise",

    # Upper body pull
    "chin-up (controlled, neutral or supinated)": "chin up proper form tutorial",
    "chin-up": "chin up proper form tutorial",
    "pull-up": "pull up proper form tutorial",
    "trx inverted row": "TRX inverted row form",
    "trx row": "TRX row exercise form",
    "single-arm kb row": "single arm kettlebell row form",
    "single-arm dumbbell row": "single arm dumbbell row form",
    "barbell row": "barbell row form tutorial",
    "landmine press (light)": "landmine press shoulder tutorial",
    "landmine press": "landmine press shoulder tutorial",

    # Core / finishers
    "suitcase carry": "suitcase carry exercise anti lateral flexion",
    "pallof press (band)": "pallof press anti rotation core",
    "pallof press": "pallof press anti rotation core",
    "bosu single-leg balance reach": "BOSU single leg balance exercise",
    "dead bug": "dead bug exercise core tutorial",
    "plank": "plank exercise proper form",
    "side plank": "side plank exercise form",
    "ab wheel rollout": "ab wheel rollout technique",
}


def get_url(exercise_name: str) -> str:
    """Return a YouTube URL for an exercise. Always returns something."""
    key = exercise_name.lower().strip()
    query = _QUERIES.get(key)

    if not query:
        # Fuzzy: check if any known key is a substring of the exercise name.
        for k, q in _QUERIES.items():
            if k in key or key in k:
                query = q
                break

    if not query:
        query = f"{exercise_name} exercise form tutorial"

    encoded = urllib.parse.quote_plus(query)
    return f"https://www.youtube.com/results?search_query={encoded}"
