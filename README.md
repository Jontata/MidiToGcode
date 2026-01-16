# Simple Python MIDI to G-Code Converter

Convert MIDI files to M1006 G-Code format for playing music on Bambu Lab 3D printers.

## Overview

This simple tool converts MIDI files into G-Code commands that can make Bambu Lab 3D printers play music using their built-in buzzer. The converter supports polyphonic playback (num. voices), tempo adjustment, and duration quantization.

Specifically tailored to work on Bambu Lab printers (A1, P1P, X1C, etc.) which use M1006 "prompt sound" commands.

## Acknowledgments

- Bambu Lab for the M1006 G-Code specification
- The `mido` library for MIDI file parsing
- Sample MIDI files from various open sources
