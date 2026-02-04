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
    
    prev_note = None

    for slice_time, slice_duration, notes_in_slice in time_slices:
        # Limit polyphony using a melody-aware heuristic
        notes_to_play, prev_note = _select_notes_for_slice(
            notes_in_slice, prev_note, slice_time, max_polyphony
        )
        
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
    
    return _merge_adjacent_commands(gcode_commands)


def _create_time_slices(events: List[Tuple], min_duration: float) -> List[Tuple]:
    """
    Convert note events into time slices with active notes.
    
    Returns:
        List of (start_time, duration, [(note, velocity, note_start_time)]) tuples
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
    active_notes = {}  # note -> (velocity, start_time)
    last_time = 0.0
    
    for event_time, event_type, note, velocity in timeline:
        # Create slice for the time that just passed
        if event_time > last_time:
            duration = event_time - last_time
            if duration >= min_duration:
                note_list = [(n, v, s) for n, (v, s) in active_notes.items()]
                slices.append((last_time, duration, note_list))
        
        # Update active notes
        if event_type == 'start':
            active_notes[note] = (velocity, event_time)
        else:
            active_notes.pop(note, None)
        
        last_time = event_time
    
    return slices

def _select_notes_for_slice(notes, prev_note, slice_time, max_polyphony,
                            attack_window=0.06,
                            w_pitch=0.55, w_vel=0.30, w_cont=0.15, w_attack=0.10):
    """
    Choose notes for a time slice using a melody-aware heuristic.
    """
    attacks = [t for t in notes if (slice_time - t[2]) <= attack_window]

    if attacks:
        scored = []
        for note, velocity, start_time in attacks:
            if prev_note is None:
                continuity = 0.0
            else:
                continuity = max(0.0, 1.0 - abs(note - prev_note) / 24.0)

            score = (
                w_pitch * (note / 127.0) +
                w_vel * (velocity / 127.0) +
                w_cont * continuity +
                w_attack
            )
            scored.append((score, note))

        scored.sort(reverse=True)
        chosen = [n for _, n in scored[:max_polyphony]]
        new_prev = chosen[0] if chosen else prev_note
        return chosen, new_prev

    if prev_note is not None and any(n == prev_note for n, _, _ in notes):
        return [prev_note], prev_note

    return [], prev_note


def _merge_adjacent_commands(commands: List[str]) -> List[str]:
    def parse(cmd: str):
        parts = cmd.split()
        if not parts or parts[0] != "M1006":
            return None
        params = {}
        for part in parts[1:]:
            if part:
                params[part[0]] = int(part[1:])
        return params

    def build(params: dict) -> str:
        order = ['A', 'B', 'L', 'C', 'D', 'M', 'E', 'F', 'N']
        return "M1006 " + " ".join(f"{k}{params[k]}" for k in order)

    merged = []
    prev_params = None

    for cmd in commands:
        params = parse(cmd)
        if params is None:
            merged.append(cmd)
            prev_params = None
            continue

        if prev_params is not None:
            prev_cmp = dict(prev_params)
            cur_cmp = dict(params)
            prev_cmp.pop('L', None)
            cur_cmp.pop('L', None)
            if prev_cmp == cur_cmp:
                prev_params['L'] += params.get('L', 0)
                merged[-1] = build(prev_params)
                continue

        merged.append(cmd)
        prev_params = params

    return merged


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
