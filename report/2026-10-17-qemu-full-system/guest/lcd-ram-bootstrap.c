/* SPDX-License-Identifier: MIT */
#define _GNU_SOURCE
#include <dirent.h>
#include <errno.h>
#include <fcntl.h>
#include <stddef.h>
#include <stdio.h>
#include <string.h>
#include <sys/mount.h>
#include <sys/stat.h>
#include <sys/statfs.h>
#include <unistd.h>

/* Sony glibc 2.25 exports the versioned stat ABI, not modern fstat/lstat. */
#if defined(__aarch64__) && !defined(LCD_RAM_BOOTSTRAP_HOST_TEST)
_Static_assert(sizeof(struct stat)==128 && offsetof(struct stat,st_mode)==16 &&
               offsetof(struct stat,st_uid)==24 && offsetof(struct stat,st_size)==48,
               "unexpected Sony arm64 stat layout");
extern int __fxstat(int, int, struct stat *);
extern int __lxstat(int, const char *, struct stat *);
static int guest_fstat(int fd, struct stat *st) { return __fxstat(0,fd,st); }
static int guest_lstat(const char *path, struct stat *st) { return __lxstat(0,path,st); }
#define fstat guest_fstat
#define lstat guest_lstat
#endif

/* The injected adapters exist only in the host test's generated directory. */
#ifdef LCD_RAM_BOOTSTRAP_HOST_TEST
#include LCD_RAM_BOOTSTRAP_HOST_TEST
#endif

#define RAM_DIR "/dev/qemu-lcd"
#define RAM_LOG RAM_DIR "/menu-load.log"
#define OLD_LOG "/tmp/menu-load.log"
#define PROJECT_LOG "/log/qemu/menu-load.log"
static const char ordinary_log[]=OLD_LOG,project_log[]=PROJECT_LOG;
static const char *log_target=ordinary_log;
static struct stat log_link,log_parent,qemu_parent;
#define PROC_LIMIT 65536
#define LINE_LIMIT 4096
#define TMPFS_MAGIC 0x01021994
static char proc_text[PROC_LIMIT+1];

static int fail(const char *reason, int error) {
    fprintf(stderr,"lcd-ram-bootstrap: %s errno=%d (%s)\n",reason,error,strerror(error));
    printf("FULLSYSTEM_LCD_RAM_FAILED=%s\n",reason);
    fflush(stdout);
    return -1;
}

static int read_proc(const char *path) {
    int fd=open(path,O_RDONLY|O_NOFOLLOW|O_CLOEXEC);
    if(fd<0) return fail("proc-open",errno);
    size_t used=0;
    for(;;) {
        ssize_t n=read(fd,proc_text+used,sizeof(proc_text)-used);
        if(n<0 && errno==EINTR) continue;
        if(n<0) { int e=errno; close(fd); return fail("proc-read",e); }
        if(!n) break;
        used+=(size_t)n;
        if(used>PROC_LIMIT) { close(fd); return fail("proc-size",EOVERFLOW); }
    }
    if(close(fd)) return fail("proc-close",errno);
    if(!used || proc_text[used-1]!='\n' || memchr(proc_text,0,used))
        return fail("proc-format",EINVAL);
    proc_text[used]=0;
    return 0;
}

static char *next_line(char **cursor) {
    char *line=*cursor;
    if(!*line) return NULL;
    char *end=strchr(line,'\n');
    if(!end || (size_t)(end-line)>LINE_LIMIT) {
        fail("proc-line",EOVERFLOW);
        *cursor=NULL;
        return NULL;
    }
    *end=0; *cursor=end+1;
    return line;
}

static int words(char *line, char **word, int capacity) {
    int n=0;
    for(char *p=line; *p;) {
        while(*p==' ' || *p=='\t') p++;
        if(!*p) break;
        if(n==capacity) return -1;
        word[n++]=p;
        while(*p && *p!=' ' && *p!='\t') {
            if((unsigned char)*p<33 || (unsigned char)*p>126) return -1;
            p++;
        }
        if(*p) *p++=0;
    }
    return n;
}

static int check_root(void) {
    if(read_proc("/proc/self/status")) return -1;
    int uid=0,gid=0,bad=0;
    char *cursor=proc_text,*line;
    while((line=next_line(&cursor))) {
        int is_uid=!strncmp(line,"Uid:",4),is_gid=!strncmp(line,"Gid:",4);
        if(!is_uid && !is_gid) continue;
        printf("FULLSYSTEM_LCD_RAM_ROOT %s\n",line);
        char *w[6]; int n=words(line,w,6);
        if(is_uid) uid++; else gid++;
        if(n!=5 || strcmp(w[0],is_uid ? "Uid:" : "Gid:")) { bad=1; continue; }
        for(int i=1;i<5;i++) if(strcmp(w[i],"0")) bad=1;
    }
    if(!cursor) return -1;
    return uid==1 && gid==1 && !bad ? 0 : fail("root",EPERM);
}

static int digits(const char *p) {
    if(!*p) return 0;
    for(;*p;p++) if(*p<'0' || *p>'9') return 0;
    return 1;
}

static int valid_path(const char *p) {
    if(*p!='/') return 0;
    for(;*p;p++) if(*p=='\\') {
        if(strncmp(p,"\\040",4) && strncmp(p,"\\011",4) &&
           strncmp(p,"\\012",4) && strncmp(p,"\\134",4)) return 0;
        p+=3;
    }
    return 1;
}

static int rw_options(const char *options) {
    int rw=0;
    for(const char *p=options; *p;) {
        const char *end=strchr(p,','); size_t n=end ? (size_t)(end-p) : strlen(p);
        if(!n) return 0;
        if(n==2 && !memcmp(p,"ro",2)) return 0;
        if(n==2 && !memcmp(p,"rw",2)) rw++;
        if(!end) break;
        p=end+1;
        if(!*p) return 0;
    }
    return rw==1;
}

static int at_or_below(const char *path,const char *base) {
    size_t n=strlen(base);
    return !strncmp(path,base,n) && (!path[n] || path[n]=='/');
}

static int check_mounts(int bound) {
    if(read_proc("/proc/self/mountinfo")) return -1;
    int dev=0,log=0;
    char *cursor=proc_text,*line;
    while((line=next_line(&cursor))) {
        char raw[LINE_LIMIT+1],*w[128];
        memcpy(raw,line,strlen(line)+1);
        int n=words(line,w,128),sep=6;
        if(n<10) return fail("mountinfo-format",EINVAL);
        while(sep<n && strcmp(w[sep],"-")) sep++;
        if(sep+4!=n || !digits(w[0]) || !digits(w[1]) ||
           !valid_path(w[3]) || !valid_path(w[4])) return fail("mountinfo-format",EINVAL);
        char *colon=strchr(w[2],':');
        if(!colon) return fail("mountinfo-format",EINVAL);
        *colon=0;
        if(!digits(w[2]) || !digits(colon+1)) return fail("mountinfo-format",EINVAL);
        if(at_or_below(w[4],RAM_DIR) ||
           (at_or_below(w[4],OLD_LOG) && strcmp(w[4],log_target)) ||
           (at_or_below(w[4],PROJECT_LOG) && strcmp(w[4],log_target)))
            return fail("mountinfo",EBUSY);
        if(!strcmp(w[4],"/dev")) {
            if(!bound) printf("FULLSYSTEM_LCD_RAM_MOUNTINFO %s\n",raw);
            dev++;
            if(strcmp(w[3],"/") || !rw_options(w[5]) ||
               strcmp(w[sep+1],"devtmpfs") || !rw_options(w[sep+3]))
                return fail("mountinfo",EINVAL);
        }
        if(!strcmp(w[4],log_target)) {
            log++;
            if(!bound) return fail("mountinfo",EBUSY);
            printf("FULLSYSTEM_LCD_RAM_LOG_MOUNTINFO %s\n",raw);
            if(strcmp(w[3],"/qemu-lcd/menu-load.log") || !rw_options(w[5]) ||
               strcmp(w[sep+1],"devtmpfs") || !rw_options(w[sep+3]))
                return fail("log-mountinfo",EINVAL);
        }
    }
    if(!cursor) return -1;
    if(dev!=1) return fail("mountinfo",EINVAL);
    return log==bound ? 0 : fail("log-mountinfo",EINVAL);
}

static int same_inode(const struct stat *a,const struct stat *b) {
    return a->st_dev==b->st_dev && a->st_ino==b->st_ino &&
           a->st_mode==b->st_mode && a->st_uid==b->st_uid && a->st_gid==b->st_gid &&
           a->st_size==b->st_size && a->st_nlink==b->st_nlink;
}

static int checked_fd(int fd,const char *path,struct stat *st,const char *reason) {
    struct stat named;
    if(fstat(fd,st) || lstat(path,&named)) return fail(reason,errno);
    return same_inode(st,&named) ? 0 : fail(reason,ESTALE);
}

static int directory(const char *path,const char *reason,struct stat *st) {
    if(lstat(path,st)) return fail(reason,errno);
    if(!S_ISDIR(st->st_mode) || st->st_uid || st->st_gid) return fail(reason,EPERM);
    int fd=open(path,O_RDONLY|O_DIRECTORY|O_NOFOLLOW|O_CLOEXEC);
    if(fd<0) return fail(reason,errno);
    struct stat opened;
    if(checked_fd(fd,path,&opened,reason)) { close(fd); return -1; }
    if(!same_inode(st,&opened)) { close(fd); return fail(reason,ESTALE); }
    return fd;
}

static int check_log_link(void) {
    struct stat before,after;
    char text[sizeof(PROJECT_LOG)];
    if(lstat(OLD_LOG,&before)) return fail("log-route-stat",errno);
    if(!S_ISLNK(before.st_mode) || before.st_uid || before.st_gid ||
       !same_inode(&log_link,&before)) return fail("log-route-changed",ESTALE);
    ssize_t n=readlink(OLD_LOG,text,sizeof(text));
    if(n<0) return fail("log-route-readlink",errno);
    if(n!=(ssize_t)(sizeof(PROJECT_LOG)-1) || memcmp(text,PROJECT_LOG,sizeof(PROJECT_LOG)-1))
        return fail("log-symlink",ELOOP);
    if(lstat(OLD_LOG,&after)) return fail("log-route-stat",errno);
    return same_inode(&log_link,&after) ? 0 : fail("log-route-changed",ESTALE);
}

static int check_log_route(void) {
    if(log_target==ordinary_log) return 0;
    const char *paths[]={"/log","/log/qemu"};
    const struct stat *expected[]={&log_parent,&qemu_parent};
    for(int i=0;i<2;i++) {
        struct stat st;
        int fd=directory(paths[i],"log-parent",&st);
        if(fd<0) return -1;
        close(fd);
        if(st.st_dev!=expected[i]->st_dev || st.st_ino!=expected[i]->st_ino)
            return fail("log-parent-changed",ESTALE);
    }
    return check_log_link();
}

static int choose_log_target(void) {
    log_target=ordinary_log;
    if(lstat(OLD_LOG,&log_link))
        return errno==ENOENT ? 0 : fail("log-stat",errno);
    if(!S_ISLNK(log_link.st_mode)) return 0;
    if(check_log_link()) return -1;
    int fd=directory("/log","log-parent",&log_parent);
    if(fd<0) return -1;
    close(fd);
    fd=directory("/log/qemu","log-parent",&qemu_parent);
    if(fd<0) return -1;
    close(fd);
    log_target=project_log;
    return check_log_route();
}

static int empty_directory(int fd) {
    int copy=dup(fd);
    if(copy<0) return fail("directory-list",errno);
    DIR *dir=fdopendir(copy);
    if(!dir) { int e=errno; close(copy); return fail("directory-list",e); }
    errno=0;
    struct dirent *entry;
    while((entry=readdir(dir))) {
        if(strcmp(entry->d_name,".") && strcmp(entry->d_name,"..")) {
            closedir(dir); return fail("directory-not-empty",EBUSY);
        }
    }
    int e=errno;
    if(closedir(dir) && !e) e=errno;
    return e ? fail("directory-list",e) : 0;
}

static int empty_log(const struct stat *st,const char *reason) {
    if(!S_ISREG(st->st_mode) || st->st_nlink!=1 || st->st_uid || st->st_gid)
        return fail(reason,EPERM);
    return st->st_size==0 ? 0 : fail("log-nonempty-preserved",EBUSY);
}

static int eof_readback(int fd) {
    char byte; ssize_t n;
    do n=pread(fd,&byte,1,0); while(n<0 && errno==EINTR);
    if(n<0) return fail("log-readback",errno);
    return n==0 ? 0 : fail("log-readback",EIO);
}

static int open_log_target(void) {
    struct stat original,st;
    int flags=O_RDWR|O_NOFOLLOW|O_CLOEXEC;
    if(check_log_route()) return -1;
    if(lstat(log_target,&original)) {
        if(errno!=ENOENT) return fail("log-stat",errno);
        flags|=O_CREAT|O_EXCL;
    } else {
        if(S_ISLNK(original.st_mode)) return fail("log-symlink",ELOOP);
        if(empty_log(&original,"log-type-owner-links")) return -1;
    }
    int fd=open(log_target,flags,0600);
    if(fd<0) return fail("log-target-open",errno);
    if((flags&O_CREAT) && fchmod(fd,0600)) {
        int e=errno; close(fd); return fail("log-target-mode",e);
    }
    if(checked_fd(fd,log_target,&st,"log-target-inode") ||
       empty_log(&st,"log-type-owner-links") || check_log_route()) { close(fd); return -1; }
    if(!(flags&O_CREAT) && !same_inode(&original,&st)) {
        close(fd); return fail("log-target-inode",ESTALE);
    }
    return fd;
}

static int check_log_alias(const struct stat *source) {
    if(check_log_route()) return -1;
    int fd=open(OLD_LOG,O_RDONLY|O_CLOEXEC|(log_target==ordinary_log ? O_NOFOLLOW : 0));
    if(fd<0) return fail("log-alias-open",errno);
    struct stat st;
    int rc=fstat(fd,&st) ? fail("log-alias-stat",errno) :
           !same_inode(source,&st) ? fail("log-alias-inode",ESTALE) : eof_readback(fd);
    close(fd);
    return rc ? rc : check_log_route();
}

static int run(int argc,char **argv) {
    (void)argc; (void)argv;
    if(check_root()) return 1;
    struct stat st,dev_st,ram_st,source,target;
    int root=directory("/","root-directory",&st);
    if(root<0) return 1;
    close(root);
    int dev=directory("/dev","dev-directory",&dev_st);
    if(dev<0) return 1;
    struct statfs fs;
    if(statfs("/dev",&fs)) return fail("dev-statfs",errno),1;
    if((unsigned long)fs.f_type!=TMPFS_MAGIC) return fail("dev-not-ram",EINVAL),1;
    int tmp=directory("/tmp","tmp-directory",&st);
    if(tmp<0 || choose_log_target() || check_mounts(0)) return 1;
    if(lstat(RAM_DIR,&st)) {
        if(errno!=ENOENT) return fail("directory-stat",errno),1;
        if(mkdir(RAM_DIR,0700)) return fail("mkdir",errno),1;
    } else {
        if(S_ISLNK(st.st_mode)) return fail("directory-symlink",ELOOP),1;
        if(!S_ISDIR(st.st_mode)) return fail("directory-type",ENOTDIR),1;
        if(st.st_uid || st.st_gid) return fail("directory-owner",EPERM),1;
    }
    int ram=directory(RAM_DIR,"directory-stat",&ram_st);
    if(ram<0 || empty_directory(ram)) return 1;
    if(ram_st.st_dev!=dev_st.st_dev) return fail("directory-device",EXDEV),1;
    if(fchmod(ram,0700)) return fail("directory-mode",errno),1;
    if(checked_fd(ram,RAM_DIR,&st,"directory-inode")) return 1;
    if(st.st_dev!=ram_st.st_dev || st.st_ino!=ram_st.st_ino ||
       !S_ISDIR(st.st_mode) || (st.st_mode&07777)!=0700 || st.st_uid || st.st_gid)
        return fail("directory-mode",EPERM),1;
    if(statfs(RAM_DIR,&fs)) return fail("ram-statfs",errno),1;
    if((unsigned long)fs.f_type!=TMPFS_MAGIC) return fail("directory-not-ram",EINVAL),1;
    printf("FULLSYSTEM_LCD_RAM_STAT=%lx:%lu:%llu:%llu mode=700:0:0\n",
           (unsigned long)fs.f_type,(unsigned long)fs.f_frsize,
           (unsigned long long)fs.f_blocks,(unsigned long long)fs.f_bfree);
    int old=open_log_target();
    if(old<0) return 1;
    int file=open(RAM_LOG,O_RDWR|O_CREAT|O_EXCL|O_NOFOLLOW|O_CLOEXEC,0600);
    if(file<0) return fail("log-ram-create",errno),1;
    if(fchmod(file,0600) || fsync(file)) return fail("log-ram-mode-sync",errno),1;
    if(checked_fd(file,RAM_LOG,&source,"log-ram-inode") || empty_log(&source,"log-ram-type-owner-links")) return 1;
    if((source.st_mode&07777)!=0600 || source.st_dev!=ram_st.st_dev)
        return fail("log-ram-mode-device",EPERM),1;
    if(check_log_route() || checked_fd(old,log_target,&st,"log-target-inode") ||
       empty_log(&st,"log-type-owner-links")) return 1;
    if(mount(RAM_LOG,log_target,NULL,MS_BIND,NULL)) return fail("log-bind",errno),1;
    /* Any later failure preserves the bind and both files for the original owner. */
    if(check_log_route()) return 1;
    int bound=open(log_target,O_RDONLY|O_NOFOLLOW|O_CLOEXEC);
    if(bound<0) return fail("log-bound-open",errno),1;
    if(checked_fd(file,RAM_LOG,&st,"log-ram-inode") ||
       checked_fd(bound,log_target,&target,"log-bound-inode")) return 1;
    if(!same_inode(&source,&st) || !same_inode(&source,&target))
        return fail("log-inode",ESTALE),1;
    if(eof_readback(file) || eof_readback(bound) || check_log_alias(&source) ||
       check_mounts(1) || check_log_route()) return 1;
    printf("FULLSYSTEM_LCD_RAM_LOG_ROUTE logical=%s actual=%s route=%s verified=readlink-inode-eof\n",
           OLD_LOG,log_target,log_target==project_log ? "known-logical-symlink" : "ordinary-file");
    printf("FULLSYSTEM_LCD_RAM_LOG_INODE=%llu:%llu:%o:%u:%u:%lld readback=eof-equal-0bytes\n",
           (unsigned long long)source.st_dev,(unsigned long long)source.st_ino,
           source.st_mode&07777,source.st_uid,source.st_gid,(long long)source.st_size);
    puts("FULLSYSTEM_LCD_RAM_PROFILE=ram-snapshot-v1 path=/dev/qemu-lcd/headless-osd-frame.bin log=/tmp/menu-load.log");
    close(bound); close(file); close(old); close(ram); close(tmp); close(dev);
    return 0;
}

#if defined(__aarch64__) && !defined(LCD_RAM_BOOTSTRAP_HOST_TEST)
extern int __libc_start_main(int (*)(int,char **),int,char **,void (*)(void),void (*)(void),void (*)(void),void *);
__asm__(".global _start\n.type _start,%function\n_start:\nmov x0,sp\nbl entry\nbrk #0\n");
__attribute__((noreturn)) void entry(unsigned long *stack) {
    __libc_start_main(run,(int)stack[0],(char **)(stack+1),0,0,0,stack);
    __builtin_trap();
}
#else
int main(int argc,char **argv) { return run(argc,argv); }
#endif
