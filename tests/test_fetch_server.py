import json
import threading
import time
import unittest
import urllib.error
import urllib.request
from pathlib import Path
from tempfile import TemporaryDirectory

from file_ops_toolkit import cli
from file_ops_toolkit.server import make_server
from tests.test_fetch_core import touch, workbook_bytes


class ServerTests(unittest.TestCase):
    def setUp(self):
        self.tmp = TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        dist = self.root / "dist"
        dist.mkdir()
        (dist / "index.html").write_text("<html><head></head><body>ui</body></html>")
        (dist / "app.js").write_text("console.log(1)")
        (self.root / "secret.txt").write_text("secret")
        self.server = make_server(web_dist=dist)
        self.state = self.server.app_state
        threading.Thread(target=self.server.serve_forever, daemon=True).start()
        self.addCleanup(self.server.server_close)
        self.addCleanup(self.server.shutdown)
        self.base = f"http://127.0.0.1:{self.server.server_address[1]}"

    def call(self, path, method="GET", body=None, token=True, headers=None):
        request = urllib.request.Request(self.base + path, data=body, method=method, headers=headers or {})
        if token:
            request.add_header("X-Token", self.state.token)
        try:
            with urllib.request.urlopen(request) as resp:
                return resp.status, resp.read(), resp.headers
        except urllib.error.HTTPError as err:
            return err.code, err.read(), err.headers

    def test_refuses_to_bind_to_a_public_interface(self):
        with self.assertRaises(ValueError):
            make_server(host="0.0.0.0")

    def test_page_carries_the_token_and_api_without_it_is_refused(self):
        status, body, _ = self.call("/", token=False)
        self.assertEqual(status, 200)
        self.assertIn(f'content="{self.state.token}"'.encode(), body)
        for path in ("/api/status", "/api/fs?path=/"):
            self.assertEqual(self.call(path, token=False)[0], 401)
        self.assertEqual(self.call("/api/cancel", "POST", b"{}", token=False)[0], 401)
        request = urllib.request.Request(self.base + "/api/status", headers={"X-Token": "wrong"})
        with self.assertRaises(urllib.error.HTTPError) as ctx:
            urllib.request.urlopen(request)
        self.assertEqual(ctx.exception.code, 401)

    def test_a_foreign_host_header_is_refused(self):
        status, _, _ = self.call("/api/status", headers={"Host": "evil.example"})
        self.assertEqual(status, 403)

    def test_static_files_cannot_escape_the_ui_folder(self):
        self.assertEqual(self.call("/app.js", token=False)[0], 200)
        status, body, _ = self.call("/..%2fsecret.txt", token=False)
        self.assertNotIn(b"secret", body)
        status, body, _ = self.call("/../secret.txt", token=False)
        self.assertNotIn(b"secret", body)

    def test_upload_run_status_and_report(self):
        src = self.root / "srv" / "F1"
        touch(src / "a.xlsx", "data")
        rows = [(str(src), "a.xlsx"), (str(src), "nope.xlsx"), ("https://x.example/y", "z")]
        sheet = workbook_bytes(rows).getvalue()
        status, body, _ = self.call("/api/upload", "POST", sheet, headers={"X-File-Name": "C:\\fake\\list.xlsx"})
        info = json.loads(body)
        self.assertEqual((status, info["file"], len(info["rows"]), info["invalid"], info["folders"]),
                         (200, "list.xlsx", 3, 1, 1))
        dest = str(self.root / "out")
        self.assertEqual(self.call("/api/run", "POST", json.dumps({"dest": dest}).encode())[0], 200)
        for _ in range(100):
            snap = json.loads(self.call("/api/status")[1])
            if snap["state"] != "running":
                break
            time.sleep(0.05)
        self.assertEqual(snap["state"], "done")
        self.assertEqual(snap["counts"], {"copied": 1, "not_found": 1, "unsupported_link": 1})
        self.assertEqual((Path(dest) / "a.xlsx").read_text(), "data")
        status, report, headers = self.call("/api/report.csv?lang=ja")
        self.assertEqual(status, 200)
        self.assertTrue(report.startswith(b"\xef\xbb\xbf"))
        self.assertIn("コピーしました".encode(), report)

    def test_bad_inputs_get_codes_not_crashes(self):
        self.assertEqual(json.loads(self.call("/api/upload", "POST", b"junk")[1])["error"], "unreadable_workbook")
        self.assertEqual(self.call("/api/run", "POST", b'{"dest": "x"}')[0], 409)  # no list loaded
        sheet = workbook_bytes([(str(self.root), "a.txt")]).getvalue()
        self.call("/api/upload", "POST", sheet)
        self.assertEqual(self.call("/api/run", "POST", b'{"dest": ""}')[0], 400)
        bogus = json.dumps({"dest": str(self.root / "x"), "layout": "bogus"}).encode()
        self.assertEqual(self.call("/api/run", "POST", bogus)[0], 400)
        self.assertEqual(self.call("/api/run", "POST", b"not json")[0], 400)

    def test_folder_browser_lists_only_folders(self):
        (self.root / "d1").mkdir()
        touch(self.root / "file.txt")
        data = json.loads(self.call("/api/fs?path=" + urllib.request.quote(str(self.root)))[1])
        self.assertIn("d1", [e["name"] for e in data["entries"]])
        self.assertNotIn("file.txt", [e["name"] for e in data["entries"]])
        self.assertEqual(self.call("/api/fs?path=" + urllib.request.quote(str(self.root / "missing")))[0], 422)


class CliTests(unittest.TestCase):
    def test_run_copies_and_reports_in_the_chosen_language(self):
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            touch(root / "srv" / "a.txt", "hi")
            xlsx = root / "list.xlsx"
            xlsx.write_bytes(workbook_bytes([(str(root / "srv"), "a.txt"), (str(root / "srv"), "b.txt")]).getvalue())
            import contextlib
            import io
            out = io.StringIO()
            with contextlib.redirect_stdout(out):
                code = cli.main(["--lang", "ja", "run", str(xlsx), str(root / "dest"), "--report", str(root / "r.csv")])
            self.assertEqual(code, 1)  # one row was not found
            self.assertIn("要確認：1", out.getvalue())
            self.assertEqual((root / "dest" / "a.txt").read_text(), "hi")
            self.assertTrue((root / "r.csv").read_bytes().startswith(b"\xef\xbb\xbf"))

    def test_unreadable_workbook_exits_2(self):
        with TemporaryDirectory() as tmp:
            bad = Path(tmp) / "bad.xlsx"
            bad.write_text("nope")
            import contextlib
            import io
            err = io.StringIO()
            with contextlib.redirect_stderr(err):
                self.assertEqual(cli.main(["--lang", "en", "run", str(bad), tmp]), 2)
            self.assertIn("cannot be read", err.getvalue())


if __name__ == "__main__":
    unittest.main()
