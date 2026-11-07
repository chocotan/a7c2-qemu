/* Read-only same-process-generation scheduler and blocked thread sampler. */
#define USB_OBSERVE_HOST_TEST
#include "usb-start-observe.c"
#include <dirent.h>
#include <time.h>
static int readtext(const char *path,char *out,size_t n) {
    int fd=open(path,O_RDONLY|O_NOFOLLOW);if(fd<0)return 0;
    ssize_t got=read(fd,out,n-1);close(fd);if(got<0)return 0;out[got]=0;return 1;
}
static uintptr_t measured_base(pid_t pid) {
    char path[80],line[1024];snprintf(path,sizeof path,"/proc/%ld/maps",(long)pid);
    FILE *f=fopen(path,"r");if(!f)return 0;uintptr_t base=0;unsigned matches=0;
    while(fgets(line,sizeof line,f)) {
        unsigned long start,end,offset;char mode[5],file[512];
        if(sscanf(line,"%lx-%lx %4s %lx %*s %*u %511s",&start,&end,mode,&offset,file)==5 && !offset && !strcmp(file,"/usr/lib/appFw.so")) {base=start;matches++;emit(0,"SNAPSHOT_MAP","pid=%ld raw=%s",(long)pid,line);}
    }
    fclose(f);return matches==1?base:0;
}
static void scheduled(uintptr_t object,unsigned index,uintptr_t base) {
    uintptr_t before[2],after[2];unsigned char control[0x1b8],again[0x1b8];
    if(!readmem(object,before,sizeof before)||!readmem(before[1],control,sizeof control)) {emit(1,"SCHEDULED_UNREADABLE","index=%u object=%#lx",index,object);return;}
    uintptr_t run=pointer(before[0]+0x10),token;uint32_t id;memcpy(&id,control+8,4);memcpy(&token,control+0x10,8);
    int stable=readmem(object,after,sizeof after)&&!memcmp(before,after,sizeof before)&&readmem(before[1],again,sizeof again)&&!memcmp(control,again,sizeof control);
    emit(0,"SCHEDULED","role=%s index=%u object=%#lx control=%#lx id=%#x token=%#lx run=%#lx stable=%u msc_run=%u",index?"pending":"active",index,object,before[1],id,token,run>=base?run-base:run,stable,run==base+0x34796b0);
    if(!index) {
        uintptr_t first,last,cap;memcpy(&first,control+0x1a0,8);memcpy(&last,control+0x1a8,8);memcpy(&cap,control+0x1b0,8);
        if(last>=first && cap>=last && last-first<=256*24 && (last-first)%24==0) {
            for(unsigned i=0;i<(last-first)/24 && i<8;i++) {uintptr_t future=pointer(first+i*24);emit(0,"SCHEDULE_DEP","index=%u future=%#lx owner=%#x status=%#x identity_unverified=1",i,future,word(first+i*24+16),word(future+0x10));}
        }else emit(1,"SCHEDULE_DEP_INVALID","first=%#lx last=%#lx capacity=%#lx",first,last,cap);
    }
}
static void scheduler(uintptr_t base) {
    uintptr_t manager=base+0x910a108,group=manager+0x310,head=group+0x10;
    unsigned char before[0x90],after[0x90];
    if(!readmem(group,before,sizeof before)||pointer(group)!=manager||word(group+8)!=0) {emit(1,"SCHED_UNAVAILABLE","base=%#lx group=%#lx",base,group);return;}
    uintptr_t first,last,count,active;memcpy(&first,before+0x10,8);memcpy(&last,before+0x18,8);memcpy(&count,before+0x20,8);memcpy(&active,before+0x88,8);
    emit(0,"SCHED_HEADER","base=%#lx group=0 first=%#lx last=%#lx pending=%lu active=%#lx no_lock=1",base,first,last,count,active);
    if(active)scheduled(active,0,base);
    uintptr_t node=first;unsigned visited=0;
    while(node!=head && visited<256 && visited<count) {
        uintptr_t fields[3],check[3];if(!readmem(node,fields,sizeof fields))break;
        scheduled(fields[2],visited+1,base);
        if(!readmem(node,check,sizeof check)||memcmp(fields,check,sizeof fields)){emit(1,"SCHED_NODE_CHANGED","index=%u",visited);break;}
        node=fields[0];visited++;
    }
    int stable=readmem(group,after,sizeof after)&&!memcmp(before,after,sizeof before);
    emit(0,"SCHED_STABILITY","header_equal=%u visited=%u pending=%lu complete=%u atomic=0",stable,visited,count,node==head && visited==count);
    blob("SCHED_HEADER_FIRST",group,sizeof before);
}
static void threads(pid_t pid) {
    char path[128];snprintf(path,sizeof path,"/proc/%ld/task",(long)pid);DIR *dir=opendir(path);if(!dir)return;
    struct dirent *entry;unsigned visited=0;
    while((entry=readdir(dir)) && visited<192) {
        char *end;long tid=strtol(entry->d_name,&end,10);if(*end||tid<1)continue;visited++;
        char name[64],raw[1024];snprintf(path,sizeof path,"/proc/%ld/task/%ld/comm",(long)pid,tid);if(!readtext(path,name,sizeof name))continue;
        name[strcspn(name,"\n")]=0;
        if(!strstr(name,"Seq")&&!strstr(name,"Usb")&&!strstr(name,"MSC")&&!strstr(name,"Mass")&&!strstr(name,"App")&&!strstr(name,"UPM"))continue;
        for(unsigned i=0;i<3;i++) {
            const char *field=i==0?"wchan":i==1?"stack":"syscall";
            snprintf(path,sizeof path,"/proc/%ld/task/%ld/%s",(long)pid,tid,field);
            if(!readtext(path,raw,sizeof raw)){emit(1,"THREAD_READ_FAILED","target_tid=%ld name=%s field=%s errno=%d",tid,name,field,errno);continue;}
            emit(0,"THREAD","target_tid=%ld name=%s field=%s raw=%s",tid,name,field,raw);
            if(i==2) {
                long number;unsigned long a0,a1,a2,a3,a4,a5,sp,pc;
                if(sscanf(raw,"%ld %lx %lx %lx %lx %lx %lx %lx %lx",&number,&a0,&a1,&a2,&a3,&a4,&a5,&sp,&pc)==9) {emit(0,"THREAD_USER_STACK","target_tid=%ld sp=%#lx pc=%#lx syscall=%ld bytes=512 raw_candidates_only=1",tid,sp,pc,number);blob("THREAD_USER_STACK_BYTES",sp,512);}
            }
        }
    }
    closedir(dir);
}
int main(int argc,char **argv) {
    if(argc!=3)return 64;char *end;long value=strtol(argv[1],&end,10);if(*end||value<2)return 64;
    if(strcmp(argv[2],"before-enter")&&strcmp(argv[2],"after-enter"))return 64;
    logfd=1;pid_t pid=(pid_t)value;uintptr_t base=measured_base(pid);
    if(!base||!identity("/usr/lib/appFw.so",USB_APP_BYTES,"2ea02f7ecbc5bb917316fe8ef4ce5ffd87eb66efaae78ba2ce11420552df539b"))return 79;
    char path[80],stat_before[4096],stat_after[4096];snprintf(path,sizeof path,"/proc/%ld/stat",value);if(!readtext(path,stat_before,sizeof stat_before))return 79;
    char *close=strrchr(stat_before,')');if(!close)return 79;char *p=close+2;unsigned field=3;unsigned long long start=0;
    while(field<22 && (p=strchr(p,' '))){p++;field++;}if(!p||sscanf(p,"%llu",&start)!=1)return 79;
    snprintf(path,sizeof path,"/proc/%ld/mem",value);memfd=open(path,O_RDONLY|O_CLOEXEC);if(memfd<0)return 79;
    struct timespec stamp;clock_gettime(CLOCK_MONOTONIC,&stamp);emit(0,"SNAPSHOT_BEGIN","phase=%s pid=%ld starttime=%llu base=%#lx monotonic=%ld.%09ld",argv[2],value,start,base,stamp.tv_sec,stamp.tv_nsec);
    scheduler(base);threads(pid);
    snprintf(path,sizeof path,"/proc/%ld/stat",value);int ok=readtext(path,stat_after,sizeof stat_after)&&measured_base(pid)==base;
    char *again=ok?strrchr(stat_after,')'):0;p=again?again+2:0;field=3;unsigned long long later=0;
    while(p&&field<22 && (p=strchr(p,' '))){p++;field++;}ok=ok&&p&&sscanf(p,"%llu",&later)==1&&later==start;
    emit(!ok,"SNAPSHOT_END","phase=%s pid=%ld generation_equal=%u",argv[2],value,ok);return ok?0:79;
}
