import unittest

from dotstts_wyoming.text import SentenceChunker


class SentenceChunkerTests(unittest.TestCase):
    def test_splits_sentences_on_terminator_and_whitespace(self):
        chunker = SentenceChunker()
        sentences = chunker.add_chunk("Ala ma kota. Kot ma Ale. Koniec")
        self.assertEqual(sentences, ["Ala ma kota.", "Kot ma Ale."])
        self.assertEqual(chunker.finish(), "Koniec")

    def test_does_not_split_at_end_of_buffer(self):
        chunker = SentenceChunker()
        self.assertEqual(chunker.add_chunk("To kosztuje $3."), [])
        self.assertEqual(chunker.add_chunk("50 i tyle. Dalej"), ["To kosztuje $3.50 i tyle."])
        self.assertEqual(chunker.finish(), "Dalej")

    def test_does_not_split_after_abbreviations(self):
        chunker = SentenceChunker()
        sentences = chunker.add_chunk("Dr. Smith is here. Next one starts")
        self.assertEqual(sentences, ["Dr. Smith is here."])

    def test_does_not_split_after_polish_abbreviations(self):
        chunker = SentenceChunker()
        sentences = chunker.add_chunk("Wpadnij np. jutro albo w 2024 r. wieczorem. Dalej")
        self.assertEqual(sentences, ["Wpadnij np. jutro albo w 2024 r. wieczorem."])

    def test_does_not_split_after_initials(self):
        chunker = SentenceChunker()
        sentences = chunker.add_chunk("Prace J. Kowalskiego czekam. Dalej")
        self.assertEqual(sentences, ["Prace J. Kowalskiego czekam."])

    def test_splits_across_streamed_chunks(self):
        chunker = SentenceChunker()
        self.assertEqual(chunker.add_chunk("Dr."), [])
        sentences = chunker.add_chunk(" Smith przyszedl. Potem")
        self.assertEqual(sentences, ["Dr. Smith przyszedl."])
        self.assertEqual(chunker.finish(), "Potem")


if __name__ == "__main__":
    unittest.main()
