#!/usr/bin/env python3
"""
Kev's Daily Health Brief
Runs via GitHub Actions at 8:30am Sydney every morning.

Secrets required in GitHub:
  GARMIN_EMAIL
  GARMIN_PASSWORD
  NOTION_TOKEN
  NOTION_SLEEP_DB_ID   = ae902ae2134983eaa85a81aa43755e36
  ANTHROPIC_API_KEY
"""

import os, requests, sys
from datetime import date, datetime, timedelta

try:
    from garminconnect import Garmin
except ImportError:
    print("Missing: pip install garminconnect")
    sys.exit(1)

GARMIN_EMAIL      = os.environ["GARMIN_EMAIL"]
GARMIN_PASSWORD   = os.environ["GARMIN_PASSWORD"]
NOTION_TOKEN      = os.environ["NOTION_TOKEN"]
NOTION_DB_ID      = os.environ["NOTION_SLEEP_DB_ID"]
ANTHROPIC_API_KEY = os.environ["ANTHROPIC_API_KEY"]

SCHEDULE = {
    "Monday":    "Upper body — push/pull hybrid. DB Bench, SA Cable Row, DB Shoulder Press, SA Lat Pulldown, Tricep Extensions, Hammer Curls. Face pulls warm-up mandatory.",
    "Tuesday":   "Lower body — posterior chain. BB RDL (3-second eccentric, stop before lumbar rounds), Lying Ham Curl, Leg Extensions, Bulgarian Split Squat, SL Leg Press, Calf Raises. McGill Big 3 + hip bridges + cat-cow MANDATORY before any loading.",
    "Wednesday": "Full rest day. Light walking only.",
    "Thursday":  "HIGH DEMAND DAY — Heavy upper push AM + 6x800m intervals PM. Bench capped RPE 8. Full meal between sessions. Face pulls warm-up.",
    "Friday":    "Upper body — pull focus. Lat Pulldown, SA Bench Pulldown, Supinated Cable Row, DB Curls, Preacher Hammer Curl. Face pulls warm-up.",
    "Saturday":  "Lower body — squat focus. Squat (just below parallel, no ATG), Leg Extensions, Leg Press, DB RDL, Ham Curl, Ab Cable Crunch, Calf Raises 2-3 sets. McGill Big 3 + hip bridges + cat-cow MANDATORY. Pallof press + RKC plank.",
    "Sunday":    "Rest + 7km steady-state run. ZONE 2 ONLY — HR under 145 bpm. Active recovery after Saturday squats.",
}

def pull_garmin() -> dict:
    print("  Connecting to Garmin Connect...")
    client = Garmin(GARMIN_EMAIL, GARMIN_PASSWORD)
    client.login()
    today     = date.today()
    yesterday = today - timedelta(days=1)
    t_str     = today.isoformat()
    y_str     = yesterday.isoformat()
    data      = {}

    try:
        raw  = client.get_sleep_data(y_str)
        dto  = raw.get("dailySleepDTO", {})
        def to_h(s): return round(s / 3600, 2) if s else None
        data["sleep_score"]   = dto.get("sleepScores", {}).get("overall", {}).get("value")
        data["total_sleep_h"] = to_h(dto.get("sleepTimeSeconds", 0))
        data["deep_sleep_h"]  = to_h(dto.get("deepSleepSeconds"))
        data["rem_sleep_h"]   = to_h(dto.get("remSleepSeconds"))
        data["light_sleep_h"] = to_h(dto.get("lightSleepSeconds"))
        data["awake_h"]       = to_h(dto.get("awakeSleepSeconds"))
        print(f"  Sleep: {data['total_sleep_h']}h | Score: {data['sleep_score']}")
    except Exception as e:
        print(f"  Sleep pull failed: {e}")
        data.update({"sleep_score": None, "total_sleep_h": None, "deep_sleep_h": None,
                     "rem_sleep_h": None, "light_sleep_h": None, "awake_h": None})

    try:
        raw  = client.get_hrv_data(t_str)
        summ = raw.get("hrvSummary", {})
        data["hrv_last_night"] = summ.get("lastNight")
        data["hrv_weekly_avg"] = summ.get("weeklyAvg")
        data["hrv_status"]     = summ.get("status", "").capitalize() or None
        print(f"  HRV: {data['hrv_last_night']} ms | Status: {data['hrv_status']}")
    except Exception as e:
        print(f"  HRV pull failed: {e}")
        data.update({"hrv_last_night": None, "hrv_weekly_avg": None, "hrv_status": None})

    try:
        raw     = client.get_rhr_day(t_str)
        metrics = raw.get("allMetrics", {}).get("metricsMap", {}).get("WELLNESS_RESTING_HEART_RATE", [{}])
        data["resting_hr"] = round(metrics[0].get("value")) if metrics else None
        print(f"  Resting HR: {data['resting_hr']} bpm")
    except Exception as e:
        print(f"  Resting HR pull failed: {e}")
        data["resting_hr"] = None

    try:
        raw = client.get_body_battery(t_str)
        data["body_battery"] = raw[-1].get("charged") if isinstance(raw, list) and raw else None
        print(f"  Body Battery: {data['body_battery']}")
    except Exception as e:
        print(f"  Body Battery pull failed: {e}")
        data["body_battery"] = None

    try:
        raw = client.get_training_readiness(t_str)
        if isinstance(raw, list) and raw:
            raw = raw[0]
        data["training_readiness"] = raw.get("score") if raw else None
        print(f"  Training Readiness: {data['training_readiness']}")
    except Exception as e:
        print(f"  Training Readiness pull failed: {e}")
        data["training_readiness"] = None

    return data


def n(v, unit=""): return f"{v}{unit}" if v is not None else "N/A"

def generate_brief(d: dict, day_name: str, date_str: str) -> str:
    session = SCHEDULE.get(day_name, "Rest day.")
    bb = d.get("body_battery")
    bb_note = (f"Body Battery CRITICALLY LOW at {bb} — REST." if bb is not None and bb < 25
               else f"Body Battery LOW at {bb} — MODIFIED session." if bb is not None and bb < 40
               else f"Body Battery {bb} — adequate." if bb is not None
               else "Body Battery unavailable.")
    sleep_h = d.get("total_sleep_h")
    sleep_note = (f"Sleep critically low at {sleep_h}h — no high intensity." if sleep_h is not None and sleep_h < 5.5
                  else f"Sleep suboptimal at {sleep_h}h — no PRs." if sleep_h is not None and sleep_h < 6.5
                  else f"Sleep adequate at {sleep_h}h." if sleep_h is not None
                  else "Sleep data unavailable.")

    prompt = f"""You are Kev's personal health and training advisor. Generate his morning brief.

DATE: {date_str}
TODAY: {session}

PROFILE: Male, mid-20s, 71kg, Sydney. Powerbuilding — 5x gym + 2x runs/week.
INJURY: L4/L5 disc bulge ~70% recovered. McGill Big 3 mandatory before every lower body session.
MEDICATIONS: Vyvanse (~10am) + Dexamfetamine (~noon), 3-4 days/week.

GARMIN:
- Sleep score: {n(d.get('sleep_score'))} / 100
- Total sleep: {n(d.get('total_sleep_h'), 'h')} | Deep: {n(d.get('deep_sleep_h'), 'h')} | REM: {n(d.get('rem_sleep_h'), 'h')}
- HRV last night: {n(d.get('hrv_last_night'), ' ms')} | Weekly avg: {n(d.get('hrv_weekly_avg'), ' ms')} | Status: {n(d.get('hrv_status'))}
- Body Battery: {n(d.get('body_battery'))} / 100
- Resting HR: {n(d.get('resting_hr'), ' bpm')}
- Training Readiness: {n(d.get('training_readiness'))} / 100

FLAGS: {bb_note} {sleep_note}

RULES: BB<25=REST | BB25-40=MODIFIED | Sleep<5.5h=no intensity | HRV declining 3 days=RPE7 cap
Sunday always Zone 2, HR under 145 bpm regardless of scores.

OUTPUT — exact format, nothing extra:
TRAINING_CALL: [GO or MODIFIED or REST]
L4L5_FLAG: [Clear or Watch or Flag]
KEY_INSIGHT: [one sentence max 120 chars]
---
## Training Call
[1-2 sentences with actual data values]

## Top 3 Actions
1. [Most important action for today]
2. [Nutrition or warm-up specific to today]
3. [Recovery action for tonight]

## L4/L5
[Specific note for today. If no risk: "Clear — standard warm-up protocol."]

## Nutrition
[One specific cue. Thursday: include pre-lift AND inter-session meal targets.]

## Recovery Tonight
[One action — sleep target, magnesium timing, or next-day prep.]"""

    resp = requests.post(
        "https://api.anthropic.com/v1/messages",
        headers={"Content-Type": "application/json", "x-api-key": ANTHROPIC_API_KEY, "anthropic-version": "2023-06-01"},
        json={"model": "claude-sonnet-4-6", "max_tokens": 1000,
              "messages": [{"role": "user", "content": prompt}]},
        timeout=30,
    )
    resp.raise_for_status()
    return resp.json()["content"][0]["text"]


def parse_brief(text: str) -> dict:
    import re
    def get(key):
        m = re.search(rf"{key}:\s*([^\n]+)", text)
        return m.group(1).strip() if m else None
    sep   = text.find("---")
    brief = text[sep + 3:].strip() if sep > -1 else text
    return {"training_call": get("TRAINING_CALL") or "GO",
            "l4l5_flag":     get("L4L5_FLAG")     or "Clear",
            "key_insight":   get("KEY_INSIGHT")    or "",
            "full_brief":    brief}


def write_notion(garmin: dict, parsed: dict, iso_date: str):
    def num(v): return {"number": round(float(v), 2)} if v is not None else {"number": None}
    def sel(v): return {"select": {"name": str(v)}} if v else {}
    def rt(v):  return {"rich_text": [{"type": "text", "text": {"content": str(v)[:2000]}}]} if v else {"rich_text": []}

    d, p = garmin, parsed
    title_label = datetime.strptime(iso_date, "%Y-%m-%d").strftime("%d.%m.%Y")
    hrv_map = {"balanced": "Balanced", "unbalanced": "Unbalanced", "low": "Low", "poor": "Poor"}
    hrv_sel = hrv_map.get((d.get("hrv_status") or "").lower(), d.get("hrv_status"))

    body = {
        "parent": {"database_id": NOTION_DB_ID},
        "properties": {
            "Date":               {"title": [{"type": "text", "text": {"content": title_label}}]},
            "Long Date":          {"date": {"start": iso_date}},
            "Total Sleep (h)":    num(d.get("total_sleep_h")),
            "Deep Sleep (h)":     num(d.get("deep_sleep_h")),
            "REM Sleep (h)":      num(d.get("rem_sleep_h")),
            "Light Sleep (h)":    num(d.get("light_sleep_h")),
            "Awake Time (h)":     num(d.get("awake_h")),
            "Resting HR":         num(d.get("resting_hr")),
            "Sleep Score":        num(d.get("sleep_score")),
            "HRV Last Night":     num(d.get("hrv_last_night")),
            "HRV Weekly Avg":     num(d.get("hrv_weekly_avg")),
            "HRV Status":         sel(hrv_sel),
            "Body Battery":       num(d.get("body_battery")),
            "Training Readiness": num(d.get("training_readiness")),
            "Training Call":      sel(p["training_call"]),
            "L4/L5 Flag":         sel(p["l4l5_flag"]),
            "Key Insight":        rt(p["key_insight"]),
            "Full Brief":         rt(p["full_brief"]),
        },
    }

    resp = requests.post(
        "https://api.notion.com/v1/pages",
        headers={"Authorization": f"Bearer {NOTION_TOKEN}", "Notion-Version": "2022-06-28", "Content-Type": "application/json"},
        json=body, timeout=15,
    )
    resp.raise_for_status()
    print("  Notion row created.")


def main():
    now      = datetime.now()
    iso_date = now.strftime("%Y-%m-%d")
    day_name = now.strftime("%A")
    date_str = now.strftime("%A %-d %B %Y")

    print(f"\n{'='*52}\n  MORNING BRIEF — {date_str}\n{'='*52}\n")

    print("[1/3] Pulling Garmin data...")
    garmin_data = pull_garmin()

    print("\n[2/3] Generating brief via Claude...")
    raw_brief = generate_brief(garmin_data, day_name, date_str)
    parsed    = parse_brief(raw_brief)
    print(f"  Call: {parsed['training_call']} | L4/L5: {parsed['l4l5_flag']}")
    print(f"  Insight: {parsed['key_insight']}")

    print("\n[3/3] Writing to Notion...")
    write_notion(garmin_data, parsed, iso_date)

    print(f"\n{'─'*52}\n  Done.\n{'─'*52}\n")
    print(parsed["full_brief"])

if __name__ == "__main__":
    main()
