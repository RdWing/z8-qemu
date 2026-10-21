/* SPDX-License-Identifier: GPL-2.0-or-later */
/* Synthetic STM32F469 reset-domain control; no Nikon firmware. */
#ifndef RESET_COUNT
#define RESET_COUNT 1
#endif
.syntax unified
.cpu cortex-m4
.thumb
.section .text
.word 0x2004fff0
.word 0x08000041
.org 0x40
.thumb_func
start:
    ldr r7, =0x20000000
    ldr r0, [r7]
    ldr r1, =0x4d435552
    cmp r0, r1
    beq again
    str r1, [r7]
    movs r1, #1
    str r1, [r7, #4]
    ldr r0, =0xcafebabe
    str r0, [r7, #0x10]
    ldr r1, =0x40024000
    str r0, [r1]
    /* Clear power-on reset flags, then program one spare flash word. */
    ldr r1, =0x40023874
    ldr r0, =0x01000000
    str r0, [r1]
    ldr r1, =0x40023c04
    ldr r0, =0x45670123
    str r0, [r1]
    ldr r0, =0xcdef89ab
    str r0, [r1]
    ldr r1, =0x40023c10
    ldr r0, =0x00000201
    str r0, [r1]
    ldr r1, =0x08001000
    ldr r0, =0xcafebabe
    str r0, [r1]
    /* Backup-domain register and RCC_BDCR should survive system reset. */
    ldr r1, =0x40002824
    movs r0, #0xca
    str r0, [r1]
    movs r0, #0x53
    str r0, [r1]
    ldr r1, =0x40002850
    ldr r0, =0x1234abcd
    str r0, [r1]
    ldr r1, =0x40023870
    ldr r0, =0x8101
    str r0, [r1]
    ldr r0, [r1]
    str r0, [r7, #0x68]
    /* Mark several ordinary controller/core registers before reset. */
    cpsid i
    ldr r1, =0x40020000
    ldr r0, =0x28000001
    str r0, [r1]
    ldr r1, =0x40013000
    movs r0, #4
    str r0, [r1]
    ldr r1, =0x40013010
    ldr r0, =0x1234
    str r0, [r1]
    ldr r1, =0x40000028
    str r0, [r1]
    ldr r1, =0x40011008
    ldr r0, =0x4321
    str r0, [r1]
    ldr r1, =0x40013c08
    movs r0, #1
    str r0, [r1]
    ldr r1, =0xe000e014
    ldr r0, =1000
    str r0, [r1]
    ldr r1, =0xe000e100
    movs r0, #0x20
    str r0, [r1]
    /* Missing VECTKEY and a keyed write without SYSRESETREQ are negatives. */
    ldr r1, =0xe000ed0c
    movs r0, #4
    str r0, [r1]
    dsb
    movs r0, #1
    str r0, [r7, #8]
    ldr r0, =0x05fa0000
    str r0, [r1]
    dsb
    movs r0, #1
    str r0, [r7, #0x58]
    b choose
again:
    ldr r0, [r7, #4]
    adds r0, #1
    str r0, [r7, #4]
choose:
    ldr r0, [r7, #4]
    cmp r0, #RESET_COUNT + 1
    bhs done
    ldr r1, =0xe000ed0c
    ldr r0, =0x05fa0004
    dsb
    str r0, [r1]
    dsb
1:  b 1b
done:
    ldr r1, =0x40023874
    ldr r0, [r1]
    str r0, [r7, #0x18]
    ldr r1, =0x40023870
    ldr r0, [r1]
    str r0, [r7, #0x1c]
    ldr r1, =0x40002850
    ldr r0, [r1]
    str r0, [r7, #0x20]
    ldr r1, =0x40020000
    ldr r0, [r1]
    str r0, [r7, #0x24]
    ldr r1, =0x40013000
    ldr r0, [r1]
    str r0, [r7, #0x28]
    ldr r1, =0x40013010
    ldr r0, [r1]
    str r0, [r7, #0x2c]
    ldr r1, =0x40000028
    ldr r0, [r1]
    str r0, [r7, #0x30]
    ldr r1, =0x40011008
    ldr r0, [r1]
    str r0, [r7, #0x34]
    ldr r1, =0x40013c08
    ldr r0, [r1]
    str r0, [r7, #0x38]
    ldr r1, =0xe000e014
    ldr r0, [r1]
    str r0, [r7, #0x3c]
    ldr r1, =0xe000e100
    ldr r0, [r1]
    str r0, [r7, #0x40]
    mrs r0, msp
    str r0, [r7, #0x44]
    mrs r0, primask
    str r0, [r7, #0x48]
    ldr r1, =0xe000ed08
    ldr r0, [r1]
    str r0, [r7, #0x4c]
    ldr r1, =0x08001000
    ldr r0, [r1]
    str r0, [r7, #0x50]
    ldr r1, =0x40023c10
    ldr r0, [r1]
    str r0, [r7, #0x54]
    ldr r1, =0x40024000
    ldr r0, [r1]
    str r0, [r7, #0x60]
    movs r0, #RESET_COUNT
    str r0, [r7, #0x70]
    ldr r0, =0x600d600d
    str r0, [r7, #0xc]
    movs r0, #0
2:  adds r0, #1
    str r0, [r7, #0x5c]
    b 2b
.ltorg
.org 0x1000
.word 0xffffffff
