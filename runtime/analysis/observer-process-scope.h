#ifndef A7C2_OBSERVER_PROCESS_SCOPE_H
#define A7C2_OBSERVER_PROCESS_SCOPE_H
/* Callers supply the actual /proc/self/exe bytes, never argv[0] or comm. */
static int menu_crypto_process_path(const char *path, long length)
{
    static const char boot[]="/usr/bin/bootin.elf";
    static const char im[]="/usr/bin/im.elf";
    static const char original[]="/simulation/bootin-original";
    return path && ((length==(long)sizeof boot-1 && !memcmp(path,boot,sizeof boot-1)) ||
                    (length==(long)sizeof im-1 && !memcmp(path,im,sizeof im-1)) ||
                    (length==(long)sizeof original-1 && !memcmp(path,original,sizeof original-1)));
}
static int menu_crypto_load_request(const char *path,long length,const char *library)
{
    return menu_crypto_process_path(path,length) && library &&
        (!__builtin_strcmp(library,"appFw.so") || !__builtin_strcmp(library,"/usr/lib/appFw.so"));
}
#endif
