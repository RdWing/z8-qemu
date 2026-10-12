# SPDX-License-Identifier: GPL-2.0-or-later
# Copyright (C) 2026 RdWing
"""Install the Z8 source overlay in an explicitly selected QEMU 11.1.1 tree."""
from pathlib import Path
import argparse
import hashlib
import json
import re

HERE = Path(__file__).resolve().parent

DMA_OLD = '''    const uint64_t size   = (uint64_t)viewport->limit - base + 1;
    const bool enabled    = viewport->cr[1] & DESIGNWARE_PCIE_ATU_ENABLE;'''
DMA_NEW = '''    const uint64_t limit = (base & ~UINT64_C(0xffffffff)) | viewport->limit;
    const uint64_t size = limit >= base ? limit - base + 1 : 0;
    const bool enabled = size && (viewport->cr[1] & DESIGNWARE_PCIE_ATU_ENABLE);'''
TCG_OLD = '''    case GDB_BREAKPOINT_SW:
    case GDB_BREAKPOINT_HW:
        CPU_FOREACH(cpu) {
            err = cpu_breakpoint_remove(cpu, addr, BP_GDB);
            if (err) {
                break;
            }
        }
        return err;'''
TCG_NEW = '''    case GDB_BREAKPOINT_SW:
    case GDB_BREAKPOINT_HW: {
        int removed = 0;
        CPU_FOREACH(cpu) {
            err = cpu_breakpoint_remove(cpu, addr, BP_GDB);
            if (!err) { removed++; }
            else if (err != -ENOENT) { return err; }
        }
        return removed ? 0 : -ENOENT;
    }'''
KCONFIG = '''config NIKON_Z8_LAB
    bool
    depends on AARCH64 && TCG
    select ARM_GIC
    select ARM_GICV5
    select GENERIC_LOADER
    select SDHCI
    select PCI_EXPRESS_DESIGNWARE
    select NVME_PCI
    select SPDM_SOCKET
'''

def replace_verified(body, old, new, label):
    if new in body:
        return body
    if body.count(old) != 1:
        raise ValueError('Unexpected ' + label + ' source; preserve and review it')
    return body.replace(old, new, 1)

def plan(source):
    source = Path(source).resolve()
    if (source/'VERSION').read_text().strip() != '11.1.1':
        raise ValueError('QEMU 11.1.1 source required')
    changes = {}
    p = source/'hw/arm/Kconfig'
    body = p.read_text()
    pattern = r'^config NIKON_Z8_LAB\n.*?(?=^config |\Z)'
    if re.search(pattern, body, re.M | re.S):
        body = re.sub(pattern, KCONFIG + '\n', body, count=1, flags=re.M | re.S)
    else:
        body += '\n' + KCONFIG
    changes[p] = (body.rstrip() + '\n').encode()
    p = source/'hw/arm/meson.build'
    body = ''.join(line for line in p.read_text().splitlines(True) if 'CONFIG_NIKON_Z8_LAB' not in line)
    marker = "hw_common_arch += {'arm': arm_common_ss}"
    if body.count(marker) != 1:
        raise ValueError('QEMU 11 ARM source-set marker not found')
    additions = "arm_common_ss.add(when: 'CONFIG_NIKON_Z8_LAB', if_true: files('nikon-z8-lab.c'))\n"
    additions += "arm_common_ss.add(when: 'CONFIG_NIKON_Z8_LAB', if_true: dependency('libjpeg', required: true))\n"
    changes[p] = body.replace(marker, additions + marker).encode()
    p = source/'configs/devices/aarch64-softmmu/default.mak'
    body = p.read_text()
    line = 'CONFIG_NIKON_Z8_LAB=y'
    if line not in body.splitlines():
        body += '\n' + line + '\n'
    changes[p] = body.encode()
    for name, old, new, label in [
        ('hw/pci-host/designware.c', DMA_OLD, DMA_NEW, 'DesignWare'),
        ('accel/tcg/tcg-accel-ops.c', TCG_OLD, TCG_NEW, 'SMP breakpoint'),
    ]:
        p = source/name
        changes[p] = replace_verified(p.read_text(), old, new, label).encode()
    for overlay in sorted(HERE.glob('nikon-z8-*')):
        if overlay.suffix not in ('.c', '.h'):
            continue
        p = source/'hw/arm'/overlay.name
        data = overlay.read_bytes()
        if p.exists() and p.read_bytes() != data:
            raise ValueError('Existing divergent Z8 overlay: ' + str(p))
        changes[p] = data
    return source, changes

def prepare(source, check=False):
    source, changes = plan(source)
    if check:
        return {'files': len(changes), 'source_changed': False}
    # Plan and validate every change before writing; preserve recoverable inputs.
    backup = source/'.z8-qemu-backup'
    backup.mkdir(exist_ok=True)
    for p, data in changes.items():
        prior = backup/p.relative_to(source)
        if p.exists() and not prior.exists():
            prior.parent.mkdir(parents=True, exist_ok=True)
            prior.write_bytes(p.read_bytes())
        p.write_bytes(data)
    receipt = {str(p.relative_to(source)): hashlib.sha256(data).hexdigest() for p, data in changes.items()}
    (source/'.z8-qemu-overlay.json').write_text(json.dumps(receipt, indent=2)+'\n')
    return receipt

if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('source', type=Path)
    parser.add_argument('--check', action='store_true', help='Validate the planned changes without writing')
    args = parser.parse_args()
    print(json.dumps(prepare(args.source, args.check), indent=2))
