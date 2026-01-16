"""
MIDI to M1006 G-Code converter for Bambu Lab 3D printers.

This module converts MIDI files to M1006 G-Code commands that can play music
on Bambu Lab 3D printers using their built-in buzzer functionality.
"""

import mido
from typing import List, Tuple


def midi_to_gcode(midi_path: str, output_path: str = None, 
                  max_polyphony: int = 2, min_note_duration_ms: int = 50,
                  tempo_scale: float = 1.0, quantize_duration_ms: int = None) -> str:
    """ Convert a MIDI file to M1006 G-Code format for Bambu Lab printers."""
    try:
        midi = mido.MidiFile(midi_path)
    except Exception as e:
        raise ValueError(f"Unexpected error loading MIDI file: {e}") from e
    
    # Convert MIDI to note events with timing in seconds
    notes = _extract_notes_from_midi(midi)
    
    # Apply tempo scaling
    if tempo_scale != 1.0:
        notes = [(t / tempo_scale, n, v, d / tempo_scale) for t, n, v, d in notes]
    
    # Generate G-Code commands
    gcode_lines = _notes_to_gcode(notes, max_polyphony, min_note_duration_ms, quantize_duration_ms)
    
    # Build final G-Code with header and footer
    gcode = _build_gcode_file(gcode_lines)
    
    # Write to file if requested
    if output_path:
        with open(output_path, 'w') as f:
            f.write(gcode)
    
    return gcode


def _extract_notes_from_midi(midi: mido.MidiFile) -> List[Tuple[float, int, int, float]]:
    """
    Extract note events from MIDI file with proper tempo handling.
    
    Returns:
        List of (time_in_seconds, midi_note, velocity, duration_in_seconds) tuples
    """
    events = []
    
    # Process each track separately
    for track_idx, track in enumerate(midi.tracks):
        track_time_ticks = 0
        track_time_seconds = 0.0
        tempo = 500000  # Default tempo: 500,000 microseconds per beat (120 BPM)
        active_notes = {}  # {note_number: (start_time_seconds, velocity)}
        
        for msg in track:
            # Accumulate ticks
            track_time_ticks += msg.time
            
            # Convert tick delta to seconds
            tick_duration_seconds = mido.tick2second(
                msg.time, midi.ticks_per_beat, tempo
            )
            track_time_seconds += tick_duration_seconds
            
            # Handle tempo changes
            if msg.type == 'set_tempo':
                tempo = msg.tempo
                
            # Handle note on/off
            if msg.type == 'note_on' and msg.velocity > 0:
                # Note starts
                active_notes[msg.note] = (track_time_seconds, msg.velocity)
                
            elif msg.type == 'note_off' or (msg.type == 'note_on' and msg.velocity == 0):
                # Note ends
                if msg.note in active_notes:
                    start_time, velocity = active_notes.pop(msg.note)
                    duration = track_time_seconds - start_time
                    events.append((start_time, msg.note, velocity, duration))
    
    # Sort events by start time
    events.sort(key=lambda x: x[0])
    
    return events


def _notes_to_gcode(events: List[Tuple], max_polyphony: int, 
                    min_duration_ms: int, quantize_duration_ms: int = None) -> List[str]:
    """
    Convert note events to M1006 G-Code commands.
    
    Args:
        events: List of (start_time, note, velocity, duration) tuples
        max_polyphony: Maximum simultaneous notes
        min_duration_ms: Minimum note duration
        quantize_duration_ms: If set, use this fixed duration for all notes
        
    Returns:
        List of M1006 command strings
    """
    if not events:
        return []
    
    gcode_commands = []
    
    # Group events into time slices
    time_slices = _create_time_slices(events, min_duration_ms / 1000.0)
    
    for slice_time, slice_duration, notes_in_slice in time_slices:
        # Limit polyphony
        notes_to_play = notes_in_slice[:max_polyphony]
        
        # Calculate duration
        if quantize_duration_ms:
            duration_ms = quantize_duration_ms
        else:
            duration_ms = int(slice_duration * 1000)
            duration_ms = max(min_duration_ms, duration_ms)
        
        if not notes_to_play:
            # Rest
            gcode_commands.append(_create_rest_command(duration_ms))
        else:
            # Play notes
            cmd = _create_note_command(notes_to_play, duration_ms)
            gcode_commands.append(cmd)
    
    return gcode_commands


def _create_time_slices(events: List[Tuple], min_duration: float) -> List[Tuple]:
    """
    Convert note events into time slices with active notes.
    
    Returns:
        List of (start_time, duration, [notes]) tuples
    """
    if not events:
        return []
    
    # Create a timeline of all event changes
    timeline = []
    
    for start_time, note, velocity, duration in events:
        timeline.append((start_time, 'start', note, velocity))
        timeline.append((start_time + duration, 'end', note, velocity))
    
    timeline.sort(key=lambda x: (x[0], x[1] == 'end'))  # ends before starts at same time
    
    slices = []
    active_notes = {}
    last_time = 0.0
    
    for event_time, event_type, note, velocity in timeline:
        # Create slice for the time that just passed
        if event_time > last_time and active_notes:
            duration = event_time - last_time
            if duration >= min_duration:
                note_list = [n for n in active_notes.keys()]
                slices.append((last_time, duration, note_list))
        elif event_time > last_time and not active_notes:
            # Rest period
            duration = event_time - last_time
            if duration >= min_duration:
                slices.append((last_time, duration, []))
        
        # Update active notes
        if event_type == 'start':
            active_notes[note] = velocity
        else:
            active_notes.pop(note, None)
        
        last_time = event_time
    
    return slices


def _create_note_command(notes: List[int], duration_ms: int) -> str:
    """
    Create an M1006 command for playing notes.
    
    The M1006 format uses:
    - C, E: MIDI note numbers for up to 2 voices
    - L: Duration in milliseconds
    - A, B, D, F, M, N: Sound shaping parameters
    """
    # Standard parameters for active notes
    params = {
        'A': 0,
        'B': 10,
        'L': duration_ms,
        'D': 15,
        'M': 75,
        'F': 10,
        'N': 75
    }
    
    # Assign notes to C and E parameters
    if len(notes) >= 1:
        params['C'] = notes[0]
    else:
        params['C'] = 0
        
    if len(notes) >= 2:
        params['E'] = notes[1]
    else:
        params['E'] = notes[0] if notes else 0
    
    # Build command string
    cmd = "M1006"
    for key in ['A', 'B', 'L', 'C', 'D', 'M', 'E', 'F', 'N']:
        cmd += f" {key}{params[key]}"
    
    return cmd


def _create_rest_command(duration_ms: int) -> str:
    """
    Create an M1006 command for a rest (silence).
    """
    return f"M1006 A0 B10 L{duration_ms} C0 D15 M60 E0 F10 N60"


def _build_gcode_file(commands: List[str]) -> str:
    """
    Build the complete G-Code file with header and footer.
    """
    lines = [
        ";=====start printer sound ===================",
        "M17",
        "M400 S1",
        "M1006 S1",
        ""
    ]
    
    lines.extend(commands)
    
    lines.extend([
        "",
        "M1006 W",
        "M18",
        ";=====end printer sound ==================="
    ])
    
    return '\n'.join(lines) + '\n'


def convert_midi_file(input_midi: str, output_gcode: str = None, **kwargs) -> str:
    """Convert a MIDI file to G-Code and save to output file. """
    if output_gcode is None:
        output_gcode = input_midi.replace('.mid', '.gcode').replace('.midi', '.gcode')
    
    return midi_to_gcode(input_midi, output_gcode, **kwargs)
