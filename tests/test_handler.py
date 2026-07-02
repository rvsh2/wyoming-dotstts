import asyncio
import unittest
from types import SimpleNamespace

from dotstts_wyoming.handler import DotsTtsEventHandler
from dotstts_wyoming.synthesizer import SynthesisResult
from dotstts_wyoming.wyoming_protocol import Attribution, Event, Info, TtsProgram


class _LockMixin:
    def get_async_lock(self):
        return asyncio.Lock()


class CollectingHandler(DotsTtsEventHandler):
    def __init__(self, cli_args, synthesizer):
        super().__init__(
            Info(
                tts=[
                    TtsProgram(
                        name="dots.tts",
                        attribution=Attribution(name="test", url="https://example.invalid"),
                        installed=True,
                        description="test",
                        version=None,
                        voices=[],
                    )
                ]
            ),
            cli_args,
            synthesizer,
            None,
            None,
        )
        self.events = []

    async def write_event(self, event):
        self.events.append(event)


class HandlerTests(unittest.TestCase):
    def run_async(self, coro):
        return asyncio.run(coro)

    def test_describe_returns_info(self):
        handler = CollectingHandler(
            cli_args=SimpleNamespace(no_streaming=False, samples_per_chunk=1024),
            synthesizer=SimpleNamespace(),
        )
        self.run_async(handler.handle_event(Event("describe", {})))
        self.assertIn(handler.events[0].type, {"describe", "info"})

    def test_synthesize_returns_audio_events_and_context_options(self):
        calls = []

        class FakeSynthesizer(_LockMixin):
            def synthesize(self, text, *, voice_name, options):
                calls.append((text, voice_name, options))
                return SynthesisResult(
                    audio=[0.0, 0.25, -0.25, 0.1],
                    sample_rate=48000,
                    voice=voice_name or "mira",
                    language=options.language,
                    processing_time=0.1,
                )

        handler = CollectingHandler(
            cli_args=SimpleNamespace(no_streaming=False, samples_per_chunk=2),
            synthesizer=FakeSynthesizer(),
        )

        self.run_async(
            handler.handle_event(
                Event(
                    "synthesize",
                    {
                        "text": "test one. test two.",
                        "voice": {"name": "mira"},
                        "context": {"num_steps": "3", "seed": "9", "language": "PL"},
                    },
                )
            )
        )

        event_types = [event.type for event in handler.events]
        self.assertEqual(event_types[0], "audio-start")
        self.assertIn("audio-chunk", event_types)
        self.assertEqual(event_types[-1], "audio-stop")
        self.assertEqual(calls[0][1], "mira")
        self.assertEqual(calls[0][2].num_steps, 3)
        self.assertEqual(calls[0][2].seed, 9)
        self.assertEqual(calls[0][2].language, "PL")

    def test_streaming_stop_emits_synthesize_stopped(self):
        class FakeSynthesizer(_LockMixin):
            def synthesize_stream(self, text, *, voice_name, options):
                yield [0.1, -0.1], 48000
                yield [0.2], 48000

        handler = CollectingHandler(
            cli_args=SimpleNamespace(no_streaming=False, samples_per_chunk=8),
            synthesizer=FakeSynthesizer(),
        )

        self.run_async(handler.handle_event(Event("synthesize-start", {"voice": {"name": "mira"}})))
        self.run_async(handler.handle_event(Event("synthesize-chunk", {"text": "Ala ma kota."})))
        self.run_async(handler.handle_event(Event("synthesize-stop", {})))

        event_types = [event.type for event in handler.events]
        self.assertIn("audio-start", event_types)
        self.assertIn("audio-chunk", event_types)
        self.assertIn("audio-stop", event_types)
        self.assertEqual(event_types[-1], "synthesize-stopped")
        # The whole stream is bracketed by exactly one audio-start/audio-stop.
        self.assertEqual(event_types.count("audio-start"), 1)
        self.assertEqual(event_types.count("audio-stop"), 1)

    def test_synthesize_error_is_reported_without_crash(self):
        class FakeSynthesizer(_LockMixin):
            def synthesize(self, text, *, voice_name, options):
                raise ValueError("missing voice")

        handler = CollectingHandler(
            cli_args=SimpleNamespace(no_streaming=False, samples_per_chunk=8),
            synthesizer=FakeSynthesizer(),
        )

        result = self.run_async(handler.handle_event(Event("synthesize", {"text": "Ala."})))

        self.assertTrue(result)
        self.assertEqual(handler.events[-1].type, "error")
        self.assertEqual(handler.events[-1].data["code"], "ValueError")

    def test_streaming_error_closes_stream_and_recovers(self):
        class FakeSynthesizer(_LockMixin):
            def __init__(self):
                self.fail = True

            def synthesize_stream(self, text, *, voice_name, options):
                if self.fail:
                    raise ValueError("boom")
                yield [0.1], 48000

            def synthesize(self, text, *, voice_name, options):
                return SynthesisResult(
                    audio=[0.1, -0.1],
                    sample_rate=48000,
                    voice="mira",
                    language=None,
                    processing_time=0.1,
                )

        synthesizer = FakeSynthesizer()
        handler = CollectingHandler(
            cli_args=SimpleNamespace(no_streaming=False, samples_per_chunk=8),
            synthesizer=synthesizer,
        )

        self.run_async(handler.handle_event(Event("synthesize-start", {})))
        self.run_async(handler.handle_event(Event("synthesize-chunk", {"text": "Ala ma kota."})))
        self.run_async(handler.handle_event(Event("synthesize-stop", {})))

        event_types = [event.type for event in handler.events]
        self.assertIn("error", event_types)
        # The stream must still be closed so Home Assistant does not hang.
        self.assertEqual(event_types.count("synthesize-stopped"), 1)
        self.assertFalse(handler._streaming)

        # The connection is persistent: the next plain synthesize must work.
        synthesizer.fail = False
        handler.events.clear()
        self.run_async(handler.handle_event(Event("synthesize", {"text": "Ala."})))
        self.assertEqual([event.type for event in handler.events][0], "audio-start")

    def test_language_only_voice_falls_back_to_default(self):
        calls = []

        class FakeSynthesizer(_LockMixin):
            def synthesize(self, text, *, voice_name, options):
                calls.append(voice_name)
                return SynthesisResult(
                    audio=[0.1],
                    sample_rate=48000,
                    voice="mira",
                    language=None,
                    processing_time=0.1,
                )

        handler = CollectingHandler(
            cli_args=SimpleNamespace(no_streaming=False, samples_per_chunk=8),
            synthesizer=FakeSynthesizer(),
        )

        self.run_async(
            handler.handle_event(Event("synthesize", {"text": "Hej.", "voice": {"language": "pl"}}))
        )

        # A language-only voice is not a profile name; the synthesizer decides
        # the default profile itself.
        self.assertEqual(calls, [None])

    def test_describe_rebuilds_info_from_factory(self):
        infos = [
            Info(tts=[TtsProgram(
                name="dots.tts",
                attribution=Attribution(name="test", url="https://example.invalid"),
                installed=True,
                description="test",
                version=None,
                voices=[],
            )]),
        ]
        calls = []

        def factory():
            calls.append(1)
            return infos[0]

        handler = CollectingHandler(
            cli_args=SimpleNamespace(no_streaming=False, samples_per_chunk=8),
            synthesizer=SimpleNamespace(),
        )
        handler._wyoming_info = factory

        self.run_async(handler.handle_event(Event("describe", {})))
        self.run_async(handler.handle_event(Event("describe", {})))

        self.assertEqual(len(calls), 2)


if __name__ == "__main__":
    unittest.main()
