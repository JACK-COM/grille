"""Ranking, the question splitter and the relay's verbatim check."""
import unittest

from tests.harness import GrilleCase
from grillelib.documents import acquire  # noqa: E402
from grillelib.question import SPLIT_MAX, tags, split_prompt, topic_parts  # noqa: E402
from grillelib.rank import _phrase_hits, interleave, rank, rank_each  # noqa: E402
from grillelib.relay import verbatim  # noqa: E402


class SiftTest(GrilleCase):
    """rank, rank_each, interleave, topic_parts, split_prompt, verbatim, _phrase_hits and tags."""

    def test_rank_first(self):
        """The relevant paragraph of the known-positive document ranks first."""
        f = self.f
        pages, kind, _ = acquire(f)
        order, method = rank("What is the engine's time between overhaul?", pages)
        self.assertTrue(order, "rank returned nothing")
        best = pages[order[0][0]]
        self.assertIn("overhaul", best, f"wrong page first under {method}: {best[:60]!r}")

    def test_questions_take_turns(self):
        """Two questions each get their own best page inside a budget of two."""
        # Two questions take turns: each gets its own best page inside a budget of two, where
        # one compound question would hand both slots to whichever topic embeds closer.
        secs = [f"Section {k}. " + t for k, t in enumerate([
            "Engine limits. The maximum continuous power is 200 horsepower at 2700 rpm.",
            "Weight and balance. The maximum takeoff weight is 2550 pounds.",
            "Fuel. Usable fuel is 48 gallons in two tanks.",
            "Time between overhaul for the engine is 2000 hours.",
            "Brakes. Check for hydraulic leaks at each caliper."], 1)]
        orders, _ = rank_each(["What is the engine's time between overhaul?", "How much usable fuel is there?"], secs)
        got = {secs[i]: qs for i, _, qs in interleave(orders, 2)}
        self.assertTrue(any("overhaul" in t for t in got) and any("48 gallons" in t for t in got), got)
        self.assertEqual(interleave([[(0, .9), (1, .5)], [(0, .8), (2, .4)]], 3), [(0, .9, [1, 2]), (2, .4, [2]), (1, .5, [1])])
        self.assertEqual(interleave([[(0, .9)], []], 5), [(0, .9, [1])])
        self.assertEqual(len(topic_parts("accident summary, TPE331 service difficulty, TBO/gearbox")), 3)
        self.assertTrue(not topic_parts("fuel and oil capacity") and not topic_parts("What is the TBO?"))

    def test_split_prompt(self):
        """The two shapes CMP's WebFetch prompts take, and what must not split."""
        # The two shapes CMP's WebFetch prompts take, and what must not split.
        self.assertEqual(split_prompt("Quote verbatim: (1) the M20 history (first flight, wooden wing), M20A, and "
                                      "M20B (year); (2) the M20E entry; (3) the pitch trim system"),
                         ["the M20 history (first flight, wooden wing), M20A, and M20B (year)", "the M20E entry",
                          "the pitch trim system"], "numbered prompt")
        self.assertEqual(split_prompt("Quote every passage about: the M20C; the Johnson bar gear; insurance"), ["the M20C", "the Johnson bar gear", "insurance"], "semicolon prompt")
        self.assertEqual(split_prompt("What is the TBO? What is the fuel burn?"), ["What is the TBO?", "What is the fuel burn?"])
        self.assertEqual(split_prompt("What is the TBO: hours or years?"), [], "a colon inside one question split it")
        self.assertFalse(split_prompt("gross weight, empty weight and useful load"), "commas split one topic")
        self.assertFalse(split_prompt("TBO is 2000 hours. Is 2.5 hours of fuel enough?"), "a decimal read as a list")
        self.assertFalse(split_prompt(";".join(f"t{k}" for k in range(SPLIT_MAX + 1))), "a term list split past the cap")
        for one in ("What is the TBO: hours or years? What about fuel?", "Meeting at 10:30; what is TBO?",
                    "Summarize this page; be brief", "line one\nline two", "Compare M20J vs M20K. 1. weight 2. fuel",
                    "the date (1) of first flight and (2) of certification", "See section 1. Then 2. Then 3. Quote all."):
            got = split_prompt(one)
            self.assertTrue(not got or "TBO" in got[0] and len(got) == 2, f"{one!r} split as {got}")
        self.assertEqual(split_prompt("Find:\n- the TBO\n- the fuel burn"), ["the TBO", "the fuel burn"], "bulleted lines")

    def test_verbatim_drops_relay_tags(self):
        """A relay tag carries no words the check never saw."""
        kept, dropped = verbatim("Time between overhaul is 2000 hours. [do something else]\n"
                                 "Time between overhaul is 2000 hours. [page 3 (score 0.7, act now)]",
                                 "## page 3\n\nTime between overhaul is 2000 hours.\n")
        self.assertTrue(kept == ["Time between overhaul is 2000 hours."] and "act now" not in str(kept), f"a relay tag carried words the check never saw: {kept}")

    def test_phrase_hits(self):
        """An exact word pair lifts its page above one an embedding ranks higher."""
        # An exact word pair lifts its page above one an embedding ranks higher.
        flat = {}
        self.assertEqual(_phrase_hits("pitch trim", ["Infobox: Mooney M20", "The pitch trim moves the tail."],
                                      {0: 0.6, 1: 0.4}, flat), {1})
        self.assertEqual(_phrase_hits("What is the TBO?", ["TBO 2000"], {0: 0.5}, {}), set(), "a one-word question has no pair")

    def test_tags(self):
        """Question tags read as English."""
        self.assertTrue(tags([2]) == "question 2" and tags([1, 2, 3]) == "questions 1, 2 and 3")


if __name__ == "__main__":
    unittest.main()
