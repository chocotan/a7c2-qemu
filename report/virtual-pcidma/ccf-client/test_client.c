#include "client.c"
#include <assert.h>
#include <stdio.h>
#include <string.h>
struct fake_clock {unsigned index,refs,prepared,enabled;};
static struct fake_clock clocks[7];
static unsigned mode,node_refs,passed;
static int node;
void *of_find_node_opts_by_path(const char *path,const char **options)
{assert(!options && !strcmp(path,"/sony-test-ccf-consumer"));if(mode==1)return 0;node_refs++;return &node;}
void of_node_put(void *p) {assert(p==&node && node_refs==1);node_refs--;}
void *of_clk_get_by_name(void *p,const char *name)
{
    assert(p==&node && node_refs==1);
    for(unsigned i=0;i<7;i++)if(!strcmp(name,names[i])) {
        if(mode==2 && i==2)return (void *)(u64)-2;
        clocks[i].refs++;return &clocks[i];
    }
    assert(0);return 0;
}
u64 clk_get_rate(void *p) {struct fake_clock *c=p;assert(c->refs==1);return rates[c->index]+(mode==3 && c->index==2);}
int __clk_is_enabled(void *p) {return ((struct fake_clock *)p)->enabled;}
int clk_prepare(void *p) {struct fake_clock *c=p;if(mode==4 && c->index==2)return -5;assert(!c->prepared);c->prepared++;return 0;}
int clk_enable(void *p) {struct fake_clock *c=p;assert(c->prepared==1);if(mode==5 && c->index==2)return -5;if(!(mode==6 && c->index==2))c->enabled=1;return 0;}
void clk_disable(void *p) {struct fake_clock *c=p;assert(c->prepared==1);c->enabled=0;}
void clk_unprepare(void *p) {struct fake_clock *c=p;assert(c->prepared==1 && !c->enabled);c->prepared--;}
void clk_put(void *p) {struct fake_clock *c=p;assert(c->refs==1 && !c->prepared);c->refs--;}
int printk(const char *format,...) {if(strstr(format,"NATIVE_CCF_PASS:"))passed++;return 0;}
int main(void)
{
    for(mode=0;mode<7;mode++) {
        memset(clocks,0,sizeof clocks);for(unsigned i=0;i<7;i++)clocks[i].index=i;
        node_refs=passed=0;int rc=init_module();assert(mode?rc<0:rc==0);
        assert(!node_refs && passed==(mode==0));
        for(unsigned i=0;i<7;i++)assert(!clocks[i].refs && !clocks[i].prepared && !clocks[i].enabled);
    }
    puts("PASS_HOST_CCF_API_CONTROL_ONLY: seven stages plus missing node/error ref/rate/prepare/enable/no hardware effect");
}
