#!/bin/busybox sh
# Explicit read-only diagnostic; inherits the existing UART fd, never reads it.
exec 8<&-
trap 'echo UART_INPUT_OBSERVER_SIGNAL_HUP > /dev/kmsg; exit 129' HUP
trap 'echo UART_INPUT_OBSERVER_SIGNAL_TERM > /dev/kmsg; exit 143' TERM
trap 'echo UART_INPUT_OBSERVER_SIGNAL_INT > /dev/kmsg; exit 130' INT
log_board() {
    cat /proc/interrupts | while IFS= read -r line; do echo "UART_IRQ_OBSERVE $line" > /dev/kmsg; done
/simulation/board-regs | while IFS= read -r line; do echo "UART_BOARD_OBSERVE $line" > /dev/kmsg; done
}
/simulation/uart-input-observe before --kernel-log
echo UART_INPUT_OBSERVER_BEFORE_RC=$? > /dev/kmsg
sleep 15
/simulation/uart-input-observe after15 --kernel-log
echo UART_INPUT_OBSERVER_AFTER15_RC=$? > /dev/kmsg
log_board
sleep 30
/simulation/uart-input-observe after45 --kernel-log
echo UART_INPUT_OBSERVER_AFTER45_RC=$? > /dev/kmsg
log_board
if [ "$1" = rx ]; then
    echo UART_INPUT_OBSERVER_DONE > /dev/kmsg
    exit 0
fi
sleep 45
/simulation/uart-input-observe after90 --kernel-log
echo UART_INPUT_OBSERVER_AFTER90_RC=$? > /dev/kmsg
log_board
echo UART_INPUT_OBSERVER_DONE > /dev/kmsg
