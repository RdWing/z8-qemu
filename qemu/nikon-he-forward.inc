/* SPDX-License-Identifier: GPL-2.0-or-later
 * Authored experimental forward counterpart to the separately pinned public
 * LibRaw HE inverse transform. This is a functional compatibility experiment,
 * not execution or verification of original Nikon encoder arithmetic.
 * The private caller supplies a header and Bayer samples locally. Neither is
 * embedded here. No reference precinct or compressed image is reused.
 */
#include <algorithm>
#include <array>
#include <cstdint>
#include <cstdio>
#include <cstdlib>
#include <fstream>
#include <iterator>
#include <stdexcept>
#include <string>
#include <vector>
using V=std::vector<int32_t>;
using Bytes=std::vector<uint8_t>;
using Bands=std::array<V,26>;

static int32_t floor_div(int64_t v,unsigned shift) {
    return v>=0 ? v/(INT64_C(1)<<shift) : -((-v+(INT64_C(1)<<shift)-1)/(INT64_C(1)<<shift));
}
static Bytes load(const char *path) {
    std::ifstream f(path,std::ios::binary);
    if(!f)throw std::runtime_error("input open");
    return Bytes(std::istreambuf_iterator<char>(f),{});
}
static unsigned be16(const uint8_t *p){return unsigned(p[0])*256+p[1];}
static void put(Bytes &b,uint64_t v,unsigned n) {
    for(unsigned i=n;i;i--)b.push_back(v>>((i-1)*8));
}
static void store(Bytes &b,size_t at,uint64_t v,unsigned n) {
    if(at+n>b.size())throw std::runtime_error("header store");
    for(unsigned i=0;i<n;i++)b[at+i]=v>>((n-i-1)*8);
}
static void marker(Bytes &b,unsigned tag,const Bytes &body) {
    put(b,tag,2);put(b,body.size()+2,2);b.insert(b.end(),body.begin(),body.end());
}
static Bytes diagnostic_header(unsigned w,unsigned h) {
    // Inferred file-format fields, not an executable/vendor header blob.
    // Use an authored nominal tone point, independently inverted per sample.
    // Unknown profile flags retain the observed experimental HE syntax; no
    // calibrated camera transfer, original ISP or original encoder is claimed.
    const unsigned A=86016,B=1024,C=16384;
    Bytes out;put(out,0xff10,2);
    const std::string signature="CONTACT_INTOPIX_";
    Bytes cap(signature.begin(),signature.end());put(cap,0xefc0,2);cap.resize(32,0);marker(out,0xff50,cap);
    Bytes pih;put(pih,0,4);put(pih,0,4);put(pih,w,2);put(pih,h,2);put(pih,0,2);put(pih,16,2);
    for(unsigned v:{4u,4u,8u,18u,0x44u,0x10u,0x51u,0x14u})put(pih,v,1);
    for(unsigned v:{0x50u,0x88u,0x70u,0x80u|(B>>8),B&255,0x15u,0x23u,
                    0xd0u|(A>>16),(A>>8)&255,A&255,C>>8,C&255,7u})put(pih,v,1);
    marker(out,0xff12,pih);
    Bytes cdt;for(unsigned c=0;c<4;c++){put(cdt,14,1);put(cdt,0x11,1);put(cdt,c==2?0:0x51,1);}marker(out,0xff13,cdt);
    Bytes weights;for(unsigned i=0;i<25;i++){put(weights,0,1);put(weights,i,1);}marker(out,0xff14,weights);
    marker(out,0xff20,Bytes{0,0});return out;
}
struct Bits {
    Bytes b;uint64_t pending=0;unsigned count=0;
    void write(uint32_t value,unsigned n) {
        if(n>24)throw std::runtime_error("bit write bound");
        pending=(pending<<n)|(value&((UINT64_C(1)<<n)-1));count+=n;
        while(count>=8){count-=8;b.push_back(pending>>count);}
    }
    void end(){if(count)write(0,8-count);}
};
static std::array<unsigned,6> group_counts(unsigned w) {
    unsigned g=(w+7)/8,n=(g+1)/2,l=(n+1)/2;
    return {(l+3)/4,(n-l+3)/4,(g+7)/8,(g+3)/4,(g+1)/2,g};
}

// Whole-sample symmetric, reversible 5/3 predict then update.
static std::pair<V,V> forward53(const V &in) {
    V low((in.size()+1)/2),high(in.size()/2);
    for(size_t i=0;i<high.size();i++)high[i]=in[2*i+1]-floor_div(int64_t(in[2*i])+in[std::min(2*i+2,in.size()-1-(in.size()%2==0))],1);
    for(size_t i=0;i<low.size();i++) {
        int32_t left=high.empty()?0:high[i?i-1:0];
        int32_t right=high.empty()?0:high[std::min(i,high.size()-1)];
        low[i]=in[2*i]+floor_div(int64_t(left)+right+2,2);
    }
    return {std::move(low),std::move(high)};
}

static std::vector<V> horizontal(V line,unsigned levels) {
    std::vector<V> high;
    for(unsigned k=0;k<levels;k++) {
        auto p=forward53(line);line=std::move(p.first);high.push_back(std::move(p.second));
    }
    std::vector<V> result;result.push_back(std::move(line));
    for(auto i=high.rbegin();i!=high.rend();++i)result.push_back(std::move(*i));
    return result;
}

static std::array<V,4> mosaic_transform(const Bytes &raw,unsigned w,unsigned h,
                                       const Bytes &header,size_t pih) {
    const uint8_t *t=header.data()+pih+4+24;
    unsigned B=((t[3]&15)<<8)|t[4], A=((t[7]&3)<<16)|(t[8]<<8)|t[9], C=(t[10]<<8)|t[11];
    if(!A)throw std::runtime_error("tone coefficient");
    std::array<int32_t,65536> transfer{};
    for(unsigned i=0;i<65536;i++) {
        int64_t d=int64_t(i)-C,q;
        if(d<0)q=-d*d;else{int64_t z=(d*A+32768)>>16;q=z*z;}
        transfer[i]=std::clamp(int64_t(B)+floor_div(q+163840,18),INT64_C(0),INT64_C(16383));
    }
    std::array<int32_t,16384> inverse{};
    for(unsigned r=0;r<16384;r++) {
        auto i=std::lower_bound(transfer.begin(),transfer.end(),int(r));
        size_t k=i==transfer.end()?65535:i-transfer.begin();
        if(k && std::abs(transfer[k-1]-int(r))<std::abs(transfer[k]-int(r)))--k;
        inverse[r]=int(k)-32768;
    }
    unsigned cols=w/2,rows=h/2;size_t n=size_t(cols)*rows;
    V gu(n),gd(n),ll(n),hl(n),pred(n),hh(n),lh(n);
    auto sample=[&](unsigned x,unsigned y) {
        size_t o=(size_t(y)*w+x)*2;unsigned v=unsigned(raw[o])|(unsigned(raw[o+1])<<8);
        if(v>16383)throw std::runtime_error("Bayer sample exceeds 14 bits");
        return inverse[v];
    };
    auto at=[&](unsigned x,unsigned y){return size_t(y)*cols+x;};
    for(unsigned y=0;y<rows;y++)for(unsigned x=0;x<cols;x++) {
        gu[at(x,y)]=sample(2*x+1,2*y);gd[at(x,y)]=sample(2*x,2*y+1);
    }
    for(unsigned y=0;y<rows;y++)for(unsigned x=0;x<cols;x++) {
        unsigned l=x?x-1:0,r=std::min(x+1,cols-1),up=y?y-1:0,dn=std::min(y+1,rows-1);size_t i=at(x,y);
        ll[i]=sample(2*x,2*y)-floor_div(int64_t(gd[at(x,up)])+gu[i]+gd[i]+gu[at(l,y)],2);
        hl[i]=sample(2*x+1,2*y+1)-floor_div(int64_t(gd[at(r,y)])+gd[i]+gu[i]+gu[at(x,dn)],2);
    }
    for(unsigned y=0;y<rows;y++)for(unsigned x=0;x<cols;x++) {
        unsigned r=std::min(x+1,cols-1),up=y?y-1:0;size_t i=at(x,y);
        pred[i]=gu[i]+floor_div(int64_t(ll[i])+hl[i]+ll[at(r,y)]+hl[at(x,up)],3);
    }
    for(unsigned y=0;y<rows;y++)for(unsigned x=0;x<cols;x++) {
        unsigned l=x?x-1:0,dn=std::min(y+1,rows-1);size_t i=at(x,y);
        hh[i]=gd[i]+floor_div(int64_t(ll[i])+hl[i]+hl[at(l,y)]+ll[at(x,dn)],3)
            -floor_div(int64_t(pred[at(l,y)])+pred[i]+pred[at(l,dn)]+pred[at(x,dn)],2);
    }
    for(unsigned y=0;y<rows;y++)for(unsigned x=0;x<cols;x++) {
        unsigned r=std::min(x+1,cols-1),up=y?y-1:0;size_t i=at(x,y);
        lh[i]=pred[i]+floor_div(int64_t(hh[i])+hh[at(r,y)]+hh[at(x,up)]+hh[at(r,up)],3);
    }
    return {std::move(lh),std::move(ll),std::move(hh),std::move(hl)};
}

static std::vector<Bands> wavelet_rows(const std::array<V,4> &planes,unsigned w,unsigned h) {
    unsigned cols=w/2,rows=h/2,n=cols,precincts=(rows+1)/2;
    auto ng=group_counts(cols);std::vector<Bands> result(precincts);
    const unsigned offsets[4]={0,6,12,13},b_offsets[4]={19,21,23,24};
    for(unsigned component=0;component<4;component++) {
        V low(n),high(n);
        for(unsigned p=0;p<precincts;p++) {
            unsigned even=p*2,odd=std::min(even+1,rows-1),next=even+2<rows?even+2:even;
            // Missing final odd row is repeated only in the suppressed band.
            if(component==2) {
                result[p][12]=V(planes[2].begin()+size_t(even)*cols,planes[2].begin()+size_t(even)*cols+n);
                result[p][23]=V(planes[2].begin()+size_t(odd)*cols,planes[2].begin()+size_t(odd)*cols+n);
                result[p][12].resize((n+3)/4*4);result[p][23].resize((n+3)/4*4);continue;
            }
            for(unsigned x=0;x<n;x++) {
                auto v=[&](unsigned y){return planes[component][size_t(y)*cols+x];};
                unsigned previous=even?even-1:1;
                int32_t prev_h=rows<2?0:v(previous)-floor_div(int64_t(v(even?even-2:0))+v(even),1);
                int32_t current_h=even+1<rows?v(odd)-floor_div(int64_t(v(even))+v(next),1):prev_h;
                if(!even)prev_h=current_h;
                high[x]=current_h;low[x]=v(even)+floor_div(int64_t(prev_h)+current_h+2,2);
            }
            auto a=horizontal(low,5),b=horizontal(high,1);
            for(unsigned j=0;j<6;j++){a[j].resize(ng[j]*4);result[p][offsets[component]+j]=std::move(a[j]);}
            for(unsigned j=0;j<2;j++){b[j].resize(((cols+7)/8)*4);result[p][b_offsets[component]+j]=std::move(b[j]);}
        }
    }
    return result;
}

static unsigned bit_width(unsigned v){unsigned n=0;while(v){v>>=1;++n;}return n;}
static const unsigned SCALE[15]={87381,74898,69905,67650,66576,66052,65793,65664,65600,65568,65552,65544,65540,65538,65537};

static void encode_band(const V &v,unsigned gtli,const std::vector<uint8_t> &previous,
                        std::vector<uint8_t> &target,Bits &sig,Bits &gcli,Bits &data,Bits &sign) {
    if(v.size()%4)throw std::runtime_error("coefficient group shape");
    std::vector<std::array<uint32_t,4>> codes(v.size()/4);
    target.resize(v.size()/4);
    if(previous.size()!=target.size())throw std::runtime_error("prediction group shape");
    for(size_t i=0;i<v.size();i+=4) {
        uint32_t magnitude[4];unsigned maximum=0;
        for(unsigned k=0;k<4;k++)maximum=std::max(maximum,unsigned(std::abs(v[i+k])));
        unsigned g=std::max(gtli,bit_width((maximum+8)/16));
        if(g>15)throw std::runtime_error("coefficient precision overflow");
        for(unsigned iteration=0;iteration<4;iteration++) {
            unsigned bc=g>gtli?g-gtli:0,max_code=bc?((1u<<bc)-1):0,observed=0;
            uint64_t denominator=bc?(uint64_t(SCALE[bc-1])*16<<gtli):1;
            for(unsigned k=0;k<4;k++) {
                uint64_t target=uint64_t(std::abs(v[i+k]))*65536;
                magnitude[k]=bc?std::min(uint64_t(max_code),(target+denominator/2)/denominator):0;
                observed=std::max(observed,magnitude[k]);
            }
            unsigned actual=observed?bit_width(observed)+gtli:gtli;
            if(actual==g)break;
            g=actual;
        }
        unsigned bc=g-gtli;
        (void)bc;target[i/4]=g;
        for(unsigned k=0;k<4;k++)codes[i/4][k]=magnitude[k];
    }
    for(size_t base=0;base<target.size();base+=8) {
        size_t n=std::min(size_t(8),target.size()-base);bool baseline=true;
        for(size_t i=0;i<n;i++)if(target[base+i]!=std::max(gtli,unsigned(previous[base+i])))baseline=false;
        sig.write(baseline,1);
        if(!baseline)for(size_t i=0;i<n;i++) {
            unsigned g=target[base+i],m=std::max(gtli,unsigned(previous[base+i])),threshold=m-gtli,u;
            if(g==m)u=0;
            else if(g<m)u=2*(m-g)-1;
            else if(g-m<=threshold)u=2*(g-m);
            else u=g-gtli;
            if(u>31)throw std::runtime_error("prediction unary bound");
            for(unsigned j=0;j<u;j++)gcli.write(1,1);
            gcli.write(0,1);
        }
    }
    for(size_t group=0;group<codes.size();group++) {
        unsigned bc=target[group]-gtli;const auto &magnitude=codes[group];
        for(unsigned plane=bc;plane;plane--) {
            unsigned nibble=0;
            for(unsigned k=0;k<4;k++)nibble=(nibble<<1)|((magnitude[k]>>(plane-1))&1);
            data.write(nibble,4);
        }
        for(unsigned k=0;k<4;k++)if(magnitude[k])sign.write(v[group*4+k]<0,1);
    }
}

using History=std::array<std::vector<uint8_t>,26>;
static Bytes encode_precinct(const Bands &bands,unsigned w,unsigned bp,
                              const std::array<unsigned,26> &gains,History &history) {
    Bytes result(12,0xff);result[3]=bp;result[4]=0;
    // WGT describes 25 bands; the final six Dpb bits are padding, not
    // three additional coding modes. The inverse uses 26 internal rows.
    result[11]=0xc0;
    const unsigned bounds[9]={0,6,12,13,19,21,23,24,26};
    unsigned sig_bytes=(w/2+255)/256;
    for(unsigned lb=0;lb<8;lb++) {
        Bits sig,gcli,data,sign;
        for(unsigned sb=bounds[lb];sb<bounds[lb+1];sb++) {
            unsigned prev_band=sb==12?23:sb==23?12:sb;
            if(history[prev_band].empty())history[prev_band].resize(bands[sb].size()/4,0);
            std::vector<uint8_t> target;unsigned gtli=bp>gains[sb]?bp-gains[sb]:0;
            encode_band(bands[sb],gtli,history[prev_band],target,sig,gcli,data,sign);
            history[sb]=std::move(target);
        }
        sig.end();gcli.end();data.end();sign.end();
        if(sig.b.size()>sig_bytes)throw std::runtime_error("significance layout exceeds typed width");
        sig.b.resize(sig_bytes,0);
        if(data.b.size()>=1u<<20 || gcli.b.size()>=1u<<20 || sign.b.size()>=1u<<15)throw std::runtime_error("substream length overflow");
        uint64_t mini=(uint64_t(data.b.size())<<35)|(uint64_t(gcli.b.size())<<15)|sign.b.size();
        put(result,mini,7);result.insert(result.end(),sig.b.begin(),sig.b.end());
        result.insert(result.end(),gcli.b.begin(),gcli.b.end());result.insert(result.end(),data.b.begin(),data.b.end());result.insert(result.end(),sign.b.begin(),sign.b.end());
    }
    // Keep at least twelve bytes of packet padding: the separately pinned
    // public decoder bounds the complete packet against Lprc, not Lprc+12.
    result.resize((result.size()+12+15)&~size_t(15),0);
    if(result.size()-12>=1u<<24)throw std::runtime_error("precinct length overflow");
    store(result,0,result.size()-12,3);return result;
}

static Bytes encode_frame(const Bytes &raw,unsigned w,unsigned h,
                          Bytes header,size_t capacity,unsigned *bp_out=nullptr) {
    if(w<64 || h<8 || ((w|h)&1) || w>16384 || h>8192 ||
       uint64_t(w)*h>50000000 || capacity>32*1024*1024 ||
       raw.size()!=uint64_t(w)*h*2 || header.size()>4096 ||
       header.size()<80 || be16(header.data())!=0xff10)
        throw std::runtime_error("geometry/header/capacity bound");
    size_t pih=0,wgt=0;
        for(size_t i=2;i+4<=header.size();) {
            unsigned marker=be16(header.data()+i),length=be16(header.data()+i+2);
            if(length<2 || i+2+length>header.size())throw std::runtime_error("header marker bound");
            if(marker==0xff12){if(length!=39)throw std::runtime_error("private PIH shape");pih=i;}
            if(marker==0xff14){if(length!=52)throw std::runtime_error("WGT shape");wgt=i;}
            i+=length+2;
            if(marker==0xff20){header.resize(i);break;}
        }
        if(!pih || !wgt)throw std::runtime_error("missing typed header");
        store(header,pih+4+8,w,2);store(header,pih+4+10,h,2);
        std::array<unsigned,26> gains{};
        for(unsigned sb=0;sb<26;sb++) {
            unsigned index=sb<23?sb:sb==23?12:sb-1;
            gains[sb]=header[wgt+4+2*index];
        }
        auto planes=mosaic_transform(raw,w,h,header,pih);auto coefficients=wavelet_rows(planes,w,h);
        Bytes output;unsigned selected=0;
        for(unsigned bp=0;bp<=15;bp++) {
            std::vector<Bytes> packets;size_t required=header.size()+2+(coefficients.size()-1)/16*6;
            History history;
            for(size_t p=0;p<coefficients.size();p++) {
                if(p%16==0)for(auto &row:history)row.clear();
                packets.push_back(encode_precinct(coefficients[p],w,bp,gains,history));required+=packets.back().size();
            }
            if(capacity && required>capacity)continue;
            // Spread the fixed-rate filler over the actual precincts. A
            // megabyte-sized final precinct defeats bounded decoder buffers.
            size_t extra=capacity?capacity-required:0;
            output=header;
            for(size_t p=0;p<packets.size();p++) {
                size_t filler=extra/packets.size()+(p<extra%packets.size());
                packets[p].resize(packets[p].size()+filler,0);
                store(packets[p],0,packets[p].size()-12,3);
                output.insert(output.end(),packets[p].begin(),packets[p].end());
                if((p&15)==15 && p+1<packets.size()){put(output,0xff200004,4);put(output,(p+1)/16,2);}
            }
            put(output,0xff11,2);selected=bp;break;
        }
        if(output.empty() || (capacity && output.size()!=capacity))throw std::runtime_error("target rate cannot be met");
        store(output,pih+4,output.size(),4);
        if(bp_out)*bp_out=selected;
        return output;

}
