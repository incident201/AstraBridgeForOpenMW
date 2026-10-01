#include "astramedia.hpp"
#include <cassert>

int main()
{
    int fd=open(std::getenv("ASTRA_MEDIA_STREAM"),O_RDWR);
    auto* control=static_cast<char*>(mmap(nullptr,128,PROT_READ|PROT_WRITE,MAP_SHARED,fd,0));
    auto set=[&](unsigned offset,unsigned value) { *reinterpret_cast<unsigned*>(control+offset)=value; };
    auto& stream=AstraMedia::stream();
    assert(stream.enabled());
    unsigned counter=0;
    stream.mixer([&](float* pcm,unsigned count) {
        for(unsigned i=0;i<count;++i) { pcm[i*2]=pcm[i*2+1]=float(counter++); }
    });
    set(56,1);
    // Non-integral sample counts must not accumulate truncation errors.
    for(int i=0;i<100;++i) { stream.begin(1.f/60,true);stream.render(i); }
    assert(counter==80000);
    // A late graphics thread must get the old frame's clock, not the newest.
    assert(stream.frame(98).start==78400 && stream.frame(98).end==79200);
    stream.begin(60,false);stream.render(100);
    assert(stream.frame(98).start==78400 && stream.frame(98).end==79200);
    assert(stream.frame(100).start==80000 && !(stream.frame(100).flags&1));
    assert(stream.frame(1).flags==0); // safely reject an overwritten frame stamp
    for(int i=0;i<100;++i) { stream.begin(60,false);stream.render(); }
    assert(counter==80000);
    set(16,1);
    for(int i=0;i<10;++i) { stream.begin(1.f/60,false);stream.render(); }
    assert(counter==88000);
    set(16,0);set(56,0);
    stream.begin(1.f/60,false);stream.render();
    assert(counter==88000);
    munmap(control,128);close(fd);
}
