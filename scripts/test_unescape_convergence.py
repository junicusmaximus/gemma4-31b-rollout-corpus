"""Synthetic regression tests; no competition text or live corpus is used."""
import json
from pathlib import Path
import tempfile
import unittest

import check_unescape_convergence as G


def escaped_x(depth):
    if depth == 0:
        return "x"
    text = r"\u0078"
    for _ in range(depth - 1):
        text = text.replace("\\", r"\u005c")
    return text


class ConvergenceGateTests(unittest.TestCase):
    def test_depth_zero_to_six_converges(self):
        for depth in range(7):
            self.assertTrue(G.converged(escaped_x(depth)), depth)

    def test_depth_seven_is_rejected(self):
        self.assertFalse(G.converged(escaped_x(7)))

    def test_depth_eight_is_rejected(self):
        self.assertFalse(G.converged(escaped_x(8)))

    def test_nested_keys_and_values_are_checked(self):
        values = list(G.strings_of({escaped_x(7): ["plain", {"key": escaped_x(8)}]}))
        self.assertEqual(len(values), 4)
        self.assertEqual(sum(not G.converged(value) for value in values), 2)

    def test_valid_input_and_duplicate_roots(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "trace.json"
            path.write_text(json.dumps({"a": escaped_x(6)}))
            result = G.inspect([path, Path(tmp)])
            self.assertTrue(result["ok"])
            self.assertEqual(result["files"], 1)

    def test_nonconvergence_is_a_failed_result(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "trace.json"
            path.write_text(json.dumps({"a": escaped_x(7)}))
            result = G.inspect([path])
            self.assertFalse(result["ok"])
            self.assertEqual(result["nonconverged_strings"], 1)

    def test_invalid_json_is_a_failed_result(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "trace.json"
            path.write_text("{")
            self.assertFalse(G.inspect([path])["ok"])

    def test_missing_or_empty_input_is_a_failed_result(self):
        with tempfile.TemporaryDirectory() as tmp:
            self.assertFalse(G.inspect([Path(tmp) / "missing"])["ok"])
            self.assertFalse(G.inspect([Path(tmp)])["ok"])

    def test_empty_root_is_rejected_alongside_valid_root(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "trace.json"
            path.write_text("{}")
            empty = Path(tmp) / "empty"
            empty.mkdir()
            self.assertFalse(G.inspect([path, empty])["ok"])

    def test_report_refuses_overwrite(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "trace.json"
            path.write_text("{}")
            report = Path(tmp) / "report.json"
            report.write_text("original")
            with self.assertRaises(FileExistsError):
                G.main(["--traces", str(path), "--report", str(report)])
            self.assertEqual(report.read_text(), "original")


if __name__ == "__main__":
    unittest.main()
