# SPDX-License-Identifier: GPL-2.0-or-later
# Copyright (C) 2026 RdWing
"""Install the Z8 source overlay in an explicitly selected QEMU 11.1.1 tree."""
from pathlib import Path
import argparse
import hashlib
import json
import re

HERE = Path(__file__).resolve().parent

# Inherited integration fix: the ATU limit contains only the low address
# word, so a DMA window above 4 GiB must retain the base's upper bits.
DMA_OLD = '''    const uint64_t size   = (uint64_t)viewport->limit - base + 1;
    const bool enabled    = viewport->cr[1] & DESIGNWARE_PCIE_ATU_ENABLE;'''
DMA_NEW = '''    const uint64_t limit = (base & ~UINT64_C(0xffffffff)) | viewport->limit;
    const uint64_t size = limit >= base ? limit - base + 1 : 0;
    const bool enabled = size && (viewport->cr[1] & DESIGNWARE_PCIE_ATU_ENABLE);'''
# Inherited integration fix: remove the breakpoint from every vCPU even
# when it is absent on one CPU; stop only for errors other than ENOENT.
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
# Optional M-profile board power controller hook. Other boards retain RAZ/WI
# SLEEPDEEP and their existing WFI/WFE behavior.
M_SLEEP_CPU_OLD = "    CPUARMState env;\n\n    /* Coprocessor information */"
M_SLEEP_CPU_NEW = """    CPUARMState env;

    void (*m_profile_sleep)(ARMCPU *cpu, bool wfe, void *opaque);
    void *m_profile_sleep_opaque;

    /* Coprocessor information */"""
M_SLEEP_NVIC_OLD = "        value &= ~(R_V7M_SCR_SLEEPDEEP_MASK | R_V7M_SCR_SLEEPDEEPS_MASK);"
M_SLEEP_NVIC_NEW = """        value &= ~R_V7M_SCR_SLEEPDEEPS_MASK;
        if (!cpu->m_profile_sleep) {
            value &= ~R_V7M_SCR_SLEEPDEEP_MASK;
        }"""
M_SLEEP_WFI_OLD = """    env->halt_reason = HALT_WFI;
    cs->exception_index = EXCP_HLT;"""
M_SLEEP_WFI_NEW = """    ARMCPU *cpu = env_archcpu(env);
    if (arm_feature(env, ARM_FEATURE_M) && cpu->m_profile_sleep &&
        (env->v7m.scr[M_REG_NS] & R_V7M_SCR_SLEEPDEEP_MASK)) {
        cpu->m_profile_sleep(cpu, false, cpu->m_profile_sleep_opaque);
    }
    env->halt_reason = HALT_WFI;
    cs->exception_index = EXCP_HLT;"""
M_SLEEP_WFE_OLD = """    env->halt_reason = HALT_WFE;
    cs->exception_index = EXCP_HLT;"""
M_SLEEP_WFE_NEW = """    if (arm_feature(env, ARM_FEATURE_M) && cpu->m_profile_sleep &&
        (env->v7m.scr[M_REG_NS] & R_V7M_SCR_SLEEPDEEP_MASK)) {
        cpu->m_profile_sleep(cpu, true, cpu->m_profile_sleep_opaque);
    }
    env->halt_reason = HALT_WFE;
    cs->exception_index = EXCP_HLT;"""
M_SLEEP_PATCHES = [
    ('target/arm/cpu.h', M_SLEEP_CPU_OLD, M_SLEEP_CPU_NEW),
    ('hw/intc/armv7m_nvic.c', M_SLEEP_NVIC_OLD, M_SLEEP_NVIC_NEW),
    ('target/arm/tcg/op_helper.c', M_SLEEP_WFI_OLD, M_SLEEP_WFI_NEW),
    ('target/arm/tcg/op_helper.c', M_SLEEP_WFE_OLD, M_SLEEP_WFE_NEW),
]

KCONFIG = '''config NIKON_Z8_LAB
    bool
    depends on AARCH64 && TCG
    select ARM_GIC
    select ARM_V7M
    select OR_IRQ
    select STM32F2XX_TIMER
    select STM32F2XX_USART
    select STM32F4XX_EXTI
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
    body = re.sub(r'# BEGIN Z8 OVERLAY\n.*?# END Z8 OVERLAY\n', '', p.read_text(), flags=re.S)
    body = ''.join(line for line in body.splitlines(True) if 'CONFIG_NIKON_Z8_LAB' not in line)
    marker = "hw_common_arch += {'arm': arm_common_ss}"
    if body.count(marker) != 1:
        raise ValueError('QEMU 11 ARM source-set marker not found')
    additions = "arm_common_ss.add(when: 'CONFIG_NIKON_Z8_LAB', if_true: files('nikon-z8-lab.c'))\n"
    additions += "arm_common_ss.add(when: 'CONFIG_NIKON_Z8_LAB', if_true: dependency('libjpeg', required: true))\n"
    additions += "arm_common_ss.add(when: 'CONFIG_NIKON_Z8_LAB', if_true: [dependency('x264'), dependency('x265'), dependency('libavcodec'), dependency('libavutil')])\n"
    he_sources = sorted(p.relative_to(HERE).as_posix() for p in HERE.rglob('*.cpp'))
    additions += "if config_all_devices.has_key('CONFIG_NIKON_Z8_LAB')\n"
    additions += "  add_languages('cpp', required: true, native: false)\n"
    additions += "  z8_he = static_library('z8-he-runtime', files(" + ', '.join(repr(x) for x in he_sources) + "), override_options: ['cpp_std=c++17'])\n"
    additions += "  arm_common_ss.add(when: 'CONFIG_NIKON_Z8_LAB', if_true: declare_dependency(link_with: z8_he))\nendif\n"
    changes[p] = body.replace(marker, "# BEGIN Z8 OVERLAY\n" + additions + "# END Z8 OVERLAY\n" + marker).encode()
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
    for name, old, new in M_SLEEP_PATCHES:
        p = source/name
        body = changes.get(p, p.read_bytes()).decode()
        if name.endswith('op_helper.c'):
            function = 'wfi' if old == M_SLEEP_WFI_OLD else 'wfe'
            start = body.index('void HELPER(' + function + ')(')
            end = body.index('\nvoid HELPER(', start + 1)
            body = body[:start] + replace_verified(body[start:end], old, new,
                'M-profile ' + function) + body[end:]
        else:
            body = replace_verified(body, old, new, 'M-profile power hook')
        changes[p] = body.encode()
    core = json.loads((HERE/'qemu-core/sources.json').read_text())
    receipt_path=source/'.z8-qemu-overlay.json'
    prior=json.loads(receipt_path.read_text()) if receipt_path.exists() else {}
    for name, record in core.items():
        p=source/name
        data=(HERE/'qemu-core'/name).read_bytes()
        digest=hashlib.sha256(p.read_bytes()).hexdigest()
        if digest not in (record['upstream_sha256'], prior.get(name), hashlib.sha256(data).hexdigest()):
            raise ValueError('Existing divergent MCU core device: '+name)
        changes[p]=data
    overlays = sorted(p for p in HERE.rglob('*') if p.is_file() and
                      'qemu-core' not in p.relative_to(HERE).parts and
                      (p.suffix in ('.c', '.h', '.cpp', '.inc') or
                       p.parent.name == 'nikon-he-public'))
    for overlay in overlays:
        if overlay.name == 'prepare_source.py':
            continue
        p = source/'hw/arm'/overlay.relative_to(HERE)
        data = overlay.read_bytes()
        if p.exists() and p.read_bytes() != data:
            # Permit only our last installed overlay to be upgraded. Never
            # overwrite an independently edited destination.
            installed = source/'.z8-qemu-overlay.json'
            receipt = json.loads(installed.read_text()) if installed.exists() else {}
            prior = receipt.get(str(p.relative_to(source)))
            if hashlib.sha256(p.read_bytes()).hexdigest() != prior:
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
        if p.exists() and p.read_bytes()==data:
            continue
        prior = backup/p.relative_to(source)
        if p.exists() and not prior.exists():
            prior.parent.mkdir(parents=True, exist_ok=True)
            prior.write_bytes(p.read_bytes())
        p.parent.mkdir(parents=True, exist_ok=True)
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
