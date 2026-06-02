import tempfile
import unittest
from pathlib import Path
from unittest import mock

from embedded_agentic_browser import downloader


class DownloaderPolicyTests(unittest.TestCase):
    def test_blocks_shadow_library_download(self) -> None:
        with self.assertRaises(downloader.DownloadError):
            downloader.ensure_download_allowed("https://libgen.pw/download/book.pdf")

    def test_blocks_regular_host_downloads(self) -> None:
        with self.assertRaises(downloader.DownloadError):
            downloader.ensure_download_allowed("https://example.com/book.pdf")

    def test_allows_public_domain_downloads(self) -> None:
        url = downloader.ensure_download_allowed("https://www.gutenberg.org/ebooks/1342.epub3.images")
        self.assertEqual(url, "https://www.gutenberg.org/ebooks/1342.epub3.images")


class DownloaderFilenameTests(unittest.TestCase):
    def test_sanitize_filename(self) -> None:
        self.assertEqual(downloader.sanitize_filename("../Pride:Prejudice?.epub"), "Pride_Prejudice_.epub")

    def test_choose_filename_from_content_disposition(self) -> None:
        headers = {"Content-Disposition": 'attachment; filename="book.epub"', "Content-Type": "application/epub+zip"}
        self.assertEqual(downloader.choose_filename("https://example.org/file", headers), "book.epub")

    def test_unique_path_adds_suffix(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            (root / "book.txt").write_text("x", encoding="utf-8")
            self.assertEqual(downloader.unique_path(root, "book.txt").name, "book-2.txt")


class DownloaderTransferTests(unittest.TestCase):
    def test_download_public_file_uses_guard_and_unique_path(self) -> None:
        class FakeResponse:
            headers = {"Content-Type": "text/plain", "Content-Length": "11"}

            def __enter__(self):
                return self

            def __exit__(self, *_args):
                return False

            def read(self, _size):
                if getattr(self, "done", False):
                    return b""
                self.done = True
                return b"hello world"

            def geturl(self):
                return "https://www.gutenberg.org/files/test.txt"

        with tempfile.TemporaryDirectory() as temp_dir, \
             mock.patch("urllib.request.urlopen", return_value=FakeResponse()):
            result = downloader.download_public_file(
                "https://www.gutenberg.org/files/test.txt",
                Path(temp_dir),
            )
        self.assertTrue(result["ok"])
        self.assertEqual(result["filename"], "test.txt")
        self.assertEqual(result["bytes"], 11)


if __name__ == "__main__":
    unittest.main()
