# Sourced only in the selected receiver's post-wait subshell.
p1_rawlog_meta()
{
    [ -f "$1" ] && [ ! -L "$1" ] || return 66
    meta=$($bb ls -lidn "$1") || return "$?"
    set -- $meta
    case "$1:$3:$6" in *[!0-9:]*) return 65 ;; esac
    case "$2" in -*) ;; *) return 65 ;; esac
    [ "$3" = 1 ] && [ "$1" -gt 0 ] || return 65
    [ "$6" -gt 0 ] && [ "$6" -le 262144 ] || return 67
    echo "$1 $6"
}
p1_rawlog_file()
{
    name=$1
    path=$2
    echo "P1_RAWLOG FILE nonce=$nonce pid=$receiver name=$name path=$path actor=guest-postwait"
    before=$(p1_rawlog_meta "$path")
    file_rc=$?
    if [ "$file_rc" -ne 0 ]; then
        echo "P1_RAWLOG ERROR nonce=$nonce pid=$receiver name=$name stage=before rc=$file_rc"
        return "$file_rc"
    fi
    set -- $before
    inode=$1
    bytes=$2
    hash=$(/usr/bin/openssl dgst -sha256 "$path")
    file_rc=$?
    if [ "$file_rc" -ne 0 ]; then
        echo "P1_RAWLOG ERROR nonce=$nonce pid=$receiver name=$name stage=hash-before rc=$file_rc"
        return "$file_rc"
    fi
    hash=${hash##* }
    echo "P1_RAWLOG BEFORE nonce=$nonce pid=$receiver name=$name type=regular links=1 inode=$inode bytes=$bytes sha256=$hash"
    transfer=$(
        {
            {
                diagnostic=$($bb dd if="$path" bs=262144 count=1 2>&1 >&4)
                read_rc=$?
                diagnostic64=$(echo "$diagnostic" | /usr/bin/openssl enc -base64 -A)
                diagnostic_rc=$?
                echo "$read_rc" >&3
                echo "$diagnostic_rc" >&3
                echo "$diagnostic64" >&3
            } 4>&1 | {
                payload=$(/usr/bin/openssl enc -base64)
                encode_rc=$?
                echo "$encode_rc"
                echo "$payload"
            }
        } 3>&1
    )
    {
        IFS= read -r read_rc
        IFS= read -r diagnostic_rc
        IFS= read -r diagnostic64
        IFS= read -r encode_rc
        encoded=$($bb cat)
    } <<P1_RAWLOG_TRANSFER
$transfer
P1_RAWLOG_TRANSFER
    echo "P1_RAWLOG READ nonce=$nonce pid=$receiver name=$name rc=$read_rc diagnostic_rc=$diagnostic_rc diagnostic_b64=$diagnostic64"
    if [ "$encode_rc" -eq 0 ]; then
        echo "$encoded" | (
            seq=0
            while IFS= read -r data; do
                echo "P1_RAWLOG DATA nonce=$nonce pid=$receiver name=$name seq=$seq b64=$data"
                seq=$((seq + 1))
            done
        )
    fi
    after=$(p1_rawlog_meta "$path")
    meta_rc=$?
    after_hash=$(/usr/bin/openssl dgst -sha256 "$path")
    hash_rc=$?
    after_hash=${after_hash##* }
    set -- $after
    echo "P1_RAWLOG AFTER nonce=$nonce pid=$receiver name=$name type=regular links=1 inode=${1:-unknown} bytes=${2:-unknown} sha256=$after_hash"
    file_rc=0
    [ "$read_rc:$diagnostic_rc:$encode_rc:$meta_rc:$hash_rc" = 0:0:0:0:0 ] && [ "$before:$hash" = "$after:$after_hash" ] || file_rc=74
    echo "P1_RAWLOG END nonce=$nonce pid=$receiver name=$name encode_rc=$encode_rc meta_rc=$meta_rc hash_rc=$hash_rc rc=$file_rc"
    return "$file_rc"
}
p1_rawlog_send()
{
    # Explicit paths are also used by the synthetic host fixture; production fixes them below.
    receiver=$1
    original_rc=$2
    tail_path=$3
    broker_path=$4
    broker_profile=$5
    nonce=
    if ! IFS= read -r nonce < /proc/sys/kernel/random/uuid; then
        echo 'P1_RAWLOG_NONCE_ERROR source=/proc/sys/kernel/random/uuid rc=66'
        return 66
    fi
    case "$nonce" in ''|*[!0-9a-f-]*)
        echo 'P1_RAWLOG_NONCE_ERROR source=/proc/sys/kernel/random/uuid rc=65'
        return 65 ;;
    esac
    files=1
    [ "$broker_profile" = off ] || files=2
    echo "P1_RAWLOG BEGIN nonce=$nonce nonce_source=proc-uuid actor=guest-postwait pid=$receiver wait_rc=$original_rc files=$files broker=$broker_profile"
    p1_rawlog_file tail "$tail_path"
    total_rc=$?
    if [ "$files" -eq 2 ]; then
        p1_rawlog_file broker "$broker_path"
        broker_rc=$?
        [ "$broker_rc" -eq 0 ] || total_rc=$broker_rc
    fi
    echo "P1_RAWLOG DONE nonce=$nonce pid=$receiver actor=guest-postwait wait_rc=$original_rc rc=$total_rc"
    return "$total_rc"
}
p1_collect_rawlogs()
{
    [ "$A7C2_P1_TAIL_PROFILE" = original-p1-stock-tail-v1 ] || return 125
    case "${A7C2_P1_TAIL_PMBP_PROFILE:-off}:${A7C2_P1_PMBP_PROFILE:-off}" in
        off:off) broker_profile=off ;;
        virtual-p1-pmbp-block-slice-v1:virtual-p1-pmbp-block-slice-v1) broker_profile=virtual-p1-pmbp-block-slice-v1 ;;
        *) return 125 ;;
    esac
    p1_rawlog_send "$1" "$2" /simulation/p1-tail/receiver.log /simulation/pmbp-runtime/receiver.log "$broker_profile"
}
