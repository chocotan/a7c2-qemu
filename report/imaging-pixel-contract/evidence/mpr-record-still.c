unsigned long mpr::RecordStill(unsigned long *a0,void *a1)
{
  unsigned long v1; // x5
  unsigned int v2; // stack - 0x654 | w0 | w2
  int v3; // w8
  unsigned int v4; // w5
  unsigned short v5 [2]; // stack - 0x656 | stack - 0x658
  unsigned long v6; // stack - 0x668 | x0
  unsigned long v7; // stack - 0x678 | x0
  unsigned long v8; // stack - 0x688 | x0
  unsigned long v9 [6]; // stack - 0x650
  char v10 [384]; // stack - 0x5f4
  char v11 [452]; // stack - 0x1d4
  char v12 [672]; // stack - 0x474
  unsigned long v13; // x0 | x26
  long v14; // x0 | x3
  unsigned long v15; // x0
  unsigned int *v16; // x0
  void *v17; // x1
  char *v18; // x1
  unsigned int *v19; // x3
  unsigned long *v20; // x0 | x19
  long v21; // stack - 0x10 | x20
  unsigned long v22; // x23
  unsigned long v23; // stack - 0x680 | x0
  unsigned long v24; // stack - 0x670 | x0
  unsigned long v25; // stack - 0x660 | x0
  char v26; // stack - 0x654
  char v27; // stack - 0x653
  char v28; // stack - 0x652
  char v29; // stack - 0x651
  unsigned int v30; // stack - 0x620 | w0
  unsigned long v31; // stack - 0x61c | x2
  unsigned long v32; // stack - 0x614 | x3
  unsigned long v33; // stack - 0x60c | x0
  unsigned long v34; // stack - 0x604 | x1
  unsigned int v35; // stack - 0x5fc | w0
  unsigned int v36; // stack - 0x5f8 | w0
  long v37; // stack - 0x10 | x20
  void *v38; // stack - 0x8
  
  sub_df8d4(a0,0x150);
  mpr::recordStillInParam::DbgPrint(a0);
  pthread_mutex_lock(_ZN3mpr15g_integApiMutexE);
  if (std::operator-(0x3817e8,0x3817c8)) { // branch-flip
    std::_Deque_iterator::_Deque_iterator(v5,0x3817c8);
    v21 = *(long *)CONCAT17(v29,CONCAT16(v28,CONCAT15(v27,CONCAT14(v26,CONCAT22(v5[1],v5[0])))));
  }
  else {
    v27 = 0;
    v21 = 0;
    v26 = 4;
    v28 = 0;
    v5[0] = 0x2120;
    v29 = 0;
    v5[1] = 0x3010;
    sub_df8d4(v5,8);
  }
  v13 = mpr::stillrecord::_check_error(v21,a0);
  if ((int)v13) { // branch-flip
label_eb364:
    v8 = a0[1];
    v7 = a0[3];
    v6 = a0[5];
    v23 = a0[2];
    v24 = a0[4];
    v25 = a0[6];
    memset(v5,0,0x540);
    mpr::stillrecord::_free(a0,v21,&v8,&v7,&v6,v5,0);
    if (a1)
      ((unsigned int *)a1)[1] = 0;
    v13 = 3;
    pthread_mutex_unlock(_ZN3mpr15g_integApiMutexE);
    mpr::recordStillOutParam::DbgPrint(a1);
    sub_df8d4(a1,0x28);
    std::deque::pop_front(_ZN3mpr4fifoE);
  }
  else {
    if (dat_3b33a8)
      stillutil::dummy::export_stillinfo(a0,v21);
    if (*(int *)(v21 + 0xc) != 1) // branch-flip
      v13 = mpr::stillrecord::_record_still(a0,v21);
    else {
      v38 = _record_trimming;
      v5[1] = (unsigned short)((unsigned int)((unsigned int *)a0)[1] >> 0x10);
      v5[0] = (unsigned short)((unsigned int *)a0)[1];
      v2 = ((unsigned int *)a0)[0x11];
      v29 = (char)(v2 >> 0x18);
      v28 = (char)(v2 >> 0x10);
      v27 = (char)(v2 >> 8);
      v26 = (char)v2;
      if (!v2) {
        v6 = 0x430302120;
        sub_df8d4(&v6,8);
        goto label_eb364;
      }
      for (v14 = 0; v14 + 0x10 != v2 * 0x10UL + 0x10; v14 = v14 + 0x10) {
        v20 = (unsigned long *)((long)a0 + v14 + 0x48);
        v1 = v20[1];
        *(unsigned long *)((long)v5 + v14 + 8) = *v20;
        *(unsigned long *)((long)v9 + v14 + 8) = v1;
      }
      v30 = *(unsigned int *)&a0[0xf];
      v22 = 0;
      v31 = *(unsigned long *)((long)a0 + 0x8c);
      v32 = *(unsigned long *)((long)a0 + 0x94);
      v33 = *(unsigned long *)((long)a0 + 0x9c);
      v34 = *(unsigned long *)((long)a0 + 0xa4);
      v35 = ((unsigned int *)a0)[0x2b];
      v36 = *(unsigned int *)&a0[0x16];
      do {
        v20 = &a0[1];
        v17 = (void *)*v20;
        if (v17) // branch-flip
          memcpy(&v10[v22 * 0xc0],v17,0xc0);
        else {
          memset(&v10[(v22 & 0xffffffff) * 0xc0],0,0xc0);
        }
        if ((void *)a0[5]) // branch-flip
          memcpy(&v11[v22 * 0xe0],(void *)a0[5],0xe0);
        else {
          memset(&v11[(v22 & 0xffffffff) * 0xe0],0,0xe0);
        }
        v15 = v22 & 0xffffffff;
        v22 += 1;
        memset(&v12[v15 * 0x150],0,0x150);
        a0 = v20;
      } while (v22 != 2);
      v37 = v21;
      execqueue::exec(_ZN3mpr11stillrecord18make_header_threadE,v5);
    }
    v13 &= 0xffffffff;
    v18 = (char *)(v21 + 0x23c);
    v19 = (unsigned int *)(v21 + 0x130);
    v3 = *(int *)(v21 + 0x20c);
    ((unsigned int *)a1)[1] = 0;
    v16 = (unsigned int *)0x374d2c;
    do {
      if (((v3 != -1) && (*v18)) || ((*(int *)(v21 + 0x794) != -1 && (v18[0x588])))) {
        v2 = ((unsigned int *)a1)[1];
        v4 = *v19;
        *(unsigned int *)((long)a1 + v2 * 8UL + 8) = *v16;
        *(unsigned int *)((long)a1 + v2 * 8UL + 0xc) = v4;
        ((int *)a1)[1] = v2 + 1;
      }
      v18 = &v18[0x106];
      v16 = &v16[0x20];
      v19 = &v19[1];
    } while ((char *)(v21 + 0x654) != v18);
    std::deque::pop_front(_ZN3mpr4fifoE);
    pthread_mutex_unlock(_ZN3mpr15g_integApiMutexE);
    mpr::recordStillOutParam::DbgPrint(a1);
    sub_df8d4(a1,0x28);
  }
  return v13;
}
