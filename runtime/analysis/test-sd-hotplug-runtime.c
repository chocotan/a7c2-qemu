#define _GNU_SOURCE
#include "sd-hotplug-runtime.h"
#include <assert.h>
#include <fcntl.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/stat.h>
#include <unistd.h>

struct fixture {sd_backing backing;unsigned sends,flushes;int flush_rc;sd_delivery delivery;uint64_t generation;};
static struct fixture f;
static bool valid(void *context,const sd_backing *b){
    assert(context==&f && b->fd==f.backing.fd);
    struct stat st;return !fstat(b->fd,&st) && (uint64_t)st.st_ino==b->identity && (uint64_t)st.st_size==b->size;
}
static int flush(void *context,uint64_t generation,uint32_t drive){
    assert(context==&f && generation>=2 && drive=='A');f.flushes++;return f.flush_rc;
}
static sd_send_result notify(void *context,uint64_t generation,sd_operation op,const uint8_t bytes[7]){
    assert(context==&f && generation>=2);f.sends++;f.generation=generation;
    assert(bytes[0]==2 && bytes[3]==2 && bytes[1]==0 && bytes[2]==0 && bytes[4]==0 && bytes[6]==0);
    assert(bytes[5]==(op==SD_EJECT?0x10:0x12));
    return (sd_send_result){f.delivery,false};
}
static void request(unsigned sequence,unsigned operation){
    FILE *out=fopen(SD_HOTPLUG_DIRECTORY "/sd-hotplug.request","w");assert(out);
    assert(fprintf(out,"1 %u %u\n",sequence,operation)>0 && !fclose(out));
    native_sd_hotplug_poll();
}
static int state_is(const char *state){
    char line[512];FILE *in=fopen(SD_HOTPLUG_DIRECTORY "/sd-hotplug.state","r");
    if(!in)return 0;
    assert(fgets(line,sizeof line,in));fclose(in);
    char expected[80];snprintf(expected,sizeof expected,"state=%s ",state);return strstr(line,expected)!=0;
}
int main(int argc,char **argv){
    assert(argc==2);assert(!setenv("A7C2_SD_HOTPLUG","1",1));
    char path[]=SD_HOTPLUG_DIRECTORY "/backing-XXXXXX";int fd=mkstemp(path);assert(fd>=0 && !unlink(path) && !ftruncate(fd,4096));
    struct stat st;assert(!fstat(fd,&st));f.backing=(sd_backing){fd,st.st_ino,4096};
    f.delivery=SD_SENT;
    struct native_sd_hotplug_io io={&f,valid,flush,notify};
    assert(!native_sd_hotplug_configure(&f.backing,&io));
    if(!strcmp(argv[1],"unbound")){
        request(1,SD_EJECT);assert(!f.sends && state_is("unavailable"));close(fd);return 0;
    }
    native_sd_hotplug_fsys(SD_MOUNT,'A',0,true,true);native_sd_hotplug_poll();
    assert(state_is("present") && native_sd_hotplug_port()==2);
    if(!strcmp(argv[1],"flush-fail")){
        f.flush_rc=-5;request(1,SD_EJECT);assert(f.flushes==1 && !f.sends && state_is("present"));close(fd);return 0;
    }
    if(!strcmp(argv[1],"not-sent"))f.delivery=SD_NOT_SENT;
    if(!strcmp(argv[1],"uncertain"))f.delivery=SD_DELIVERY_UNCERTAIN;
    request(1,SD_EJECT);assert(f.sends==1 && f.flushes==1);
    if(f.delivery==SD_NOT_SENT){assert(state_is("present") && native_sd_hotplug_port()==2);close(fd);return 0;}
    if(f.delivery==SD_DELIVERY_UNCERTAIN){assert(state_is("uncertain"));close(fd);return 0;}
    assert(state_is("ejecting") && native_sd_hotplug_port()==0x10);
    if(!strcmp(argv[1],"overrun")){
        native_sd_hotplug_freed(f.generation,0);
        native_sd_hotplug_fsys(SD_UNMOUNT,'A',0,false,true);
        for(unsigned i=0;i<64;i++)native_sd_hotplug_freed(f.generation,0);
        native_sd_hotplug_poll();
        assert(state_is("uncertain") && !native_sd_hotplug_retired());close(fd);return 0;
    }
    if(!strcmp(argv[1],"unrelated")){
        native_sd_hotplug_fsys(SD_UNMOUNT,'B',-5,false,false);
        native_sd_hotplug_fsys(SD_MOUNT,'C',-5,false,false);
        native_sd_hotplug_poll();assert(state_is("ejecting"));
    }
    native_sd_hotplug_freed(f.generation,0);native_sd_hotplug_poll();assert(state_is("ejecting"));
    if(!strcmp(argv[1],"unretired")){
        native_sd_hotplug_fsys(SD_UNMOUNT,'A',0,false,false);native_sd_hotplug_poll();
        assert(state_is("uncertain"));close(fd);return 0;
    }
    native_sd_hotplug_fsys(SD_UNMOUNT,'A',0,false,true);native_sd_hotplug_poll();assert(state_is("absent"));
    request(1,SD_EJECT);assert(f.sends==1);
    request(2,SD_INSERT);assert(f.sends==2 && f.flushes==1 && state_is("inserting"));
    if(!strcmp(argv[1],"stale-fsys")){
        uint64_t old=f.generation-1;
        native_sd_hotplug_fsys_generation(old,SD_MOUNT,'B',-5,true,false);
        native_sd_hotplug_fsys_generation(old,SD_MOUNT,'B',0,true,true);
        native_sd_hotplug_poll();assert(state_is("inserting"));
        native_sd_hotplug_fsys(SD_MOUNT,'C',-5,false,false);
        native_sd_hotplug_poll();assert(state_is("inserting"));
    }
    native_sd_hotplug_fsys(SD_MOUNT,'B',0,true,true);native_sd_hotplug_poll();assert(state_is("inserting"));
    native_sd_hotplug_freed(f.generation-1,0);native_sd_hotplug_poll();assert(state_is("inserting"));
    native_sd_hotplug_freed(f.generation,0);native_sd_hotplug_poll();assert(state_is("present"));
    assert(native_sd_hotplug_port()==0x12);assert(!close(fd));
    puts("PASS: genuine mount, flush, queued free/retirement, insert and stale rejection");return 0;
}
