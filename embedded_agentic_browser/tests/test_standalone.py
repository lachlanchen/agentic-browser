import argparse
import unittest
from pathlib import Path
from unittest import mock

from embedded_agentic_browser import standalone


class StandaloneLauncherTests(unittest.TestCase):
    def test_app_url(self) -> None:
        self.assertEqual(standalone.app_url("127.0.0.1", 8792), "http://127.0.0.1:8792")

    def test_server_command_includes_backend_and_browser_ports(self) -> None:
        args = argparse.Namespace(
            host="127.0.0.1",
            port=8792,
            browser_port=9444,
            profile_dir=Path("/tmp/controlled"),
            model="gpt-5.4-mini",
            reasoning_effort="low",
        )
        command = standalone.build_server_command(args)
        self.assertIn("embedded_agentic_browser.server", command)
        self.assertIn("8792", command)
        self.assertIn("9444", command)
        self.assertIn("/tmp/controlled", command)

    def test_app_chrome_command_uses_app_mode_and_profile(self) -> None:
        with mock.patch.object(standalone, "find_chrome_binary", return_value="/usr/bin/chrome"):
            command = standalone.build_app_chrome_command("http://127.0.0.1:8792", Path("/tmp/shell"))
        self.assertEqual(command[0], "/usr/bin/chrome")
        self.assertIn("--app=http://127.0.0.1:8792", command)
        self.assertIn("--user-data-dir=/tmp/shell", command)

    def test_profile_chrome_pids_parses_pgrep_output(self) -> None:
        output = "123 chrome --user-data-dir=/tmp/profile\n456 python launcher\n"
        self.assertEqual(standalone.profile_chrome_pids(output, current_pid=456), [123])


if __name__ == "__main__":
    unittest.main()
