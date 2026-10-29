"""Execute the actual QOM formatter against asymmetric state and check no mutation."""
import json
from pathlib import Path
import subprocess


def test_formatter_reads_state_without_mutating_or_acknowledging(tmp_path):
    models=Path(__file__).resolve().parent/'device-models'
    source=r'''
#include <glib.h>
#include <stdbool.h>
#include <stdio.h>
#include <string.h>
#include <assert.h>
#define GIC_MAXIRQ 1024
#define GIC_NCPU 8
#define ARRAY_SIZE(a) (sizeof(a)/sizeof((a)[0]))
typedef struct {unsigned char enabled,pending,active,level,group;bool edge_trigger;} gic_irq_state;
typedef struct {
 unsigned num_irq,num_cpu,ctlr;
 bool sony_loader_spi_targets;
 unsigned char irq_target[GIC_MAXIRQ],priority2[GIC_MAXIRQ-32];
 unsigned cpu_ctlr[8],priority_mask[8],running_priority[8],current_pending[8];
 gic_irq_state irq_state[GIC_MAXIRQ];
} GICState;
typedef GICState Object;typedef void Error;
#define ARM_GIC_COMMON(obj) (obj)
#include "sony-gic-readback.inc"
int main(void){
 GICState state={.num_cpu=2,.num_irq=256,.ctlr=3},before;
 state.irq_target[35]=2;state.irq_state[33].enabled=255;state.irq_state[33].level=255;
 state.priority2[1]=128;state.cpu_ctlr[0]=1;state.cpu_ctlr[1]=3;
 state.priority_mask[0]=240;state.priority_mask[1]=248;state.current_pending[0]=1023;
 before=state;char *text=sony_gic_readback(&state,NULL);
 assert(!memcmp(&before,&state,sizeof state));puts(text);g_free(text);return 0;
}
'''
    path=tmp_path/'readback.c';path.write_text(source);binary=tmp_path/'readback'
    flags=subprocess.check_output(['pkg-config','--cflags','--libs','glib-2.0'],text=True).split()
    subprocess.run(['cc','-Wall','-Wextra','-Werror','-I',str(models),str(path),'-o',str(binary),*flags],check=True)
    result=json.loads(subprocess.check_output([str(binary)],text=True))
    assert result['observations_only'] and result['zero_spi_targets']==223
    assert result['irqs'][0]['target']==0 and result['irqs'][0]['level']==255
    assert result['irqs'][1]['target']==2 and result['cpus'][1]['priority_mask']==248
