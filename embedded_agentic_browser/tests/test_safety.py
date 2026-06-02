import unittest

from embedded_agentic_browser.safety import classify_url, normalize_url


class SafetyPolicyTests(unittest.TestCase):
    def test_normalize_adds_https(self) -> None:
        self.assertEqual(normalize_url("example.com/path"), "https://example.com/path")

    def test_allows_libgen_search_inspection(self) -> None:
        policy = classify_url("https://libgen.pw/search?query=x&collection=libgen")
        self.assertTrue(policy.allowed)
        self.assertTrue(policy.is_shadow_library)
        self.assertEqual(policy.mode, "shadow-library-inspection")

    def test_allows_libgen_links_inspection(self) -> None:
        policy = classify_url("https://libgen.pw/links/123")
        self.assertTrue(policy.allowed)
        self.assertTrue(policy.is_shadow_library)

    def test_allows_libgen_book_inspection(self) -> None:
        policy = classify_url("https://libgen.pw/book/123")
        self.assertTrue(policy.allowed)
        self.assertTrue(policy.is_shadow_library)

    def test_blocks_libgen_download_like_url(self) -> None:
        policy = classify_url("https://libgen.pw/download/book.pdf")
        self.assertFalse(policy.allowed)
        self.assertTrue(policy.looks_download)
        self.assertIn("Blocked", policy.stop_reason)

    def test_blocks_shadow_library_resolver_query(self) -> None:
        policy = classify_url("https://libgen.net/?l=token")
        self.assertFalse(policy.allowed)
        self.assertIn("resolver", policy.stop_reason)

    def test_blocks_non_public_binary_url(self) -> None:
        policy = classify_url("https://example.com/book.epub")
        self.assertFalse(policy.allowed)
        self.assertTrue(policy.looks_binary)

    def test_allows_public_domain_binary_url(self) -> None:
        policy = classify_url("https://zh.wikisource.org/wiki/Special:DownloadAsPdf/foo.pdf")
        self.assertTrue(policy.allowed)
        self.assertTrue(policy.is_public_domain)

    def test_design_tools_are_allowed(self) -> None:
        policy = classify_url("https://www.figma.com/file/example")
        self.assertTrue(policy.allowed)
        self.assertTrue(policy.is_design_tool)
        self.assertEqual(policy.mode, "design-tool")


if __name__ == "__main__":
    unittest.main()
