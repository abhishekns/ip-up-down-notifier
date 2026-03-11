# ip-up-down-notifier

An application that checks whether an IP address or hostname is available or
unavailable and — on every status change — sends an email **and** shows a
desktop notification to the user. It runs continuously on your PC.

---

## Technology stack

| Layer | Choice | Why minimal |
|---|---|---|
| Language | **Python 3** | Pre-installed on macOS and most Linux distros; one-click installer on Windows |
| Connectivity check | `socket` (stdlib) | No extra packages; works without root/admin |
| Email | `smtplib` / `email` (stdlib) | No extra packages |
| Desktop notifications | Platform OS commands | `notify-send` (Linux), `osascript` (macOS), PowerShell (Windows) — all built-in |
| Configuration | `json` (stdlib) | No extra packages |
| Tests | `pytest` | One `pip install pytest` away |

**No third-party runtime packages are required** to run the application.
`pytest` is the only package listed in `requirements.txt` and is only needed
to run the test suite.

---

## Requirements

* Python 3.8 or newer
* For desktop notifications on Linux: `libnotify` / `notify-send`
  (installed by default on GNOME/KDE desktops)

---

## Quick start

```bash
# 1. Clone the repository
git clone https://github.com/abhishekns/ip-up-down-notifier.git
cd ip-up-down-notifier

# 2. Create your configuration file
cp config.json.example config.json
#    Edit config.json with your hosts and (optionally) SMTP settings

# 3. Run the notifier
python notifier.py

# Optional flags:
python notifier.py --config /path/to/config.json   # custom config path
python notifier.py --verbose                        # debug logging
```

---

## Configuration (`config.json`)

Copy `config.json.example` to `config.json` and edit it.
`config.json` is listed in `.gitignore` so your SMTP credentials are never
committed to the repository.

```jsonc
{
  // How often (in seconds) to check each host
  "check_interval": 60,

  // List of hosts to monitor.
  // Each entry can be a plain string (defaults to port 80)
  // or an object with "host", "port", and optional "label".
  "hosts": [
    "8.8.8.8",
    {
      "host": "1.1.1.1",
      "port": 53,
      "label": "Cloudflare DNS"
    },
    {
      "host": "example.com",
      "port": 80,
      "label": "Example Website"
    }
  ],

  // Email notifications (uses built-in smtplib — no extra package)
  "email": {
    "enabled": false,
    "smtp_server": "smtp.gmail.com",
    "smtp_port": 587,
    "use_tls": true,
    "username": "your-email@gmail.com",
    "password": "your-app-password",
    "from": "your-email@gmail.com",
    "to": "recipient@example.com"
  }
}
```

> **Gmail tip** – use an [App Password](https://support.google.com/accounts/answer/185833)
> instead of your normal Gmail password.

---

## How it works

1. The script reads `config.json` at startup.
2. Every `check_interval` seconds it opens a TCP connection to each configured
   `host:port`.  A successful connection means the host is **UP**; any error
   means **DOWN**.
3. When a host changes state (UP→DOWN or DOWN→UP):
   * A **desktop notification** is shown via the OS native command.
   * An **email** is sent if `email.enabled` is `true`.
4. The initial status check on startup is always silent (no notification).

---

## Running the tests

```bash
pip install pytest
python -m pytest tests/ -v
```

All tests mock network calls so they run without any real hosts or SMTP server.

---

## Project structure

```
ip-up-down-notifier/
├── notifier.py          # Main application (Python stdlib only)
├── config.json.example  # Example configuration (safe to commit)
├── config.json          # Your configuration (git-ignored, contains secrets)
├── requirements.txt     # Only pytest — for the test suite
├── tests/
│   └── test_notifier.py # Unit tests
└── README.md
```
