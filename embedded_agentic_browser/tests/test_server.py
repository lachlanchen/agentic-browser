import unittest
from pathlib import Path
from unittest import mock

from embedded_agentic_browser import server
from embedded_agentic_browser.open_chrome_driver import Target


class ServerPolicyTests(unittest.TestCase):
    def test_internal_policy_for_about_blank(self) -> None:
        policy = server.policy_dict_for_url("about:blank")
        self.assertTrue(policy["allowed"])
        self.assertEqual(policy["mode"], "browser-internal")

    def test_guard_navigation_blocks_download(self) -> None:
        with self.assertRaises(server.EmbeddedBrowserError):
            server.guard_navigation("https://libgen.pw/download/book.pdf")

    def test_libgen_search_url_encodes_query(self) -> None:
        url = server.libgen_search_url("Pride and Prejudice Jane Austen")
        self.assertEqual(url, "https://libgen.pw/search?query=Pride%20and%20Prejudice%20Jane%20Austen&collection=libgen")

    def test_libgen_inspection_start_url_accepts_url_or_query(self) -> None:
        self.assertEqual(server.libgen_inspection_start_url("https://libgen.pw/book/123"), "https://libgen.pw/book/123")
        self.assertEqual(
            server.libgen_inspection_start_url("マーガレット ミッチェル"),
            "https://libgen.pw/search?query=%E3%83%9E%E3%83%BC%E3%82%AC%E3%83%AC%E3%83%83%E3%83%88%20%E3%83%9F%E3%83%83%E3%83%81%E3%82%A7%E3%83%AB&collection=libgen",
        )

    def test_expected_navigation_accepts_plus_normalized_query(self) -> None:
        expected = "https://libgen.pw/search?query=Pride%20and%20Prejudice&collection=libgen"
        actual = "https://libgen.pw/search?query=Pride+and+Prejudice&collection=libgen"
        self.assertTrue(server.is_expected_navigation(actual, expected))

    def test_stable_browser_selector_removes_vue_transition_classes(self) -> None:
        selector = "div.v-books-list.fade-enter-active:nth-of-type(2) > div.v-book-card:nth-of-type(3)"
        self.assertEqual(
            server.stable_browser_selector(selector),
            "div.v-books-list:nth-of-type(2) > div.v-book-card:nth-of-type(3)",
        )


class AutopilotTests(unittest.TestCase):
    def test_autopilot_stops_on_select(self) -> None:
        driver = mock.Mock()
        driver.target.return_value = mock.Mock(id="target-1")
        driver.snapshot.return_value = {"title": "Result", "url": "https://libgen.pw/search?query=x", "policy": {}}
        with mock.patch.object(
            server,
            "run_codex_decision",
            return_value={
                "action": "select",
                "selected_index": 1,
                "selected_title": "Book",
                "selected_author": "Author",
                "selected_language": "eng",
                "next_url": "",
                "scroll_delta_y": 0,
                "wait_seconds": 0,
                "safety_stop": False,
                "reason": "Exact candidate",
            },
        ), mock.patch.object(server, "append_action"):
            result = server.run_autopilot(driver, "target-1", "pick", 3, "model", "low")
        self.assertTrue(result["ok"])
        self.assertEqual(result["status"], "select")
        self.assertEqual(len(result["steps"]), 1)

    def test_autopilot_blocks_unsafe_open(self) -> None:
        driver = mock.Mock()
        driver.target.return_value = mock.Mock(id="target-1")
        driver.snapshot.return_value = {"title": "Result", "url": "https://libgen.pw/search?query=x", "policy": {}}
        with mock.patch.object(
            server,
            "run_codex_decision",
            return_value={
                "action": "open_url",
                "selected_index": None,
                "selected_title": "",
                "selected_author": "",
                "selected_language": "",
                "next_url": "https://libgen.pw/download/book.pdf",
                "scroll_delta_y": 0,
                "wait_seconds": 0,
                "safety_stop": False,
                "reason": "Unsafe test",
            },
        ), mock.patch.object(server, "append_action"):
            result = server.run_autopilot(driver, "target-1", "pick", 3, "model", "low")
        self.assertFalse(result["ok"])
        self.assertEqual(result["status"], "blocked")
        self.assertIn("blocked", result["steps"][0])

    def test_run_book_task_opens_search_and_autopilots(self) -> None:
        driver = mock.Mock()
        driver.new_tab.return_value = Target(
            id="target-1",
            title="",
            url="https://libgen.pw/search?query=x",
            websocket_url="ws://x",
        )
        page = mock.Mock()
        driver.page.return_value = page
        with mock.patch.object(server, "wait_for_navigation", return_value={"url": "https://libgen.pw/search?query=x"}), \
             mock.patch.object(server, "wait_for_dynamic_results", return_value={"cards": [{"title": "Book"}]}), \
             mock.patch.object(server, "run_autopilot", return_value={"ok": True, "status": "select", "steps": []}), \
             mock.patch.object(server, "append_action"):
            result = server.run_book_task(driver, "Pride and Prejudice", "libgen", "", 3, "model", "low")
        self.assertTrue(result["ok"])
        self.assertEqual(result["source"], "libgen")
        self.assertIn("Pride%20and%20Prejudice", result["url"])
        driver.new_tab.assert_called_once()
        page.bring_to_front.assert_called_once()

    def test_observe_page_returns_snapshot_and_viewport(self) -> None:
        driver = mock.Mock()
        driver.target.return_value = mock.Mock(id="target-1")
        driver.snapshot.return_value = {"target_id": "target-1", "url": "about:blank", "interactive": [{"selector": "button"}]}
        driver.capture.return_value = {"target_id": "target-1", "metrics": {"url": "about:blank"}, "screenshot": "data:image/jpeg;base64,x"}
        result = server.observe_page(driver, None, quality=55)
        self.assertEqual(result["target_id"], "target-1")
        self.assertIn("snapshot", result)
        self.assertIn("viewport", result)
        self.assertEqual(result["snapshot"]["interactive"][0]["selector"], "button")
        driver.capture.assert_called_once_with("target-1", quality=55)

    def test_handle_download_uses_guarded_downloader(self) -> None:
        handler = object.__new__(server.EmbeddedBrowserHandler)
        with mock.patch.object(server, "download_public_file", return_value={"ok": True, "path": "/tmp/book.txt"}) as download, \
             mock.patch.object(server, "append_action") as append_action, \
             mock.patch.object(handler, "send_json") as send_json:
            handler.handle_download({"url": "https://www.gutenberg.org/files/book.txt", "filename": ""})
        download.assert_called_once()
        append_action.assert_called_once()
        send_json.assert_called_once_with({"ok": True, "path": "/tmp/book.txt"})

    def test_handle_autonomous_run_uses_process_agent(self) -> None:
        handler = object.__new__(server.EmbeddedBrowserHandler)
        handler.server = mock.Mock(
            driver=mock.Mock(port=9333, profile_dir=Path("/tmp/profile")),
            model="gpt-test",
            reasoning_effort="low",
        )
        summary = {
            "ok": True,
            "status": "download",
            "target_id": "target-1",
            "steps": 2,
            "log_path": "/tmp/run.jsonl",
        }
        with mock.patch("embedded_agentic_browser.agent.run_agent", return_value=summary) as run_agent, \
             mock.patch.object(server, "append_action") as append_action, \
             mock.patch.object(handler, "send_json") as send_json:
            handler.handle_autonomous_run(
                {
                    "goal": "Download a public-domain book",
                    "start_url": "https://www.gutenberg.org/ebooks/1342",
                    "max_steps": 4,
                    "make_plan": True,
                }
            )
        config = run_agent.call_args.args[0]
        self.assertEqual(config.goal, "Download a public-domain book")
        self.assertEqual(config.browser_port, 9333)
        self.assertEqual(config.max_steps, 4)
        self.assertTrue(config.make_plan)
        append_action.assert_called_once()
        send_json.assert_called_once_with(summary)

    def test_handle_libgen_inspect_uses_safe_inspection_flow(self) -> None:
        handler = object.__new__(server.EmbeddedBrowserHandler)
        handler.server = mock.Mock(driver=mock.Mock(), model="gpt-test", reasoning_effort="low")
        result = {"ok": True, "status": "links_ready"}
        with mock.patch.object(server, "open_libgen_link_inspection", return_value=result) as inspect, \
             mock.patch.object(handler, "send_json") as send_json:
            handler.handle_libgen_inspect({"query_or_url": "マーガレット ミッチェル", "goal": "pick best"})
        inspect.assert_called_once_with(handler.server.driver, "マーガレット ミッチェル", "pick best", "gpt-test", "low")
        send_json.assert_called_once_with(result)

    def test_libgen_inspect_executes_scroll_then_select(self) -> None:
        driver = mock.Mock()
        driver.new_tab.return_value = Target(
            id="target-1",
            title="",
            url="https://libgen.pw/search?query=x&collection=libgen",
            websocket_url="ws://x",
        )
        page = mock.Mock()
        driver.page.return_value = page
        initial_snapshot = {
            "url": "https://libgen.pw/search?query=x&collection=libgen",
            "cards": [],
            "policy": {},
        }
        selected_snapshot = {
            "url": "https://libgen.pw/search?query=x&collection=libgen",
            "cards": [
                {
                    "index": 0,
                    "title": "A Concise History of Japan",
                    "authors": ["Brett L. Walker"],
                    "lang": "eng",
                    "file": "epub, 0.21 MB",
                    "file_selector": ".v-book-card__link",
                }
            ],
            "policy": {},
        }
        with mock.patch.object(server, "wait_for_navigation", return_value=initial_snapshot), \
             mock.patch.object(server, "wait_for_dynamic_results", side_effect=[initial_snapshot, selected_snapshot]), \
             mock.patch.object(
                 server,
                 "run_codex_decision",
                 side_effect=[
                     {
                         "action": "scroll",
                         "selected_index": None,
                         "scroll_delta_y": 700,
                         "wait_seconds": 0,
                         "reason": "Need visible results",
                     },
                     {
                         "action": "select",
                         "selected_index": 0,
                         "scroll_delta_y": 0,
                         "wait_seconds": 0,
                         "reason": "Exact match",
                     },
                 ],
             ), \
             mock.patch.object(
                 server,
                 "wait_for_links_page",
                 return_value={"url": "https://libgen.pw/links/1", "links": [], "policy": {}},
             ), \
             mock.patch.object(server, "append_action"):
            result = server.open_libgen_link_inspection(driver, "x", "", "model", "low")

        self.assertEqual(result["status"], "links_ready")
        self.assertEqual(result["selected_card"]["title"], "A Concise History of Japan")
        self.assertEqual([step["action"] for step in result["inspection_steps"]], ["scroll", "select"])
        driver.action.assert_any_call("target-1", "scroll", {"delta_y": 700})
        driver.action.assert_any_call("target-1", "click_selector", {"selector": ".v-book-card__link"})


if __name__ == "__main__":
    unittest.main()
