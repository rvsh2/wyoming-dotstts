"""Text chunking helpers for streaming-style Wyoming TTS input."""

from __future__ import annotations

import re


# Require real whitespace after the terminator. During streaming, end-of-buffer
# only means "more text may still arrive", so it must NOT be treated as a
# sentence boundary (otherwise "$3.50" gets split). The trailing partial
# sentence is flushed by finish() once the stream ends.
SENTENCE_END_RE = re.compile(r"([.!?。！？]+)\s+")

# Words that end with "." mid-sentence (English + Polish). Compared lowercase,
# without the trailing period.
_ABBREVIATIONS = {
    # English
    "dr", "mr", "mrs", "ms", "prof", "st", "jr", "sr", "vs", "etc", "no",
    "vol", "approx", "dept", "est", "min", "max",
    # Polish
    "np", "itp", "itd", "tzn", "tj", "tzw", "ul", "al", "św", "im", "godz",
    "r", "s", "str", "nr", "mgr", "inż", "hab", "ok", "wg", "pt", "ww",
    "m.in", "płk", "gen", "kpt", "por", "ks", "abp", "bp", "woj", "pow",
}


def _ends_with_abbreviation(text: str) -> bool:
    """True when *text* ends in a period that belongs to an abbreviation."""
    if not text.endswith("."):
        return False
    body = text[:-1]
    if not body.strip():
        return False
    last_word = body.rsplit(None, 1)[-1].lstrip("(\"'[{").lower()
    # Single letters cover initials ("J. Kowalski").
    return (len(last_word) == 1 and last_word.isalpha()) or last_word in _ABBREVIATIONS


class SentenceChunker:
    def __init__(self) -> None:
        self._buffer = ""
        # Where to resume the boundary search: skips terminators already
        # classified as abbreviations so they are not re-tested on every chunk.
        self._search_pos = 0

    def add_chunk(self, text: str) -> list[str]:
        self._buffer += text
        sentences: list[str] = []

        while True:
            match = SENTENCE_END_RE.search(self._buffer, self._search_pos)
            if match is None:
                break
            sentence = self._buffer[: match.end(1)]
            if _ends_with_abbreviation(sentence):
                self._search_pos = match.end(1)
                continue
            sentence = sentence.strip()
            if sentence:
                sentences.append(sentence)
            self._buffer = self._buffer[match.end() :]
            self._search_pos = 0

        return sentences

    def finish(self) -> str:
        remainder = self._buffer.strip()
        self._buffer = ""
        self._search_pos = 0
        return remainder
