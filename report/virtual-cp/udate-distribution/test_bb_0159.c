/* Reuse the existing BB transport fixture; new checks never depend on NDEBUG. */
#define main legacy_bb_main
#include "test_bb_receiver.c"
#undef main
int main(int argc,char **argv)
{
    CHECK(argc==2);CHECK(!init_module());
    if(!strcmp(argv[1],"values")) {
        const u8 header[8]={1,0x20,2,3,12,0,2,0};
        for(unsigned value=0;value<65536;value++) {
            CHECK(!udate_sender(BB_TARGET,new_message(0x159,(u16)value)));
            CHECK(bb_count==1);CHECK(bb_worker_step());verify_pool();
            CHECK(bb_values[5]==value && bb_generation[5]==value+1 && bb_0159_vdf_pending==1);
            for(unsigned i=0;i<8;i++) CHECK(bb_0159_vdf_request[i]==header[i]);
            CHECK(bb_0159_vdf_request[8]==((u8)value&0xef));
            for(unsigned i=9;i<12;i++) CHECK(bb_0159_vdf_request[i]==0);
            CHECK(bb_panel_generation==0 && bb_panel_pending_mask==0 && !bb_panel_busy);
        }
        CHECK(bb_accepted==65536 && bb_consumed==65536 && !replies);
    } else if(!strcmp(argv[1],"failure")) {
        void *m=new_message(0x159,7);CHECK(!udate_sender(BB_TARGET,m));free_failure=1;
        CHECK(!bb_worker_step() && bb_fault && active==1 && failed_free==1);
        CHECK(bb_inflight.message==m && !bb_generation[5] && !bb_0159_vdf_pending);
        free_failure=0;reject(new_message(0x159,8),-1021);
        CHECK(!bb_worker_step() && failed_free==1);
        CHECK(!osal_free_msg(BB_TARGET,m));bb_inflight.message=NULL;
        CHECK(!active && !replies);
    } else if(!strcmp(argv[1],"reject")) {
        for(unsigned n=0;n<8;n++) {
            void *m=new_message(0x159,7);
            switch(n) {
            case 0:meta(m)->size=9;break;
            case 1:put16((u8 *)m+4,12);break;
            case 2:put16(m,0x2001);break;
            case 3:put16((u8 *)m+6,0);break;
            case 4:meta(m)->source=BB_TARGET;break;
            case 5:put16((u8 *)m+2,0x158);break;
            case 6:put16((u8 *)m+2,0x15b);break;
            default:meta(m)->source=0x80000000;break;
            }
            reject(m,-1020);
        }
        CHECK(!bb_generation[5] && !bb_0159_vdf_pending);verify_pool();
    } else if(!strcmp(argv[1],"corrupt-queue")) {
        void *m=new_message(0x159,7);CHECK(!udate_sender(BB_TARGET,m));
        bb_ring[bb_head].command=0xffff;
        CHECK(!bb_worker_step() && bb_fault && bb_inflight.message==m && active==1);
        CHECK(!bb_generation[5] && !bb_0159_vdf_pending && !freed);
        CHECK(!bb_worker_step());CHECK(!osal_free_msg(BB_TARGET,m));bb_inflight.message=NULL;
        CHECK(!active && !replies);
    } else if(!strcmp(argv[1],"reuse")) {
        void *m=new_message(0x159,0xf7);CHECK(!udate_sender(BB_TARGET,m));recycle_once=1;
        CHECK(bb_worker_step());CHECK(recycle_rc==0 && bb_values[5]==0xf7);
        CHECK(bb_0159_vdf_request[8]==0xe7 && bb_0159_vdf_pending);
        CHECK(bb_worker_step() && bb_values[0]==1);verify_pool();
    } else CHECK(0);
    printf("{\"case\":\"%s\",\"accepted\":%u,\"consumed\":%u,\"outstanding\":%u,\"replies\":%u,\"lower_sent\":false}\n",argv[1],bb_accepted,bb_consumed,active,replies);
    return 0;
}
