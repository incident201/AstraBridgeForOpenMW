#ifndef OPENMW_ASTRA_MEDIA_HPP
#define OPENMW_ASTRA_MEDIA_HPP

// Private Linux transport. The engine owns the clock; the controller only
// requests UI/recording intervals. Audio and completed frames share sample IDs.
#include <algorithm>
#include <array>
#include <cmath>
#include <cstdint>
#include <cstdlib>
#include <cstring>
#include <functional>
#include <mutex>
#include <vector>
#ifdef __linux__
#include <fcntl.h>
#include <sys/mman.h>
#include <sys/stat.h>
#include <unistd.h>
#endif

namespace AstraMedia
{
    constexpr unsigned Rate = 48000;
    struct Frame { std::uint64_t number=~std::uint64_t(0), start=0, end=0; unsigned flags=0; };
    class Stream
    {
        char* mData = nullptr;
        std::size_t mSize = 0;
        unsigned mCapacity = 0, mSlots = 0;
        std::uint64_t mSequence = 0, mSamples = 0;
        double mFraction = 0;
        bool mRecording = false;
        unsigned mFrames = 0;
        std::function<void(float*, unsigned)> mMixer;
        std::array<Frame,64> mFrameHistory;
        std::mutex mFrameMutex;
        template<class T> T* at(std::size_t n) { return reinterpret_cast<T*>(mData+n); }
    public:
        bool active = false;
        bool movie = false;
        std::uint64_t frameStart = 0, frameEnd = 0;
        unsigned frameFlags = 0;
        Stream()
        {
#ifdef __linux__
            const char* path = std::getenv("ASTRA_MEDIA_STREAM");
            if (!path) return;
            int fd = open(path, O_RDWR|O_CLOEXEC|O_NOFOLLOW);
            if (fd < 0) return;
            struct stat st{};
            if (fstat(fd,&st) || !S_ISREG(st.st_mode) || st.st_size < 128) { close(fd); return; }
            mSize = st.st_size;
            auto p = mmap(nullptr,mSize,PROT_READ|PROT_WRITE,MAP_SHARED,fd,0);
            close(fd);
            if (p == MAP_FAILED) return;
            mData = static_cast<char*>(p);
            mCapacity = *at<unsigned>(8); mSlots = *at<unsigned>(12);
            if (std::memcmp(mData,"ASTRAMD1",8) || mCapacity != 4096 || mSlots != 128
                || mSize != 128+mSlots*(64+std::size_t(mCapacity)*8))
            { munmap(mData,mSize); mData=nullptr; }
#endif
        }
        ~Stream()
        {
#ifdef __linux__
            if (mData) munmap(mData,mSize);
#endif
        }
        bool enabled() const { return mData != nullptr; }
        void mixer(std::function<void(float*,unsigned)> fn)
        {
            mMixer=std::move(fn);
            if (mData) __atomic_store_n(at<unsigned>(40),mMixer ? 1u : 0u,__ATOMIC_RELEASE);
        }
        void monitor(bool available, bool overflow=false)
        {
            if (!mData) return;
            __atomic_store_n(at<unsigned>(104),unsigned(available),__ATOMIC_RELEASE);
            if (overflow) __atomic_add_fetch(at<std::uint64_t>(80),1,__ATOMIC_RELEASE);
        }
        void begin(float duration, bool running)
        {
            if (!mData) return;
            const bool record=__atomic_load_n(at<unsigned>(56),__ATOMIC_ACQUIRE)!=0;
            if (record != mRecording)
            {
                mRecording=record;
                *at<std::uint64_t>(record ? 64 : 72)=mSamples;
                __atomic_store_n(at<unsigned>(60),unsigned(record),__ATOMIC_RELEASE);
            }
            active=running || __atomic_load_n(at<unsigned>(16),__ATOMIC_ACQUIRE)!=0;
            __atomic_store_n(at<unsigned>(44),unsigned(active),__ATOMIC_RELEASE);
            frameStart=frameEnd=mSamples;
            frameFlags=(active ? 1u : 0u) | (mRecording ? 2u : 0u);
            mFrames=0;
            if (active)
            {
                // Preserve fractional samples across frames and reasoning pauses.
                mFraction+=std::max(0.0,double(duration))*Rate;
                mFrames=static_cast<unsigned>(std::floor(mFraction));
                mFraction-=mFrames;
            }
            __atomic_add_fetch(at<std::uint64_t>(96),1,__ATOMIC_RELEASE);
        }
        Frame frame(unsigned number)
        {
            std::lock_guard<std::mutex> lock(mFrameMutex);
            const auto& value=mFrameHistory[number%mFrameHistory.size()];
            return value.number==number ? value : Frame{};
        }
        void render(unsigned number=0)
        {
            if (!mData) return;
            std::vector<float> pcm(std::min(mFrames,mCapacity)*2);
            for (unsigned left=mFrames;left;)
            {
                const unsigned count=std::min(left,mCapacity);
                if (mMixer) mMixer(pcm.data(),count);
                else std::fill(pcm.begin(),pcm.end(),0.f);
                // Live viewers need PCM independently of a benchmark interval.
                // Recording start/end acknowledgements and frame flags retain
                // their exact meaning when a viewer subscribes or leaves.
                if (mRecording || __atomic_load_n(at<unsigned>(108),__ATOMIC_ACQUIRE)!=0)
                {
                    const auto seq=++mSequence;
                    const auto offset=128+((seq-1)%mSlots)*(64+std::size_t(mCapacity)*8);
                    __atomic_store_n(at<std::uint64_t>(offset),seq*2+1,__ATOMIC_SEQ_CST);
                    *at<std::uint64_t>(offset+8)=mSamples;
                    *at<unsigned>(offset+16)=count;
                    std::memcpy(mData+offset+64,pcm.data(),count*8);
                    __atomic_store_n(at<std::uint64_t>(offset),seq*2,__ATOMIC_RELEASE);
                    __atomic_store_n(at<std::uint64_t>(24),seq,__ATOMIC_RELEASE);
                }
                mSamples+=count; left-=count;
            }
            frameEnd=mSamples;
            __atomic_store_n(at<std::uint64_t>(32),mSamples,__ATOMIC_RELEASE);
            mFrames=0;
            // OSG may draw on another thread after the next simulation update.
            // Bind media time to its actual frame stamp, never a mutable "now".
            std::lock_guard<std::mutex> lock(mFrameMutex);
            mFrameHistory[number%mFrameHistory.size()]={number,frameStart,frameEnd,frameFlags};
        }
    };
    inline Stream& stream() { static Stream value; return value; }
    struct MovieScope
    {
        Stream& media = stream();
        bool previous = media.movie;
        MovieScope() { media.movie = true; }
        ~MovieScope() { media.movie = previous; }
    };
}
#endif
