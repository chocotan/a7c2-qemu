import os
from pathlib import Path

import pytest

import p1_transport_frontier as p1


def test_original_spi_and_pcidma_errors_are_not_link_readiness_proof():
    raw = (b'UPDATE_MODULE_REJECT module=/usr/kmod/pciedma.ko reason=unmodeled-resource\n'
           b'LOAD CP UPDATER START.\nERROR: open /dev/spidev0.0 failed.\n'
           b'[E] pcidma open error\nlink up NG.\nUdrAPI,89,Plugin.cpp:52,nor_loader_writer.sh\n')
    result = p1.analyze(raw)
    assert result['spi_open_failed'] and result['pcidma_module_rejected']
    assert result['pcidma_open_failed'] and result['link_failure_text_observed']
    assert not result['readiness_query_verified']
    assert not result['cp_loader_execution_verified'] and not result['installation_verified']
    assert [row['line'] for row in result['events']] == [1, 2, 3, 4, 5, 6]


def test_unknown_or_malformed_input_does_not_claim_success(tmp_path):
    result = p1.analyze(b'ordinary unrelated message\n')
    assert not result['events'] and not result['installation_verified']
    assert not result['spi_open_failed'] and not result['readiness_query_verified']
    with pytest.raises(ValueError):
        p1.analyze('not bytes')
    source = tmp_path/'serial.log'
    source.write_bytes(b'log\n')
    assert p1.read_serial(source) == b'log\n'
    alias = tmp_path/'alias'
    alias.symlink_to(source)
    with pytest.raises(ValueError, match='symlink'):
        p1.read_serial(alias)
    hardlink = tmp_path/'hardlink'
    os.link(source, hardlink)
    with pytest.raises(ValueError, match='single-link'):
        p1.read_serial(source)
