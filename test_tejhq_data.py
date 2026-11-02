from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq

from tejhq_data import (
    REPO_ID,
    build_symbol_chains,
    get_dataset_revision,
    load_adjusted_frames,
    map_symbol_chains,
)


class TejHQAdjustedLoaderTests(unittest.TestCase):
    def _write_history(self, path, rows):
        frame = pd.DataFrame(rows, columns=["isin", "symbol", "valid_from", "valid_to"])
        pq.write_table(pa.Table.from_pandas(frame, preserve_index=False), path)

    def _write_prices(self, path, rows):
        columns = [
            "date", "symbol", "series", "isin", "open", "high", "low", "close",
            "volume", "turnover", "adj_factor_cumulative", "adj_close",
        ]
        frame = pd.DataFrame(rows, columns=columns)
        frame["date"] = pd.to_datetime(frame["date"]).dt.date
        pq.write_table(pa.Table.from_pandas(frame, preserve_index=False), path)

    def _mock_download(self, history_path, price_path):
        def fake_download(repo_id, repo_type, filename, cache_dir, force_download, revision):
            return str(history_path if filename == "symbol_history/nse.parquet" else price_path)
        return patch("huggingface_hub.hf_hub_download", side_effect=fake_download)

    def test_adjusts_ohlc_but_preserves_raw_volume_and_turnover(self):
        with tempfile.TemporaryDirectory() as tmp:
            history_path = Path(tmp) / "symbol_history.parquet"
            price_path = Path(tmp) / "nse_2026.parquet"
            self._write_history(history_path, [
                ("INE000A01001", "ABC", "2026-01-02", "2026-01-05"),
            ])
            self._write_prices(price_path, [
                ("2026-01-02", "ABC", "EQ", "INE000A01001", 100.0, 105.0, 95.0, 102.0, 1000, 102000.0, 0.5, 51.0),
                ("2026-01-05", "ABC", "EQ", "INE000A01001", 110.0, 115.0, 108.0, 112.0, 1200, 134400.0, 1.0, 112.0),
            ])
            with self._mock_download(history_path, price_path):
                frames, diagnostics = load_adjusted_frames(
                    ["ABC.NS", "MISSING.NS"], "2026-01-01", "2026-01-31",
                    cache_dir=tmp, revision="fixture",
                )

            frame = frames["ABC.NS"]
            self.assertEqual(len(frame), 2)
            self.assertAlmostEqual(frame.iloc[0]["Open"], 50.0)
            self.assertAlmostEqual(frame.iloc[0]["High"], 52.5)
            self.assertAlmostEqual(frame.iloc[0]["Low"], 47.5)
            self.assertAlmostEqual(frame.iloc[0]["Close"], 51.0)
            self.assertEqual(frame.iloc[0]["Volume"], 1000)
            self.assertEqual(frame.iloc[0]["Turnover"], 102000.0)
            self.assertEqual(diagnostics["ABC.NS"]["bars"], 2)
            self.assertEqual(diagnostics["ABC.NS"]["status"], "insufficient_history")
            self.assertEqual(diagnostics["MISSING.NS"]["status"], "no_history")
            self.assertEqual(diagnostics["_source"]["dataset_revision"], "fixture")

    def test_include_raw_preserves_exchange_ohlc_for_benchmark_reconciliation(self):
        with tempfile.TemporaryDirectory() as tmp:
            history_path = Path(tmp) / "symbol_history.parquet"
            price_path = Path(tmp) / "nse_2026.parquet"
            self._write_history(history_path, [
                ("INE000A01001", "NIFTYBEES", "2026-01-02", "2026-01-05"),
            ])
            self._write_prices(price_path, [
                ("2026-01-02", "NIFTYBEES", "EQ", "INE000A01001", 100.0, 105.0, 95.0, 102.0, 1000, 102000.0, 0.5, 51.0),
            ])
            with self._mock_download(history_path, price_path):
                frames, _ = load_adjusted_frames(
                    ["NIFTYBEES.NS"], "2026-01-01", "2026-01-31",
                    cache_dir=tmp, min_bars=1, revision="fixture", include_raw=True,
                )
            frame = frames["NIFTYBEES.NS"]
            self.assertAlmostEqual(frame.iloc[0]["Open"], 50.0)
            self.assertAlmostEqual(frame.iloc[0]["Close"], 51.0)
            self.assertAlmostEqual(frame.iloc[0]["RawOpen"], 100.0)
            self.assertAlmostEqual(frame.iloc[0]["RawHigh"], 105.0)
            self.assertAlmostEqual(frame.iloc[0]["RawLow"], 95.0)
            self.assertAlmostEqual(frame.iloc[0]["RawClose"], 102.0)


    def test_retains_short_history_and_marks_it_insufficient(self):
        with tempfile.TemporaryDirectory() as tmp:
            history_path = Path(tmp) / "symbol_history.parquet"
            price_path = Path(tmp) / "nse_2026.parquet"
            self._write_history(history_path, [
                ("INE000B01002", "NEWCO", "2026-06-01", "2026-06-01"),
            ])
            self._write_prices(price_path, [
                ("2026-06-01", "NEWCO", "EQ", "INE000B01002", 10.0, 11.0, 9.0, 10.5, 100, 1050.0, 1.0, 10.5),
            ])
            with self._mock_download(history_path, price_path):
                frames, diagnostics = load_adjusted_frames(
                    ["NEWCO.NS"], "2026-01-01", "2026-10-01",
                    cache_dir=tmp, min_bars=253, revision="fixture",
                )
            self.assertIn("NEWCO.NS", frames)
            self.assertEqual(len(frames["NEWCO.NS"]), 1)
            self.assertEqual(diagnostics["NEWCO.NS"]["status"], "insufficient_history")

    def test_renamed_symbol_inherits_same_isin_lookback(self):
        with tempfile.TemporaryDirectory() as tmp:
            history_path = Path(tmp) / "symbol_history.parquet"
            price_path = Path(tmp) / "nse_2026.parquet"
            self._write_history(history_path, [
                ("INE000C01003", "OLD", "2025-12-29", "2026-01-05"),
                ("INE000C01003", "NEW", "2026-01-06", "2026-01-31"),
            ])
            self._write_prices(price_path, [
                ("2026-01-02", "OLD", "EQ", "INE000C01003", 100.0, 102.0, 99.0, 101.0, 1000, 101000.0, 1.0, 101.0),
                ("2026-01-05", "OLD", "EQ", "INE000C01003", 101.0, 103.0, 100.0, 102.0, 1000, 102000.0, 1.0, 102.0),
                ("2026-01-06", "NEW", "EQ", "INE000C01003", 102.0, 104.0, 101.0, 103.0, 1000, 103000.0, 1.0, 103.0),
                ("2026-01-07", "NEW", "EQ", "INE000C01003", 103.0, 105.0, 102.0, 104.0, 1000, 104000.0, 1.0, 104.0),
            ])
            membership = pd.DataFrame([{
                "symbol": "NEW", "valid_from": pd.Timestamp("2026-01-06"),
                "valid_to": pd.NaT,
            }])
            with self._mock_download(history_path, price_path):
                frames, diagnostics = load_adjusted_frames(
                    ["NEW.NS"], "2026-01-01", "2026-01-31",
                    cache_dir=tmp, membership_df=membership, min_bars=1,
                    revision="fixture",
                )
            self.assertEqual(len(frames["NEW.NS"]), 4)
            self.assertEqual(frames["NEW.NS"].index.min(), pd.Timestamp("2026-01-02"))
            self.assertEqual(diagnostics["NEW.NS"]["status"], "loaded")
            self.assertIn("aliases=['NEW', 'OLD']", diagnostics["NEW.NS"]["detail"])

    def test_same_ticker_reuse_after_long_gap_is_a_separate_chain(self):
        history = pd.DataFrame([
            ("INE000D01004", "REUSED", "2025-01-01", "2025-01-31"),
            ("INE000E01005", "REUSED", "2025-04-01", "2025-05-01"),
        ], columns=["isin", "symbol", "valid_from", "valid_to"])
        chained = build_symbol_chains(history)
        self.assertNotEqual(chained.iloc[0]["chain_id"], chained.iloc[1]["chain_id"])
        membership = pd.DataFrame([{
            "symbol": "REUSED", "valid_from": pd.Timestamp("2025-01-01"),
            "valid_to": pd.Timestamp("2025-02-01"),
        }])
        mapping = map_symbol_chains(["REUSED"], chained, membership)
        self.assertEqual(mapping["REUSED"], {chained.iloc[0]["chain_id"]})

    @patch("huggingface_hub.HfApi")
    def test_dataset_revision_uses_dataset_specific_info_method(self, api):
        api.return_value.dataset_info.return_value.sha = "a" * 40
        self.assertEqual(get_dataset_revision(), "a" * 40)
        api.return_value.dataset_info.assert_called_once_with(REPO_ID)

    def test_same_symbol_new_isin_within_30_days_is_one_chain(self):
        history = pd.DataFrame([
            ("INE000F01006", "CONTINUOUS", "2025-01-01", "2025-01-31"),
            ("INE000G01007", "CONTINUOUS", "2025-02-10", "2025-03-01"),
        ], columns=["isin", "symbol", "valid_from", "valid_to"])
        chained = build_symbol_chains(history)
        self.assertEqual(chained.iloc[0]["chain_id"], chained.iloc[1]["chain_id"])

    def test_overlapping_different_isin_intervals_are_rejected(self):
        history = pd.DataFrame([
            ("INE000H01008", "AMBIGUOUS", "2025-01-01", "2025-01-31"),
            ("INE000I01009", "AMBIGUOUS", "2025-01-31", "2025-02-15"),
        ], columns=["isin", "symbol", "valid_from", "valid_to"])
        with self.assertRaisesRegex(RuntimeError, "overlapping ISIN intervals"):
            build_symbol_chains(history)


if __name__ == "__main__":
    unittest.main()
