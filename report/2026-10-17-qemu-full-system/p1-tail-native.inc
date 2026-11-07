/* Original function address comes from guarded mapped body, including RTLD_LOCAL. */
static void *tail_body_original(unsigned index,const char *symbol,void *caller) {
    void *base=0;
    if(tail_pin_at(index,caller,0,&base))return (char *)base+tail_pins[index].va;
    void *fn=next(symbol);if(!fn)__builtin_trap();return fn;
}
/* Static EndUpdate(mode); return value is unspecified, so record only normal exit. */
void _ZN7Updater13BuildInPlugin9EndUpdateENS_19UPDATER_ACTION_MODEE(unsigned mode) {
    int saved=*__errno_location();void *caller=__builtin_return_address(0);
    void (*fn)(unsigned)=tail_body_original(10,"_ZN7Updater13BuildInPlugin9EndUpdateENS_19UPDATER_ACTION_MODEE",caller);
    int observe=tail_site(10,caller,0x129d8);char line[100];snprintf(line,sizeof line,"mode=%u result=void native_calls=1",mode);
    if(observe)tail_emit(T_END,"EndUpdate-start",line,0,saved,caller);
    *__errno_location()=saved;fn(mode);int error=*__errno_location();
    if(observe)tail_emit(T_END,"EndUpdate-return",line,0,error,caller);
    *__errno_location()=error;
}
void _ZN7Updater30FlagFirmwareInformationHandler14CompleteUpdateERKN10UpdaterAPI22firmware_information_t11informationE(void *object,const void *information) {
    int saved=*__errno_location();void *caller=__builtin_return_address(0);
    void (*fn)(void *,const void *)=tail_body_original(11,"_ZN7Updater30FlagFirmwareInformationHandler14CompleteUpdateERKN10UpdaterAPI22firmware_information_t11informationE",caller);
    int observe=tail_site(11,caller,0x129e4);char line[180];snprintf(line,sizeof line,"this=%p information=%p layout=opaque native_calls=1",object,information);
    if(observe)tail_emit(T_END,"CompleteUpdate-start",line,0,saved,caller);
    *__errno_location()=saved;fn(object,information);int error=*__errno_location();
    if(observe)tail_emit(T_END,"CompleteUpdate-return",line,0,error,caller);
    *__errno_location()=error;
}
void _ZN7Updater12ThreadPlugin8setErrorEv(void *object) {
    int saved=*__errno_location();void *caller=__builtin_return_address(0);
    void (*fn)(void *)=tail_body_original(12,"_ZN7Updater12ThreadPlugin8setErrorEv",caller);
    int observe=tail_site(12,caller,0x191a4) || tail_site(12,caller,0x19200);
    *__errno_location()=saved;fn(object);int error=*__errno_location();
    if(observe)tail_emit(T_PLUGIN,"thread-set-error","result=void original_calls=1 layout=opaque",0,error,caller);
    *__errno_location()=error;
}
unsigned char _ZN7Updater12ThreadPlugin8HasErrorEv(void *object) {
    int saved=*__errno_location();void *caller=__builtin_return_address(0);
    unsigned char (*fn)(void *)=tail_body_original(13,"_ZN7Updater12ThreadPlugin8HasErrorEv",caller);
    int observe=tail_site(13,caller,0x129c8);
    *__errno_location()=saved;unsigned char rc=fn(object);int error=*__errno_location();
    if(observe)tail_emit(T_PLUGIN,"thread-has-error","original_calls=1 layout=opaque",rc,error,caller);
    *__errno_location()=error;return rc;
}
