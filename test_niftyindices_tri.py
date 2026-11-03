import unittest
from unittest.mock import Mock

from niftyindices_tri import URL, load_nifty500_tri_history


class TestNifty500TRI(unittest.TestCase):
    def _load_with_payload(self, payload):
        response = Mock()
        response.raise_for_status.return_value = None
        response.json.return_value = payload
        session = Mock()
        session.headers = {}
        session.post.return_value = response
        result = load_nifty500_tri_history("2024-01-01", "2024-01-02", session)
        session.post.assert_called_once()
        self.assertEqual(session.post.call_args.args[0], URL)
        self.assertEqual(result["Close"].tolist(), [100.0, 101.0])

    def test_parse_current_direct_array_response(self):
        self._load_with_payload([
            {"Date": "01 Jan 2024", "TotalReturnsIndex": "100.0"},
            {"Date": "02 Jan 2024", "TotalReturnsIndex": "101.0"},
        ])

    def test_parse_legacy_envelope_response(self):
        self._load_with_payload({
            "d": '[{"Date":"01 Jan 2024","TotalReturnsIndex":"100.0"},'
                 '{"Date":"02 Jan 2024","TotalReturnsIndex":"101.0"}]'
        })


if __name__ == "__main__":
    unittest.main()
