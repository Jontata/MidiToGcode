import sys
import os

from converter import convert_midi_file

def main():
    print("=" * 70)
    print()
    
    # Input file
    midi_file = "samples/MIDI/john_cena_time_is_now.mid"
    
    print(f"Input MIDI file: {midi_file}")
    print()
    
    # Validate file exists
    if not os.path.exists(midi_file):
        print(f"Error: File not found: {midi_file}")
        print()
        print("Please provide a valid MIDI file path.")
        return 1
    
    try:
        # BASIC CONVERSION
        # USES DEFAULT PARAMETERS
        print("1  Basic Conversion")
        print("-" * 70)
        output1 = "demo_output_basic.gcode"
        gcode1 = convert_midi_file(midi_file, output1)
        print(f"Converted to: {output1}")
        print(f"Generated {len(gcode1.splitlines())} lines of G-Code")
        print()
        
        # OPTIMIZED CONVERSION
        # PLAY WITH PARAMETERS HERE
        print("2  Custom Conversion")
        print("-" * 70)
        output2 = "demo_output_custom.gcode"
        gcode2 = convert_midi_file(
            midi_file, 
            output2,
            max_polyphony=1,
            min_note_duration_ms=75,
            quantize_duration_ms=160,
            tempo_scale=1
        )
        print(f"Converted to: {output2}")
        print(f"Generated {len(gcode2.splitlines())} lines of G-Code")
        print()
            
    except ValueError as e:
        print(f"Error converting MIDI file:")
        print()
        print(str(e))
        return 1
    except Exception as e:
        print(f"Unexpected error: {e}")
        return 1

if __name__ == "__main__":
    main()
