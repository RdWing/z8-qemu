# SPDX-License-Identifier: GPL-2.0-or-later
# Copyright (C) 2026 RdWing
"""Explicit functional saved-Movie video and stereo PCM output profile."""
PROPERTIES = (
    'video-nr-reset-model', 'video-initial-reset-model', 'backend-program-epoch-model',
    'video-processing-config-model', 'wave5-vpu-model',
    'wave5-host-codec-diagnostic', 'wave5-host-decoder-diagnostic',
    'video-main-output-model', 'video-yuv-output-events-model',
    'event1508-programmed-clock-model', 'video-preview-ram-model',
    'lpcm-host-conversion-model', 'lpcm-ram-aperture-fixture',
    'serial5-audio-config-model', 'serial5-audio-idle-drain-model',
    'serial5-tx-drain-model', 'serial5-playback-ram-aperture-fixture',
)

def attach(guest, audio_output="auto"):
    audio_output = validate_audio_output(audio_output)
    index = guest.command.index('-M') + 1
    guest.command[index] += ',' + ','.join(name + '=on' for name in PROPERTIES)
    if audio_output != 'none':
        backend = 'auto' if audio_output == 'auto' else 'z8playback'
        guest.command[index] += ',serial5-audio-output=' + backend
        if audio_output != 'auto':
            guest.command += ['-audiodev', 'wav,id=z8playback,path=' + audio_output +
                              ',out.frequency=48000,out.channels=2,out.format=s16']
    guest.data['experimental_movie_playback'] = {
        'host_decoder': 'libavcodec', 'linear_8bit_output': True,
        'properties': list(PROPERTIES), 'audio_output': audio_output, 'audio_tx_qualified': True, 'audio_format': '48000 Hz stereo LE32',
        'vendor_microcode_executed': False, 'physical_timing_verified': False,
    }


def validate_audio_output(value):
    from pathlib import Path
    if not isinstance(value, str) or not value:
        raise ValueError('Movie audio output must be auto, none or a new WAV path')
    if value in ('auto', 'none'):
        return value
    path = Path(value).absolute()
    if (',' in str(path) or path.suffix.lower() != '.wav' or path.exists()
            or path.is_symlink() or not path.parent.is_dir()):
        raise ValueError('Choose a new WAV file in an existing directory without commas')
    return str(path)
