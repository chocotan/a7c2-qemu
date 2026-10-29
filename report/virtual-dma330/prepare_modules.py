#!/usr/bin/env python3
"""Build/check owned modules only while no project VM is using their sources."""
from pathlib import Path
import subprocess
from admission import idle_lock

here = Path(__file__).resolve().parent
with idle_lock(here.parents[1]/'runtime/analysis/.menu-probe.lock'):
    for component in ('dma330-kernel-client-abi', 'sony-pl330-mmio', 'sony-pl330-client'):
        subprocess.run(['bash', str(here/component/'build.sh')], check=True)
