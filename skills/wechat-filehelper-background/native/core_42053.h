// Exact 4.2.0.53 core; no fallback addresses.
#pragma once
static volatile LONG core_profile_id = 0;
static bool core_size_supported(uint64_t n) { return n == 204154920ull; }
static bool core_select_build(uint64_t n,const unsigned char* digest,uint32_t timestamp,uint32_t image_size) {
    const unsigned char expected[] = {0xac,0x6b,0x17,0x4d,0x98,0xee,0x1b,0x69,0xe9,0x5c,0x99,0xa7,0xa3,0x9c,0x31,0x97,0xc8,0xc1,0x67,0xb7,0xc6,0xd3,0x2f,0x5b,0x72,0xc7,0xa7,0x65,0x9c,0x10,0x48,0x25};
    if(n!=204154920ull || timestamp!=1794391333u || image_size!=204644352u || !std::equal(digest,digest+32,expected)) return false;
    InterlockedExchange(&core_profile_id,53);return true;
}
static uintptr_t core_address(uintptr_t base,uintptr_t legacy) {
    if(!base || InterlockedCompareExchange(&core_profile_id,0,0)!=53) return 0;
    switch(legacy) {
    case 0x45d10:return base+0x1fc90;
    case 0x47310:return base+0x21290;
    case 0x2fb010:return base+0x2e3340;
    case 0x47220:return base+0x211a0;
    case 0x36c740:return base+0x355620;
    case 0x6f4d90:return base+0x7023d0;
    case 0x178f100:return base+0x1760b80;
    case 0x74ab89c:return base+0x776931c;
    case 0x74ab8e0:return base+0x7769360;
    case 0xb912690:return base+0xbb6b788;
    case 0x8dfe2f8:return base+0x90cccb8;
    case 0x8d804e8:return base+0x901b0e8;
    case 0x9b5d0:return base+0x94090;
    case 0x7a60:return base+0x7800;
    case 0x22d8390:return base+0x231e4a0;
    case 0x389830:return base+0x372f50;
    case 0x57fe90:return base+0x57f0f0;
    case 0x9f4b0:return base+0x98070;
    case 0x2bab360:return base+0x2c2e100;
    case 0x8e53718:return base+0x9126618;
    default:return 0;
    }
}
static uintptr_t core_video_address(uintptr_t,uintptr_t) { return 0; }
