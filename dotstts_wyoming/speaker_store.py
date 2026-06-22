"""Speaker profile discovery for dots.tts reference prompts."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class SpeakerProfile:
    name: str
    prompt_audio_path: Path
    prompt_text: str


@dataclass(frozen=True)
class InvalidSpeakerProfile:
    name: str
    reason: str
    path: Path


class SpeakerProfileNotFoundError(ValueError):
    pass


class SpeakerStore:
    def __init__(self, speaker_dir: str | Path) -> None:
        self.speaker_dir = Path(speaker_dir)

    def _profile_from_dir(self, profile_dir: Path) -> SpeakerProfile | InvalidSpeakerProfile:
        prompt_path = profile_dir / "prompt.txt"
        wav_paths = sorted(profile_dir.glob("*.wav"))

        if not wav_paths:
            return InvalidSpeakerProfile(profile_dir.name, "missing .wav reference audio", profile_dir)
        if not prompt_path.exists():
            return InvalidSpeakerProfile(profile_dir.name, "missing prompt.txt transcript", profile_dir)

        prompt_text = prompt_path.read_text(encoding="utf-8").strip()
        if not prompt_text:
            return InvalidSpeakerProfile(profile_dir.name, "empty prompt.txt transcript", profile_dir)

        reference = profile_dir / "reference.wav"
        if not reference.exists():
            reference = wav_paths[0]

        return SpeakerProfile(
            name=profile_dir.name,
            prompt_audio_path=reference,
            prompt_text=prompt_text,
        )

    def _scan(self) -> tuple[list[SpeakerProfile], list[InvalidSpeakerProfile]]:
        valid: list[SpeakerProfile] = []
        invalid: list[InvalidSpeakerProfile] = []
        if not self.speaker_dir.exists():
            return valid, invalid

        for child in sorted(self.speaker_dir.iterdir()):
            if not child.is_dir():
                continue
            profile = self._profile_from_dir(child)
            if isinstance(profile, SpeakerProfile):
                valid.append(profile)
            else:
                invalid.append(profile)
        return valid, invalid

    def list_profiles(self) -> list[SpeakerProfile]:
        return self._scan()[0]

    def list_invalid_profiles(self) -> list[InvalidSpeakerProfile]:
        return self._scan()[1]

    def get_profile(self, name: str | None, default_name: str | None = None) -> SpeakerProfile:
        requested = name or default_name
        if not requested:
            raise SpeakerProfileNotFoundError("No voice profile was requested.")

        # Direct lookup instead of scanning every profile; guard against path
        # traversal since the voice name comes from the client (reject anything
        # that is not a single, plain directory component).
        if Path(requested).name == requested and requested not in (".", ".."):
            profile_dir = self.speaker_dir / requested
            if profile_dir.is_dir():
                profile = self._profile_from_dir(profile_dir)
                if isinstance(profile, SpeakerProfile):
                    return profile

        raise SpeakerProfileNotFoundError(
            f"Voice profile '{requested}' is missing or invalid. "
            "Create data/speakers/<voice>/reference.wav and data/speakers/<voice>/prompt.txt."
        )

    def ensure_default_profile_hint(self, default_name: str | None) -> None:
        if not default_name:
            return
        if self.speaker_dir.exists() and any(profile.name == default_name for profile in self.list_profiles()):
            return

        hint_dir = self.speaker_dir / default_name
        hint_dir.mkdir(parents=True, exist_ok=True)
        hint_path = hint_dir / "README.txt"
        if not hint_path.exists():
            hint_path.write_text(
                "Add reference.wav and prompt.txt here to publish this dots.tts voice profile.\n",
                encoding="utf-8",
            )

    def profile_names(self) -> list[str]:
        return [profile.name for profile in self.list_profiles()]

    def health_payload(self) -> dict:
        valid, invalid = self._scan()
        return {
            "valid": [
                {
                    "name": profile.name,
                    "prompt_audio": str(profile.prompt_audio_path),
                    "prompt_text_chars": len(profile.prompt_text),
                }
                for profile in valid
            ],
            "invalid": [
                {
                    "name": profile.name,
                    "reason": profile.reason,
                    "path": str(profile.path),
                }
                for profile in invalid
            ],
        }
