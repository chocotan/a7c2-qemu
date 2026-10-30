"""Console-only retained-source fault detection; no camera, VM or process IO."""
import pytest

from menu_live import FirmwareFault, FirmwareMonitor


SOURCE = b"OBS FUNCTIONAL_FACE_SOURCE_RETAINED_FAULT "


@pytest.mark.parametrize("cut", [1, 12, len(SOURCE) - 1])
def test_source_fault_split_across_reads_keeps_original_frame_reason(tmp_path, cut):
    console = tmp_path / "console.log"
    console.write_bytes(b"boot complete\n" + SOURCE[:cut])
    monitor = FirmwareMonitor(console)
    monitor.check()
    with console.open("ab") as writer:
        writer.write(SOURCE[cut:] + b"rc=-5 claimed=1 original_sender_started=0\n")
    with pytest.raises(FirmwareFault, match="功能源快照.*调用栈和资源已保留"):
        monitor.check()
    console.write_bytes(b"later log rotation\n")
    with pytest.raises(FirmwareFault, match="功能源快照.*调用栈和资源已保留"):
        monitor.check()


@pytest.mark.parametrize("marker", [b"Entering exception monitor.", b"Exception>", b"OBS GUI_MODEL_FAILED "])
def test_original_firmware_and_gui_faults_still_stop_input(tmp_path, marker):
    console = tmp_path / "console.log"
    console.write_bytes(b"boot\n" + marker + b"details\n")
    monitor = FirmwareMonitor(console)
    with pytest.raises(FirmwareFault, match="相机固件发生异常"):
        monitor.check()


def test_source_success_or_quoted_marker_cannot_create_fault(tmp_path):
    console = tmp_path / "console.log"
    console.write_bytes(b"OBS FUNCTIONAL_FACE_SOURCE_SNAPSHOT_RESULT rc=0\nquoted " + SOURCE + b"ignored\n")
    monitor = FirmwareMonitor(console)
    monitor.check()
    assert not monitor.failed
