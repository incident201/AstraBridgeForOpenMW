#ifndef OPENMW_ASTRA_FRAME_HPP
#define OPENMW_ASTRA_FRAME_HPP

// Completed back-buffer frames only. No desktop capture and no GL work on the
// controller thread. The private file is created/owned by the launcher.
#ifdef __linux__
#include <atomic>
#include <chrono>
#include <cstdint>
#include <cstdlib>
#include <cstring>
#include <fcntl.h>
#include <sys/mman.h>
#include <sys/stat.h>
#include <unistd.h>
#include <SDL_video.h>
#include <osg/GL>

namespace AstraFrame
{
    class Stream
    {
        char* mData = nullptr;
        std::size_t mSize = 0;
        std::uint32_t mCapacity = 0, mSlots = 0;
        std::uint64_t mSequence = 0;
        template <class T> T* at(std::size_t offset) { return reinterpret_cast<T*>(mData + offset); }
    public:
        Stream()
        {
            const char* path = std::getenv("ASTRA_FRAME_STREAM");
            if (!path) return;
            int fd = open(path, O_RDWR | O_CLOEXEC | O_NOFOLLOW);
            if (fd < 0) return;
            struct stat st{};
            if (fstat(fd, &st) || !S_ISREG(st.st_mode) || st.st_size < 64) { close(fd); return; }
            mSize = st.st_size;
            void* ptr = mmap(nullptr, mSize, PROT_READ | PROT_WRITE, MAP_SHARED, fd, 0);
            close(fd);
            if (ptr == MAP_FAILED) return;
            mData = static_cast<char*>(ptr);
            mCapacity = *at<std::uint32_t>(8); mSlots = *at<std::uint32_t>(12);
            if (std::memcmp(mData, "ASTRAFR1", 8) || mSlots < 2 || mSlots > 32
                || mCapacity > 3840*2160*4 || mCapacity == 0
                || mSize != 64 + mSlots * (std::size_t(mCapacity) + 64))
            { munmap(mData, mSize); mData = nullptr; }
        }
        ~Stream() { if (mData) munmap(mData, mSize); }
        void capture(SDL_Window* window)
        {
            if (!mData) return;
            __atomic_add_fetch(at<std::uint64_t>(32), 1, __ATOMIC_RELEASE);
            if (!__atomic_load_n(at<std::uint32_t>(16), __ATOMIC_ACQUIRE)) return;
            int w, h; SDL_GL_GetDrawableSize(window, &w, &h);
            const std::size_t bytes = std::size_t(w) * h * 4;
            if (w <= 0 || h <= 0 || bytes > mCapacity)
            { __atomic_store_n(at<std::uint32_t>(20), 1, __ATOMIC_RELEASE); return; }
            // The swap callback runs after all scene and HUD cameras. Preserve
            // pack/read state so screenshots and postprocessing keep working.
            using BindFn = void (APIENTRY *)(GLenum, GLuint);
            static auto bindFramebuffer = reinterpret_cast<BindFn>(SDL_GL_GetProcAddress("glBindFramebuffer"));
            static auto bindBuffer = reinterpret_cast<BindFn>(SDL_GL_GetProcAddress("glBindBuffer"));
            GLint framebuffer = 0, buffer = 0, readBuffer = 0, pack = 0, row = 0, skipRows = 0, skipPixels = 0;
            glGetIntegerv(GL_READ_FRAMEBUFFER_BINDING, &framebuffer);
            glGetIntegerv(GL_PIXEL_PACK_BUFFER_BINDING, &buffer);
            if (bindFramebuffer) bindFramebuffer(GL_READ_FRAMEBUFFER, 0);
            if (bindBuffer) bindBuffer(GL_PIXEL_PACK_BUFFER, 0);
            glGetIntegerv(GL_READ_BUFFER, &readBuffer);
            glGetIntegerv(GL_PACK_ALIGNMENT, &pack); glGetIntegerv(GL_PACK_ROW_LENGTH, &row);
            glGetIntegerv(GL_PACK_SKIP_ROWS, &skipRows); glGetIntegerv(GL_PACK_SKIP_PIXELS, &skipPixels);
            glReadBuffer(GL_BACK); glPixelStorei(GL_PACK_ALIGNMENT, 4); glPixelStorei(GL_PACK_ROW_LENGTH, 0);
            glPixelStorei(GL_PACK_SKIP_ROWS, 0); glPixelStorei(GL_PACK_SKIP_PIXELS, 0);
            const auto sequence = ++mSequence;
            const auto offset = 64 + ((sequence-1) % mSlots) * (std::size_t(mCapacity)+64);
            __atomic_store_n(at<std::uint64_t>(offset), sequence*2+1, __ATOMIC_SEQ_CST);
            // Synchronous readback fences completion of rendering into this buffer.
            glReadPixels(0, 0, w, h, GL_BGRA, GL_UNSIGNED_BYTE, mData+offset+64);
            const double timestamp = std::chrono::duration<double>(
                std::chrono::steady_clock::now().time_since_epoch()).count();
            *at<double>(offset+8) = timestamp;
            *at<std::uint32_t>(offset+16) = w; *at<std::uint32_t>(offset+20) = h;
            *at<std::uint32_t>(offset+24) = bytes;
            __atomic_store_n(at<std::uint64_t>(offset), sequence*2, __ATOMIC_RELEASE);
            __atomic_store_n(at<std::uint64_t>(24), sequence, __ATOMIC_RELEASE);
            glReadBuffer(readBuffer); glPixelStorei(GL_PACK_ALIGNMENT, pack); glPixelStorei(GL_PACK_ROW_LENGTH, row);
            glPixelStorei(GL_PACK_SKIP_ROWS, skipRows); glPixelStorei(GL_PACK_SKIP_PIXELS, skipPixels);
            if (bindBuffer) bindBuffer(GL_PIXEL_PACK_BUFFER, buffer);
            if (bindFramebuffer) bindFramebuffer(GL_READ_FRAMEBUFFER, framebuffer);
        }
    };
    inline void capture(SDL_Window* window) { static Stream stream; stream.capture(window); }
}
#else
namespace AstraFrame { inline void capture(SDL_Window*) {} }
#endif
#endif
