/* Finite public ALLLANG helper; menu changes and cross-VM proof belong to host. */
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <errno.h>
#include <fcntl.h>
#include <unistd.h>
#include <sys/mman.h>
#include <sys/vfs.h>
#define CONFIG_BYTES 2390264U
#define WINDOW_BYTES 0x400000U
#define EXPORT_PHYS UINT64_C(0x41e600000)
#define SCOPE "sid02cf_language_date_bank0_only"
static uint32_t u32(const unsigned char *p){return p[0]|(uint32_t)p[1]<<8|(uint32_t)p[2]<<16|(uint32_t)p[3]<<24;}
static unsigned u16(const unsigned char *p){return p[0]|(unsigned)p[1]<<8;}
static uint64_t fnv(const volatile unsigned char *p,unsigned n){
    uint64_t h=UINT64_C(14695981039346656037);
    for(unsigned i=0;i<n;i++)h=(h^p[i])*UINT64_C(1099511628211);
    return h;
}
static int number(const char *s,unsigned max,unsigned char *out){
    unsigned n=0;if(!s || !*s)return 0;
    for(;*s;s++){if(*s<'0'||*s>'9'||n>max/10||(n==max/10&&(unsigned)(*s-'0')>max%10))return 0;n=n*10+(unsigned)(*s-'0');}
    *out=(unsigned char)n;return 1;
}
static int reserved(const char *s){
    const char *a="memrsv=0x00400000@0x41e600000:uc",*b="memrsv=0x00900000@0x41e100000:uc";
    unsigned count=0;if(!s)return 0;
    while(*s){
        s+=strspn(s," \t\r\n");size_t n=strcspn(s," \t\r\n");
        if((n==strlen(a)&&!memcmp(s,a,n))||(n==strlen(b)&&!memcmp(s,b,n)))count++;
        s+=n;
    }
    return count==1;
}
static int space_ok(uint64_t blocks,uint64_t size){
    return size && blocks<=UINT64_MAX/size && blocks*size>=CONFIG_BYTES+UINT64_C(1048576);
}
static int changed(const unsigned char *v){return v[0]!=1 && v[1]!=3 && v[1]<=3;}
static int parse(const unsigned char *p,unsigned n,unsigned char values[2]){
    if(n!=CONFIG_BYTES)return 0;
    unsigned base=0;
    for(unsigned bank=0;bank<2;bank++){
        if(base>n || n-base<256)return 0;
        const unsigned char *q=p+base;
        uint32_t count=u32(q+20),data=u32(q+24),bytes=u32(q+28);
        if(memcmp(q+12,"BK4\0",4)||u32(q+16)!=819 ||
           count!=(bank?33018U:37680U)||data!=(bank?203296U:231264U)||
           bytes!=(bank?1216216U:737717U)||data>n-base||bytes>n-base-data)return 0;
        unsigned end=data+bytes;
        if(256U+819U*6U+count*6U>data)return 0;
        uint32_t sum=0;for(unsigned i=0;i<end;i++)if(i<32||i>=36)sum+=q[i];
        if(sum!=u32(q+32))return 0;
        for(unsigned i=0;i<819;i++){
            const unsigned char *s=q+256+i*6;
            if(u32(s+2)>count || u16(s)>count-u32(s+2))return 0;
        }
        if(!bank){
            const unsigned char *sid=q+256+0x2cf*6;
            if(u16(sid)!=6873 || u32(sid+2)!=30536)return 0;
            for(unsigned i=0;i<2;i++){
                const unsigned char *a=q+256+819*6+(30536+0x401+i*2)*6;
                uint32_t ptr=u32(a+2),off=ptr&0xffffff;
                if(u16(a)!=64 || ptr>>24!=1 || off<data || off>=end ||
                   ptr!=(i?0x0109555aU:0x01095556U))return 0;
                values[i]=q[off];
            }
            if(values[1]>3)return 0;
        }
        if(bank){if(base+end!=n)return 0;}
        else base=(end+4095U)&~4095U;
    }
    return 1;
}
#ifndef HOST_PURE
extern int Backup_nread(unsigned,void *,int);
extern int Backup_sync_subsystem(unsigned);
static int fail(const char *stage,long rc){
    int e=errno;printf("USER_SETTINGS_ERROR stage=%s rc=%ld errno=%d\n",stage,rc,e);fflush(0);return 1;
}
static unsigned char *readfile(void){
    errno=0;int fd=open("/setting/Backup.bin",O_RDONLY|O_NOFOLLOW|O_NONBLOCK);
    if(fd<0){fail("file_open",fd);return 0;}
    errno=0;off_t size=lseek(fd,0,SEEK_END);
    if(size!=CONFIG_BYTES){fail("file_length",size);close(fd);return 0;}
    errno=0;off_t pos=lseek(fd,0,SEEK_SET);
    if(pos){fail("file_seek",pos);close(fd);return 0;}
    errno=0;unsigned char *p=malloc(CONFIG_BYTES);
    if(!p){fail("file_malloc",-1);close(fd);return 0;}
    unsigned total=0;
    while(total<CONFIG_BYTES){
        errno=0;ssize_t n=read(fd,p+total,CONFIG_BYTES-total);
        if(n<0&&errno==EINTR)continue;
        if(n<=0){fail("file_read",n);close(fd);free(p);return 0;}total+=(unsigned)n;
    }
    errno=0;unsigned char extra;ssize_t n=read(fd,&extra,1);
    if(n!=0){fail("file_eof",n);close(fd);free(p);return 0;}
    errno=0;int rc=close(fd);if(rc){fail("file_close",rc);free(p);return 0;}
    return p;
}
static int api(unsigned char out[2],const char *stage){
    for(unsigned i=0;i<2;i++){
        unsigned id=0x02cf0401+i*2;errno=0;int rc=Backup_nread(id,out+i,1);int e=errno;
        printf("USER_SETTINGS_API stage=%s id=%08x rc=%d errno=%d value=%u\n",stage,id,rc,e,rc==1?out[i]:256U);fflush(0);
        if(rc!=1){errno=e;return fail(stage,rc);}
    }
    errno=0;return out[1]>3?fail("api_date_range",out[1]):0;
}
static int guard(void){
    struct statfs st;errno=0;int rc=statfs("/setting",&st);
    if(rc)return fail("setting_statfs",rc);
    printf("USER_SETTINGS_SPACE type=%lx available_blocks=%llu block_size=%lu\n",
           (unsigned long)st.f_type,(unsigned long long)st.f_bavail,(unsigned long)st.f_bsize);fflush(0);
    errno=0;if(st.f_type!=0x01021994 || st.f_bsize<=0 || !space_ok(st.f_bavail,st.f_bsize))return fail("tmpfs_space_guard",-1);
    return 0;
}
static int export_ram(const unsigned char *p,const char *tag){
    char cmd[8192];errno=0;int fd=open("/proc/cmdline",O_RDONLY);
    if(fd<0)return fail("cmdline_open",fd);
    ssize_t n;unsigned total=0;
    while(total<sizeof cmd-1){
        errno=0;n=read(fd,cmd+total,sizeof cmd-1-total);
        if(n<0&&errno==EINTR)continue;
        if(n<0){fail("cmdline_read",n);close(fd);return 1;}
        if(!n)break;total+=(unsigned)n;
    }
    errno=0;int rc=close(fd);if(rc)return fail("cmdline_close",rc);
    cmd[total]=0;errno=0;
    if(total==sizeof cmd-1 || strlen(cmd)!=total || !reserved(cmd) || CONFIG_BYTES>WINDOW_BYTES)return fail("reservation_guard",total);
    errno=0;fd=open("/dev/mem",O_RDWR);if(fd<0)return fail("memory_open",fd);
    errno=0;unsigned char *m=mmap(0,WINDOW_BYTES,PROT_READ|PROT_WRITE,MAP_SHARED,fd,EXPORT_PHYS);
    int e=errno;if(m==MAP_FAILED){close(fd);errno=e;return fail("memory_map",-1);}
    errno=0;rc=close(fd);if(rc){fail("memory_close",rc);munmap(m,WINDOW_BYTES);return 1;}
    uint64_t hash=fnv(p,CONFIG_BYTES);memcpy(m,p,CONFIG_BYTES);__sync_synchronize();
    uint64_t back=fnv(m,CONFIG_BYTES);errno=0;rc=munmap(m,WINDOW_BYTES);
    if(rc)return fail("memory_unmap",rc);
    if(hash!=back){errno=0;return fail("memory_hash",-1);}
    printf("%s physical=0x41e600000 bytes=%u fnv1a64=%016llx scope=%s\n",tag,CONFIG_BYTES,(unsigned long long)hash,SCOPE);fflush(0);return 0;
}
static int run(int argc,char **argv){
    int save=argc==2&&!strcmp(argv[1],"save");
    int snapshot=argc==2&&!strcmp(argv[1],"snapshot");
    int restore=argc==4&&!strcmp(argv[1],"restore");unsigned char expected[2]={0},v[2]={0},file[2]={0};
    if(!save&&!restore&&!snapshot){errno=0;return fail("usage_save_snapshot_or_restore_expectedlang_expecteddate",argc);}
    if(restore&&(!number(argv[2],255,expected)||!number(argv[3],3,expected+1))){errno=0;return fail("expected_ascii_range",-1);}
    int result=1;unsigned char *p=0;
    if(api(v,"before"))goto done;
    p=readfile();if(!p)goto done;
    errno=0;if(!parse(p,CONFIG_BYTES,file)){fail("before_layout_checksum",-1);goto done;}
    printf("USER_SETTINGS_BEFORE api=%u,%u file=%u,%u writeComp=%u low=%u fnv1a64=%016llx scope=%s\n",
           v[0],v[1],file[0],file[1],u32(p+8),p[8],(unsigned long long)fnv(p,CONFIG_BYTES),SCOPE);fflush(0);
    if(restore){
        errno=0;if(memcmp(v,file,2)||memcmp(v,expected,2)){fail("restore_expected_file_api",-1);goto done;}
    }else{
        errno=0;if(save&&!changed(v)){fail("both_changed_from_seed_1_3",-1);goto done;}
        /* Original menu code may have already committed one setting. Both
         * values must differ from seed, but one pending byte proves new work. */
        int pending=memcmp(v,file,2)!=0;
        errno=0;if(save&&!pending){fail("before_file_no_pending_change",-1);goto done;}
        printf("USER_SETTINGS_COMMIT_NEEDED value=%d\n",pending);fflush(0);
        if(pending){
            if(guard())goto done;
            errno=0;int rc=Backup_sync_subsystem(0x02cf);int e=errno;
            printf("USER_SETTINGS_SYNC sid=02cf rc=%d errno=%d\n",rc,e);fflush(0);
            if(rc){errno=e;fail("sync",rc);goto done;}
            free(p);p=readfile();if(!p)goto done;
            errno=0;if(!parse(p,CONFIG_BYTES,file)||memcmp(v,file,2)){fail("after_layout_checksum_api",-1);goto done;}
        }
    }
    unsigned char stable[2]={0};if(api(stable,"stable"))goto done;
    errno=0;if(memcmp(v,stable,2)){fail("api_unstable",-1);goto done;}
    printf("USER_SETTINGS_FILE lang=%u date=%u writeComp=%u low=%u fnv1a64=%016llx\n",
           file[0],file[1],u32(p+8),p[8],(unsigned long long)fnv(p,CONFIG_BYTES));fflush(0);
    if((save||snapshot)&&export_ram(p,"USER_SETTINGS_EXPORTED"))goto done;
    printf("USER_SETTINGS_%s_MATCH lang=%u date=%u scope=%s\n",snapshot?"SNAPSHOT":save?"SAVE":"RESTORE",v[0],v[1],SCOPE);fflush(0);result=0;
done:
    free(p);
    if(result&&(save||snapshot)){
        p=readfile();int rc=p?export_ram(p,"USER_SETTINGS_FAILED_EXPORTED"):1;
        printf("USER_SETTINGS_FAILED_EXPORT rc=%d original_failure=1\n",rc);fflush(0);free(p);
    }
    printf("USER_SETTINGS_DONE rc=%d scope=%s\n",result,SCOPE);fflush(0);return result;
}
extern int __libc_start_main(int (*)(int,char **),int,char **,void (*)(void),void (*)(void),void (*)(void),void *);
__asm__(".global _start\n.type _start, %function\n_start:\nmov x0, sp\nbl entry\nbrk #0\n");
__attribute__((noreturn)) void entry(unsigned long *s){__libc_start_main(run,(int)s[0],(char **)(s+1),0,0,0,s);__builtin_trap();}
#endif
