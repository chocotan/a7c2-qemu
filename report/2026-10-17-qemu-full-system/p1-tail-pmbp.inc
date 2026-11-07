/* LP64 signatures from pmbp-candidate.h/pmbp-libc.h; caller is captured by each exported frame. */
extern int *__errno_location(void);
extern char *getenv(const char *);
extern int strcmp(const char *,const char *);
static void *next(const char *);
static int tail_pmbp_selected(void) {
    const char *value=getenv("A7C2_P1_TAIL_PMBP_PROFILE");
    if(!value)return 0;
    if(!strcmp(value,"virtual-p1-pmbp-block-slice-v1"))return 1;
    *__errno_location()=71;return -1;
}
static void *tail_pmbp_entry(const char *symbol) {
    int saved=*__errno_location();
    const void *(*native)(void)=next("pmbp_native_io");
    void *entry=next(symbol);
    if(!native || !entry || !native()){*__errno_location()=71;return 0;}
    *__errno_location()=saved;return entry;
}
static long tail_pmbp_write(int fd,const void *data,unsigned long bytes,void *caller) {
    int selected=tail_pmbp_selected();if(selected<0)return -1;
    if(!selected){long (*fn)(int,const void *,unsigned long)=next("write");if(!fn){*__errno_location()=71;return -1;}return fn(fd,data,bytes);}
    long (*fn)(int,const void *,unsigned long,unsigned long)=tail_pmbp_entry("pmbp_write_at");
    return fn?fn(fd,data,bytes,(unsigned long)caller):-1;
}
static int tail_pmbp_close(int fd,void *caller) {
    int selected=tail_pmbp_selected();if(selected<0)return -1;
    if(!selected){int (*fn)(int)=next("close");if(!fn){*__errno_location()=71;return -1;}return fn(fd);}
    int (*fn)(int,unsigned long)=tail_pmbp_entry("pmbp_close_at");
    return fn?fn(fd,(unsigned long)caller):-1;
}
