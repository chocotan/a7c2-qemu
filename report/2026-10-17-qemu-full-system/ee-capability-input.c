#include "ee-capability-input.h"

static uint16_t u16(const uint8_t *p) { return (uint16_t)(p[0] | ((uint16_t)p[1] << 8)); }
static uint32_t u32(const uint8_t *p) { return (uint32_t)u16(p) | ((uint32_t)u16(p+2) << 16); }
static void put32(uint8_t *p, uint32_t v) {
    unsigned i;
    for (i=0; i<4; ++i) p[i]=(uint8_t)(v >> (i*8));
}
static int layout(const uint8_t *r, size_t rb, const uint8_t *s, size_t sb) {
    return r && s && rb && !(rb%64) && rb/64<=0x650 && sb==rb/4;
}
int ee_adc_consume(uint8_t *rows, size_t rb, uint8_t *state, size_t sb,
                   unsigned state_known, const struct ee_adc_sample samples[2],
                   uint64_t now, uint64_t max_age) {
    size_t i, n;
    if (!state_known || !samples) return EE_INPUT_UNKNOWN;
    if (!layout(rows,rb,state,sb)) return EE_INPUT_INVALID;
    for (i=0; i<2; ++i) {
        const struct ee_adc_sample *a=&samples[i];
        if (!a->known || !a->calibrated || a->virtual_input_state!=1) return EE_INPUT_UNKNOWN;
        if (!a->data || a->bytes!=24 || a->selector!=i) return EE_INPUT_INVALID;
        if (a->sampled_at>now || now-a->sampled_at>max_age) return EE_INPUT_STALE;
    }
    if (samples[0].generation!=samples[1].generation) return EE_INPUT_INVALID;
    n=rb/64;
    /* Validate the complete batch before mutating any state. */
    for (i=0; i<n; ++i) {
        uint8_t *r=rows+64*i, *s=state+16*i;
        int count=s[12]<128 ? s[12] : (int)s[12]-256;
        if (u32(r+8)>23 || u16(r+20)>u16(r+24) || count< -100 || count>100 || s[14]>1)
            return EE_INPUT_INVALID;
        if (r[46]==2 && (uint8_t)u16(r+44)>=n) return EE_INPUT_INVALID;
    }
    /* 42467e..42481e: inclusive thresholds, signed saturation, zero-skipping serial. */
    for (i=0; i<n; ++i) {
        uint8_t *r=rows+64*i, *s=state+16*i;
        uint32_t channel=u32(r+8);
        uint16_t adc=u16(samples[channel/12].data+2*(channel%12)), key=u16(r+44);
        int count=s[12]<128 ? s[12] : (int)s[12]-256;
        unsigned on, transition;
        uint32_t value;
        if (adc<u16(r+20) || adc>u16(r+24)) {
            if (count>=1) { count=-1; transition=1; }
            else { --count; if (count<=-101) count=-100; transition=(count==-1); }
            on=0;
        } else {
            if (count<=-1) { count=1; transition=1; }
            else { ++count; if (count>=101) count=100; transition=(count==1); }
            on=1;
        }
        s[12]=(uint8_t)count;
        put32(r+32,1);
        if (transition) {
            if (r[46]==1) { put32(s,adc); }
            else if (r[46]==2) { if (on) put32(s,u32(r+40)); }
            else if (r[46]==4) { if (on) put32(s,u32(s+8)); }
            else { value=on ? u32(r+40) : 0; put32(s,value); }
            if (r[46]!=2 || on) {
                s[14]=(uint8_t)(r[47]==0);
                put32(s+4,key);
            }
        }
        if (s[14]) {
            uint8_t *target=s;
            if (r[46]==2) {
                target=state+16*(uint8_t)key;
                put32(target,u32(s));put32(target+4,u32(s+4));
            }
            target[13]=(uint8_t)(target[13]+1);
            if (!target[13]) target[13]=1;
            s[14]=0;
        }
    }
    return EE_INPUT_OK;
}
int ee_adc_read_key(const uint8_t *rows, size_t rb, const uint8_t *state,
                    size_t sb, uint32_t keycode, uint32_t *value) {
    size_t i;
    unsigned found=0;
    if (!value || !layout(rows,rb,state,sb)) return EE_INPUT_INVALID;
    for (i=0; i<rb/64; ++i) {
        const uint8_t *r=rows+64*i, *s;
        size_t idx=i;
        if (u32(r+36)!=keycode) continue;
        if (r[46]==2) idx=r[44];
        if (idx>=rb/64) return EE_INPUT_INVALID;
        s=state+16*idx;
        *value=s[13] ? u32(s) : UINT32_MAX;
        found=1;
    }
    return found ? (*value==UINT32_MAX ? EE_INPUT_UNKNOWN : EE_INPUT_OK) : EE_INPUT_UNKNOWN;
}
struct ee_normal_result ee_normal_select(const struct ee_normal_inputs *in) {
    struct ee_normal_result out={EE_REJECT_UNKNOWN,0,0,0,0,0};
    uint32_t a,b,c,d;
    static const unsigned policy[4]={0,2,3,5};
    out.unknown_gates=(in ? (63u & ~in->known) : 63u) | EE_GATE_TRIGGER;
    if (!in || (out.unknown_gates & 63u)) return out;
    if (!in->backup_00030162 || in->backup_bytes!=64 || (in->known & ~63u)) {
        out.decision=EE_REJECT_INVALID;return out;
    }
    if (in->current[0]==UINT32_MAX || in->current[1]==UINT32_MAX) {
        out.unknown_gates|=EE_GATE_CURRENT;return out;
    }
    if (in->object_110c!=0 || !in->object_10bf) {
        out.decision=EE_TRIGGER_INACTIVE;return out;
    }
    a=in->current[0];b=in->current[1];
    c=u32(in->backup_00030162);d=u32(in->backup_00030162+4);
    if (in->be9bae_byte9) out.reason=4;
    else if (a!=c || (b!=d && ((b-2u)|(d-2u))>3u) || a==UINT32_MAX-1u || b==UINT32_MAX-1u)
        out.reason=1;
    else out.reason=in->policy_00030a01<4 ? policy[in->policy_00030a01] : 255;
    if (in->force_e0 & 4u) out.reason=255;
    out.decision=out.reason ? EE_NORMAL_SPINAL_OFF : EE_CONTINUE_EE;
    out.raw_candidate_valid=(out.decision==EE_NORMAL_SPINAL_OFF);
    return out;
}
