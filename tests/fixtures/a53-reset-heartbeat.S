/* SPDX-License-Identifier: GPL-2.0-or-later */
/* Synthetic heartbeat on the separate EXPEED cluster, no Nikon code. */
.section .text
.global _start
_start:
    ldr x0, =0xa00010000
    ldr x1, =0x4135334845415254
    str x1, [x0]
    mov x2, #0
1:  add x2, x2, #1
    str x2, [x0, #8]
    b 1b
.ltorg
