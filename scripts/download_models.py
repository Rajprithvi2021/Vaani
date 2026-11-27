"""Download the open-source models used by the app.

    python scripts/download_models.py            # Piper voices (text-to-speech), ~120 MB
    python scripts/download_models.py --whisper  # also the faster-whisper model for STT_PROVIDER=whisper

Voices come from the official Piper voice repository on Hugging Face (rhasspy/piper-voices);
Whisper weights from Systran's faster-whisper conversions.
"""
import argparse
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.config import get_settings  # noqa: E402


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--whisper", action="store_true", help="also download the faster-whisper model")
    args = parser.parse_args()
    s = get_settings()

    s.piper_voices_dir.mkdir(parents=True, exist_ok=True)
    print(f"Downloading Piper voices into {s.piper_voices_dir} ...")
    subprocess.run([sys.executable, "-m", "piper.download_voices", s.piper_voice_en, s.piper_voice_hi,
                    "--download-dir", str(s.piper_voices_dir)], check=True)

    if args.whisper:
        from app.stt.whisper_local import load_model

        print(f"Downloading/loading faster-whisper '{s.whisper_model}' ...")
        load_model(s.whisper_model, s.whisper_device, s.whisper_compute_type)
    print("Done.")


if __name__ == "__main__":
    main()
