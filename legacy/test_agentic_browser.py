#!/usr/bin/env python3
import unittest
from unittest import mock

import agentic_browser as ab


class HostPolicyTests(unittest.TestCase):
    def test_allows_libgen_search_and_detail(self) -> None:
        self.assertTrue(ab.host_policy("https://libgen.pw/search?query=x&collection=libgen")["allowed"])
        self.assertTrue(ab.host_policy("https://libgen.pw/links/123")["allowed"])

    def test_blocks_libgen_download_like_urls(self) -> None:
        policy = ab.host_policy("https://libgen.pw/download/example.pdf")
        self.assertFalse(policy["allowed"])
        self.assertTrue(policy["is_shadow_library"])
        self.assertTrue(policy["looks_download"])

    def test_blocks_non_public_direct_binary(self) -> None:
        policy = ab.host_policy("https://example.com/book.epub")
        self.assertFalse(policy["allowed"])

    def test_allows_public_domain_binary_hosts(self) -> None:
        policy = ab.host_policy("https://dl.ndl.go.jp/api/iiif/123/R0001/full/1000,/0/default.jpg")
        self.assertTrue(policy["allowed"])
        self.assertTrue(policy["is_public_domain"])


class AutopilotTests(unittest.TestCase):
    def test_autopilot_stops_on_select(self) -> None:
        with mock.patch.object(ab, "active_or_first_target", return_value="target-1"), \
             mock.patch.object(ab, "page_snapshot", return_value={"title": "Libgen", "url": "https://libgen.pw/search?query=x", "policy": {}}), \
             mock.patch.object(
                 ab,
                 "run_codex_autopilot_step",
                 return_value={
                     "action": "select",
                     "selected_index": 2,
                     "selected_title": "Book",
                     "selected_author": "Author",
                     "selected_language": "eng",
                     "next_url": "",
                     "scroll_delta_y": 0,
                     "wait_seconds": 0,
                     "safety_stop": False,
                     "reason": "Exact match",
                 },
             ), \
             mock.patch.object(ab, "append_action"):
            result = ab.run_autopilot(9223, "target-1", "pick book", 3, "model", "low")
        self.assertTrue(result["ok"])
        self.assertEqual(result["status"], "select")
        self.assertEqual(len(result["steps"]), 1)

    def test_autopilot_blocks_unsafe_next_url(self) -> None:
        with mock.patch.object(ab, "active_or_first_target", return_value="target-1"), \
             mock.patch.object(ab, "page_snapshot", return_value={"title": "Libgen", "url": "https://libgen.pw/search?query=x", "policy": {}}), \
             mock.patch.object(
                 ab,
                 "run_codex_autopilot_step",
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
                     "reason": "Try unsafe link",
                 },
             ), \
             mock.patch.object(ab, "append_action"):
            result = ab.run_autopilot(9223, "target-1", "pick book", 3, "model", "low")
        self.assertFalse(result["ok"])
        self.assertEqual(result["status"], "blocked")
        self.assertIn("blocked", result["steps"][0])


if __name__ == "__main__":
    unittest.main()
