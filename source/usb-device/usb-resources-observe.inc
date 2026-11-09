/* Passive resource boundary taps, selected only by the existing private diagnostics. */
static unsigned resource_records,resource_rpc_serial;
static int resource_live(void) {return __atomic_load_n(&resource_records,__ATOMIC_RELAXED)<64;}
static int resource_emit(const char *kind,const char *format,...) {
    int saved=errno;char line[512];
    unsigned n=__atomic_load_n(&resource_records,__ATOMIC_RELAXED);
    do {if(n>=64){errno=saved;return 0;}}
    while(!__atomic_compare_exchange_n(&resource_records,&n,n+1,1,__ATOMIC_RELAXED,__ATOMIC_RELAXED));
    int prefix=snprintf(line,sizeof line,"USB_START RESOURCE_%s pid=%ld tid=%ld ",kind,(long)getpid(),syscall(SYS_gettid));
    va_list args;va_start(args,format);
    int used=vsnprintf(line+prefix,sizeof line-(size_t)prefix-2,format,args);va_end(args);
    int complete=used>=0&&(size_t)used<sizeof line-(size_t)prefix-2;
    size_t size=strlen(line);line[size++]='\n';
    int written=logfd>=0&&syscall(SYS_write,logfd,line,size)==(ssize_t)size;
    if(n==63&&logfd>=0)syscall(SYS_write,logfd,"USB_START RESOURCE_CAP records=64\n",sizeof("USB_START RESOURCE_CAP records=64\n")-1);
    errno=saved;return complete&&written;
}
static int resource_bytes(uintptr_t address,unsigned bytes,char hex[225]) {
    unsigned char raw[112];hex[0]=0;
    if(!resource_live()||!bytes||bytes>sizeof raw||!readmem(address,raw,bytes))return 0;
    for(unsigned i=0;i<bytes;i++)snprintf(hex+2*i,3,"%02x",raw[i]);
    return 1;
}
static uint32_t (*real_storage_create)(uintptr_t,uintptr_t,uintptr_t,uintptr_t);
static uint32_t (*real_sen_create)(uintptr_t,uintptr_t,uintptr_t,uintptr_t);
static uint32_t (*real_gadget_create)(uintptr_t,uintptr_t,uintptr_t,uintptr_t);
static uint32_t u_storage_create(uintptr_t self,uintptr_t svc,uintptr_t reg,uintptr_t info) {
    int saved=errno;resource_emit("STORAGE_CREATE_ENTER","self=%#lx svc=%#lx reg=%#lx info=%#lx",self,svc,reg,info);errno=saved;
    uint32_t r=real_storage_create(self,svc,reg,info);int e=errno;
    resource_emit("STORAGE_CREATE_RETURN","self=%#lx rc=%#x errno=%d",self,r,e);errno=e;return r;
}
static uint32_t u_sen_create(uintptr_t self,uintptr_t svc,uintptr_t reg,uintptr_t info) {
    int saved=errno;resource_emit("SEN_CREATE_ENTER","self=%#lx svc=%#lx reg=%#lx info=%#lx",self,svc,reg,info);errno=saved;
    uint32_t r=real_sen_create(self,svc,reg,info);int e=errno;
    resource_emit("SEN_CREATE_RETURN","self=%#lx rc=%#x errno=%d",self,r,e);errno=e;return r;
}
static uint32_t u_gadget_create(uintptr_t self,uintptr_t svc,uintptr_t reg,uintptr_t info) {
    int saved=errno;resource_emit("GADGET_CREATE_ENTER","self=%#lx svc=%#lx reg=%#lx info=%#lx",self,svc,reg,info);errno=saved;
    uint32_t r=real_gadget_create(self,svc,reg,info);int e=errno;
    resource_emit("GADGET_CREATE_RETURN","self=%#lx rc=%#x errno=%d",self,r,e);errno=e;return r;
}
static uint32_t (*real_sync_startstop)(uintptr_t,uint32_t,int32_t,int32_t,int32_t);
static uint32_t u_sync_startstop(uintptr_t self,uint32_t op,int32_t a,int32_t b,int32_t c) {
    int saved=errno;
    if(resource_live())resource_emit("SYNC_ENTER","self=%#lx op=%u a=%d b=%d c=%d qid_raw=%#x",self,op,a,b,c,control_base?word(control_base+0x30a68):UINT32_MAX);
    errno=saved;uint32_t r=real_sync_startstop(self,op,a,b,c);int e=errno;
    resource_emit("SYNC_RETURN","self=%#lx rc=%#x errno=%d",self,r,e);errno=e;return r;
}
static uint32_t (*real_wrapper_start)(uintptr_t,int32_t,int32_t);
static uint32_t (*real_do_start)(uintptr_t,int32_t,int32_t,int32_t);
static uint32_t u_wrapper_start(uintptr_t self,int32_t functions,int32_t port) {
    int saved=errno;resource_emit("WRAPPER_START_ENTER","self=%#lx functions=%d port=%d",self,functions,port);errno=saved;
    uint32_t r=real_wrapper_start(self,functions,port);int e=errno;
    resource_emit("WRAPPER_START_RETURN","self=%#lx rc=%#x errno=%d",self,r,e);errno=e;return r;
}
static uint32_t u_do_start(uintptr_t self,int32_t did,int32_t port,int32_t mode) {
    int saved=errno;
    if(resource_live())resource_emit("DO_START_ENTER","self=%#lx did=%d port=%d mode=%d qid_raw=%#x",self,did,port,mode,control_base?word(control_base+0x30a68):UINT32_MAX);
    errno=saved;uint32_t r=real_do_start(self,did,port,mode);int e=errno;
    resource_emit("DO_START_RETURN","self=%#lx rc=%#x errno=%d",self,r,e);errno=e;return r;
}
static void (*real_control_configure)(uintptr_t,int32_t,uintptr_t);
static void (*real_control_start)(uintptr_t,int32_t,uintptr_t);
static void (*real_control_start_entry)(uintptr_t,int32_t,uintptr_t);
static void u_control_configure(uintptr_t fsm,int32_t event,uintptr_t self) {
    int saved=errno;resource_emit("CONTROL_CONFIGURE_ENTER","fsm=%#lx event=%d self=%#lx",fsm,event,self);errno=saved;
    real_control_configure(fsm,event,self);int e=errno;
    resource_emit("CONTROL_CONFIGURE_RETURN","self=%#lx return_type=void errno=%d",self,e);errno=e;
}
static void u_control_start(uintptr_t fsm,int32_t event,uintptr_t self) {
    int saved=errno;resource_emit("CONTROL_START_ENTER","fsm=%#lx event=%d self=%#lx",fsm,event,self);errno=saved;
    real_control_start(fsm,event,self);int e=errno;
    resource_emit("CONTROL_START_RETURN","self=%#lx return_type=void errno=%d",self,e);errno=e;
}
static void u_control_start_entry(uintptr_t fsm,int32_t event,uintptr_t self) {
    int saved=errno;resource_emit("CONTROL_START_ENTRY_ENTER","fsm=%#lx event=%d self=%#lx",fsm,event,self);errno=saved;
    real_control_start_entry(fsm,event,self);int e=errno;
    resource_emit("CONTROL_START_ENTRY_RETURN","self=%#lx return_type=void errno=%d",self,e);errno=e;
}
/* usb_hndl_t is unsigned long; the event and speed parameters are unsigned char. */
static void (*real_gadget_event)(uintptr_t,uint8_t,uint8_t,uintptr_t);
static void (*real_svc_notify)(uintptr_t,uint32_t,uintptr_t,uint8_t);
static void u_gadget_event(uintptr_t handle,uint8_t event,uint8_t speed,uintptr_t argument) {
    int saved=errno;resource_emit("GADGET_EVENT_ENTER","handle=%#lx event=%u speed=%u argument=%#lx",handle,event,speed,argument);errno=saved;
    real_gadget_event(handle,event,speed,argument);int e=errno;
    resource_emit("GADGET_EVENT_RETURN","handle=%#lx event=%u return_type=void errno=%d",handle,event,e);errno=e;
}
static void u_svc_notify(uintptr_t self,uint32_t event,uintptr_t argument,uint8_t speed) {
    int saved=errno;resource_emit("SVC_NOTIFY_ENTER","self=%#lx event=%u argument=%#lx speed=%u",self,event,argument,speed);errno=saved;
    real_svc_notify(self,event,argument,speed);int e=errno;
    resource_emit("SVC_NOTIFY_RETURN","self=%#lx event=%u return_type=void errno=%d",self,event,e);errno=e;
}
static uint32_t (*real_ko_insmod)(uintptr_t,uintptr_t,uintptr_t);
static uint32_t u_ko_insmod(uintptr_t self,uintptr_t path,uintptr_t parameters) {
    int saved=errno;char p[128]={0},a[128]={0};unsigned pn=0,an=0;
    if(resource_live()){
        pn=cstring((const char *)path,p,sizeof p);an=cstring((const char *)parameters,a,sizeof a);
        char ph[257]={0},ah[257]={0};
        if(pn)for(size_t i=0;i<strlen(p);i++)snprintf(ph+2*i,3,"%02x",(unsigned char)p[i]);
        if(an)for(size_t i=0;i<strlen(a);i++)snprintf(ah+2*i,3,"%02x",(unsigned char)a[i]);
        resource_emit("MODULE_ENTER","self=%#lx path_ptr=%#lx parameters_ptr=%#lx",self,path,parameters);
        resource_emit("MODULE_PATH","path_ptr=%#lx read=%u raw=%s",path,pn,pn?(*p?ph:"empty"):"unavailable");
        resource_emit("MODULE_PARAMETERS","parameters_ptr=%#lx read=%u raw=%s",parameters,an,an?(*a?ah:"empty"):"unavailable");
    }
    errno=saved;uint32_t r=real_ko_insmod(self,path,parameters);int e=errno;
    resource_emit("MODULE_RETURN","self=%#lx rc=%#x errno=%d registration_proven=0",self,r,e);errno=e;return r;
}
static void resource_ioctl(int fd,unsigned long req,uintptr_t arg,int returning,int rc,int error) {
    int saved=errno;char name[64],path[256];
    if(!resource_live()){errno=saved;return;}
    snprintf(name,sizeof name,"/proc/self/fd/%d",fd);
    long n=syscall(SYS_readlinkat,AT_FDCWD,name,path,sizeof path-1);
    if(n<0){strcpy(path,"unknown");}else{path[n]=0;}
    if(returning)resource_emit("IOCTL_RETURN","fd=%d path=%s req=%#lx arg=%#lx rc=%d errno=%d",fd,path,req,arg,rc,error);
    else {
        resource_emit("IOCTL_ENTER","fd=%d path=%s req=%#lx arg=%#lx",fd,path,req,arg);
        /* LP64 headers bind exactly these input sizes; descriptor data stays on EP0. */
        unsigned bytes=req==0x4038e201?56:req==0x4070e000?112:0;
        if(bytes&&resource_live()){
            char hex[225];int ok=resource_bytes(arg,bytes,hex);
            resource_emit("PROBE_INPUT","fd=%d req=%#lx argument=%#lx bytes=%u read=%d raw=%s",fd,req,arg,bytes,ok,ok?hex:"unavailable");
        }
    }
    errno=saved;
}
/* Only the original synchronous 0146/0429 shapes are inspected; no extra OSAL getters. */
struct resource_rpc_scope {unsigned serial,valid;uintptr_t response;};
struct resource_rpc_ticket {unsigned serial,valid;uint32_t owner;uintptr_t message;};
static __thread struct resource_rpc_scope resource_rpc __attribute__((tls_model("initial-exec")));
static void (*real_resource_rpc)(uint32_t,uintptr_t,int32_t,uintptr_t,int32_t);
static void u_resource_rpc(uint32_t destination,uintptr_t request,int32_t bytes,uintptr_t response,int32_t reply_bytes) {
    int saved=errno;struct resource_rpc_scope previous=resource_rpc;
    memset(&resource_rpc,0,sizeof resource_rpc);
    if(destination==0x92840747&&bytes==10&&reply_bytes==12&&resource_live()){
        char hex[225];int ok=resource_bytes(request,10,hex);
        if(ok&&(!strncmp(hex,"0d2046010a000180",16)||!strncmp(hex,"0d2029040a000180",16))&&(!strcmp(hex+16,"0000")||!strcmp(hex+16,"0100"))){
            resource_rpc.serial=__atomic_add_fetch(&resource_rpc_serial,1,__ATOMIC_RELAXED);
            resource_rpc.response=response;
            resource_rpc.valid=resource_emit("RPC_ENTER","serial=%u destination=%#x request=%#lx bytes=%d response=%#lx reply_bytes=%d raw=%s caller=%p",resource_rpc.serial,destination,request,bytes,response,reply_bytes,hex,__builtin_return_address(0));
        }
    }
    errno=saved;real_resource_rpc(destination,request,bytes,response,reply_bytes);int e=errno;
    if(resource_rpc.valid&&resource_live()){
        char hex[225];int ok=resource_bytes(response,12,hex);
        resource_emit("RPC_RETURN","serial=%u response=%#lx bytes=12 read=%d raw=%s return_type=void errno=%d",resource_rpc.serial,response,ok,ok?hex:"unavailable",e);
    }
    resource_rpc=previous;errno=e;
}
static struct resource_rpc_ticket resource_rpc_free_enter(uint32_t owner,uintptr_t message,uintptr_t caller,uintptr_t app) {
    int saved=errno;struct resource_rpc_ticket ticket={0};
    if(app&&resource_rpc.valid&&resource_live()&&message>=12&&owner!=0x80020002&&(owner>>28)==8&&(owner&0xfffffff)&&caller==app+0x34e57a8){
        uint32_t header[3];char hex[225],copy[225];
        int ok=readmem(message-12,header,sizeof header)&&header[0]==0x92840747&&header[1]==12&&resource_bytes(message,12,hex)&&
            resource_bytes(resource_rpc.response,12,copy)&&!strcmp(hex,copy);
        /* Offsets -12/-8 are guarded original UIPC get_source/msg_size instructions. */
        if(ok&&(!strncmp(hex,"0d2046110c000180",16)||!strncmp(hex,"0d2029140c000180",16))){
            ticket=(struct resource_rpc_ticket){resource_rpc.serial,1,owner,message};
            resource_emit("RPC_FREE_ENTER","serial=%u owner=%#x message=%#lx source=%#x bytes=12 raw=%s caller=%#lx",ticket.serial,owner,message,header[0],hex,caller);
        }
    }
    errno=saved;return ticket;
}
static void resource_rpc_free_return(struct resource_rpc_ticket ticket,int32_t rc,int error) {
    if(ticket.valid)resource_emit("RPC_FREE_RETURN","serial=%u owner=%#x message=%#lx rc=%d errno=%d",ticket.serial,ticket.owner,ticket.message,rc,error);
}
