/* SPDX-License-Identifier: GPL-2.0-or-later
 * Authored in-process bridge. The separately licensed public inverse is in
 * nikon-he-public; no firmware, reference picture or vendor SDK is linked. */
#include "nikon-he-runtime.h"
#include "nikon-he-forward.inc"
#include "nikon-he-public/nikon_he_decode.h"
#include "nikon-he-public/nikon_he_picture_header.h"
#include "nikon-he-public/nikon_he_gtli_table.h"
#include "nikon-he-public/nikon_he_precinct_header.h"
#include <cstring>
#include <mutex>

static std::mutex codec_mutex;
static bool geometry(unsigned w,unsigned h) {
    return w>=64 && h>=8 && !((w|h)&1) && w<=16384 && h<=8192 &&
           uint64_t(w)*h<=50000000;
}

extern "C" int wl_he_encode14(const uint8_t *packed,size_t bytes,unsigned w,
    unsigned h,unsigned pitch,uint8_t *output,size_t capacity) {
    try {
        if(!packed || !output || !geometry(w,h) || pitch<(w*14+7)/8 ||
           bytes!=uint64_t(pitch)*h || capacity<256 || capacity>32*1024*1024)return 0;
        Bytes raw(uint64_t(w)*h*2);
        for(unsigned y=0;y<h;y++)for(unsigned x=0;x<w;x++) {
            size_t at=size_t(y)*pitch+x*14/8;unsigned shift=(x*14)&7;
            uint32_t v=packed[at]|unsigned(packed[at+1])<<8;
            if(shift>2)v|=unsigned(packed[at+2])<<16;
            v=(v>>shift)&16383;size_t dst=(size_t(y)*w+x)*2;
            raw[dst]=v;raw[dst+1]=v>>8;
        }
        auto result=encode_frame(raw,w,h,diagnostic_header(w,h),capacity);
        std::memcpy(output,result.data(),capacity);return 1;
    }catch(...){return 0;}
}

extern "C" int wl_he_decode14(const uint8_t *packet,size_t bytes,unsigned w,
    unsigned h,uint16_t *output,size_t samples) {
    std::lock_guard<std::mutex> lock(codec_mutex);
    try {
        if(!packet || !output || !geometry(w,h) || samples!=uint64_t(w)*h ||
           bytes<256 || bytes>32*1024*1024)return 0;
        nikon_he::PictureHeader ph{};
        if(!nikon_he::parse_picture_header(packet,bytes,ph) ||
           !nikon_he::is_supported_picture_header(ph,bytes) || ph.Lcod!=bytes ||
           ph.hdr_width!=w || ph.hdr_height!=h)return 0;
        // Bound every precinct and slice before invoking the public inverse.
        size_t at=ph.precinct_offset;
        for(unsigned row=0;row<(h+3)/4;row++) {
            if(at+12>bytes)return 0;
            size_t size=(size_t(packet[at])<<16)|(unsigned(packet[at+1])<<8)|packet[at+2];size+=12;
            if(size>bytes-at || packet[at+3]>15 || packet[at+4]>25)return 0;
            nikon_he::PrecinctSizes sizes{};
            if(!nikon_he::parse_precinct_header(packet+at,size,w,sizes))return 0;
            // Current device emits predicted mode 3 for its 25 real bands.
            // Do not advertise arbitrary unqualified HE profiles as supported.
            for(unsigned n=0;n<25;n++)if(sizes.Dpb[n]!=3)return 0;
            if((packet[at+11]&63)!=0)return 0;
            at+=size;
            if((row&15)==15 && row+1<(h+3)/4) {
                if(at+6>bytes || be16(packet+at)!=0xff20 ||
                   be16(packet+at+2)!=4 || be16(packet+at+4)!=(row+1)/16)return 0;
                at+=6;
            }
        }
        if(at+2!=bytes || be16(packet+at)!=0xff11)return 0;
        size_t pih=2;
        while(pih+4<=ph.precinct_offset && be16(packet+pih)!=0xff12) {
            unsigned length=be16(packet+pih+2);
            if(length<2 || length+2>ph.precinct_offset-pih)return 0;
            pih+=length+2;
        }
        if(pih+41>ph.precinct_offset || be16(packet+pih+2)!=39)return 0;
        const uint8_t *tail=packet+pih+28;
        unsigned B=((tail[3]&15)<<8)|tail[4];
        unsigned A=((tail[7]&3)<<16)|(tail[8]<<8)|tail[9],C=tail[10]*256+tail[11];
        std::vector<int32_t> lut(81792);
        for(int i=0;i<int(lut.size());i++) {
            int64_t d=std::min(i,65535)-int(C),q;
            if(d<0)q=-d*d;else{int64_t t=(d*A+32768)>>16;q=t*t;}
            lut[i]=4*std::clamp(int64_t(B)+floor_div(q+163840,18),INT64_C(0),INT64_C(16383));
        }
        nikon_he::set_active_picture_header(&ph);
        auto result=nikon_he::decode_nikon_he_image(packet+ph.precinct_offset,
            bytes-ph.precinct_offset,w,h,lut.data(),output);
        nikon_he::set_active_picture_header(nullptr);
        return result.success?1:0;
    }catch(...){nikon_he::set_active_picture_header(nullptr);return 0;}
}
