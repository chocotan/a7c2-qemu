unsigned long mpr::stillrecord::_write_async_and_sidb_update(void *a0,int a1,long a2,int a3)
{
  unsigned long *v1; // x6
  unsigned short v2; // tmp
  int v3; // stack - 0x550 | stack - 0x5d0 | w2 | w26
  unsigned int v4; // w1
  unsigned int v5; // w4
  char v6; // w1
  bool v7; // tmp
  unsigned long *v8; // stack - 0x508 | x0
  unsigned short v9; // stack - 0x560
  char v10 [4]; // stack - 0x4ec
  int v11 [4]; // stack - 0x588 | stack - 0x590
  void *v12; // stack - 0x580 | stack - 0x5a0 | x0
  unsigned long v13; // stack - 0x4f8
  unsigned long v14 [24]; // stack - 0xd8
  unsigned long v15; // stack - 0x4fc | stack - 0x500 | w0 | w19
  unsigned int v16; // stack - 0x500 | w0
  int v17; // stack - 0x4f8 | stack - 0x554 | stack - 0x5d0 | w0 | w1 | w23 | w25 | w27
  void *v18; // stack - 0x5a0 | x0
  int *v19; // x0 | x21
  void *v20; // x0 | x22
  unsigned long v21; // x2
  unsigned long v22; // x1 | x2
  unsigned int v23; // stack - 0x18 | w3
  long v24; // x5
  char v25; // stack - 0x5d0 | stack - 0x5d8 | w0 | w6
  char *v26; // stack - 0x5e8 | x26 | x7
  int v27; // stack - 0x4fc | stack - 0x550 | stack - 0x554 | stack - 0x5a8 | stack - 0x5c8 | w0 | w21 | w5
  unsigned long v28; // x21 | x27
  char *v29; // stack - 0x5d8 | x0 | x23
  long v30; // x25
  char *v31; // x26 | x7
  int v32; // stack - 0xdc | w27 | w3
  unsigned long v33; // x25 | x27
  int *v34; // stack - 0x5b0 | stack - 0x5e0 | x0 | x28
  void *v35; // x28
  char *v36; // stack - 0x5d8 | x0 | x23
  int v37; // stack - 0x5cc | w0
  void *v38; // stack - 0x598 | stack - 0x5c8 | x0 | x19
  int *v39; // stack - 0x5b0 | stack - 0x5e0 | x0 | x28
  void *v40; // stack - 0x598 | x0 | x19
  long v41; // stack - 0x578 | x0
  long v42; // stack - 0x570 | x0
  long v43; // stack - 0x568 | x0
  unsigned short v44; // stack - 0x55e
  unsigned int v45; // stack - 0x55c | w0
  int v46; // stack - 0x558 | w0 | w27
  int v47; // stack - 0x4fc | stack - 0x554 | stack - 0x5a8 | w0 | w21 | w23 | w27
  int v48; // stack - 0x550 | stack - 0x5c8 | stack - 0x5d0 | w0 | w2 | w5
  unsigned long v49; // stack - 0x54c | x2
  unsigned long v50; // stack - 0x544 | x3
  unsigned long v51; // stack - 0x53c | x0
  unsigned long v52; // stack - 0x534 | x1
  unsigned long v53; // stack - 0x52c | x2
  unsigned long v54; // stack - 0x524 | x3
  unsigned long v55; // stack - 0x51c | x0
  unsigned long v56; // stack - 0x514 | x1
  unsigned int v57; // stack - 0x50c | w0
  unsigned long v58; // stack - 0x4f0
  unsigned long v59; // stack - 0x4e8
  unsigned long v60; // stack - 0x4e0
  unsigned long v61; // stack - 0x4d8
  unsigned long v62; // stack - 0x4d0
  unsigned int v63; // stack - 0xf8
  unsigned short v64; // stack - 0xf0 | stack - 0xf4 | w3
  unsigned short v65; // stack - 0xee | stack - 0xf2 | w0
  unsigned short v66; // stack - 0xf0 | stack - 0xf4 | w3
  unsigned short v67; // stack - 0xee | stack - 0xf2 | w0
  unsigned short v68; // stack - 0xec
  unsigned short v69; // stack - 0xea
  short v70; // stack - 0xe4 | stack - 0xe8 | w1
  unsigned short v71; // stack - 0xe6
  short v72; // stack - 0xe4 | stack - 0xe8 | w1
  unsigned short v73; // stack - 0xe2
  unsigned short v74; // stack - 0xe0
  int v75; // stack - 0xdc | w27 | w3
  unsigned int v76; // stack - 0x18 | w3
  void *v77; // stack - 0x10
  void *v78; // stack - 0x8 | x0 | x22
  
  v8 = (unsigned long *)0x150002120;
  *(unsigned int *)&v15 = osal_thread_id();
  v13 = CONCAT44((int)a2,a1);
  ((unsigned int *)&v15)[1] = (int)a0;
  sub_df8d4(&v8,0x18);
  v11[0] = 0;
  v11[1] = 0;
  v11[2] = 0;
  v11[3] = 0;
  v18 = calloc(4,0x15f0);
  if (!v18)
    __assert_fail("p_tmpBuffer!=NULL","integRecordStill.cpp",0xbf5,"int mpr::stillrecord::_write_async_and_sidb_update(mpr::recordStillParam_t*, uint32_t, libstill*, uint32_t)"); // no-return
  v12 = v18;
  v41 = (long)v18 + 0x15f0;
  v31 = &((char *)a0)[0x214];
  v42 = (long)v18 + 0x2be0;
  v19 = &((int *)a0)[0x4c];
  v30 = 0;
  v43 = (long)v18 + 0x41d0;
  v8 = (unsigned long *)0x3db082120;
  v15 = CONCAT44(((unsigned int *)&v15)[1],osal_thread_id());
  sub_df8d4(&v8,0xc);
  do {
    v25 = 1;
    v17 = v30;
    v8 = NULL;
    v15 = 0;
    v27 = 0;
    v13 = 0;
    v58 = 0;
    v59 = 0;
    v60 = 0;
    v61 = 0;
    v62 = 0;
    v7 = 0;
    v26 = v31;
    v28 = 0;
    v34 = &((int *)a0)[0x7d];
    do {
      v33 = v28;
      if ((v34[6] != -1) && (((char *)v34)[v30 * 0x106 + 0x48])) {
        v9 = 0x2120;
        v45 = 1;
        v44 = 0xdb09;
        v46 = osal_thread_id();
        v49 &= 0xffffffff00000000;
        v47 = v17;
        v48 = v27;
        sub_df8d4(&v9,0x18);
        v33 = (int)v28 + 1;
        v22 = *(unsigned long *)&v34[2];
        if (!v26[0x24])
          v25 = 0;
        (&v8)[v28 * 4] = *(unsigned long **)v34;
        (&v15)[v28 * 4] = v22;
        v22 = *(unsigned long *)&v34[6];
        (&v13)[v28 * 4] = *(unsigned long *)&v34[4];
        *(unsigned long *)&(&Stackfffffffffffffb10)[v28 * 0x20] = v22;
        v10[v28 * 0x20] = *v26;
        v11[v30] = v27;
        v7 = 1;
      }
      v27 += 1;
      v34 = &v34[0x162];
      v26 = &v26[0x588];
      v28 = v33;
    } while (v27 != 2);
    if (v7) {
      v9 = 0x2120;
      v34 = (&v12)[v30];
      *v34 = v17;
      v45 = 1;
      v44 = 0xdb10;
      v46 = osal_thread_id();
      v48 = *v34;
      v49 &= 0xffffffff00000000;
      v47 = v17;
      sub_df8d4(&v9,0x18);
      v9 = 0x2120;
      v34[4] = *v19;
      v45 = 1;
      v44 = 0xdb11;
      v46 = osal_thread_id();
      v47 = *v19;
      v49 &= 0xffffffff00000000;
      v48 = v34[4];
      sub_df8d4(&v9,0x18);
      v34[5] = 0;
      v27 = ((int *)a0)[0x4b];
      ((char *)v34)[0x19] = v25;
      *(bool *)&v34[6] = v27 == 2;
      ((char *)v34)[0x1a] = v31[-0xd0];
      v25 = v31[-0xcc];
      v34[8] = v33;
      ((char *)v34)[0x1b] = v25;
      for (v24 = 0; v33 << 5 != v24; v24 = v24 + 0x20) {
        v1 = (unsigned long *)((long)v34 + v24 + 0x24);
        v22 = *(unsigned long *)((long)&v15 + v24);
        *v1 = *(unsigned long *)((long)&v8 + v24);
        v1[1] = v22;
        v22 = *(unsigned long *)&(&Stackfffffffffffffb10)[v24];
        v1[2] = *(unsigned long *)((long)&v13 + v24);
        v1[3] = v22;
      }
      *(char *)&v34[0x19] = ((char *)a0)[0xde];
      v34[0x574] = a3;
      *(void **)&v34[0x576] = _write_db;
    }
    v30 += 1;
    v31 = &v31[1];
    v19 = &v19[1];
  } while (v30 != 4);
  v28 = 0;
  v8 = (unsigned long *)0x3db142120;
  v16 = osal_thread_id();
  v15 = CONCAT44(((unsigned int *)&v15)[1],v16);
  sub_df8d4(&v8,0xc);
  v37 = 0;
  v36 = &((char *)a0)[0x23c];
  v40 = a0;
  while( true ) {
    v33 = 0;
    v7 = 1;
    v27 = v28;
    v38 = v40;
    v29 = v36;
    v39 = &((int *)a0)[0x7d];
    do {
      v17 = v33;
      if ((v39[6] != -1) && (*v29)) {
        v3 = *v39;
        v8 = (unsigned long *)0x1db152120;
        v15 = CONCAT44(v27,osal_thread_id());
        v13 = v33 & 0xffffffff;
        sub_df8d4(&v8,0x18);
        sub_95048(0x2120,0xffffdb1c,v29);
        if (a1 == v17 & ((unsigned char *)v39)[v28 + 0x44]) { // branch-flip
          v8 = &v13;
          sub_df468(&v8,v29,&v29[strlen(v29)]);
          mpr::ClearStillCacheForPseudoStill(v33 & 0xffffffff);
          mpr::SetStillCacheForPseudoStill(v33 & 0xffffffff,&v8);
          if (v11[v28] == v17)
            mpr::stillrecord::SetWriteDbParam(a0,v28 & 0xffffffff,(&v12)[v28]);
          std::__cxx11::basic_string::_M_dispose(&v8);
        }
        else {
          if ((v7) && (((int *)v38)[0x8a]))
            mpr::fs::MkMultiDir(v29,((int *)v38)[0x8a],1,0);
          memset(&v8,0,0x508);
          strncpy((char *)&v8,v29,0x7f);
          v64 = 0;
          v63 = 0x206;
          if (0x7bc <= ((short *)a0)[1])
            v64 = ((unsigned char *)a0)[5] & 0x1f | (((short *)a0)[1] + -0x7bc) * 0x200 | ((short)((char *)a0)[4] & 0xfU) << 5;
          v6 = ((char *)a0)[8];
          v32 = 0;
          v2 = -((short)v6 & 1U);
          if ('\0' <= v6)
            v2 = (short)v6 & 1U;
          v65 = (short)((char *)a0)[6] << 0xb | (unsigned short)((unsigned long)v6 >> 1) & 0x1f | ((short)((char *)a0)[7] & 0x3fU) << 5;
          v70 = ((short *)a0)[5] / 10 + v2 * 100;
          v68 = 0xffff;
          v69 = 0xffff;
          v71 = 0xffff;
          v73 = 0xffff;
          v74 = 0xffff;
          v4 = *(unsigned int *)(a2 + 0x11f0);
          v7 = 0;
          v23 = v76;
          for (v19 = (int *)(a2 + 0x1200); (int *)(a2 + v4 * 0x30UL + 0x1200) != v19; v19 = &v19[0xc]) {
            v5 = *v19;
            if (v5) {
              v21 = v23;
              v32 += v5;
              v23 += 1;
              v14[v21 * 3] = *(unsigned long *)&v19[4];
              v14[v21 * 3 + 1] = *(unsigned long *)&v19[2];
              v14[v21 * 3 + 2] = v5 + 0xfff & 0xfffff000UL;
              v7 = 1;
            }
          }
          if (v7)
            v76 = v23;
          v77 = fsys_callbackfunc;
          v66 = v64;
          v67 = v65;
          v72 = v70;
          v75 = v32;
          v20 = malloc(0x1680);
          v78 = v20;
          if (a1 == v17) {
            if (v3 != 1) { // branch-flip
              if (v3 != 2) { // branch-flip
                if (v3 != 4) goto label_f2030;
                v22 = 0x50;
              }
              else {
                v22 = 0x54;
              }
            }
            else {
              v22 = 0x4c;
            }
            sidb::PartialUpdate(0xffffffff,((unsigned int *)v40)[0x4c],v22,v32,1,0);
          }
label_f2030:
          v45 = 3;
          v9 = 0x2120;
          if (v11[v28] != v17) { // branch-flip
            v44 = 0xdb1f;
            v46 = osal_thread_id();
            sub_df8d4(&v9,0xc);
            ((char *)v20)[0x15e4] = 0;
          }
          else {
            v44 = 0xdb1e;
            v46 = osal_thread_id();
            sub_df8d4(&v9,0xc);
            memcpy(v20,(&v12)[v28],0x15e0);
            ((char *)v20)[0x15e4] = 1;
          }
          ((unsigned int *)v20)[0x57a] = ((unsigned int *)v40)[0x57];
          ((int *)v20)[0x578] = v27;
          ((unsigned int *)v20)[0x57b] = *(unsigned int *)((long)a0 + v33 * 4 + 0x1ec);
          strncpy(&((char *)v20)[0x15f0],v29,0x7f);
          ((void **)v20)[0x2ce] = a0;
          ((int *)v20)[0x59e] = a1;
          if (a1 != v17) // branch-flip
            free(v20); // crossjump-dupe
          else {
            v17 = Fsys_WriteDirectFileAsyncV2(&v8);
            v37 += 1;
            v9 = 0x2120;
            v45 = 2;
            v44 = 0xdbff;
            v46 = osal_thread_id();
            v47 = v17;
            sub_df8d4(&v9,0x10);
            if (v17) {
              v9 = 0x2120;
              v3 = v11[v28];
              v44 = 0x5020;
              v45 = 1;
              v46 = v17;
              v49 = CONCAT44(((unsigned int *)&v49)[1],a1);
              v47 = v27;
              v48 = v3;
              sub_df8d4(&v9,0x18);
              v35 = (&v12)[v28];
              ((int *)v35)[5] = v17;
              if (v3 == a1) {
                mpr::evtStillWriteCountdownParam::evtStillWriteCountdownParam(&v9);
                v46 = *(int *)&_ZN3mpr10g_msidconvE[v28 * 0x80 + 0x7c];
                v47 = ((int *)v35)[4];
                v48 = ((int *)v35)[8];
                v49 = *(unsigned long *)((long)v35 + 0x24);
                v50 = *(unsigned long *)((long)v35 + 0x2c);
                v51 = *(unsigned long *)((long)v35 + 0x34);
                v52 = *(unsigned long *)((long)v35 + 0x3c);
                v53 = *(unsigned long *)((long)v35 + 0x44);
                v54 = *(unsigned long *)((long)v35 + 0x4c);
                v55 = *(unsigned long *)((long)v35 + 0x54);
                v56 = *(unsigned long *)((long)v35 + 0x5c);
                v57 = ((unsigned int *)v35)[5];
                v45 = ((unsigned int *)v35)[0x574];
                mpr::stillrecord::SetEvtStillWriteCountdownParam(a0,v28 & 0xffffffff,0x100d,&v9,0x58);
                mpr::stillrecord::SetWriteDbParam(a0,v28 & 0xffffffff,v35);
              }
              free(v20);
            }
          }
          v7 = 0;
        }
      }
      v33 += 1;
      v29 = &v29[0x588];
      v39 = &v39[0x162];
      v38 = &((char *)v38)[0x588];
    } while (v33 != 2);
    v28 += 1;
    v36 = &v36[0x106];
    v40 = &((char *)v40)[4];
    if (v28 == 4) {
      mpr::stillrecord::SetFsysWriteRequestCount(a0,a1,v37);
      free(v18);
      v8 = (unsigned long *)0x150302120;
      v15 = CONCAT44((int)a0,osal_thread_id());
      v13 = CONCAT44((int)a2,a1);
      sub_df8d4(&v8,0x18);
      return 0;
    }
  }
}
