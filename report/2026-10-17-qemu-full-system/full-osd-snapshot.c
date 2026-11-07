/* SPDX-License-Identifier: MIT */
#define _GNU_SOURCE
#include "full-osd-snapshot.h"
#include "guest-stat-compat.h"
#include <dirent.h>
#include <errno.h>
#include <fcntl.h>
#include <inttypes.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/file.h>
#include <sys/stat.h>
#include <sys/statvfs.h>
#include <unistd.h>
#ifdef FULL_OSD_HOST_FIXTURE
#define RECORD_PREFIX "FULL_OSD_HOSTFIXTURE_"
#else
#define RECORD_PREFIX "OSD_IMMUTABLE_"
#endif
#define RESERVE_BYTES UINT64_C(1048576)
#define PIXEL_BYTES 614400U
#define METADATA_BYTES 24930U
static uint32_t le32(const unsigned char *p){return (uint32_t)p[0]|(uint32_t)p[1]<<8|(uint32_t)p[2]<<16|(uint32_t)p[3]<<24;}
static unsigned le16(const unsigned char *p){return p[0]|(unsigned)p[1]<<8;}
static uint64_t le64(const unsigned char *p){return le32(p)|(uint64_t)le32(p+4)<<32;}
static uint64_t hash_bytes(uint64_t hash,const unsigned char *p,size_t length,size_t offset){
    for(size_t i=0;i<length;i++){
        size_t position=offset+i;
        hash^=position>=40 && position<48?0:p[i];hash*=UINT64_C(1099511628211);
    }
    return hash;
}
static int valid_nonce(const char *nonce){
    if(!nonce)return 0;
    for(size_t i=0;i<=64;i++){
        unsigned char c=(unsigned char)nonce[i];
        if(!c)return i!=0;
        if(i==64 || !((c>='0' && c<='9') || (c>='a' && c<='f') || (c>='A' && c<='F')))return 0;
    }
    return 0;
}
static int valid_container(const unsigned char *p,size_t length){
    if(!p || length!=FULL_OSD_SNAPSHOT_BYTES || memcmp(p,"HOSDAP02",8))return 0;
    uint64_t sequence=le64(p+8),source=le64(p+120),physical=le64(p+32);
    uint32_t pending=le32(p+56);const unsigned char *d=p+64;
    if(!sequence || !source || source>sequence || le32(p+20)!=640 || le32(p+24)!=480 || le32(p+28)!=1 ||
       le32(p+48)!=PIXEL_BYTES || le32(p+52)!=METADATA_BYTES || le32(p+60) ||
       physical<UINT64_C(0x410000000) || physical>UINT64_C(0x500000000)-PIXEL_BYTES ||
       le16(d)!=0x1003 || le32(d+8)!=le32(p+16) || le16(d+16) ||
       le16(d+20)!=640 || le16(d+22)!=480 || le16(d+24)>640 || le16(d+26)>480 ||
       le16(d+28)>640-le16(d+24) || le16(d+30)>480-le16(d+26) ||
       le16(p+100)!=0x1002 || le32(p+108)!=pending)return 0;
    if(pending==0x1003){if(source!=sequence || le64(p+112))return 0;}
    else if(pending==0x1005){if(source>=sequence || le16(p+112)!=0x1005)return 0;}
    else return 0;
    return hash_bytes(UINT64_C(14695981039346656037),p,length,0)==le64(p+40);
}
/* Pin every directory component; never follow even an intermediate symlink. */
static int open_directory(const char *path,struct stat *identity){
    if(!path || path[0]!='/' || strlen(path)>=4096){errno=EINVAL;return -1;}
    char copy[4096];memcpy(copy,path,strlen(path)+1);
    int fd=open("/",O_RDONLY|O_DIRECTORY|O_CLOEXEC|O_NOFOLLOW);
    if(fd<0)return -1;
    char *part=copy+1;
    while(*part){
        char *end=strchr(part,'/');if(end)*end=0;
        if(!*part || !strcmp(part,".") || !strcmp(part,"..")){errno=EINVAL;goto fail;}
        int next=openat(fd,part,O_RDONLY|O_DIRECTORY|O_CLOEXEC|O_NOFOLLOW);
        if(next<0)goto fail;
        if(close(fd)){int saved=errno;close(next);errno=saved;return -1;}
        fd=next;if(!end)break;part=end+1;if(!*part){errno=EINVAL;goto fail;}
    }
    struct stat st;if(fstat(fd,&st))goto fail;
    if(st.st_uid!=geteuid() || (st.st_mode&0022)){errno=EPERM;goto fail;}
    *identity=st;return fd;
fail:{int saved=errno;close(fd);errno=saved;return -1;}
}
static int read_request(int directory,const char *nonce){
    char name[80],expected[80],buffer[81];
    snprintf(name,sizeof name,"%s.request",nonce);
    int expected_length=snprintf(expected,sizeof expected,"HOSDREQ1 %s\n",nonce);
    int fd=openat(directory,name,O_RDONLY|O_CLOEXEC|O_NOFOLLOW|O_NONBLOCK);
    if(fd<0)return errno==ENOENT?FULL_OSD_NO_REQUEST:FULL_OSD_REJECTED;
    struct stat st;int ok=!fstat(fd,&st) && S_ISREG(st.st_mode) && st.st_nlink==1 &&
        st.st_uid==geteuid() && !(st.st_mode&0022) && st.st_size==expected_length;
    size_t used=0;
    while(ok && used<sizeof buffer){
        ssize_t n=read(fd,buffer+used,sizeof buffer-used);
        if(n<0 && errno==EINTR)continue;
        if(n<0){ok=0;break;}
        if(!n)break;
        used+=(size_t)n;
    }
    ok=ok && used==(size_t)expected_length && !memcmp(buffer,expected,used);
    if(close(fd))ok=0;
    if(!ok){errno=EINVAL;return FULL_OSD_REJECTED;}return 0;
}
static int inventory(int directory,const char *nonce,unsigned *count,int *already){
    int copy=dup(directory);if(copy<0)return -1;
    DIR *stream=fdopendir(copy);
    if(!stream){int saved=errno;close(copy);errno=saved;return -1;}
    *count=0;*already=0;int ok=1;
    for(;;){
        errno=0;struct dirent *entry=readdir(stream);
        if(!entry){if(errno)ok=0;break;}
        size_t length=strlen(entry->d_name);
        if(length<5 || strcmp(entry->d_name+length-5,".hosd"))continue;
        struct stat st;
        if(fstatat(directory,entry->d_name,&st,AT_SYMLINK_NOFOLLOW) || !S_ISREG(st.st_mode) ||
           st.st_nlink!=1 || st.st_uid!=geteuid()){errno=EINVAL;ok=0;break;}
        if(++*count>FULL_OSD_SNAPSHOT_LIMIT){*count=FULL_OSD_SNAPSHOT_LIMIT+1;break;}
        size_t nonce_length=strlen(nonce);
        if(length>nonce_length && !memcmp(entry->d_name,nonce,nonce_length) && entry->d_name[nonce_length]=='-')*already=1;
    }
    int saved=errno;if(closedir(stream)){if(ok)saved=errno;ok=0;}errno=saved;return ok?0:-1;
}
static int enough_space(int directory,size_t length){
    struct statvfs st;if(fstatvfs(directory,&st))return 0;
    uint64_t unit=st.f_frsize,blocks=st.f_bavail;
    if(!unit || blocks>UINT64_MAX/unit || (uint64_t)length>UINT64_MAX-(unit-1)){errno=EOVERFLOW;return 0;}
    uint64_t needed=((uint64_t)length+unit-1)/unit*unit;
    if(needed>UINT64_MAX-unit || needed+unit>UINT64_MAX-RESERVE_BYTES ||
       blocks*unit<needed+unit+RESERVE_BYTES){errno=ENOSPC;return 0;}
    return 1;
}
static int sync_fd(int fd){int rc;do{rc=fsync(fd);}while(rc && errno==EINTR);return rc;}
static int remove_partial(int directory,const char *filename,const struct stat *own){
    struct stat current;if(fstatat(directory,filename,&current,AT_SYMLINK_NOFOLLOW))return -1;
    if(current.st_ino!=own->st_ino || current.st_dev!=own->st_dev){errno=ESTALE;return -1;}
    return unlinkat(directory,filename,0) || sync_fd(directory)?-1:0;
}
int full_osd_snapshot_save(const void *bytes,size_t length,const struct full_osd_snapshot_request *request){
    if(!request || !request->enabled)return FULL_OSD_DISABLED;
    if(!request->log){errno=EINVAL;return FULL_OSD_REJECTED;}
    const unsigned char *p=bytes;const char *reason="invalid-nonce";
    int rc=FULL_OSD_REJECTED,directory=-1,fd=-1,created=0;
    int nonce_ok=valid_nonce(request->nonce);unsigned count=0;
    char filename[96]={0},record[512];struct stat own={0},directory_identity={0};const char *path=0;
    if(!nonce_ok){errno=EINVAL;goto done;}
    reason="invalid-container";if(!valid_container(p,length)){errno=EINVAL;goto done;}
#ifdef FULL_OSD_HOST_FIXTURE
    path=request->host_fixture_directory;
#else
    path=FULL_OSD_SNAPSHOT_DIRECTORY;
#endif
    reason="unsafe-directory";directory=open_directory(path,&directory_identity);if(directory<0)goto done;
    reason="directory-lock";rc=FULL_OSD_IO_FAILED;if(flock(directory,LOCK_EX|LOCK_NB))goto done;
    reason="request-missing-or-invalid";rc=read_request(directory,request->nonce);if(rc)goto done;
    reason="inventory";rc=FULL_OSD_IO_FAILED;int already;
    if(inventory(directory,request->nonce,&count,&already))goto done;
    if(count>=FULL_OSD_SNAPSHOT_LIMIT){reason="snapshot-limit";rc=FULL_OSD_LIMIT_REACHED;errno=ENOSPC;goto done;}
    if(already){reason="nonce-already-present";rc=FULL_OSD_NONCE_EXISTS;errno=EEXIST;goto done;}
    reason="space-unavailable";if(!enough_space(directory,length))goto done;
    snprintf(filename,sizeof filename,"%s-%" PRIu64 ".hosd",request->nonce,le64(p+8));
    reason="exclusive-create";fd=openat(directory,filename,O_RDWR|O_CREAT|O_EXCL|O_NOFOLLOW|O_CLOEXEC,0600);
    if(fd<0)goto done;
    created=1;reason="new-inode";
    if(fstat(fd,&own) || !S_ISREG(own.st_mode) || own.st_nlink!=1)goto done;
    reason="write";
    for(size_t offset=0;offset<length;){
        ssize_t n=write(fd,p+offset,length-offset);
        if(n<0 && errno==EINTR)continue;
        if(n<=0 || (size_t)n>length-offset){if(!n)errno=EIO;goto done;}offset+=(size_t)n;
    }
    reason="readback";unsigned char verify[4096];uint64_t hash=UINT64_C(14695981039346656037);
    for(size_t offset=0;offset<length;){
        size_t wanted=length-offset;if(wanted>sizeof verify)wanted=sizeof verify;
        ssize_t n=pread(fd,verify,wanted,(off_t)offset);
        if(n<0 && errno==EINTR)continue;
        if(n<=0 || (size_t)n>wanted || memcmp(verify,p+offset,(size_t)n)){errno=EIO;goto done;}
        hash=hash_bytes(hash,verify,(size_t)n,offset);offset+=(size_t)n;
    }
    struct stat saved;
    if(hash!=le64(p+40) || fstat(fd,&saved) || saved.st_size!=(off_t)length ||
       fstatat(directory,filename,&saved,AT_SYMLINK_NOFOLLOW) || own.st_ino!=saved.st_ino ||
       own.st_dev!=saved.st_dev || saved.st_nlink!=1){errno=EIO;goto done;}
    reason="sync-file";if(fchmod(fd,0400) || sync_fd(fd))goto done;
    reason="close-file";int closing=fd;fd=-1;if(close(closing))goto done;
    reason="sync-directory";if(sync_fd(directory))goto done;rc=FULL_OSD_COMMITTED;
done:{
    int saved_errno=errno;
    if(fd>=0 && close(fd) && rc==FULL_OSD_COMMITTED)rc=FULL_OSD_IO_FAILED;
    if(created && rc!=FULL_OSD_COMMITTED){
        if(remove_partial(directory,filename,&own)){reason="partial-cleanup-failed";saved_errno=errno;}
    }
    if(directory>=0 && close(directory) && rc==FULL_OSD_COMMITTED){
        rc=FULL_OSD_IO_FAILED;reason="close-directory";saved_errno=errno;
        struct stat identity;int recovery=open_directory(path,&identity);
        if(recovery<0 || identity.st_ino!=directory_identity.st_ino || identity.st_dev!=directory_identity.st_dev ||
           remove_partial(recovery,filename,&own))reason="partial-cleanup-failed";
        if(recovery>=0 && close(recovery))reason="partial-cleanup-failed";
    }
    if(rc==FULL_OSD_COMMITTED){
        snprintf(record,sizeof record,RECORD_PREFIX "COMMIT sequence=%" PRIu64
                 " pixel_source=%" PRIu64 " id=0x%" PRIx32 " physical=0x%" PRIx64
                 " fnv1a64=%016" PRIx64 " size=%zu nonce=%s file=%s",
                 le64(p+8),le64(p+120),le32(p+16),le64(p+32),le64(p+40),length,request->nonce,filename);
    }else{
        snprintf(record,sizeof record,RECORD_PREFIX "REJECT result=%d reason=%s errno=%d"
                 " nonce=%s snapshots=%u limit=%u file=%s",rc,reason,saved_errno,
                 nonce_ok?request->nonce:"-",count,FULL_OSD_SNAPSHOT_LIMIT,filename[0]?filename:"-");
    }
    request->log(request->log_context,record);errno=saved_errno;return rc;
}}
static void capture_record(void *context,const char *record){
    void (**log)(const char *,const char *)=context;
    (*log)("OSD_IMMUTABLE_RECORD ",record);
}
int full_osd_capture_owned(const void *bytes,size_t length,void (*log)(const char *,const char *)){
    const char *enabled=getenv("FULLSYSTEM_OSD_IMMUTABLE");
    if(!enabled || strcmp(enabled,"capture"))return FULL_OSD_DISABLED;
    if(!bytes || length!=FULL_OSD_SNAPSHOT_BYTES || !log)return FULL_OSD_REJECTED;
    const unsigned char *p=bytes;
    /* Save fresh pixels only; a re-published old source is not attributable to
     * the currently active content screen. The single hosd worker owns state. */
    if(le32(p+56)!=0x1003 || le64(p+8)!=le64(p+120))return FULL_OSD_DISABLED;
    static char attempted_nonce[65];
    struct stat directory_identity,st;
    int directory=open_directory(FULL_OSD_SNAPSHOT_DIRECTORY,&directory_identity);
    if(directory<0)return FULL_OSD_NO_REQUEST;
    int fd=openat(directory,"current.nonce",O_RDONLY|O_NONBLOCK|O_NOFOLLOW|O_CLOEXEC);
    close(directory);
    if(fd<0)return FULL_OSD_NO_REQUEST;
    char mailbox[66];ssize_t used=0;
    int valid=!fstat(fd,&st) && S_ISREG(st.st_mode) && st.st_nlink==1 &&
        st.st_uid==geteuid() && !(st.st_mode&0022) && st.st_size>=2 && st.st_size<=65;
    while(valid && used<(ssize_t)sizeof mailbox){
        ssize_t n=read(fd,mailbox+used,sizeof mailbox-(size_t)used);
        if(n<0 && errno==EINTR)continue;
        if(n<0){valid=0;break;}if(!n)break;used+=n;
    }
    if(close(fd))valid=0;
    if(!valid || used<2 || used>65 || mailbox[used-1]!='\n')return FULL_OSD_REJECTED;
    mailbox[used-1]=0;
    if(!valid_nonce(mailbox))return FULL_OSD_REJECTED;
    if(!strcmp(attempted_nonce,mailbox))return FULL_OSD_DISABLED;
    struct full_osd_snapshot_request request={.enabled=1,.nonce=mailbox,
        .log=capture_record,.log_context=&log};
    int rc=full_osd_snapshot_save(bytes,length,&request);
    /* Failures are observable, not retried forever. A new explicit nonce is
     * required after failure; a request that has not arrived yet is not latched. */
    if(rc!=FULL_OSD_NO_REQUEST)memcpy(attempted_nonce,mailbox,(size_t)used);
    return rc;
}
