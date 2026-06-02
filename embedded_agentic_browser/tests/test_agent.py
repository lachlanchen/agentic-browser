import unittest
from unittest import mock

from embedded_agentic_browser import agent


class AgentExecutionTests(unittest.TestCase):
    def test_open_url_blocks_unsafe_download(self) -> None:
        driver = mock.Mock()
        decision = {
            "action": "open_url",
            "url": "https://libgen.pw/download/book.pdf",
        }
        with self.assertRaises(agent.AgentRuntimeError):
            agent.execute_agent_action(driver, "target-1", decision)
        driver.action.assert_not_called()

    def test_click_selector_executes_driver_action(self) -> None:
        driver = mock.Mock()
        driver.action.return_value = {"ok": True}
        with mock.patch.object(agent, "observe", return_value={"policy": {"is_shadow_library": False}}):
            result = agent.execute_agent_action(
                driver,
                "target-1",
                {"action": "click_selector", "selector": "#search"},
            )
        self.assertFalse(result["terminal"])
        driver.action.assert_called_once_with("target-1", "click_selector", {"selector": "#search"})

    def test_type_selector_executes_driver_action(self) -> None:
        driver = mock.Mock()
        driver.action.return_value = {"ok": True}
        result = agent.execute_agent_action(
            driver,
            "target-1",
            {"action": "type_selector", "selector": "input", "text": "Kokoro", "clear_first": True},
        )
        self.assertFalse(result["terminal"])
        driver.action.assert_called_once_with(
            "target-1",
            "type_selector",
            {"selector": "input", "text": "Kokoro", "clear_first": True},
        )

    def test_terminal_action_stops_without_driver_call(self) -> None:
        driver = mock.Mock()
        result = agent.execute_agent_action(driver, "target-1", {"action": "extract"})
        self.assertTrue(result["terminal"])
        self.assertEqual(result["status"], "extract")
        driver.action.assert_not_called()

    def test_download_url_terminal_action(self) -> None:
        driver = mock.Mock()
        with mock.patch.object(agent, "download_public_file", return_value={"ok": True, "path": "/tmp/book.txt"}):
            result = agent.execute_agent_action(
                driver,
                "target-1",
                {"action": "download_url", "url": "https://www.gutenberg.org/files/book.txt", "filename": ""},
            )
        self.assertTrue(result["terminal"])
        self.assertEqual(result["status"], "download")
        driver.action.assert_not_called()

    def test_click_text_blocks_shadow_library_mirror(self) -> None:
        driver = mock.Mock()
        with mock.patch.object(
            agent,
            "observe",
            return_value={
                "url": "https://libgen.pw/links/123",
                "policy": {"is_shadow_library": True},
                "links": [{"text": "Libgen", "href": "https://libgen.net/?l=token"}],
            },
        ):
            with self.assertRaises(agent.AgentRuntimeError):
                agent.execute_agent_action(driver, "target-1", {"action": "click_text", "text": "Libgen"})
        driver.action.assert_not_called()

    def test_click_selector_allows_shadow_library_in_page_file_link(self) -> None:
        driver = mock.Mock()
        driver.action.return_value = {"ok": True}
        with mock.patch.object(
            agent,
            "observe",
            return_value={
                "url": "https://libgen.pw/search?query=x",
                "policy": {"is_shadow_library": True},
                "interactive": [{"selector": ".v-book-card__link", "text": "epub, 0.06 MB", "href": ""}],
                "links": [],
            },
        ):
            result = agent.execute_agent_action(
                driver,
                "target-1",
                {"action": "click_selector", "selector": ".v-book-card__link"},
            )
        self.assertFalse(result["terminal"])
        driver.action.assert_called_once()


class AgentPromptTests(unittest.TestCase):
    def test_prompt_includes_interactive_selectors(self) -> None:
        snapshot = {
            "title": "Example",
            "url": "https://example.com",
            "policy": {"allowed": True},
            "interactive": [{"selector": "input[name=q]", "text": "Search"}],
            "textSample": ["Search"],
        }
        prompt = agent.build_agent_prompt("search", snapshot, [], 1)
        self.assertIn("input[name=q]", prompt)
        self.assertIn("type_selector", prompt)
        self.assertIn("download_url", prompt)

    def test_prompt_includes_plan_context(self) -> None:
        snapshot = {
            "title": "Example",
            "url": "https://example.com",
            "policy": {"allowed": True},
            "textSample": ["Search"],
        }
        prompt = agent.build_agent_prompt(
            "download a public-domain book",
            snapshot,
            [],
            1,
            plan={
                "plan": ["Open the public-domain source page.", "Use a visible download link."],
                "risk_notes": "Avoid blocked domains.",
                "done_signal": "Stop after the file is saved.",
            },
        )
        self.assertIn("Open the public-domain source page.", prompt)
        self.assertIn("Follow the plan", prompt)

    def test_plan_prompt_mentions_done_signal(self) -> None:
        prompt = agent.build_plan_prompt("download Pride and Prejudice", "https://www.gutenberg.org/ebooks/1342")
        self.assertIn("download Pride and Prejudice", prompt)
        self.assertIn("how the agent should know it is done", prompt)


if __name__ == "__main__":
    unittest.main()
