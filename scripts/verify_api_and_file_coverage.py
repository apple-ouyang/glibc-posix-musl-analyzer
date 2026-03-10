#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
import json
import re
from collections import Counter
from pathlib import Path
from typing import Iterable

TOKEN_BOUNDARY_TEMPLATE = r"(?<![A-Za-z0-9_]){token}(?![A-Za-z0-9_])"
ENTRY_MARKERS = ("@deftypefun", "@deftypefunx", "@deftypefn", "@deftp", "@defvr", "@defvar")
ANCHOR_MARKER = "@c"


class VerificationError(Exception):
    pass


def _require_path(path: Path, kind: str) -> Path:
    if not path.exists():
        raise VerificationError(f"{kind}不存在: {path}")
    return path


def _read_csv_first_column(csv_path: Path) -> list[str]:
    _require_path(csv_path, "CSV文件")
    with csv_path.open(newline="", encoding="utf-8-sig") as handle:
        reader = csv.reader(handle)
        rows = [row[0].strip() for row in reader if row and row[0].strip()]
    if len(rows) <= 1:
        return []
    return rows[1:]


def load_glibc_symbols(csv_path: Path | str) -> list[str]:
    return _read_csv_first_column(Path(csv_path))


def load_musl_files(csv_path: Path | str) -> list[str]:
    return _read_csv_first_column(Path(csv_path))


def _compile_token_pattern(symbol: str) -> re.Pattern[str]:
    return re.compile(TOKEN_BOUNDARY_TEMPLATE.format(token=re.escape(symbol)))


def _iter_glibc_manual_files(manual_root: Path) -> Iterable[Path]:
    _require_path(manual_root, "glibc manual目录")
    yield from sorted(path for path in manual_root.rglob("*") if path.suffix in {".texi", ".texinfo"})


def check_glibc_manual_coverage(symbols: list[str], manual_root: Path | str, max_hits: int = 5) -> list[dict[str, object]]:
    manual_root_path = Path(manual_root)
    files = list(_iter_glibc_manual_files(manual_root_path))
    results: list[dict[str, object]] = []
    for symbol in symbols:
        token_pattern = _compile_token_pattern(symbol)
        categorized_hits: dict[str, list[dict[str, object]]] = {
            "entry": [],
            "anchor": [],
            "mention": [],
        }
        best_status = "missing"
        for file_path in files:
            with file_path.open(encoding="utf-8", errors="ignore") as handle:
                for line_no, line in enumerate(handle, start=1):
                    if not token_pattern.search(line):
                        continue
                    stripped = line.strip()
                    if any(marker in stripped for marker in ENTRY_MARKERS):
                        hit_kind = "entry"
                        best_status = "entry"
                    elif stripped.startswith(f"{ANCHOR_MARKER} {symbol}") or stripped == f"{ANCHOR_MARKER} {symbol}":
                        hit_kind = "anchor"
                        if best_status != "entry":
                            best_status = "anchor"
                    else:
                        hit_kind = "mention"
                        if best_status == "missing":
                            best_status = "mention"
                    bucket = categorized_hits[hit_kind]
                    if len(bucket) < max_hits:
                        bucket.append(
                            {
                                "path": str(file_path),
                                "line": line_no,
                                "kind": hit_kind,
                                "text": stripped,
                            }
                        )
        ordered_hits = (
            categorized_hits["entry"]
            + categorized_hits["anchor"]
            + categorized_hits["mention"]
        )[:max_hits]
        results.append(
            {
                "symbol": symbol,
                "glibc_manual_status": best_status,
                "glibc_manual_hits": ordered_hits,
            }
        )
    return results


def check_posix_coverage(symbols: list[str], posix_root: Path | str) -> list[dict[str, object]]:
    posix_root_path = _require_path(Path(posix_root), "POSIX根目录")
    results: list[dict[str, object]] = []
    for symbol in symbols:
        exact_paths = sorted(posix_root_path.rglob(f"{symbol}.html"))
        if exact_paths:
            results.append(
                {
                    "symbol": symbol,
                    "posix_status": "found",
                    "posix_path": str(exact_paths[0]),
                }
            )
            continue
        results.append(
            {
                "symbol": symbol,
                "posix_status": "missing",
                "posix_path": "",
            }
        )
    return results


def check_musl_file_coverage(paths: list[str], musl_root: Path | str) -> list[dict[str, object]]:
    musl_root_path = _require_path(Path(musl_root), "musl源码目录")
    results: list[dict[str, object]] = []
    for relative_path in paths:
        resolved_path = musl_root_path / relative_path
        results.append(
            {
                "path": relative_path,
                "exists": resolved_path.exists(),
                "resolved_path": str(resolved_path),
            }
        )
    return results


def build_report(
    glibc_symbols: list[str],
    glibc_manual_results: list[dict[str, object]],
    posix_results: list[dict[str, object]],
    musl_file_results: list[dict[str, object]],
) -> dict[str, object]:
    by_symbol = {item["symbol"]: dict(item) for item in glibc_manual_results}
    for item in posix_results:
        by_symbol[item["symbol"]].update(item)

    glibc_counter = Counter(item["glibc_manual_status"] for item in glibc_manual_results)
    posix_counter = Counter(item["posix_status"] for item in posix_results)
    musl_existing = sum(1 for item in musl_file_results if item["exists"])
    musl_missing = len(musl_file_results) - musl_existing

    return {
        "summary": {
            "glibc_symbols_total": len(glibc_symbols),
            "glibc_manual_entry": glibc_counter["entry"],
            "glibc_manual_anchor": glibc_counter["anchor"],
            "glibc_manual_mention": glibc_counter["mention"],
            "glibc_manual_missing": glibc_counter["missing"],
            "posix_found": posix_counter["found"],
            "posix_missing": posix_counter["missing"],
            "musl_files_total": len(musl_file_results),
            "musl_files_existing": musl_existing,
            "musl_files_missing": musl_missing,
        },
        "symbols": [by_symbol[symbol] for symbol in glibc_symbols],
        "musl_files": musl_file_results,
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="验证 glibc 接口在 manual / POSIX 中是否存在，以及 musl 文件是否存在。")
    parser.add_argument("--glibc-csv", default="glibc_API_analyse.csv")
    parser.add_argument("--glibc-manual-root", default="glibc/glibc-2.34/manual")
    parser.add_argument("--posix-root", default="out/posix/issue8/extracted/susv5-html")
    parser.add_argument("--musl-files-csv", default="musl_file_modify_analyse.csv")
    parser.add_argument("--musl-root", default="musl/musl-1.2.4")
    parser.add_argument("--output", default="out/validation/api_and_file_coverage.json")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    glibc_symbols = load_glibc_symbols(args.glibc_csv)
    musl_files = load_musl_files(args.musl_files_csv)
    glibc_manual_results = check_glibc_manual_coverage(glibc_symbols, args.glibc_manual_root)
    posix_results = check_posix_coverage(glibc_symbols, args.posix_root)
    musl_file_results = check_musl_file_coverage(musl_files, args.musl_root)
    report = build_report(glibc_symbols, glibc_manual_results, posix_results, musl_file_results)

    output_path = Path(args.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")

    summary = report["summary"]
    print(
        "glibc symbols={total}, entry={entry}, anchor={anchor}, mention={mention}, missing={missing}; "
        "POSIX found={posix_found}, missing={posix_missing}; "
        "musl files existing={musl_existing}, missing={musl_missing}".format(
            total=summary["glibc_symbols_total"],
            entry=summary["glibc_manual_entry"],
            anchor=summary["glibc_manual_anchor"],
            mention=summary["glibc_manual_mention"],
            missing=summary["glibc_manual_missing"],
            posix_found=summary["posix_found"],
            posix_missing=summary["posix_missing"],
            musl_existing=summary["musl_files_existing"],
            musl_missing=summary["musl_files_missing"],
        )
    )
    print(f"report: {output_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
