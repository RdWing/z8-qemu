/* SPDX-License-Identifier: GPL-2.0-or-later */
/* Copyright (C) 2026 RdWing */
/* Read-only CLI for the same bounded functional inverse used by the model. */
#include "nikon_he_picture_header.h"
#include "nikon-he-runtime.h"
#include <cstdio>
#include <fstream>
#include <vector>
int main(int argc,char **argv) {
    if(argc!=3)return 2;
    std::ifstream f(argv[1],std::ios::binary|std::ios::ate);
    if(!f)return 3;
    auto n=f.tellg();if(n<256||n>32*1024*1024)return 4;
    std::vector<uint8_t> bytes(static_cast<size_t>(n));f.seekg(0);
    if(!f.read(reinterpret_cast<char *>(bytes.data()),bytes.size()))return 3;
    nikon_he::PictureHeader ph{};
    if(!nikon_he::parse_picture_header(bytes.data(),bytes.size(),ph)||
       !ph.hdr_width||!ph.hdr_height||uint64_t(ph.hdr_width)*ph.hdr_height>50000000)return 5;
    std::vector<uint16_t> raw(size_t(ph.hdr_width)*ph.hdr_height);
    if(!wl_he_decode14(bytes.data(),bytes.size(),ph.hdr_width,ph.hdr_height,raw.data(),raw.size()))return 6;
    FILE *out=std::fopen(argv[2],"wbx");if(!out)return 7;
    bool ok=std::fwrite(raw.data(),2,raw.size(),out)==raw.size();
    if(std::fclose(out)||!ok)return 8;
    std::printf("{\"width\":%u,\"height\":%u,\"samples\":%zu}\n",ph.hdr_width,ph.hdr_height,raw.size());
    return 0;
}
