import json
import pathlib
import subprocess
import tempfile
import unittest

from scripts.verify_api_and_file_coverage import (
    check_glibc_manual_coverage,
    check_musl_file_coverage,
    check_posix_coverage,
    load_glibc_symbols,
    load_musl_files,
)


class VerifyApiAndFileCoverageTests(unittest.TestCase):
    def setUp(self) -> None:
        self.root = pathlib.Path(__file__).resolve().parent / "fixtures"
        self.glibc_csv = self.root / "glibc_api_sample.csv"
        self.musl_csv = self.root / "musl_files_sample.csv"
        self.glibc_manual_root = self.root / "glibc_manual"
        self.posix_root = self.root / "posix"
        self.musl_root = self.root / "musl_src"

    def test_load_glibc_symbols_reads_first_column(self) -> None:
        symbols = load_glibc_symbols(self.glibc_csv)
        self.assertEqual(symbols, ["basename", "pthread_detach", "accept4", "missing_symbol"])

    def test_check_glibc_manual_coverage_classifies_entry_anchor_and_mention(self) -> None:
        result = check_glibc_manual_coverage(
            ["basename", "pthread_detach", "accept4", "missing_symbol"],
            self.glibc_manual_root,
        )
        status_by_symbol = {item["symbol"]: item["glibc_manual_status"] for item in result}
        self.assertEqual(status_by_symbol["basename"], "entry")
        self.assertEqual(status_by_symbol["pthread_detach"], "anchor")
        self.assertEqual(status_by_symbol["accept4"], "mention")
        self.assertEqual(status_by_symbol["missing_symbol"], "missing")

    def test_check_glibc_manual_keeps_entry_evidence_when_mentions_appear_first(self) -> None:
        result = check_glibc_manual_coverage(["abort"], self.glibc_manual_root)
        self.assertEqual(result[0]["glibc_manual_status"], "entry")
        self.assertTrue(any(hit["kind"] == "entry" for hit in result[0]["glibc_manual_hits"]))

    def test_check_posix_coverage_uses_official_function_pages(self) -> None:
        result = check_posix_coverage(
            ["basename", "pthread_detach", "accept4"],
            self.posix_root,
        )
        status_by_symbol = {item["symbol"]: item["posix_status"] for item in result}
        self.assertEqual(status_by_symbol["basename"], "found")
        self.assertEqual(status_by_symbol["pthread_detach"], "found")
        self.assertEqual(status_by_symbol["accept4"], "missing")

    def test_check_musl_file_coverage_reports_existing_and_missing(self) -> None:
        paths = load_musl_files(self.musl_csv)
        result = check_musl_file_coverage(paths, self.musl_root)
        exists_by_path = {item["path"]: item["exists"] for item in result}
        self.assertTrue(exists_by_path["include/pthread.h"])
        self.assertTrue(exists_by_path["src/thread/pthread_detach.c"])
        self.assertFalse(exists_by_path["src/missing/not_found.c"])

    def test_cli_writes_json_report(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            output_path = pathlib.Path(temp_dir) / "report.json"
            completed = subprocess.run(
                [
                    "python3",
                    "scripts/verify_api_and_file_coverage.py",
                    "--glibc-csv",
                    str(self.glibc_csv),
                    "--glibc-manual-root",
                    str(self.glibc_manual_root),
                    "--posix-root",
                    str(self.posix_root),
                    "--musl-files-csv",
                    str(self.musl_csv),
                    "--musl-root",
                    str(self.musl_root),
                    "--output",
                    str(output_path),
                ],
                cwd=pathlib.Path(__file__).resolve().parents[1],
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertEqual(completed.returncode, 0, completed.stderr)
            report = json.loads(output_path.read_text(encoding="utf-8"))
            self.assertEqual(report["summary"]["glibc_symbols_total"], 4)
            self.assertEqual(report["summary"]["musl_files_missing"], 1)


if __name__ == "__main__":
    unittest.main()
