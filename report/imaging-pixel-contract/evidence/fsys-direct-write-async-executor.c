void sub_2f7e4(char a0,unsigned long a1,char *a2,unsigned int a3,unsigned short a4)
{
  unsigned int v1; // stack - 0x4f8 | w25
  unsigned short v2 [4]; // stack - 0x5c0 | w24 | w4
  char v3 [1240]; // stack - 0x4dc
  long v4; // stack - 0x5e8 | x0
  unsigned long v5; // stack - 0x5e0 | x0
  unsigned long v6; // stack - 0x5d8 | x0
  unsigned long v7; // stack - 0x5d0 | stack - 0x5e0 | x0
  char v8 [192]; // stack - 0x5b8
  int v9; // w0 | w23
  char *v10; // x20 | x28
  unsigned int v11; // w26
  unsigned long v12; // stack - 0x5c8 | stack - 0x5d8 | x0
  unsigned int v13; // stack - 0x4f8 | w25
  unsigned long v14; // stack - 0x4f0 | x0
  unsigned long v15; // stack - 0x4e8 | x0
  int v16; // stack - 0x4e0 | w0 | w23
  char v17; // stack - 0x4 | w0 | w21
  
  v5 = 0;
  v6 = 0;
  memset(v2,0,0x5c0);
  v14 = *(unsigned long *)&a2[0x4f8];
  v15 = *(unsigned long *)&a2[0x500];
  v2[0] = a4;
  v17 = a0;
  strncpy(v3,a2,0x40e);
  v9 = sub_2c534(a2,&v4);
  fsysDepMCmn_StartIOQueue((unsigned char)a0,1,&v5);
  if (0 <= v9) { // branch-flip
    if (9 <= *(unsigned int *)&a2[0x4f0]) // branch-flip
      v16 = -0x7fffffd0;
    else {
      v11 = 0;
      for (v10 = &a2[0x430]; (v1 = *(unsigned int *)&a2[0x4f0], v11 < v1 && (*(long *)&v10[8])); v10 = &v10[0x18]) {
        v11 += 1;
        fsysDep_SetStreamArea(*(long *)&v10[8],*(unsigned long *)&v10[0x10],*(unsigned long *)v10);
      }
      memcpy(v8,&a2[0x430],v1 * 0x18UL);
      v13 = v1;
      v16 = sub_2f5ac(v4,a4,a2,v3,1);
    }
  }
  else {
    v16 = v9;
  }
  fsysDepMCmn_RegistIOQueueCallback((unsigned char)a0,0x2d1d8,v2,0x5c0);
  fsysDepMCmn_EndIOQueue((unsigned char)a0,v5,&v6);
  if (0 <= v9)
    sub_2d94c(v4 + 0x65ac,v9);
  v7 = v5;
  v12 = v6;
  fsysDepAsync_DriveQueueRequest((unsigned char)a0,1,0x2d26c,&v7,0x10,a3,a4);
  return;
}
