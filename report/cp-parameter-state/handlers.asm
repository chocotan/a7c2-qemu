
SLOT 0 OP 4002 WIRE 8 HANDLER 8dad14
008dad14: 017a       ldrb r1, [r0, #8]
008dad16: 4af22070   movw r0, #0xa720
008dad1a: c0f26510   movt r0, #0x165
008dad1e: c0f89016   str.w r1, [r0, #0x690]
008dad22: 43f2a430   movw r0, #0x33a4
008dad26: c0f2a510   movt r0, #0x1a5
008dad2a: 90f83200   ldrb.w r0, [r0, #0x32]
008dad2e: c007       lsls r0, r0, #0x1f
008dad30: 09d0       beq #0x8dad46
008dad32: 80b5       push {r7, lr}
008dad34: 6f46       mov r7, sp
008dad36: 4bf2b430   movw r0, #0xb3b4
008dad3a: c0f2f700   movt r0, #0xf7
008dad3e: 69f21cfc   bl #0xb4457a
008dad42: bde88040   pop.w {r7, lr}
008dad46: 0120       movs r0, #1
008dad48: 7047       bx lr

SLOT 1 OP 4006 WIRE 14 HANDLER 354900
00354900: f0b5       push {r4, r5, r6, r7, lr}
00354902: 03af       add r7, sp, #0xc
00354904: 2de90007   push.w {r8, sb, sl}
00354908: 84b0       sub sp, #0x10
0035490a: 017a       ldrb r1, [r0, #8]
0035490c: 4af2207c   movw ip, #0xa720
00354910: 00f11409   add.w sb, r0, #0x14
00354914: c0f2651c   movt ip, #0x165
00354918: ccf83419   str.w r1, [ip, #0x934]
0035491c: 90f90920   ldrsb.w r2, [r0, #9]
00354920: 8cf83829   strb.w r2, [ip, #0x938]
00354924: 90f90a30   ldrsb.w r3, [r0, #0xa]
00354928: 8cf83939   strb.w r3, [ip, #0x939]
0035492c: 8489       ldrh r4, [r0, #0xc]
0035492e: acf83a49   strh.w r4, [ip, #0x93a]
00354932: c489       ldrh r4, [r0, #0xe]
00354934: acf83c49   strh.w r4, [ip, #0x93c]
00354938: 90f810e0   ldrb.w lr, [r0, #0x10]
0035493c: 8cf840e9   strb.w lr, [ip, #0x940]
00354940: 90f91180   ldrsb.w r8, [r0, #0x11]
00354944: 8cf84189   strb.w r8, [ip, #0x941]
00354948: 857c       ldrb r5, [r0, #0x12]
0035494a: 8cf84259   strb.w r5, [ip, #0x942]
0035494e: 0cf64415   addw r5, ip, #0x944
00354952: b9e85104   ldm.w sb!, {r0, r4, r6, sl}
00354956: a5e85104   stm.w r5!, {r0, r4, r6, sl}
0035495a: 99e85104   ldm.w sb, {r0, r4, r6, sl}
0035495e: 85e85104   stm.w r5, {r0, r4, r6, sl}
00354962: 43f2a430   movw r0, #0x33a4
00354966: c0f2a510   movt r0, #0x1a5
0035496a: 90f83200   ldrb.w r0, [r0, #0x32]
0035496e: c007       lsls r0, r0, #0x1f
00354970: 0ad0       beq #0x354988
00354972: bcf84409   ldrh.w r0, [ip, #0x944]
00354976: bcf84669   ldrh.w r6, [ip, #0x946]
0035497a: cde900e8   strd lr, r8, [sp]
0035497e: cde90206   strd r0, r6, [sp, #8]
00354982: 04a0       adr r0, #0x10
00354984: eff3f9f5   bl #0xb4457a
00354988: 0120       movs r0, #1
0035498a: 04b0       add sp, #0x10
0035498c: bde80007   pop.w {r8, sb, sl}
00354990: f0bd       pop {r4, r5, r6, r7, pc}

SLOT 2 OP 4007 WIRE 48 HANDLER 354a04
00354a04: 90f90810   ldrsb.w r1, [r0, #8]
00354a08: 4af22073   movw r3, #0xa720
00354a0c: c0f26513   movt r3, #0x165
00354a10: 83f83e19   strb.w r1, [r3, #0x93e]
00354a14: 90f90920   ldrsb.w r2, [r0, #9]
00354a18: 43f2a430   movw r0, #0x33a4
00354a1c: c0f2a510   movt r0, #0x1a5
00354a20: 90f83200   ldrb.w r0, [r0, #0x32]
00354a24: 83f83f29   strb.w r2, [r3, #0x93f]
00354a28: c007       lsls r0, r0, #0x1f
00354a2a: 06d0       beq #0x354a3a
00354a2c: 80b5       push {r7, lr}
00354a2e: 6f46       mov r7, sp
00354a30: 03a0       adr r0, #0xc
00354a32: eff3a2f5   bl #0xb4457a
00354a36: bde88040   pop.w {r7, lr}
00354a3a: 0120       movs r0, #1
00354a3c: 7047       bx lr

SLOT 3 OP 4008 WIRE 54 HANDLER 354a5c
00354a5c: b0b5       push {r4, r5, r7, lr}
00354a5e: 02af       add r7, sp, #8
00354a60: 4af22075   movw r5, #0xa720
00354a64: 0446       mov r4, r0
00354a66: c0f26515   movt r5, #0x165
00354a6a: e268       ldr r2, [r4, #0xc]
00354a6c: 217a       ldrb r1, [r4, #8]
00354a6e: d5f83801   ldr.w r0, [r5, #0x138]
00354a72: 86f187f7   bl #0x8db984
00354a76: 217a       ldrb r1, [r4, #8]
00354a78: 43f2a430   movw r0, #0x33a4
00354a7c: c0f2a510   movt r0, #0x1a5
00354a80: 90f83200   ldrb.w r0, [r0, #0x32]
00354a84: c5f82411   str.w r1, [r5, #0x124]
00354a88: 627a       ldrb r2, [r4, #9]
00354a8a: c007       lsls r0, r0, #0x1f
00354a8c: c5f82821   str.w r2, [r5, #0x128]
00354a90: e368       ldr r3, [r4, #0xc]
00354a92: c5f82031   str.w r3, [r5, #0x120]
00354a96: 02d0       beq #0x354a9e
00354a98: 02a0       adr r0, #8
00354a9a: eff36ef5   bl #0xb4457a
00354a9e: 0120       movs r0, #1
00354aa0: b0bd       pop {r4, r5, r7, pc}

SLOT 4 OP 400a WIRE 64 HANDLER 354bf0
00354bf0: 017a       ldrb r1, [r0, #8]
00354bf2: 4af22070   movw r0, #0xa720
00354bf6: c0f26510   movt r0, #0x165
00354bfa: c0f82c1b   str.w r1, [r0, #0xb2c]
00354bfe: 43f2a430   movw r0, #0x33a4
00354c02: c0f2a510   movt r0, #0x1a5
00354c06: 90f83200   ldrb.w r0, [r0, #0x32]
00354c0a: c007       lsls r0, r0, #0x1f
00354c0c: 06d0       beq #0x354c1c
00354c0e: 80b5       push {r7, lr}
00354c10: 6f46       mov r7, sp
00354c12: 03a0       adr r0, #0xc
00354c14: eff3b1f4   bl #0xb4457a
00354c18: bde88040   pop.w {r7, lr}
00354c1c: 0120       movs r0, #1
00354c1e: 7047       bx lr

SLOT 5 OP 400b WIRE 70 HANDLER 354c38
00354c38: 017a       ldrb r1, [r0, #8]
00354c3a: 4af22070   movw r0, #0xa720
00354c3e: c0f26510   movt r0, #0x165
00354c42: c0f8301b   str.w r1, [r0, #0xb30]
00354c46: 43f2a430   movw r0, #0x33a4
00354c4a: c0f2a510   movt r0, #0x1a5
00354c4e: 90f83200   ldrb.w r0, [r0, #0x32]
00354c52: c007       lsls r0, r0, #0x1f
00354c54: 06d0       beq #0x354c64
00354c56: 80b5       push {r7, lr}
00354c58: 6f46       mov r7, sp
00354c5a: 03a0       adr r0, #0xc
00354c5c: eff38df4   bl #0xb4457a
00354c60: bde88040   pop.w {r7, lr}
00354c64: 0120       movs r0, #1
00354c66: 7047       bx lr

SLOT 6 OP 400c WIRE 7c HANDLER 354c80
00354c80: 017a       ldrb r1, [r0, #8]
00354c82: 4af22070   movw r0, #0xa720
00354c86: c0f26510   movt r0, #0x165
00354c8a: c0f8341b   str.w r1, [r0, #0xb34]
00354c8e: 43f2a430   movw r0, #0x33a4
00354c92: c0f2a510   movt r0, #0x1a5
00354c96: 90f83200   ldrb.w r0, [r0, #0x32]
00354c9a: c007       lsls r0, r0, #0x1f
00354c9c: 06d0       beq #0x354cac
00354c9e: 80b5       push {r7, lr}
00354ca0: 6f46       mov r7, sp
00354ca2: 03a0       adr r0, #0xc
00354ca4: eff369f4   bl #0xb4457a
00354ca8: bde88040   pop.w {r7, lr}
00354cac: 0120       movs r0, #1
00354cae: 7047       bx lr

SLOT 7 OP 400d WIRE 88 HANDLER 354cc8
00354cc8: 017a       ldrb r1, [r0, #8]
00354cca: 4af22070   movw r0, #0xa720
00354cce: c0f26510   movt r0, #0x165
00354cd2: c0f8381b   str.w r1, [r0, #0xb38]
00354cd6: 43f2a430   movw r0, #0x33a4
00354cda: c0f2a510   movt r0, #0x1a5
00354cde: 90f83200   ldrb.w r0, [r0, #0x32]
00354ce2: c007       lsls r0, r0, #0x1f
00354ce4: 06d0       beq #0x354cf4
00354ce6: 80b5       push {r7, lr}
00354ce8: 6f46       mov r7, sp
00354cea: 03a0       adr r0, #0xc
00354cec: eff345f4   bl #0xb4457a
00354cf0: bde88040   pop.w {r7, lr}
00354cf4: 0120       movs r0, #1
00354cf6: 7047       bx lr

SLOT 8 OP 400e WIRE 94 HANDLER 354d0c
00354d0c: 017a       ldrb r1, [r0, #8]
00354d0e: 4af22070   movw r0, #0xa720
00354d12: c0f26510   movt r0, #0x165
00354d16: c0f83c1b   str.w r1, [r0, #0xb3c]
00354d1a: 43f2a430   movw r0, #0x33a4
00354d1e: c0f2a510   movt r0, #0x1a5
00354d22: 90f83200   ldrb.w r0, [r0, #0x32]
00354d26: c007       lsls r0, r0, #0x1f
00354d28: 06d0       beq #0x354d38
00354d2a: 80b5       push {r7, lr}
00354d2c: 6f46       mov r7, sp
00354d2e: 03a0       adr r0, #0xc
00354d30: eff323f4   bl #0xb4457a
00354d34: bde88040   pop.w {r7, lr}
00354d38: 0120       movs r0, #1
00354d3a: 7047       bx lr

SLOT 9 OP 400f WIRE a0 HANDLER 354d50
00354d50: 017a       ldrb r1, [r0, #8]
00354d52: 4af2207c   movw ip, #0xa720
00354d56: c0f2651c   movt ip, #0x165
00354d5a: ccf8101b   str.w r1, [ip, #0xb10]
00354d5e: 427a       ldrb r2, [r0, #9]
00354d60: 8cf8142b   strb.w r2, [ip, #0xb14]
00354d64: 837a       ldrb r3, [r0, #0xa]
00354d66: 43f2a430   movw r0, #0x33a4
00354d6a: c0f2a510   movt r0, #0x1a5
00354d6e: 90f83200   ldrb.w r0, [r0, #0x32]
00354d72: 8cf8153b   strb.w r3, [ip, #0xb15]
00354d76: c007       lsls r0, r0, #0x1f
00354d78: 06d0       beq #0x354d88
00354d7a: 80b5       push {r7, lr}
00354d7c: 6f46       mov r7, sp
00354d7e: 03a0       adr r0, #0xc
00354d80: eff3fbf3   bl #0xb4457a
00354d84: bde88040   pop.w {r7, lr}
00354d88: 0120       movs r0, #1
00354d8a: 7047       bx lr

SLOT 10 OP 4010 WIRE ac HANDLER 354dac
00354dac: 017a       ldrb r1, [r0, #8]
00354dae: 4af22070   movw r0, #0xa720
00354db2: c0f26510   movt r0, #0x165
00354db6: c0f8a812   str.w r1, [r0, #0x2a8]
00354dba: 43f2a430   movw r0, #0x33a4
00354dbe: c0f2a510   movt r0, #0x1a5
00354dc2: 90f83200   ldrb.w r0, [r0, #0x32]
00354dc6: c007       lsls r0, r0, #0x1f
00354dc8: 06d0       beq #0x354dd8
00354dca: 80b5       push {r7, lr}
00354dcc: 6f46       mov r7, sp
00354dce: 03a0       adr r0, #0xc
00354dd0: eff3d3f3   bl #0xb4457a
00354dd4: bde88040   pop.w {r7, lr}
00354dd8: 0120       movs r0, #1
00354dda: 7047       bx lr

SLOT 11 OP 4011 WIRE b8 HANDLER 354df4
00354df4: 017a       ldrb r1, [r0, #8]
00354df6: 4af22070   movw r0, #0xa720
00354dfa: c0f26510   movt r0, #0x165
00354dfe: c0f82c1d   str.w r1, [r0, #0xd2c]
00354e02: 43f2a430   movw r0, #0x33a4
00354e06: c0f2a510   movt r0, #0x1a5
00354e0a: 90f83200   ldrb.w r0, [r0, #0x32]
00354e0e: c007       lsls r0, r0, #0x1f
00354e10: 06d0       beq #0x354e20
00354e12: 80b5       push {r7, lr}
00354e14: 6f46       mov r7, sp
00354e16: 03a0       adr r0, #0xc
00354e18: eff3aff3   bl #0xb4457a
00354e1c: bde88040   pop.w {r7, lr}
00354e20: 0120       movs r0, #1
00354e22: 7047       bx lr

SLOT 12 OP 4012 WIRE c4 HANDLER 3555c0
003555c0: 017a       ldrb r1, [r0, #8]
003555c2: 4af22070   movw r0, #0xa720
003555c6: c0f26510   movt r0, #0x165
003555ca: c0f8b81c   str.w r1, [r0, #0xcb8]
003555ce: 43f2a430   movw r0, #0x33a4
003555d2: c0f2a510   movt r0, #0x1a5
003555d6: 90f83200   ldrb.w r0, [r0, #0x32]
003555da: c007       lsls r0, r0, #0x1f
003555dc: 06d0       beq #0x3555ec
003555de: 80b5       push {r7, lr}
003555e0: 6f46       mov r7, sp
003555e2: 03a0       adr r0, #0xc
003555e4: eef3c9f7   bl #0xb4457a
003555e8: bde88040   pop.w {r7, lr}
003555ec: 0120       movs r0, #1
003555ee: 7047       bx lr

SLOT 13 OP 4013 WIRE d0 HANDLER 355608
00355608: 017a       ldrb r1, [r0, #8]
0035560a: 4af22070   movw r0, #0xa720
0035560e: c0f26510   movt r0, #0x165
00355612: c0f8bc1c   str.w r1, [r0, #0xcbc]
00355616: 43f2a430   movw r0, #0x33a4
0035561a: c0f2a510   movt r0, #0x1a5
0035561e: 90f83200   ldrb.w r0, [r0, #0x32]
00355622: c007       lsls r0, r0, #0x1f
00355624: 06d0       beq #0x355634
00355626: 80b5       push {r7, lr}
00355628: 6f46       mov r7, sp
0035562a: 03a0       adr r0, #0xc
0035562c: eef3a5f7   bl #0xb4457a
00355630: bde88040   pop.w {r7, lr}
00355634: 0120       movs r0, #1
00355636: 7047       bx lr

SLOT 14 OP 4015 WIRE dc HANDLER 355848
00355848: f0b5       push {r4, r5, r6, r7, lr}
0035584a: 03af       add r7, sp, #0xc
0035584c: 4df804bd   str fp, [sp, #-0x4]!
00355850: 86b0       sub sp, #0x18
00355852: 017a       ldrb r1, [r0, #8]
00355854: 4af22076   movw r6, #0xa720
00355858: c0f26516   movt r6, #0x165
0035585c: c6f84011   str.w r1, [r6, #0x140]
00355860: 427a       ldrb r2, [r0, #9]
00355862: c6f84421   str.w r2, [r6, #0x144]
00355866: 837a       ldrb r3, [r0, #0xa]
00355868: 86f84831   strb.w r3, [r6, #0x148]
0035586c: 90f80bc0   ldrb.w ip, [r0, #0xb]
00355870: c6f84cc1   str.w ip, [r6, #0x14c]
00355874: 90f80ce0   ldrb.w lr, [r0, #0xc]
00355878: c6f850e1   str.w lr, [r6, #0x150]
0035587c: 447b       ldrb r4, [r0, #0xd]
0035587e: 86f85441   strb.w r4, [r6, #0x154]
00355882: 857b       ldrb r5, [r0, #0xe]
00355884: c6f85851   str.w r5, [r6, #0x158]
00355888: 0069       ldr r0, [r0, #0x10]
0035588a: c6f85c01   str.w r0, [r6, #0x15c]
0035588e: 43f2a436   movw r6, #0x33a4
00355892: c0f2a516   movt r6, #0x1a5
00355896: 96f83260   ldrb.w r6, [r6, #0x32]
0035589a: f607       lsls r6, r6, #0x1f
0035589c: 07d0       beq #0x3558ae
0035589e: cde900ce   strd ip, lr, [sp]
003558a2: cde90245   strd r4, r5, [sp, #8]
003558a6: 0490       str r0, [sp, #0x10]
003558a8: 03a0       adr r0, #0xc
003558aa: eef366f6   bl #0xb4457a
003558ae: 0120       movs r0, #1
003558b0: 06b0       add sp, #0x18
003558b2: 5df804bb   ldr fp, [sp], #4
003558b6: f0bd       pop {r4, r5, r6, r7, pc}

SLOT 15 OP 4016 WIRE f0 HANDLER 354e44
00354e44: 80b5       push {r7, lr}
00354e46: 6f46       mov r7, sp
00354e48: 82b0       sub sp, #8
00354e4a: 017a       ldrb r1, [r0, #8]
00354e4c: 4af2207c   movw ip, #0xa720
00354e50: c0f2651c   movt ip, #0x165
00354e54: ccf8e811   str.w r1, [ip, #0x1e8]
00354e58: 427a       ldrb r2, [r0, #9]
00354e5a: ccf8ec21   str.w r2, [ip, #0x1ec]
00354e5e: 837a       ldrb r3, [r0, #0xa]
00354e60: ccf8f031   str.w r3, [ip, #0x1f0]
00354e64: 9cf8f401   ldrb.w r0, [ip, #0x1f4]
00354e68: ff28       cmp r0, #0xff
00354e6a: 04d0       beq #0x354e76
00354e6c: 00f1010e   add.w lr, r0, #1
00354e70: 8cf8f4e1   strb.w lr, [ip, #0x1f4]
00354e74: 01e0       b #0x354e7a
00354e76: 4ff0ff0e   mov.w lr, #0xff
00354e7a: 43f2a430   movw r0, #0x33a4
00354e7e: c0f2a510   movt r0, #0x1a5
00354e82: 90f83200   ldrb.w r0, [r0, #0x32]
00354e86: c007       lsls r0, r0, #0x1f
00354e88: 05d0       beq #0x354e96
00354e8a: 5ffa8ef0   uxtb.w r0, lr
00354e8e: 0090       str r0, [sp]
00354e90: 02a0       adr r0, #8
00354e92: eff372f3   bl #0xb4457a
00354e96: 0120       movs r0, #1
00354e98: 02b0       add sp, #8
00354e9a: 80bd       pop {r7, pc}

SLOT 16 OP 4017 WIRE fc HANDLER 354ebc
00354ebc: 017a       ldrb r1, [r0, #8]
00354ebe: 4af22070   movw r0, #0xa720
00354ec2: c0f26510   movt r0, #0x165
00354ec6: c0f8f81c   str.w r1, [r0, #0xcf8]
00354eca: 43f2a430   movw r0, #0x33a4
00354ece: c0f2a510   movt r0, #0x1a5
00354ed2: 90f83200   ldrb.w r0, [r0, #0x32]
00354ed6: c007       lsls r0, r0, #0x1f
00354ed8: 06d0       beq #0x354ee8
00354eda: 80b5       push {r7, lr}
00354edc: 6f46       mov r7, sp
00354ede: 03a0       adr r0, #0xc
00354ee0: eff34bf3   bl #0xb4457a
00354ee4: bde88040   pop.w {r7, lr}
00354ee8: 0120       movs r0, #1
00354eea: 7047       bx lr

SLOT 17 OP 4019 WIRE 108 HANDLER 8dadca
008dadca: 017a       ldrb r1, [r0, #8]
008dadcc: 4af22070   movw r0, #0xa720
008dadd0: c0f26510   movt r0, #0x165
008dadd4: c0f8241d   str.w r1, [r0, #0xd24]
008dadd8: 43f2a430   movw r0, #0x33a4
008daddc: c0f2a510   movt r0, #0x1a5
008dade0: 90f83200   ldrb.w r0, [r0, #0x32]
008dade4: c007       lsls r0, r0, #0x1f
008dade6: 09d0       beq #0x8dadfc
008dade8: 80b5       push {r7, lr}
008dadea: 6f46       mov r7, sp
008dadec: 4bf2c930   movw r0, #0xb3c9
008dadf0: c0f2f700   movt r0, #0xf7
008dadf4: 69f2c1fb   bl #0xb4457a
008dadf8: bde88040   pop.w {r7, lr}
008dadfc: 0120       movs r0, #1
008dadfe: 7047       bx lr

SLOT 18 OP 401a WIRE 114 HANDLER 354f04
00354f04: 017a       ldrb r1, [r0, #8]
00354f06: 4af22073   movw r3, #0xa720
00354f0a: c0f26513   movt r3, #0x165
00354f0e: c3f85c15   str.w r1, [r3, #0x55c]
00354f12: 427a       ldrb r2, [r0, #9]
00354f14: c3f86025   str.w r2, [r3, #0x560]
00354f18: 93f86405   ldrb.w r0, [r3, #0x564]
00354f1c: 0130       adds r0, #1
00354f1e: 83f86405   strb.w r0, [r3, #0x564]
00354f22: 43f2a433   movw r3, #0x33a4
00354f26: c0f2a513   movt r3, #0x1a5
00354f2a: 93f83230   ldrb.w r3, [r3, #0x32]
00354f2e: db07       lsls r3, r3, #0x1f
00354f30: 07d0       beq #0x354f42
00354f32: 80b5       push {r7, lr}
00354f34: 6f46       mov r7, sp
00354f36: c3b2       uxtb r3, r0
00354f38: 03a0       adr r0, #0xc
00354f3a: eff31ef3   bl #0xb4457a
00354f3e: bde88040   pop.w {r7, lr}
00354f42: 0120       movs r0, #1
00354f44: 7047       bx lr

SLOT 19 OP 401d WIRE 120 HANDLER 3550fc
003550fc: 90f90810   ldrsb.w r1, [r0, #8]
00355100: 4af22073   movw r3, #0xa720
00355104: c0f26513   movt r3, #0x165
00355108: 83f86c15   strb.w r1, [r3, #0x56c]
0035510c: 427a       ldrb r2, [r0, #9]
0035510e: 43f2a430   movw r0, #0x33a4
00355112: c0f2a510   movt r0, #0x1a5
00355116: 90f83200   ldrb.w r0, [r0, #0x32]
0035511a: c3f87025   str.w r2, [r3, #0x570]
0035511e: c007       lsls r0, r0, #0x1f
00355120: 06d0       beq #0x355130
00355122: 80b5       push {r7, lr}
00355124: 6f46       mov r7, sp
00355126: 03a0       adr r0, #0xc
00355128: eff327f2   bl #0xb4457a
0035512c: bde88040   pop.w {r7, lr}
00355130: 0120       movs r0, #1
00355132: 7047       bx lr

SLOT 20 OP 401e WIRE 12c HANDLER 355154
00355154: 017a       ldrb r1, [r0, #8]
00355156: 4af22070   movw r0, #0xa720
0035515a: c0f26510   movt r0, #0x165
0035515e: c0f86815   str.w r1, [r0, #0x568]
00355162: 43f2a430   movw r0, #0x33a4
00355166: c0f2a510   movt r0, #0x1a5
0035516a: 90f83200   ldrb.w r0, [r0, #0x32]
0035516e: c007       lsls r0, r0, #0x1f
00355170: 06d0       beq #0x355180
00355172: 80b5       push {r7, lr}
00355174: 6f46       mov r7, sp
00355176: 03a0       adr r0, #0xc
00355178: eff3fff1   bl #0xb4457a
0035517c: bde88040   pop.w {r7, lr}
00355180: 0120       movs r0, #1
00355182: 7047       bx lr

SLOT 21 OP 4021 WIRE 138 HANDLER 355e34
00355e34: 017a       ldrb r1, [r0, #8]
00355e36: 4af22070   movw r0, #0xa720
00355e3a: c0f26510   movt r0, #0x165
00355e3e: c0f8c416   str.w r1, [r0, #0x6c4]
00355e42: 43f2a430   movw r0, #0x33a4
00355e46: c0f2a510   movt r0, #0x1a5
00355e4a: 90f83200   ldrb.w r0, [r0, #0x32]
00355e4e: c007       lsls r0, r0, #0x1f
00355e50: 06d0       beq #0x355e60
00355e52: 80b5       push {r7, lr}
00355e54: 6f46       mov r7, sp
00355e56: 03a0       adr r0, #0xc
00355e58: eef38ff3   bl #0xb4457a
00355e5c: bde88040   pop.w {r7, lr}
00355e60: 0120       movs r0, #1
00355e62: 7047       bx lr

SLOT 22 OP 4022 WIRE 144 HANDLER 8daaa4
008daaa4: f0b5       push {r4, r5, r6, r7, lr}
008daaa6: 03af       add r7, sp, #0xc
008daaa8: 2de9000f   push.w {r8, sb, sl, fp}
008daaac: 8db0       sub sp, #0x34
008daaae: 0446       mov r4, r0
008daab0: 53f280f9   bl #0xb2ddb4
008daab4: 406b       ldr r0, [r0, #0x34]
008daab6: 267a       ldrb r6, [r4, #8]
008daab8: 90f8db02   ldrb.w r0, [r0, #0x2db]
008daabc: 30b1       cbz r0, #0x8daacc
008daabe: 4af22070   movw r0, #0xa720
008daac2: c0f26510   movt r0, #0x165
008daac6: d0f8c826   ldr.w r2, [r0, #0x6c8]
008daaca: 23e0       b #0x8dab14
008daacc: 4af22070   movw r0, #0xa720
008daad0: c0f26510   movt r0, #0x165
008daad4: d0f8c826   ldr.w r2, [r0, #0x6c8]
008daad8: 9642       cmp r6, r2
008daada: 1bd1       bne #0x8dab14
008daadc: b0f8d216   ldrh.w r1, [r0, #0x6d2]
008daae0: 628a       ldrh r2, [r4, #0x12]
008daae2: 8a42       cmp r2, r1
008daae4: 15d1       bne #0x8dab12
008daae6: b0f8ac16   ldrh.w r1, [r0, #0x6ac]
008daaea: 6289       ldrh r2, [r4, #0xa]
008daaec: 8a42       cmp r2, r1
008daaee: 10d1       bne #0x8dab12
008daaf0: b0f8ae16   ldrh.w r1, [r0, #0x6ae]
008daaf4: a289       ldrh r2, [r4, #0xc]
008daaf6: 8a42       cmp r2, r1
008daaf8: 0bd1       bne #0x8dab12
008daafa: b0f87817   ldrh.w r1, [r0, #0x778]
008daafe: a28b       ldrh r2, [r4, #0x1c]
008dab00: 8a42       cmp r2, r1
008dab02: 06d1       bne #0x8dab12
008dab04: b0f87a07   ldrh.w r0, [r0, #0x77a]
008dab08: e18b       ldrh r1, [r4, #0x1e]
008dab0a: 3246       mov r2, r6
008dab0c: 8142       cmp r1, r0
008dab0e: 01d1       bne #0x8dab14
008dab10: 07e0       b #0x8dab22
008dab12: 3246       mov r2, r6
008dab14: 4af22070   movw r0, #0xa720
008dab18: 0021       movs r1, #0
008dab1a: c0f26510   movt r0, #0x165
008dab1e: 80f8ba12   strb.w r1, [r0, #0x2ba]
008dab22: b4f812e0   ldrh.w lr, [r4, #0x12]
008dab26: 4af22070   movw r0, #0xa720
008dab2a: 9642       cmp r6, r2
008dab2c: c0f26510   movt r0, #0x165
008dab30: 0dd1       bne #0x8dab4e
008dab32: b0f8d216   ldrh.w r1, [r0, #0x6d2]
008dab36: 8e45       cmp lr, r1
008dab38: 09d1       bne #0x8dab4e
008dab3a: 6289       ldrh r2, [r4, #0xa]
008dab3c: b0f8ac16   ldrh.w r1, [r0, #0x6ac]
008dab40: 8a42       cmp r2, r1
008dab42: 04d1       bne #0x8dab4e
008dab44: a389       ldrh r3, [r4, #0xc]
008dab46: b0f8ae16   ldrh.w r1, [r0, #0x6ae]
008dab4a: 8b42       cmp r3, r1
008dab4c: 06d0       beq #0x8dab5c
008dab4e: 90f8a617   ldrb.w r1, [r0, #0x7a6]
008dab52: 0131       adds r1, #1
008dab54: 80f8a617   strb.w r1, [r0, #0x7a6]
008dab58: a389       ldrh r3, [r4, #0xc]
008dab5a: 6289       ldrh r2, [r4, #0xa]
008dab5c: c0f8c866   str.w r6, [r0, #0x6c8]
008dab60: a0f8ac26   strh.w r2, [r0, #0x6ac]
008dab64: 0c92       str r2, [sp, #0x30]
008dab66: a0f8ae36   strh.w r3, [r0, #0x6ae]
008dab6a: 0b96       str r6, [sp, #0x2c]
008dab6c: e289       ldrh r2, [r4, #0xe]
008dab6e: a0f8cc26   strh.w r2, [r0, #0x6cc]
008dab72: b4f81080   ldrh.w r8, [r4, #0x10]
008dab76: a0f8ce86   strh.w r8, [r0, #0x6ce]
008dab7a: b4f81490   ldrh.w sb, [r4, #0x14]
008dab7e: a0f8d096   strh.w sb, [r0, #0x6d0]
008dab82: a0f8d2e6   strh.w lr, [r0, #0x6d2]
008dab86: 94f816e0   ldrb.w lr, [r4, #0x16]
008dab8a: c0f874e7   str.w lr, [r0, #0x774]
008dab8e: 94f817a0   ldrb.w sl, [r4, #0x17]
008dab92: c0f884a7   str.w sl, [r0, #0x784]
008dab96: 94f818b0   ldrb.w fp, [r4, #0x18]
008dab9a: c0f8d4b6   str.w fp, [r0, #0x6d4]
008dab9e: 667e       ldrb r6, [r4, #0x19]
008daba0: c0f8d866   str.w r6, [r0, #0x6d8]
008daba4: a57e       ldrb r5, [r4, #0x1a]
008daba6: c0f8dc56   str.w r5, [r0, #0x6dc]
008dabaa: 94f81bc0   ldrb.w ip, [r4, #0x1b]
008dabae: c0f8e0c6   str.w ip, [r0, #0x6e0]
008dabb2: a18b       ldrh r1, [r4, #0x1c]
008dabb4: a0f87817   strh.w r1, [r0, #0x778]
008dabb8: e48b       ldrh r4, [r4, #0x1e]
008dabba: a0f87a47   strh.w r4, [r0, #0x77a]
008dabbe: 43f2a430   movw r0, #0x33a4
008dabc2: c0f2a510   movt r0, #0x1a5
008dabc6: 90f83200   ldrb.w r0, [r0, #0x32]
008dabca: c007       lsls r0, r0, #0x1f
008dabcc: 10d0       beq #0x8dabf0
008dabce: cde908c1   strd ip, r1, [sp, #0x20]
008dabd2: 0a94       str r4, [sp, #0x28]
008dabd4: cde90665   strd r6, r5, [sp, #0x18]
008dabd8: cde904ab   strd sl, fp, [sp, #0x10]
008dabdc: 8de80443   stm.w sp, {r2, r8, sb, lr}
008dabe0: 4bf21730   movw r0, #0xb317
008dabe4: dde90b12   ldrd r1, r2, [sp, #0x2c]
008dabe8: c0f2f700   movt r0, #0xf7
008dabec: 69f2c5fc   bl #0xb4457a
008dabf0: 0120       movs r0, #1
008dabf2: 0db0       add sp, #0x34
008dabf4: bde8000f   pop.w {r8, sb, sl, fp}
008dabf8: f0bd       pop {r4, r5, r6, r7, pc}

SLOT 23 OP 4023 WIRE 164 HANDLER 355edc
00355edc: d0b5       push {r4, r6, r7, lr}
00355ede: 02af       add r7, sp, #8
00355ee0: 0446       mov r4, r0
00355ee2: 42f356f3   bl #0xa98592
00355ee6: a8b9       cbnz r0, #0x355f14
00355ee8: 4af22070   movw r0, #0xa720
00355eec: c0f26510   movt r0, #0x165
00355ef0: d0f83411   ldr.w r1, [r0, #0x134]
00355ef4: d0f89821   ldr.w r2, [r0, #0x198]
00355ef8: 1143       orrs r1, r2
00355efa: 0bd1       bne #0x355f14
00355efc: 217a       ldrb r1, [r4, #8]
00355efe: d0f88806   ldr.w r0, [r0, #0x688]
00355f02: 8842       cmp r0, r1
00355f04: 06d0       beq #0x355f14
00355f06: 41f00800   orr r0, r1, #8
00355f0a: 0828       cmp r0, #8
00355f0c: 02d0       beq #0x355f14
00355f0e: 0020       movs r0, #0
00355f10: caf334f6   bl #0xb20b7c
00355f14: d7f34ef7   bl #0xb2ddb4
00355f18: 406b       ldr r0, [r0, #0x34]
00355f1a: 217a       ldrb r1, [r4, #8]
00355f1c: 90f8db02   ldrb.w r0, [r0, #0x2db]
00355f20: 30b1       cbz r0, #0x355f30
00355f22: 4af22070   movw r0, #0xa720
00355f26: c0f26510   movt r0, #0x165
00355f2a: d0f88826   ldr.w r2, [r0, #0x688]
00355f2e: 08e0       b #0x355f42
00355f30: 4af22070   movw r0, #0xa720
00355f34: c0f26510   movt r0, #0x165
00355f38: d0f88826   ldr.w r2, [r0, #0x688]
00355f3c: 0846       mov r0, r1
00355f3e: 9142       cmp r1, r2
00355f40: 07d0       beq #0x355f52
00355f42: 4af22070   movw r0, #0xa720
00355f46: 0023       movs r3, #0
00355f48: c0f26510   movt r0, #0x165
00355f4c: 80f8ba32   strb.w r3, [r0, #0x2ba]
00355f50: 1046       mov r0, r2
00355f52: 09b9       cbnz r1, #0x355f58
00355f54: 0128       cmp r0, #1
00355f56: 03d0       beq #0x355f60
00355f58: 0129       cmp r1, #1
00355f5a: 08bf       it eq
00355f5c: 0028       cmp r0, #0
00355f5e: 08d1       bne #0x355f72
00355f60: 4af22070   movw r0, #0xa720
00355f64: c0f26510   movt r0, #0x165
00355f68: 90f8a627   ldrb.w r2, [r0, #0x7a6]
00355f6c: 0132       adds r2, #1
00355f6e: 80f8a627   strb.w r2, [r0, #0x7a6]
00355f72: 4af22070   movw r0, #0xa720
00355f76: c0f26510   movt r0, #0x165
00355f7a: c0f88816   str.w r1, [r0, #0x688]
00355f7e: a27a       ldrb r2, [r4, #0xa]
00355f80: 80f82027   strb.w r2, [r0, #0x720]
00355f84: 43f2a430   movw r0, #0x33a4
00355f88: c0f2a510   movt r0, #0x1a5
00355f8c: 90f83200   ldrb.w r0, [r0, #0x32]
00355f90: c007       lsls r0, r0, #0x1f
00355f92: 02d0       beq #0x355f9a
00355f94: 02a0       adr r0, #8
00355f96: eef3f0f2   bl #0xb4457a
00355f9a: 0120       movs r0, #1
00355f9c: d0bd       pop {r4, r6, r7, pc}

SLOT 24 OP 4024 WIRE 170 HANDLER 3559e0
003559e0: 017a       ldrb r1, [r0, #8]
003559e2: 4af22072   movw r2, #0xa720
003559e6: c0f26512   movt r2, #0x165
003559ea: 0029       cmp r1, #0
003559ec: 0846       mov r0, r1
003559ee: 18bf       it ne
003559f0: 0120       movs r0, #1
003559f2: 82f87405   strb.w r0, [r2, #0x574]
003559f6: 43f2a430   movw r0, #0x33a4
003559fa: c0f2a510   movt r0, #0x1a5
003559fe: 90f83200   ldrb.w r0, [r0, #0x32]
00355a02: c007       lsls r0, r0, #0x1f
00355a04: 09d0       beq #0x355a1a
00355a06: 80b5       push {r7, lr}
00355a08: 6f46       mov r7, sp
00355a0a: 0029       cmp r1, #0
00355a0c: 04a0       adr r0, #0x10
00355a0e: 18bf       it ne
00355a10: 0121       movs r1, #1
00355a12: eef3b2f5   bl #0xb4457a
00355a16: bde88040   pop.w {r7, lr}
00355a1a: 0120       movs r0, #1
00355a1c: 7047       bx lr

SLOT 25 OP 4025 WIRE 17c HANDLER 355a44
00355a44: 017a       ldrb r1, [r0, #8]
00355a46: 4af22072   movw r2, #0xa720
00355a4a: c0f26512   movt r2, #0x165
00355a4e: 0029       cmp r1, #0
00355a50: 0846       mov r0, r1
00355a52: 18bf       it ne
00355a54: 0120       movs r0, #1
00355a56: 82f87505   strb.w r0, [r2, #0x575]
00355a5a: 43f2a430   movw r0, #0x33a4
00355a5e: c0f2a510   movt r0, #0x1a5
00355a62: 90f83200   ldrb.w r0, [r0, #0x32]
00355a66: c007       lsls r0, r0, #0x1f
00355a68: 09d0       beq #0x355a7e
00355a6a: 80b5       push {r7, lr}
00355a6c: 6f46       mov r7, sp
00355a6e: 0029       cmp r1, #0
00355a70: 04a0       adr r0, #0x10
00355a72: 18bf       it ne
00355a74: 0121       movs r1, #1
00355a76: eef380f5   bl #0xb4457a
00355a7a: bde88040   pop.w {r7, lr}
00355a7e: 0120       movs r0, #1
00355a80: 7047       bx lr

SLOT 26 OP 4026 WIRE 188 HANDLER 355aa0
00355aa0: 017a       ldrb r1, [r0, #8]
00355aa2: 4af22070   movw r0, #0xa720
00355aa6: c0f26510   movt r0, #0x165
00355aaa: c0f87815   str.w r1, [r0, #0x578]
00355aae: 43f2a430   movw r0, #0x33a4
00355ab2: c0f2a510   movt r0, #0x1a5
00355ab6: 90f83200   ldrb.w r0, [r0, #0x32]
00355aba: c007       lsls r0, r0, #0x1f
00355abc: 06d0       beq #0x355acc
00355abe: 80b5       push {r7, lr}
00355ac0: 6f46       mov r7, sp
00355ac2: 03a0       adr r0, #0xc
00355ac4: eef359f5   bl #0xb4457a
00355ac8: bde88040   pop.w {r7, lr}
00355acc: 0120       movs r0, #1
00355ace: 7047       bx lr

SLOT 27 OP 4029 WIRE 194 HANDLER 355c20
00355c20: f0b5       push {r4, r5, r6, r7, lr}
00355c22: 03af       add r7, sp, #0xc
00355c24: 4df804bd   str fp, [sp, #-0x4]!
00355c28: 82b0       sub sp, #8
00355c2a: 017a       ldrb r1, [r0, #8]
00355c2c: 4af22074   movw r4, #0xa720
00355c30: c0f26514   movt r4, #0x165
00355c34: c4f80413   str.w r1, [r4, #0x304]
00355c38: 427a       ldrb r2, [r0, #9]
00355c3a: c4f80823   str.w r2, [r4, #0x308]
00355c3e: 837a       ldrb r3, [r0, #0xa]
00355c40: c4f80c33   str.w r3, [r4, #0x30c]
00355c44: c67a       ldrb r6, [r0, #0xb]
00355c46: c4f81063   str.w r6, [r4, #0x310]
00355c4a: 067b       ldrb r6, [r0, #0xc]
00355c4c: c4f81463   str.w r6, [r4, #0x314]
00355c50: 457b       ldrb r5, [r0, #0xd]
00355c52: c4f81853   str.w r5, [r4, #0x318]
00355c56: 867b       ldrb r6, [r0, #0xe]
00355c58: c4f85464   str.w r6, [r4, #0x454]
00355c5c: 43f2a436   movw r6, #0x33a4
00355c60: c07b       ldrb r0, [r0, #0xf]
00355c62: c0f2a516   movt r6, #0x1a5
00355c66: c4f81c03   str.w r0, [r4, #0x31c]
00355c6a: 96f83200   ldrb.w r0, [r6, #0x32]
00355c6e: 10f0010f   tst.w r0, #1
00355c72: 05d0       beq #0x355c80
00355c74: 09a0       adr r0, #0x24
00355c76: 0095       str r5, [sp]
00355c78: eef37ff4   bl #0xb4457a
00355c7c: 96f83200   ldrb.w r0, [r6, #0x32]
00355c80: c007       lsls r0, r0, #0x1f
00355c82: 06d0       beq #0x355c92
00355c84: d4f81c23   ldr.w r2, [r4, #0x31c]
00355c88: d4f85414   ldr.w r1, [r4, #0x454]
00355c8c: 12a0       adr r0, #0x48
00355c8e: eef374f4   bl #0xb4457a
00355c92: 0120       movs r0, #1
00355c94: 02b0       add sp, #8
00355c96: 5df804bb   ldr fp, [sp], #4
00355c9a: f0bd       pop {r4, r5, r6, r7, pc}

SLOT 28 OP 402a WIRE 1a4 HANDLER 355994
00355994: 017a       ldrb r1, [r0, #8]
00355996: 4af22070   movw r0, #0xa720
0035599a: c0f26510   movt r0, #0x165
0035599e: c0f86011   str.w r1, [r0, #0x160]
003559a2: 43f2a430   movw r0, #0x33a4
003559a6: c0f2a510   movt r0, #0x1a5
003559aa: 90f83200   ldrb.w r0, [r0, #0x32]
003559ae: c007       lsls r0, r0, #0x1f
003559b0: 06d0       beq #0x3559c0
003559b2: 80b5       push {r7, lr}
003559b4: 6f46       mov r7, sp
003559b6: 03a0       adr r0, #0xc
003559b8: eef3dff5   bl #0xb4457a
003559bc: bde88040   pop.w {r7, lr}
003559c0: 0120       movs r0, #1
003559c2: 7047       bx lr

SLOT 29 OP 402e WIRE 1b0 HANDLER 356388
00356388: 017a       ldrb r1, [r0, #8]
0035638a: 4af2207c   movw ip, #0xa720
0035638e: c0f2651c   movt ip, #0x165
00356392: ccf82413   str.w r1, [ip, #0x324]
00356396: 427a       ldrb r2, [r0, #9]
00356398: ccf82823   str.w r2, [ip, #0x328]
0035639c: 837a       ldrb r3, [r0, #0xa]
0035639e: 43f2a430   movw r0, #0x33a4
003563a2: c0f2a510   movt r0, #0x1a5
003563a6: 90f83200   ldrb.w r0, [r0, #0x32]
003563aa: ccf82c33   str.w r3, [ip, #0x32c]
003563ae: c007       lsls r0, r0, #0x1f
003563b0: 06d0       beq #0x3563c0
003563b2: 80b5       push {r7, lr}
003563b4: 6f46       mov r7, sp
003563b6: 03a0       adr r0, #0xc
003563b8: eef3dff0   bl #0xb4457a
003563bc: bde88040   pop.w {r7, lr}
003563c0: 0120       movs r0, #1
003563c2: 7047       bx lr

SLOT 30 OP 402f WIRE 1bc HANDLER 356484
00356484: 017a       ldrb r1, [r0, #8]
00356486: 4af22070   movw r0, #0xa720
0035648a: c0f26510   movt r0, #0x165
0035648e: c0f86419   str.w r1, [r0, #0x964]
00356492: 43f2a430   movw r0, #0x33a4
00356496: c0f2a510   movt r0, #0x1a5
0035649a: 90f83200   ldrb.w r0, [r0, #0x32]
0035649e: c007       lsls r0, r0, #0x1f
003564a0: 06d0       beq #0x3564b0
003564a2: 80b5       push {r7, lr}
003564a4: 6f46       mov r7, sp
003564a6: 03a0       adr r0, #0xc
003564a8: eef367f0   bl #0xb4457a
003564ac: bde88040   pop.w {r7, lr}
003564b0: 0120       movs r0, #1
003564b2: 7047       bx lr

SLOT 31 OP 4030 WIRE 1c8 HANDLER 3564cc
003564cc: 90f90810   ldrsb.w r1, [r0, #8]
003564d0: 4af22070   movw r0, #0xa720
003564d4: c0f26510   movt r0, #0x165
003564d8: 80f86819   strb.w r1, [r0, #0x968]
003564dc: 43f2a430   movw r0, #0x33a4
003564e0: c0f2a510   movt r0, #0x1a5
003564e4: 90f83200   ldrb.w r0, [r0, #0x32]
003564e8: c007       lsls r0, r0, #0x1f
003564ea: 06d0       beq #0x3564fa
003564ec: 80b5       push {r7, lr}
003564ee: 6f46       mov r7, sp
003564f0: 03a0       adr r0, #0xc
003564f2: eef342f0   bl #0xb4457a
003564f6: bde88040   pop.w {r7, lr}
003564fa: 0120       movs r0, #1
003564fc: 7047       bx lr

SLOT 32 OP 4031 WIRE 1d4 HANDLER 356518
00356518: 90f90810   ldrsb.w r1, [r0, #8]
0035651c: 4af22070   movw r0, #0xa720
00356520: c0f26510   movt r0, #0x165
00356524: 80f86c19   strb.w r1, [r0, #0x96c]
00356528: 43f2a430   movw r0, #0x33a4
0035652c: c0f2a510   movt r0, #0x1a5
00356530: 90f83200   ldrb.w r0, [r0, #0x32]
00356534: c007       lsls r0, r0, #0x1f
00356536: 06d0       beq #0x356546
00356538: 80b5       push {r7, lr}
0035653a: 6f46       mov r7, sp
0035653c: 03a0       adr r0, #0xc
0035653e: eef31cf0   bl #0xb4457a
00356542: bde88040   pop.w {r7, lr}
00356546: 0120       movs r0, #1
00356548: 7047       bx lr

SLOT 33 OP 4032 WIRE 1e0 HANDLER 356564
00356564: 90f90810   ldrsb.w r1, [r0, #8]
00356568: 4af22070   movw r0, #0xa720
0035656c: c0f26510   movt r0, #0x165
00356570: 80f8d21c   strb.w r1, [r0, #0xcd2]
00356574: 43f2a430   movw r0, #0x33a4
00356578: c0f2a510   movt r0, #0x1a5
0035657c: 90f83200   ldrb.w r0, [r0, #0x32]
00356580: c007       lsls r0, r0, #0x1f
00356582: 06d0       beq #0x356592
00356584: 80b5       push {r7, lr}
00356586: 6f46       mov r7, sp
00356588: 03a0       adr r0, #0xc
0035658a: edf3f6f7   bl #0xb4457a
0035658e: bde88040   pop.w {r7, lr}
00356592: 0120       movs r0, #1
00356594: 7047       bx lr

SLOT 34 OP 4033 WIRE 1ec HANDLER 356720
00356720: 90f90810   ldrsb.w r1, [r0, #8]
00356724: 4af22070   movw r0, #0xa720
00356728: c0f26510   movt r0, #0x165
0035672c: 80f86d19   strb.w r1, [r0, #0x96d]
00356730: 43f2a430   movw r0, #0x33a4
00356734: c0f2a510   movt r0, #0x1a5
00356738: 90f83200   ldrb.w r0, [r0, #0x32]
0035673c: c007       lsls r0, r0, #0x1f
0035673e: 06d0       beq #0x35674e
00356740: 80b5       push {r7, lr}
00356742: 6f46       mov r7, sp
00356744: 03a0       adr r0, #0xc
00356746: edf318f7   bl #0xb4457a
0035674a: bde88040   pop.w {r7, lr}
0035674e: 0120       movs r0, #1
00356750: 7047       bx lr

SLOT 35 OP 4034 WIRE 1f8 HANDLER 35676c
0035676c: 90f90810   ldrsb.w r1, [r0, #8]
00356770: 4af22070   movw r0, #0xa720
00356774: c0f26510   movt r0, #0x165
00356778: 80f86e19   strb.w r1, [r0, #0x96e]
0035677c: 43f2a430   movw r0, #0x33a4
00356780: c0f2a510   movt r0, #0x1a5
00356784: 90f83200   ldrb.w r0, [r0, #0x32]
00356788: c007       lsls r0, r0, #0x1f
0035678a: 06d0       beq #0x35679a
0035678c: 80b5       push {r7, lr}
0035678e: 6f46       mov r7, sp
00356790: 03a0       adr r0, #0xc
00356792: edf3f2f6   bl #0xb4457a
00356796: bde88040   pop.w {r7, lr}
0035679a: 0120       movs r0, #1
0035679c: 7047       bx lr

SLOT 36 OP 403a WIRE 204 HANDLER 355208
00355208: 017a       ldrb r1, [r0, #8]
0035520a: 4af22070   movw r0, #0xa720
0035520e: c0f26510   movt r0, #0x165
00355212: c0f8c812   str.w r1, [r0, #0x2c8]
00355216: 43f2a430   movw r0, #0x33a4
0035521a: c0f2a510   movt r0, #0x1a5
0035521e: 90f83200   ldrb.w r0, [r0, #0x32]
00355222: c007       lsls r0, r0, #0x1f
00355224: 06d0       beq #0x355234
00355226: 80b5       push {r7, lr}
00355228: 6f46       mov r7, sp
0035522a: 03a0       adr r0, #0xc
0035522c: eff3a5f1   bl #0xb4457a
00355230: bde88040   pop.w {r7, lr}
00355234: 0120       movs r0, #1
00355236: 7047       bx lr

SLOT 37 OP 4041 WIRE 210 HANDLER 3563e4
003563e4: 017a       ldrb r1, [r0, #8]
003563e6: 4af22070   movw r0, #0xa720
003563ea: c0f26510   movt r0, #0x165
003563ee: c0f87019   str.w r1, [r0, #0x970]
003563f2: 43f2a430   movw r0, #0x33a4
003563f6: c0f2a510   movt r0, #0x1a5
003563fa: 90f83200   ldrb.w r0, [r0, #0x32]
003563fe: c007       lsls r0, r0, #0x1f
00356400: 06d0       beq #0x356410
00356402: 80b5       push {r7, lr}
00356404: 6f46       mov r7, sp
00356406: 03a0       adr r0, #0xc
00356408: eef3b7f0   bl #0xb4457a
0035640c: bde88040   pop.w {r7, lr}
00356410: 0120       movs r0, #1
00356412: 7047       bx lr

SLOT 38 OP 4044 WIRE 21c HANDLER 356434
00356434: 017a       ldrb r1, [r0, #8]
00356436: 4af22070   movw r0, #0xa720
0035643a: c0f26510   movt r0, #0x165
0035643e: c0f87419   str.w r1, [r0, #0x974]
00356442: 43f2a430   movw r0, #0x33a4
00356446: c0f2a510   movt r0, #0x1a5
0035644a: 90f83200   ldrb.w r0, [r0, #0x32]
0035644e: c007       lsls r0, r0, #0x1f
00356450: 06d0       beq #0x356460
00356452: 80b5       push {r7, lr}
00356454: 6f46       mov r7, sp
00356456: 03a0       adr r0, #0xc
00356458: eef38ff0   bl #0xb4457a
0035645c: bde88040   pop.w {r7, lr}
00356460: 0120       movs r0, #1
00356462: 7047       bx lr

SLOT 39 OP 4047 WIRE 228 HANDLER 3567b4
003567b4: 017a       ldrb r1, [r0, #8]
003567b6: 4af22070   movw r0, #0xa720
003567ba: c0f26510   movt r0, #0x165
003567be: c0f8ec16   str.w r1, [r0, #0x6ec]
003567c2: 43f2a430   movw r0, #0x33a4
003567c6: c0f2a510   movt r0, #0x1a5
003567ca: 90f83200   ldrb.w r0, [r0, #0x32]
003567ce: c007       lsls r0, r0, #0x1f
003567d0: 06d0       beq #0x3567e0
003567d2: 80b5       push {r7, lr}
003567d4: 6f46       mov r7, sp
003567d6: 03a0       adr r0, #0xc
003567d8: edf3cff6   bl #0xb4457a
003567dc: bde88040   pop.w {r7, lr}
003567e0: 0120       movs r0, #1
003567e2: 7047       bx lr

SLOT 40 OP 4048 WIRE 234 HANDLER 3551a8
003551a8: 90f90810   ldrsb.w r1, [r0, #8]
003551ac: 4af2207c   movw ip, #0xa720
003551b0: c0f2651c   movt ip, #0x165
003551b4: 8cf8c012   strb.w r1, [ip, #0x2c0]
003551b8: 427a       ldrb r2, [r0, #9]
003551ba: ccf8c422   str.w r2, [ip, #0x2c4]
003551be: 837a       ldrb r3, [r0, #0xa]
003551c0: 43f2a430   movw r0, #0x33a4
003551c4: c0f2a510   movt r0, #0x1a5
003551c8: 90f83200   ldrb.w r0, [r0, #0x32]
003551cc: 8cf8bf32   strb.w r3, [ip, #0x2bf]
003551d0: c007       lsls r0, r0, #0x1f
003551d2: 06d0       beq #0x3551e2
003551d4: 80b5       push {r7, lr}
003551d6: 6f46       mov r7, sp
003551d8: 03a0       adr r0, #0xc
003551da: eff3cef1   bl #0xb4457a
003551de: bde88040   pop.w {r7, lr}
003551e2: 0120       movs r0, #1
003551e4: 7047       bx lr

SLOT 41 OP 4049 WIRE 240 HANDLER 35690c
0035690c: 017a       ldrb r1, [r0, #8]
0035690e: 4af22070   movw r0, #0xa720
00356912: c0f26510   movt r0, #0x165
00356916: c0f8c41c   str.w r1, [r0, #0xcc4]
0035691a: 43f2a430   movw r0, #0x33a4
0035691e: c0f2a510   movt r0, #0x1a5
00356922: 90f83200   ldrb.w r0, [r0, #0x32]
00356926: c007       lsls r0, r0, #0x1f
00356928: 06d0       beq #0x356938
0035692a: 80b5       push {r7, lr}
0035692c: 6f46       mov r7, sp
0035692e: 03a0       adr r0, #0xc
00356930: edf323f6   bl #0xb4457a
00356934: bde88040   pop.w {r7, lr}
00356938: 0120       movs r0, #1
0035693a: 7047       bx lr

SLOT 42 OP 404a WIRE 24c HANDLER 356954
00356954: b0b5       push {r4, r5, r7, lr}
00356956: 02af       add r7, sp, #8
00356958: 017a       ldrb r1, [r0, #8]
0035695a: 4af22074   movw r4, #0xa720
0035695e: 43f2a435   movw r5, #0x33a4
00356962: c0f26514   movt r4, #0x165
00356966: c0f2a515   movt r5, #0x1a5
0035696a: c4f8301d   str.w r1, [r4, #0xd30]
0035696e: 407a       ldrb r0, [r0, #9]
00356970: c4f8340d   str.w r0, [r4, #0xd34]
00356974: 95f83200   ldrb.w r0, [r5, #0x32]
00356978: 10f0010f   tst.w r0, #1
0035697c: 04d0       beq #0x356988
0035697e: 07a0       adr r0, #0x1c
00356980: edf3fbf5   bl #0xb4457a
00356984: 95f83200   ldrb.w r0, [r5, #0x32]
00356988: c007       lsls r0, r0, #0x1f
0035698a: 04d0       beq #0x356996
0035698c: d4f8341d   ldr.w r1, [r4, #0xd34]
00356990: 08a0       adr r0, #0x20
00356992: edf3f2f5   bl #0xb4457a
00356996: 0120       movs r0, #1
00356998: b0bd       pop {r4, r5, r7, pc}

SLOT 43 OP 404c WIRE 258 HANDLER 356a1c
00356a1c: 017a       ldrb r1, [r0, #8]
00356a1e: 4af22070   movw r0, #0xa720
00356a22: c0f26510   movt r0, #0x165
00356a26: c0f8f016   str.w r1, [r0, #0x6f0]
00356a2a: 43f2a430   movw r0, #0x33a4
00356a2e: c0f2a510   movt r0, #0x1a5
00356a32: 90f83200   ldrb.w r0, [r0, #0x32]
00356a36: c007       lsls r0, r0, #0x1f
00356a38: 06d0       beq #0x356a48
00356a3a: 80b5       push {r7, lr}
00356a3c: 6f46       mov r7, sp
00356a3e: 03a0       adr r0, #0xc
00356a40: edf39bf5   bl #0xb4457a
00356a44: bde88040   pop.w {r7, lr}
00356a48: 0120       movs r0, #1
00356a4a: 7047       bx lr

SLOT 44 OP 404d WIRE 264 HANDLER 35524c
0035524c: 017a       ldrb r1, [r0, #8]
0035524e: 4af22070   movw r0, #0xa720
00355252: c0f26510   movt r0, #0x165
00355256: 80f83513   strb.w r1, [r0, #0x335]
0035525a: 43f2a430   movw r0, #0x33a4
0035525e: c0f2a510   movt r0, #0x1a5
00355262: 90f83200   ldrb.w r0, [r0, #0x32]
00355266: c007       lsls r0, r0, #0x1f
00355268: 06d0       beq #0x355278
0035526a: 80b5       push {r7, lr}
0035526c: 6f46       mov r7, sp
0035526e: 03a0       adr r0, #0xc
00355270: eff383f1   bl #0xb4457a
00355274: bde88040   pop.w {r7, lr}
00355278: 0120       movs r0, #1
0035527a: 7047       bx lr

SLOT 45 OP 404f WIRE 270 HANDLER 35529c
0035529c: 017a       ldrb r1, [r0, #8]
0035529e: 4af22070   movw r0, #0xa720
003552a2: c0f26510   movt r0, #0x165
003552a6: 80f83613   strb.w r1, [r0, #0x336]
003552aa: 43f2a430   movw r0, #0x33a4
003552ae: c0f2a510   movt r0, #0x1a5
003552b2: 90f83200   ldrb.w r0, [r0, #0x32]
003552b6: c007       lsls r0, r0, #0x1f
003552b8: 06d0       beq #0x3552c8
003552ba: 80b5       push {r7, lr}
003552bc: 6f46       mov r7, sp
003552be: 03a0       adr r0, #0xc
003552c0: eff35bf1   bl #0xb4457a
003552c4: bde88040   pop.w {r7, lr}
003552c8: 0120       movs r0, #1
003552ca: 7047       bx lr

SLOT 46 OP 4050 WIRE 27c HANDLER 356b14
00356b14: 017a       ldrb r1, [r0, #8]
00356b16: 4af22070   movw r0, #0xa720
00356b1a: c0f26510   movt r0, #0x165
00356b1e: c0f87819   str.w r1, [r0, #0x978]
00356b22: 43f2a430   movw r0, #0x33a4
00356b26: c0f2a510   movt r0, #0x1a5
00356b2a: 90f83200   ldrb.w r0, [r0, #0x32]
00356b2e: c007       lsls r0, r0, #0x1f
00356b30: 06d0       beq #0x356b40
00356b32: 80b5       push {r7, lr}
00356b34: 6f46       mov r7, sp
00356b36: 03a0       adr r0, #0xc
00356b38: edf31ff5   bl #0xb4457a
00356b3c: bde88040   pop.w {r7, lr}
00356b40: 0120       movs r0, #1
00356b42: 7047       bx lr

SLOT 47 OP 4051 WIRE 288 HANDLER 356bb0
00356bb0: 017a       ldrb r1, [r0, #8]
00356bb2: 4af22070   movw r0, #0xa720
00356bb6: c0f26510   movt r0, #0x165
00356bba: c0f8181d   str.w r1, [r0, #0xd18]
00356bbe: 43f2a430   movw r0, #0x33a4
00356bc2: c0f2a510   movt r0, #0x1a5
00356bc6: 90f83200   ldrb.w r0, [r0, #0x32]
00356bca: c007       lsls r0, r0, #0x1f
00356bcc: 06d0       beq #0x356bdc
00356bce: 80b5       push {r7, lr}
00356bd0: 6f46       mov r7, sp
00356bd2: 03a0       adr r0, #0xc
00356bd4: edf3d1f4   bl #0xb4457a
00356bd8: bde88040   pop.w {r7, lr}
00356bdc: 0120       movs r0, #1
00356bde: 7047       bx lr

SLOT 48 OP 4052 WIRE 294 HANDLER 356c00
00356c00: 017a       ldrb r1, [r0, #8]
00356c02: 4af22070   movw r0, #0xa720
00356c06: c0f26510   movt r0, #0x165
00356c0a: c0f8201d   str.w r1, [r0, #0xd20]
00356c0e: 43f2a430   movw r0, #0x33a4
00356c12: c0f2a510   movt r0, #0x1a5
00356c16: 90f83200   ldrb.w r0, [r0, #0x32]
00356c1a: c007       lsls r0, r0, #0x1f
00356c1c: 06d0       beq #0x356c2c
00356c1e: 80b5       push {r7, lr}
00356c20: 6f46       mov r7, sp
00356c22: 03a0       adr r0, #0xc
00356c24: edf3a9f4   bl #0xb4457a
00356c28: bde88040   pop.w {r7, lr}
00356c2c: 0120       movs r0, #1
00356c2e: 7047       bx lr

SLOT 49 OP 4056 WIRE 2a0 HANDLER 8dae36
008dae36: f0b5       push {r4, r5, r6, r7, lr}
008dae38: 03af       add r7, sp, #0xc
008dae3a: 2de9000f   push.w {r8, sb, sl, fp}
008dae3e: b1b0       sub sp, #0xc4
008dae40: 017a       ldrb r1, [r0, #8]
008dae42: 4af22074   movw r4, #0xa720
008dae46: c0f26514   movt r4, #0x165
008dae4a: c4f85012   str.w r1, [r4, #0x250]
008dae4e: 417a       ldrb r1, [r0, #9]
008dae50: 84f85412   strb.w r1, [r4, #0x254]
008dae54: 817a       ldrb r1, [r0, #0xa]
008dae56: 84f85512   strb.w r1, [r4, #0x255]
008dae5a: c17a       ldrb r1, [r0, #0xb]
008dae5c: 84f85612   strb.w r1, [r4, #0x256]
008dae60: 017b       ldrb r1, [r0, #0xc]
008dae62: 84f85712   strb.w r1, [r4, #0x257]
008dae66: 417b       ldrb r1, [r0, #0xd]
008dae68: 84f85812   strb.w r1, [r4, #0x258]
008dae6c: 817b       ldrb r1, [r0, #0xe]
008dae6e: c4f85c12   str.w r1, [r4, #0x25c]
008dae72: c17b       ldrb r1, [r0, #0xf]
008dae74: 84f86012   strb.w r1, [r4, #0x260]
008dae78: 017c       ldrb r1, [r0, #0x10]
008dae7a: 84f86112   strb.w r1, [r4, #0x261]
008dae7e: 417c       ldrb r1, [r0, #0x11]
008dae80: 84f86212   strb.w r1, [r4, #0x262]
008dae84: 817c       ldrb r1, [r0, #0x12]
008dae86: 84f86312   strb.w r1, [r4, #0x263]
008dae8a: c17c       ldrb r1, [r0, #0x13]
008dae8c: 84f86412   strb.w r1, [r4, #0x264]
008dae90: 017d       ldrb r1, [r0, #0x14]
008dae92: 84f86512   strb.w r1, [r4, #0x265]
008dae96: 417d       ldrb r1, [r0, #0x15]
008dae98: 84f86612   strb.w r1, [r4, #0x266]
008dae9c: 90f91660   ldrsb.w r6, [r0, #0x16]
008daea0: 84f86762   strb.w r6, [r4, #0x267]
008daea4: 90f917c0   ldrsb.w ip, [r0, #0x17]
008daea8: 84f868c2   strb.w ip, [r4, #0x268]
008daeac: 037e       ldrb r3, [r0, #0x18]
008daeae: c4f86c32   str.w r3, [r4, #0x26c]
008daeb2: 90f91910   ldrsb.w r1, [r0, #0x19]
008daeb6: 3091       str r1, [sp, #0xc0]
008daeb8: 84f87012   strb.w r1, [r4, #0x270]
008daebc: 817e       ldrb r1, [r0, #0x1a]
008daebe: 2f91       str r1, [sp, #0xbc]
008daec0: 84f87112   strb.w r1, [r4, #0x271]
008daec4: c17e       ldrb r1, [r0, #0x1b]
008daec6: 2e91       str r1, [sp, #0xb8]
008daec8: 84f87212   strb.w r1, [r4, #0x272]
008daecc: 017f       ldrb r1, [r0, #0x1c]
008daece: 2d91       str r1, [sp, #0xb4]
008daed0: 84f87312   strb.w r1, [r4, #0x273]
008daed4: 417f       ldrb r1, [r0, #0x1d]
008daed6: 2c91       str r1, [sp, #0xb0]
008daed8: c4f87412   str.w r1, [r4, #0x274]
008daedc: 817f       ldrb r1, [r0, #0x1e]
008daede: 2b91       str r1, [sp, #0xac]
008daee0: 84f87812   strb.w r1, [r4, #0x278]
008daee4: 90f91f10   ldrsb.w r1, [r0, #0x1f]
008daee8: 2a91       str r1, [sp, #0xa8]
008daeea: 84f87912   strb.w r1, [r4, #0x279]
008daeee: 90f82020   ldrb.w r2, [r0, #0x20]
008daef2: 84f87a22   strb.w r2, [r4, #0x27a]
008daef6: 90f92110   ldrsb.w r1, [r0, #0x21]
008daefa: 84f87b12   strb.w r1, [r4, #0x27b]
008daefe: 90f922e0   ldrsb.w lr, [r0, #0x22]
008daf02: 84f87ce2   strb.w lr, [r4, #0x27c]
008daf06: 90f82380   ldrb.w r8, [r0, #0x23]
008daf0a: 84f87d82   strb.w r8, [r4, #0x27d]
008daf0e: 90f82490   ldrb.w sb, [r0, #0x24]
008daf12: 84f87e92   strb.w sb, [r4, #0x27e]
008daf16: 90f825a0   ldrb.w sl, [r0, #0x25]
008daf1a: 84f87fa2   strb.w sl, [r4, #0x27f]
008daf1e: 90f926b0   ldrsb.w fp, [r0, #0x26]
008daf22: 84f880b2   strb.w fp, [r4, #0x280]
008daf26: 90f82750   ldrb.w r5, [r0, #0x27]
008daf2a: c4f88452   str.w r5, [r4, #0x284]
008daf2e: 90f82850   ldrb.w r5, [r0, #0x28]
008daf32: c4f88852   str.w r5, [r4, #0x288]
008daf36: 458d       ldrh r5, [r0, #0x2a]
008daf38: a4f88c52   strh.w r5, [r4, #0x28c]
008daf3c: 90f82c50   ldrb.w r5, [r0, #0x2c]
008daf40: 84f88e52   strb.w r5, [r4, #0x28e]
008daf44: 90f82d50   ldrb.w r5, [r0, #0x2d]
008daf48: 84f88f52   strb.w r5, [r4, #0x28f]
008daf4c: 90f82e50   ldrb.w r5, [r0, #0x2e]
008daf50: 84f89052   strb.w r5, [r4, #0x290]
008daf54: 90f82f50   ldrb.w r5, [r0, #0x2f]
008daf58: 84f89152   strb.w r5, [r4, #0x291]
008daf5c: 058e       ldrh r5, [r0, #0x30]
008daf5e: a4f89252   strh.w r5, [r4, #0x292]
008daf62: 90f83250   ldrb.w r5, [r0, #0x32]
008daf66: 84f89452   strb.w r5, [r4, #0x294]
008daf6a: 90f83350   ldrb.w r5, [r0, #0x33]
008daf6e: 84f89552   strb.w r5, [r4, #0x295]
008daf72: 90f83450   ldrb.w r5, [r0, #0x34]
008daf76: 84f89652   strb.w r5, [r4, #0x296]
008daf7a: 90f83550   ldrb.w r5, [r0, #0x35]
008daf7e: 84f89752   strb.w r5, [r4, #0x297]
008daf82: 43f2a435   movw r5, #0x33a4
008daf86: c0f2a515   movt r5, #0x1a5
008daf8a: 90f83600   ldrb.w r0, [r0, #0x36]
008daf8e: 95f83250   ldrb.w r5, [r5, #0x32]
008daf92: c4f84c02   str.w r0, [r4, #0x24c]
008daf96: 15f0010f   tst.w r5, #1
008daf9a: 67d0       beq #0x8db06c
008daf9c: 94f95552   ldrsb.w r5, [r4, #0x255]
008dafa0: cdf86490   str.w sb, [sp, #0x64]
008dafa4: cdf868a0   str.w sl, [sp, #0x68]
008dafa8: cdf86cb0   str.w fp, [sp, #0x6c]
008dafac: 1c90       str r0, [sp, #0x70]
008dafae: 2995       str r5, [sp, #0xa4]
008dafb0: 94f85452   ldrb.w r5, [r4, #0x254]
008dafb4: 2895       str r5, [sp, #0xa0]
008dafb6: d4f85052   ldr.w r5, [r4, #0x250]
008dafba: 2795       str r5, [sp, #0x9c]
008dafbc: 94f95652   ldrsb.w r5, [r4, #0x256]
008dafc0: 2695       str r5, [sp, #0x98]
008dafc2: 94f95752   ldrsb.w r5, [r4, #0x257]
008dafc6: 2595       str r5, [sp, #0x94]
008dafc8: 94f95852   ldrsb.w r5, [r4, #0x258]
008dafcc: 2495       str r5, [sp, #0x90]
008dafce: d4f85c52   ldr.w r5, [r4, #0x25c]
008dafd2: 2395       str r5, [sp, #0x8c]
008dafd4: 94f96052   ldrsb.w r5, [r4, #0x260]
008dafd8: 2295       str r5, [sp, #0x88]
008dafda: 94f96152   ldrsb.w r5, [r4, #0x261]
008dafde: 2195       str r5, [sp, #0x84]
008dafe0: 94f96252   ldrsb.w r5, [r4, #0x262]
008dafe4: 2095       str r5, [sp, #0x80]
008dafe6: 94f96352   ldrsb.w r5, [r4, #0x263]
008dafea: 1f95       str r5, [sp, #0x7c]
008dafec: 94f96452   ldrsb.w r5, [r4, #0x264]
008daff0: 1e95       str r5, [sp, #0x78]
008daff2: 94f96552   ldrsb.w r5, [r4, #0x265]
008daff6: 1d95       str r5, [sp, #0x74]
008daff8: 94f96652   ldrsb.w r5, [r4, #0x266]
008daffc: cde917e8   strd lr, r8, [sp, #0x5c]
008db000: cde91521   strd r2, r1, [sp, #0x54]
008db004: 2a98       ldr r0, [sp, #0xa8]
008db006: 1490       str r0, [sp, #0x50]
008db008: 2b98       ldr r0, [sp, #0xac]
008db00a: 1390       str r0, [sp, #0x4c]
008db00c: 2c98       ldr r0, [sp, #0xb0]
008db00e: 1290       str r0, [sp, #0x48]
008db010: 2d98       ldr r0, [sp, #0xb4]
008db012: 1190       str r0, [sp, #0x44]
008db014: 2e98       ldr r0, [sp, #0xb8]
008db016: 1090       str r0, [sp, #0x40]
008db018: 2f98       ldr r0, [sp, #0xbc]
008db01a: 0f90       str r0, [sp, #0x3c]
008db01c: 3098       ldr r0, [sp, #0xc0]
008db01e: cde90d30   strd r3, r0, [sp, #0x34]
008db022: 0aa8       add r0, sp, #0x28
008db024: 80e86010   stm.w r0, {r5, r6, ip}
008db028: 1d98       ldr r0, [sp, #0x74]
008db02a: 0990       str r0, [sp, #0x24]
008db02c: 1e98       ldr r0, [sp, #0x78]
008db02e: 0890       str r0, [sp, #0x20]
008db030: 1f98       ldr r0, [sp, #0x7c]
008db032: 0790       str r0, [sp, #0x1c]
008db034: 2098       ldr r0, [sp, #0x80]
008db036: 0690       str r0, [sp, #0x18]
008db038: 2198       ldr r0, [sp, #0x84]
008db03a: 0590       str r0, [sp, #0x14]
008db03c: 2298       ldr r0, [sp, #0x88]
008db03e: 0490       str r0, [sp, #0x10]
008db040: 2398       ldr r0, [sp, #0x8c]
008db042: 0390       str r0, [sp, #0xc]
008db044: 2498       ldr r0, [sp, #0x90]
008db046: 0290       str r0, [sp, #8]
008db048: 2598       ldr r0, [sp, #0x94]
008db04a: 0190       str r0, [sp, #4]
008db04c: 2698       ldr r0, [sp, #0x98]
008db04e: 0090       str r0, [sp]
008db050: 27ab       add r3, sp, #0x9c
008db052: 4bf2de30   movw r0, #0xb3de
008db056: 0ecb       ldm r3, {r1, r2, r3}
008db058: c0f2f700   movt r0, #0xf7
008db05c: 69f28dfa   bl #0xb4457a
008db060: 43f2a430   movw r0, #0x33a4
008db064: c0f2a510   movt r0, #0x1a5
008db068: 90f83250   ldrb.w r5, [r0, #0x32]
008db06c: e807       lsls r0, r5, #0x1f
008db06e: 24d0       beq #0x8db0ba
008db070: b4f88c32   ldrh.w r3, [r4, #0x28c]
008db074: d4e9a112   ldrd r1, r2, [r4, #0x284]
008db078: 94f88ec2   ldrb.w ip, [r4, #0x28e]
008db07c: 94f88f62   ldrb.w r6, [r4, #0x28f]
008db080: 94f99052   ldrsb.w r5, [r4, #0x290]
008db084: 94f99102   ldrsb.w r0, [r4, #0x291]
008db088: b4f892e2   ldrh.w lr, [r4, #0x292]
008db08c: 94f89482   ldrb.w r8, [r4, #0x294]
008db090: 94f89592   ldrb.w sb, [r4, #0x295]
008db094: 94f996a2   ldrsb.w sl, [r4, #0x296]
008db098: 94f99742   ldrsb.w r4, [r4, #0x297]
008db09c: 0894       str r4, [sp, #0x20]
008db09e: cde90250   strd r5, r0, [sp, #8]
008db0a2: 4bf27540   movw r0, #0xb475
008db0a6: cde904e8   strd lr, r8, [sp, #0x10]
008db0aa: cde9069a   strd sb, sl, [sp, #0x18]
008db0ae: cde900c6   strd ip, r6, [sp]
008db0b2: c0f2f700   movt r0, #0xf7
008db0b6: 69f260fa   bl #0xb4457a
008db0ba: 0120       movs r0, #1
008db0bc: 31b0       add sp, #0xc4
008db0be: bde8000f   pop.w {r8, sb, sl, fp}
008db0c2: f0bd       pop {r4, r5, r6, r7, pc}

SLOT 50 OP 4059 WIRE 2d8 HANDLER 35535c
0035535c: 90f90810   ldrsb.w r1, [r0, #8]
00355360: 4af22073   movw r3, #0xa720
00355364: c0f26513   movt r3, #0x165
00355368: 83f82013   strb.w r1, [r3, #0x320]
0035536c: 427a       ldrb r2, [r0, #9]
0035536e: 83f82123   strb.w r2, [r3, #0x321]
00355372: 93f82203   ldrb.w r0, [r3, #0x322]
00355376: 0130       adds r0, #1
00355378: 83f82203   strb.w r0, [r3, #0x322]
0035537c: 43f2a433   movw r3, #0x33a4
00355380: c0f2a513   movt r3, #0x1a5
00355384: 93f83230   ldrb.w r3, [r3, #0x32]
00355388: db07       lsls r3, r3, #0x1f
0035538a: 07d0       beq #0x35539c
0035538c: 80b5       push {r7, lr}
0035538e: 6f46       mov r7, sp
00355390: c3b2       uxtb r3, r0
00355392: 03a0       adr r0, #0xc
00355394: eff3f1f0   bl #0xb4457a
00355398: bde88040   pop.w {r7, lr}
0035539c: 0120       movs r0, #1
0035539e: 7047       bx lr

SLOT 51 OP 405a WIRE 2e4 HANDLER 3553c0
003553c0: 017a       ldrb r1, [r0, #8]
003553c2: 4af22070   movw r0, #0xa720
003553c6: c0f26510   movt r0, #0x165
003553ca: 80f8d412   strb.w r1, [r0, #0x2d4]
003553ce: 43f2a430   movw r0, #0x33a4
003553d2: c0f2a510   movt r0, #0x1a5
003553d6: 90f83200   ldrb.w r0, [r0, #0x32]
003553da: c007       lsls r0, r0, #0x1f
003553dc: 06d0       beq #0x3553ec
003553de: 80b5       push {r7, lr}
003553e0: 6f46       mov r7, sp
003553e2: 03a0       adr r0, #0xc
003553e4: eff3c9f0   bl #0xb4457a
003553e8: bde88040   pop.w {r7, lr}
003553ec: 0120       movs r0, #1
003553ee: 7047       bx lr

SLOT 52 OP 405b WIRE 2f0 HANDLER 35540c
0035540c: 017a       ldrb r1, [r0, #8]
0035540e: 4af22070   movw r0, #0xa720
00355412: c0f26510   movt r0, #0x165
00355416: 80f8e812   strb.w r1, [r0, #0x2e8]
0035541a: 43f2a430   movw r0, #0x33a4
0035541e: c0f2a510   movt r0, #0x1a5
00355422: 90f83200   ldrb.w r0, [r0, #0x32]
00355426: c007       lsls r0, r0, #0x1f
00355428: 06d0       beq #0x355438
0035542a: 80b5       push {r7, lr}
0035542c: 6f46       mov r7, sp
0035542e: 03a0       adr r0, #0xc
00355430: eff3a3f0   bl #0xb4457a
00355434: bde88040   pop.w {r7, lr}
00355438: 0120       movs r0, #1
0035543a: 7047       bx lr

SLOT 53 OP 405c WIRE 2fc HANDLER 355458
00355458: 017a       ldrb r1, [r0, #8]
0035545a: 4af22070   movw r0, #0xa720
0035545e: c0f26510   movt r0, #0x165
00355462: 80f8cc12   strb.w r1, [r0, #0x2cc]
00355466: 43f2a430   movw r0, #0x33a4
0035546a: c0f2a510   movt r0, #0x1a5
0035546e: 90f83200   ldrb.w r0, [r0, #0x32]
00355472: c007       lsls r0, r0, #0x1f
00355474: 06d0       beq #0x355484
00355476: 80b5       push {r7, lr}
00355478: 6f46       mov r7, sp
0035547a: 03a0       adr r0, #0xc
0035547c: eff37df0   bl #0xb4457a
00355480: bde88040   pop.w {r7, lr}
00355484: 0120       movs r0, #1
00355486: 7047       bx lr

SLOT 54 OP 405d WIRE 308 HANDLER 356a6c
00356a6c: 017a       ldrb r1, [r0, #8]
00356a6e: 4af22070   movw r0, #0xa720
00356a72: c0f26510   movt r0, #0x165
00356a76: c0f8001d   str.w r1, [r0, #0xd00]
00356a7a: 43f2a430   movw r0, #0x33a4
00356a7e: c0f2a510   movt r0, #0x1a5
00356a82: 90f83200   ldrb.w r0, [r0, #0x32]
00356a86: c007       lsls r0, r0, #0x1f
00356a88: 06d0       beq #0x356a98
00356a8a: 80b5       push {r7, lr}
00356a8c: 6f46       mov r7, sp
00356a8e: 03a0       adr r0, #0xc
00356a90: edf373f5   bl #0xb4457a
00356a94: bde88040   pop.w {r7, lr}
00356a98: 0120       movs r0, #1
00356a9a: 7047       bx lr

SLOT 55 OP 405e WIRE 314 HANDLER 356ac0
00356ac0: 017a       ldrb r1, [r0, #8]
00356ac2: 4af22070   movw r0, #0xa720
00356ac6: c0f26510   movt r0, #0x165
00356aca: c0f8041d   str.w r1, [r0, #0xd04]
00356ace: 43f2a430   movw r0, #0x33a4
00356ad2: c0f2a510   movt r0, #0x1a5
00356ad6: 90f83200   ldrb.w r0, [r0, #0x32]
00356ada: c007       lsls r0, r0, #0x1f
00356adc: 06d0       beq #0x356aec
00356ade: 80b5       push {r7, lr}
00356ae0: 6f46       mov r7, sp
00356ae2: 03a0       adr r0, #0xc
00356ae4: edf349f5   bl #0xb4457a
00356ae8: bde88040   pop.w {r7, lr}
00356aec: 0120       movs r0, #1
00356aee: 7047       bx lr

SLOT 56 OP 405f WIRE 320 HANDLER 356c50
00356c50: 017a       ldrb r1, [r0, #8]
00356c52: 4af22070   movw r0, #0xa720
00356c56: c0f26510   movt r0, #0x165
00356c5a: c0f81c1d   str.w r1, [r0, #0xd1c]
00356c5e: 43f2a430   movw r0, #0x33a4
00356c62: c0f2a510   movt r0, #0x1a5
00356c66: 90f83200   ldrb.w r0, [r0, #0x32]
00356c6a: c007       lsls r0, r0, #0x1f
00356c6c: 06d0       beq #0x356c7c
00356c6e: 80b5       push {r7, lr}
00356c70: 6f46       mov r7, sp
00356c72: 03a0       adr r0, #0xc
00356c74: edf381f4   bl #0xb4457a
00356c78: bde88040   pop.w {r7, lr}
00356c7c: 0120       movs r0, #1
00356c7e: 7047       bx lr

SLOT 57 OP 4060 WIRE 32c HANDLER 8dae00
008dae00: 017a       ldrb r1, [r0, #8]
008dae02: 4af22070   movw r0, #0xa720
008dae06: c0f26510   movt r0, #0x165
008dae0a: c0f8281d   str.w r1, [r0, #0xd28]
008dae0e: 43f2a430   movw r0, #0x33a4
008dae12: c0f2a510   movt r0, #0x1a5
008dae16: 90f83200   ldrb.w r0, [r0, #0x32]
008dae1a: c007       lsls r0, r0, #0x1f
008dae1c: 09d0       beq #0x8dae32
008dae1e: 80b5       push {r7, lr}
008dae20: 6f46       mov r7, sp
008dae22: 4bf2c930   movw r0, #0xb3c9
008dae26: c0f2f700   movt r0, #0xf7
008dae2a: 69f2a6fb   bl #0xb4457a
008dae2e: bde88040   pop.w {r7, lr}
008dae32: 0120       movs r0, #1
008dae34: 7047       bx lr

SLOT 58 OP 4061 WIRE 338 HANDLER 356cf8
00356cf8: 017a       ldrb r1, [r0, #8]
00356cfa: 4af22070   movw r0, #0xa720
00356cfe: c0f26510   movt r0, #0x165
00356d02: c0f83c13   str.w r1, [r0, #0x33c]
00356d06: 43f2a430   movw r0, #0x33a4
00356d0a: c0f2a510   movt r0, #0x1a5
00356d0e: 90f83200   ldrb.w r0, [r0, #0x32]
00356d12: c007       lsls r0, r0, #0x1f
00356d14: 06d0       beq #0x356d24
00356d16: 80b5       push {r7, lr}
00356d18: 6f46       mov r7, sp
00356d1a: 03a0       adr r0, #0xc
00356d1c: edf32df4   bl #0xb4457a
00356d20: bde88040   pop.w {r7, lr}
00356d24: 0120       movs r0, #1
00356d26: 7047       bx lr

SLOT 59 OP 4062 WIRE 344 HANDLER 356ca0
00356ca0: 017a       ldrb r1, [r0, #8]
00356ca2: 4af22073   movw r3, #0xa720
00356ca6: c0f26513   movt r3, #0x165
00356caa: c3f8f816   str.w r1, [r3, #0x6f8]
00356cae: 427a       ldrb r2, [r0, #9]
00356cb0: 43f2a430   movw r0, #0x33a4
00356cb4: c0f2a510   movt r0, #0x1a5
00356cb8: 90f83200   ldrb.w r0, [r0, #0x32]
00356cbc: c3f8fc26   str.w r2, [r3, #0x6fc]
00356cc0: c007       lsls r0, r0, #0x1f
00356cc2: 06d0       beq #0x356cd2
00356cc4: 80b5       push {r7, lr}
00356cc6: 6f46       mov r7, sp
00356cc8: 03a0       adr r0, #0xc
00356cca: edf356f4   bl #0xb4457a
00356cce: bde88040   pop.w {r7, lr}
00356cd2: 0120       movs r0, #1
00356cd4: 7047       bx lr

SLOT 60 OP 4064 WIRE 350 HANDLER 356d40
00356d40: 017a       ldrb r1, [r0, #8]
00356d42: 4af22070   movw r0, #0xa720
00356d46: c0f26510   movt r0, #0x165
00356d4a: c0f80017   str.w r1, [r0, #0x700]
00356d4e: 43f2a430   movw r0, #0x33a4
00356d52: c0f2a510   movt r0, #0x1a5
00356d56: 90f83200   ldrb.w r0, [r0, #0x32]
00356d5a: c007       lsls r0, r0, #0x1f
00356d5c: 06d0       beq #0x356d6c
00356d5e: 80b5       push {r7, lr}
00356d60: 6f46       mov r7, sp
00356d62: 03a0       adr r0, #0xc
00356d64: edf309f4   bl #0xb4457a
00356d68: bde88040   pop.w {r7, lr}
00356d6c: 0120       movs r0, #1
00356d6e: 7047       bx lr

SLOT 61 OP 4066 WIRE 35c HANDLER 356e80
00356e80: 017a       ldrb r1, [r0, #8]
00356e82: 4af22070   movw r0, #0xa720
00356e86: c0f26510   movt r0, #0x165
00356e8a: c0f88c15   str.w r1, [r0, #0x58c]
00356e8e: 43f2a430   movw r0, #0x33a4
00356e92: c0f2a510   movt r0, #0x1a5
00356e96: 90f83200   ldrb.w r0, [r0, #0x32]
00356e9a: c007       lsls r0, r0, #0x1f
00356e9c: 06d0       beq #0x356eac
00356e9e: 80b5       push {r7, lr}
00356ea0: 6f46       mov r7, sp
00356ea2: 03a0       adr r0, #0xc
00356ea4: edf369f3   bl #0xb4457a
00356ea8: bde88040   pop.w {r7, lr}
00356eac: 0120       movs r0, #1
00356eae: 7047       bx lr

SLOT 62 OP 4067 WIRE 368 HANDLER 356ed0
00356ed0: 017a       ldrb r1, [r0, #8]
00356ed2: 4af22070   movw r0, #0xa720
00356ed6: c0f26510   movt r0, #0x165
00356eda: c0f80417   str.w r1, [r0, #0x704]
00356ede: 43f2a430   movw r0, #0x33a4
00356ee2: c0f2a510   movt r0, #0x1a5
00356ee6: 90f83200   ldrb.w r0, [r0, #0x32]
00356eea: c007       lsls r0, r0, #0x1f
00356eec: 06d0       beq #0x356efc
00356eee: 80b5       push {r7, lr}
00356ef0: 6f46       mov r7, sp
00356ef2: 03a0       adr r0, #0xc
00356ef4: edf341f3   bl #0xb4457a
00356ef8: bde88040   pop.w {r7, lr}
00356efc: 0120       movs r0, #1
00356efe: 7047       bx lr

SLOT 63 OP 406e WIRE 374 HANDLER 356f68
00356f68: 017a       ldrb r1, [r0, #8]
00356f6a: 4af22070   movw r0, #0xa720
00356f6e: c0f26510   movt r0, #0x165
00356f72: c0f89015   str.w r1, [r0, #0x590]
00356f76: 43f2a430   movw r0, #0x33a4
00356f7a: c0f2a510   movt r0, #0x1a5
00356f7e: 90f83200   ldrb.w r0, [r0, #0x32]
00356f82: c007       lsls r0, r0, #0x1f
00356f84: 06d0       beq #0x356f94
00356f86: 80b5       push {r7, lr}
00356f88: 6f46       mov r7, sp
00356f8a: 03a0       adr r0, #0xc
00356f8c: edf3f5f2   bl #0xb4457a
00356f90: bde88040   pop.w {r7, lr}
00356f94: 0120       movs r0, #1
00356f96: 7047       bx lr

SLOT 64 OP 4078 WIRE 380 HANDLER 35793c
0035793c: 017a       ldrb r1, [r0, #8]
0035793e: 4af22073   movw r3, #0xa720
00357942: c0f26513   movt r3, #0x165
00357946: c3f84c13   str.w r1, [r3, #0x34c]
0035794a: 427a       ldrb r2, [r0, #9]
0035794c: 43f2a430   movw r0, #0x33a4
00357950: c0f2a510   movt r0, #0x1a5
00357954: 90f83200   ldrb.w r0, [r0, #0x32]
00357958: c3f85023   str.w r2, [r3, #0x350]
0035795c: c007       lsls r0, r0, #0x1f
0035795e: 06d0       beq #0x35796e
00357960: 80b5       push {r7, lr}
00357962: 6f46       mov r7, sp
00357964: 03a0       adr r0, #0xc
00357966: ecf308f6   bl #0xb4457a
0035796a: bde88040   pop.w {r7, lr}
0035796e: 0120       movs r0, #1
00357970: 7047       bx lr

SLOT 65 OP 4079 WIRE 38c HANDLER 357998
00357998: 017a       ldrb r1, [r0, #8]
0035799a: 4af22070   movw r0, #0xa720
0035799e: c0f26510   movt r0, #0x165
003579a2: c0f85413   str.w r1, [r0, #0x354]
003579a6: 43f2a430   movw r0, #0x33a4
003579aa: c0f2a510   movt r0, #0x1a5
003579ae: 90f83200   ldrb.w r0, [r0, #0x32]
003579b2: c007       lsls r0, r0, #0x1f
003579b4: 06d0       beq #0x3579c4
003579b6: 80b5       push {r7, lr}
003579b8: 6f46       mov r7, sp
003579ba: 03a0       adr r0, #0xc
003579bc: ecf3ddf5   bl #0xb4457a
003579c0: bde88040   pop.w {r7, lr}
003579c4: 0120       movs r0, #1
003579c6: 7047       bx lr

SLOT 66 OP 407a WIRE 398 HANDLER 3579e4
003579e4: d0b5       push {r4, r6, r7, lr}
003579e6: 02af       add r7, sp, #8
003579e8: 017a       ldrb r1, [r0, #8]
003579ea: 4af22074   movw r4, #0xa720
003579ee: c0f26514   movt r4, #0x165
003579f2: c4f8a411   str.w r1, [r4, #0x1a4]
003579f6: 0139       subs r1, #1
003579f8: 0c29       cmp r1, #0xc
003579fa: 28d8       bhi #0x357a4e
003579fc: dfe801f0   tbb [pc, r1]
00357a00: 0727       movs r7, #7
00357a02: 0e27       movs r7, #0xe
00357a04: 1012       asrs r0, r2, #8
00357a06: 1416       asrs r4, r2, #0x18
00357a08: 1827       movs r7, #0x18
00357a0a: 1a22       movs r2, #0x1a
00357a0c: 2400       movs r4, r4
00357a0e: c17a       ldrb r1, [r0, #0xb]
00357a10: c4f8a811   str.w r1, [r4, #0x1a8]
00357a14: c07c       ldrb r0, [r0, #0x13]
00357a16: 84f8ac01   strb.w r0, [r4, #0x1ac]
00357a1a: 18e0       b #0x357a4e
00357a4e: 43f2a430   movw r0, #0x33a4
00357a52: c0f2a510   movt r0, #0x1a5
00357a56: 90f83200   ldrb.w r0, [r0, #0x32]
00357a5a: c007       lsls r0, r0, #0x1f
00357a5c: 04d0       beq #0x357a68
00357a5e: d4f8a411   ldr.w r1, [r4, #0x1a4]
00357a62: 02a0       adr r0, #8
00357a64: ecf389f5   bl #0xb4457a
00357a68: 0120       movs r0, #1
00357a6a: d0bd       pop {r4, r6, r7, pc}

SLOT 67 OP 407c WIRE 3ac HANDLER 3547d4
003547d4: 017a       ldrb r1, [r0, #8]
003547d6: 4af22072   movw r2, #0xa720
003547da: c0f26512   movt r2, #0x165
003547de: 0129       cmp r1, #1
003547e0: 0846       mov r0, r1
003547e2: 18bf       it ne
003547e4: 0020       movs r0, #0
003547e6: 82f8b80b   strb.w r0, [r2, #0xbb8]
003547ea: 43f2a430   movw r0, #0x33a4
003547ee: c0f2a510   movt r0, #0x1a5
003547f2: 90f83200   ldrb.w r0, [r0, #0x32]
003547f6: c007       lsls r0, r0, #0x1f
003547f8: 09d0       beq #0x35480e
003547fa: 80b5       push {r7, lr}
003547fc: 6f46       mov r7, sp
003547fe: 0129       cmp r1, #1
00354800: 04a0       adr r0, #0x10
00354802: 18bf       it ne
00354804: 0021       movs r1, #0
00354806: eff3b8f6   bl #0xb4457a
0035480a: bde88040   pop.w {r7, lr}
0035480e: 0120       movs r0, #1
00354810: 7047       bx lr

SLOT 68 OP 407d WIRE 3b8 HANDLER 357ad8
00357ad8: 017a       ldrb r1, [r0, #8]
00357ada: 4af22070   movw r0, #0xa720
00357ade: c0f26510   movt r0, #0x165
00357ae2: c0f8481b   str.w r1, [r0, #0xb48]
00357ae6: 43f2a430   movw r0, #0x33a4
00357aea: c0f2a510   movt r0, #0x1a5
00357aee: 90f83200   ldrb.w r0, [r0, #0x32]
00357af2: c007       lsls r0, r0, #0x1f
00357af4: 06d0       beq #0x357b04
00357af6: 80b5       push {r7, lr}
00357af8: 6f46       mov r7, sp
00357afa: 03a0       adr r0, #0xc
00357afc: ecf33df5   bl #0xb4457a
00357b00: bde88040   pop.w {r7, lr}
00357b04: 0120       movs r0, #1
00357b06: 7047       bx lr

SLOT 69 OP 407e WIRE 3c4 HANDLER 357b28
00357b28: d0b5       push {r4, r6, r7, lr}
00357b2a: 02af       add r7, sp, #8
00357b2c: 007a       ldrb r0, [r0, #8]
00357b2e: 4af22074   movw r4, #0xa720
00357b32: c0f26514   movt r4, #0x165
00357b36: c4f80402   str.w r0, [r4, #0x204]
00357b3a: 82f120f7   bl #0x8da97e
00357b3e: 43f2a430   movw r0, #0x33a4
00357b42: c0f2a510   movt r0, #0x1a5
00357b46: 90f83200   ldrb.w r0, [r0, #0x32]
00357b4a: c007       lsls r0, r0, #0x1f
00357b4c: 04d0       beq #0x357b58
00357b4e: d4f80412   ldr.w r1, [r4, #0x204]
00357b52: 02a0       adr r0, #8
00357b54: ecf311f5   bl #0xb4457a
00357b58: 0120       movs r0, #1
00357b5a: d0bd       pop {r4, r6, r7, pc}

SLOT 70 OP 407f WIRE 3d0 HANDLER 357b7c
00357b7c: d0b5       push {r4, r6, r7, lr}
00357b7e: 02af       add r7, sp, #8
00357b80: 007a       ldrb r0, [r0, #8]
00357b82: 4af22074   movw r4, #0xa720
00357b86: c0f26514   movt r4, #0x165
00357b8a: c4f80c02   str.w r0, [r4, #0x20c]
00357b8e: 82f1f6f6   bl #0x8da97e
00357b92: 43f2a430   movw r0, #0x33a4
00357b96: c0f2a510   movt r0, #0x1a5
00357b9a: 90f83200   ldrb.w r0, [r0, #0x32]
00357b9e: c007       lsls r0, r0, #0x1f
00357ba0: 04d0       beq #0x357bac
00357ba2: d4f80c12   ldr.w r1, [r4, #0x20c]
00357ba6: 02a0       adr r0, #8
00357ba8: ecf3e7f4   bl #0xb4457a
00357bac: 0120       movs r0, #1
00357bae: d0bd       pop {r4, r6, r7, pc}

SLOT 71 OP 4080 WIRE 3dc HANDLER 357bd4
00357bd4: d0b5       push {r4, r6, r7, lr}
00357bd6: 02af       add r7, sp, #8
00357bd8: 007a       ldrb r0, [r0, #8]
00357bda: 4af22074   movw r4, #0xa720
00357bde: c0f26514   movt r4, #0x165
00357be2: c4f8fc01   str.w r0, [r4, #0x1fc]
00357be6: 82f1caf6   bl #0x8da97e
00357bea: 43f2a430   movw r0, #0x33a4
00357bee: c0f2a510   movt r0, #0x1a5
00357bf2: 90f83200   ldrb.w r0, [r0, #0x32]
00357bf6: c007       lsls r0, r0, #0x1f
00357bf8: 04d0       beq #0x357c04
00357bfa: d4f8fc11   ldr.w r1, [r4, #0x1fc]
00357bfe: 02a0       adr r0, #8
00357c00: ecf3bbf4   bl #0xb4457a
00357c04: 0120       movs r0, #1
00357c06: d0bd       pop {r4, r6, r7, pc}

SLOT 72 OP 4082 WIRE 3e8 HANDLER 357c2c
00357c2c: 017a       ldrb r1, [r0, #8]
00357c2e: 4af22070   movw r0, #0xa720
00357c32: c0f26510   movt r0, #0x165
00357c36: c0f8ac15   str.w r1, [r0, #0x5ac]
00357c3a: 43f2a430   movw r0, #0x33a4
00357c3e: c0f2a510   movt r0, #0x1a5
00357c42: 90f83200   ldrb.w r0, [r0, #0x32]
00357c46: c007       lsls r0, r0, #0x1f
00357c48: 06d0       beq #0x357c58
00357c4a: 80b5       push {r7, lr}
00357c4c: 6f46       mov r7, sp
00357c4e: 03a0       adr r0, #0xc
00357c50: ecf393f4   bl #0xb4457a
00357c54: bde88040   pop.w {r7, lr}
00357c58: 0120       movs r0, #1
00357c5a: 7047       bx lr

SLOT 73 OP 4083 WIRE 3f4 HANDLER 35482c
0035482c: d0b5       push {r4, r6, r7, lr}
0035482e: 02af       add r7, sp, #8
00354830: 82b0       sub sp, #8
00354832: 007a       ldrb r0, [r0, #8]
00354834: 4af22074   movw r4, #0xa720
00354838: c0f26514   movt r4, #0x165
0035483c: 0228       cmp r0, #2
0035483e: 84f8d10b   strb.w r0, [r4, #0xbd1]
00354842: 06d1       bne #0x354852
00354844: 0120       movs r0, #1
00354846: 8df80000   strb.w r0, [sp]
0035484a: 0190       str r0, [sp, #4]
0035484c: 6846       mov r0, sp
0035484e: 97f05ef6   bl #0x7ec50e
00354852: 43f2a430   movw r0, #0x33a4
00354856: c0f2a510   movt r0, #0x1a5
0035485a: 90f83200   ldrb.w r0, [r0, #0x32]
0035485e: c007       lsls r0, r0, #0x1f
00354860: 04d0       beq #0x35486c
00354862: 94f8d11b   ldrb.w r1, [r4, #0xbd1]
00354866: 03a0       adr r0, #0xc
00354868: eff387f6   bl #0xb4457a
0035486c: 0120       movs r0, #1
0035486e: 02b0       add sp, #8
00354870: d0bd       pop {r4, r6, r7, pc}

SLOT 74 OP 4084 WIRE 400 HANDLER 357c7c
00357c7c: 017a       ldrb r1, [r0, #8]
00357c7e: 4af22070   movw r0, #0xa720
00357c82: c0f26510   movt r0, #0x165
00357c86: 80f83713   strb.w r1, [r0, #0x337]
00357c8a: 43f2a430   movw r0, #0x33a4
00357c8e: c0f2a510   movt r0, #0x1a5
00357c92: 90f83200   ldrb.w r0, [r0, #0x32]
00357c96: c007       lsls r0, r0, #0x1f
00357c98: 06d0       beq #0x357ca8
00357c9a: 80b5       push {r7, lr}
00357c9c: 6f46       mov r7, sp
00357c9e: 03a0       adr r0, #0xc
00357ca0: ecf36bf4   bl #0xb4457a
00357ca4: bde88040   pop.w {r7, lr}
00357ca8: 0120       movs r0, #1
00357caa: 7047       bx lr

SLOT 75 OP 4086 WIRE 40c HANDLER 357db8
00357db8: 017a       ldrb r1, [r0, #8]
00357dba: 4af22070   movw r0, #0xa720
00357dbe: c0f26510   movt r0, #0x165
00357dc2: 80f85813   strb.w r1, [r0, #0x358]
00357dc6: 43f2a430   movw r0, #0x33a4
00357dca: c0f2a510   movt r0, #0x1a5
00357dce: 90f83200   ldrb.w r0, [r0, #0x32]
00357dd2: c007       lsls r0, r0, #0x1f
00357dd4: 06d0       beq #0x357de4
00357dd6: 80b5       push {r7, lr}
00357dd8: 6f46       mov r7, sp
00357dda: 03a0       adr r0, #0xc
00357ddc: ecf3cdf3   bl #0xb4457a
00357de0: bde88040   pop.w {r7, lr}
00357de4: 0120       movs r0, #1
00357de6: 7047       bx lr

SLOT 76 OP 4088 WIRE 418 HANDLER 357e58
00357e58: 017a       ldrb r1, [r0, #8]
00357e5a: 4af22070   movw r0, #0xa720
00357e5e: c0f26510   movt r0, #0x165
00357e62: c0f8b011   str.w r1, [r0, #0x1b0]
00357e66: 43f2a430   movw r0, #0x33a4
00357e6a: c0f2a510   movt r0, #0x1a5
00357e6e: 90f83200   ldrb.w r0, [r0, #0x32]
00357e72: c007       lsls r0, r0, #0x1f
00357e74: 06d0       beq #0x357e84
00357e76: 80b5       push {r7, lr}
00357e78: 6f46       mov r7, sp
00357e7a: 03a0       adr r0, #0xc
00357e7c: ecf37df3   bl #0xb4457a
00357e80: bde88040   pop.w {r7, lr}
00357e84: 0120       movs r0, #1
00357e86: 7047       bx lr

SLOT 77 OP 4089 WIRE 424 HANDLER 354710
00354710: 017a       ldrb r1, [r0, #8]
00354712: 4af22072   movw r2, #0xa720
00354716: c0f26512   movt r2, #0x165
0035471a: 0029       cmp r1, #0
0035471c: 0846       mov r0, r1
0035471e: 18bf       it ne
00354720: 0120       movs r0, #1
00354722: 82f8e401   strb.w r0, [r2, #0x1e4]
00354726: 43f2a430   movw r0, #0x33a4
0035472a: c0f2a510   movt r0, #0x1a5
0035472e: 90f83200   ldrb.w r0, [r0, #0x32]
00354732: c007       lsls r0, r0, #0x1f
00354734: 09d0       beq #0x35474a
00354736: 80b5       push {r7, lr}
00354738: 6f46       mov r7, sp
0035473a: 0029       cmp r1, #0
0035473c: 04a0       adr r0, #0x10
0035473e: 18bf       it ne
00354740: 0121       movs r1, #1
00354742: eff31af7   bl #0xb4457a
00354746: bde88040   pop.w {r7, lr}
0035474a: 0120       movs r0, #1
0035474c: 7047       bx lr

SLOT 78 OP 408c WIRE 430 HANDLER 357f38
00357f38: 017a       ldrb r1, [r0, #8]
00357f3a: 4af22072   movw r2, #0xa720
00357f3e: c0f26512   movt r2, #0x165
00357f42: 0129       cmp r1, #1
00357f44: 0846       mov r0, r1
00357f46: 18bf       it ne
00357f48: 0020       movs r0, #0
00357f4a: 82f8d20b   strb.w r0, [r2, #0xbd2]
00357f4e: 43f2a430   movw r0, #0x33a4
00357f52: c0f2a510   movt r0, #0x1a5
00357f56: 90f83200   ldrb.w r0, [r0, #0x32]
00357f5a: c007       lsls r0, r0, #0x1f
00357f5c: 09d0       beq #0x357f72
00357f5e: 80b5       push {r7, lr}
00357f60: 6f46       mov r7, sp
00357f62: 0129       cmp r1, #1
00357f64: 04a0       adr r0, #0x10
00357f66: 18bf       it ne
00357f68: 0021       movs r1, #0
00357f6a: ecf306f3   bl #0xb4457a
00357f6e: bde88040   pop.w {r7, lr}
00357f72: 0120       movs r0, #1
00357f74: 7047       bx lr

SLOT 79 OP 408d WIRE 43c HANDLER 355bd8
00355bd8: 017a       ldrb r1, [r0, #8]
00355bda: 4af22070   movw r0, #0xa720
00355bde: c0f26510   movt r0, #0x165
00355be2: c0f8d012   str.w r1, [r0, #0x2d0]
00355be6: 43f2a430   movw r0, #0x33a4
00355bea: c0f2a510   movt r0, #0x1a5
00355bee: 90f83200   ldrb.w r0, [r0, #0x32]
00355bf2: c007       lsls r0, r0, #0x1f
00355bf4: 06d0       beq #0x355c04
00355bf6: 80b5       push {r7, lr}
00355bf8: 6f46       mov r7, sp
00355bfa: 03a0       adr r0, #0xc
00355bfc: eef3bdf4   bl #0xb4457a
00355c00: bde88040   pop.w {r7, lr}
00355c04: 0120       movs r0, #1
00355c06: 7047       bx lr

SLOT 80 OP 4093 WIRE 448 HANDLER 357fe8
00357fe8: 017a       ldrb r1, [r0, #8]
00357fea: 4af22070   movw r0, #0xa720
00357fee: c0f26510   movt r0, #0x165
00357ff2: c0f85c13   str.w r1, [r0, #0x35c]
00357ff6: 43f2a430   movw r0, #0x33a4
00357ffa: c0f2a510   movt r0, #0x1a5
00357ffe: 90f83200   ldrb.w r0, [r0, #0x32]
00358002: c007       lsls r0, r0, #0x1f
00358004: 06d0       beq #0x358014
00358006: 80b5       push {r7, lr}
00358008: 6f46       mov r7, sp
0035800a: 03a0       adr r0, #0xc
0035800c: ecf3b5f2   bl #0xb4457a
00358010: bde88040   pop.w {r7, lr}
00358014: 0120       movs r0, #1
00358016: 7047       bx lr

SLOT 81 OP 4097 WIRE 454 HANDLER 8db234
008db234: 80b5       push {r7, lr}
008db236: 6f46       mov r7, sp
008db238: 027a       ldrb r2, [r0, #8]
008db23a: 4af22070   movw r0, #0xa720
008db23e: 42f22901   movw r1, #0x2029
008db242: c0f26510   movt r0, #0x165
008db246: 80f8512b   strb.w r2, [r0, #0xb51]
008db24a: 0420       movs r0, #4
008db24c: 1346       mov r3, r2
008db24e: 68f2e5f9   bl #0xb4361c
008db252: 0120       movs r0, #1
008db254: 80bd       pop {r7, pc}

SLOT 82 OP 409a WIRE 460 HANDLER 358278
00358278: 017a       ldrb r1, [r0, #8]
0035827a: 4af22070   movw r0, #0xa720
0035827e: c0f26510   movt r0, #0x165
00358282: c0f84c17   str.w r1, [r0, #0x74c]
00358286: 43f2a430   movw r0, #0x33a4
0035828a: c0f2a510   movt r0, #0x1a5
0035828e: 90f83200   ldrb.w r0, [r0, #0x32]
00358292: c007       lsls r0, r0, #0x1f
00358294: 06d0       beq #0x3582a4
00358296: 80b5       push {r7, lr}
00358298: 6f46       mov r7, sp
0035829a: 03a0       adr r0, #0xc
0035829c: ecf36df1   bl #0xb4457a
003582a0: bde88040   pop.w {r7, lr}
003582a4: 0120       movs r0, #1
003582a6: 7047       bx lr

SLOT 83 OP 40a1 WIRE 46c HANDLER 8db332
008db332: 017a       ldrb r1, [r0, #8]
008db334: 4af22070   movw r0, #0xa720
008db338: c0f26510   movt r0, #0x165
008db33c: c0f85017   str.w r1, [r0, #0x750]
008db340: 43f2a430   movw r0, #0x33a4
008db344: c0f2a510   movt r0, #0x1a5
008db348: 90f83200   ldrb.w r0, [r0, #0x32]
008db34c: c007       lsls r0, r0, #0x1f
008db34e: 09d0       beq #0x8db364
008db350: 80b5       push {r7, lr}
008db352: 6f46       mov r7, sp
008db354: 4bf28050   movw r0, #0xb580
008db358: c0f2f700   movt r0, #0xf7
008db35c: 69f20df9   bl #0xb4457a
008db360: bde88040   pop.w {r7, lr}
008db364: 0120       movs r0, #1
008db366: 7047       bx lr

SLOT 84 OP 40a2 WIRE 478 HANDLER 35858c
0035858c: d0b5       push {r4, r6, r7, lr}
0035858e: 02af       add r7, sp, #8
00358590: 0446       mov r4, r0
00358592: d5f30ff4   bl #0xb2ddb4
00358596: c068       ldr r0, [r0, #0xc]
00358598: d0f85009   ldr.w r0, [r0, #0x950]
0035859c: 0028       cmp r0, #0
0035859e: 43f2a430   movw r0, #0x33a4
003585a2: 08bf       it eq
003585a4: 227a       ldrb r2, [r4, #8]
003585a6: c0f2a510   movt r0, #0x1a5
003585aa: 4af22074   movw r4, #0xa720
003585ae: c0f26514   movt r4, #0x165
003585b2: 18bf       it ne
003585b4: 0022       movs r2, #0
003585b6: 90f83200   ldrb.w r0, [r0, #0x32]
003585ba: c4f89c22   str.w r2, [r4, #0x29c]
003585be: c007       lsls r0, r0, #0x1f
003585c0: 05d0       beq #0x3585ce
003585c2: 1ba0       adr r0, #0x6c
003585c4: 1146       mov r1, r2
003585c6: ebf3d8f7   bl #0xb4457a
003585ca: d4f89c22   ldr.w r2, [r4, #0x29c]
003585ce: 0420       movs r0, #4
003585d0: 42f23401   movw r1, #0x2034
003585d4: ff23       movs r3, #0xff
003585d6: ebf321f0   bl #0xb4361c
003585da: d4f83801   ldr.w r0, [r4, #0x138]
003585de: 2028       cmp r0, #0x20
003585e0: 0bd0       beq #0x3585fa
003585e2: 1f28       cmp r0, #0x1f
003585e4: 0bd1       bne #0x3585fe
003585e6: d5f3e5f3   bl #0xb2ddb4
003585ea: c068       ldr r0, [r0, #0xc]
003585ec: d0f85019   ldr.w r1, [r0, #0x950]
003585f0: 0220       movs r0, #2
003585f2: 0029       cmp r1, #0
003585f4: 08bf       it eq
003585f6: 0120       movs r0, #1
003585f8: 10e0       b #0x35861c
003585fa: 0220       movs r0, #2
003585fc: 0ee0       b #0x35861c
003585fe: d4f89c02   ldr.w r0, [r4, #0x29c]
00358602: 0228       cmp r0, #2
00358604: 07d0       beq #0x358616
00358606: 0128       cmp r0, #1
00358608: 07d1       bne #0x35861a
0035860a: d4f8a002   ldr.w r0, [r4, #0x2a0]
0035860e: 0128       cmp r0, #1
00358610: 18bf       it ne
00358612: 0020       movs r0, #0
00358614: 02e0       b #0x35861c
00358616: 0120       movs r0, #1
00358618: 00e0       b #0x35861c
0035861a: 0020       movs r0, #0
0035861c: 84f8a402   strb.w r0, [r4, #0x2a4]
00358620: 82f1adf1   bl #0x8da97e
00358624: 2046       mov r0, r4
00358626: b5f3fbf3   bl #0xb0de20
0035862a: 0120       movs r0, #1
0035862c: d0bd       pop {r4, r6, r7, pc}

SLOT 85 OP 40a4 WIRE 484 HANDLER 356d84
00356d84: 017a       ldrb r1, [r0, #8]
00356d86: 4af22070   movw r0, #0xa720
00356d8a: c0f26510   movt r0, #0x165
00356d8e: c0f86413   str.w r1, [r0, #0x364]
00356d92: 43f2a430   movw r0, #0x33a4
00356d96: c0f2a510   movt r0, #0x1a5
00356d9a: 90f83200   ldrb.w r0, [r0, #0x32]
00356d9e: c007       lsls r0, r0, #0x1f
00356da0: 06d0       beq #0x356db0
00356da2: 80b5       push {r7, lr}
00356da4: 6f46       mov r7, sp
00356da6: 03a0       adr r0, #0xc
00356da8: edf3e7f3   bl #0xb4457a
00356dac: bde88040   pop.w {r7, lr}
00356db0: 0120       movs r0, #1
00356db2: 7047       bx lr

SLOT 86 OP 40a6 WIRE 490 HANDLER 358644
00358644: 017a       ldrb r1, [r0, #8]
00358646: 4af22070   movw r0, #0xa720
0035864a: c0f26510   movt r0, #0x165
0035864e: c0f85817   str.w r1, [r0, #0x758]
00358652: 43f2a430   movw r0, #0x33a4
00358656: c0f2a510   movt r0, #0x1a5
0035865a: 90f83200   ldrb.w r0, [r0, #0x32]
0035865e: c007       lsls r0, r0, #0x1f
00358660: 06d0       beq #0x358670
00358662: 80b5       push {r7, lr}
00358664: 6f46       mov r7, sp
00358666: 03a0       adr r0, #0xc
00358668: ebf387f7   bl #0xb4457a
0035866c: bde88040   pop.w {r7, lr}
00358670: 0120       movs r0, #1
00358672: 7047       bx lr

SLOT 87 OP 40a7 WIRE 49c HANDLER 35869c
0035869c: 017a       ldrb r1, [r0, #8]
0035869e: 4af22070   movw r0, #0xa720
003586a2: c0f26510   movt r0, #0x165
003586a6: c0f85c17   str.w r1, [r0, #0x75c]
003586aa: 43f2a430   movw r0, #0x33a4
003586ae: c0f2a510   movt r0, #0x1a5
003586b2: 90f83200   ldrb.w r0, [r0, #0x32]
003586b6: c007       lsls r0, r0, #0x1f
003586b8: 06d0       beq #0x3586c8
003586ba: 80b5       push {r7, lr}
003586bc: 6f46       mov r7, sp
003586be: 03a0       adr r0, #0xc
003586c0: ebf35bf7   bl #0xb4457a
003586c4: bde88040   pop.w {r7, lr}
003586c8: 0120       movs r0, #1
003586ca: 7047       bx lr

SLOT 88 OP 40a9 WIRE 4a8 HANDLER 356dcc
00356dcc: 017a       ldrb r1, [r0, #8]
00356dce: 4af22070   movw r0, #0xa720
00356dd2: c0f26510   movt r0, #0x165
00356dd6: c0f86813   str.w r1, [r0, #0x368]
00356dda: 43f2a430   movw r0, #0x33a4
00356dde: c0f2a510   movt r0, #0x1a5
00356de2: 90f83200   ldrb.w r0, [r0, #0x32]
00356de6: c007       lsls r0, r0, #0x1f
00356de8: 06d0       beq #0x356df8
00356dea: 80b5       push {r7, lr}
00356dec: 6f46       mov r7, sp
00356dee: 03a0       adr r0, #0xc
00356df0: edf3c3f3   bl #0xb4457a
00356df4: bde88040   pop.w {r7, lr}
00356df8: 0120       movs r0, #1
00356dfa: 7047       bx lr

SLOT 89 OP 40aa WIRE 4b4 HANDLER 3582c4
003582c4: 017a       ldrb r1, [r0, #8]
003582c6: 4af22070   movw r0, #0xa720
003582ca: c0f26510   movt r0, #0x165
003582ce: c0f86417   str.w r1, [r0, #0x764]
003582d2: 43f2a430   movw r0, #0x33a4
003582d6: c0f2a510   movt r0, #0x1a5
003582da: 90f83200   ldrb.w r0, [r0, #0x32]
003582de: c007       lsls r0, r0, #0x1f
003582e0: 06d0       beq #0x3582f0
003582e2: 80b5       push {r7, lr}
003582e4: 6f46       mov r7, sp
003582e6: 03a0       adr r0, #0xc
003582e8: ecf347f1   bl #0xb4457a
003582ec: bde88040   pop.w {r7, lr}
003582f0: 0120       movs r0, #1
003582f2: 7047       bx lr

SLOT 90 OP 40ab WIRE 4c0 HANDLER 358310
00358310: 017a       ldrb r1, [r0, #8]
00358312: 4af2207c   movw ip, #0xa720
00358316: c0f2651c   movt ip, #0x165
0035831a: ccf86817   str.w r1, [ip, #0x768]
0035831e: c268       ldr r2, [r0, #0xc]
00358320: ccf86c27   str.w r2, [ip, #0x76c]
00358324: 0369       ldr r3, [r0, #0x10]
00358326: 43f2a430   movw r0, #0x33a4
0035832a: c0f2a510   movt r0, #0x1a5
0035832e: 90f83200   ldrb.w r0, [r0, #0x32]
00358332: ccf87037   str.w r3, [ip, #0x770]
00358336: c007       lsls r0, r0, #0x1f
00358338: 06d0       beq #0x358348
0035833a: 80b5       push {r7, lr}
0035833c: 6f46       mov r7, sp
0035833e: 03a0       adr r0, #0xc
00358340: ecf31bf1   bl #0xb4457a
00358344: bde88040   pop.w {r7, lr}
00358348: 0120       movs r0, #1
0035834a: 7047       bx lr

SLOT 91 OP 40ac WIRE 4d4 HANDLER 358818
00358818: 80b5       push {r7, lr}
0035881a: 6f46       mov r7, sp
0035881c: 017a       ldrb r1, [r0, #8]
0035881e: 4af22070   movw r0, #0xa720
00358822: c0f26510   movt r0, #0x165
00358826: c0f8401b   str.w r1, [r0, #0xb40]
0035882a: 43f2a430   movw r0, #0x33a4
0035882e: c0f2a510   movt r0, #0x1a5
00358832: 90f83200   ldrb.w r0, [r0, #0x32]
00358836: c007       lsls r0, r0, #0x1f
00358838: 02d0       beq #0x358840
0035883a: 03a0       adr r0, #0xc
0035883c: ebf39df6   bl #0xb4457a
00358840: fbf7d4fb   bl #0x353fec
00358844: 0120       movs r0, #1
00358846: 80bd       pop {r7, pc}

SLOT 92 OP 40ad WIRE 4e0 HANDLER 358864
00358864: 017a       ldrb r1, [r0, #8]
00358866: 4af22070   movw r0, #0xa720
0035886a: c0f26510   movt r0, #0x165
0035886e: c0f8b015   str.w r1, [r0, #0x5b0]
00358872: 43f2a430   movw r0, #0x33a4
00358876: c0f2a510   movt r0, #0x1a5
0035887a: 90f83200   ldrb.w r0, [r0, #0x32]
0035887e: c007       lsls r0, r0, #0x1f
00358880: 06d0       beq #0x358890
00358882: 80b5       push {r7, lr}
00358884: 6f46       mov r7, sp
00358886: 03a0       adr r0, #0xc
00358888: ebf377f6   bl #0xb4457a
0035888c: bde88040   pop.w {r7, lr}
00358890: 0120       movs r0, #1
00358892: 7047       bx lr

SLOT 93 OP 40ae WIRE 4ec HANDLER 358c00
00358c00: 0189       ldrh r1, [r0, #8]
00358c02: 4af2207c   movw ip, #0xa720
00358c06: c0f2651c   movt ip, #0x165
00358c0a: acf87013   strh.w r1, [ip, #0x370]
00358c0e: 827a       ldrb r2, [r0, #0xa]
00358c10: ccf87423   str.w r2, [ip, #0x374]
00358c14: c37a       ldrb r3, [r0, #0xb]
00358c16: 43f2a430   movw r0, #0x33a4
00358c1a: c0f2a510   movt r0, #0x1a5
00358c1e: 90f83200   ldrb.w r0, [r0, #0x32]
00358c22: ccf87833   str.w r3, [ip, #0x378]
00358c26: c007       lsls r0, r0, #0x1f
00358c28: 06d0       beq #0x358c38
00358c2a: 80b5       push {r7, lr}
00358c2c: 6f46       mov r7, sp
00358c2e: 03a0       adr r0, #0xc
00358c30: ebf3a3f4   bl #0xb4457a
00358c34: bde88040   pop.w {r7, lr}
00358c38: 0120       movs r0, #1
00358c3a: 7047       bx lr

SLOT 94 OP 40af WIRE 4f8 HANDLER 3588b8
003588b8: 017a       ldrb r1, [r0, #8]
003588ba: 4af22070   movw r0, #0xa720
003588be: c0f26510   movt r0, #0x165
003588c2: c0f86411   str.w r1, [r0, #0x164]
003588c6: 43f2a430   movw r0, #0x33a4
003588ca: c0f2a510   movt r0, #0x1a5
003588ce: 90f83200   ldrb.w r0, [r0, #0x32]
003588d2: c007       lsls r0, r0, #0x1f
003588d4: 06d0       beq #0x3588e4
003588d6: 80b5       push {r7, lr}
003588d8: 6f46       mov r7, sp
003588da: 03a0       adr r0, #0xc
003588dc: ebf34df6   bl #0xb4457a
003588e0: bde88040   pop.w {r7, lr}
003588e4: 0120       movs r0, #1
003588e6: 7047       bx lr

SLOT 95 OP 40b0 WIRE 504 HANDLER 358a78
00358a78: 017a       ldrb r1, [r0, #8]
00358a7a: 4af22070   movw r0, #0xa720
00358a7e: c0f26510   movt r0, #0x165
00358a82: c0f87c13   str.w r1, [r0, #0x37c]
00358a86: 43f2a430   movw r0, #0x33a4
00358a8a: c0f2a510   movt r0, #0x1a5
00358a8e: 90f83200   ldrb.w r0, [r0, #0x32]
00358a92: c007       lsls r0, r0, #0x1f
00358a94: 06d0       beq #0x358aa4
00358a96: 80b5       push {r7, lr}
00358a98: 6f46       mov r7, sp
00358a9a: 03a0       adr r0, #0xc
00358a9c: ebf36df5   bl #0xb4457a
00358aa0: bde88040   pop.w {r7, lr}
00358aa4: 0120       movs r0, #1
00358aa6: 7047       bx lr

SLOT 96 OP 40b1 WIRE 510 HANDLER 358ac4
00358ac4: 017a       ldrb r1, [r0, #8]
00358ac6: 4af22070   movw r0, #0xa720
00358aca: c0f26510   movt r0, #0x165
00358ace: c0f88013   str.w r1, [r0, #0x380]
00358ad2: 43f2a430   movw r0, #0x33a4
00358ad6: c0f2a510   movt r0, #0x1a5
00358ada: 90f83200   ldrb.w r0, [r0, #0x32]
00358ade: c007       lsls r0, r0, #0x1f
00358ae0: 06d0       beq #0x358af0
00358ae2: 80b5       push {r7, lr}
00358ae4: 6f46       mov r7, sp
00358ae6: 03a0       adr r0, #0xc
00358ae8: ebf347f5   bl #0xb4457a
00358aec: bde88040   pop.w {r7, lr}
00358af0: 0120       movs r0, #1
00358af2: 7047       bx lr

SLOT 97 OP 40b2 WIRE 51c HANDLER 8db368
008db368: 017a       ldrb r1, [r0, #8]
008db36a: 4af22070   movw r0, #0xa720
008db36e: c0f26510   movt r0, #0x165
008db372: c0f82417   str.w r1, [r0, #0x724]
008db376: 43f2a430   movw r0, #0x33a4
008db37a: c0f2a510   movt r0, #0x1a5
008db37e: 90f83200   ldrb.w r0, [r0, #0x32]
008db382: c007       lsls r0, r0, #0x1f
008db384: 09d0       beq #0x8db39a
008db386: 80b5       push {r7, lr}
008db388: 6f46       mov r7, sp
008db38a: 4bf28050   movw r0, #0xb580
008db38e: c0f2f700   movt r0, #0xf7
008db392: 69f2f2f8   bl #0xb4457a
008db396: bde88040   pop.w {r7, lr}
008db39a: 0120       movs r0, #1
008db39c: 7047       bx lr

SLOT 98 OP 40b3 WIRE 528 HANDLER 8db39e
008db39e: 017a       ldrb r1, [r0, #8]
008db3a0: 4af22070   movw r0, #0xa720
008db3a4: c0f26510   movt r0, #0x165
008db3a8: c0f85417   str.w r1, [r0, #0x754]
008db3ac: 43f2a430   movw r0, #0x33a4
008db3b0: c0f2a510   movt r0, #0x1a5
008db3b4: 90f83200   ldrb.w r0, [r0, #0x32]
008db3b8: c007       lsls r0, r0, #0x1f
008db3ba: 09d0       beq #0x8db3d0
008db3bc: 80b5       push {r7, lr}
008db3be: 6f46       mov r7, sp
008db3c0: 4bf28050   movw r0, #0xb580
008db3c4: c0f2f700   movt r0, #0xf7
008db3c8: 69f2d7f8   bl #0xb4457a
008db3cc: bde88040   pop.w {r7, lr}
008db3d0: 0120       movs r0, #1
008db3d2: 7047       bx lr

SLOT 99 OP 40b4 WIRE 534 HANDLER 358b14
00358b14: 017a       ldrb r1, [r0, #8]
00358b16: 4af22070   movw r0, #0xa720
00358b1a: c0f26510   movt r0, #0x165
00358b1e: c0f87c17   str.w r1, [r0, #0x77c]
00358b22: 43f2a430   movw r0, #0x33a4
00358b26: c0f2a510   movt r0, #0x1a5
00358b2a: 90f83200   ldrb.w r0, [r0, #0x32]
00358b2e: c007       lsls r0, r0, #0x1f
00358b30: 06d0       beq #0x358b40
00358b32: 80b5       push {r7, lr}
00358b34: 6f46       mov r7, sp
00358b36: 03a0       adr r0, #0xc
00358b38: ebf31ff5   bl #0xb4457a
00358b3c: bde88040   pop.w {r7, lr}
00358b40: 0120       movs r0, #1
00358b42: 7047       bx lr

SLOT 100 OP 40b5 WIRE 540 HANDLER 358b54
00358b54: 017a       ldrb r1, [r0, #8]
00358b56: 4af22072   movw r2, #0xa720
00358b5a: c0f26512   movt r2, #0x165
00358b5e: 0029       cmp r1, #0
00358b60: 0846       mov r0, r1
00358b62: 18bf       it ne
00358b64: 0120       movs r0, #1
00358b66: 82f8c006   strb.w r0, [r2, #0x6c0]
00358b6a: 43f2a430   movw r0, #0x33a4
00358b6e: c0f2a510   movt r0, #0x1a5
00358b72: 90f83200   ldrb.w r0, [r0, #0x32]
00358b76: c007       lsls r0, r0, #0x1f
00358b78: 09d0       beq #0x358b8e
00358b7a: 80b5       push {r7, lr}
00358b7c: 6f46       mov r7, sp
00358b7e: 0029       cmp r1, #0
00358b80: 04a0       adr r0, #0x10
00358b82: 18bf       it ne
00358b84: 0121       movs r1, #1
00358b86: ebf3f8f4   bl #0xb4457a
00358b8a: bde88040   pop.w {r7, lr}
00358b8e: 0120       movs r0, #1
00358b90: 7047       bx lr

SLOT 101 OP 40b6 WIRE 54c HANDLER 358bac
00358bac: 017a       ldrb r1, [r0, #8]
00358bae: 4af22070   movw r0, #0xa720
00358bb2: c0f26510   movt r0, #0x165
00358bb6: c0f88017   str.w r1, [r0, #0x780]
00358bba: 43f2a430   movw r0, #0x33a4
00358bbe: c0f2a510   movt r0, #0x1a5
00358bc2: 90f83200   ldrb.w r0, [r0, #0x32]
00358bc6: c007       lsls r0, r0, #0x1f
00358bc8: 06d0       beq #0x358bd8
00358bca: 80b5       push {r7, lr}
00358bcc: 6f46       mov r7, sp
00358bce: 03a0       adr r0, #0xc
00358bd0: ebf3d3f4   bl #0xb4457a
00358bd4: bde88040   pop.w {r7, lr}
00358bd8: 0120       movs r0, #1
00358bda: 7047       bx lr

SLOT 102 OP 40c2 WIRE 558 HANDLER 3593f0
003593f0: 017a       ldrb r1, [r0, #8]
003593f2: 4af22070   movw r0, #0xa720
003593f6: c0f26510   movt r0, #0x165
003593fa: c0f80c1d   str.w r1, [r0, #0xd0c]
003593fe: 43f2a430   movw r0, #0x33a4
00359402: c0f2a510   movt r0, #0x1a5
00359406: 90f83200   ldrb.w r0, [r0, #0x32]
0035940a: c007       lsls r0, r0, #0x1f
0035940c: 06d0       beq #0x35941c
0035940e: 80b5       push {r7, lr}
00359410: 6f46       mov r7, sp
00359412: 03a0       adr r0, #0xc
00359414: ebf3b1f0   bl #0xb4457a
00359418: bde88040   pop.w {r7, lr}
0035941c: 0120       movs r0, #1
0035941e: 7047       bx lr

SLOT 103 OP 40c3 WIRE 564 HANDLER 35943c
0035943c: 017a       ldrb r1, [r0, #8]
0035943e: 4af22070   movw r0, #0xa720
00359442: c0f26510   movt r0, #0x165
00359446: 80f8531b   strb.w r1, [r0, #0xb53]
0035944a: 43f2a430   movw r0, #0x33a4
0035944e: c0f2a510   movt r0, #0x1a5
00359452: 90f83200   ldrb.w r0, [r0, #0x32]
00359456: c007       lsls r0, r0, #0x1f
00359458: 06d0       beq #0x359468
0035945a: 80b5       push {r7, lr}
0035945c: 6f46       mov r7, sp
0035945e: 03a0       adr r0, #0xc
00359460: ebf38bf0   bl #0xb4457a
00359464: bde88040   pop.w {r7, lr}
00359468: 0120       movs r0, #1
0035946a: 7047       bx lr

SLOT 104 OP 40c4 WIRE 570 HANDLER 358f80
00358f80: 017a       ldrb r1, [r0, #8]
00358f82: 4af22070   movw r0, #0xa720
00358f86: c0f26510   movt r0, #0x165
00358f8a: c0f8a013   str.w r1, [r0, #0x3a0]
00358f8e: 43f2a430   movw r0, #0x33a4
00358f92: c0f2a510   movt r0, #0x1a5
00358f96: 90f83200   ldrb.w r0, [r0, #0x32]
00358f9a: c007       lsls r0, r0, #0x1f
00358f9c: 06d0       beq #0x358fac
00358f9e: 80b5       push {r7, lr}
00358fa0: 6f46       mov r7, sp
00358fa2: 03a0       adr r0, #0xc
00358fa4: ebf3e9f2   bl #0xb4457a
00358fa8: bde88040   pop.w {r7, lr}
00358fac: 0120       movs r0, #1
00358fae: 7047       bx lr

SLOT 105 OP 40c5 WIRE 57c HANDLER 358fd4
00358fd4: 017a       ldrb r1, [r0, #8]
00358fd6: 4af22070   movw r0, #0xa720
00358fda: c0f26510   movt r0, #0x165
00358fde: c0f8a413   str.w r1, [r0, #0x3a4]
00358fe2: 43f2a430   movw r0, #0x33a4
00358fe6: c0f2a510   movt r0, #0x1a5
00358fea: 90f83200   ldrb.w r0, [r0, #0x32]
00358fee: c007       lsls r0, r0, #0x1f
00358ff0: 06d0       beq #0x359000
00358ff2: 80b5       push {r7, lr}
00358ff4: 6f46       mov r7, sp
00358ff6: 03a0       adr r0, #0xc
00358ff8: ebf3bff2   bl #0xb4457a
00358ffc: bde88040   pop.w {r7, lr}
00359000: 0120       movs r0, #1
00359002: 7047       bx lr

SLOT 106 OP 40c6 WIRE 588 HANDLER 359488
00359488: 017a       ldrb r1, [r0, #8]
0035948a: 4af22070   movw r0, #0xa720
0035948e: c0f26510   movt r0, #0x165
00359492: c0f8541b   str.w r1, [r0, #0xb54]
00359496: 43f2a430   movw r0, #0x33a4
0035949a: c0f2a510   movt r0, #0x1a5
0035949e: 90f83200   ldrb.w r0, [r0, #0x32]
003594a2: c007       lsls r0, r0, #0x1f
003594a4: 06d0       beq #0x3594b4
003594a6: 80b5       push {r7, lr}
003594a8: 6f46       mov r7, sp
003594aa: 03a0       adr r0, #0xc
003594ac: ebf365f0   bl #0xb4457a
003594b0: bde88040   pop.w {r7, lr}
003594b4: 0120       movs r0, #1
003594b6: 7047       bx lr

SLOT 107 OP 40c7 WIRE 594 HANDLER 3594d8
003594d8: 017a       ldrb r1, [r0, #8]
003594da: 4af22070   movw r0, #0xa720
003594de: c0f26510   movt r0, #0x165
003594e2: c0f88817   str.w r1, [r0, #0x788]
003594e6: 43f2a430   movw r0, #0x33a4
003594ea: c0f2a510   movt r0, #0x1a5
003594ee: 90f83200   ldrb.w r0, [r0, #0x32]
003594f2: c007       lsls r0, r0, #0x1f
003594f4: 06d0       beq #0x359504
003594f6: 80b5       push {r7, lr}
003594f8: 6f46       mov r7, sp
003594fa: 03a0       adr r0, #0xc
003594fc: ebf33df0   bl #0xb4457a
00359500: bde88040   pop.w {r7, lr}
00359504: 0120       movs r0, #1
00359506: 7047       bx lr

SLOT 108 OP 40ca WIRE 5a0 HANDLER 359528
00359528: 017a       ldrb r1, [r0, #8]
0035952a: 4af2207c   movw ip, #0xa720
0035952e: c0f2651c   movt ip, #0x165
00359532: ccf8641b   str.w r1, [ip, #0xb64]
00359536: ccf8581b   str.w r1, [ip, #0xb58]
0035953a: 427a       ldrb r2, [r0, #9]
0035953c: ccf8682b   str.w r2, [ip, #0xb68]
00359540: ccf85c2b   str.w r2, [ip, #0xb5c]
00359544: 4389       ldrh r3, [r0, #0xa]
00359546: 43f2a430   movw r0, #0x33a4
0035954a: c0f2a510   movt r0, #0x1a5
0035954e: 90f83200   ldrb.w r0, [r0, #0x32]
00359552: acf86c3b   strh.w r3, [ip, #0xb6c]
00359556: acf8603b   strh.w r3, [ip, #0xb60]
0035955a: c007       lsls r0, r0, #0x1f
0035955c: 06d0       beq #0x35956c
0035955e: 80b5       push {r7, lr}
00359560: 6f46       mov r7, sp
00359562: 03a0       adr r0, #0xc
00359564: ebf309f0   bl #0xb4457a
00359568: bde88040   pop.w {r7, lr}
0035956c: 0120       movs r0, #1
0035956e: 7047       bx lr

SLOT 109 OP 40cb WIRE 5ac HANDLER 3595a0
003595a0: 017a       ldrb r1, [r0, #8]
003595a2: 4af2207c   movw ip, #0xa720
003595a6: c0f2651c   movt ip, #0x165
003595aa: ccf8701b   str.w r1, [ip, #0xb70]
003595ae: ccf8581b   str.w r1, [ip, #0xb58]
003595b2: 427a       ldrb r2, [r0, #9]
003595b4: ccf8742b   str.w r2, [ip, #0xb74]
003595b8: ccf85c2b   str.w r2, [ip, #0xb5c]
003595bc: 4389       ldrh r3, [r0, #0xa]
003595be: 43f2a430   movw r0, #0x33a4
003595c2: c0f2a510   movt r0, #0x1a5
003595c6: 90f83200   ldrb.w r0, [r0, #0x32]
003595ca: acf8783b   strh.w r3, [ip, #0xb78]
003595ce: acf8603b   strh.w r3, [ip, #0xb60]
003595d2: c007       lsls r0, r0, #0x1f
003595d4: 06d0       beq #0x3595e4
003595d6: 80b5       push {r7, lr}
003595d8: 6f46       mov r7, sp
003595da: 03a0       adr r0, #0xc
003595dc: eaf3cdf7   bl #0xb4457a
003595e0: bde88040   pop.w {r7, lr}
003595e4: 0120       movs r0, #1
003595e6: 7047       bx lr

SLOT 110 OP 40cc WIRE 5b8 HANDLER 359618
00359618: 017a       ldrb r1, [r0, #8]
0035961a: 4af22070   movw r0, #0xa720
0035961e: c0f26510   movt r0, #0x165
00359622: c0f8441d   str.w r1, [r0, #0xd44]
00359626: 43f2a430   movw r0, #0x33a4
0035962a: c0f2a510   movt r0, #0x1a5
0035962e: 90f83200   ldrb.w r0, [r0, #0x32]
00359632: c007       lsls r0, r0, #0x1f
00359634: 06d0       beq #0x359644
00359636: 80b5       push {r7, lr}
00359638: 6f46       mov r7, sp
0035963a: 03a0       adr r0, #0xc
0035963c: eaf39df7   bl #0xb4457a
00359640: bde88040   pop.w {r7, lr}
00359644: 0120       movs r0, #1
00359646: 7047       bx lr

SLOT 111 OP 40cd WIRE 5c4 HANDLER 359664
00359664: 017a       ldrb r1, [r0, #8]
00359666: 4af2207c   movw ip, #0xa720
0035966a: c0f2651c   movt ip, #0x165
0035966e: ccf8b413   str.w r1, [ip, #0x3b4]
00359672: c268       ldr r2, [r0, #0xc]
00359674: ccf8b823   str.w r2, [ip, #0x3b8]
00359678: 038a       ldrh r3, [r0, #0x10]
0035967a: 43f2a430   movw r0, #0x33a4
0035967e: c0f2a510   movt r0, #0x1a5
00359682: 90f83200   ldrb.w r0, [r0, #0x32]
00359686: acf8bc33   strh.w r3, [ip, #0x3bc]
0035968a: c007       lsls r0, r0, #0x1f
0035968c: 06d0       beq #0x35969c
0035968e: 80b5       push {r7, lr}
00359690: 6f46       mov r7, sp
00359692: 03a0       adr r0, #0xc
00359694: eaf371f7   bl #0xb4457a
00359698: bde88040   pop.w {r7, lr}
0035969c: 0120       movs r0, #1
0035969e: 7047       bx lr

SLOT 112 OP 40ce WIRE 5d8 HANDLER 3596cc
003596cc: 017a       ldrb r1, [r0, #8]
003596ce: 4af22070   movw r0, #0xa720
003596d2: c0f26510   movt r0, #0x165
003596d6: c0f88413   str.w r1, [r0, #0x384]
003596da: 43f2a430   movw r0, #0x33a4
003596de: c0f2a510   movt r0, #0x1a5
003596e2: 90f83200   ldrb.w r0, [r0, #0x32]
003596e6: c007       lsls r0, r0, #0x1f
003596e8: 06d0       beq #0x3596f8
003596ea: 80b5       push {r7, lr}
003596ec: 6f46       mov r7, sp
003596ee: 03a0       adr r0, #0xc
003596f0: eaf343f7   bl #0xb4457a
003596f4: bde88040   pop.w {r7, lr}
003596f8: 0120       movs r0, #1
003596fa: 7047       bx lr

SLOT 113 OP 40d2 WIRE 5e4 HANDLER 3597b4
003597b4: 017a       ldrb r1, [r0, #8]
003597b6: 4af22070   movw r0, #0xa720
003597ba: c0f26510   movt r0, #0x165
003597be: c0f8e81c   str.w r1, [r0, #0xce8]
003597c2: 43f2a430   movw r0, #0x33a4
003597c6: c0f2a510   movt r0, #0x1a5
003597ca: 90f83200   ldrb.w r0, [r0, #0x32]
003597ce: c007       lsls r0, r0, #0x1f
003597d0: 06d0       beq #0x3597e0
003597d2: 80b5       push {r7, lr}
003597d4: 6f46       mov r7, sp
003597d6: 03a0       adr r0, #0xc
003597d8: eaf3cff6   bl #0xb4457a
003597dc: bde88040   pop.w {r7, lr}
003597e0: 0120       movs r0, #1
003597e2: 7047       bx lr

SLOT 114 OP 40d3 WIRE 5f0 HANDLER 3597fc
003597fc: 017a       ldrb r1, [r0, #8]
003597fe: 4af22070   movw r0, #0xa720
00359802: c0f26510   movt r0, #0x165
00359806: c0f8241b   str.w r1, [r0, #0xb24]
0035980a: 43f2a430   movw r0, #0x33a4
0035980e: c0f2a510   movt r0, #0x1a5
00359812: 90f83200   ldrb.w r0, [r0, #0x32]
00359816: c007       lsls r0, r0, #0x1f
00359818: 06d0       beq #0x359828
0035981a: 80b5       push {r7, lr}
0035981c: 6f46       mov r7, sp
0035981e: 03a0       adr r0, #0xc
00359820: eaf3abf6   bl #0xb4457a
00359824: bde88040   pop.w {r7, lr}
00359828: 0120       movs r0, #1
0035982a: 7047       bx lr

SLOT 115 OP 40d4 WIRE 5fc HANDLER 358910
00358910: 017a       ldrb r1, [r0, #8]
00358912: 4af22070   movw r0, #0xa720
00358916: c0f26510   movt r0, #0x165
0035891a: c0f86811   str.w r1, [r0, #0x168]
0035891e: 43f2a430   movw r0, #0x33a4
00358922: c0f2a510   movt r0, #0x1a5
00358926: 90f83200   ldrb.w r0, [r0, #0x32]
0035892a: c007       lsls r0, r0, #0x1f
0035892c: 06d0       beq #0x35893c
0035892e: 80b5       push {r7, lr}
00358930: 6f46       mov r7, sp
00358932: 03a0       adr r0, #0xc
00358934: ebf321f6   bl #0xb4457a
00358938: bde88040   pop.w {r7, lr}
0035893c: 0120       movs r0, #1
0035893e: 7047       bx lr

SLOT 116 OP 40d5 WIRE 608 HANDLER 359850
00359850: 017a       ldrb r1, [r0, #8]
00359852: 4af22070   movw r0, #0xa720
00359856: c0f26510   movt r0, #0x165
0035985a: c0f87c1b   str.w r1, [r0, #0xb7c]
0035985e: 43f2a430   movw r0, #0x33a4
00359862: c0f2a510   movt r0, #0x1a5
00359866: 90f83200   ldrb.w r0, [r0, #0x32]
0035986a: c007       lsls r0, r0, #0x1f
0035986c: 06d0       beq #0x35987c
0035986e: 80b5       push {r7, lr}
00359870: 6f46       mov r7, sp
00359872: 03a0       adr r0, #0xc
00359874: eaf381f6   bl #0xb4457a
00359878: bde88040   pop.w {r7, lr}
0035987c: 0120       movs r0, #1
0035987e: 7047       bx lr

SLOT 117 OP 40d6 WIRE 614 HANDLER 3598a4
003598a4: 017a       ldrb r1, [r0, #8]
003598a6: 4af22070   movw r0, #0xa720
003598aa: c0f26510   movt r0, #0x165
003598ae: 80f8801b   strb.w r1, [r0, #0xb80]
003598b2: 43f2a430   movw r0, #0x33a4
003598b6: c0f2a510   movt r0, #0x1a5
003598ba: 90f83200   ldrb.w r0, [r0, #0x32]
003598be: c007       lsls r0, r0, #0x1f
003598c0: 06d0       beq #0x3598d0
003598c2: 80b5       push {r7, lr}
003598c4: 6f46       mov r7, sp
003598c6: 03a0       adr r0, #0xc
003598c8: eaf357f6   bl #0xb4457a
003598cc: bde88040   pop.w {r7, lr}
003598d0: 0120       movs r0, #1
003598d2: 7047       bx lr

SLOT 118 OP 40d7 WIRE 620 HANDLER 8db3d4
008db3d4: 007a       ldrb r0, [r0, #8]
008db3d6: 4af22071   movw r1, #0xa720
008db3da: c0f26511   movt r1, #0x165
008db3de: c1f88c07   str.w r0, [r1, #0x78c]
008db3e2: 0120       movs r0, #1
008db3e4: 7047       bx lr

SLOT 119 OP 40d8 WIRE 62c HANDLER 3598f4
003598f4: 017a       ldrb r1, [r0, #8]
003598f6: 4af22070   movw r0, #0xa720
003598fa: c0f26510   movt r0, #0x165
003598fe: c0f8481d   str.w r1, [r0, #0xd48]
00359902: 43f2a430   movw r0, #0x33a4
00359906: c0f2a510   movt r0, #0x1a5
0035990a: 90f83200   ldrb.w r0, [r0, #0x32]
0035990e: c007       lsls r0, r0, #0x1f
00359910: 06d0       beq #0x359920
00359912: 80b5       push {r7, lr}
00359914: 6f46       mov r7, sp
00359916: 03a0       adr r0, #0xc
00359918: eaf32ff6   bl #0xb4457a
0035991c: bde88040   pop.w {r7, lr}
00359920: 0120       movs r0, #1
00359922: 7047       bx lr

SLOT 120 OP 40d9 WIRE 638 HANDLER 359944
00359944: 017a       ldrb r1, [r0, #8]
00359946: 4af22072   movw r2, #0xa720
0035994a: c0f26512   movt r2, #0x165
0035994e: c2f84c1d   str.w r1, [r2, #0xd4c]
00359952: 92f8500d   ldrb.w r0, [r2, #0xd50]
00359956: 0130       adds r0, #1
00359958: 82f8500d   strb.w r0, [r2, #0xd50]
0035995c: 43f2a432   movw r2, #0x33a4
00359960: c0f2a512   movt r2, #0x1a5
00359964: 92f83220   ldrb.w r2, [r2, #0x32]
00359968: d207       lsls r2, r2, #0x1f
0035996a: 07d0       beq #0x35997c
0035996c: 80b5       push {r7, lr}
0035996e: 6f46       mov r7, sp
00359970: c2b2       uxtb r2, r0
00359972: 03a0       adr r0, #0xc
00359974: eaf301f6   bl #0xb4457a
00359978: bde88040   pop.w {r7, lr}
0035997c: 0120       movs r0, #1
0035997e: 7047       bx lr

SLOT 121 OP 40db WIRE 644 HANDLER 359a00
00359a00: b0b5       push {r4, r5, r7, lr}
00359a02: 02af       add r7, sp, #8
00359a04: 017a       ldrb r1, [r0, #8]
00359a06: 4af22074   movw r4, #0xa720
00359a0a: 43f2a435   movw r5, #0x33a4
00359a0e: c0f26514   movt r4, #0x165
00359a12: c0f2a515   movt r5, #0x1a5
00359a16: 84f8be13   strb.w r1, [r4, #0x3be]
00359a1a: 427a       ldrb r2, [r0, #9]
00359a1c: 84f8bf23   strb.w r2, [r4, #0x3bf]
00359a20: 827a       ldrb r2, [r0, #0xa]
00359a22: 84f8c023   strb.w r2, [r4, #0x3c0]
00359a26: c27a       ldrb r2, [r0, #0xb]
00359a28: 84f8c123   strb.w r2, [r4, #0x3c1]
00359a2c: 027b       ldrb r2, [r0, #0xc]
00359a2e: 84f8c223   strb.w r2, [r4, #0x3c2]
00359a32: 407b       ldrb r0, [r0, #0xd]
00359a34: 84f8c303   strb.w r0, [r4, #0x3c3]
00359a38: 95f83200   ldrb.w r0, [r5, #0x32]
00359a3c: 10f0010f   tst.w r0, #1
00359a40: 04d0       beq #0x359a4c
00359a42: 1da0       adr r0, #0x74
00359a44: eaf399f5   bl #0xb4457a
00359a48: 95f83200   ldrb.w r0, [r5, #0x32]
00359a4c: c107       lsls r1, r0, #0x1f
00359a4e: 06d0       beq #0x359a5e
00359a50: 94f9bf13   ldrsb.w r1, [r4, #0x3bf]
00359a54: 22a0       adr r0, #0x88
00359a56: eaf390f5   bl #0xb4457a
00359a5a: 95f83200   ldrb.w r0, [r5, #0x32]
00359a5e: c107       lsls r1, r0, #0x1f
00359a60: 06d0       beq #0x359a70
00359a62: 94f9c013   ldrsb.w r1, [r4, #0x3c0]
00359a66: 2aa0       adr r0, #0xa8
00359a68: eaf387f5   bl #0xb4457a
00359a6c: 95f83200   ldrb.w r0, [r5, #0x32]
00359a70: c107       lsls r1, r0, #0x1f
00359a72: 09d0       beq #0x359a88
00359a74: 94f9c113   ldrsb.w r1, [r4, #0x3c1]
00359a78: 4bf29a50   movw r0, #0xb59a
00359a7c: c0f2f700   movt r0, #0xf7
00359a80: eaf37bf5   bl #0xb4457a
00359a84: 95f83200   ldrb.w r0, [r5, #0x32]
00359a88: c107       lsls r1, r0, #0x1f
00359a8a: 09d0       beq #0x359aa0
00359a8c: 94f9c213   ldrsb.w r1, [r4, #0x3c2]
00359a90: 4bf2c750   movw r0, #0xb5c7
00359a94: c0f2f700   movt r0, #0xf7
00359a98: eaf36ff5   bl #0xb4457a
00359a9c: 95f83200   ldrb.w r0, [r5, #0x32]
00359aa0: c007       lsls r0, r0, #0x1f
00359aa2: 07d0       beq #0x359ab4
00359aa4: 94f9c313   ldrsb.w r1, [r4, #0x3c3]
00359aa8: 4bf2f950   movw r0, #0xb5f9
00359aac: c0f2f700   movt r0, #0xf7
00359ab0: eaf363f5   bl #0xb4457a
00359ab4: 0120       movs r0, #1
00359ab6: b0bd       pop {r4, r5, r7, pc}

SLOT 122 OP 40dc WIRE 654 HANDLER 359b40
00359b40: 017a       ldrb r1, [r0, #8]
00359b42: 4af22070   movw r0, #0xa720
00359b46: c0f26510   movt r0, #0x165
00359b4a: c0f8c413   str.w r1, [r0, #0x3c4]
00359b4e: 43f2a430   movw r0, #0x33a4
00359b52: c0f2a510   movt r0, #0x1a5
00359b56: 90f83200   ldrb.w r0, [r0, #0x32]
00359b5a: c007       lsls r0, r0, #0x1f
00359b5c: 06d0       beq #0x359b6c
00359b5e: 80b5       push {r7, lr}
00359b60: 6f46       mov r7, sp
00359b62: 03a0       adr r0, #0xc
00359b64: eaf309f5   bl #0xb4457a
00359b68: bde88040   pop.w {r7, lr}
00359b6c: 0120       movs r0, #1
00359b6e: 7047       bx lr

SLOT 123 OP 40e3 WIRE 660 HANDLER 359e40
00359e40: 017a       ldrb r1, [r0, #8]
00359e42: 4af22070   movw r0, #0xa720
00359e46: c0f26510   movt r0, #0x165
00359e4a: c0f89017   str.w r1, [r0, #0x790]
00359e4e: 43f2a430   movw r0, #0x33a4
00359e52: c0f2a510   movt r0, #0x1a5
00359e56: 90f83200   ldrb.w r0, [r0, #0x32]
00359e5a: c007       lsls r0, r0, #0x1f
00359e5c: 06d0       beq #0x359e6c
00359e5e: 80b5       push {r7, lr}
00359e60: 6f46       mov r7, sp
00359e62: 03a0       adr r0, #0xc
00359e64: eaf389f3   bl #0xb4457a
00359e68: bde88040   pop.w {r7, lr}
00359e6c: 0120       movs r0, #1
00359e6e: 7047       bx lr

SLOT 124 OP 40e4 WIRE 66c HANDLER 359d44
00359d44: 017a       ldrb r1, [r0, #8]
00359d46: 4af22070   movw r0, #0xa720
00359d4a: c0f26510   movt r0, #0x165
00359d4e: c0f8b411   str.w r1, [r0, #0x1b4]
00359d52: 43f2a430   movw r0, #0x33a4
00359d56: c0f2a510   movt r0, #0x1a5
00359d5a: 90f83200   ldrb.w r0, [r0, #0x32]
00359d5e: c007       lsls r0, r0, #0x1f
00359d60: 06d0       beq #0x359d70
00359d62: 80b5       push {r7, lr}
00359d64: 6f46       mov r7, sp
00359d66: 03a0       adr r0, #0xc
00359d68: eaf307f4   bl #0xb4457a
00359d6c: bde88040   pop.w {r7, lr}
00359d70: 0120       movs r0, #1
00359d72: 7047       bx lr

SLOT 125 OP 40e6 WIRE 678 HANDLER 359da0
00359da0: 017a       ldrb r1, [r0, #8]
00359da2: 4af22070   movw r0, #0xa720
00359da6: c0f26510   movt r0, #0x165
00359daa: c0f8d413   str.w r1, [r0, #0x3d4]
00359dae: 43f2a430   movw r0, #0x33a4
00359db2: c0f2a510   movt r0, #0x1a5
00359db6: 90f83200   ldrb.w r0, [r0, #0x32]
00359dba: c007       lsls r0, r0, #0x1f
00359dbc: 06d0       beq #0x359dcc
00359dbe: 80b5       push {r7, lr}
00359dc0: 6f46       mov r7, sp
00359dc2: 03a0       adr r0, #0xc
00359dc4: eaf3d9f3   bl #0xb4457a
00359dc8: bde88040   pop.w {r7, lr}
00359dcc: 0120       movs r0, #1
00359dce: 7047       bx lr

SLOT 126 OP 40e7 WIRE 684 HANDLER 359df0
00359df0: 017a       ldrb r1, [r0, #8]
00359df2: 4af22070   movw r0, #0xa720
00359df6: c0f26510   movt r0, #0x165
00359dfa: c0f8b811   str.w r1, [r0, #0x1b8]
00359dfe: 43f2a430   movw r0, #0x33a4
00359e02: c0f2a510   movt r0, #0x1a5
00359e06: 90f83200   ldrb.w r0, [r0, #0x32]
00359e0a: c007       lsls r0, r0, #0x1f
00359e0c: 06d0       beq #0x359e1c
00359e0e: 80b5       push {r7, lr}
00359e10: 6f46       mov r7, sp
00359e12: 03a0       adr r0, #0xc
00359e14: eaf3b1f3   bl #0xb4457a
00359e18: bde88040   pop.w {r7, lr}
00359e1c: 0120       movs r0, #1
00359e1e: 7047       bx lr

SLOT 127 OP 40e8 WIRE 690 HANDLER 35907c
0035907c: 017a       ldrb r1, [r0, #8]
0035907e: 0529       cmp r1, #5
00359080: 0ed0       beq #0x3590a0
00359082: f1b9       cbnz r1, #0x3590c2
00359084: 4af22071   movw r1, #0xa720
00359088: 0022       movs r2, #0
0035908a: c0f26511   movt r1, #0x165
0035908e: 81f8a82b   strb.w r2, [r1, #0xba8]
00359092: c1f8b42b   str.w r2, [r1, #0xbb4]
00359096: 81f8b32b   strb.w r2, [r1, #0xbb3]
0035909a: 81f8f426   strb.w r2, [r1, #0x6f4]
0035909e: 0de0       b #0x3590bc
003590a0: 4af22071   movw r1, #0xa720
003590a4: 0022       movs r2, #0
003590a6: 0123       movs r3, #1
003590a8: c0f26511   movt r1, #0x165
003590ac: 81f8a82b   strb.w r2, [r1, #0xba8]
003590b0: c1f8b42b   str.w r2, [r1, #0xbb4]
003590b4: 81f8b33b   strb.w r3, [r1, #0xbb3]
003590b8: 81f8f436   strb.w r3, [r1, #0x6f4]
003590bc: 0021       movs r1, #0
003590be: 0023       movs r3, #0
003590c0: 1de0       b #0x3590fe
003590c2: 4af2207c   movw ip, #0xa720
003590c6: 0122       movs r2, #1
003590c8: 0023       movs r3, #0
003590ca: c0f2651c   movt ip, #0x165
003590ce: 0129       cmp r1, #1
003590d0: 8cf8a82b   strb.w r2, [ip, #0xba8]
003590d4: 8cf8b33b   strb.w r3, [ip, #0xbb3]
003590d8: 8cf8f436   strb.w r3, [ip, #0x6f4]
003590dc: 08d0       beq #0x3590f0
003590de: 0629       cmp r1, #6
003590e0: 4ff00002   mov.w r2, #0
003590e4: 05d0       beq #0x3590f2
003590e6: 0229       cmp r1, #2
003590e8: 0a46       mov r2, r1
003590ea: 18bf       it ne
003590ec: 0122       movs r2, #1
003590ee: 00e0       b #0x3590f2
003590f0: 0022       movs r2, #0
003590f2: 0629       cmp r1, #6
003590f4: ccf8b42b   str.w r2, [ip, #0xbb4]
003590f8: 08bf       it eq
003590fa: 0123       movs r3, #1
003590fc: 0121       movs r1, #1
003590fe: 4af2207c   movw ip, #0xa720
00359102: c0f2651c   movt ip, #0x165
00359106: 8cf8e53b   strb.w r3, [ip, #0xbe5]
0035910a: 437a       ldrb r3, [r0, #9]
0035910c: 012b       cmp r3, #1
0035910e: 1846       mov r0, r3
00359110: 18bf       it ne
00359112: 0020       movs r0, #0
00359114: 8cf8c40b   strb.w r0, [ip, #0xbc4]
00359118: 43f2a430   movw r0, #0x33a4
0035911c: c0f2a510   movt r0, #0x1a5
00359120: 90f83200   ldrb.w r0, [r0, #0x32]
00359124: c007       lsls r0, r0, #0x1f
00359126: 09d0       beq #0x35913c
00359128: 80b5       push {r7, lr}
0035912a: 6f46       mov r7, sp
0035912c: 012b       cmp r3, #1
0035912e: 04a0       adr r0, #0x10
00359130: 18bf       it ne
00359132: 0023       movs r3, #0
00359134: ebf321f2   bl #0xb4457a
00359138: bde88040   pop.w {r7, lr}
0035913c: 0120       movs r0, #1
0035913e: 7047       bx lr

SLOT 128 OP 40e9 WIRE 69c HANDLER 359164
00359164: 017a       ldrb r1, [r0, #8]
00359166: 4af22072   movw r2, #0xa720
0035916a: c0f26512   movt r2, #0x165
0035916e: 0029       cmp r1, #0
00359170: 0846       mov r0, r1
00359172: 18bf       it ne
00359174: 0120       movs r0, #1
00359176: 82f8a90b   strb.w r0, [r2, #0xba9]
0035917a: 43f2a430   movw r0, #0x33a4
0035917e: c0f2a510   movt r0, #0x1a5
00359182: 90f83200   ldrb.w r0, [r0, #0x32]
00359186: c007       lsls r0, r0, #0x1f
00359188: 09d0       beq #0x35919e
0035918a: 80b5       push {r7, lr}
0035918c: 6f46       mov r7, sp
0035918e: 0029       cmp r1, #0
00359190: 04a0       adr r0, #0x10
00359192: 18bf       it ne
00359194: 0121       movs r1, #1
00359196: ebf3f0f1   bl #0xb4457a
0035919a: bde88040   pop.w {r7, lr}
0035919e: 0120       movs r0, #1
003591a0: 7047       bx lr

SLOT 129 OP 40ea WIRE 6a8 HANDLER 3591c0
003591c0: 017a       ldrb r1, [r0, #8]
003591c2: 4af22070   movw r0, #0xa720
003591c6: c0f26510   movt r0, #0x165
003591ca: 0029       cmp r1, #0
003591cc: 18bf       it ne
003591ce: 0121       movs r1, #1
003591d0: c0f8ac1b   str.w r1, [r0, #0xbac]
003591d4: c0f8f81b   str.w r1, [r0, #0xbf8]
003591d8: 43f2a430   movw r0, #0x33a4
003591dc: c0f2a510   movt r0, #0x1a5
003591e0: 90f83200   ldrb.w r0, [r0, #0x32]
003591e4: c007       lsls r0, r0, #0x1f
003591e6: 06d0       beq #0x3591f6
003591e8: 80b5       push {r7, lr}
003591ea: 6f46       mov r7, sp
003591ec: 03a0       adr r0, #0xc
003591ee: ebf3c4f1   bl #0xb4457a
003591f2: bde88040   pop.w {r7, lr}
003591f6: 0120       movs r0, #1
003591f8: 7047       bx lr

SLOT 130 OP 40eb WIRE 6b4 HANDLER 359218
00359218: 017a       ldrb r1, [r0, #8]
0035921a: 4af22072   movw r2, #0xa720
0035921e: c0f26512   movt r2, #0x165
00359222: 0029       cmp r1, #0
00359224: 0846       mov r0, r1
00359226: 18bf       it ne
00359228: 0120       movs r0, #1
0035922a: 82f8b00b   strb.w r0, [r2, #0xbb0]
0035922e: 43f2a430   movw r0, #0x33a4
00359232: c0f2a510   movt r0, #0x1a5
00359236: 90f83200   ldrb.w r0, [r0, #0x32]
0035923a: c007       lsls r0, r0, #0x1f
0035923c: 09d0       beq #0x359252
0035923e: 80b5       push {r7, lr}
00359240: 6f46       mov r7, sp
00359242: 0029       cmp r1, #0
00359244: 04a0       adr r0, #0x10
00359246: 18bf       it ne
00359248: 0121       movs r1, #1
0035924a: ebf396f1   bl #0xb4457a
0035924e: bde88040   pop.w {r7, lr}
00359252: 0120       movs r0, #1
00359254: 7047       bx lr

SLOT 131 OP 40ec WIRE 6c0 HANDLER 35927c
0035927c: 017a       ldrb r1, [r0, #8]
0035927e: 4af22072   movw r2, #0xa720
00359282: c0f26512   movt r2, #0x165
00359286: 0029       cmp r1, #0
00359288: 0846       mov r0, r1
0035928a: 18bf       it ne
0035928c: 0120       movs r0, #1
0035928e: 82f8b10b   strb.w r0, [r2, #0xbb1]
00359292: 43f2a430   movw r0, #0x33a4
00359296: c0f2a510   movt r0, #0x1a5
0035929a: 90f83200   ldrb.w r0, [r0, #0x32]
0035929e: c007       lsls r0, r0, #0x1f
003592a0: 09d0       beq #0x3592b6
003592a2: 80b5       push {r7, lr}
003592a4: 6f46       mov r7, sp
003592a6: 0029       cmp r1, #0
003592a8: 04a0       adr r0, #0x10
003592aa: 18bf       it ne
003592ac: 0121       movs r1, #1
003592ae: ebf364f1   bl #0xb4457a
003592b2: bde88040   pop.w {r7, lr}
003592b6: 0120       movs r0, #1
003592b8: 7047       bx lr

SLOT 132 OP 40f1 WIRE 6cc HANDLER 35a7e0
0035a7e0: 017a       ldrb r1, [r0, #8]
0035a7e2: 4af22070   movw r0, #0xa720
0035a7e6: c0f26510   movt r0, #0x165
0035a7ea: c0f8041a   str.w r1, [r0, #0xa04]
0035a7ee: 43f2a430   movw r0, #0x33a4
0035a7f2: c0f2a510   movt r0, #0x1a5
0035a7f6: 90f83200   ldrb.w r0, [r0, #0x32]
0035a7fa: c007       lsls r0, r0, #0x1f
0035a7fc: 06d0       beq #0x35a80c
0035a7fe: 80b5       push {r7, lr}
0035a800: 6f46       mov r7, sp
0035a802: 03a0       adr r0, #0xc
0035a804: e9f3b9f6   bl #0xb4457a
0035a808: bde88040   pop.w {r7, lr}
0035a80c: 0120       movs r0, #1
0035a80e: 7047       bx lr

SLOT 133 OP 40f3 WIRE 6d8 HANDLER 3565b0
003565b0: 90f90810   ldrsb.w r1, [r0, #8]
003565b4: 4af22070   movw r0, #0xa720
003565b8: c0f26510   movt r0, #0x165
003565bc: 80f86a19   strb.w r1, [r0, #0x96a]
003565c0: 43f2a430   movw r0, #0x33a4
003565c4: c0f2a510   movt r0, #0x1a5
003565c8: 90f83200   ldrb.w r0, [r0, #0x32]
003565cc: c007       lsls r0, r0, #0x1f
003565ce: 06d0       beq #0x3565de
003565d0: 80b5       push {r7, lr}
003565d2: 6f46       mov r7, sp
003565d4: 03a0       adr r0, #0xc
003565d6: edf3d0f7   bl #0xb4457a
003565da: bde88040   pop.w {r7, lr}
003565de: 0120       movs r0, #1
003565e0: 7047       bx lr

SLOT 134 OP 40f4 WIRE 6e4 HANDLER 3565fc
003565fc: 90f90810   ldrsb.w r1, [r0, #8]
00356600: 4af22070   movw r0, #0xa720
00356604: c0f26510   movt r0, #0x165
00356608: 80f86919   strb.w r1, [r0, #0x969]
0035660c: 43f2a430   movw r0, #0x33a4
00356610: c0f2a510   movt r0, #0x1a5
00356614: 90f83200   ldrb.w r0, [r0, #0x32]
00356618: c007       lsls r0, r0, #0x1f
0035661a: 06d0       beq #0x35662a
0035661c: 80b5       push {r7, lr}
0035661e: 6f46       mov r7, sp
00356620: 03a0       adr r0, #0xc
00356622: edf3aaf7   bl #0xb4457a
00356626: bde88040   pop.w {r7, lr}
0035662a: 0120       movs r0, #1
0035662c: 7047       bx lr

SLOT 135 OP 40f5 WIRE 6f0 HANDLER 356644
00356644: 90f90810   ldrsb.w r1, [r0, #8]
00356648: 4af22070   movw r0, #0xa720
0035664c: c0f26510   movt r0, #0x165
00356650: 80f86b19   strb.w r1, [r0, #0x96b]
00356654: 43f2a430   movw r0, #0x33a4
00356658: c0f2a510   movt r0, #0x1a5
0035665c: 90f83200   ldrb.w r0, [r0, #0x32]
00356660: c007       lsls r0, r0, #0x1f
00356662: 06d0       beq #0x356672
00356664: 80b5       push {r7, lr}
00356666: 6f46       mov r7, sp
00356668: 03a0       adr r0, #0xc
0035666a: edf386f7   bl #0xb4457a
0035666e: bde88040   pop.w {r7, lr}
00356672: 0120       movs r0, #1
00356674: 7047       bx lr

SLOT 136 OP 40f6 WIRE 6fc HANDLER 35668c
0035668c: 90f90810   ldrsb.w r1, [r0, #8]
00356690: 4af22070   movw r0, #0xa720
00356694: c0f26510   movt r0, #0x165
00356698: 80f8d31c   strb.w r1, [r0, #0xcd3]
0035669c: 43f2a430   movw r0, #0x33a4
003566a0: c0f2a510   movt r0, #0x1a5
003566a4: 90f83200   ldrb.w r0, [r0, #0x32]
003566a8: c007       lsls r0, r0, #0x1f
003566aa: 06d0       beq #0x3566ba
003566ac: 80b5       push {r7, lr}
003566ae: 6f46       mov r7, sp
003566b0: 03a0       adr r0, #0xc
003566b2: edf362f7   bl #0xb4457a
003566b6: bde88040   pop.w {r7, lr}
003566ba: 0120       movs r0, #1
003566bc: 7047       bx lr

SLOT 137 OP 40f7 WIRE 708 HANDLER 3566d8
003566d8: 90f90810   ldrsb.w r1, [r0, #8]
003566dc: 4af22070   movw r0, #0xa720
003566e0: c0f26510   movt r0, #0x165
003566e4: 80f8d41c   strb.w r1, [r0, #0xcd4]
003566e8: 43f2a430   movw r0, #0x33a4
003566ec: c0f2a510   movt r0, #0x1a5
003566f0: 90f83200   ldrb.w r0, [r0, #0x32]
003566f4: c007       lsls r0, r0, #0x1f
003566f6: 06d0       beq #0x356706
003566f8: 80b5       push {r7, lr}
003566fa: 6f46       mov r7, sp
003566fc: 03a0       adr r0, #0xc
003566fe: edf33cf7   bl #0xb4457a
00356702: bde88040   pop.w {r7, lr}
00356706: 0120       movs r0, #1
00356708: 7047       bx lr

SLOT 138 OP 40f8 WIRE 714 HANDLER 359f3c
00359f3c: 017a       ldrb r1, [r0, #8]
00359f3e: 4af22070   movw r0, #0xa720
00359f42: c0f26510   movt r0, #0x165
00359f46: 90f8d32b   ldrb.w r2, [r0, #0xbd3]
00359f4a: 9142       cmp r1, r2
00359f4c: 02d0       beq #0x359f54
00359f4e: 0022       movs r2, #0
00359f50: 80f8ba22   strb.w r2, [r0, #0x2ba]
00359f54: 80f8d31b   strb.w r1, [r0, #0xbd3]
00359f58: 43f2a430   movw r0, #0x33a4
00359f5c: c0f2a510   movt r0, #0x1a5
00359f60: 90f83200   ldrb.w r0, [r0, #0x32]
00359f64: c007       lsls r0, r0, #0x1f
00359f66: 06d0       beq #0x359f76
00359f68: 80b5       push {r7, lr}
00359f6a: 6f46       mov r7, sp
00359f6c: 03a0       adr r0, #0xc
00359f6e: eaf304f3   bl #0xb4457a
00359f72: bde88040   pop.w {r7, lr}
00359f76: 0120       movs r0, #1
00359f78: 7047       bx lr

SLOT 139 OP 40fb WIRE 720 HANDLER 359f9c
00359f9c: 017a       ldrb r1, [r0, #8]
00359f9e: 4af22070   movw r0, #0xa720
00359fa2: c0f26510   movt r0, #0x165
00359fa6: c0f8f01a   str.w r1, [r0, #0xaf0]
00359faa: 43f2a430   movw r0, #0x33a4
00359fae: c0f2a510   movt r0, #0x1a5
00359fb2: 90f83200   ldrb.w r0, [r0, #0x32]
00359fb6: c007       lsls r0, r0, #0x1f
00359fb8: 06d0       beq #0x359fc8
00359fba: 80b5       push {r7, lr}
00359fbc: 6f46       mov r7, sp
00359fbe: 03a0       adr r0, #0xc
00359fc0: eaf3dbf2   bl #0xb4457a
00359fc4: bde88040   pop.w {r7, lr}
00359fc8: 0120       movs r0, #1
00359fca: 7047       bx lr

SLOT 140 OP 40fc WIRE 72c HANDLER 359fe8
00359fe8: 017a       ldrb r1, [r0, #8]
00359fea: 4af22070   movw r0, #0xa720
00359fee: c0f26510   movt r0, #0x165
00359ff2: c0f8f41a   str.w r1, [r0, #0xaf4]
00359ff6: 43f2a430   movw r0, #0x33a4
00359ffa: c0f2a510   movt r0, #0x1a5
00359ffe: 90f83200   ldrb.w r0, [r0, #0x32]
0035a002: c007       lsls r0, r0, #0x1f
0035a004: 06d0       beq #0x35a014
0035a006: 80b5       push {r7, lr}
0035a008: 6f46       mov r7, sp
0035a00a: 03a0       adr r0, #0xc
0035a00c: eaf3b5f2   bl #0xb4457a
0035a010: bde88040   pop.w {r7, lr}
0035a014: 0120       movs r0, #1
0035a016: 7047       bx lr

SLOT 141 OP 40fd WIRE 738 HANDLER 35a03c
0035a03c: 017a       ldrb r1, [r0, #8]
0035a03e: 4af22070   movw r0, #0xa720
0035a042: c0f26510   movt r0, #0x165
0035a046: c0f8e81b   str.w r1, [r0, #0xbe8]
0035a04a: 43f2a430   movw r0, #0x33a4
0035a04e: c0f2a510   movt r0, #0x1a5
0035a052: 90f83200   ldrb.w r0, [r0, #0x32]
0035a056: c007       lsls r0, r0, #0x1f
0035a058: 06d0       beq #0x35a068
0035a05a: 80b5       push {r7, lr}
0035a05c: 6f46       mov r7, sp
0035a05e: 03a0       adr r0, #0xc
0035a060: eaf38bf2   bl #0xb4457a
0035a064: bde88040   pop.w {r7, lr}
0035a068: 0120       movs r0, #1
0035a06a: 7047       bx lr

SLOT 142 OP 40ff WIRE 744 HANDLER 35a0d8
0035a0d8: 017a       ldrb r1, [r0, #8]
0035a0da: 4af22070   movw r0, #0xa720
0035a0de: c0f26510   movt r0, #0x165
0035a0e2: c0f8f01b   str.w r1, [r0, #0xbf0]
0035a0e6: 43f2a430   movw r0, #0x33a4
0035a0ea: c0f2a510   movt r0, #0x1a5
0035a0ee: 90f83200   ldrb.w r0, [r0, #0x32]
0035a0f2: c007       lsls r0, r0, #0x1f
0035a0f4: 06d0       beq #0x35a104
0035a0f6: 80b5       push {r7, lr}
0035a0f8: 6f46       mov r7, sp
0035a0fa: 03a0       adr r0, #0xc
0035a0fc: eaf33df2   bl #0xb4457a
0035a100: bde88040   pop.w {r7, lr}
0035a104: 0120       movs r0, #1
0035a106: 7047       bx lr

SLOT 143 OP 4100 WIRE 750 HANDLER 35a244
0035a244: 017a       ldrb r1, [r0, #8]
0035a246: 4af22070   movw r0, #0xa720
0035a24a: c0f26510   movt r0, #0x165
0035a24e: c0f8b417   str.w r1, [r0, #0x7b4]
0035a252: 43f2a430   movw r0, #0x33a4
0035a256: c0f2a510   movt r0, #0x1a5
0035a25a: 90f83200   ldrb.w r0, [r0, #0x32]
0035a25e: c007       lsls r0, r0, #0x1f
0035a260: 06d0       beq #0x35a270
0035a262: 80b5       push {r7, lr}
0035a264: 6f46       mov r7, sp
0035a266: 03a0       adr r0, #0xc
0035a268: eaf387f1   bl #0xb4457a
0035a26c: bde88040   pop.w {r7, lr}
0035a270: 0120       movs r0, #1
0035a272: 7047       bx lr

SLOT 144 OP 4101 WIRE 75c HANDLER 35a29c
0035a29c: 017a       ldrb r1, [r0, #8]
0035a29e: 4af22070   movw r0, #0xa720
0035a2a2: c0f26510   movt r0, #0x165
0035a2a6: c0f8d813   str.w r1, [r0, #0x3d8]
0035a2aa: 43f2a430   movw r0, #0x33a4
0035a2ae: c0f2a510   movt r0, #0x1a5
0035a2b2: 90f83200   ldrb.w r0, [r0, #0x32]
0035a2b6: c007       lsls r0, r0, #0x1f
0035a2b8: 06d0       beq #0x35a2c8
0035a2ba: 80b5       push {r7, lr}
0035a2bc: 6f46       mov r7, sp
0035a2be: 03a0       adr r0, #0xc
0035a2c0: eaf35bf1   bl #0xb4457a
0035a2c4: bde88040   pop.w {r7, lr}
0035a2c8: 0120       movs r0, #1
0035a2ca: 7047       bx lr

SLOT 145 OP 4103 WIRE 768 HANDLER 35a2f4
0035a2f4: d0b5       push {r4, r6, r7, lr}
0035a2f6: 02af       add r7, sp, #8
0035a2f8: 0446       mov r4, r0
0035a2fa: 8ef0e0f2   bl #0x7e88be
0035a2fe: 227a       ldrb r2, [r4, #8]
0035a300: 042a       cmp r2, #4
0035a302: 1146       mov r1, r2
0035a304: 08bf       it eq
0035a306: 0721       movs r1, #7
0035a308: 0028       cmp r0, #0
0035a30a: 4af22070   movw r0, #0xa720
0035a30e: 08bf       it eq
0035a310: 1146       mov r1, r2
0035a312: c0f26510   movt r0, #0x165
0035a316: c0f8f41b   str.w r1, [r0, #0xbf4]
0035a31a: 43f2a430   movw r0, #0x33a4
0035a31e: c0f2a510   movt r0, #0x1a5
0035a322: 90f83200   ldrb.w r0, [r0, #0x32]
0035a326: c007       lsls r0, r0, #0x1f
0035a328: 02d0       beq #0x35a330
0035a32a: 02a0       adr r0, #8
0035a32c: eaf325f1   bl #0xb4457a
0035a330: 0120       movs r0, #1
0035a332: d0bd       pop {r4, r6, r7, pc}

SLOT 146 OP 4104 WIRE 774 HANDLER 35a4b4
0035a4b4: 43f2a430   movw r0, #0x33a4
0035a4b8: c0f2a510   movt r0, #0x1a5
0035a4bc: 90f83200   ldrb.w r0, [r0, #0x32]
0035a4c0: c007       lsls r0, r0, #0x1f
0035a4c2: 0cd0       beq #0x35a4de
0035a4c4: 80b5       push {r7, lr}
0035a4c6: 6f46       mov r7, sp
0035a4c8: 4af22070   movw r0, #0xa720
0035a4cc: c0f26510   movt r0, #0x165
0035a4d0: d0f8f81b   ldr.w r1, [r0, #0xbf8]
0035a4d4: 03a0       adr r0, #0xc
0035a4d6: eaf350f0   bl #0xb4457a
0035a4da: bde88040   pop.w {r7, lr}
0035a4de: 0120       movs r0, #1
0035a4e0: 7047       bx lr

SLOT 147 OP 4105 WIRE 780 HANDLER 35a508
0035a508: 017a       ldrb r1, [r0, #8]
0035a50a: 4af22070   movw r0, #0xa720
0035a50e: c0f26510   movt r0, #0x165
0035a512: c0f8b817   str.w r1, [r0, #0x7b8]
0035a516: 43f2a430   movw r0, #0x33a4
0035a51a: c0f2a510   movt r0, #0x1a5
0035a51e: 90f83200   ldrb.w r0, [r0, #0x32]
0035a522: c007       lsls r0, r0, #0x1f
0035a524: 06d0       beq #0x35a534
0035a526: 80b5       push {r7, lr}
0035a528: 6f46       mov r7, sp
0035a52a: 03a0       adr r0, #0xc
0035a52c: eaf325f0   bl #0xb4457a
0035a530: bde88040   pop.w {r7, lr}
0035a534: 0120       movs r0, #1
0035a536: 7047       bx lr

SLOT 148 OP 4137 WIRE 78c HANDLER 35ba7c
0035ba7c: 017a       ldrb r1, [r0, #8]
0035ba7e: 4af22070   movw r0, #0xa720
0035ba82: c0f26510   movt r0, #0x165
0035ba86: c0f8ec1c   str.w r1, [r0, #0xcec]
0035ba8a: 43f2a430   movw r0, #0x33a4
0035ba8e: c0f2a510   movt r0, #0x1a5
0035ba92: 90f83200   ldrb.w r0, [r0, #0x32]
0035ba96: c007       lsls r0, r0, #0x1f
0035ba98: 06d0       beq #0x35baa8
0035ba9a: 80b5       push {r7, lr}
0035ba9c: 6f46       mov r7, sp
0035ba9e: 03a0       adr r0, #0xc
0035baa0: e8f36bf5   bl #0xb4457a
0035baa4: bde88040   pop.w {r7, lr}
0035baa8: 0120       movs r0, #1
0035baaa: 7047       bx lr

SLOT 149 OP 4138 WIRE 798 HANDLER 35a788
0035a788: 017a       ldrb r1, [r0, #8]
0035a78a: 4af22070   movw r0, #0xa720
0035a78e: c0f26510   movt r0, #0x165
0035a792: 80f85815   strb.w r1, [r0, #0x558]
0035a796: 43f2a430   movw r0, #0x33a4
0035a79a: c0f2a510   movt r0, #0x1a5
0035a79e: 90f83200   ldrb.w r0, [r0, #0x32]
0035a7a2: c007       lsls r0, r0, #0x1f
0035a7a4: 06d0       beq #0x35a7b4
0035a7a6: 80b5       push {r7, lr}
0035a7a8: 6f46       mov r7, sp
0035a7aa: 03a0       adr r0, #0xc
0035a7ac: e9f3e5f6   bl #0xb4457a
0035a7b0: bde88040   pop.w {r7, lr}
0035a7b4: 0120       movs r0, #1
0035a7b6: 7047       bx lr

SLOT 150 OP 413a WIRE 7a4 HANDLER 35a8a0
0035a8a0: 017a       ldrb r1, [r0, #8]
0035a8a2: 4af22070   movw r0, #0xa720
0035a8a6: c0f26510   movt r0, #0x165
0035a8aa: c0f86c13   str.w r1, [r0, #0x36c]
0035a8ae: 43f2a430   movw r0, #0x33a4
0035a8b2: c0f2a510   movt r0, #0x1a5
0035a8b6: 90f83200   ldrb.w r0, [r0, #0x32]
0035a8ba: c007       lsls r0, r0, #0x1f
0035a8bc: 06d0       beq #0x35a8cc
0035a8be: 80b5       push {r7, lr}
0035a8c0: 6f46       mov r7, sp
0035a8c2: 03a0       adr r0, #0xc
0035a8c4: e9f359f6   bl #0xb4457a
0035a8c8: bde88040   pop.w {r7, lr}
0035a8cc: 0120       movs r0, #1
0035a8ce: 7047       bx lr

SLOT 151 OP 413b WIRE 7b0 HANDLER 35a944
0035a944: b0b5       push {r4, r5, r7, lr}
0035a946: 02af       add r7, sp, #8
0035a948: 0446       mov r4, r0
0035a94a: 4af22070   movw r0, #0xa720
0035a94e: 43f2a435   movw r5, #0x33a4
0035a952: 217a       ldrb r1, [r4, #8]
0035a954: c0f26510   movt r0, #0x165
0035a958: c0f2a515   movt r5, #0x1a5
0035a95c: 8164       str r1, [r0, #0x48]
0035a95e: 627a       ldrb r2, [r4, #9]
0035a960: c264       str r2, [r0, #0x4c]
0035a962: a27a       ldrb r2, [r4, #0xa]
0035a964: 0265       str r2, [r0, #0x50]
0035a966: 95f83200   ldrb.w r0, [r5, #0x32]
0035a96a: 10f0010f   tst.w r0, #1
0035a96e: 04d0       beq #0x35a97a
0035a970: 0ba0       adr r0, #0x2c
0035a972: e9f302f6   bl #0xb4457a
0035a976: 95f83200   ldrb.w r0, [r5, #0x32]
0035a97a: c107       lsls r1, r0, #0x1f
0035a97c: 05d0       beq #0x35a98a
0035a97e: 617a       ldrb r1, [r4, #9]
0035a980: 13a0       adr r0, #0x4c
0035a982: e9f3faf5   bl #0xb4457a
0035a986: 95f83200   ldrb.w r0, [r5, #0x32]
0035a98a: c007       lsls r0, r0, #0x1f
0035a98c: 06d0       beq #0x35a99c
0035a98e: a17a       ldrb r1, [r4, #0xa]
0035a990: 4bf2be60   movw r0, #0xb6be
0035a994: c0f2f700   movt r0, #0xf7
0035a998: e9f3eff5   bl #0xb4457a
0035a99c: 0120       movs r0, #1
0035a99e: b0bd       pop {r4, r5, r7, pc}

SLOT 152 OP 413c WIRE 7bc HANDLER 35a8f0
0035a8f0: 017a       ldrb r1, [r0, #8]
0035a8f2: 4af22070   movw r0, #0xa720
0035a8f6: c0f26510   movt r0, #0x165
0035a8fa: 4165       str r1, [r0, #0x54]
0035a8fc: 43f2a430   movw r0, #0x33a4
0035a900: c0f2a510   movt r0, #0x1a5
0035a904: 90f83200   ldrb.w r0, [r0, #0x32]
0035a908: c007       lsls r0, r0, #0x1f
0035a90a: 06d0       beq #0x35a91a
0035a90c: 80b5       push {r7, lr}
0035a90e: 6f46       mov r7, sp
0035a910: 03a0       adr r0, #0xc
0035a912: e9f332f6   bl #0xb4457a
0035a916: bde88040   pop.w {r7, lr}
0035a91a: 0120       movs r0, #1
0035a91c: 7047       bx lr

SLOT 153 OP 413d WIRE 7c8 HANDLER 8db48c
008db48c: 017a       ldrb r1, [r0, #8]
008db48e: 4af22070   movw r0, #0xa720
008db492: c0f26510   movt r0, #0x165
008db496: 8165       str r1, [r0, #0x58]
008db498: 43f2a430   movw r0, #0x33a4
008db49c: c0f2a510   movt r0, #0x1a5
008db4a0: 90f83200   ldrb.w r0, [r0, #0x32]
008db4a4: c007       lsls r0, r0, #0x1f
008db4a6: 09d0       beq #0x8db4bc
008db4a8: 80b5       push {r7, lr}
008db4aa: 6f46       mov r7, sp
008db4ac: 4bf27360   movw r0, #0xb673
008db4b0: c0f2f700   movt r0, #0xf7
008db4b4: 69f261f8   bl #0xb4457a
008db4b8: bde88040   pop.w {r7, lr}
008db4bc: 0120       movs r0, #1
008db4be: 7047       bx lr

SLOT 154 OP 413e WIRE 7d4 HANDLER 35a838
0035a838: 017a       ldrb r1, [r0, #8]
0035a83a: 4af22070   movw r0, #0xa720
0035a83e: c0f26510   movt r0, #0x165
0035a842: c0f8b415   str.w r1, [r0, #0x5b4]
0035a846: 43f2a430   movw r0, #0x33a4
0035a84a: c0f2a510   movt r0, #0x1a5
0035a84e: 90f83200   ldrb.w r0, [r0, #0x32]
0035a852: c007       lsls r0, r0, #0x1f
0035a854: 06d0       beq #0x35a864
0035a856: 80b5       push {r7, lr}
0035a858: 6f46       mov r7, sp
0035a85a: 03a0       adr r0, #0xc
0035a85c: e9f38df6   bl #0xb4457a
0035a860: bde88040   pop.w {r7, lr}
0035a864: 0120       movs r0, #1
0035a866: 7047       bx lr

SLOT 155 OP 413f WIRE 7e0 HANDLER 35aa04
0035aa04: 017a       ldrb r1, [r0, #8]
0035aa06: 4af22070   movw r0, #0xa720
0035aa0a: c0f26510   movt r0, #0x165
0035aa0e: 0029       cmp r1, #0
0035aa10: c0f8f812   str.w r1, [r0, #0x2f8]
0035aa14: 02d1       bne #0x35aa1c
0035aa16: 0022       movs r2, #0
0035aa18: c0f8f422   str.w r2, [r0, #0x2f4]
0035aa1c: 43f2a430   movw r0, #0x33a4
0035aa20: c0f2a510   movt r0, #0x1a5
0035aa24: 90f83200   ldrb.w r0, [r0, #0x32]
0035aa28: c007       lsls r0, r0, #0x1f
0035aa2a: 06d0       beq #0x35aa3a
0035aa2c: 80b5       push {r7, lr}
0035aa2e: 6f46       mov r7, sp
0035aa30: 03a0       adr r0, #0xc
0035aa32: e9f3a2f5   bl #0xb4457a
0035aa36: bde88040   pop.w {r7, lr}
0035aa3a: 0120       movs r0, #1
0035aa3c: 7047       bx lr

SLOT 156 OP 4141 WIRE 7ec HANDLER 356340
00356340: 017a       ldrb r1, [r0, #8]
00356342: 4af22070   movw r0, #0xa720
00356346: c0f26510   movt r0, #0x165
0035634a: c0f8fc10   str.w r1, [r0, #0xfc]
0035634e: 43f2a430   movw r0, #0x33a4
00356352: c0f2a510   movt r0, #0x1a5
00356356: 90f83200   ldrb.w r0, [r0, #0x32]
0035635a: c007       lsls r0, r0, #0x1f
0035635c: 06d0       beq #0x35636c
0035635e: 80b5       push {r7, lr}
00356360: 6f46       mov r7, sp
00356362: 03a0       adr r0, #0xc
00356364: eef309f1   bl #0xb4457a
00356368: bde88040   pop.w {r7, lr}
0035636c: 0120       movs r0, #1
0035636e: 7047       bx lr

SLOT 157 OP 4142 WIRE 7f8 HANDLER 35aabc
0035aabc: 017a       ldrb r1, [r0, #8]
0035aabe: 4af22070   movw r0, #0xa720
0035aac2: c0f26510   movt r0, #0x165
0035aac6: c0f80013   str.w r1, [r0, #0x300]
0035aaca: 43f2a430   movw r0, #0x33a4
0035aace: c0f2a510   movt r0, #0x1a5
0035aad2: 90f83200   ldrb.w r0, [r0, #0x32]
0035aad6: c007       lsls r0, r0, #0x1f
0035aad8: 06d0       beq #0x35aae8
0035aada: 80b5       push {r7, lr}
0035aadc: 6f46       mov r7, sp
0035aade: 03a0       adr r0, #0xc
0035aae0: e9f34bf5   bl #0xb4457a
0035aae4: bde88040   pop.w {r7, lr}
0035aae8: 0120       movs r0, #1
0035aaea: 7047       bx lr

SLOT 158 OP 4143 WIRE 804 HANDLER 35bd80
0035bd80: 4af22071   movw r1, #0xa720
0035bd84: c0f26511   movt r1, #0x165
0035bd88: d1f8fc2a   ldr.w r2, [r1, #0xafc]
0035bd8c: 032a       cmp r2, #3
0035bd8e: 06d1       bne #0x35bd9e
0035bd90: 007a       ldrb r0, [r0, #8]
0035bd92: 0022       movs r2, #0
0035bd94: 0028       cmp r0, #0
0035bd96: 08bf       it eq
0035bd98: 0122       movs r2, #1
0035bd9a: c1f8042b   str.w r2, [r1, #0xb04]
0035bd9e: 43f2a430   movw r0, #0x33a4
0035bda2: c0f2a510   movt r0, #0x1a5
0035bda6: 90f83200   ldrb.w r0, [r0, #0x32]
0035bdaa: c007       lsls r0, r0, #0x1f
0035bdac: 08d0       beq #0x35bdc0
0035bdae: 80b5       push {r7, lr}
0035bdb0: 6f46       mov r7, sp
0035bdb2: d1f8041b   ldr.w r1, [r1, #0xb04]
0035bdb6: 03a0       adr r0, #0xc
0035bdb8: e8f3dff3   bl #0xb4457a
0035bdbc: bde88040   pop.w {r7, lr}
0035bdc0: 0120       movs r0, #1
0035bdc2: 7047       bx lr

SLOT 159 OP 4145 WIRE 810 HANDLER 35becc
0035becc: 017a       ldrb r1, [r0, #8]
0035bece: 4af22070   movw r0, #0xa720
0035bed2: c0f26510   movt r0, #0x165
0035bed6: c0f8dc13   str.w r1, [r0, #0x3dc]
0035beda: 43f2a430   movw r0, #0x33a4
0035bede: c0f2a510   movt r0, #0x1a5
0035bee2: 90f83200   ldrb.w r0, [r0, #0x32]
0035bee6: c007       lsls r0, r0, #0x1f
0035bee8: 06d0       beq #0x35bef8
0035beea: 80b5       push {r7, lr}
0035beec: 6f46       mov r7, sp
0035beee: 03a0       adr r0, #0xc
0035bef0: e8f343f3   bl #0xb4457a
0035bef4: bde88040   pop.w {r7, lr}
0035bef8: 0120       movs r0, #1
0035befa: 7047       bx lr

SLOT 160 OP 4146 WIRE 81c HANDLER 35bf20
0035bf20: 017a       ldrb r1, [r0, #8]
0035bf22: 4af22070   movw r0, #0xa720
0035bf26: c0f26510   movt r0, #0x165
0035bf2a: c0f8e013   str.w r1, [r0, #0x3e0]
0035bf2e: 43f2a430   movw r0, #0x33a4
0035bf32: c0f2a510   movt r0, #0x1a5
0035bf36: 90f83200   ldrb.w r0, [r0, #0x32]
0035bf3a: c007       lsls r0, r0, #0x1f
0035bf3c: 06d0       beq #0x35bf4c
0035bf3e: 80b5       push {r7, lr}
0035bf40: 6f46       mov r7, sp
0035bf42: 03a0       adr r0, #0xc
0035bf44: e8f319f3   bl #0xb4457a
0035bf48: bde88040   pop.w {r7, lr}
0035bf4c: 0120       movs r0, #1
0035bf4e: 7047       bx lr

SLOT 161 OP 4148 WIRE 828 HANDLER 35bf74
0035bf74: 017a       ldrb r1, [r0, #8]
0035bf76: 4af22070   movw r0, #0xa720
0035bf7a: c0f26510   movt r0, #0x165
0035bf7e: c0f8f811   str.w r1, [r0, #0x1f8]
0035bf82: 43f2a430   movw r0, #0x33a4
0035bf86: c0f2a510   movt r0, #0x1a5
0035bf8a: 90f83200   ldrb.w r0, [r0, #0x32]
0035bf8e: c007       lsls r0, r0, #0x1f
0035bf90: 06d0       beq #0x35bfa0
0035bf92: 80b5       push {r7, lr}
0035bf94: 6f46       mov r7, sp
0035bf96: 03a0       adr r0, #0xc
0035bf98: e8f3eff2   bl #0xb4457a
0035bf9c: bde88040   pop.w {r7, lr}
0035bfa0: 0120       movs r0, #1
0035bfa2: 7047       bx lr

SLOT 162 OP 4149 WIRE 834 HANDLER 35c314
0035c314: 017a       ldrb r1, [r0, #8]
0035c316: 4af22070   movw r0, #0xa720
0035c31a: c0f26510   movt r0, #0x165
0035c31e: c0f8e413   str.w r1, [r0, #0x3e4]
0035c322: 43f2a430   movw r0, #0x33a4
0035c326: c0f2a510   movt r0, #0x1a5
0035c32a: 90f83200   ldrb.w r0, [r0, #0x32]
0035c32e: c007       lsls r0, r0, #0x1f
0035c330: 06d0       beq #0x35c340
0035c332: 80b5       push {r7, lr}
0035c334: 6f46       mov r7, sp
0035c336: 03a0       adr r0, #0xc
0035c338: e8f31ff1   bl #0xb4457a
0035c33c: bde88040   pop.w {r7, lr}
0035c340: 0120       movs r0, #1
0035c342: 7047       bx lr

SLOT 163 OP 414b WIRE 840 HANDLER 35bfc0
0035bfc0: 017a       ldrb r1, [r0, #8]
0035bfc2: 4af22070   movw r0, #0xa720
0035bfc6: c0f26510   movt r0, #0x165
0035bfca: c0f8bc17   str.w r1, [r0, #0x7bc]
0035bfce: 43f2a430   movw r0, #0x33a4
0035bfd2: c0f2a510   movt r0, #0x1a5
0035bfd6: 90f83200   ldrb.w r0, [r0, #0x32]
0035bfda: c007       lsls r0, r0, #0x1f
0035bfdc: 06d0       beq #0x35bfec
0035bfde: 80b5       push {r7, lr}
0035bfe0: 6f46       mov r7, sp
0035bfe2: 03a0       adr r0, #0xc
0035bfe4: e8f3c9f2   bl #0xb4457a
0035bfe8: bde88040   pop.w {r7, lr}
0035bfec: 0120       movs r0, #1
0035bfee: 7047       bx lr

SLOT 164 OP 414c WIRE 84c HANDLER 35c00c
0035c00c: 017a       ldrb r1, [r0, #8]
0035c00e: 4af22070   movw r0, #0xa720
0035c012: c0f26510   movt r0, #0x165
0035c016: c0f8c017   str.w r1, [r0, #0x7c0]
0035c01a: 43f2a430   movw r0, #0x33a4
0035c01e: c0f2a510   movt r0, #0x1a5
0035c022: 90f83200   ldrb.w r0, [r0, #0x32]
0035c026: c007       lsls r0, r0, #0x1f
0035c028: 06d0       beq #0x35c038
0035c02a: 80b5       push {r7, lr}
0035c02c: 6f46       mov r7, sp
0035c02e: 03a0       adr r0, #0xc
0035c030: e8f3a3f2   bl #0xb4457a
0035c034: bde88040   pop.w {r7, lr}
0035c038: 0120       movs r0, #1
0035c03a: 7047       bx lr

SLOT 165 OP 4150 WIRE 858 HANDLER 35c060
0035c060: 017a       ldrb r1, [r0, #8]
0035c062: 4af22072   movw r2, #0xa720
0035c066: c0f26512   movt r2, #0x165
0035c06a: 0129       cmp r1, #1
0035c06c: 0846       mov r0, r1
0035c06e: 18bf       it ne
0035c070: 0020       movs r0, #0
0035c072: 82f82008   strb.w r0, [r2, #0x820]
0035c076: 43f2a430   movw r0, #0x33a4
0035c07a: c0f2a510   movt r0, #0x1a5
0035c07e: 90f83200   ldrb.w r0, [r0, #0x32]
0035c082: c007       lsls r0, r0, #0x1f
0035c084: 09d0       beq #0x35c09a
0035c086: 80b5       push {r7, lr}
0035c088: 6f46       mov r7, sp
0035c08a: 0129       cmp r1, #1
0035c08c: 04a0       adr r0, #0x10
0035c08e: 18bf       it ne
0035c090: 0021       movs r1, #0
0035c092: e8f372f2   bl #0xb4457a
0035c096: bde88040   pop.w {r7, lr}
0035c09a: 0120       movs r0, #1
0035c09c: 7047       bx lr

SLOT 166 OP 4151 WIRE 864 HANDLER 8db508
008db508: b0b5       push {r4, r5, r7, lr}
008db50a: 02af       add r7, sp, #8
008db50c: 84b0       sub sp, #0x10
008db50e: 8168       ldr r1, [r0, #8]
008db510: 4af22075   movw r5, #0xa720
008db514: c0f26515   movt r5, #0x165
008db518: c5f8e813   str.w r1, [r5, #0x3e8]
008db51c: 8289       ldrh r2, [r0, #0xc]
008db51e: a5f8ec23   strh.w r2, [r5, #0x3ec]
008db522: 837b       ldrb r3, [r0, #0xe]
008db524: c5f8f033   str.w r3, [r5, #0x3f0]
008db528: d0f810c0   ldr.w ip, [r0, #0x10]
008db52c: c5f8f4c3   str.w ip, [r5, #0x3f4]
008db530: b0f814e0   ldrh.w lr, [r0, #0x14]
008db534: a5f8f8e3   strh.w lr, [r5, #0x3f8]
008db538: 847d       ldrb r4, [r0, #0x16]
008db53a: c5f8fc43   str.w r4, [r5, #0x3fc]
008db53e: c07d       ldrb r0, [r0, #0x17]
008db540: c5f80004   str.w r0, [r5, #0x400]
008db544: 43f2a435   movw r5, #0x33a4
008db548: c0f2a515   movt r5, #0x1a5
008db54c: 95f83250   ldrb.w r5, [r5, #0x32]
008db550: ed07       lsls r5, r5, #0x1f
008db552: 09d0       beq #0x8db568
008db554: cde900ce   strd ip, lr, [sp]
008db558: cde90240   strd r4, r0, [sp, #8]
008db55c: 4bf24870   movw r0, #0xb748
008db560: c0f2f700   movt r0, #0xf7
008db564: 69f209f8   bl #0xb4457a
008db568: 0120       movs r0, #1
008db56a: 04b0       add sp, #0x10
008db56c: b0bd       pop {r4, r5, r7, pc}

SLOT 167 OP 4154 WIRE 87c HANDLER 35c4a4
0035c4a4: d0b5       push {r4, r6, r7, lr}
0035c4a6: 02af       add r7, sp, #8
0035c4a8: 82b0       sub sp, #8
0035c4aa: 017a       ldrb r1, [r0, #8]
0035c4ac: 4af2207e   movw lr, #0xa720
0035c4b0: c0f2651e   movt lr, #0x165
0035c4b4: 0029       cmp r1, #0
0035c4b6: 0a46       mov r2, r1
0035c4b8: 18bf       it ne
0035c4ba: 0122       movs r2, #1
0035c4bc: 8ef86420   strb.w r2, [lr, #0x64]
0035c4c0: 427a       ldrb r2, [r0, #9]
0035c4c2: 002a       cmp r2, #0
0035c4c4: 1346       mov r3, r2
0035c4c6: 18bf       it ne
0035c4c8: 0123       movs r3, #1
0035c4ca: 8ef86530   strb.w r3, [lr, #0x65]
0035c4ce: 837a       ldrb r3, [r0, #0xa]
0035c4d0: 90f80bc0   ldrb.w ip, [r0, #0xb]
0035c4d4: 5cea0304   orrs.w r4, ip, r3
0035c4d8: 18bf       it ne
0035c4da: 0124       movs r4, #1
0035c4dc: 8ef86640   strb.w r4, [lr, #0x66]
0035c4e0: 007b       ldrb r0, [r0, #0xc]
0035c4e2: 50ea0304   orrs.w r4, r0, r3
0035c4e6: 18bf       it ne
0035c4e8: 0124       movs r4, #1
0035c4ea: 8ef86740   strb.w r4, [lr, #0x67]
0035c4ee: 43f2a434   movw r4, #0x33a4
0035c4f2: c0f2a514   movt r4, #0x1a5
0035c4f6: 94f83240   ldrb.w r4, [r4, #0x32]
0035c4fa: e407       lsls r4, r4, #0x1f
0035c4fc: 04d0       beq #0x35c508
0035c4fe: cde900c0   strd ip, r0, [sp]
0035c502: 03a0       adr r0, #0xc
0035c504: e8f339f0   bl #0xb4457a
0035c508: 0120       movs r0, #1
0035c50a: 02b0       add sp, #8
0035c50c: d0bd       pop {r4, r6, r7, pc}

SLOT 168 OP 4155 WIRE 88c HANDLER 35c54c
0035c54c: f0b5       push {r4, r5, r6, r7, lr}
0035c54e: 03af       add r7, sp, #0xc
0035c550: 4df8048d   str r8, [sp, #-0x4]!
0035c554: 86b0       sub sp, #0x18
0035c556: 0446       mov r4, r0
0035c558: a068       ldr r0, [r4, #8]
0035c55a: 18b1       cbz r0, #0x35c564
0035c55c: 6069       ldr r0, [r4, #0x14]
0035c55e: 08b1       cbz r0, #0x35c564
0035c560: e668       ldr r6, [r4, #0xc]
0035c562: 01e0       b #0x35c568
0035c564: 4ff0ff36   mov.w r6, #-1
0035c568: 49f2d065   movw r5, #0x96d0
0035c56c: c0f26515   movt r5, #0x165
0035c570: 2868       ldr r0, [r5]
0035c572: b042       cmp r0, r6
0035c574: 28d0       beq #0x35c5c8
0035c576: 2846       mov r0, r5
0035c578: 0521       movs r1, #5
0035c57a: e8f30cf3   bl #0xb44b96
0035c57e: d4f80880   ldr.w r8, [r4, #8]
0035c582: 2846       mov r0, r5
0035c584: b521       movs r1, #0xb5
0035c586: e8f306f3   bl #0xb44b96
0035c58a: 0120       movs r0, #1
0035c58c: 2e60       str r6, [r5]
0035c58e: c5f80880   str.w r8, [r5, #8]
0035c592: a871       strb r0, [r5, #6]
0035c594: 701c       adds r0, r6, #1
0035c596: 3bd0       beq #0x35c610
0035c598: 49f2d066   movw r6, #0x96d0
0035c59c: 0121       movs r1, #1
0035c59e: 0522       movs r2, #5
0035c5a0: c0f26516   movt r6, #0x165
0035c5a4: 3046       mov r0, r6
0035c5a6: e8f341f2   bl #0xb44a2c
0035c5aa: 60b1       cbz r0, #0x35c5c6
0035c5ac: 4ff0ff30   mov.w r0, #-1
0035c5b0: 4021       movs r1, #0x40
0035c5b2: 3060       str r0, [r6]
0035c5b4: 0020       movs r0, #0
0035c5b6: b080       strh r0, [r6, #4]
0035c5b8: b060       str r0, [r6, #8]
0035c5ba: b071       strb r0, [r6, #6]
0035c5bc: 06f11000   add.w r0, r6, #0x10
0035c5c0: c2f29eeb   blx #0x61ed00
0035c5c4: 24e0       b #0x35c610
0035c5c6: 3668       ldr r6, [r6]
0035c5c8: 701c       adds r0, r6, #1
0035c5ca: 21d0       beq #0x35c610
0035c5cc: d5e90412   ldrd r1, r2, [r5, #0x10]
0035c5d0: 2369       ldr r3, [r4, #0x10]
0035c5d2: 4af22070   movw r0, #0xa720
0035c5d6: c0f26510   movt r0, #0x165
0035c5da: 5b18       adds r3, r3, r1
0035c5dc: 8366       str r3, [r0, #0x68]
0035c5de: 42f10003   adc r3, r2, #0
0035c5e2: c366       str r3, [r0, #0x6c]
0035c5e4: 6369       ldr r3, [r4, #0x14]
0035c5e6: 8367       str r3, [r0, #0x78]
0035c5e8: a369       ldr r3, [r4, #0x18]
0035c5ea: c918       adds r1, r1, r3
0035c5ec: 0167       str r1, [r0, #0x70]
0035c5ee: 42f10001   adc r1, r2, #0
0035c5f2: 04f12002   add.w r2, r4, #0x20
0035c5f6: 4167       str r1, [r0, #0x74]
0035c5f8: e169       ldr r1, [r4, #0x1c]
0035c5fa: c167       str r1, [r0, #0x7c]
0035c5fc: 0021       movs r1, #0
0035c5fe: 535c       ldrb r3, [r2, r1]
0035c600: 7bb1       cbz r3, #0x35c622
0035c602: 4618       adds r6, r0, r1
0035c604: 0131       adds r1, #1
0035c606: 3f29       cmp r1, #0x3f
0035c608: 86f88030   strb.w r3, [r6, #0x80]
0035c60c: f7d3       blo #0x35c5fe
0035c60e: 0ee0       b #0x35c62e
0035c610: 4af22070   movw r0, #0xa720
0035c614: 5721       movs r1, #0x57
0035c616: c0f26510   movt r0, #0x165
0035c61a: 6830       adds r0, #0x68
0035c61c: c2f270eb   blx #0x61ed00
0035c620: 05e0       b #0x35c62e
0035c622: 0844       add r0, r1
0035c624: c1f13f01   rsb.w r1, r1, #0x3f
0035c628: 8030       adds r0, #0x80
0035c62a: c2f26aeb   blx #0x61ed00
0035c62e: 4af22074   movw r4, #0xa720
0035c632: 43f2a438   movw r8, #0x33a4
0035c636: c0f26514   movt r4, #0x165
0035c63a: c0f2a518   movt r8, #0x1a5
0035c63e: d4f8c000   ldr.w r0, [r4, #0xc0]
0035c642: 98f83210   ldrb.w r1, [r8, #0x32]
0035c646: 0130       adds r0, #1
0035c648: 11f0010f   tst.w r1, #1
0035c64c: c4f8c000   str.w r0, [r4, #0xc0]
0035c650: 14d0       beq #0x35c67c
0035c652: 04f1700c   add.w ip, r4, #0x70
0035c656: d4e91a23   ldrd r2, r3, [r4, #0x68]
0035c65a: 9ce84210   ldm.w ip, {r1, r6, ip}
0035c65e: e56f       ldr r5, [r4, #0x7c]
0035c660: cde90216   strd r1, r6, [sp, #8]
0035c664: cde90450   strd r5, r0, [sp, #0x10]
0035c668: 4bf28970   movw r0, #0xb789
0035c66c: cdf800c0   str.w ip, [sp]
0035c670: c0f2f700   movt r0, #0xf7
0035c674: e7f381f7   bl #0xb4457a
0035c678: 98f83210   ldrb.w r1, [r8, #0x32]
0035c67c: c807       lsls r0, r1, #0x1f
0035c67e: 04d0       beq #0x35c68a
0035c680: 04f18001   add.w r1, r4, #0x80
0035c684: 03a0       adr r0, #0xc
0035c686: e7f378f7   bl #0xb4457a
0035c68a: 0120       movs r0, #1
0035c68c: 06b0       add sp, #0x18
0035c68e: 5df8048b   ldr r8, [sp], #4
0035c692: f0bd       pop {r4, r5, r6, r7, pc}

SLOT 169 OP 4156 WIRE 8ec HANDLER 35c6a8
0035c6a8: 017a       ldrb r1, [r0, #8]
0035c6aa: 4af22072   movw r2, #0xa720
0035c6ae: c0f26512   movt r2, #0x165
0035c6b2: 0029       cmp r1, #0
0035c6b4: 0846       mov r0, r1
0035c6b6: 18bf       it ne
0035c6b8: 0120       movs r0, #1
0035c6ba: 82f8c800   strb.w r0, [r2, #0xc8]
0035c6be: 43f2a430   movw r0, #0x33a4
0035c6c2: c0f2a510   movt r0, #0x1a5
0035c6c6: 90f83200   ldrb.w r0, [r0, #0x32]
0035c6ca: c007       lsls r0, r0, #0x1f
0035c6cc: 09d0       beq #0x35c6e2
0035c6ce: 80b5       push {r7, lr}
0035c6d0: 6f46       mov r7, sp
0035c6d2: 0029       cmp r1, #0
0035c6d4: 04a0       adr r0, #0x10
0035c6d6: 18bf       it ne
0035c6d8: 0121       movs r1, #1
0035c6da: e7f34ef7   bl #0xb4457a
0035c6de: bde88040   pop.w {r7, lr}
0035c6e2: 0120       movs r0, #1
0035c6e4: 7047       bx lr

SLOT 170 OP 4157 WIRE 8f8 HANDLER 8db56e
008db56e: d0b5       push {r4, r6, r7, lr}
008db570: 02af       add r7, sp, #8
008db572: 82b0       sub sp, #8
008db574: 017a       ldrb r1, [r0, #8]
008db576: 4af2207e   movw lr, #0xa720
008db57a: c0f2651e   movt lr, #0x165
008db57e: cef8f81a   str.w r1, [lr, #0xaf8]
008db582: 427a       ldrb r2, [r0, #9]
008db584: cef8fc2a   str.w r2, [lr, #0xafc]
008db588: 032a       cmp r2, #3
008db58a: 837a       ldrb r3, [r0, #0xa]
008db58c: cef8003b   str.w r3, [lr, #0xb00]
008db590: 03d0       beq #0x8db59a
008db592: 90f80bc0   ldrb.w ip, [r0, #0xb]
008db596: cef804cb   str.w ip, [lr, #0xb04]
008db59a: 90f80cc0   ldrb.w ip, [r0, #0xc]
008db59e: cef808cb   str.w ip, [lr, #0xb08]
008db5a2: def88446   ldr.w r4, [lr, #0x684]
008db5a6: 0134       adds r4, #1
008db5a8: cef88446   str.w r4, [lr, #0x684]
008db5ac: 43f2a434   movw r4, #0x33a4
008db5b0: c0f2a514   movt r4, #0x1a5
008db5b4: 94f83240   ldrb.w r4, [r4, #0x32]
008db5b8: e407       lsls r4, r4, #0x1f
008db5ba: 08d0       beq #0x8db5ce
008db5bc: c07a       ldrb r0, [r0, #0xb]
008db5be: cde9000c   strd r0, ip, [sp]
008db5c2: 4bf2e170   movw r0, #0xb7e1
008db5c6: c0f2f700   movt r0, #0xf7
008db5ca: 68f2d6ff   bl #0xb4457a
008db5ce: 0120       movs r0, #1
008db5d0: 02b0       add sp, #8
008db5d2: d0bd       pop {r4, r6, r7, pc}

SLOT 171 OP 4158 WIRE 908 HANDLER 355d08
00355d08: 8168       ldr r1, [r0, #8]
00355d0a: 4af22073   movw r3, #0xa720
00355d0e: c0f26513   movt r3, #0x165
00355d12: c3f82c14   str.w r1, [r3, #0x42c]
00355d16: c268       ldr r2, [r0, #0xc]
00355d18: 43f2a430   movw r0, #0x33a4
00355d1c: c0f2a510   movt r0, #0x1a5
00355d20: 90f83200   ldrb.w r0, [r0, #0x32]
00355d24: c3f83024   str.w r2, [r3, #0x430]
00355d28: c007       lsls r0, r0, #0x1f
00355d2a: 06d0       beq #0x355d3a
00355d2c: 80b5       push {r7, lr}
00355d2e: 6f46       mov r7, sp
00355d30: 03a0       adr r0, #0xc
00355d32: eef322f4   bl #0xb4457a
00355d36: bde88040   pop.w {r7, lr}
00355d3a: 0120       movs r0, #1
00355d3c: 7047       bx lr

SLOT 172 OP 4159 WIRE 918 HANDLER 35c824
0035c824: 017a       ldrb r1, [r0, #8]
0035c826: 4af22073   movw r3, #0xa720
0035c82a: c0f26513   movt r3, #0x165
0035c82e: c3f8bc11   str.w r1, [r3, #0x1bc]
0035c832: 4289       ldrh r2, [r0, #0xa]
0035c834: 43f2a430   movw r0, #0x33a4
0035c838: c0f2a510   movt r0, #0x1a5
0035c83c: 90f83200   ldrb.w r0, [r0, #0x32]
0035c840: a3f8c021   strh.w r2, [r3, #0x1c0]
0035c844: c007       lsls r0, r0, #0x1f
0035c846: 06d0       beq #0x35c856
0035c848: 80b5       push {r7, lr}
0035c84a: 6f46       mov r7, sp
0035c84c: 03a0       adr r0, #0xc
0035c84e: e7f394f6   bl #0xb4457a
0035c852: bde88040   pop.w {r7, lr}
0035c856: 0120       movs r0, #1
0035c858: 7047       bx lr

SLOT 173 OP 415b WIRE 924 HANDLER 35c7c0
0035c7c0: 017a       ldrb r1, [r0, #8]
0035c7c2: 4af22072   movw r2, #0xa720
0035c7c6: c0f26512   movt r2, #0x165
0035c7ca: 0129       cmp r1, #1
0035c7cc: 0846       mov r0, r1
0035c7ce: 18bf       it ne
0035c7d0: 0020       movs r0, #0
0035c7d2: 82f82108   strb.w r0, [r2, #0x821]
0035c7d6: 43f2a430   movw r0, #0x33a4
0035c7da: c0f2a510   movt r0, #0x1a5
0035c7de: 90f83200   ldrb.w r0, [r0, #0x32]
0035c7e2: c007       lsls r0, r0, #0x1f
0035c7e4: 09d0       beq #0x35c7fa
0035c7e6: 80b5       push {r7, lr}
0035c7e8: 6f46       mov r7, sp
0035c7ea: 0129       cmp r1, #1
0035c7ec: 04a0       adr r0, #0x10
0035c7ee: 18bf       it ne
0035c7f0: 0021       movs r1, #0
0035c7f2: e7f3c2f6   bl #0xb4457a
0035c7f6: bde88040   pop.w {r7, lr}
0035c7fa: 0120       movs r0, #1
0035c7fc: 7047       bx lr

SLOT 174 OP 415f WIRE 930 HANDLER 35a358
0035a358: f0b5       push {r4, r5, r6, r7, lr}
0035a35a: 03af       add r7, sp, #0xc
0035a35c: 2de9000f   push.w {r8, sb, sl, fp}
0035a360: 91b0       sub sp, #0x44
0035a362: 017a       ldrb r1, [r0, #8]
0035a364: 4af22078   movw r8, #0xa720
0035a368: 43f2a43a   movw sl, #0x33a4
0035a36c: 0024       movs r4, #0
0035a36e: 0df11409   add.w sb, sp, #0x14
0035a372: 0df13c0b   add.w fp, sp, #0x3c
0035a376: c0f26518   movt r8, #0x165
0035a37a: c0f2a51a   movt sl, #0x1a5
0035a37e: 0f91       str r1, [sp, #0x3c]
0035a380: 817b       ldrb r1, [r0, #0xe]
0035a382: 1091       str r1, [sp, #0x40]
0035a384: 417a       ldrb r1, [r0, #9]
0035a386: 8df81410   strb.w r1, [sp, #0x14]
0035a38a: 817a       ldrb r1, [r0, #0xa]
0035a38c: 0691       str r1, [sp, #0x18]
0035a38e: c17a       ldrb r1, [r0, #0xb]
0035a390: 0791       str r1, [sp, #0x1c]
0035a392: 017b       ldrb r1, [r0, #0xc]
0035a394: 0891       str r1, [sp, #0x20]
0035a396: 417b       ldrb r1, [r0, #0xd]
0035a398: 0991       str r1, [sp, #0x24]
0035a39a: c17b       ldrb r1, [r0, #0xf]
0035a39c: 8df82810   strb.w r1, [sp, #0x28]
0035a3a0: 017c       ldrb r1, [r0, #0x10]
0035a3a2: 0b91       str r1, [sp, #0x2c]
0035a3a4: 417c       ldrb r1, [r0, #0x11]
0035a3a6: 0c91       str r1, [sp, #0x30]
0035a3a8: 817c       ldrb r1, [r0, #0x12]
0035a3aa: 0d91       str r1, [sp, #0x34]
0035a3ac: c07c       ldrb r0, [r0, #0x13]
0035a3ae: 0e90       str r0, [sp, #0x38]
0035a3b0: 08f61440   addw r0, r8, #0xc14
0035a3b4: 0290       str r0, [sp, #8]
0035a3b6: 08f62840   addw r0, r8, #0xc28
0035a3ba: 0490       str r0, [sp, #0x10]
0035a3bc: 08f63c40   addw r0, r8, #0xc3c
0035a3c0: 0390       str r0, [sp, #0xc]
0035a3c2: 9af83200   ldrb.w r0, [sl, #0x32]
0035a3c6: 5bf80460   ldr.w r6, [fp, r4]
0035a3ca: c007       lsls r0, r0, #0x1f
0035a3cc: 0bd0       beq #0x35a3e6
0035a3ce: 04eb8400   add.w r0, r4, r4, lsl #2
0035a3d2: 05a9       add r1, sp, #0x14
0035a3d4: 0844       add r0, r1
0035a3d6: 3146       mov r1, r6
0035a3d8: d0e90223   ldrd r2, r3, [r0, #8]
0035a3dc: 0069       ldr r0, [r0, #0x10]
0035a3de: 0090       str r0, [sp]
0035a3e0: 1ba0       adr r0, #0x6c
0035a3e2: eaf3caf0   bl #0xb4457a
0035a3e6: 062e       cmp r6, #6
0035a3e8: 12d8       bhi #0x35a410
0035a3ea: dfe806f0   tbb [pc, r6]
0035a3ee: 2704       lsls r7, r4, #0x10
0035a3f0: 0608       lsrs r6, r0, #0x20
0035a3f2: 0e16       asrs r6, r1, #0x18
0035a3f4: 1900       movs r1, r3
0035a3f6: 0299       ldr r1, [sp, #8]
0035a3f8: 02e0       b #0x35a400
0035a400: cc46       mov ip, sb
0035a402: 9ce86d00   ldm.w ip, {r0, r2, r3, r5, r6}
0035a406: 6dc1       stm r1!, {r0, r2, r3, r5, r6}
0035a408: 18e0       b #0x35a43c
0035a410: 1da0       adr r0, #0x74
0035a412: 3146       mov r1, r6
0035a414: eaf3b1f0   bl #0xb4457a
0035a418: 10e0       b #0x35a43c
0035a43c: 0434       adds r4, #4
0035a43e: 09f11409   add.w sb, sb, #0x14
0035a442: 082c       cmp r4, #8
0035a444: bdd1       bne #0x35a3c2
0035a446: 0120       movs r0, #1
0035a448: 11b0       add sp, #0x44
0035a44a: bde8000f   pop.w {r8, sb, sl, fp}
0035a44e: f0bd       pop {r4, r5, r6, r7, pc}

SLOT 175 OP 4161 WIRE 944 HANDLER 35c924
0035c924: 017a       ldrb r1, [r0, #8]
0035c926: 4af22070   movw r0, #0xa720
0035c92a: c0f26510   movt r0, #0x165
0035c92e: 80f80914   strb.w r1, [r0, #0x409]
0035c932: 43f2a430   movw r0, #0x33a4
0035c936: c0f2a510   movt r0, #0x1a5
0035c93a: 90f83200   ldrb.w r0, [r0, #0x32]
0035c93e: c007       lsls r0, r0, #0x1f
0035c940: 06d0       beq #0x35c950
0035c942: 80b5       push {r7, lr}
0035c944: 6f46       mov r7, sp
0035c946: 03a0       adr r0, #0xc
0035c948: e7f317f6   bl #0xb4457a
0035c94c: bde88040   pop.w {r7, lr}
0035c950: 0120       movs r0, #1
0035c952: 7047       bx lr

SLOT 176 OP 4162 WIRE 950 HANDLER 35c97c
0035c97c: 017a       ldrb r1, [r0, #8]
0035c97e: 4af22073   movw r3, #0xa720
0035c982: c0f26513   movt r3, #0x165
0035c986: c3f80c14   str.w r1, [r3, #0x40c]
0035c98a: 427a       ldrb r2, [r0, #9]
0035c98c: 43f2a430   movw r0, #0x33a4
0035c990: c0f2a510   movt r0, #0x1a5
0035c994: 90f83200   ldrb.w r0, [r0, #0x32]
0035c998: 83f81024   strb.w r2, [r3, #0x410]
0035c99c: c007       lsls r0, r0, #0x1f
0035c99e: 06d0       beq #0x35c9ae
0035c9a0: 80b5       push {r7, lr}
0035c9a2: 6f46       mov r7, sp
0035c9a4: 03a0       adr r0, #0xc
0035c9a6: e7f3e8f5   bl #0xb4457a
0035c9aa: bde88040   pop.w {r7, lr}
0035c9ae: 0120       movs r0, #1
0035c9b0: 7047       bx lr

SLOT 177 OP 4163 WIRE 95c HANDLER 35c9e4
0035c9e4: 017a       ldrb r1, [r0, #8]
0035c9e6: 4af22070   movw r0, #0xa720
0035c9ea: c0f26510   movt r0, #0x165
0035c9ee: c0f80c1b   str.w r1, [r0, #0xb0c]
0035c9f2: 43f2a430   movw r0, #0x33a4
0035c9f6: c0f2a510   movt r0, #0x1a5
0035c9fa: 90f83200   ldrb.w r0, [r0, #0x32]
0035c9fe: c007       lsls r0, r0, #0x1f
0035ca00: 06d0       beq #0x35ca10
0035ca02: 80b5       push {r7, lr}
0035ca04: 6f46       mov r7, sp
0035ca06: 03a0       adr r0, #0xc
0035ca08: e7f3b7f5   bl #0xb4457a
0035ca0c: bde88040   pop.w {r7, lr}
0035ca10: 0120       movs r0, #1
0035ca12: 7047       bx lr

SLOT 178 OP 4164 WIRE 968 HANDLER 8db5d4
008db5d4: 0120       movs r0, #1
008db5d6: 7047       bx lr

SLOT 179 OP 4165 WIRE 974 HANDLER 8db5d8
008db5d8: b0b5       push {r4, r5, r7, lr}
008db5da: 02af       add r7, sp, #8
008db5dc: 84b0       sub sp, #0x10
008db5de: 017a       ldrb r1, [r0, #8]
008db5e0: 4af22075   movw r5, #0xa720
008db5e4: c0f26515   movt r5, #0x165
008db5e8: c5f8841b   str.w r1, [r5, #0xb84]
008db5ec: 427a       ldrb r2, [r0, #9]
008db5ee: c5f8882b   str.w r2, [r5, #0xb88]
008db5f2: 837a       ldrb r3, [r0, #0xa]
008db5f4: c5f88c3b   str.w r3, [r5, #0xb8c]
008db5f8: 90f80bc0   ldrb.w ip, [r0, #0xb]
008db5fc: c5f890cb   str.w ip, [r5, #0xb90]
008db600: 90f80ce0   ldrb.w lr, [r0, #0xc]
008db604: c5f894eb   str.w lr, [r5, #0xb94]
008db608: 447b       ldrb r4, [r0, #0xd]
008db60a: c5f8984b   str.w r4, [r5, #0xb98]
008db60e: 807b       ldrb r0, [r0, #0xe]
008db610: c5f89c0b   str.w r0, [r5, #0xb9c]
008db614: 43f2a435   movw r5, #0x33a4
008db618: c0f2a515   movt r5, #0x1a5
008db61c: 95f83250   ldrb.w r5, [r5, #0x32]
008db620: ed07       lsls r5, r5, #0x1f
008db622: 09d0       beq #0x8db638
008db624: cde900ce   strd ip, lr, [sp]
008db628: cde90240   strd r4, r0, [sp, #8]
008db62c: 4bf65b00   movw r0, #0xb85b
008db630: c0f2f700   movt r0, #0xf7
008db634: 68f2a1ff   bl #0xb4457a
008db638: 0120       movs r0, #1
008db63a: 04b0       add sp, #0x10
008db63c: b0bd       pop {r4, r5, r7, pc}

SLOT 180 OP 4166 WIRE 984 HANDLER 35ca88
0035ca88: 017a       ldrb r1, [r0, #8]
0035ca8a: 4af22070   movw r0, #0xa720
0035ca8e: c0f26510   movt r0, #0x165
0035ca92: c0f8d410   str.w r1, [r0, #0xd4]
0035ca96: 43f2a430   movw r0, #0x33a4
0035ca9a: c0f2a510   movt r0, #0x1a5
0035ca9e: 90f83200   ldrb.w r0, [r0, #0x32]
0035caa2: c007       lsls r0, r0, #0x1f
0035caa4: 06d0       beq #0x35cab4
0035caa6: 80b5       push {r7, lr}
0035caa8: 6f46       mov r7, sp
0035caaa: 03a0       adr r0, #0xc
0035caac: e7f365f5   bl #0xb4457a
0035cab0: bde88040   pop.w {r7, lr}
0035cab4: 0120       movs r0, #1
0035cab6: 7047       bx lr

SLOT 181 OP 4167 WIRE 990 HANDLER 35cad0
0035cad0: 017a       ldrb r1, [r0, #8]
0035cad2: 4af22070   movw r0, #0xa720
0035cad6: c0f26510   movt r0, #0x165
0035cada: c0f8fc1c   str.w r1, [r0, #0xcfc]
0035cade: 43f2a430   movw r0, #0x33a4
0035cae2: c0f2a510   movt r0, #0x1a5
0035cae6: 90f83200   ldrb.w r0, [r0, #0x32]
0035caea: c007       lsls r0, r0, #0x1f
0035caec: 06d0       beq #0x35cafc
0035caee: 80b5       push {r7, lr}
0035caf0: 6f46       mov r7, sp
0035caf2: 03a0       adr r0, #0xc
0035caf4: e7f341f5   bl #0xb4457a
0035caf8: bde88040   pop.w {r7, lr}
0035cafc: 0120       movs r0, #1
0035cafe: 7047       bx lr

SLOT 182 OP 4169 WIRE 99c HANDLER 35cbe4
0035cbe4: 017a       ldrb r1, [r0, #8]
0035cbe6: 4af22070   movw r0, #0xa720
0035cbea: c0f26510   movt r0, #0x165
0035cbee: c0f81414   str.w r1, [r0, #0x414]
0035cbf2: 43f2a430   movw r0, #0x33a4
0035cbf6: c0f2a510   movt r0, #0x1a5
0035cbfa: 90f83200   ldrb.w r0, [r0, #0x32]
0035cbfe: c007       lsls r0, r0, #0x1f
0035cc00: 06d0       beq #0x35cc10
0035cc02: 80b5       push {r7, lr}
0035cc04: 6f46       mov r7, sp
0035cc06: 03a0       adr r0, #0xc
0035cc08: e7f3b7f4   bl #0xb4457a
0035cc0c: bde88040   pop.w {r7, lr}
0035cc10: 0120       movs r0, #1
0035cc12: 7047       bx lr

SLOT 183 OP 416c WIRE 9a8 HANDLER 35cc40
0035cc40: 017a       ldrb r1, [r0, #8]
0035cc42: 4af22070   movw r0, #0xa720
0035cc46: c0f26510   movt r0, #0x165
0035cc4a: c0f8a01b   str.w r1, [r0, #0xba0]
0035cc4e: 43f2a430   movw r0, #0x33a4
0035cc52: c0f2a510   movt r0, #0x1a5
0035cc56: 90f83200   ldrb.w r0, [r0, #0x32]
0035cc5a: c007       lsls r0, r0, #0x1f
0035cc5c: 06d0       beq #0x35cc6c
0035cc5e: 80b5       push {r7, lr}
0035cc60: 6f46       mov r7, sp
0035cc62: 03a0       adr r0, #0xc
0035cc64: e7f389f4   bl #0xb4457a
0035cc68: bde88040   pop.w {r7, lr}
0035cc6c: 0120       movs r0, #1
0035cc6e: 7047       bx lr

SLOT 184 OP 4170 WIRE 9b4 HANDLER 35594c
0035594c: 017a       ldrb r1, [r0, #8]
0035594e: 4af22070   movw r0, #0xa720
00355952: c0f26510   movt r0, #0x165
00355956: 80f83111   strb.w r1, [r0, #0x131]
0035595a: 43f2a430   movw r0, #0x33a4
0035595e: c0f2a510   movt r0, #0x1a5
00355962: 90f83200   ldrb.w r0, [r0, #0x32]
00355966: c007       lsls r0, r0, #0x1f
00355968: 06d0       beq #0x355978
0035596a: 80b5       push {r7, lr}
0035596c: 6f46       mov r7, sp
0035596e: 03a0       adr r0, #0xc
00355970: eef303f6   bl #0xb4457a
00355974: bde88040   pop.w {r7, lr}
00355978: 0120       movs r0, #1
0035597a: 7047       bx lr

SLOT 185 OP 4172 WIRE 9c0 HANDLER 8daa9c
008daa9c: 0120       movs r0, #1
008daa9e: 7047       bx lr

SLOT 186 OP 4173 WIRE 9d0 HANDLER 8daaa0
008daaa0: 0120       movs r0, #1
008daaa2: 7047       bx lr

SLOT 187 OP 4174 WIRE 9dc HANDLER 35ca3c
0035ca3c: 017a       ldrb r1, [r0, #8]
0035ca3e: 4af22070   movw r0, #0xa720
0035ca42: c0f26510   movt r0, #0x165
0035ca46: c0f8a41b   str.w r1, [r0, #0xba4]
0035ca4a: 43f2a430   movw r0, #0x33a4
0035ca4e: c0f2a510   movt r0, #0x1a5
0035ca52: 90f83200   ldrb.w r0, [r0, #0x32]
0035ca56: c007       lsls r0, r0, #0x1f
0035ca58: 06d0       beq #0x35ca68
0035ca5a: 80b5       push {r7, lr}
0035ca5c: 6f46       mov r7, sp
0035ca5e: 03a0       adr r0, #0xc
0035ca60: e7f38bf5   bl #0xb4457a
0035ca64: bde88040   pop.w {r7, lr}
0035ca68: 0120       movs r0, #1
0035ca6a: 7047       bx lr

SLOT 188 OP 4176 WIRE 9e8 HANDLER 35cd38
0035cd38: d0b5       push {r4, r6, r7, lr}
0035cd3a: 02af       add r7, sp, #8
0035cd3c: 84b0       sub sp, #0x10
0035cd3e: 017a       ldrb r1, [r0, #8]
0035cd40: 4af22074   movw r4, #0xa720
0035cd44: c0f26514   movt r4, #0x165
0035cd48: c4f8a01c   str.w r1, [r4, #0xca0]
0035cd4c: 427a       ldrb r2, [r0, #9]
0035cd4e: c4f8a42c   str.w r2, [r4, #0xca4]
0035cd52: 837a       ldrb r3, [r0, #0xa]
0035cd54: c4f8a83c   str.w r3, [r4, #0xca8]
0035cd58: 90f80bc0   ldrb.w ip, [r0, #0xb]
0035cd5c: c4f8accc   str.w ip, [r4, #0xcac]
0035cd60: 90f80ce0   ldrb.w lr, [r0, #0xc]
0035cd64: c4f8b0ec   str.w lr, [r4, #0xcb0]
0035cd68: 407b       ldrb r0, [r0, #0xd]
0035cd6a: c4f8b40c   str.w r0, [r4, #0xcb4]
0035cd6e: 43f2a434   movw r4, #0x33a4
0035cd72: c0f2a514   movt r4, #0x1a5
0035cd76: 94f83240   ldrb.w r4, [r4, #0x32]
0035cd7a: e407       lsls r4, r4, #0x1f
0035cd7c: 05d0       beq #0x35cd8a
0035cd7e: cde900ce   strd ip, lr, [sp]
0035cd82: 0290       str r0, [sp, #8]
0035cd84: 02a0       adr r0, #8
0035cd86: e7f3f8f3   bl #0xb4457a
0035cd8a: 0120       movs r0, #1
0035cd8c: 04b0       add sp, #0x10
0035cd8e: d0bd       pop {r4, r6, r7, pc}

SLOT 189 OP 4177 WIRE 9f8 HANDLER 35cdc8
0035cdc8: 017a       ldrb r1, [r0, #8]
0035cdca: 4af22070   movw r0, #0xa720
0035cdce: c0f26510   movt r0, #0x165
0035cdd2: c0f8c411   str.w r1, [r0, #0x1c4]
0035cdd6: 43f2a430   movw r0, #0x33a4
0035cdda: c0f2a510   movt r0, #0x1a5
0035cdde: 90f83200   ldrb.w r0, [r0, #0x32]
0035cde2: c007       lsls r0, r0, #0x1f
0035cde4: 06d0       beq #0x35cdf4
0035cde6: 80b5       push {r7, lr}
0035cde8: 6f46       mov r7, sp
0035cdea: 03a0       adr r0, #0xc
0035cdec: e7f3c5f3   bl #0xb4457a
0035cdf0: bde88040   pop.w {r7, lr}
0035cdf4: 0120       movs r0, #1
0035cdf6: 7047       bx lr
