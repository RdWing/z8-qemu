/* SPDX-License-Identifier: GPL-2.0-or-later */
/* Bounded physical NV16 producer records. Metadata never substitutes for
 * RAM, completion or a guest ACK. Count passes do not release a frame. */
static bool capture_pool_overlap(uint64_t a, uint64_t n, uint64_t b, uint64_t m)
{ return a < b + m && b < a + n; }

static bool capture_pool_writable(NikonZ8State *s, const uint64_t *p,
                                  const uint64_t *n, unsigned count,
                                  unsigned records)
{
    if (!s->capture_frame_pool_model) { return true; }
    unsigned free_slots = 0;
    for (unsigned i = 0; i < ARRAY_SIZE(s->capture_surfaces); i++) {
        const Ex7CaptureSurface *f = &s->capture_surfaces[i];
        if (!f->valid || f->committed) { free_slots++; continue; }
        uint64_t bytes = (uint64_t)f->stride * f->height;
        for (unsigned j = 0; j < count; j++) {
            if (capture_pool_overlap(p[j],n[j],f->y,bytes) ||
                capture_pool_overlap(p[j],n[j],f->uv,bytes)) { return false; }
        }
    }
    return free_slots >= records;
}

static void capture_pool_record(NikonZ8State *s, unsigned kind, unsigned output,
                                uint64_t generation, uint64_t y, uint64_t uv,
                                unsigned w, unsigned h, unsigned stride)
{
    if (!s->capture_frame_pool_model) { return; }
    uint64_t bytes = (uint64_t)stride * h;
    int slot = -1;
    for (unsigned i = 0; i < ARRAY_SIZE(s->capture_surfaces); i++) {
        Ex7CaptureSurface *f = &s->capture_surfaces[i];
        uint64_t old_bytes = (uint64_t)f->stride * f->height;
        if (f->valid && (capture_pool_overlap(y,bytes,f->y,old_bytes) ||
            capture_pool_overlap(y,bytes,f->uv,old_bytes) ||
            capture_pool_overlap(uv,bytes,f->y,old_bytes) ||
            capture_pool_overlap(uv,bytes,f->uv,old_bytes))) {
            /* The complete destination set was checked before any DMA. */
            g_assert(f->committed);
            f->valid = false;
        }
        if (!f->valid && slot < 0) { slot = i; }
    }
    if (slot < 0) {
        for (unsigned i = 0; i < ARRAY_SIZE(s->capture_surfaces); i++) {
            Ex7CaptureSurface *f = &s->capture_surfaces[i];
            if (f->committed && (slot < 0 || f->serial < s->capture_surfaces[slot].serial)) { slot = i; }
        }
    }
    g_assert(slot >= 0);
    s->capture_surfaces[slot] = (Ex7CaptureSurface){
        .valid=true,.kind=kind,.output=output,.generation=generation,
        .y=y,.uv=uv,.width=w,.height=h,.stride=stride,
        .serial=++s->capture_pool_productions,
    };
}

static bool capture_pool_current_owned(NikonZ8State *s)
{
    unsigned found = 0;
    for (unsigned j = 0; j < 3; j++) {
        if (s->capture_nv16_jpeg_consumed[j] == s->capture_nv16_jobs) { found |= 1u << j; }
    }
    for (unsigned i = 0; i < ARRAY_SIZE(s->capture_surfaces); i++) {
        const Ex7CaptureSurface *f = &s->capture_surfaces[i];
        if (f->valid && f->kind == 0 && f->generation == s->capture_nv16_jobs) {
            found |= 1u << f->output;
        }
    }
    return found == 7;
}

static int capture_pool_thumbnail_source(NikonZ8State *s, uint64_t y, uint64_t uv,
                                         unsigned w, unsigned h, unsigned stride)
{
    for (unsigned i = 0; i < ARRAY_SIZE(s->capture_surfaces); i++) {
        const Ex7CaptureSurface *f = &s->capture_surfaces[i];
        if (f->valid && f->kind == 0 && f->output > 0 && !f->thumbnail_used &&
            f->y == y && f->uv == uv && f->width == w && f->height == h && f->stride == stride) { return i; }
    }
    return -1;
}

static bool capture_pool_border(NikonZ8State *s, const Ex7CaptureSurface *f,
                                 const uint32_t *c)
{
    unsigned h=c[0x41c/4],w=c[0x418/4],stride=c[0x410/4];
    if (f->kind != 1 || h < f->height || h-f->height > 32 || ((h-f->height)&1) ||
        w != f->width || stride != f->stride || c[0x414/4] != stride) { return false; }
    unsigned pad=(h-f->height)/2;
    uint64_t head=(uint64_t)pad*stride,plane=(uint64_t)h*stride;
    uint64_t y=(uint64_t)c[0x430/4]<<4,uv=(uint64_t)c[0x434/4]<<4;
    if (f->y < head || f->uv < head || y != f->y-head || uv != f->uv-head ||
        !plane || plane > 4*MiB || !dma_ram_range(s,y,plane) || !dma_ram_range(s,uv,plane)) { return false; }
    uint8_t *row=g_malloc(stride);
    bool ok=true;
    for (unsigned p=0;ok && p<2;p++) {
        for (unsigned r=0;ok && r<h;r++) {
            if (r>=pad && r<pad+f->height) { continue; }
            if (address_space_read(&address_space_memory,(p?uv:y)+(uint64_t)r*stride,
                    MEMTXATTRS_UNSPECIFIED,row,stride)!=MEMTX_OK) { ok=false;break; }
            for (unsigned x=0;x<w;x++) { if (row[x]!=(p?128:0)) { ok=false;break; } }
        }
    }
    g_free(row);return ok;
}

static int capture_pool_jpeg_owner(NikonZ8State *s, unsigned bank)
{
    const uint32_t *c=s->engine15e2_config[bank];
    for (unsigned i=0;i<ARRAY_SIZE(s->capture_surfaces);i++) {
        const Ex7CaptureSurface *f=&s->capture_surfaces[i];
        if (!f->valid || (f->committed && !s->engine15e2_preflight_model)) { continue; }
        bool exact=f->y==((uint64_t)c[0x430/4]<<4) && f->uv==((uint64_t)c[0x434/4]<<4) &&
            f->width==c[0x418/4] && f->height==c[0x41c/4] && f->stride==c[0x410/4];
        if (exact || (s->engine15e2_preflight_model && capture_pool_border(s,f,c))) { return 8+i; }
    }
    return -1;
}

static bool capture_pool_small_owner(NikonZ8State *s, int owner)
{
    if (owner < 8 || (unsigned)(owner-8) >= ARRAY_SIZE(s->capture_surfaces)) { return false; }
    const Ex7CaptureSurface *f=&s->capture_surfaces[owner-8];
    return f->valid && (f->kind == 1 || f->output > 0);
}

static void capture_pool_jpeg_complete(NikonZ8State *s, int owner, bool count)
{
    Ex7CaptureSurface *f=&s->capture_surfaces[owner-8];
    if (count) { f->count_passes++;s->engine15e2_count_jobs++;return; }
    f->committed=true;f->commits++;
    if (f->kind==0 && f->generation==s->capture_nv16_jobs) {
        s->capture_nv16_jpeg_consumed[f->output]=f->generation;
    } else if (f->kind==1 && f->generation==s->capture_thumbnail_jobs) {
        s->engine15e2_thumbnail_consumed=f->generation;
    }
}

static bool get_capture_frame_pool(Object *obj, Error **errp)
{ return NIKON_Z8_LAB(obj)->capture_frame_pool_model; }
static void set_capture_frame_pool(Object *obj, bool value, Error **errp)
{
    NikonZ8State *s=NIKON_Z8_LAB(obj);
    if (s->image_ram.ram || s->image_ram.rom_device) { error_setg(errp,"capture frame pool immutable after realization");return; }
    s->capture_frame_pool_model=value;
}
static char *get_capture_frame_pool_state(Object *obj, Error **errp)
{
    NikonZ8State *s=NIKON_Z8_LAB(obj);GString *out=g_string_new(NULL);
    g_string_append_printf(out,"{\"enabled\":%s,\"capacity\":%zu,\"productions\":%"PRIu64",\"frames\":[",
        s->capture_frame_pool_model?"true":"false",ARRAY_SIZE(s->capture_surfaces),s->capture_pool_productions);
    bool comma=false;
    for (unsigned i=0;i<ARRAY_SIZE(s->capture_surfaces);i++) {
        const Ex7CaptureSurface *f=&s->capture_surfaces[i];if(!f->valid){continue;}
        g_string_append_printf(out,"%s{\"slot\":%u,\"kind\":%u,\"output\":%u,\"generation\":%"PRIu64
            ",\"y\":%"PRIu64",\"uv\":%"PRIu64",\"width\":%u,\"height\":%u,\"stride\":%u,"
            "\"committed\":%s,\"thumbnail_used\":%s,\"count_passes\":%"PRIu64",\"commits\":%"PRIu64"}",
            comma?",":"",i,f->kind,f->output,f->generation,f->y,f->uv,f->width,f->height,f->stride,
            f->committed?"true":"false",f->thumbnail_used?"true":"false",f->count_passes,f->commits);comma=true;
    }
    g_string_append(out,"],\"camera_acceptance\":false}");return g_string_free(out,false);
}
