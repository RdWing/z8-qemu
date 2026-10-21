# Copyright (C) 2026 RdWing: Z8 adaptation.
"""Extract production C functions for synthetic checks."""
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
def function(source, name):
    start = source.rfind('static ', 0, source.index(name + '('))
    opening = source.index('{', start)
    depth = 1
    end = opening + 1
    while depth:
        depth += (source[end] == '{') - (source[end] == '}')
        end += 1
    return source[start:end] + '\n'
