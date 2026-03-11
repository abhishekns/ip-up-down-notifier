#!/usr/bin/env python3
"""
IP/Host Up-Down Notifier
Monitors IP addresses or hostnames and sends notifications on status changes.

Requires only Python 3 standard library for core functionality.
Desktop notifications use platform-native OS commands (no extra packages needed).
Email notifications use the built-in smtplib module.
"""

import json
import logging
import platform
import smtplib
import socket
import subprocess
import sys
import time
from datetime import datetime
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from pathlib import Path


# ---------------------------------------------------------------------------
# Host connectivity check
# ---------------------------------------------------------------------------

def is_host_up(host, port=80, timeout=3):
    """Return True if *host* is reachable by opening a TCP connection to *port*.

    Uses only Python's built-in ``socket`` module so no extra packages are
    needed.  A TCP-SYN style check is reliable without requiring root/admin
    privileges (unlike raw ICMP ping).
    """
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except (socket.timeout, socket.error, OSError):
        return False


# ---------------------------------------------------------------------------
# Notification helpers
# ---------------------------------------------------------------------------

def send_desktop_notification(host, status):
    """Send a desktop notification using platform-native OS commands.

    * Linux  – ``notify-send`` (part of ``libnotify``, available in most distros)
    * macOS  – ``osascript`` (built-in)
    * Windows – PowerShell ``BurntToast``-free toast via Windows Runtime COM
    """
    title = f"Host {status.upper()}: {host}"
    message = f"{host} is now {status.upper()} — {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
    system = platform.system()

    try:
        if system == "Linux":
            icon = "network-transmit-receive" if status == "up" else "network-offline"
            subprocess.run(
                ["notify-send", "-i", icon, title, message],
                check=False,
                timeout=5,
            )
        elif system == "Darwin":
            script = f'display notification "{message}" with title "{title}"'
            subprocess.run(
                ["osascript", "-e", script],
                check=False,
                timeout=5,
            )
        elif system == "Windows":
            # Uses Windows Runtime via PowerShell — available on Windows 8+ with no extra installs
            ps_script = (
                "[Windows.UI.Notifications.ToastNotificationManager, "
                "Windows.UI.Notifications, ContentType = WindowsRuntime] | Out-Null; "
                "$t = [Windows.UI.Notifications.ToastTemplateType]::ToastText02; "
                "$xml = [Windows.UI.Notifications.ToastNotificationManager]::GetTemplateContent($t); "
                "$nodes = $xml.GetElementsByTagName('text'); "
                f"$nodes.Item(0).AppendChild($xml.CreateTextNode('{title}')) | Out-Null; "
                f"$nodes.Item(1).AppendChild($xml.CreateTextNode('{message}')) | Out-Null; "
                "$toast = [Windows.UI.Notifications.ToastNotification]::new($xml); "
                "$notifier = [Windows.UI.Notifications.ToastNotificationManager]"
                "::CreateToastNotifier('IP Up-Down Notifier'); "
                "$notifier.Show($toast)"
            )
            subprocess.run(
                ["powershell", "-NoProfile", "-Command", ps_script],
                check=False,
                timeout=10,
            )
        else:
            logging.warning("Desktop notifications not supported on platform: %s", system)
    except FileNotFoundError as exc:
        logging.warning("Desktop notification command not found: %s", exc)
    except Exception as exc:  # pragma: no cover
        logging.error("Failed to send desktop notification: %s", exc)


def send_email(config, host, status):
    """Send an email notification about a host status change.

    Reads connection settings from *config['email']*.  Uses the built-in
    ``smtplib`` module so no extra packages are required.

    The ``email`` section of the config must contain:
        enabled, smtp_server, smtp_port, username, password, from, to
    Optional keys: use_tls (default True)
    """
    email_cfg = config.get("email", {})
    if not email_cfg.get("enabled", False):
        return

    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    subject = f"[ip-notifier] {host} is {status.upper()}"
    body = (
        f"Host:   {host}\n"
        f"Status: {status.upper()}\n"
        f"Time:   {timestamp}\n"
    )

    msg = MIMEMultipart()
    msg["From"] = email_cfg["from"]
    msg["To"] = email_cfg["to"]
    msg["Subject"] = subject
    msg.attach(MIMEText(body, "plain"))

    try:
        with smtplib.SMTP(email_cfg["smtp_server"], int(email_cfg["smtp_port"])) as server:
            if email_cfg.get("use_tls", True):
                server.starttls()
            server.login(email_cfg["username"], email_cfg["password"])
            server.send_message(msg)
        logging.info("Email sent for %s → %s", host, status.upper())
    except smtplib.SMTPException as exc:
        logging.error("SMTP error sending notification for %s: %s", host, exc)
    except OSError as exc:
        logging.error("Network error sending email for %s: %s", host, exc)


# ---------------------------------------------------------------------------
# Configuration loading
# ---------------------------------------------------------------------------

def load_config(config_path="config.json"):
    """Load and return the JSON configuration file at *config_path*."""
    path = Path(config_path)
    if not path.exists():
        raise FileNotFoundError(
            f"Configuration file not found: {config_path}\n"
            "Copy config.json.example to config.json and edit it."
        )
    with path.open("r", encoding="utf-8") as fh:
        return json.load(fh)


# ---------------------------------------------------------------------------
# Core monitoring loop
# ---------------------------------------------------------------------------

def monitor_hosts(config):
    """Continuously check every host defined in *config* and emit notifications
    whenever a host transitions between up and down states.

    Each entry in ``config['hosts']`` can be either:
    * a plain string (e.g. ``"8.8.8.8"``) — checked on port 80
    * a dict with keys ``host``, optional ``port`` (default 80),
      optional ``label`` for friendlier log messages
    """
    hosts = config.get("hosts", [])
    interval = int(config.get("check_interval", 60))

    if not hosts:
        logging.warning("No hosts configured. Please edit config.json.")
        return

    logging.info("Starting monitoring for %d host(s) every %ds", len(hosts), interval)

    # Track last known status per host key (None = not yet checked)
    host_status: dict = {}

    while True:
        for entry in hosts:
            if isinstance(entry, str):
                host, port, label = entry, 80, entry
            else:
                host = entry["host"]
                port = int(entry.get("port", 80))
                label = entry.get("label", host)

            current_up = is_host_up(host, port)
            current_status = "up" if current_up else "down"
            previous_status = host_status.get(host)

            if previous_status is None:
                host_status[host] = current_status
                logging.info("[initial] %s → %s", label, current_status.upper())
            elif previous_status != current_status:
                logging.info(
                    "[change]  %s: %s → %s",
                    label,
                    previous_status.upper(),
                    current_status.upper(),
                )
                host_status[host] = current_status
                send_email(config, label, current_status)
                send_desktop_notification(label, current_status)
            else:
                logging.debug("[ok]      %s is %s", label, current_status.upper())

        time.sleep(interval)


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main(argv=None):
    import argparse

    parser = argparse.ArgumentParser(
        description="Monitor IP addresses/hostnames and notify on status changes."
    )
    parser.add_argument(
        "-c", "--config",
        default="config.json",
        help="Path to config file (default: config.json)",
    )
    parser.add_argument(
        "-v", "--verbose",
        action="store_true",
        help="Enable verbose (DEBUG) logging",
    )
    args = parser.parse_args(argv)

    log_level = logging.DEBUG if args.verbose else logging.INFO
    logging.basicConfig(
        level=log_level,
        format="%(asctime)s  %(levelname)-8s  %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    try:
        config = load_config(args.config)
    except (FileNotFoundError, json.JSONDecodeError) as exc:
        logging.error("%s", exc)
        sys.exit(1)

    try:
        monitor_hosts(config)
    except KeyboardInterrupt:
        logging.info("Monitoring stopped.")


if __name__ == "__main__":
    main()
