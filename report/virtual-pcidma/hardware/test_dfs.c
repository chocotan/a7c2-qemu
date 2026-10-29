/* SPDX-License-Identifier: GPL-2.0-or-later */
#include "dfs.h"
#include <assert.h>
#include <stdio.h>

static uint64_t read_reg(struct sony_dfs_selector *s,unsigned int offset)
{
    uint64_t result=~UINT64_C(0);
    assert(!sony_dfs_read(s,offset,4,&result));return result;
}
static void init(struct sony_dfs_selector *s)
{
    sony_dfs_reset(s);assert(!sony_dfs_write(s,4,4,0x101));
    assert(s->initialized && s->phase==SONY_DFS_IDLE && read_reg(s,16)==0);
}
static void submit(struct sony_dfs_selector *s,unsigned int mode)
{
    unsigned int previous=s->current_mode;
    assert(!sony_dfs_write(s,0,4,0x101));
    assert(read_reg(s,0)==0x101 && read_reg(s,16)==previous);
    assert(!(read_reg(s,16)&0x100)); /* pre-submit busy must remain clear */
    assert(!sony_dfs_complete(s));
    assert(!sony_dfs_write(s,12,4,0x100|mode));
    assert(read_reg(s,12)==(0x100|mode) && read_reg(s,16)==previous);
    assert(!sony_dfs_complete(s));
    assert(!sony_dfs_write(s,8,4,1));
    assert(s->phase==SONY_DFS_BUSY && read_reg(s,0)==0x101);
    assert(read_reg(s,16)==(previous|0x100));
}
static void finish(struct sony_dfs_selector *s,unsigned int mode)
{
    assert(sony_dfs_complete(s)==1);
    assert(read_reg(s,0)==1 && read_reg(s,16)==mode && s->current_mode==mode);
    assert(s->phase==SONY_DFS_COMPLETE && s->completed_generation==s->generation);
    assert(!sony_dfs_complete(s));
}
int main(void)
{
    struct sony_dfs_selector s;
    init(&s);
    for (unsigned int mode=0;mode<7;mode++) {
        submit(&s,mode);finish(&s,mode);
        submit(&s,mode); /* same mode needs another request and consumption */
        assert(s.generation==2*mode+2 && s.completed_generation==2*mode+1);
        finish(&s,mode);
    }
    assert(s.requests==14 && s.completions==14 && !s.faults);
    submit(&s,0);finish(&s,0);submit(&s,5);finish(&s,5);
    assert(s.completions==16);
    assert(!sony_dfs_write(&s,4,4,0x101) && s.current_mode==5 && s.completions==16);

    for (unsigned int kind=0;kind<15;kind++) {
        init(&s);int rc=0;uint64_t result=0;
        switch(kind) {
        case 0:sony_dfs_reset(&s);rc=sony_dfs_write(&s,0,4,0x101);break;
        case 1:rc=sony_dfs_write(&s,4,4,0);break;
        case 2:rc=sony_dfs_write(&s,0,1,1);break;
        case 3:rc=sony_dfs_write(&s,1,4,0x101);break;
        case 4:assert(!sony_dfs_write(&s,0,4,0x101));rc=sony_dfs_write(&s,12,4,0x107);break;
        case 5:assert(!sony_dfs_write(&s,0,4,0x101));rc=sony_dfs_write(&s,12,4,1);break;
        case 6:rc=sony_dfs_write(&s,0,4,UINT64_C(0x100000101));break;
        case 7:rc=sony_dfs_write(&s,8,4,1);break;
        case 8:assert(!sony_dfs_write(&s,0,4,0x101));rc=sony_dfs_write(&s,0,4,0x101);break;
        case 9:submit(&s,3);rc=sony_dfs_write(&s,12,4,0x104);break;
        case 10:rc=sony_dfs_write(&s,16,4,0);break;
        case 11:assert(!sony_dfs_write(&s,0,4,0x101));assert(!sony_dfs_write(&s,12,4,0x101));rc=sony_dfs_write(&s,8,4,0);break;
        case 12:submit(&s,4);finish(&s,4);rc=sony_dfs_write(&s,8,4,1);break;
        case 13:rc=sony_dfs_read(&s,16,8,&result);break;
        case 14:rc=sony_dfs_read(&s,20,4,&result);break;
        }
        assert(rc && s.faults && s.phase==SONY_DFS_FAULT);
        assert(!sony_dfs_complete(&s));
        unsigned int completed=s.completions,current=s.current_mode;
        assert(sony_dfs_write(&s,4,4,0x101)); /* init is not fault recovery */
        assert(!sony_dfs_complete(&s) && s.completions==completed && s.current_mode==current);
    }
    init(&s);submit(&s,6);sony_dfs_reset(&s);
    assert(!sony_dfs_complete(&s) && s.phase==SONY_DFS_UNINITIALIZED && !s.generation);
    puts("DFS_SELECTOR_CORE_PASS modes0..6, fresh epochs, pre-submit ordering, fail-stop, reset; clocks not changed");
    return 0;
}
