"""Quick regression tests: python3 test_engine.py"""
import os
import tempfile
import unittest
from unittest import mock

import speech
import voice
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

    def setUp(self):
        self.tutor = voice.VoiceTutor(self.e)

    # -- the separation: speech answers, it does not echo -----------------

    def test_statement_is_explained_not_read_back(self):
        """
        The whole point of the split. Saying a sentence out loud gets you the
        terms in it explained - not that same sentence with the words swapped,
        which is the translator's job and is useless as a spoken answer.
        """
        said = "The Federal Reserve raised rates to curb inflation."
        reply = self.tutor.reply_to(said)
        self.assertEqual(reply.kind, "definition")

        # Neither their sentence nor the translator's rewrite of it is spoken.
        # (Individual words may still recur - a glossary example is allowed to
        # mention rates - so the test is about the sentence, not the vocabulary.)
        rewritten = self.e.to_plain(said).translated.rstrip(".").lower()
        self.assertNotIn(said.rstrip(".").lower(), reply.speech.lower())
        self.assertNotIn(rewritten, reply.speech.lower())
        self.assertNotIn("In plain English", reply.speech)

        # What they get instead is an explanation.
        self.assertIn("central bank", reply.speech.lower())

    def test_heard_is_kept_for_display_but_never_spoken(self):
        said = "Inflation rose while unemployment fell."
        reply = self.tutor.reply_to(said)
        self.assertEqual(reply.heard, said)          # shown on screen
        self.assertNotIn(said, reply.speech)         # never read aloud

    def test_speech_ignores_the_translator_direction(self):
        """Speech is its own operation: the toggle has no say in what it says."""
        a = voice.VoiceTutor(self.e).reply_to("what is inflation?")
        b = voice.VoiceTutor(self.e).reply_to("what is inflation?")
        self.assertEqual(a.speech, b.speech)
        self.assertNotIn("In plain English", a.speech)

    # -- answering --------------------------------------------------------

    def test_question_gets_a_definition_not_a_substitution(self):
        reply = self.tutor.reply_to("What does opportunity cost mean?")
        self.assertTrue(reply.speech.startswith("Opportunity cost means"))
        self.assertIn("For example,", reply.speech)
        self.assertNotIn("What does what you give up", reply.speech)

    def test_plain_words_find_the_jargon(self):
        # Asked the other way round: everyday words, jargon answer.
        reply = self.tutor.reply_to("what's the word for when prices keep going up?")
        self.assertEqual(reply.kind, "definition")
        self.assertTrue(reply.terms)

    def test_unknown_says_so_without_echoing(self):
        reply = self.tutor.reply_to("What is a widget dingus?")
        self.assertEqual(reply.kind, "unknown")
        self.assertIn("don't have that one", reply.speech)
        self.assertNotIn("widget dingus", reply.speech)

    def test_avoids_saying_a_word_means_itself(self):
        reply = self.tutor.reply_to("What is economics?")
        self.assertNotIn("economics means economics", reply.speech.lower())
        self.assertIn("economics. the study of", reply.speech.lower())

    def test_empty_input(self):
        reply = self.tutor.reply_to("")
        self.assertEqual(reply.kind, "empty")
        self.assertEqual(reply.speech, "")

    # -- the one time reading it back is the request ----------------------

    def test_explicit_rephrase_request_is_honoured(self):
        reply = self.tutor.reply_to(
            "Put that in plain English: the Fed raised rates to curb inflation")
        self.assertEqual(reply.kind, "rephrase")
        self.assertTrue(reply.speech.startswith("In plain English: "))
        self.assertIn("rising prices", reply.speech)
        # The instruction itself is not part of what gets rewritten.
        self.assertNotIn("put that in plain english", reply.speech.lower())

    def test_rephrase_detection(self):
        for asked in ["simplify this", "say that in plain english",
                      "can you translate that", "rephrase that for me"]:
            self.assertTrue(voice.wants_rephrase(asked), asked)
        for asked in ["what is inflation?", "explain the yield curve",
                      "the Fed raised rates"]:
            self.assertFalse(voice.wants_rephrase(asked), asked)

    # -- prose quality ----------------------------------------------------

    def test_no_doubled_punctuation(self):
        for asked in ["Explain inflation", "What is GDP?", "Inflation rose!",
                      "simplify: inflation rose"]:
            said = self.tutor.reply_to(asked).speech
            for bad in ("?.", "!.", "..", " .", ";."):
                self.assertNotIn(bad, said, f"{bad!r} in {said!r}")

    def test_spoken_sentences_start_capitalised(self):
        said = self.tutor.reply_to("Tell me about the federal reserve").speech
        self.assertTrue(said[0].isupper(), said[:40])

    def test_looks_like_question(self):
        for q in ["what is inflation", "Explain GDP", "How does the Fed work?",
                  "define elasticity", "Tell me about tariffs", "is this a question?"]:
            self.assertTrue(voice.looks_like_question(q), q)
        for s_ in ["The Fed raised rates.", "Inflation rose 3%.", ""]:
            self.assertFalse(voice.looks_like_question(s_), s_)

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
