/* Original CCF API diagnostic only; no private structs, PHY, PCI or DMA calls. */
typedef unsigned long u64;
extern void *of_find_node_opts_by_path(const char *,const char **);
extern void of_node_put(void *);
extern void *of_clk_get_by_name(void *,const char *);
extern u64 clk_get_rate(void *);
extern int clk_prepare(void *);
extern int clk_enable(void *);
extern void clk_disable(void *);
extern void clk_unprepare(void *);
extern void clk_put(void *);
extern int __clk_is_enabled(void *);
extern int printk(const char *,...);
static const char *const names[]={"apb_pclk","dbi_aclk","slv_aclk","mstr_aclk","aux_clk","axi2avb_pcie0","axi2avb_pcie1"};
static const unsigned ids[]={62,63,64,65,66,29,30};
static const u64 rates[]={99000000,396000000,396000000,396000000,1000000,0,0};
int __attribute__((section(".init.text"))) init_module(void)
{
    void *node=of_find_node_opts_by_path("/sony-test-ccf-consumer",(const char **)0);
    if(!node) {printk("\0013NATIVE_CCF_FAILED: missing actual consumer node\n");return -22;}
    for(unsigned i=0;i<7;i++) {
        void *clock=of_clk_get_by_name(node,names[i]);
        if(!clock || (u64)clock>=(u64)-4095) {
            printk("\0013NATIVE_CCF_FAILED: lookup index=%u\n",i);of_node_put(node);return -22;
        }
        u64 rate=clk_get_rate(clock);int before=__clk_is_enabled(clock);
        if(rate!=rates[i] || before) {
            printk("\0013NATIVE_CCF_FAILED: initial index=%u rate=%lu enabled=%d\n",i,rate,before);
            clk_put(clock);of_node_put(node);return -22;
        }
        int rc=clk_prepare(clock);
        if(rc) {clk_put(clock);of_node_put(node);return rc;}
        rc=clk_enable(clock);
        if(rc) {clk_unprepare(clock);clk_put(clock);of_node_put(node);return rc;}
        int enabled=__clk_is_enabled(clock);
        clk_disable(clock);clk_unprepare(clock);
        int after=__clk_is_enabled(clock);
        printk("\0016NATIVE_CCF_CLOCK: id=%u rate=%lu before=%d enabled=%d after=%d\n",ids[i],rate,before,enabled,after);
        clk_put(clock);
        if(enabled!=1 || after) {of_node_put(node);return -22;}
    }
    of_node_put(node);
    printk("\0016NATIVE_CCF_PASS: seven original lookups/rates/prepare/enable/hardware status/disable; no host or DMA\n");
    return 0;
}
