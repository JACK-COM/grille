"""Grille's half of panoply-lib's scorer contract."""
import json
import sys
import unittest

import _scorer_contract as contract

from tests.harness import GrilleCase
from grillelib.score import score_text  # noqa: E402


class ContractTest(GrilleCase):
    """The request Grille sends a scorer has the contract's shape, and it reads the contract's reply."""

    def test_scorer_contract(self):
        """One request and one reply through a recording stand-in."""
        d = self.d
        sent = d / "contract-request.json"
        cmd = [sys.executable, "-c", "import json, sys; open(sys.argv[1], 'w').write(sys.stdin.read()); "
               "print(json.dumps(json.loads(sys.argv[2])))", str(sent), json.dumps(contract.REPLY)]
        got = score_text(cmd, contract.REQUEST["text"], contract.REQUEST["subject"])
        self.assertEqual(got, contract.probability(contract.REPLY), f"the contract's reply read as {got}")
        req = json.loads(sent.read_text())
        self.assertTrue(set(req) <= contract.REQUEST_KEYS and {"questions", "text"} <= set(req), f"request keys {sorted(req)}")
        self.assertEqual(set(req["questions"]), set(contract.REQUEST["questions"]), f"question names {sorted(req['questions'])}")
        self.assertEqual(req["questions"][contract.QUESTION]["type"], "noul", "the scorer question is not a noul")


if __name__ == "__main__":
    unittest.main()
