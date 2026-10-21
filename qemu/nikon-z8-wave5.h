/* SPDX-License-Identifier: GPL-2.0-or-later
 * Authored functional Wave5-compatible HEVC/AVC device. The compatible 5210
 * identity is an explicit virtual profile, not measured Nikon silicon.
 * Original microcode execution is required by default and is not available.
 * Explicit diagnostic mode: actual input RAM -> x265 -> actual output RAM.
 * Opaque code DMA checks never prove vendor ISA execution. No files or RTOS
 * flags are injected. The host reference buffers belong to this backend.
 */
#include "qemu/thread.h"
#include "nikon-wave5-codec.h"

#define WL_W5_BASE UINT64_C(0x16010000)
#define WL_W5_INSTANCES 4
#define WL_W5_REG(off) ((off) / 4)

typedef struct WlWave5Instance {
    bool created, configured, buffers, result, sequence_result, ring;
    unsigned width, height, depth, fps_n, fps_d;
    unsigned keyframe_period;
    unsigned source_index, bytes, nal_type, output_bus;
    unsigned main_surface;
    unsigned codec_mode;
    unsigned crop[4]; /* left, top, right, bottom: coded-surface pixels */
    int recon_index;
    uint32_t submit_tick, complete_tick;
    uint64_t pictures, output;
    uint64_t ring_physical;
    unsigned ring_bus, ring_capacity, ring_written;
    uint64_t work_physical;
    unsigned work_bus, work_capacity;
    bool report_requested;
    uint32_t header_lengths[4]; /* AUD, VPS (HEVC only), SPS, PPS; no prefix */
    WlHevcCodec *codec;
} WlWave5Instance;

typedef struct WlWave5Job {
    struct WlWave5State *owner;
    WlWave5Instance *instance;
    uint8_t *input;
    unsigned strides[3], source_index, nal_type;
    unsigned main_surface;
    uint64_t output, pts;
    unsigned capacity, input_bytes, output_bus;
    uint32_t input_crc;
    GByteArray *encoded;
    bool done, valid;
} WlWave5Job;

typedef struct WlWave5State {
    NikonZ8State *board;
    uint32_t regs[0x2000 / 4], pending, interrupt_mask;
    bool booted, sleeping, busy, lossless;
    unsigned last_command, instances, fio_address;
    uint32_t fio_data, fio_words[18];
    uint64_t writes, reads, commands, completions, rejections, resets;
    uint32_t external_reset_held;
    uint64_t external_resets;
    uint64_t boot_bytes, input_bytes, output_bytes;
    uint64_t boot_physical;
    uint32_t boot_crc, input_crc, output_crc;
    const char *boot_rejection, *source_rejection;
    WlWave5Instance instance[WL_W5_INSTANCES];
    WlWave5Job *job;
    QemuMutex lock;
    QEMUTimer *timer;
    qemu_irq irq;
} WlWave5State;

static const uint16_t wave5_fio_offsets[] = {
    0x88f0,0x88f4,0xfe10,0xfe14,0x8e10,0x8e14,0x9e10,0x9e14,
    0xfe0c,0xfec0,0xfee0,0xfea0,0xfea4,0xfea8,0xfeac,0xff00,
    0xfe64,0xfe6c
};

static bool wave5_bus_stopped(WlWave5State *w)
{
    return w->fio_words[0] || w->fio_words[2] || w->fio_words[4] || w->fio_words[6];
}

static bool wave5_fio(WlWave5State *w,uint32_t control)
{
    if (control&~0x1ffffU) { return false; }
    unsigned address=control&0xffff,index;
    for (index=0;index<G_N_ELEMENTS(wave5_fio_offsets);index++) {
        if (wave5_fio_offsets[index]==address) { break; }
    }
    if (index==G_N_ELEMENTS(wave5_fio_offsets)) { return false; }
    uint32_t value=w->regs[WL_W5_REG(0x24)];
    bool status=index==1 || index==3 || index==5 || index==7;
    if (control&0x10000) {
        /* Original INIT40e53eb8 posts both SRAM-side configuration words
         * before the core-start request. These retain configuration only;
         * they cannot release or complete any microcode work. */
        if ((w->busy && index>=8) || ((index==16 || index==17) && value&~15U)) { return false; }
        if (status || (index==0 && value!=0 && value!=0x100) ||
            (index==2 && value!=0 && value!=7 && value!=255) ||
            ((index==4 || index==6) && value!=0 && value!=7)) { return false; }
        w->fio_words[index]=value;
    } else if (status) {
        bool held=w->fio_words[index-1]!=0;
        /* Existing accepted DMA drains before the bus-stop status becomes
         * idle. An unretired result/IRQ is still separately reset-protected. */
        if (!held || w->busy) { value=0; }
        else if (index==3 && w->fio_words[2]==255) { value=0; }
        else { value=0x3f; } /* pinned Nikon VDI compares exactly 0x3f */
        w->regs[WL_W5_REG(0x24)]=value;
    } else { w->regs[WL_W5_REG(0x24)]=w->fio_words[index]; }
    w->fio_address=address;w->regs[WL_W5_REG(0x20)]=control|0x80000000;
    return true;
}

static bool wave5_address(NikonZ8State *s, uint64_t address, uint64_t bytes, uint64_t *physical)
{
    if (!bytes || bytes > 256 * MiB) { return false; }
    /* Original VDI supplies the AXI address high word through FIO FEC0.
     * Apply it consistently to code, source and bitstream reservations;
     * otherwise a native low address can refer to an unrelated lab bank. */
    if (s->wave5 && s->wave5->fio_words[9]) {
        uint64_t extended=((uint64_t)s->wave5->fio_words[9]<<32)|address;
        if (!dma_ram_range(s,extended,bytes)) { return false; }
        *physical=extended;return true;
    }
    if (address>=UINT64_C(0x40000000) && address<UINT64_C(0x60000000)) {
        /* Declared virtual 32-bit AXI aperture, independently checked
         * against actual work RAM. Physical EXPEED master16 is unmeasured. */
        uint64_t mapped=UINT64_C(0xa00000000)+address-UINT64_C(0x40000000);
        if (address+bytes>UINT64_C(0x60000000) || !dma_ram_range(s,mapped,bytes)) { return false; }
        *physical=mapped;return true;
    }
    /* The explicit lab bus aperture overlaps low physical firmware RAM.
     * Resolve encoded DMA addresses first, rather than silently reading or
     * writing another RAM region at the same numerical 32-bit address. */
    if (raw_pipeline_address(s,address,bytes,physical) && dma_ram_range(s,*physical,bytes)) { return true; }
    if (address>=UINT64_C(0xa00000000) && dma_ram_range(s,address,bytes)) { *physical=address;return true; }
    return false;
}

static bool wave5_code_address(WlWave5State *w,uint32_t address,uint64_t bytes,uint64_t *physical)
{
    uint32_t high=w->fio_words[9]; /* FEC0: original VDI program extension */
    if (high) {
        uint64_t extended=((uint64_t)high<<32)|address;
        if (!bytes || bytes>4*MiB || !dma_ram_range(w->board,extended,bytes)) { return false; }
        *physical=extended;return true;
    }
    return wave5_address(w->board,address,bytes,physical);
}

static void wave5_irq_update(WlWave5State *w)
{
    bool asserted=(w->pending&w->interrupt_mask)!=0;
    w->regs[WL_W5_REG(0x30)]=w->pending;
    w->regs[WL_W5_REG(0x44)]=w->pending != 0;
    w->regs[WL_W5_REG(0x4c)]=w->pending;
    /* Original ZR ISR reads the shared controller before the VPU reason.
     * Only completed, enabled VPU work owns aggregate bit0. */
    w->board->video_processing_global[3]=
        (w->board->video_processing_global[3]&~1U)|asserted;
    if (w->irq) { qemu_set_irq(w->irq,asserted); }
}

static void wave5_complete(WlWave5State *w, unsigned reason)
{
    w->busy=false;w->board->wave5_busy=false;
    w->regs[WL_W5_REG(0x70)]=0;
    w->regs[WL_W5_REG(0x108)]=1;w->regs[WL_W5_REG(0x10c)]=0;
    unsigned instance=w->regs[WL_W5_REG(0x110)]&0xffff;
    if (instance<WL_W5_INSTANCES) {
        /* Native ISR retires per-instance bitmaps by read/modify/write.
         * Do not advertise an instance before its command has completed. */
        if (reason&((1U<<6)|(1U<<9))) { w->regs[WL_W5_REG(0x1fc)]|=1U<<instance; }
        if (reason&(1U<<8)) { w->regs[WL_W5_REG(0x1e8)]|=1U<<instance; }
        if (reason&(1U<<15)) { w->regs[WL_W5_REG(0x1e4)]|=1U<<instance; }
    }
    w->pending|=reason;w->completions++;wave5_irq_update(w);
}

static uint32_t wave5_virtual_tick(void)
{
    /* Recorded command latency on the lab virtual clock. These are not
     * vendor instruction counts or measured physical silicon timing. */
    return qemu_clock_get_ns(QEMU_CLOCK_VIRTUAL)/256;
}

static bool wave5_report(WlWave5State *w,WlWave5Instance *i)
{
    if (!i->report_requested) { return true; }
    /* Original ZR40e3c810 reads RET1a8+100 into the four header lengths;
     * 402ff918 adds a four-byte prefix to each before copying AUD/VPS/SPS/PPS.
     * Zero-filled header reports formerly produced four-byte empty NALs.
     * Report actual output lengths in the guest-owned CREATE reservation.
     * Picture statistics remain unmodeled, not original ISP arithmetic. */
    uint8_t report[16]={0};
    for (unsigned n = 0; n < 4; n++) { stl_le_p(report + 4 * n, i->header_lengths[n]); }
    return i->work_capacity>=0x110 &&
        address_space_write(&address_space_memory,i->work_physical+0x100,
            MEMTXATTRS_UNSPECIFIED,report,sizeof(report))==MEMTX_OK;
}

static void *wave5_encode_worker(void *opaque)
{
    WlWave5Job *job=opaque;WlWave5Instance *i=job->instance;
    unsigned bpp=i->depth>8 ? 2 : 1;
    uint8_t *planes[3]={job->input,job->input+(uint64_t)i->width*i->height*bpp,
        job->input+(uint64_t)i->width*i->height*bpp*5/4};
    bool valid=wl_hevc_picture(i->codec,planes,job->strides,job->pts,job->encoded,&job->nal_type);
    qemu_mutex_lock(&job->owner->lock);
    job->valid=valid;job->done=true;
    qemu_mutex_unlock(&job->owner->lock);
    return NULL;
}

static void wave5_tick(void *opaque)
{
    WlWave5State *w=opaque;WlWave5Job *job=w->job;
    if (!job) { return; }
    qemu_mutex_lock(&w->lock);bool done=job->done;qemu_mutex_unlock(&w->lock);
    if (!done) { timer_mod(w->timer,qemu_clock_get_ns(QEMU_CLOCK_VIRTUAL)+1000000);return; }
    WlWave5Instance *i=job->instance;
    bool success=job->valid && job->encoded->len && job->encoded->len<=job->capacity &&
        dma_ram_range(w->board,job->output,job->capacity) &&
        address_space_write(&address_space_memory,job->output,MEMTXATTRS_UNSPECIFIED,
                            job->encoded->data,job->encoded->len)==MEMTX_OK;
    if (success && !wave5_report(w,i)) { success=false; }
    if (success) {
        i->bytes=job->encoded->len;i->output=job->output;i->nal_type=job->nal_type;
        i->source_index=job->source_index;i->output_bus=job->output_bus;i->result=true;i->pictures++;
        i->main_surface=job->main_surface;
        i->recon_index=(i->pictures-1)%2;i->complete_tick=wave5_virtual_tick();
        if (i->ring) { i->ring_written+=i->bytes; }
        w->input_bytes+=job->input_bytes;w->output_bytes+=i->bytes;w->input_crc=job->input_crc;
        w->output_crc=crc32(0,job->encoded->data,job->encoded->len);
        w->regs[WL_W5_REG(0x1e0)]=1;
        wave5_complete(w,1U<<8);
    } else {
        /* An actual encoder error or overflow is a failed command, never a
         * zero-byte successful picture. No partial guest output is written. */
        w->regs[WL_W5_REG(0x108)]=0;w->regs[WL_W5_REG(0x10c)]=0x100;
        w->regs[WL_W5_REG(0x70)]=0;w->busy=false;w->board->wave5_busy=false;
        w->rejections++;
        video_main_release(w->board,job->main_surface);
    }
    g_free(job->input);g_byte_array_unref(job->encoded);g_free(job);w->job=NULL;
}

static bool wave5_snapshot(WlWave5State *w,WlWave5Instance *i,WlWave5Job *job)
{
    w->source_rejection="unsupported source format";
    uint32_t format=w->regs[WL_W5_REG(0x158)];
    unsigned packing=(format>>3)&3,justified=(format>>5)&1,layout=format&7;
    unsigned endian=(format>>6)&15;
    if (format&~0x3ffU || packing==3 || layout>3 || (endian!=0 && endian!=15 && endian!=12) ||
        (i->depth==10 && packing==0) || (i->depth==8 && packing!=0)) { return false; }
    unsigned sy=w->regs[WL_W5_REG(0x154)]>>16,sc=w->regs[WL_W5_REG(0x154)]&0xffff;
    unsigned bpp=i->depth>8 ? 2 : 1;
    bool interleaved=layout&2,nv21=layout&1;
    uint64_t addresses[3],sizes[3];
    unsigned rows[3]={i->height,i->height/2,i->height/2};
    unsigned samples[3]={i->width,interleaved ? i->width : i->width/2,i->width/2};
    unsigned strides[3]={sy,sc,sc};
    unsigned main_token=0;
    w->source_rejection="registered source pair is unavailable or changed";
    int main_mapping=video_main_resolve(w->board,w->regs[WL_W5_REG(0x148)],
        w->regs[WL_W5_REG(0x14c)],i->width,i->height,
        i->width-i->crop[0]-i->crop[2],i->height-i->crop[1]-i->crop[3],
        sy,sc,format,addresses,&main_token);
    if (main_mapping<0) { return false; }
    /* The registered hardware reader changes byte lanes; the actual stored
     * packet retains the producer's format. Direct RAM uses command endian. */
    if (main_mapping) {
        endian=(w->board->video_main->surface[main_token-1].source_format>>6)&15;
    }
    w->source_rejection="source stride, DMA span or output/work overlap";
    for (unsigned p=0;p<(interleaved ? 2 : 3);p++) {
        unsigned minrow=packing==2 ? (samples[p]+2)/3*4 : samples[p]*bpp;
        sizes[p]=(uint64_t)strides[p]*rows[p];
        uint64_t physical_size=main_mapping?video_main_physical_bytes(w->board,main_token,p):sizes[p];
        if (strides[p]<minrow || strides[p]>32768 || (endian==12 && (strides[p]&3)) ||
            (!main_mapping && !wave5_address(w->board,w->regs[WL_W5_REG(0x148+p*4)],sizes[p],&addresses[p])) ||
            !dma_ram_range(w->board,addresses[p],physical_size) ||
            graphics_spans_overlap(addresses[p],physical_size,i->work_physical,i->work_capacity) ||
            graphics_spans_overlap(addresses[p],physical_size,job->output,job->capacity)) { return false; }
        for (unsigned q=0;q<p;q++) {
            uint64_t other_size=main_mapping?video_main_physical_bytes(w->board,main_token,q):sizes[q];
            if (graphics_spans_overlap(addresses[p],physical_size,addresses[q],other_size)) {
                w->source_rejection="source planes overlap";return false;
            }
        }
    }
    uint64_t total=(uint64_t)i->width*i->height*bpp*3/2;
    if (total>128*MiB) { w->source_rejection="source exceeds copy bound";return false; }
    job->input=g_malloc(total);job->input_bytes=total;
    job->strides[0]=i->width*bpp;job->strides[1]=job->strides[2]=i->width/2*bpp;
    uint64_t offsets[3]={0,(uint64_t)i->width*i->height*bpp,(uint64_t)i->width*i->height*bpp*5/4};
    for (unsigned p=0;p<(interleaved ? 2 : 3);p++) {
        g_autofree uint8_t *row=g_malloc(strides[p]);
        g_autofree uint8_t *decoded=NULL;
        w->source_rejection="compact source header, generation or payload integrity";
        if (main_mapping && !video_main_read(w->board,main_token,p,&decoded)) { return false; }
        w->source_rejection="source RAM read failed";
        for (unsigned y=0;y<rows[p];y++) {
            if (decoded) { memcpy(row,decoded+(uint64_t)y*strides[p],strides[p]); }
            else if (address_space_read(&address_space_memory,addresses[p]+(uint64_t)y*strides[p],
                                  MEMTXATTRS_UNSPECIFIED,row,strides[p])!=MEMTX_OK) { return false; }
            for (unsigned x=0;x<samples[p];x++) {
                unsigned value;
                /* Native SRC_FORMAT332 inverts VDI32-bit-big code3 to12.
                 * Reverse byte lanes within each 32-bit storage word before
                 * sample unpacking. Complete rows and padding remain intact;
                 * another endian/layout still requires its own contract. */
                if (!packing) { value=row[endian==12 ? (x^3u) : x]; }
                else if (packing==1) {
                    value=endian==12 ? lduw_be_p(row+((x*2)^2u)) : lduw_le_p(row+x*2);
                    value=justified ? value>>6 : value&1023;
                } else {
                    uint32_t word=endian==12 ? ldl_be_p(row+(x/3)*4) : ldl_le_p(row+(x/3)*4);
                    unsigned shift=justified ? 22-(x%3)*10 : (x%3)*10;
                    value=(word>>shift)&1023;
                }
                unsigned dest=p,index=x;
                if (interleaved && p==1) { dest=((x&1)^nv21) ? 2 : 1;index=x/2; }
                uint8_t *out=job->input+offsets[dest]+(uint64_t)y*job->strides[dest]+index*bpp;
                if (bpp==2) { stw_le_p(out,value); } else { *out=value; }
            }
        }
    }
    job->input_crc=crc32(0,job->input,total);
    video_main_acquire(w->board,main_token);job->main_surface=main_token;
    w->source_rejection=NULL;
    return true;
}

static bool wave5_command(WlWave5State *w,unsigned command,bool core_start)
{
    uint32_t *r=w->regs;
    unsigned info=r[WL_W5_REG(0x110)],idx=info&0xffff;
    if (w->external_reset_held) { return false; }
    if (w->busy || (w->sleeping && command!=2)) { return false; }
    if (wave5_bus_stopped(w) && command!=4) { return false; }
    bool global=command==1 || command==2 || command==4 ||
                (command==0x4000 && r[WL_W5_REG(0x104)]==0);
    if (!global && idx>=WL_W5_INSTANCES) { return false; }
    if (global) { idx=0; }
    WlWave5Instance *i=&w->instance[idx];
    if (!global && command!=8 && i->created && (info>>16)!=i->codec_mode) { return false; }
    if (command==1) {
        uint64_t code,temp;unsigned bytes=r[WL_W5_REG(0x114)],tmp=r[WL_W5_REG(0x120)];
        w->boot_rejection=NULL;
        if (!core_start || w->booted || !bytes || bytes>4*MiB || (bytes&4095)) {
            w->boot_rejection="invalid core request or code size";return false;
        }
        if (!wave5_code_address(w,r[WL_W5_REG(0x110)],bytes,&code)) {
            w->boot_rejection="unmapped original code address";return false;
        }
        if (!wave5_code_address(w,r[WL_W5_REG(0x11c)],tmp,&temp)) {
            w->boot_rejection="unmapped original temporary address";return false;
        }
        if (graphics_spans_overlap(code,bytes,temp,tmp)) {
            w->boot_rejection="code and temporary spans overlap";return false;
        }
        g_autofree uint8_t *program=g_malloc(bytes);
        if (address_space_read(&address_space_memory,code,MEMTXATTRS_UNSPECIFIED,program,bytes)!=MEMTX_OK) { return false; }
        bool nonzero=false;
        for (unsigned n=0;n<bytes;n++) { nonzero|=program[n]!=0; }
        if (!nonzero) { w->boot_rejection="supplied code is all zero";return false; }
        w->boot_crc=crc32(0,program,bytes);w->boot_bytes=bytes;w->boot_physical=code;
        if (!w->board->wave5_host_codec_diagnostic) {
            /* The original driver has supplied code, but there is no vendor
             * core decoder yet. Preserve its DMA evidence and refuse INIT;
             * never substitute a host service PC or fabricate boot success. */
            w->boot_rejection="original VPU instruction core unavailable";return false;
        }
        w->booted=true;
        r[WL_W5_REG(4)]=4; /* functional service entry; not executed microcode PC */
        wave5_complete(w,0);
    } else if (!w->booted) { return false; }
    else if (command==2) {
        w->sleeping=false;wave5_complete(w,0);
    }
    else if (command==8) {
        unsigned mode = info >> 16;
        if (i->created || (mode != 1 && mode != 3)) { return false; }
        bool ring=(r[WL_W5_REG(0x124)]&(1U<<9))!=0;
        uint64_t physical=0,work=0;
        unsigned ring_bus=r[WL_W5_REG(0x11c)],capacity=r[WL_W5_REG(0x120)];
        unsigned work_bus=r[WL_W5_REG(0x114)],work_capacity=r[WL_W5_REG(0x118)];
        if (work_capacity<0x110 || work_capacity>4*MiB ||
            !wave5_address(w->board,work_bus,work_capacity,&work) ||
            graphics_spans_overlap(work,work_capacity,w->boot_physical,w->boot_bytes)) { return false; }
        /* Original ZR40e57cb8 supplies ring start/size during CREATE.
         * Later SET_PARAM/SET_FB overwrite the command register window. */
        if (ring && (!capacity || capacity>256*MiB ||
            !wave5_address(w->board,ring_bus,capacity,&physical) ||
            graphics_spans_overlap(physical,capacity,work,work_capacity))) { return false; }
        i->work_physical=work;i->work_bus=work_bus;i->work_capacity=work_capacity;
        i->ring=ring;i->ring_bus=ring_bus;i->ring_capacity=capacity;i->ring_physical=physical;
        i->codec_mode=mode;i->created=true;w->instances++;wave5_complete(w,1U<<3);
    } else if (command==0x200) {
        if (!i->created || i->result || i->codec) { return false; }
        if (r[WL_W5_REG(0x104)]==1) {
            /* Counted custom GOP syntax retained. The functional profile
             * uses low-delay IP references; reordering is not verified. */
            if ((r[WL_W5_REG(0x11c)]&0xff)>8) { return false; }
            wave5_complete(w,1U<<9);
        } else if (r[WL_W5_REG(0x104)]==0) {
            unsigned size=r[WL_W5_REG(0x11c)],depth=(r[WL_W5_REG(0x124)]>>14)&15;
            unsigned width=size&0xffff,height=size>>16;
            unsigned n=r[WL_W5_REG(0x178)],d=r[WL_W5_REG(0x174)];
            unsigned crop[4]={r[WL_W5_REG(0x138)]&0xffff,r[WL_W5_REG(0x134)]&0xffff,
                r[WL_W5_REG(0x138)]>>16,r[WL_W5_REG(0x134)]>>16};
            if (!n || !d) { n=r[WL_W5_REG(0x150)];d=1; }
            else if (i->codec_mode==3) {
                if (d>500000) { return false; }
                d*=2; /* AVC VUI: time_scale/(2*num_units_in_tick). */
            }
            if (!width || !height || (width|height)&1 || (depth!=8 && depth!=10) ||
                !n || !d || n>1000000 || d>1000000 || r[WL_W5_REG(0x170)] ||
                ((crop[0]|crop[1]|crop[2]|crop[3])&1) || crop[0]+crop[2]>=width ||
                crop[1]+crop[3]>=height ||
                (i->codec_mode!=3 && (r[WL_W5_REG(0x138)] || r[WL_W5_REG(0x134)]))) { return false; }
            memcpy(i->crop,crop,sizeof(crop));
            /* Public Wave5 INTRA_PARAM field layout. Native MOV indexing
             * follows the configured intra period; a host default250 GOP
             * cannot substitute for a requested15-frame GOP. */
            unsigned intra=r[WL_W5_REG(0x130)];
            i->keyframe_period=i->codec_mode==3 ? ((intra>>17)&0x7ff) : intra>>16;
            if (i->codec_mode==3 && !i->keyframe_period) {
                i->keyframe_period=(intra>>6)&0x7ff;
            }
            i->width=width;i->height=height;i->depth=depth;i->fps_n=n;i->fps_d=d;i->configured=true;
            i->sequence_result=true;r[WL_W5_REG(0x1e0)]=1;
            wave5_complete(w,1U<<9);
        } else { return false; }
    } else if (command==0x80) {
        if (!i->configured || i->result) { return false; }
        /* Retained framebuffer descriptors are management reservations;
         * codec references live in x265, no fictitious FBC bytes are made. */
        i->buffers=true;wave5_complete(w,0);
    } else if (command==0x100) {
        if (!i->configured || !i->buffers || i->result || w->pending) { return false; }
        uint64_t output;unsigned output_bus=r[WL_W5_REG(0x118)];
        unsigned capacity=r[WL_W5_REG(0x11c)];
        if (i->ring) {
            /* Until reader/wrap ownership is implemented, use only the
             * remaining actual reservation; never overwrite unread bytes. */
            if (i->ring_written>=i->ring_capacity) { return false; }
            output_bus=i->ring_bus+i->ring_written;capacity=i->ring_capacity-i->ring_written;
        }
        if (!capacity || capacity>(i->ring ? 256 : 64)*MiB ||
            !wave5_address(w->board,output_bus,capacity,&output) ||
            graphics_spans_overlap(output,capacity,i->work_physical,i->work_capacity)) { return false; }
        if (!i->codec) {
            i->codec=wl_video_open(i->codec_mode,i->width,i->height,i->depth,i->fps_n,i->fps_d,w->lossless,i->crop,i->keyframe_period);
            if (!i->codec) { return false; }
        }
        unsigned option=r[WL_W5_REG(0x164)],source=r[WL_W5_REG(0x144)];
        /* Bit0 implicit headers, bit1 VCL; bit4 is PPS, not a picture.
         * Native header-only40e59dac requests VPS/SPS/PPS/AUD with0x3c. */
        bool headers=!(option&3);
        i->submit_tick=wave5_virtual_tick();
        i->report_requested=(r[WL_W5_REG(0x128)]&4)!=0;
        memset(i->header_lengths, 0, sizeof(i->header_lengths));
        if (headers || source==UINT32_MAX) {
            GByteArray *payload=g_byte_array_new();
            bool ok=true;
            if (headers) { ok=wl_hevc_headers(i->codec,payload,option,i->header_lengths); }
            else {
                static const uint8_t hevc_eos[]={0,0,0,1,0x48,1,0x80};
                static const uint8_t avc_eos[]={0,0,0,1,0x0a,0x80};
                if (i->codec_mode==3) { g_byte_array_append(payload,avc_eos,sizeof(avc_eos)); }
                else { g_byte_array_append(payload,hevc_eos,sizeof(hevc_eos)); }
            }
            if (!ok || !payload->len || payload->len>capacity || !wave5_report(w,i) ||
                address_space_write(&address_space_memory,output,MEMTXATTRS_UNSPECIFIED,payload->data,payload->len)!=MEMTX_OK) {
                g_byte_array_unref(payload);return false;
            }
            i->output=output;i->output_bus=output_bus;i->bytes=payload->len;i->source_index=UINT32_MAX;
            i->nal_type=i->codec_mode==3 ? (headers ? 7 : 10) : (headers ? 32 : 36);i->result=true;
            i->recon_index=headers ? -3 : -1;i->complete_tick=wave5_virtual_tick();
            if (i->ring) { i->ring_written+=i->bytes; }
            w->output_bytes+=payload->len;w->output_crc=crc32(0,payload->data,payload->len);
            g_byte_array_unref(payload);r[WL_W5_REG(0x1e0)]=1;wave5_complete(w,1U<<8);
        } else {
            WlWave5Job *job=g_new0(WlWave5Job,1);job->owner=w;job->instance=i;
            job->source_index=source;job->pts=i->pictures;job->output=output;job->output_bus=output_bus;job->capacity=capacity;
            job->encoded=g_byte_array_new();
            if (!wave5_snapshot(w,i,job)) {
                g_free(job->input);g_byte_array_unref(job->encoded);g_free(job);return false;
            }
            w->job=job;w->busy=true;w->board->wave5_busy=true;r[WL_W5_REG(0x70)]=1;
            QemuThread worker;qemu_thread_create(&worker,"wl-hevc",wave5_encode_worker,job,QEMU_THREAD_DETACHED);
            timer_mod(w->timer,qemu_clock_get_ns(QEMU_CLOCK_VIRTUAL)+1000000);
        }
    } else if (command==0x4000) {
        unsigned query=r[WL_W5_REG(0x104)];
        if (query==0) {
            r[WL_W5_REG(0x118)]=0x10000;r[WL_W5_REG(0x11c)]=0x574c3556;
            r[WL_W5_REG(0x120)]=0x5210;r[WL_W5_REG(0x124)]=0;
            r[WL_W5_REG(0x128)]=3; /* Public Wave5 convention: HEVC/AVC encoders. */
            r[WL_W5_REG(0x12c)]=(1U<<3)|(1U<<11); /* Functional 10-bit HEVC/AVC. */
            r[WL_W5_REG(0x130)]=0;r[WL_W5_REG(0x134)]=0;r[WL_W5_REG(0x140)]=0;
        } else if (query==2) {
            if (!i->created || (!i->sequence_result && !i->result)) { return false; }
            /* Command acceptance (108) is independent of operation success
             * (1dc). Native ZR40e5890c reads sequence requirements before
             * allocating reference/task reservations. Never return stale
             * SET_PARAM addresses as byte counts or a fake picture result. */
            r[WL_W5_REG(0x1dc)]=1;
            r[WL_W5_REG(0x1d4)]=0;r[WL_W5_REG(0x1d8)]=0;
            r[WL_W5_REG(0x1e0)]=0;
            if (i->sequence_result && !i->result) {
                r[WL_W5_REG(0x11c)]=2;r[WL_W5_REG(0x120)]=2;
                r[WL_W5_REG(0x16c)]=0;
                /* Explicit virtual management reservations. The host codec
                 * owns references; these are not measured VPU/FBC sizes. */
                r[WL_W5_REG(0x1b0)]=4096;r[WL_W5_REG(0x1b4)]=4096;
                i->sequence_result=false;
                wave5_complete(w,0);
                w->commands++;w->last_command=command;return true;
            }
            r[WL_W5_REG(0x114)]=i->output_bus;
            r[WL_W5_REG(0x118)]=i->output_bus+i->bytes;
            r[WL_W5_REG(0x11c)]=2;r[WL_W5_REG(0x120)]=2;
            /* Key pictures can recur after the first frame. Report the
             * actual encoded access unit, not the lifetime frame count. */
            r[WL_W5_REG(0x124)]=i->codec_mode==3 ?
                (i->nal_type==5 ? 0 : 1) :
                (i->nal_type>=16 && i->nal_type<=23 ? 0 : 1);
            r[WL_W5_REG(0x128)]=i->pictures ? i->pictures-1 : 0;
            /* Native40e59c1c explicitly recognizes HEADER_ONLY=-3. A
             * header has no reconstructed picture or consumed source. */
            r[WL_W5_REG(0x12c)]=(uint32_t)i->recon_index;
            r[WL_W5_REG(0x14c)]=i->result ? i->bytes : 0;
            r[WL_W5_REG(0x154)]=i->result ? i->source_index : UINT32_MAX;
            r[WL_W5_REG(0x158)]=i->pictures;
            r[WL_W5_REG(0x130)]=1;r[WL_W5_REG(0x134)]=0;
            r[WL_W5_REG(0x138)]=0;r[WL_W5_REG(0x13c)]=0;
            r[WL_W5_REG(0x144)]=0;r[WL_W5_REG(0x148)]=0;
            r[WL_W5_REG(0x150)]=i->pictures ? i->pictures-1 : 0;
            r[WL_W5_REG(0x16c)]=0;r[WL_W5_REG(0x170)]=0;
            r[WL_W5_REG(0x164)]=0;r[WL_W5_REG(0x168)]=0;
            r[WL_W5_REG(0x18c)]=i->source_index<32 ? 1U<<i->source_index : 0;
            r[WL_W5_REG(0x19c)]=0;
            r[WL_W5_REG(0x1a8)]=i->report_requested ? i->work_bus : 0;
            r[WL_W5_REG(0x1b8)]=i->submit_tick;
            r[WL_W5_REG(0x1bc)]=r[WL_W5_REG(0x1c0)]=i->submit_tick;
            r[WL_W5_REG(0x1c4)]=r[WL_W5_REG(0x1c8)]=i->submit_tick;
            r[WL_W5_REG(0x1cc)]=i->submit_tick;r[WL_W5_REG(0x1d0)]=i->complete_tick;
            r[WL_W5_REG(0x15c)]=i->nal_type;r[WL_W5_REG(0x1e0)]=0;
            video_main_release(w->board,i->main_surface);i->main_surface=0;
            i->result=false;
        } else if (query==6) { r[WL_W5_REG(0x114)]=i->ring ? i->ring_bus+i->ring_written : i->output_bus+i->bytes; }
        else if (query==7) { r[WL_W5_REG(0x114)]=0; }
        else { return false; }
        wave5_complete(w,0);
    } else if (command==0x20 || command==0x10) {
        if (!i->created || i->result || w->pending) { return false; }
        wl_hevc_close(i->codec);i->codec=NULL;
        if (command==0x20) { memset(i,0,sizeof(*i));w->instances--; }
        wave5_complete(w,0);
    } else if (command==4) {
        if (w->pending) { return false; }
        w->sleeping=true;wave5_complete(w,0);
    } else { return false; }
    w->commands++;w->last_command=command;return true;
}

/* The native movie power sequence asserts all seven bank8 bits16..22
 * after destroying its codec, and releases them before the next INIT.
 * Previously these writes only changed the bootstrap latch: CUR_PC stayed
 * nonzero and the original VDI returned CALLED_BEFORE on a fresh session.
 * Model the observed complete reset bundle, not an invented mapping of an
 * individual bit to a physical subcore. Active DMA/results remain protected.
 */
static bool wave5_external_reset(NikonZ8State *s,hwaddr address,uint32_t value)
{
    const uint32_t bundle=0x007f0000;
    WlWave5State *w=s->wave5;
    if (!s->wave5_model || !(value&bundle)) { return true; }
    bool release=address==0x0d154248;
    if (!release && (w->busy || w->job || w->pending || w->instances)) {
        w->rejections++;return false;
    }
    uint32_t held=release ? w->external_reset_held&~value :
                           w->external_reset_held|(value&bundle);
    if (held==bundle && w->external_reset_held!=bundle) {
        memset(w->regs,0,sizeof(w->regs));
        memset(w->fio_words,0,sizeof(w->fio_words));
        w->fio_address=0;w->fio_data=0;
        w->booted=false;w->sleeping=false;w->interrupt_mask=0;
        w->boot_physical=0;w->boot_bytes=0;w->boot_crc=0;
        w->external_resets++;wave5_irq_update(w);
    }
    w->external_reset_held=held;
    return true;
}

static bool wave5_access(NikonZ8State *s,hwaddr address,uint64_t *value,unsigned size,bool write)
{
    if (!s->wave5_model || address<WL_W5_BASE || address>=WL_W5_BASE+0x2000) { return false; }
    WlWave5State *w=s->wave5;unsigned off=address-WL_W5_BASE;
    if (size!=4 || (off&3) || (off>=0x200 && off!=0x1040 && off!=0x1044)) { goto rejected; }
    unsigned word=off/4;
    if (!write) {
        *value=off==0x1044 ? 0x5210 : off==0x1040 ? 0x574c3556 : w->regs[word];w->reads++;return true;
    }
    if (off==0x1044 || off==0x1040 || off==4 || off==8) { goto rejected; }
    if (w->busy && off!=0x34 && off!=0x3c && off!=0x48 && off!=0x20 && off!=0x24) { goto rejected; }
    uint32_t v=*value;
    if (off==0x34) { w->pending&=~v;wave5_irq_update(w); }
    else if (off==0x3c) { if (v!=1) { goto rejected; }wave5_irq_update(w); }
    else if (off==0x48) { w->interrupt_mask=v;w->regs[word]=v;wave5_irq_update(w); }
    else if (off==0x50) {
        if (w->pending || (v&~0x3fffffffU)) { goto rejected; }
        for (unsigned i=0;i<WL_W5_INSTANCES;i++) {
            if (w->instance[i].result) { goto rejected; }
        }
        if (v) {
            for (unsigned i=0;i<WL_W5_INSTANCES;i++) { wl_hevc_close(w->instance[i].codec);memset(&w->instance[i],0,sizeof(w->instance[i])); }
            memset(w->regs,0,sizeof(w->regs));w->booted=false;w->sleeping=false;w->instances=0;w->resets++;
        }
        w->regs[word]=v;w->regs[WL_W5_REG(0x54)]=0;
    } else if (off==0x100) { w->regs[word]=v; }
    else if (off==0x6c || off==0x38) {
        if (v!=1 || !w->regs[WL_W5_REG(0x70)] ||
            !wave5_command(w,w->regs[WL_W5_REG(0x100)],off==0x6c)) { goto rejected; }
    } else if (off==0x20) {
        if (!wave5_fio(w,v)) { goto rejected; }
    } else if (off==0x70) { if (v>1) { goto rejected; }w->regs[word]=v; }
    else if (off==0 || off==0x58 || off==0x5c || off==0x60 || off==0x64 || off==0x68 || off==0x24 || (off>=0x104 && off<0x200)) { w->regs[word]=v; }
    else { goto rejected; }
    w->writes++;return true;
rejected:
    w->rejections++;
    fprintf(stderr,"Z8_WAVE5_REJECT off=%x write=%u value=%" PRIx64 " busy=%u boot=%u; no completion\n",off,write,*value,w->busy,w->booted);
    return false;
}

static bool get_wave5_model(Object *obj,Error **errp) { return NIKON_Z8_LAB(obj)->wave5_model; }
static char *get_wave5_irq(Object *obj,Error **errp) { return g_strdup_printf("%u",NIKON_Z8_LAB(obj)->wave5_irq_number); }
static void set_wave5_irq(Object *obj,const char *text,Error **errp)
{
    NikonZ8State *s=NIKON_Z8_LAB(obj);const char *end;unsigned long number;
    if (qemu_strtoul(text,&end,0,&number) || *end || (number && (number<32 || number>=512)) || s->wave5_busy ||
        (s->wave5_realized && number!=s->wave5_irq_number)) {
        error_setg(errp,"Wave5 SPI must be an explicit virtual GIC binding or zero for polling");return;
    }
    s->wave5_irq_number=number;
}
static void set_wave5_model(Object *obj,bool value,Error **errp)
{
    NikonZ8State *s=NIKON_Z8_LAB(obj);
    if (s->wave5 && (s->wave5_busy || s->wave5->pending || s->wave5->instances)) { error_setg(errp,"Wave5 owns a command, instance or completion");return; }
    if (value && !s->wave5) {
        s->wave5=g_new0(WlWave5State,1);s->wave5->board=s;s->wave5->lossless=s->wave5_lossless_requested;
        qemu_mutex_init(&s->wave5->lock);s->wave5->timer=timer_new_ns(QEMU_CLOCK_VIRTUAL,wave5_tick,s->wave5);
    }
    s->wave5_model=value;
}
static bool get_wave5_lossless(Object *obj,Error **errp) { return NIKON_Z8_LAB(obj)->wave5_lossless_requested; }
static bool get_wave5_diagnostic(Object *obj,Error **errp) { return NIKON_Z8_LAB(obj)->wave5_host_codec_diagnostic; }
static void set_wave5_diagnostic(Object *obj,bool value,Error **errp)
{
    NikonZ8State *s=NIKON_Z8_LAB(obj);
    if (s->wave5_realized) { error_setg(errp,"Choose diagnostic host codec before realization");return; }
    s->wave5_host_codec_diagnostic=value;
}
static void set_wave5_lossless(Object *obj,bool value,Error **errp)
{
    NikonZ8State *s=NIKON_Z8_LAB(obj);
    if ((s->wave5 && s->wave5->instances) || s->wave5_busy) { error_setg(errp,"Choose lossless before any instance");return; }
    s->wave5_lossless_requested=value;
    if (s->wave5) { s->wave5->lossless=value; }
}
static char *get_wave5_state(Object *obj,Error **errp)
{
    NikonZ8State *s=NIKON_Z8_LAB(obj);WlWave5State *w=s->wave5;
    if (!w) { return g_strdup("{\"enabled\":false}"); }
    GString *j=g_string_new(NULL);
    g_string_append_printf(j,"{\"external_reset_held\":%u,\"external_resets\":%" PRIu64 ",",
        w->external_reset_held,w->external_resets);
    g_string_append_printf(j,"\"enabled\":%s,\"virtual_product\":%u,\"booted\":%s,\"busy\":%s,\"pending\":%u,"
        "\"writes\":%" PRIu64 ",\"reads\":%" PRIu64 ",\"commands\":%" PRIu64 ",\"completions\":%" PRIu64 ","
        "\"rejects\":%" PRIu64 ",\"boot_bytes\":%" PRIu64 ",\"boot_crc\":%u,\"input_bytes\":%" PRIu64 ","
        "\"output_bytes\":%" PRIu64 ",\"input_crc\":%u,\"output_crc\":%u,"
        "\"irq_number\":%u,\"interrupt_mask\":%u,\"irq_asserted\":%s,\"last_command\":%u,\"instances\":[",
        s->wave5_model ? "true" : "false",0x5210,w->booted ? "true" : "false",w->busy ? "true" : "false",w->pending,
        w->writes,w->reads,w->commands,w->completions,w->rejections,w->boot_bytes,w->boot_crc,w->input_bytes,w->output_bytes,w->input_crc,w->output_crc,
        s->wave5_irq_number,w->interrupt_mask,(w->pending&w->interrupt_mask) ? "true" : "false",w->last_command);
    for (unsigned n=0;n<WL_W5_INSTANCES;n++) {
        WlWave5Instance *i=&w->instance[n];
        g_string_append_printf(j,"%s{\"created\":%s,\"configured\":%s,\"width\":%u,\"height\":%u,\"depth\":%u,\"pictures\":%" PRIu64 ",\"result\":%s,\"bytes\":%u,"
            "\"ring\":%s,\"ring_bus\":%u,\"ring_capacity\":%u,\"ring_written\":%u,"
            "\"codec_mode\":%u,\"display_width\":%u,\"display_height\":%u,\"crop\":[%u,%u,%u,%u],\"fps_n\":%u,\"fps_d\":%u,\"keyframe_period\":%u}",
            n ? "," : "",i->created ? "true" : "false",i->configured ? "true" : "false",i->width,i->height,i->depth,i->pictures,i->result ? "true" : "false",i->bytes,
            i->ring ? "true" : "false",i->ring_bus,i->ring_capacity,i->ring_written,
            i->codec_mode,i->width-i->crop[0]-i->crop[2],i->height-i->crop[1]-i->crop[3],
            i->crop[0],i->crop[1],i->crop[2],i->crop[3],i->fps_n,i->fps_d,i->keyframe_period);
    }
    g_string_append(j,"],\"fio_configuration\":{");
    for (unsigned n=0;n<G_N_ELEMENTS(wave5_fio_offsets);n++) {
        g_string_append_printf(j,"%s\"0x%x\":%u",n ? "," : "",wave5_fio_offsets[n],w->fio_words[n]);
    }
    g_string_append(j,"},\"command_registers\":{");
    for (unsigned n=0x100;n<0x200;n+=4) {
        g_string_append_printf(j,"%s\"0x%x\":%u",n==0x100 ? "" : ",",n,w->regs[n/4]);
    }
    g_string_append_printf(j,"},\"source_rejection\":\"%s\",\"boot_rejection\":\"%s\",\"original_execution_required\":%s,\"diagnostic_host_codec\":%s,\"boot_physical\":%" PRIu64 ","
        "\"physical_identity_verified\":false,\"vendor_microcode_executed\":false,"
        "\"scope\":\"virtual VDI control; original code DMA evidence; explicitly optional diagnostic host codec\"}",
        w->source_rejection ? w->source_rejection : "",w->boot_rejection ? w->boot_rejection : "",s->wave5_host_codec_diagnostic ? "false" : "true",
        s->wave5_host_codec_diagnostic ? "true" : "false",w->boot_physical);
    return g_string_free(j,false);
}
