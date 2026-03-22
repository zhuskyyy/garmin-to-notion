"""
One-off backfill script: fetches sleep data for the last N days from Garmin
and creates Notion entries for any missing dates.

Usage:
    python backfill_sleep.py            # backfills last 30 days
    python backfill_sleep.py 14         # backfills last 14 days
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


def sleep_data_exists(client, database_id, sleep_date):
    query = client.databases.query(
        database_id=database_id,
        filter={"property": "Long Date", "date": {"equals": sleep_date}}
    )
    return bool(query.get('results'))


def create_sleep_entry(client, database_id, sleep_data):
    daily_sleep = sleep_data.get('dailySleepDTO', {})
    if not daily_sleep:
        return False

    sleep_date = daily_sleep.get('calendarDate', "Unknown Date")
    total_sleep = sum(
        (daily_sleep.get(k, 0) or 0) for k in ['deepSleepSeconds', 'lightSleepSeconds', 'remSleepSeconds']
    )

    if total_sleep == 0:
        print(f"  Skipping {sleep_date} — no sleep recorded")
        return False

    properties = {
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

    client.pages.create(parent={"database_id": database_id}, properties=properties, icon={"emoji": "😴"})
    print(f"  Created entry for {sleep_date}")
    return True


def main():
    days_back = int(sys.argv[1]) if len(sys.argv) > 1 else 30

    garmin_email = os.getenv("GARMIN_EMAIL")
    garmin_password = os.getenv("GARMIN_PASSWORD")
    notion_token = os.getenv("NOTION_TOKEN")
    database_id = os.getenv("NOTION_SLEEP_DB_ID")

    print("Connecting to Garmin...")
    garmin = Garmin(garmin_email, garmin_password)
    garmin.login()
    print("Connected.")

    client = Client(auth=notion_token)

    today = datetime.today().date()
    dates = [(today - timedelta(days=i)).isoformat() for i in range(1, days_back + 1)]

    print(f"\nChecking {days_back} days ({dates[-1]} → {dates[0]})...\n")
    created = 0
    skipped = 0

    for date_str in dates:
        if sleep_data_exists(client, database_id, date_str):
            print(f"  {date_str} — already exists, skipping")
            skipped += 1
            continue

        print(f"  {date_str} — fetching from Garmin...")
        try:
            data = garmin.get_sleep_data(date_str)
            if data and create_sleep_entry(client, database_id, data):
                created += 1
            time.sleep(1)  # gentle rate limiting
        except Exception as e:
            print(f"  {date_str} — error: {e}")

    print(f"\nDone. Created: {created}, Already existed: {skipped}")


if __name__ == "__main__":
    main()
