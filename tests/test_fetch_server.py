import http.client
import json
import threading
import time
import unittest
import urllib.error
import urllib.request
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import mock

from file_ops_toolkit import cli
from file_ops_toolkit.runner import JobRun
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

    def test_a_destination_inside_a_source_is_refused_and_since_must_be_a_number(self):
        src = self.root / "srv"
        touch(src / "a.txt")
        self.call("/api/upload", "POST", workbook_bytes([(str(src), "a.txt")]).getvalue())
        status, body, _ = self.call("/api/run", "POST", json.dumps({"dest": str(src / "out")}).encode())
        self.assertEqual((status, json.loads(body)["error"]), (422, "dest_inside_source"))
        self.assertFalse((src / "out").exists())
        self.assertEqual(self.call("/api/status?since=abc")[0], 400)

    def test_windows_spellings_in_a_static_path_are_refused(self):
        self.assertEqual(self.call("/C:/x", token=False)[0], 403)
        connection = http.client.HTTPConnection("127.0.0.1", self.server.server_address[1])
        connection.request("GET", "/\\evilhost\\share\\x")  # a raw backslash, as a non-browser client may send
        self.assertEqual(connection.getresponse().status, 403)
        connection.close()

    def test_a_started_run_cannot_be_replaced_by_an_upload(self):
        entered, release, finish = threading.Event(), threading.Event(), threading.Event()
        real_start = JobRun.start

        def slow_start(run):  # holds the moment between "run created" and "run running" open
            entered.set()
            release.wait(10)
            real_start(run)

        src = self.root / "srv"
        touch(src / "a.txt")
        sheet = workbook_bytes([(str(src), "a.txt")]).getvalue()
        self.call("/api/upload", "POST", sheet)
        outcome = {}
        with mock.patch.object(JobRun, "start", slow_start), \
                mock.patch("file_ops_toolkit.runner.run_job", lambda *a, **k: finish.wait(10)):
            starter = threading.Thread(target=lambda: outcome.update(
                run=self.call("/api/run", "POST", json.dumps({"dest": str(self.root / "out")}).encode())))
            starter.start()
            self.assertTrue(entered.wait(10))
            uploader = threading.Thread(target=lambda: outcome.update(up=self.call("/api/upload", "POST", sheet)))
            uploader.start()
            time.sleep(0.3)
            release.set()
            starter.join(10)
            uploader.join(10)
            self.assertEqual(outcome["run"][0], 200)
            self.assertEqual((outcome["up"][0], json.loads(outcome["up"][1])["error"]), (409, "run_in_progress"))
            self.assertEqual(self.call("/api/run", "POST", json.dumps({"dest": str(self.root / "o2")}).encode())[0], 409)
            finish.set()
            self.state.run.join(10)

    def test_the_csv_follows_the_requested_language_and_neutralises_formulas(self):
        src = self.root / "srv"
        touch(src / "@cmd().txt")
        self.call("/api/upload", "POST", workbook_bytes([(str(src), "@cmd().txt")]).getvalue())
        self.call("/api/run", "POST", json.dumps({"dest": str(self.root / "out")}).encode())
        self.state.run.join(10)
        report = self.call("/api/report.csv?lang=vi")[1].decode("utf-8-sig")
        self.assertIn("Đã sao chép", report)
        self.assertIn("'@cmd().txt", report)
        self.assertNotIn(",@cmd()", report)

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
