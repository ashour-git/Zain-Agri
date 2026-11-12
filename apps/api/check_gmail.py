"""Check that a Gmail address and app password can send mail (SMTP login only).

Usage, from apps/api:
    uv run python check_gmail.py you@gmail.com

The app password is asked for at a hidden prompt and never printed or stored.
Nothing is sent; the script only logs in and out.
"""

import getpass
import smtplib
import sys


def main() -> int:
    if len(sys.argv) != 2:
        print("usage: uv run python check_gmail.py you@gmail.com")
        return 2
    user = sys.argv[1].strip()
    password = "".join(getpass.getpass("App password (hidden): ").split())
    print(f"Password length: {len(password)} (a Google app password has 16 letters)")
    try:
        with smtplib.SMTP_SSL("smtp.gmail.com", 465, timeout=30) as smtp:
            smtp.login(user, password)
    except smtplib.SMTPAuthenticationError as exc:
        print(f"REFUSED by Google: {exc.smtp_code} {exc.smtp_error.decode(errors='replace')}")
        return 1
    except smtplib.SMTPServerDisconnected:
        print("REFUSED: Google closed the connection during login.")
        print("Either the app password is wrong, or Google is blocking the sign-in.")
        return 1
    except OSError as exc:
        print(f"NETWORK problem reaching Gmail: {exc}")
        return 1
    print("OK: Gmail accepted this address and app password.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
