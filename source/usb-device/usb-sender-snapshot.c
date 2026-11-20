/* Read-only scheduler sampler, adapted from the reviewed historical tool.
 * No ptrace, process stop, hook, ioctl, target write, or synthetic MSC request. */
#define _GNU_SOURCE
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <stdarg.h>
#include <errno.h>
#include <unistd.h>
#include <fcntl.h>
#include <dirent.h>
#include <time.h>
#include <sys/stat.h>
#include <sys/sysmacros.h>
#ifndef SNAPSHOT_SOURCE_SHA256
#error "Build must bind the consumed source digest"
#endif
#if !defined(__aarch64__) || __SIZEOF_POINTER__ != 8
#error "The sampler requires the real AArch64 LP64 target"
#endif
#define APP_SHA "2ea02f7ecbc5bb917316fe8ef4ce5ffd87eb66efaae78ba2ce11420552df539b"
#define EXE_SHA "5171f576d8b76cfbf15581389183b390c445bd6ff9dd97fd6668c5f64e77dc91"
#define APP_BYTES 99960744
#define MAP_LIMIT (1024*1024)
#define THREAD_LIMIT 512
#define OUTPUT_LIMIT (4U*1024U*1024U)
#define OUTPUT_TAIL_RESERVE 4096U
static size_t output_bytes;
static int memfd=-1, procfd=-1, reads_ok=1;
static void emit(const char *kind,const char *format,...) {
    char line[2048];
    int prefix=snprintf(line,sizeof line,"SNAPSHOT_%s ",kind);
    va_list args;va_start(args,format);
    int body=prefix>0&&(size_t)prefix<sizeof line?vsnprintf(line+prefix,sizeof line-(size_t)prefix,format,args):-1;
    va_end(args);
    if(body<0||prefix<0||(size_t)prefix+(size_t)body+1>=sizeof line||
       output_bytes+(size_t)prefix+(size_t)body+1>OUTPUT_LIMIT-OUTPUT_TAIL_RESERVE){
        /* Preserve space for the explicit incomplete record and shell/transport tail. */
        printf("SNAPSHOT_INCOMPLETE reason=output-budget emitted=%zu limit=%u reserve=%u\n",output_bytes,OUTPUT_LIMIT,OUTPUT_TAIL_RESERVE);
        fflush(stdout);exit(80);
    }
    size_t bytes=(size_t)prefix+(size_t)body;line[bytes++]='\n';
    if(fwrite(line,1,bytes,stdout)!=bytes)exit(79);
    output_bytes+=bytes;
}
static int readmem(uintptr_t p,void *out,size_t n) {
    int ok=p && pread(memfd,out,n,(off_t)p)==(ssize_t)n;
    if(!ok){reads_ok=0;emit("READ_FAILED","address=%#lx bytes=%zu",(unsigned long)p,n);}return ok;
}
static ssize_t textat(int dir,const char *path,char *out,size_t cap) {
    int fd=openat(dir,path,O_RDONLY|O_CLOEXEC|O_NOFOLLOW);if(fd<0)return -1;
    size_t got=0;while(got<cap-1){ssize_t n=read(fd,out+got,cap-1-got);if(n<0&&errno==EINTR)continue;if(n<0){close(fd);return -1;}if(!n)break;got+=(size_t)n;}
    char extra;ssize_t tail=read(fd,&extra,1);close(fd);if(tail!=0)return -1;out[got]=0;return (ssize_t)got;
}
static uint32_t rr(uint32_t x,unsigned n){return(x>>n)|(x<<(32-n));}
static const uint32_t k[64]={
0x428a2f98,0x71374491,0xb5c0fbcf,0xe9b5dba5,0x3956c25b,0x59f111f1,0x923f82a4,0xab1c5ed5,0xd807aa98,0x12835b01,0x243185be,0x550c7dc3,0x72be5d74,0x80deb1fe,0x9bdc06a7,0xc19bf174,
0xe49b69c1,0xefbe4786,0x0fc19dc6,0x240ca1cc,0x2de92c6f,0x4a7484aa,0x5cb0a9dc,0x76f988da,0x983e5152,0xa831c66d,0xb00327c8,0xbf597fc7,0xc6e00bf3,0xd5a79147,0x06ca6351,0x14292967,
0x27b70a85,0x2e1b2138,0x4d2c6dfc,0x53380d13,0x650a7354,0x766a0abb,0x81c2c92e,0x92722c85,0xa2bfe8a1,0xa81a664b,0xc24b8b70,0xc76c51a3,0xd192e819,0xd6990624,0xf40e3585,0x106aa070,
0x19a4c116,0x1e376c08,0x2748774c,0x34b0bcb5,0x391c0cb3,0x4ed8aa4a,0x5b9cca4f,0x682e6ff3,0x748f82ee,0x78a5636f,0x84c87814,0x8cc70208,0x90befffa,0xa4506ceb,0xbef9a3f7,0xc67178f2};
/* The constants are reviewed against the original observer's SHA-256 implementation. */
static void digest(unsigned char *data,size_t size,char hex[65]) {
    uint32_t h[8]={0x6a09e667,0xbb67ae85,0x3c6ef372,0xa54ff53a,0x510e527f,0x9b05688c,0x1f83d9ab,0x5be0cd19};
    size_t total=(size+9+63)&~63UL;memset(data+size,0,total-size);data[size]=0x80;
    for(unsigned i=0;i<8;i++)data[total-1-i]=(unsigned char)(((uint64_t)size*8)>>(i*8));
    for(size_t off=0;off<total;off+=64){uint32_t w[64],v[8];memcpy(v,h,32);
        for(unsigned i=0;i<16;i++)w[i]=((uint32_t)data[off+4*i]<<24)|((uint32_t)data[off+4*i+1]<<16)|((uint32_t)data[off+4*i+2]<<8)|data[off+4*i+3];
        for(unsigned i=16;i<64;i++)w[i]=w[i-16]+(rr(w[i-15],7)^rr(w[i-15],18)^(w[i-15]>>3))+w[i-7]+(rr(w[i-2],17)^rr(w[i-2],19)^(w[i-2]>>10));
        for(unsigned i=0;i<64;i++){uint32_t a=v[7]+(rr(v[4],6)^rr(v[4],11)^rr(v[4],25))+((v[4]&v[5])^(~v[4]&v[6]))+k[i]+w[i];uint32_t b=(rr(v[0],2)^rr(v[0],13)^rr(v[0],22))+((v[0]&v[1])^(v[0]&v[2])^(v[1]&v[2]));for(unsigned j=7;j;j--)v[j]=v[j-1];v[4]+=a;v[0]=a+b;}
        for(unsigned i=0;i<8;i++)h[i]+=v[i];
    }
    for(unsigned i=0;i<8;i++)snprintf(hex+i*8,9,"%08x",h[i]);
}
static int samefile(const struct stat *a,const struct stat *b) {
    return a->st_dev==b->st_dev&&a->st_ino==b->st_ino&&a->st_size==b->st_size&&a->st_mtim.tv_sec==b->st_mtim.tv_sec&&a->st_mtim.tv_nsec==b->st_mtim.tv_nsec&&a->st_ctim.tv_sec==b->st_ctim.tv_sec&&a->st_ctim.tv_nsec==b->st_ctim.tv_nsec;
}
static int file_identity(int fd,size_t size,const char *expected,struct stat *out) {
    struct stat a,b;if(fd<0||fstat(fd,&a)||!S_ISREG(a.st_mode)||a.st_size<0||(size_t)a.st_size!=size||size>128*1024*1024)return 0;
    unsigned char *data=malloc(size+128);if(!data)return 0;size_t got=0;
    while(got<size){ssize_t n=pread(fd,data+got,size-got,(off_t)got);if(n<0&&errno==EINTR)continue;if(n<=0)break;got+=(size_t)n;}
    char hex[65]={0};if(got==size)digest(data,size,hex);free(data);
    int ok=got==size&&!fstat(fd,&b)&&samefile(&a,&b)&&!strcmp(hex,expected);if(ok&&out)*out=a;return ok;
}
static unsigned long long generation(int dir,const char *path) {
    char raw[4096];if(textat(dir,path,raw,sizeof raw)<0)return 0;char *p=strrchr(raw,')');if(!p||p[1]!=' ')return 0;p+=2;
    for(unsigned field=3;field<22;field++){p=strchr(p,' ');if(!p)return 0;p++;}
    char *end;errno=0;unsigned long long start=strtoull(p,&end,10);return !errno&&end!=p&&*end==' '?start:0;
}
static uintptr_t map_base(const char *maps,const struct stat *image) {
    unsigned count=0;uintptr_t base=0;const char *p=maps;
    while(*p){unsigned long start,end,offset,inode;unsigned major_id,minor_id;char mode[5],file[512];
        int n=sscanf(p,"%lx-%lx %4s %lx %x:%x %lu %511[^\n]",&start,&end,mode,&offset,&major_id,&minor_id,&inode,file);
        if(n==8&&!strcmp(file,"/usr/lib/appFw.so")){
            if(inode!=(unsigned long)image->st_ino||major_id!=major(image->st_dev)||minor_id!=minor(image->st_dev))return 0;
            if(!offset){base=start;count++;}
        }
        p=strchr(p,'\n');if(!p)break;p++;
    }return count==1?base:0;
}
static int snapshot_maps(char *maps,struct stat *image,uintptr_t *base) {
    int fd=openat(procfd,"root/usr/lib/appFw.so",O_RDONLY|O_CLOEXEC|O_NOFOLLOW);
    int ok=file_identity(fd,APP_BYTES,APP_SHA,image);if(fd>=0)close(fd);
    int exe=openat(procfd,"exe",O_RDONLY|O_CLOEXEC);struct stat st;
    ok=ok&&exe>=0&&!fstat(exe,&st)&&st.st_size>0&&file_identity(exe,(size_t)st.st_size,EXE_SHA,0);if(exe>=0)close(exe);
    if(!ok||textat(procfd,"maps",maps,MAP_LIMIT)<0)return 0;*base=map_base(maps,image);return *base!=0;
}
static void rawhex(const char *kind,const unsigned char *data,size_t size,unsigned long id) {
    for(size_t off=0;off<size;off+=64){size_t n=size-off;if(n>64)n=64;char hex[129];for(size_t i=0;i<n;i++)snprintf(hex+2*i,3,"%02x",data[off+i]);emit(kind,"id=%lu offset=%zu bytes=%zu hex=%s",id,off,n,hex);}
}
static int scheduled(uintptr_t object,unsigned index,uintptr_t base) {
    uintptr_t before[2],after[2],run,run_again;unsigned char control[0x1b8],again[0x1b8];
    int object_readable=readmem(object,before,sizeof before);
    int control_readable=object_readable&&readmem(before[1],control,sizeof control);
    int run_readable=object_readable&&readmem(before[0]+0x10,&run,8);
    emit("SCHEDULED_READ","index=%u object_readable=%u control_readable=%u run_readable=%u token_readable=%u",index,object_readable,control_readable,run_readable,control_readable);
    if(!object_readable||!control_readable||!run_readable)return 0;
    uint32_t id;uintptr_t token;memcpy(&id,control+8,4);memcpy(&token,control+0x10,8);
    int stable=readmem(object,after,sizeof after)&&!memcmp(before,after,sizeof before)&&readmem(before[1],again,sizeof again)&&!memcmp(control,again,sizeof control)&&readmem(before[0]+0x10,&run_again,8)&&run==run_again;
    emit("SCHEDULED","role=%s index=%u object=%#lx control=%#lx id=%#x token=%#lx run=%#lx stable=%u msc_run=%u",index?"pending":"active",index,object,before[1],id,token,run>=base?run-base:run,stable,run==base+0x34796b0);
    rawhex("OBJECT",(unsigned char *)before,sizeof before,index);
    rawhex("CONTROL",control,sizeof control,index);
    if(!index){uintptr_t first,last,cap;memcpy(&first,control+0x1a0,8);memcpy(&last,control+0x1a8,8);memcpy(&cap,control+0x1b0,8);
        if(last<first||cap<last||last-first>256*24||(last-first)%24){emit("DEPENDENCIES","complete=0 first=%#lx last=%#lx capacity=%#lx",first,last,cap);return 0;}
        for(unsigned i=0;i<(last-first)/24;i++){
            unsigned char value[24],check[24];uintptr_t future;uint32_t status,status_again;
            if(!readmem(first+i*24,value,24)||!readmem(first+i*24,check,24)||memcmp(value,check,24)){stable=0;break;}
            memcpy(&future,value,8);int readable=readmem(future?future+0x10:0,&status,4)&&readmem(future?future+0x10:0,&status_again,4);
            if(!readable){emit("DEPENDENCY_STATE","index=%u status_readable=0",i);stable=0;break;}
            int equal=status==status_again;stable=stable&&equal;
            emit("DEPENDENCY_STATE","index=%u future=%#lx status=%#x status_readable=1 stable=%u identity_unverified=1",i,future,status,equal);
            rawhex("DEPENDENCY",value,24,i);
        }
    }return stable;
}
static void scheduler(uintptr_t base,int *complete,int *stable) {
    uintptr_t manager=base+0x910a108,group=manager+0x310+6*0x90,head=group+0x10;
    unsigned char before[0x90],after[0x90]={0};uintptr_t owner,first,last,count,active;uint32_t number;
    *complete=*stable=0;if(!readmem(group,before,sizeof before))return;
    memcpy(&owner,before,8);memcpy(&number,before+8,4);if(owner!=manager||number!=6){emit("SCHED_UNAVAILABLE","group=%#lx",group);return;}
    memcpy(&first,before+0x10,8);memcpy(&last,before+0x18,8);memcpy(&count,before+0x20,8);memcpy(&active,before+0x88,8);
    emit("SCHED_HEADER","base=%#lx first=%#lx last=%#lx pending=%lu active=%#lx no_lock=1",base,first,last,count,active);
    int objects=active?scheduled(active,0,base):1;uintptr_t node=first,previous=head;unsigned visited=0;
    while(node!=head&&visited<256&&visited<count){uintptr_t fields[3],check[3];if(!readmem(node,fields,sizeof fields)||fields[1]!=previous){objects=0;break;}
        rawhex("NODE",(unsigned char *)fields,sizeof fields,visited+1);
        objects=scheduled(fields[2],visited+1,base)&&objects;
        if(!readmem(node,check,sizeof check)||memcmp(fields,check,sizeof fields)){objects=0;break;}previous=node;node=fields[0];visited++;
    }
    *complete=node==head&&visited==count&&previous==last;
    *stable=readmem(group,after,sizeof after)&&!memcmp(before,after,sizeof before)&&objects&&reads_ok;
    emit("SCHED_STABILITY","header_equal=%u visited=%u pending=%lu complete=%u stable=%u atomic=0",!memcmp(before,after,sizeof before),visited,count,*complete,*stable);
    rawhex("SCHED_HEADER_BYTES",before,sizeof before,0);
}
static int cmp_tid(const void *a,const void *b){long x=*(const long *)a,y=*(const long *)b;return (x>y)-(x<y);}
static int thread_ids(long ids[THREAD_LIMIT],unsigned *count) {
    int fd=openat(procfd,"task",O_RDONLY|O_DIRECTORY|O_CLOEXEC);if(fd<0)return 0;DIR *dir=fdopendir(fd);if(!dir){close(fd);return 0;}
    struct dirent *entry;*count=0;int ok=1;errno=0;
    while((entry=readdir(dir))){char *end;errno=0;long tid=strtol(entry->d_name,&end,10);if(*end||tid<1){errno=0;continue;}if(*count==THREAD_LIMIT){ok=0;break;}ids[(*count)++]=tid;errno=0;}
    if(errno)ok=0;closedir(dir);qsort(ids,*count,sizeof *ids,cmp_tid);return ok;
}
static int threads(void) {
    long ids[THREAD_LIMIT],after[THREAD_LIMIT];unsigned count=0,later=0;int ok=thread_ids(ids,&count);
    for(unsigned i=0;i<count;i++){char path[128],raw[4096];snprintf(path,sizeof path,"task/%ld/stat",ids[i]);unsigned long long start=generation(procfd,path);if(!start)ok=0;
        const char *fields[]={"comm","wchan","stack","syscall"};
        for(unsigned f=0;f<4;f++){snprintf(path,sizeof path,"task/%ld/%s",ids[i],fields[f]);ssize_t n=textat(procfd,path,raw,sizeof raw);
            emit("THREAD","tid=%ld start=%llu start_readable=%u field=%s readable=%u bytes=%zd errno=%d",ids[i],start,start!=0,fields[f],n>=0,n,n>=0?0:errno);
            const char *kinds[]={"THREAD_COMM_BYTES","THREAD_WCHAN_BYTES","THREAD_STACK_BYTES","THREAD_SYSCALL_BYTES"};
            if(n<0){ok=0;continue;}rawhex(kinds[f],(unsigned char *)raw,(size_t)n,(unsigned long)ids[i]);
            if(f==3){long number;unsigned long a[6],sp,pc;unsigned char stack[512];if(sscanf(raw,"%ld %lx %lx %lx %lx %lx %lx %lx %lx",&number,&a[0],&a[1],&a[2],&a[3],&a[4],&a[5],&sp,&pc)==9){emit("THREAD_USER_STACK","tid=%ld sp=%#lx pc=%#lx syscall=%ld raw_candidates_only=1",ids[i],sp,pc,number);if(readmem(sp,stack,sizeof stack))rawhex("THREAD_USER_STACK_BYTES",stack,sizeof stack,(unsigned long)ids[i]);else ok=0;}}
        }
        snprintf(path,sizeof path,"task/%ld/stat",ids[i]);int equal=start&&generation(procfd,path)==start;emit("THREAD_END","tid=%ld generation_equal=%u",ids[i],equal);ok=ok&&equal;
    }
    ok=thread_ids(after,&later)&&ok&&count==later&&!memcmp(ids,after,count*sizeof *ids);
    emit("THREADS_END","visited=%u complete=%u limit=%u atomic=0",count,ok,THREAD_LIMIT);return ok;
}
int main(int argc,char **argv) {
    unsigned char check[256]="abc";char check_sha[65];digest(check,3,check_sha);
    if(strcmp(check_sha,"ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad"))return 79;
    if(argc!=5)return 64;const char *phase=argv[1];if(strcmp(phase,"before-enter")&&strcmp(phase,"after-enter"))return 64;
    char *end;long requested=strtol(argv[2],&end,10);if(*end||requested<0||requested==1)return 64;
    unsigned long long expected=strtoull(argv[3],&end,10);if(*end||((requested==0)!=(expected==0)))return 64;
    if(strlen(argv[4])!=64)return 64;int self=open("/proc/self/exe",O_RDONLY|O_CLOEXEC);struct stat selfst;
    int selfok=self>=0&&!fstat(self,&selfst)&&selfst.st_size>0&&file_identity(self,(size_t)selfst.st_size,argv[4],0);if(self>=0)close(self);if(!selfok)return 79;
    char *before=malloc(MAP_LIMIT+128),*after=malloc(MAP_LIMIT+128);if(!before||!after)return 79;
    long pid=requested;
    if(!pid){DIR *dir=opendir("/proc");if(!dir)return 79;struct dirent *entry;unsigned matches=0;
        while((entry=readdir(dir))){long candidate=strtol(entry->d_name,&end,10);if(*end||candidate<2)continue;char path[80];snprintf(path,sizeof path,"/proc/%ld",candidate);int fd=open(path,O_RDONLY|O_DIRECTORY|O_CLOEXEC|O_NOFOLLOW);if(fd<0)continue;
            if(textat(fd,"maps",before,MAP_LIMIT)>=0&&strstr(before," /usr/lib/appFw.so\n")){pid=candidate;matches++;}close(fd);
        }closedir(dir);if(matches!=1)return 79;
    }
    char path[80];snprintf(path,sizeof path,"/proc/%ld",pid);procfd=open(path,O_RDONLY|O_DIRECTORY|O_CLOEXEC|O_NOFOLLOW);if(procfd<0)return 79;
    unsigned long long start=generation(procfd,"stat");struct stat image1,image2;uintptr_t base1=0,base2=0;
    if(!start||(expected&&expected!=start)||!snapshot_maps(before,&image1,&base1))return 79;
    memfd=openat(procfd,"mem",O_RDONLY|O_CLOEXEC|O_NOFOLLOW);if(memfd<0)return 79;
    struct timespec stamp;if(clock_gettime(CLOCK_MONOTONIC,&stamp))return 79;
    emit("BEGIN","phase=%s pid=%ld start=%llu base=%#lx source_sha256=%s app_sha256=%s exe_sha256=%s monotonic=%ld.%09ld",phase,pid,start,base1,SNAPSHOT_SOURCE_SHA256,APP_SHA,EXE_SHA,stamp.tv_sec,stamp.tv_nsec);
    size_t maps_bytes=strlen(before);char map_sha[65];unsigned char *copy=malloc(maps_bytes+128);if(!copy)return 79;memcpy(copy,before,maps_bytes);digest(copy,maps_bytes,map_sha);free(copy);
    emit("MAPS","sha256=%s bytes=%zu device=%u:%u inode=%lu",map_sha,maps_bytes,major(image1.st_dev),minor(image1.st_dev),(unsigned long)image1.st_ino);rawhex("MAPS_BYTES",(unsigned char *)before,maps_bytes,0);
    int complete,stable;scheduler(base1,&complete,&stable);int thread_complete=threads();
    int generation_equal=generation(procfd,"stat")==start;
    int files_equal=snapshot_maps(after,&image2,&base2)&&samefile(&image1,&image2);
    int maps_equal=files_equal&&base1==base2&&!strcmp(before,after);
    emit("END","phase=%s pid=%ld start=%llu generation_equal=%u maps_equal=%u file_identity_equal=%u pending_complete=%u scheduler_stable=%u threads_complete=%u reads_complete=%u atomic=0",phase,pid,start,generation_equal,maps_equal,files_equal,complete,stable,thread_complete,reads_ok);
    close(memfd);close(procfd);free(before);free(after);
    if(ferror(stdout)||fflush(stdout)||!generation_equal||!maps_equal||!files_equal)return 79;
    return complete&&stable&&thread_complete&&reads_ok?0:80;
}
