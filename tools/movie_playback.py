# SPDX-License-Identifier: GPL-2.0-or-later
# Copyright (C) 2026 RdWing
"""Explicit functional saved-Movie decoder profile; audio TX remains open."""
PROPERTIES = (
    'video-nr-reset-model', 'video-initial-reset-model',
    'video-processing-config-model', 'wave5-vpu-model',
    'wave5-host-codec-diagnostic', 'wave5-host-decoder-diagnostic',
    'video-main-output-model', 'video-yuv-output-events-model',
    'event1508-programmed-clock-model', 'video-preview-ram-model',
    'lpcm-host-conversion-model', 'lpcm-ram-aperture-fixture',
    'serial5-audio-config-model', 'serial5-audio-idle-drain-model',
    'serial5-tx-drain-model',
)

def attach(guest):
    index = guest.command.index('-M') + 1
    guest.command[index] += ',' + ','.join(name + '=on' for name in PROPERTIES)
    guest.data['experimental_movie_playback'] = {
        'host_decoder': 'libavcodec', 'linear_8bit_output': True,
        'properties': list(PROPERTIES), 'audio_tx_qualified': False,
        'vendor_microcode_executed': False, 'physical_timing_verified': False,
    }
