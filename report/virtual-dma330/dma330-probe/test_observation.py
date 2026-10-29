import importlib.util
from pathlib import Path

spec = importlib.util.spec_from_file_location('dma_probe', Path(__file__).with_name('run_probe.py'))
probe = importlib.util.module_from_spec(spec)
spec.loader.exec_module(probe)
SHA = '9ba277f011b3ddcfbc3fa610d22b63ae3be1e0ded385b42ff2c7cf0a83e520ab'


def sample(symbol=True):
    output = (b'/ # echo DMA330_LOAD_RC=$?\r\n'
              b'/ # grep " dma330_mem_transfer_async" /proc/kallsyms\r\n'
              b'Uid:\t0\t0\t0\t0\r\nGid:\t0\t0\t0\t0\r\n'
              b'SHA2-256(/kmod/dma330.ko)= '+SHA.encode()+b'\r\n'
              b'DMA330_LOAD_RC=0\r\n'
              b'dma330 598016 0 - Live 0xffffff80004b6000 (PO)\r\n')
    if symbol:
        output += b'ffffff80004be7c8 T dma330_mem_transfer_async [dma330]\r\n'
    return output


def test_real_symbol_row_with_module_suffix():
    assert probe.parse_observation(sample(), SHA)['ok']


def test_command_echo_cannot_substitute_for_symbol():
    result = probe.parse_observation(sample(False), SHA)
    assert not result['ok'] and not result['checks']['symbol_listed']
    assert result['checks']['module_live']


def test_identity_echo_cannot_substitute_for_digest():
    data = sample().replace(b'SHA2-256(/kmod/dma330.ko)= '+SHA.encode(),
                            b'/ # grep -q "'+SHA.encode()+b'$" /tmp/dma330.sha')
    assert not probe.parse_observation(data, SHA)['checks']['guest_identity']


def test_monitor_words_require_actual_complete_read():
    assert probe.parse_monitor_words('ffffffc000012240: 0x10 0x20\n', 2) == [16, 32]
    import pytest
    with pytest.raises(ValueError):
        probe.parse_monitor_words('Cannot access memory at address 0xffffffc000012240', 2)
    with pytest.raises(ValueError):
        probe.parse_monitor_words('ffffffc000012240: 0x10\n', 2)


def test_actual_udif_count_is_at_18_not_28():
    values = [0x302d64303333, 0, 0, 18, 0xffffff80086bed88, 0]
    assert probe.parse_device_words(values) == (0xffffff80086bed88, 18)
    import pytest
    with pytest.raises(RuntimeError):
        probe.parse_device_words([*values[:3], 0, values[4], 18])
