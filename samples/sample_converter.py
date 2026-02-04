import sys
import os

sys.path.append(os.path.dirname(os.path.abspath(__file__)) + os.sep + "..")
from converter import convert_midi_file

def main():
    print("=" * 70)
    print()
    
    # Input file
    midi_files = ["samples/MIDI/pink_panther.mid", "samples/MIDI/john_cena_time_is_now.mid", "samples/MIDI/mariobros.mid"]
    
    for midi_file in midi_files:
        print(f"Input MIDI file: {midi_file}")
        print()
        
        output = midi_file.replace("MIDI", "GCode").replace(".mid", ".gcode")
        gcode = convert_midi_file(
            midi_file, 
            output,
            max_polyphony=1,
            min_note_duration_ms=60,
            quantize_duration_ms=None,
            tempo_scale=1
        )

if __name__ == "__main__":
    main()