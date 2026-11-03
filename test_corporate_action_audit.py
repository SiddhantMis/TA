import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
import pandas as pd
from corporate_action_audit import load_and_apply_action_quarantine

class TestActionQuarantine(unittest.TestCase):
    def test_resets_lookback(self):
        idx=pd.bdate_range("2024-01-01",periods=300)
        frame=pd.DataFrame({"Close":range(300)},index=idx)
        data=pd.DataFrame([{"symbol":"AAA","ex_date":idx[270],"type":"demerger"}])
        with tempfile.TemporaryDirectory() as tmp:
            with patch("huggingface_hub.hf_hub_download",return_value=str(Path(tmp)/"actions.parquet")):
                empty = pd.DataFrame(columns=["symbol","ex_date","type"])
                with patch("pandas.read_parquet",side_effect=[data,empty]):
                    out,audit,quarantine=load_and_apply_action_quarantine({"AAA.NS":frame},idx[0],idx[-1],tmp,"fixture")
        self.assertEqual(len(out["AAA.NS"]),30)
        self.assertFalse(bool(quarantine.iloc[0]["eligible_after_253_sessions"]))
        self.assertEqual(len(audit),1)

if __name__=="__main__": unittest.main()
