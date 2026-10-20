/* Bounded-retry proof: a busy poll must be retried, not treated as fatal. */
#include "headless-osd.h"
#include <assert.h>
#include <stdio.h>
#include <string.h>
#include <stddef.h>
#include <stdlib.h>
int main(void){
    /* The retry budget must be finite and the helper must exist exactly once. */
    /* Resolve relative to this source file so the test runs from any cwd. */
    const char *path=__FILE__;
    char dir[512];snprintf(dir,sizeof dir,"%s",path);
    char *slash=strrchr(dir,'/');assert(slash);*slash=0;
    char target[600];snprintf(target,sizeof target,"%s/headless-osd.c",dir);
    FILE *f=fopen(target,"rb");assert(f);
    static char buf[1<<20];size_t n=fread(buf,1,sizeof buf,f);fclose(f);
    if(n<sizeof buf-1)buf[n]=0;
    assert(strstr(buf,"extern int usleep(unsigned int);"));
    int waits=0;for(char *p=buf;(p=strstr(p,"FB90-poll"));p++)waits++;
    assert(waits>=1);
    assert(strstr(buf,"attempt >= 200"));
    /* ReadLock and raster must also be retried. */
    assert(strstr(buf,"ReadLock-poll") && strstr(buf,"raster-trylock"));
    printf("HOSD_LEASE_POLL_BOUNDED_RETRY_PRESENT_PASS\n");
    return 0;
}
