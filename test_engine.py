"""Quick regression tests: python3 test_engine.py"""
import unittest
from engine import Engine, TERMS


class EngineTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.e = Engine()

    def plain(self, text):
        return self.e.to_plain(text).translated

    def econ(self, text):
        return self.e.to_econ(text).translated

    def test_single_term(self):
        self.assertEqual(self.plain("inflation"), "rising prices")
        self.assertEqual(self.plain("Inflation"), "Rising prices")

    def test_sentence_and_explanations(self):
        r = self.e.to_plain("The Fed raised rates by 25 basis points to fight inflation.")
        self.assertIn("0.25 percentage points", r.translated)
        self.assertIn("rising prices", r.translated)
        names = [t.term for t in r.terms]
        self.assertIn("inflation", names)
        self.assertIn("basis points", names)
        self.assertIn("federal reserve", names)

    def test_plurals(self):
        self.assertEqual(self.plain("tariffs and subsidies"), "taxes on imports and government payments that lower prices")
        self.assertEqual(self.plain("consumers and households"), "shoppers and families")
        self.assertIn("shrinking economies", self.plain("Two recessions in a decade"))

    def test_articles_and_capitals(self):
        self.assertEqual(self.plain("into a recession."), "into a shrinking economy.")
        self.assertEqual(self.plain("Treasury yields rose."), "interest returns rose.".capitalize())
        self.assertEqual(self.plain("pushing Treasury yields up"), "pushing interest returns up")

    def test_protected_phrases(self):
        text = "I paid my credit card and appreciate the real estate deal."
        self.assertEqual(self.plain(text), text)
        self.assertEqual(self.e.to_plain(text).terms, [])

    def test_no_double_replacement(self):
        self.assertEqual(self.plain("tariffs on imports"), "taxes on imports")

    def test_adjectives(self):
        self.assertIn("rate-cut-leaning pivot", self.plain("a dovish pivot"))
        self.assertIn("is not price-sensitive", self.plain("Demand is inelastic"))

    def test_keep_terms_are_explained_not_replaced(self):
        r = self.e.to_plain("Demand rose.")
        self.assertEqual(r.translated, "Demand rose.")
        self.assertEqual([t.term for t in r.terms], ["demand"])

    def test_reverse(self):
        self.assertEqual(self.econ("prices keep going up"), "inflation")
        self.assertIn("budget deficit", self.econ("the government spends more than it takes in"))
        self.assertIn("ceteris paribus", self.econ("all else being equal"))
        r = self.e.to_econ("home loans got pricier")
        self.assertIn("mortgages", r.translated.lower())
        self.assertEqual(r.terms[0].term, "mortgage")

    def test_spans_point_into_original(self):
        text = "  Rates rose 50 bps as inflation climbed."
        r = self.e.to_plain(text)
        stripped = text.strip()
        for f in r.found:
            self.assertEqual(stripped[f.start:f.end].lower(), f.matched.lower())

    def test_glossary_integrity(self):
        names = [t.term for t in TERMS]
        self.assertEqual(len(names), len(set(names)), "duplicate term names")
        for t in TERMS:
            self.assertTrue(t.plain and t.meaning and t.example, t.term)
            self.assertNotIn("as", t.aliases)

    def test_textbook_terms(self):
        out = self.plain("Rational people think at the margin. Points inside the PPF are inefficient.")
        self.assertIn("People who weigh costs and benefits", out)
        self.assertIn("most-you-can-make curve", out)
        self.assertIn("wasteful", out)
        self.assertEqual(self.plain("The production possibilities frontier (PPF) shifts outward."),
                         "The most-you-can-make curve shifts outward.")
        self.assertEqual(self.plain("with the available factors of production"),
                         "with the available basic ingredients for making things")
        r = self.e.to_plain("Positive statements are descriptive.")
        self.assertEqual(r.translated, "Claims about how things are are fact-based.")
        self.assertEqual([t.term for t in r.terms], ["positive statement"])

    def test_empty(self):
        self.assertEqual(self.plain("   "), "")


if __name__ == "__main__":
    unittest.main(verbosity=1)
