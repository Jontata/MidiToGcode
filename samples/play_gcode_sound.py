import re
import sys
import wave
import numpy as np
import sounddevice as sd

# Config
SAMPLE_RATE = 44100
MASTER_VOL = 0.25
INTER_CMD_GAP_MS = 8
FADE_MS = 4
OCTAVE_SHIFT = 12

def midi_to_freq(midi_note: float) -> float:
    """
    Interpret values like 48, 50, 53, 55 as MIDI notes.
    69 => 440 Hz (A4)
    """
    midi_note = float(np.clip(midi_note + OCTAVE_SHIFT, 0, 127))
    return 440.0 * (2.0 ** ((midi_note - 69.0) / 12.0))


def stepperish_wave(freq: np.ndarray, t: np.ndarray) -> np.ndarray:
    """
    Stepper motors don't sound like pure sine waves.
    This approximates the buzzy tone with harmonics.
    """
    x = np.sin(2 * np.pi * freq * t)
    x += 0.45 * np.sin(2 * np.pi * (2 * freq) * t)
    x += 0.20 * np.sin(2 * np.pi * (3 * freq) * t)
    return x.astype(np.float32)


def synth_note(freq_hz: float, duration_ms: int, amp: float) -> np.ndarray:
    duration_s = max(0.001, duration_ms / 1000.0)
    n = int(SAMPLE_RATE * duration_s)
    t = np.linspace(0, duration_s, n, endpoint=False)

    # Constant pitch note
    freq = np.full_like(t, freq_hz, dtype=np.float32)
    x = stepperish_wave(freq, t)

    # Fade in/out
    fade = int((FADE_MS / 1000.0) * SAMPLE_RATE)
    fade = min(fade, n // 2)
    if fade > 0:
        env = np.ones(n, dtype=np.float32)
        env[:fade] = np.linspace(0, 1, fade, dtype=np.float32)
        env[-fade:] = np.linspace(1, 0, fade, dtype=np.float32)
        x *= env

    # Apply amplitude
    x *= float(amp)
    return x


def parse_params(line: str) -> dict[str, int]:
    return {k: int(v) for k, v in re.findall(r"([A-Z])(-?\d+)", line)}


def extract_voices(p: dict[str, int]):
    """
    For this M1006 flavor, treat A/C/E as note numbers (MIDI-ish).
    0 means the voice is off.

    D/F/M/N appear to shape the sound on the printer; we use them only
    to derive a rough amplitude.
    """
    L = int(p.get("L", 100))

    # Notes (0 => off)
    notes = []
    for key in ("A", "C", "E"):
        n = p.get(key, 0)
        if n and n > 0:
            notes.append(n)

    # Rough amplitude heuristic:
    shape_vals = [p.get(k, 0) for k in ("B", "D", "F", "M", "N")]
    shape = max(shape_vals) if shape_vals else 0
    # Map shape (~0..100-ish) into a sane amplitude multiplier
    amp = np.clip(0.10 + (shape / 100.0) * 0.35, 0.10, 0.55)

    return L, notes, float(amp)


def mix(segments: list[np.ndarray]) -> np.ndarray:
    if not segments:
        return np.zeros(0, dtype=np.float32)
    out = np.zeros_like(segments[0], dtype=np.float32)
    for s in segments:
        out += s
    out /= max(1, len(segments))  # prevent clipping when multiple voices
    return out


def gcode_to_audio(path: str, verbose: bool = True) -> np.ndarray:
    chunks = []
    idx = 0

    with open(path, "r", encoding="utf-8", errors="ignore") as f:
        for raw in f:
            line = raw.strip()
            if not line or line.startswith(";"):
                continue

            if line.startswith("M1006 W"):
                # tiny drain pause
                chunks.append(np.zeros(int(0.02 * SAMPLE_RATE), dtype=np.float32))
                continue

            if not line.startswith("M1006 "):
                continue

            p = parse_params(line)

            # Skip M1006 S1 and similar non-note setup calls
            if not any(k in p for k in ("A", "C", "E", "L")):
                continue

            L, notes, amp = extract_voices(p)
            n_samples = int(SAMPLE_RATE * (L / 1000.0))

            if not notes:
                # real rest
                seg = np.zeros(n_samples, dtype=np.float32)
            else:
                # synth each active voice as a constant-pitch note
                voices = []
                for n in notes:
                    f_hz = midi_to_freq(n)
                    voices.append(synth_note(f_hz, L, amp))
                seg = mix(voices)

            chunks.append(seg)

            # add a small inter-command gap to restore “pauses”
            gap = np.zeros(int(SAMPLE_RATE * (INTER_CMD_GAP_MS / 1000.0)), dtype=np.float32)
            chunks.append(gap)

            idx += 1
            if verbose and idx <= 60:
                # keep console sane: print first ~60 lines
                note_str = ",".join(str(n) for n in notes) if notes else "REST"
                print(f"{idx:03d}: L={L}ms notes={note_str} amp={amp:.2f}")

    if not chunks:
        raise RuntimeError("No playable M1006 commands found. Check path / contents.")

    audio = np.concatenate(chunks).astype(np.float32)
    audio *= MASTER_VOL
    audio = np.clip(audio, -1.0, 1.0)
    return audio


def write_wav(path: str, audio: np.ndarray):
    audio_i16 = (np.clip(audio, -1.0, 1.0) * 32767).astype(np.int16)
    with wave.open(path, "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(SAMPLE_RATE)
        wf.writeframes(audio_i16.tobytes())


def main():
    # Can also be updated to point to demo G-Code files
    gcode_path = "samples/GCode/john_cena_time_is_now.gcode"

    device = None
    if "--device" in sys.argv:
        i = sys.argv.index("--device")
        device = int(sys.argv[i + 1])

    # Test beep
    print("Test beep...")
    test = synth_note(440.0, 250, 0.4) * MASTER_VOL
    sd.play(test, SAMPLE_RATE, device=device)
    sd.wait()

    audio = gcode_to_audio(gcode_path, verbose=True)

    print("\nPlaying... (press Enter to stop)")

    import threading
    import time

    stop_flag = threading.Event()

    def playback():
        sd.play(audio, SAMPLE_RATE, device=device)
        sd.wait()
        stop_flag.set()

    def wait_for_stop():
        input()
        stop_flag.set()
        sd.stop()

    play_thread = threading.Thread(target=playback)
    stop_thread = threading.Thread(target=wait_for_stop)
    play_thread.start()
    stop_thread.start()
    while not stop_flag.is_set():
        time.sleep(0.1)

    print("Done.")

    # wav_path = gcode_path.replace(".gcode", ".wav")
    # write_wav(wav_path, audio)
    # print(f"Wrote WAV: {wav_path}")


if __name__ == "__main__":
    main()
