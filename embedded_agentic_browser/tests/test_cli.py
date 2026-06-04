import unittest
from contextlib import redirect_stdout
from io import StringIO
from unittest import mock

import agentic_browser_cli as cli


class CliFormattingTests(unittest.TestCase):
    def test_status_summary_lists_targets(self) -> None:
        text = cli.status_summary(
            {
                "browser_port": 9344,
                "model": "gpt-test",
                "reasoning_effort": "low",
                "targets": [{"id": "target-1", "title": "Example", "url": "https://example.com"}],
            }
        )
        self.assertIn("browser_port: 9344", text)
        self.assertIn("target-1", text)

    def test_libgen_summary_reports_blocked_mirrors(self) -> None:
        text = cli.libgen_summary(
            {
                "status": "links_ready",
                "selected_card": {"title": "Book", "authors": ["Author"], "file": "epub"},
                "links_snapshot": {"url": "https://libgen.pw/links/1"},
                "mirror_links": [
                    {
                        "text": "Libgen",
                        "href": "https://libgen.net/?l=x",
                        "policy": {"allowed": False, "stop_reason": "Blocked shadow-library resolver/mirror URL."},
                    }
                ],
            }
        )
        self.assertIn("links_ready", text)
        self.assertIn("Book", text)
        self.assertIn("blocked", text)

    def test_parse_repl_plain_text_becomes_goal(self) -> None:
        command, values = cli.parse_repl_line("find the title")
        self.assertEqual(command, "goal")
        self.assertEqual(values, ["find the title"])

    def test_parse_repl_slash_command_uses_shell_words(self) -> None:
        command, values = cli.parse_repl_line('/start-url "https://example.com" "get title"')
        self.assertEqual(command, "start-url")
        self.assertEqual(values, ["https://example.com", "get title"])

    def test_autonomous_summary_includes_selected_result(self) -> None:
        text = cli.autonomous_summary(
            {
                "status": "select",
                "run_id": "run-1",
                "steps": 1,
                "target_id": "target-1",
                "log_path": "/tmp/run.jsonl",
                "final_decision": {
                    "action": "select",
                    "reason": "Exact match",
                    "selected_title": "A Concise History of Japan",
                    "selected_author": "Brett L. Walker",
                    "selected_language": "eng",
                    "extracted_answer": "Best English candidate found.",
                },
                "final_snapshot": {"page": {"url": "https://libgen.pw/search?query=x"}},
                "step_records": [{"execution": {"status": "select"}}],
            }
        )
        self.assertIn("selected: A Concise History of Japan", text)
        self.assertIn("Brett L. Walker", text)
        self.assertIn("final page:", text)


class CliCommandTests(unittest.TestCase):
    def test_goal_command_posts_autonomous_run(self) -> None:
        args = cli.build_parser().parse_args(["--base-url", "http://test", "goal", "--start-url", "https://example.com", "get", "title"])
        args.goal = " ".join(args.goal)
        with mock.patch.object(cli.BrowserClient, "post", return_value={"ok": True}) as post:
            result = cli.command_goal(args)
        self.assertTrue(result["ok"])
        post.assert_called_once()
        endpoint, payload = post.call_args.args[:2]
        self.assertEqual(endpoint, "/api/autonomous-run")
        self.assertEqual(payload["start_url"], "https://example.com")
        self.assertEqual(payload["goal"], "get title")

    def test_service_action_uses_vdesktop_script(self) -> None:
        fake = mock.Mock(returncode=0, stdout="ok\n", stderr="")
        with mock.patch("subprocess.run", return_value=fake) as run, redirect_stdout(StringIO()):
            code = cli.run_service_action("status", json_output=True)
        self.assertEqual(code, 0)
        self.assertIn("run-agentic-browser-vdesktop.sh", run.call_args.args[0][0])
        self.assertEqual(run.call_args.args[0][1], "status")


if __name__ == "__main__":
    unittest.main()
