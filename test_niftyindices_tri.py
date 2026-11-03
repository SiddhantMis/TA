import unittest
from unittest.mock import Mock
from niftyindices_tri import load_nifty500_tri_history

class TestNifty500TRI(unittest.TestCase):
    def test_parse(self):
        response=Mock()
        response.raise_for_status.return_value=None
        response.json.return_value={"d":'[{"Date":"01 Jan 2024","TotalReturnsIndex":"100.0"},{"Date":"02 Jan 2024","TotalReturnsIndex":"101.0"}]'}
        session=Mock(); session.headers={}; session.post.return_value=response
        result=load_nifty500_tri_history("2024-01-01","2024-01-02",session)
        self.assertEqual(result["Close"].tolist(),[100.0,101.0])

if __name__=="__main__": unittest.main()
