"""Quick regression tests: python3 test_engine.py"""
import os
import tempfile
import unittest
from unittest import mock

import speech
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


class SpeechHelperTests(unittest.TestCase):
    """Speech helpers that need no microphone and no network."""

    @classmethod
    def setUpClass(cls):
        cls.e = Engine()

    def test_spoken_summary_reads_naturally(self):
        r = self.e.to_plain("Inflation rose while unemployment fell.")
        said = speech.spoken_summary(r, "plain")
        self.assertTrue(said.startswith("In plain English: "))
        self.assertIn("rising prices", said)
        self.assertIn("inflation means rising prices", said)
        self.assertNotIn("..", said)

    def test_spoken_summary_handles_keep_terms(self):
        # A "keep" term stays in the sentence but is still explained aloud.
        r = self.e.to_plain("Demand rose.")
        said = speech.spoken_summary(r, "plain")
        self.assertIn("In plain English: Demand rose.", said)
        self.assertIn("demand means how much people want to buy", said.lower())

    def test_spoken_summary_avoids_saying_a_word_means_itself(self):
        # "economics" is its own plain phrase, so it must not say
        # "economics means economics".
        r = self.e.to_plain("Economics is about scarcity.")
        said = speech.spoken_summary(r, "plain")
        self.assertNotIn("economics means economics", said.lower())
        self.assertIn("economics. the study of", said.lower())

    def test_spoken_summary_empty(self):
        self.assertEqual(speech.spoken_summary(None, "plain"), "")
        self.assertEqual(speech.spoken_summary(self.e.to_plain(""), "plain"), "")

    def test_fatal_flag(self):
        self.assertFalse(speech.SpeechError("try again").fatal)
        self.assertTrue(speech.SpeechError("no mic", fatal=True).fatal)

    def test_config_roundtrip(self):
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "config.json")
            with mock.patch.object(speech, "CONFIG_PATH", path), \
                 mock.patch.object(speech, "CONFIG_DIR", d), \
                 mock.patch.dict(os.environ, {}, clear=True):
                self.assertIsNone(speech.get_api_key())
                speech.save_api_key("  sk-abc123  ")
                self.assertEqual(speech.get_api_key(), "sk-abc123")
                self.assertEqual(oct(os.stat(path).st_mode)[-3:], "600")

    def test_env_key_wins(self):
        with mock.patch.dict(os.environ, {"OPENAI_API_KEY": "sk-from-env"}):
            self.assertEqual(speech.get_api_key(), "sk-from-env")

    def test_wav_header(self):
        wav = speech._to_wav(b"\x00\x01" * 800)
        self.assertTrue(wav.startswith(b"RIFF"))
        self.assertIn(b"WAVE", wav[:16])


if __name__ == "__main__":
    unittest.main(verbosity=1)
