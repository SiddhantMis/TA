from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq

from tejhq_data import load_adjusted_frames


class TejHQAdjustedLoaderTests(unittest.TestCase):
    # Regression coverage for the exchange-adjusted provider path.
    def test_adjusts_ohlc_but_preserves_raw_volume_and_turnover(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "nse_2026.parquet"
            raw = pd.DataFrame({
                "date": [pd.Timestamp("2026-01-02").date(), pd.Timestamp("2026-01-05").date()],
                "symbol": ["ABC", "ABC"],
                "series": ["EQ", "EQ"],
                "open": [100.0, 110.0],
                "high": [105.0, 115.0],
                "low": [95.0, 108.0],
                "close": [102.0, 112.0],
                "volume": [1000, 1200],
                "turnover": [102000.0, 134400.0],
                "adj_factor_cumulative": [0.5, 1.0],
                "adj_close": [51.0, 112.0],
            })
            pq.write_table(pa.Table.from_pandas(raw, preserve_index=False), path)
            with patch("huggingface_hub.hf_hub_download", return_value=str(path)):
                frames, diagnostics = load_adjusted_frames(
                    ["ABC.NS", "MISSING.NS"], "2026-01-01", "2026-01-31",
                    cache_dir=tmp,
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
            self.assertEqual(diagnostics["MISSING.NS"]["status"], "no_history")

    def test_retains_new_listing_with_short_history(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "nse_2026.parquet"
            raw = pd.DataFrame({
                "date": [pd.Timestamp("2026-06-01").date()],
                "symbol": ["NEWCO"], "series": ["EQ"],
                "open": [10.0], "high": [11.0], "low": [9.0], "close": [10.5],
                "volume": [100], "turnover": [1050.0],
                "adj_factor_cumulative": [1.0], "adj_close": [10.5],
            })
            pq.write_table(pa.Table.from_pandas(raw, preserve_index=False), path)
            with patch("huggingface_hub.hf_hub_download", return_value=str(path)):
                frames, diagnostics = load_adjusted_frames(
                    ["NEWCO.NS"], "2026-01-01", "2026-10-01", cache_dir=tmp,
                )
            self.assertIn("NEWCO.NS", frames)
            self.assertEqual(len(frames["NEWCO.NS"]), 1)
            self.assertEqual(diagnostics["NEWCO.NS"]["status"], "loaded")


if __name__ == "__main__":
    unittest.main()
