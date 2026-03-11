"""Unit tests for notifier.py.

All tests use mocking to avoid real network connections, SMTP calls, or
subprocess invocations so they run reliably in any environment (no network
access required, no SMTP server needed).
"""

import json
import logging
import smtplib
import socket
import sys
from pathlib import Path
from unittest.mock import MagicMock, call, mock_open, patch

import pytest

# Ensure the project root is on the path when tests are run from any directory.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from notifier import (
    is_host_up,
    load_config,
    monitor_hosts,
    send_desktop_notification,
    send_email,
)


# ---------------------------------------------------------------------------
# is_host_up
# ---------------------------------------------------------------------------

class TestIsHostUp:
    def test_returns_true_when_connection_succeeds(self):
        with patch("socket.create_connection") as mock_conn:
            mock_conn.return_value.__enter__ = lambda s: s
            mock_conn.return_value.__exit__ = MagicMock(return_value=False)
            assert is_host_up("8.8.8.8", 80) is True

    def test_returns_false_on_socket_timeout(self):
        with patch("socket.create_connection", side_effect=socket.timeout):
            assert is_host_up("192.0.2.1", 80) is False

    def test_returns_false_on_socket_error(self):
        with patch("socket.create_connection", side_effect=socket.error("refused")):
            assert is_host_up("192.0.2.1", 80) is False

    def test_returns_false_on_os_error(self):
        with patch("socket.create_connection", side_effect=OSError("unreachable")):
            assert is_host_up("192.0.2.1", 80) is False

    def test_uses_custom_port_and_timeout(self):
        with patch("socket.create_connection") as mock_conn:
            mock_conn.return_value.__enter__ = lambda s: s
            mock_conn.return_value.__exit__ = MagicMock(return_value=False)
            is_host_up("example.com", port=443, timeout=5)
            mock_conn.assert_called_once_with(("example.com", 443), timeout=5)


# ---------------------------------------------------------------------------
# load_config
# ---------------------------------------------------------------------------

class TestLoadConfig:
    def test_loads_valid_json(self, tmp_path):
        cfg = {"check_interval": 30, "hosts": ["1.1.1.1"]}
        config_file = tmp_path / "config.json"
        config_file.write_text(json.dumps(cfg))
        result = load_config(str(config_file))
        assert result == cfg

    def test_raises_file_not_found_for_missing_file(self, tmp_path):
        with pytest.raises(FileNotFoundError, match="config.json"):
            load_config(str(tmp_path / "missing.json"))

    def test_raises_json_decode_error_for_invalid_json(self, tmp_path):
        bad_file = tmp_path / "bad.json"
        bad_file.write_text("{ not valid json }")
        with pytest.raises(json.JSONDecodeError):
            load_config(str(bad_file))


# ---------------------------------------------------------------------------
# send_email
# ---------------------------------------------------------------------------

class TestSendEmail:
    BASE_CONFIG = {
        "email": {
            "enabled": True,
            "smtp_server": "smtp.example.com",
            "smtp_port": 587,
            "use_tls": True,
            "username": "user@example.com",
            "password": "secret",
            "from": "user@example.com",
            "to": "admin@example.com",
        }
    }

    def test_sends_email_when_enabled(self):
        with patch("smtplib.SMTP") as mock_smtp_cls:
            mock_server = MagicMock()
            mock_smtp_cls.return_value.__enter__ = lambda s: mock_server
            mock_smtp_cls.return_value.__exit__ = MagicMock(return_value=False)
            send_email(self.BASE_CONFIG, "192.168.1.1", "down")
            mock_server.starttls.assert_called_once()
            mock_server.login.assert_called_once_with("user@example.com", "secret")
            mock_server.send_message.assert_called_once()

    def test_skips_email_when_disabled(self):
        config = {"email": {"enabled": False}}
        with patch("smtplib.SMTP") as mock_smtp_cls:
            send_email(config, "10.0.0.1", "up")
            mock_smtp_cls.assert_not_called()

    def test_skips_email_when_no_email_section(self):
        with patch("smtplib.SMTP") as mock_smtp_cls:
            send_email({}, "10.0.0.1", "up")
            mock_smtp_cls.assert_not_called()

    def test_logs_error_on_smtp_exception(self, caplog):
        with patch("smtplib.SMTP") as mock_smtp_cls:
            mock_smtp_cls.return_value.__enter__ = MagicMock(
                side_effect=smtplib.SMTPException("auth failed")
            )
            mock_smtp_cls.return_value.__exit__ = MagicMock(return_value=False)
            with caplog.at_level(logging.ERROR):
                send_email(self.BASE_CONFIG, "host", "up")
            assert any("SMTP" in r.message for r in caplog.records)

    def test_logs_error_on_network_os_error(self, caplog):
        with patch("smtplib.SMTP") as mock_smtp_cls:
            mock_smtp_cls.return_value.__enter__ = MagicMock(
                side_effect=OSError("connection refused")
            )
            mock_smtp_cls.return_value.__exit__ = MagicMock(return_value=False)
            with caplog.at_level(logging.ERROR):
                send_email(self.BASE_CONFIG, "host", "up")
            assert any("Network" in r.message or "error" in r.message.lower() for r in caplog.records)

    def test_no_tls_when_use_tls_false(self):
        config = dict(self.BASE_CONFIG)
        config["email"] = {**self.BASE_CONFIG["email"], "use_tls": False}
        with patch("smtplib.SMTP") as mock_smtp_cls:
            mock_server = MagicMock()
            mock_smtp_cls.return_value.__enter__ = lambda s: mock_server
            mock_smtp_cls.return_value.__exit__ = MagicMock(return_value=False)
            send_email(config, "host", "up")
            mock_server.starttls.assert_not_called()


# ---------------------------------------------------------------------------
# send_desktop_notification
# ---------------------------------------------------------------------------

class TestSendDesktopNotification:
    def test_linux_calls_notify_send(self):
        with patch("platform.system", return_value="Linux"), \
             patch("subprocess.run") as mock_run:
            send_desktop_notification("myhost", "down")
            mock_run.assert_called_once()
            args = mock_run.call_args[0][0]
            assert args[0] == "notify-send"
            assert "myhost" in " ".join(args)

    def test_macos_calls_osascript(self):
        with patch("platform.system", return_value="Darwin"), \
             patch("subprocess.run") as mock_run:
            send_desktop_notification("myhost", "up")
            mock_run.assert_called_once()
            args = mock_run.call_args[0][0]
            assert args[0] == "osascript"
            assert "myhost" in " ".join(args)

    def test_windows_calls_powershell(self):
        with patch("platform.system", return_value="Windows"), \
             patch("subprocess.run") as mock_run:
            send_desktop_notification("myhost", "up")
            mock_run.assert_called_once()
            args = mock_run.call_args[0][0]
            assert "powershell" in args[0].lower()

    def test_unknown_platform_logs_warning(self, caplog):
        with patch("platform.system", return_value="FreeBSD"), \
             patch("subprocess.run") as mock_run, \
             caplog.at_level(logging.WARNING):
            send_desktop_notification("myhost", "up")
            mock_run.assert_not_called()
            assert any("not supported" in r.message for r in caplog.records)

    def test_file_not_found_logs_warning(self, caplog):
        with patch("platform.system", return_value="Linux"), \
             patch("subprocess.run", side_effect=FileNotFoundError("notify-send not found")), \
             caplog.at_level(logging.WARNING):
            send_desktop_notification("myhost", "down")
            assert any("not found" in r.message for r in caplog.records)


# ---------------------------------------------------------------------------
# monitor_hosts
# ---------------------------------------------------------------------------

class TestMonitorHosts:
    """Tests for the monitoring loop.  ``time.sleep`` is always mocked to
    prevent tests from hanging and ``is_host_up`` is mocked to control the
    simulated host state sequence.
    """

    def _run_loop_n_times(self, config, side_effects):
        """Run monitor_hosts for exactly one iteration using the given
        is_host_up side-effect sequence, then raise StopIteration to exit."""
        # After the side-effects are exhausted StopIteration breaks the loop.
        effects = list(side_effects) + [StopIteration]

        def mock_sleep(_):
            raise StopIteration

        with patch("notifier.is_host_up", side_effect=effects), \
             patch("notifier.send_email") as mock_email, \
             patch("notifier.send_desktop_notification") as mock_desktop, \
             patch("time.sleep", side_effect=mock_sleep):
            try:
                monitor_hosts(config)
            except StopIteration:
                pass
        return mock_email, mock_desktop

    def test_no_notification_on_first_check(self):
        config = {"hosts": ["1.1.1.1"], "check_interval": 10}
        mock_email, mock_desktop = self._run_loop_n_times(config, [True])
        mock_email.assert_not_called()
        mock_desktop.assert_not_called()

    def test_notification_sent_on_host_going_down(self):
        config = {"hosts": ["1.1.1.1"], "check_interval": 10}
        # Two iterations: first UP (initial), second DOWN (change)
        call_sequence = [True, False]

        sleep_calls = []

        def mock_sleep(_):
            sleep_calls.append(1)
            if len(sleep_calls) >= 2:
                raise StopIteration

        with patch("notifier.is_host_up", side_effect=call_sequence + [StopIteration]), \
             patch("notifier.send_email") as mock_email, \
             patch("notifier.send_desktop_notification") as mock_desktop, \
             patch("time.sleep", side_effect=mock_sleep):
            try:
                monitor_hosts(config)
            except StopIteration:
                pass

        mock_email.assert_called_once()
        mock_desktop.assert_called_once()
        # Ensure the status passed is "down"
        assert mock_email.call_args[0][2] == "down"
        assert mock_desktop.call_args[0][1] == "down"

    def test_notification_sent_on_host_coming_up(self):
        config = {"hosts": ["1.1.1.1"], "check_interval": 10}
        call_sequence = [False, True]

        sleep_calls = []

        def mock_sleep(_):
            sleep_calls.append(1)
            if len(sleep_calls) >= 2:
                raise StopIteration

        with patch("notifier.is_host_up", side_effect=call_sequence + [StopIteration]), \
             patch("notifier.send_email") as mock_email, \
             patch("notifier.send_desktop_notification") as mock_desktop, \
             patch("time.sleep", side_effect=mock_sleep):
            try:
                monitor_hosts(config)
            except StopIteration:
                pass

        mock_email.assert_called_once()
        assert mock_email.call_args[0][2] == "up"

    def test_no_notification_when_status_unchanged(self):
        config = {"hosts": ["1.1.1.1"], "check_interval": 10}
        call_sequence = [True, True]

        sleep_calls = []

        def mock_sleep(_):
            sleep_calls.append(1)
            if len(sleep_calls) >= 2:
                raise StopIteration

        with patch("notifier.is_host_up", side_effect=call_sequence + [StopIteration]), \
             patch("notifier.send_email") as mock_email, \
             patch("notifier.send_desktop_notification") as mock_desktop, \
             patch("time.sleep", side_effect=mock_sleep):
            try:
                monitor_hosts(config)
            except StopIteration:
                pass

        mock_email.assert_not_called()
        mock_desktop.assert_not_called()

    def test_dict_host_entry_with_custom_port_and_label(self):
        config = {
            "hosts": [{"host": "10.0.0.1", "port": 443, "label": "My Server"}],
            "check_interval": 10,
        }
        with patch("notifier.is_host_up", return_value=True) as mock_check, \
             patch("time.sleep", side_effect=StopIteration), \
             patch("notifier.send_email"), \
             patch("notifier.send_desktop_notification"):
            try:
                monitor_hosts(config)
            except StopIteration:
                pass
        mock_check.assert_called_with("10.0.0.1", 443)

    def test_empty_hosts_list_logs_warning_and_returns(self, caplog):
        config = {"hosts": [], "check_interval": 10}
        with caplog.at_level(logging.WARNING):
            monitor_hosts(config)
        assert any("No hosts" in r.message for r in caplog.records)

    def test_multiple_hosts_tracked_independently(self):
        config = {
            "hosts": ["host-a", "host-b"],
            "check_interval": 10,
        }
        # host-a: UP → DOWN; host-b: stays UP
        call_sequence_iter1 = [True, True]   # first sleep: both UP
        call_sequence_iter2 = [False, True]  # second sleep: host-a DOWN, host-b still UP

        sleep_calls = []

        def mock_sleep(_):
            sleep_calls.append(1)
            if len(sleep_calls) >= 2:
                raise StopIteration

        side_effects = call_sequence_iter1 + call_sequence_iter2 + [StopIteration]

        with patch("notifier.is_host_up", side_effect=side_effects), \
             patch("notifier.send_email") as mock_email, \
             patch("notifier.send_desktop_notification") as mock_desktop, \
             patch("time.sleep", side_effect=mock_sleep):
            try:
                monitor_hosts(config)
            except StopIteration:
                pass

        # Only one notification (for host-a going down)
        assert mock_email.call_count == 1
        assert mock_desktop.call_count == 1
        assert mock_email.call_args[0][1] == "host-a"
        assert mock_email.call_args[0][2] == "down"
