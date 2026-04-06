#!/usr/bin/env python3
# Kev's Daily Health Brief — writes to Sleep Data database in Notion
# Required GitHub secrets: GARMIN_EMAIL, GARMIN_PASSWORD, NOTION_TOKEN,
#                          NOTION_SLEEP_DB_ID, ANTHROPIC_API_KEY

import os, re, requests, sys
from datetime import date, datetime, timedelta

try:
    from garminconnect import Garmin
except ImportError:
    sys.exit("Missing: pip install garminconnect")

GARMIN_EMAIL      = os.environ["GARMIN_EMAIL"]
GARMIN_PASSWORD   = os.environ["GARMIN_PASSWORD"]
NOTION_TOKEN      = os.environ["NOTION_TOKEN"]
NOTION_DB_ID      = os.environ["NOTION_SLEEP_DB_ID"]
ANTHROPIC_API_KEY = os.environ["ANTHROPIC_API_KEY"]

# ── VERIFY model string is correct ──────────────────────────────────────────
MODEL = "claude-sonnet-4-6"
print(f"  Using Claude model: {MODEL}")

SCHEDULE = {
    "Monday":    "Upper body push/pull. DB Bench, SA Cable Row, DB Shoulder Press, Lat Pulldown, Tricep Extensions, Hammer Curls. Face pulls warm-up.",
    "Tuesday":   "Lower body posterior chain. BB RDL (3-second eccentric), Ham Curl, Leg Extensions, Bulgarian Split Squat, SL Leg Press, Calf Raises. McGill Big 3 MANDATORY first.",
    "Wednesday": "Full rest day.",
    "Thursday":  "HIGH DEMAND — Heavy bench AM + 6x800m intervals PM. Bench RPE 8 cap. Full meal between sessions.",
    "Friday":    "Upper body pull. Lat Pulldown, SA Bench Pulldown, Supinated Cable Row, DB Curls, Preacher Hammer Curl. Face pulls warm-up.",
    "Saturday":  "Lower body squat focus. Squat (below parallel, no ATG), Leg Press, DB RDL, Ham Curl, Ab Crunch, Calf Raises x3. McGill Big 3 MANDATORY. Pallof press + RKC plank.",
    "Sunday":    "Rest + 7km run. ZONE 2 ONLY — HR under 145 bpm.",
}


def pull_garmin():
    print("  Connecting to Garmin...")
    token_dir = os.environ.get("GARMIN_TOKEN_DIR")
    if token_dir:
        client = Garmin()
        client.garth.load(token_dir)
    else:
        client = Garmin(GARMIN_EMAIL, GARMIN_PASSWORD)
        client.login()
    today = date.today()
    yesterday = (today - timedelta(days=1)).isoformat()
    today_str = today.isoformat()
    d = {}

    try:
        raw = client.get_sleep_data(today_str)
        dto = raw.get("dailySleepDTO", {})
        def h(s): return round(s / 3600, 2) if s else None
        d["sleep_score"]   = dto.get("sleepScores", {}).get("overall", {}).get("value")
        d["total_sleep_h"] = h(dto.get("sleepTimeSeconds", 0))
        d["deep_h"]        = h(dto.get("deepSleepSeconds"))
        d["rem_h"]         = h(dto.get("remSleepSeconds"))
        d["light_h"]       = h(dto.get("lightSleepSeconds"))
        d["awake_h"]       = h(dto.get("awakeSleepSeconds"))
        print(f"  Sleep {d['total_sleep_h']}h score {d['sleep_score']}")
    except Exception as e:
        print(f"  Sleep failed: {e}")
        d.update({"sleep_score": None, "total_sleep_h": None, "deep_h": None, "rem_h": None, "light_h": None, "awake_h": None})

    try:
        raw = client.get_hrv_data(today_str)
        s = raw.get("hrvSummary", {})
        d["hrv_last"] = s.get("lastNight")
        d["hrv_avg"]  = s.get("weeklyAvg")
        d["hrv_stat"] = s.get("status", "").capitalize() or None
        print(f"  HRV {d['hrv_last']} ms {d['hrv_stat']}")
    except Exception as e:
        print(f"  HRV failed: {e}")
        d.update({"hrv_last": None, "hrv_avg": None, "hrv_stat": None})

    try:
        raw = client.get_rhr_day(today_str)
        m = raw.get("allMetrics", {}).get("metricsMap", {}).get("WELLNESS_RESTING_HEART_RATE", [{}])
        d["rhr"] = round(m[0].get("value")) if m else None
        print(f"  RHR {d['rhr']} bpm")
    except Exception as e:
        print(f"  RHR failed: {e}")
        d["rhr"] = None

    try:
        raw = client.get_body_battery(today_str)
        d["bb"] = raw[-1].get("charged") if isinstance(raw, list) and raw else None
        print(f"  Body Battery {d['bb']}")
    except Exception as e:
        print(f"  Body Battery failed: {e}")
        d["bb"] = None

    try:
        raw = client.get_training_readiness(today_str)
        if isinstance(raw, list) and raw: raw = raw[0]
        d["tr"] = raw.get("score") if raw else None
        print(f"  Training Readiness {d['tr']}")
    except Exception as e:
        print(f"  Training Readiness failed: {e}")
        d["tr"] = None

    return d


def generate_brief(d, day, date_str):
    session = SCHEDULE.get(day, "Rest day.")
    bb = d.get("bb")
    sl = d.get("total_sleep_h")
    flags = []
    if bb is not None:
        if bb < 25:   flags.append(f"Body Battery CRITICALLY LOW ({bb}) — REST")
        elif bb < 40: flags.append(f"Body Battery LOW ({bb}) — MODIFIED session")
        else:         flags.append(f"Body Battery OK ({bb})")
    if sl is not None:
        if sl < 5.5:   flags.append(f"Sleep critically low ({sl}h) — no high intensity")
        elif sl < 6.5: flags.append(f"Sleep suboptimal ({sl}h) — no PRs")
        else:          flags.append(f"Sleep adequate ({sl}h)")

    prompt = f"""You are Kev's personal health and training advisor. Generate his morning brief.

DATE: {date_str} | SESSION: {session}
PROFILE: Male mid-20s, 71kg, Sydney. Powerbuilding — 5x gym + 2x runs. L4/L5 disc ~70% recovered.
MEDICATIONS: Vyvanse + Dexamfetamine 3-4 days/week.

GARMIN DATA:
Sleep score={d.get('sleep_score')} Total={d.get('total_sleep_h')}h Deep={d.get('deep_h')}h REM={d.get('rem_h')}h
HRV={d.get('hrv_last')}ms AvgHRV={d.get('hrv_avg')}ms HRV_status={d.get('hrv_stat')}
BodyBattery={bb} RHR={d.get('rhr')}bpm TrainingReadiness={d.get('tr')}
FLAGS: {' | '.join(flags) if flags else 'All clear'}

RULES: BB<25=REST BB25-40=MODIFIED Sleep<5.5h=no intensity HRV decline 3days=RPE7cap
Sunday always Zone 2 HR<145 regardless. Lower days McGill Big 3 mandatory. Squat below parallel no ATG.

RESPOND IN EXACTLY THIS FORMAT — nothing before or after:
TRAINING_CALL: [GO or MODIFIED or REST]
L4L5_FLAG: [Clear or Watch or Flag]
KEY_INSIGHT: [max 120 chars]
---
## Training Call
[1-2 sentences citing actual numbers]

## Top 3 Actions
1. [Most important action]
2. [Nutrition or warm-up]
3. [Recovery tonight]

## L4/L5
[Session-specific note or "Clear — standard warm-up protocol."]

## Nutrition
[One specific cue. Thursday: pre-lift AND inter-session targets.]

## Recovery Tonight
[Sleep target, magnesium timing, or next-day prep.]"""

    print(f"  Calling Claude API ({MODEL})...")
    r = requests.post(
        "https://api.anthropic.com/v1/messages",
        headers={
            "Content-Type": "application/json",
            "x-api-key": ANTHROPIC_API_KEY,
            "anthropic-version": "2023-06-01",
        },
        json={"model": MODEL, "max_tokens": 800, "messages": [{"role": "user", "content": prompt}]},
        timeout=30,
    )
    print(f"  Claude response status: {r.status_code}")
    r.raise_for_status()
    return r.json()["content"][0]["text"]


def parse(text):
    def g(k):
        m = re.search(rf"{k}:\s*([^\n]+)", text)
        return m.group(1).strip() if m else None
    sep = text.find("---")
    return {
        "call":    g("TRAINING_CALL") or "GO",
        "flag":    g("L4L5_FLAG")     or "Clear",
        "insight": g("KEY_INSIGHT")   or "",
        "brief":   text[sep+3:].strip() if sep > -1 else text,
    }


def find_notion_page(title):
    """Search Sleep Data DB for a row matching the given date title (DD.MM.YYYY)."""
    r = requests.post(
        f"https://api.notion.com/v1/databases/{NOTION_DB_ID}/query",
        headers={"Authorization": f"Bearer {NOTION_TOKEN}", "Notion-Version": "2022-06-28", "Content-Type": "application/json"},
        json={"filter": {"property": "Date", "title": {"equals": title}}},
        timeout=15,
    )
    r.raise_for_status()
    results = r.json().get("results", [])
    return results[0]["id"] if results else None


def write_notion(d, p, iso_date):
    def num(v): return {"number": round(float(v), 2)} if v is not None else {"number": None}
    def sel(v): return {"select": {"name": str(v)}} if v else {}
    def rt(v):  return {"rich_text": [{"type": "text", "text": {"content": str(v)[:2000]}}]} if v else {"rich_text": []}

    hrv_map = {"balanced": "Balanced", "unbalanced": "Unbalanced", "low": "Low", "poor": "Poor"}
    hrv_sel = hrv_map.get((d.get("hrv_stat") or "").lower(), d.get("hrv_stat"))

    title = datetime.strptime(iso_date, "%Y-%m-%d").strftime("%d.%m.%Y")

    # Fields that belong to kev_daily_health.py — never overwrite sleep-data.py's text columns
    kev_props = {
        "Sleep Score":        num(d.get("sleep_score")),
        "HRV Last Night":     num(d.get("hrv_last")),
        "HRV Weekly Avg":     num(d.get("hrv_avg")),
        "HRV Status":         sel(hrv_sel),
        "Body Battery":       num(d.get("bb")),
        "Training Readiness": num(d.get("tr")),
        "Training Call":      sel(p["call"]),
        "L4/L5 Flag":         sel(p["flag"]),
        "Key Insight":        rt(p["insight"]),
        "Full Brief":         rt(p["brief"]),
    }

    page_id = find_notion_page(title)

    if page_id:
        # Row already created by sleep-data.py — patch only our columns
        r = requests.patch(
            f"https://api.notion.com/v1/pages/{page_id}",
            headers={"Authorization": f"Bearer {NOTION_TOKEN}", "Notion-Version": "2022-06-28", "Content-Type": "application/json"},
            json={"properties": kev_props},
            timeout=15,
        )
        print(f"  Notion PATCH status: {r.status_code}")
        r.raise_for_status()
        print(f"  Patched existing row: {title}")
    else:
        # sleep-data.py hasn't run yet or skipped — create a fallback row with everything we have
        fallback_props = {
            "Date":               {"title": [{"type": "text", "text": {"content": title}}]},
            "Long Date":          {"date": {"start": iso_date}},
            "Total Sleep (h)":    num(d.get("total_sleep_h")),
            "Deep Sleep (h)":     num(d.get("deep_h")),
            "REM Sleep (h)":      num(d.get("rem_h")),
            "Light Sleep (h)":    num(d.get("light_h")),
            "Awake Time (h)":     num(d.get("awake_h")),
            "Resting HR":         num(d.get("rhr")),
            **kev_props,
        }
        r = requests.post(
            "https://api.notion.com/v1/pages",
            headers={"Authorization": f"Bearer {NOTION_TOKEN}", "Notion-Version": "2022-06-28", "Content-Type": "application/json"},
            json={"parent": {"database_id": NOTION_DB_ID}, "properties": fallback_props},
            timeout=15,
        )
        print(f"  Notion CREATE status: {r.status_code}")
        r.raise_for_status()
        print(f"  Created fallback row: {title}")


def main():
    now = datetime.now()
    iso = now.strftime("%Y-%m-%d")
    day = now.strftime("%A")
    ds  = now.strftime("%A %-d %B %Y")
    print(f"\n{'='*50}\n  BRIEF — {ds}\n{'='*50}")

    print("\n[1/3] Garmin...")
    gd = pull_garmin()

    print("\n[2/3] Claude brief...")
    raw = generate_brief(gd, day, ds)
    p   = parse(raw)
    print(f"  Call={p['call']} Flag={p['flag']}")

    print("\n[3/3] Notion...")
    write_notion(gd, p, iso)

    print(f"\n{'='*50}\n  DONE\n{'='*50}\n")
    print(p["brief"])

if __name__ == "__main__":
    main()
