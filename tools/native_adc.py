# SPDX-License-Identifier: GPL-2.0-or-later
"""Explicit numeric ADC input profiles; no inherited dial or voltage mapping."""
import re


def validate(value):
    if not isinstance(value,str) or not 1<=len(value)<=1024:
        raise ValueError('ADC inputs require ADC.CH=VALUE batches')
    seen=set()
    for item in value.split(':'):
        match=re.fullmatch(r'([0-9]+)\.([0-9]+)=([0-9]+)',item)
        if not match:raise ValueError('ADC inputs require decimal ADC.CH=VALUE batches')
        adc,channel,sample=map(int,match.groups())
        if not 1<=adc<=3 or not 0<=channel<=18 or not 0<=sample<=4095 or (adc,channel) in seen:
            raise ValueError('ADC requires unique ADC 1..3, channel 0..18 and sample 0..4095')
        seen.add((adc,channel))
    return value
