/* Exact 2.01 sender taps; ObjMsg remains opaque and getters run only at original calls. */
static uintptr_t msc_base,app_base;
static __thread struct {uintptr_t self,msg;uint32_t source,category;unsigned phase;} msc_context __attribute__((tls_model("initial-exec")));
static uintptr_t (*real_msc_process)(uintptr_t,uint32_t,uintptr_t);
static uint32_t (*real_configure)(uintptr_t,uintptr_t),(*real_lower)(uintptr_t,uintptr_t,uint32_t);
static void (*real_connect)(uintptr_t,int32_t,uintptr_t),(*real_ap_run)(uintptr_t),(*real_ap_send)(uintptr_t);
static uint32_t (*real_msc_mid)(uintptr_t),(*real_msc_category)(uintptr_t),(*real_check)(uintptr_t);
static uint32_t (*real_async_wait)(uintptr_t,uintptr_t,uintptr_t,uintptr_t,uintptr_t);
static uint32_t (*real_sendcmd)(uintptr_t,uintptr_t,uintptr_t),(*real_upper)(uintptr_t,uintptr_t,uint32_t);
static void sender_stack(const char *site) {
    uintptr_t fp=(uintptr_t)__builtin_frame_address(0),pair[2];
    for(unsigned i=0;i<12;i++) {
        if(!readmem(fp,pair,sizeof pair)){emit(1,"STACK_UNAVAILABLE","site=%s depth=%u fp=%#lx",site,i,fp);break;}
        emit(0,"USER_FRAME","site=%s depth=%u fp=%#lx next=%#lx lr=%#lx",site,i,fp,pair[0],pair[1]);
        if(pair[0]<=fp || pair[0]-fp>1024*1024 || (pair[0]&15))break;
        fp=pair[0];
    }
}
static uintptr_t u_msc_process(uintptr_t self,uint32_t source,uintptr_t msg) {
    int saved=errno;__typeof__(msc_context) previous=msc_context;
    msc_context.self=self;msc_context.source=source;msc_context.msg=msg;msc_context.category=0;msc_context.phase=1;
    emit(0,"MSC_PROCESS_ENTER","self=%#lx source=%#x message=%#lx lr=%p",self,source,msg,__builtin_return_address(0));
    errno=saved;uintptr_t r=real_msc_process(self,source,msg);int e=errno;
    emit(0,"MSC_PROCESS_RETURN","self=%#lx source=%#x message=%#lx rawreturn=%#lx errno=%d",self,source,msg,r,e);
    msc_context=previous;errno=e;return r;
}
static uint32_t u_msc_category(uintptr_t msg) {
    uint32_t r=real_msc_category(msg);int e=errno;
    if(msc_context.msg==msg){msc_context.category=r;emit(0,"MSC_CATEGORY","self=%#lx message=%#lx category=%#x lr=%p",msc_context.self,msg,r,__builtin_return_address(0));}
    errno=e;return r;
}
static uint32_t u_msc_mid(uintptr_t msg) {
    uint32_t r=real_msc_mid(msg);int e=errno;
    if(msc_context.msg==msg)emit(0,"MSC_MESSAGE_ID","self=%#lx source=%#x message=%#lx category=%#x id=%#x lr=%p",msc_context.self,msc_context.source,msg,msc_context.category,r,__builtin_return_address(0));
    errno=e;return r;
}
static uint32_t u_configure(uintptr_t self,uintptr_t msg) {
    int saved=errno;unsigned previous=msc_context.phase;msc_context.phase=2;
    emit(0,"MSC_CONFIGURE_ENTER","self=%#lx message=%#lx lr=%p",self,msg,__builtin_return_address(0));sender_stack("configure");
    errno=saved;uint32_t r=real_configure(self,msg);int e=errno;
    emit(0,"MSC_CONFIGURE_RETURN","self=%#lx message=%#lx rawreturn=%#x errno=%d",self,msg,r,e);msc_context.phase=previous;errno=e;return r;
}
static uint32_t u_check(uintptr_t msg) {
    int saved=errno;emit(0,"MSC_PARAMCHECK_ENTER","message=%#lx lr=%p",msg,__builtin_return_address(0));errno=saved;
    uint32_t r=real_check(msg);int e=errno;emit(0,"MSC_PARAMCHECK_RETURN","message=%#lx rawreturn=%#x errno=%d",msg,r,e);errno=e;return r;
}
static uint32_t u_async_wait(uintptr_t sender,uintptr_t msg,uintptr_t reply,uintptr_t callback,uintptr_t argument) {
    int saved=errno;emit(0,"MSC_ASYNC_WAIT_ENTER","sender=%#lx message=%#lx reply=%#lx callback=%#lx argument=%#lx phase=%u lr=%p",sender,msg,reply,callback,argument,msc_context.phase,__builtin_return_address(0));
    errno=saved;uint32_t r=real_async_wait(sender,msg,reply,callback,argument);int e=errno;
    emit(0,"MSC_ASYNC_WAIT_RETURN","sender=%#lx rawreturn=%#x errno=%d",sender,r,e);errno=e;return r;
}
static void u_connect(uintptr_t fsm,int32_t event,uintptr_t self) {
    int saved=errno;unsigned previous=msc_context.phase;msc_context.phase=3;
    emit(0,"MSC_CONNECT_ENTER","fsm=%#lx event=%d self=%#lx value468=%#x lr=%p",fsm,event,self,word(self+0x468),__builtin_return_address(0));sender_stack("connect");
    errno=saved;real_connect(fsm,event,self);int e=errno;
    emit(0,"MSC_CONNECT_RETURN","self=%#lx value468=%#x errno=%d return_type=void",self,word(self+0x468),e);msc_context.phase=previous;errno=e;
}
static uint32_t u_upper(uintptr_t self,uintptr_t msg,uint32_t id) {
    int saved=errno;emit(0,"MSC_UPPER_ENTER","self=%#lx message=%#lx id=%#x value468=%#x lr=%p",self,msg,id,word(self+0x468),__builtin_return_address(0));
    errno=saved;uint32_t r=real_upper(self,msg,id);int e=errno;
    emit(0,"MSC_UPPER_RETURN","self=%#lx id=%#x value468=%#x rawreturn=%#x errno=%d",self,id,word(self+0x468),r,e);errno=e;return r;
}
static uint32_t u_lower(uintptr_t self,uintptr_t msg,uint32_t id) {
    int saved=errno;emit(0,"MSC_LOWER_ENTER","self=%#lx message=%#lx id=%#x queue4c=%#x queue50=%#x selector58=%#x lr=%p",self,msg,id,word(self+0x4c),word(self+0x50),word(self+0x58)&65535,__builtin_return_address(0));sender_stack("lower");
    errno=saved;uint32_t r=real_lower(self,msg,id);int e=errno;
    emit(0,"MSC_LOWER_RETURN","self=%#lx id=%#x rawreturn=%#x errno=%d",self,id,r,e);errno=e;return r;
}
static uint32_t u_sendcmd(uintptr_t sender,uintptr_t msg,uintptr_t reply) {
    int saved=errno;emit(0,"MSC_SENDCMD_ENTER","sender=%#lx message=%#lx reply=%#lx phase=%u lr=%p",sender,msg,reply,msc_context.phase,__builtin_return_address(0));
    errno=saved;uint32_t r=real_sendcmd(sender,msg,reply);int e=errno;
    emit(0,"MSC_SENDCMD_RETURN","sender=%#lx rawreturn=%#x errno=%d",sender,r,e);errno=e;return r;
}
static void u_ap_run(uintptr_t self) {
    int saved=errno;emit(0,"AP_MSC_RUN_ENTER","self=%#lx lr=%p",self,__builtin_return_address(0));sender_stack("ap-run");
    errno=saved;real_ap_run(self);int e=errno;emit(0,"AP_MSC_RUN_RETURN","self=%#lx errno=%d return_type=void",self,e);errno=e;
}
static void u_ap_send(uintptr_t args) {
    int saved=errno;emit(0,"AP_MSC_SEND_ENTER","arguments=%#lx lr=%p",args,__builtin_return_address(0));blob("AP_MSC_ARRAY12",args,12);sender_stack("ap-send");
    errno=saved;real_ap_send(args);int e=errno;emit(0,"AP_MSC_SEND_RETURN","arguments=%#lx errno=%d return_type=void",args,e);errno=e;
}
