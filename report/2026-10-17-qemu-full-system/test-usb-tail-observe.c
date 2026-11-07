/* Host-only typed wrapper tests; no guest, USB, module loading or sockets. */
#define USB_OBSERVE_HOST_TEST 1
#define USB_RESOURCE_OBSERVE 1
#include "usb-start-observe.c"
#include <assert.h>
#include <limits.h>
static uintptr_t received_args[5];
static unsigned calls;
static uint32_t four(uintptr_t a,uintptr_t b,uintptr_t c,uintptr_t d) {
    assert(errno==31);received_args[0]=a;received_args[1]=b;received_args[2]=c;received_args[3]=d;
    calls++;errno=43;return UINT32_C(0x80000009);
}
static uint32_t five(uintptr_t a,uint32_t b,int32_t c,int32_t d,int32_t e) {
    assert(errno==31);received_args[0]=a;received_args[1]=b;received_args[2]=(uint32_t)c;
    received_args[3]=(uint32_t)d;received_args[4]=(uint32_t)e;calls++;errno=44;return UINT32_C(0x80000007);
}
static uint32_t start3(uintptr_t a,int32_t b,int32_t c) {
    assert(errno==31);received_args[0]=a;received_args[1]=(uint32_t)b;received_args[2]=(uint32_t)c;
    calls++;errno=45;return UINT32_C(0xf0000001);
}
static uint32_t start4(uintptr_t a,int32_t b,int32_t c,int32_t d) {
    assert(errno==31);received_args[0]=a;received_args[1]=(uint32_t)b;received_args[2]=(uint32_t)c;
    received_args[3]=(uint32_t)d;calls++;errno=46;return UINT32_C(0xf0000002);
}
static void action3(uintptr_t a,int32_t b,uintptr_t c) {
    assert(errno==31);received_args[0]=a;received_args[1]=(uint32_t)b;received_args[2]=c;calls++;errno=47;
}
static void event4(uintptr_t a,uint8_t b,uint8_t c,uintptr_t d) {
    assert(errno==31);received_args[0]=a;received_args[1]=b;received_args[2]=c;received_args[3]=d;calls++;errno=48;
}
static void notify4(uintptr_t a,uint32_t b,uintptr_t c,uint8_t d) {
    assert(errno==31);received_args[0]=a;received_args[1]=b;received_args[2]=c;received_args[3]=d;calls++;errno=49;
}
static uint32_t module3(uintptr_t a,uintptr_t b,uintptr_t c) {
    assert(errno==31);received_args[0]=a;received_args[1]=b;received_args[2]=c;calls++;errno=50;return 7;
}
static struct {uint32_t source,size,reserved;unsigned char data[12];} reply;
static const unsigned char reply_wire[12]={0x0d,0x20,0x46,0x11,12,0,1,0x80,0,0,0x59,0};
static const unsigned char tcin_reply_wire[12]={0x0d,0x20,0x29,0x14,12,0,1,0x80,0,0,0,0};
static int inspect_rpc;
static void rpc5(uint32_t dest,uintptr_t request,int32_t size,uintptr_t output,int32_t output_size) {
    assert(errno==31);received_args[0]=dest;received_args[1]=request;received_args[2]=(uint32_t)size;
    received_args[3]=output;received_args[4]=(uint32_t)output_size;calls++;
    if(inspect_rpc){
        assert(resource_rpc.valid&&size==10&&output_size==12);
        const unsigned char *wire=inspect_rpc==2?tcin_reply_wire:reply_wire;
        reply.source=0x92840747;reply.size=12;memcpy(reply.data,wire,12);
        memcpy((void *)output,reply.data,12);
        struct resource_rpc_ticket ticket=resource_rpc_free_enter(0x81cf1234,(uintptr_t)reply.data,0x100000+0x34e57a8,0x100000);
        assert(ticket.valid&&ticket.owner==0x81cf1234&&ticket.message==(uintptr_t)reply.data);
        memset(reply.data,0xa5,12); /* Actual release invalidates the message before RETURN observation. */
        resource_rpc_free_return(ticket,0,71);
    }
    errno=71;
}
static void clear_log(void) {
    assert(!ftruncate(logfd,0)&&lseek(logfd,0,SEEK_SET)==0);resource_records=0;
}
static void read_log(char *out,size_t capacity) {
    off_t size=lseek(logfd,0,SEEK_END);assert(size>=0&&(size_t)size<capacity);
    assert(pread(logfd,out,(size_t)size,0)==size);out[size]=0;
}
int main(int argc,char **argv) {
    assert(argc==2);logfd=open(argv[1],O_CREAT|O_TRUNC|O_RDWR,0600);assert(logfd>=0);
    memfd=open("/proc/self/mem",O_RDONLY);assert(memfd>=0);
    static unsigned char control[0x30a70];control_base=(uintptr_t)control;
    uint32_t qid=0x81cf1234;memcpy(control+0x30a68,&qid,4);
    uintptr_t high=UINT64_C(0xffff123456789abc),other=UINT64_C(0xfedcba9876543210);
    real_storage_create=four;real_sen_create=four;real_gadget_create=four;real_sync_startstop=five;
    errno=31;assert(u_storage_create(high,2,3,other)==0x80000009&&errno==43&&received_args[0]==high&&received_args[3]==other);
    errno=31;assert(u_sen_create(high,2,3,other)==0x80000009&&errno==43&&received_args[3]==other);
    errno=31;assert(u_gadget_create(high,2,3,other)==0x80000009&&errno==43&&received_args[3]==other);
    errno=31;assert(u_sync_startstop(high,UINT32_MAX,INT32_MIN,INT32_MAX,-3)==0x80000007&&errno==44);
    assert(received_args[0]==high&&received_args[1]==UINT32_MAX&&(int32_t)received_args[2]==INT32_MIN&&(int32_t)received_args[4]==-3);
    real_wrapper_start=start3;real_do_start=start4;
    errno=31;assert(u_wrapper_start(high,-7,INT32_MAX)==0xf0000001&&errno==45&&received_args[0]==high&&(int32_t)received_args[1]==-7);
    errno=31;assert(u_do_start(high,55,-9,INT32_MIN)==0xf0000002&&errno==46&&(int32_t)received_args[2]==-9&&(int32_t)received_args[3]==INT32_MIN);
    real_control_configure=action3;real_control_start=action3;real_control_start_entry=action3;
    errno=31;u_control_configure(high,-31,other);assert(errno==47&&received_args[0]==high&&received_args[2]==other);
    errno=31;u_control_start(high,-32,other);assert(errno==47&&(int32_t)received_args[1]==-32);
    errno=31;u_control_start_entry(high,-33,other);assert(errno==47&&(int32_t)received_args[1]==-33);
    real_gadget_event=event4;real_svc_notify=notify4;
    errno=31;u_gadget_event(high,255,128,other);assert(errno==48&&received_args[0]==high&&received_args[1]==255&&received_args[2]==128&&received_args[3]==other);
    errno=31;u_svc_notify(high,0x87654321,other,255);assert(errno==49&&received_args[1]==0x87654321&&received_args[2]==other&&received_args[3]==255);
    real_ko_insmod=module3;char path[]="/usr/kmod/usbg_storage.ko",parameters[]="debug=0\nraw=1";
    errno=31;assert(u_ko_insmod(high,(uintptr_t)path,(uintptr_t)parameters)==7&&errno==50&&received_args[2]==(uintptr_t)parameters);
    assert(calls==12);
    char text[40000];read_log(text,sizeof text);assert(strstr(text,"qid_raw=0x81cf1234"));
    assert(strstr(text,"return_type=void")&&strstr(text,"MODULE_PARAMETERS")&&strstr(text,"0a7261773d31"));

    clear_log();unsigned char probe[112];memset(probe,0x6b,sizeof probe);
    errno=31;resource_ioctl(logfd,0x4038e201,(uintptr_t)probe,0,0,31);assert(errno==31);
    errno=31;resource_ioctl(logfd,0x4070e000,(uintptr_t)probe,0,0,31);assert(errno==31);
    resource_ioctl(logfd,0x4070e000,1,0,0,31);resource_ioctl(-1,0x4070e000,0,1,-1,19);
    read_log(text,sizeof text);assert(strstr(text,"bytes=56 read=1 raw=6b6b")&&strstr(text,"bytes=112 read=1 raw=6b6b"));
    assert(strstr(text,"bytes=112 read=0 raw=unavailable")&&strstr(text,"rc=-1 errno=19"));
    char hex[225];assert(!resource_bytes((uintptr_t)probe,113,hex)&&!resource_bytes((uintptr_t)probe,0,hex));

    clear_log();real_resource_rpc=rpc5;
    unsigned char request[10]={0x0d,0x20,0x46,1,10,0,1,0x80,1,0},output[12];inspect_rpc=1;
    errno=31;u_resource_rpc(0x92840747,(uintptr_t)request,10,(uintptr_t)output,12);assert(errno==71&&!resource_rpc.valid);
    assert(received_args[1]==(uintptr_t)request&&received_args[3]==(uintptr_t)output);
    assert(!memcmp(output,reply_wire,12)&&reply.data[0]==0xa5);
    read_log(text,sizeof text);assert(strstr(text,"RPC_FREE_ENTER")&&strstr(text,"RPC_FREE_RETURN"));
    assert(strstr(text,"raw=0d2046110c00018000005900")&&!strstr(text,"raw=a5a5"));
    clear_log();request[2]=0x29;request[3]=4;request[8]=0;inspect_rpc=2;
    errno=31;u_resource_rpc(0x92840747,(uintptr_t)request,10,(uintptr_t)output,12);
    assert(errno==71&&!resource_rpc.valid&&!memcmp(output,tcin_reply_wire,12));
    read_log(text,sizeof text);assert(strstr(text,"raw=0d2029040a0001800000")&&strstr(text,"raw=0d2029140c00018000000000"));
    assert(strstr(text,"RPC_FREE_ENTER")&&strstr(text,"RPC_FREE_RETURN"));
    clear_log();request[9]=1;inspect_rpc=0;
    errno=31;u_resource_rpc(0x92840747,(uintptr_t)request,10,(uintptr_t)output,12);
    assert(errno==71&&resource_records==0);
    inspect_rpc=0;errno=31;u_resource_rpc(0x92840747,high,-10,other,INT32_MIN);
    assert(errno==71&&received_args[1]==high&&(int32_t)received_args[2]==-10&&received_args[3]==other&&(int32_t)received_args[4]==INT32_MIN);
    resource_rpc=(struct resource_rpc_scope){99,1,0};reply.source=0x92840747;reply.size=12;memcpy(reply.data,reply_wire,12);
    assert(!resource_rpc_free_enter(0x80020002,(uintptr_t)reply.data,0x100000+0x34e57a8,0x100000).valid);
    assert(!resource_rpc_free_enter(0x91cf1234,(uintptr_t)reply.data,0x100000+0x34e57a8,0x100000).valid);
    assert(!resource_rpc_free_enter(0x81cf1234,(uintptr_t)reply.data,0x100000+0x34e57ac,0x100000).valid);
    reply.source=0x90bf0274;assert(!resource_rpc_free_enter(0x81cf1234,(uintptr_t)reply.data,0x100000+0x34e57a8,0x100000).valid);
    reply.source=0x92840747;reply.size=10;assert(!resource_rpc_free_enter(0x81cf1234,(uintptr_t)reply.data,0x100000+0x34e57a8,0x100000).valid);

    clear_log();records=10000;errors=10000;
    for(unsigned i=0;i<10000;i++)resource_emit("NOISE","value=%u",i);
    assert(resource_records==64&&records==10000&&errors==10000);
    read_log(text,sizeof text);unsigned count=0;for(char *p=text;(p=strstr(p,"USB_START RESOURCE_"));p++)count++;
    assert(count==65&&strstr(text,"RESOURCE_CAP records=64\n")&&strlen(text)<=64*512+sizeof("USB_START RESOURCE_CAP records=64\n"));
    control_base=1;errno=31;assert(u_do_start(high,55,-9,INT32_MIN)==0xf0000002&&errno==46);
    close(memfd);memfd=-1;
    assert(!resource_rpc_free_enter(0x81cf1234,1,0x100000+0x34e57a8,0x100000).valid);
    assert(resource_records==64);close(logfd);return 0;
}
