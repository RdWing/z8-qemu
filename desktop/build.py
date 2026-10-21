# SPDX-License-Identifier: GPL-2.0-or-later
"""Build the local macOS workbench. Nikon inputs and QEMU are never bundled."""
import argparse
from pathlib import Path
import plistlib
import platform
import re
import shutil
import subprocess

ROOT = Path(__file__).resolve().parents[1]
p = argparse.ArgumentParser(description=__doc__)
p.add_argument('--output', type=Path, default=ROOT/'.local/desktop/Z8.app')
a = p.parse_args()
bundle = a.output.resolve()
if bundle.exists():
    p.error('Choose a new output app directory')
resources = bundle/'Contents/Resources'
executable = bundle/'Contents/MacOS/Z8'
resources.mkdir(parents=True); executable.parent.mkdir()
cache=ROOT/'.local/swift-module-cache';cache.mkdir(parents=True,exist_ok=True)
architecture={'arm64':'arm64','x86_64':'x86_64'}[platform.machine()]
subprocess.run(['xcrun', 'swiftc', '-target', architecture+'-apple-macosx13.0', '-module-cache-path', str(cache), '-swift-version', '5', '-O', str(ROOT/'desktop/Z8.swift'),
                '-o', str(executable), '-framework', 'AppKit', '-framework', 'WebKit'], check=True)
shutil.copytree(ROOT/'tools', resources/'runtime/tools', ignore=shutil.ignore_patterns('__pycache__', '*.pyc'))
shutil.copy2(ROOT/'source-manifest.json', resources/'runtime/source-manifest.json')
styles = re.findall(r'<style>(.*?)</style>', (ROOT/'tools/control.html').read_text(), re.S)
assert len(styles) == 1
(resources/'workbench.css').write_text(styles[0])
(bundle/'Contents/Info.plist').write_bytes(plistlib.dumps(dict(
    CFBundleExecutable='Z8', CFBundleIdentifier='org.rdwing.z8-emulator',
    CFBundleName='Z8 emulator', CFBundleVersion='1', CFBundleShortVersionString='0.1',
    CFBundlePackageType='APPL', LSMinimumSystemVersion='13.0', NSHighResolutionCapable=True,
    NSAppTransportSecurity={'NSAllowsLocalNetworking': True, 'NSAllowsArbitraryLoadsInWebContent': True})))
subprocess.run(['codesign', '--force', '--sign', '-', str(bundle)], check=True)
print(bundle)
