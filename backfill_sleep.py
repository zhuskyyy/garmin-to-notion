"""
One-off backfill script: fetches sleep data for the last N days from Garmin
and creates Notion entries for any missing dates.

Usage:
    python backfill_sleep.py            # backfills last 30 days (skip existing)
    python backfill_sleep.py 14         # backfills last 14 days
    python backfill_sleep.py 30 --force # overwrites blank/incomplete existing rows
"""
import os
import sys
import time
from datetime import datetime, timedelta
from garminconnect import Garmin
from notion_client import Client
from dotenv import load_dotenv
import pytz

local_tz = pytz.timezone("America/New_York")
TOKEN_DIR = "/tmp/garth_tokens"

load_dotenv()


def format_duration(seconds):
    minutes = (seconds or 0) // 60
    return f"{minutes // 60}h {minutes % 60}m"


def format_time(timestamp):
    return (
        datetime.utcfromtimestamp(timestamp / 1000).strftime("%Y-%m-%dT%H:%M:%S.000Z")
        if timestamp else None
    )


def format_time_readable(timestamp):
    return (
        datetime.fromtimestamp(timestamp / 1000, local_tz).strftime("%H:%M")
        if timestamp else "Unknown"
    )


def format_date_for_name(sleep_date):
    return datetime.strptime(sleep_date, "%Y-%m-%d").strftime("%d.%m.%Y") if sleep_date else "Unknown"


def find_existing_page(client, database_id, sleep_date):
    """Return page_id if a row exists for this date (by Long Date), else None."""
    query = client.databases.query(
        database_id=database_id,
        filter={"property": "Long Date", "date": {"equals": sleep_date}}
    )
    results = query.get('results', [])
    return results[0]["id"] if results else None


def build_properties(daily_sleep, sleep_data):
    sleep_date = daily_sleep.get('calendarDate', "Unknown Date")
    total_sleep = sum(
        (daily_sleep.get(k, 0) or 0) for k in ['deepSleepSeconds', 'lightSleepSeconds', 'remSleepSeconds']
    )
    return sleep_date, total_sleep, {
        "Date": {"title": [{"text": {"content": format_date_for_name(sleep_date)}}]},
        "Times": {"rich_text": [{"text": {"content": f"{format_time_readable(daily_sleep.get('sleepStartTimestampGMT'))} → {format_time_readable(daily_sleep.get('sleepEndTimestampGMT'))}"}}]},
        "Long Date": {"date": {"start": sleep_date}},
        "Full Date/Time": {"date": {"start": format_time(daily_sleep.get('sleepStartTimestampGMT')), "end": format_time(daily_sleep.get('sleepEndTimestampGMT'))}},
        "Total Sleep (h)": {"number": round(total_sleep / 3600, 1)},
        "Light Sleep (h)": {"number": round(daily_sleep.get('lightSleepSeconds', 0) / 3600, 1)},
        "Deep Sleep (h)": {"number": round(daily_sleep.get('deepSleepSeconds', 0) / 3600, 1)},
        "REM Sleep (h)": {"number": round(daily_sleep.get('remSleepSeconds', 0) / 3600, 1)},
        "Awake Time (h)": {"number": round(daily_sleep.get('awakeSleepSeconds', 0) / 3600, 1)},
        "Total Sleep": {"rich_text": [{"text": {"content": format_duration(total_sleep)}}]},
        "Light Sleep": {"rich_text": [{"text": {"content": format_duration(daily_sleep.get('lightSleepSeconds', 0))}}]},
        "Deep Sleep": {"rich_text": [{"text": {"content": format_duration(daily_sleep.get('deepSleepSeconds', 0))}}]},
        "REM Sleep": {"rich_text": [{"text": {"content": format_duration(daily_sleep.get('remSleepSeconds', 0))}}]},
        "Awake Time": {"rich_text": [{"text": {"content": format_duration(daily_sleep.get('awakeSleepSeconds', 0))}}]},
        "Resting HR": {"number": sleep_data.get('restingHeartRate', 0)}
    }


def create_or_patch_entry(client, database_id, sleep_data, force=False):
    daily_sleep = sleep_data.get('dailySleepDTO', {})
    if not daily_sleep:
        return False

    sleep_date, total_sleep, properties = build_properties(daily_sleep, sleep_data)

    if total_sleep == 0:
        print(f"  Skipping {sleep_date} — no sleep recorded")
        return False

    notion_headers = {
        "Authorization": f"Bearer {client.auth}",
        "Notion-Version": "2022-06-28",
        "Content-Type": "application/json",
    }

    page_id = find_existing_page(client, database_id, sleep_date)

    if page_id and force:
        import requests
        r = requests.patch(
            f"https://api.notion.com/v1/pages/{page_id}",
            headers=notion_headers,
            json={"properties": properties},
            timeout=15,
        )
        r.raise_for_status()
        print(f"  Patched entry for {sleep_date}")
        return True
    elif page_id:
        print(f"  {sleep_date} — already exists, skipping (use --force to overwrite)")
        return False
    else:
        client.pages.create(parent={"database_id": database_id}, properties=properties, icon={"emoji": "😴"})
        print(f"  Created entry for {sleep_date}")
        return True


def main():
    args = sys.argv[1:]
    days_back = int(args[0]) if args and args[0].lstrip('-').isdigit() else 30
    force = "--force" in args

    garmin_email = os.getenv("GARMIN_EMAIL")
    garmin_password = os.getenv("GARMIN_PASSWORD")
    notion_token = os.getenv("NOTION_TOKEN")
    database_id = os.getenv("NOTION_SLEEP_DB_ID")

    print("Connecting to Garmin...")
    try:
        garmin = Garmin(tokenstore=TOKEN_DIR)
        garmin.login()
        print("  Loaded cached token.")
    except Exception:
        garmin = Garmin(garmin_email, garmin_password)
        garmin.login()
        garmin.garth.dump(TOKEN_DIR)
        print("  Authenticated with credentials.")

    client = Client(auth=notion_token)

    today = datetime.today().date()
    dates = [(today - timedelta(days=i)).isoformat() for i in range(1, days_back + 1)]

    mode = "FORCE (overwriting blanks)" if force else "SAFE (skipping existing)"
    print(f"\nMode: {mode}")
    print(f"Checking {days_back} days ({dates[-1]} → {dates[0]})...\n")
    created = patched = skipped = 0

    for date_str in dates:
        print(f"  {date_str} — fetching from Garmin...")
        try:
            data = garmin.get_sleep_data(date_str)
            if data:
                result = create_or_patch_entry(client, database_id, data, force=force)
                if result:
                    if force and find_existing_page(client, database_id, date_str):
                        patched += 1
                    else:
                        created += 1
            time.sleep(1)
        except Exception as e:
            print(f"  {date_str} — error: {e}")
            skipped += 1

    print(f"\nDone. Created: {created}, Patched: {patched}, Errors: {skipped}")


if __name__ == "__main__":
    main()
