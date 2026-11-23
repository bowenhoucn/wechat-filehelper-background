// Derived from helper bdbe97d4 under its noncommercial license; see LICENSE.helper.
// Changes: exact new profile, filehelper-only exports, bounded jobs, no hooks or receive API.
#define WIN32_LEAN_AND_MEAN
#define NOMINMAX
#include <windows.h>
#include <bcrypt.h>
#include <cstdint>
#include <cstring>
#include <cstdio>
#include <algorithm>
#include <functional>
#include <memory>
#include <vector>
#include <sstream>
#include "core_42053.h"
struct SharedMessage { void* object; void* control; };
struct SmallString { char data[16]; uint64_t length; uint64_t capacity; };
struct TestConfig {
    uint32_t size;
    uint32_t pid;
    uint64_t manager;
    wchar_t log_path[MAX_PATH];
    char text[1024];
};
struct TestResult {
    DWORD stage;
    DWORD exception;
    uint64_t vtable_rva;
    uint32_t native_status;
    uint64_t exception_pc;
    uint64_t fault_address;
    uint64_t access_kind;
    uint32_t native_status_high;
};

using SendFunction = void* (__fastcall*)(void*, void*, SharedMessage*, uint8_t);

struct TextConfig { TestConfig base; char target[128]; };
static uintptr_t core_base = 0;
static volatile LONG active_callbacks = 0, live_tasks = 0;
static bool text_reply_pending() { return false; }
static bool valid_target(const char* value) {
    if(!value || !*value) return false;
    for(const char* p=value; *p; ++p) if(!((*p>='a'&&*p<='z')||(*p>='A'&&*p<='Z')||(*p>='0'&&*p<='9')||*p=='_'||*p=='-'||*p=='.'))return false;
    return true;
}
struct NativeExecutionSlot { volatile LONG64 id, started; };
static_assert(sizeof(NativeExecutionSlot) == 16);
extern "C" {
__declspec(dllexport) NativeExecutionSlot WxNativeExecutionSlots[16]{};
// Diagnostic counters contain no account or attachment content.
__declspec(dllexport) volatile LONG64 WxFileDiagnostics[12]{};
__declspec(dllexport) char WxFileReport[65536]{};
}
static volatile LONG64 native_execution_sequence;

static NativeExecutionSlot* begin_native_execution() {
    ULONGLONG ticks = 0;
    if (!QueryUnbiasedInterruptTime(&ticks)) return nullptr;
    for (auto& slot : WxNativeExecutionSlots) {
        if (InterlockedCompareExchange64(&slot.id, -1, 0) != 0) continue;
        InterlockedExchange64(&slot.started, static_cast<LONG64>(ticks / 10000));
        InterlockedExchange64(&slot.id, InterlockedIncrement64(&native_execution_sequence));
        return &slot;
    }
    return nullptr;
}

static void end_native_execution(NativeExecutionSlot* slot) {
    if (slot) InterlockedExchange64(&slot->id, 0);
}

static void invoke_native_task(std::function<void()>* task) {
    InterlockedIncrement64(&WxFileDiagnostics[0]);
    auto* slot = begin_native_execution();
    __try { (*task)(); }
    __finally { end_native_execution(slot); }
}

static std::function<void()> tracked_native_task(std::function<void()> task) {
    return [task = std::move(task)]() mutable { invoke_native_task(&task); };
}

static int record_exception(EXCEPTION_POINTERS* exception, TestResult* result) {
    result->exception = exception->ExceptionRecord->ExceptionCode;
    result->exception_pc = reinterpret_cast<uintptr_t>(exception->ExceptionRecord->ExceptionAddress);
    if (exception->ExceptionRecord->NumberParameters >= 2) {
        result->access_kind = exception->ExceptionRecord->ExceptionInformation[0];
        result->fault_address = exception->ExceptionRecord->ExceptionInformation[1];
    }
    return EXCEPTION_EXECUTE_HANDLER;
}

static bool core_image_identity(HMODULE core, uint32_t* timestamp, uint32_t* image_size) {
    __try {
        const auto bytes = reinterpret_cast<const unsigned char*>(core);
        const auto dos = reinterpret_cast<const IMAGE_DOS_HEADER*>(bytes);
        if (dos->e_magic != IMAGE_DOS_SIGNATURE || dos->e_lfanew < 64 || dos->e_lfanew > 1048576) return false;
        const auto nt = reinterpret_cast<const IMAGE_NT_HEADERS64*>(bytes + dos->e_lfanew);
        if (nt->Signature != IMAGE_NT_SIGNATURE || nt->FileHeader.Machine != IMAGE_FILE_MACHINE_AMD64 ||
                nt->OptionalHeader.Magic != IMAGE_NT_OPTIONAL_HDR64_MAGIC) return false;
        *timestamp = nt->FileHeader.TimeDateStamp;
        *image_size = nt->OptionalHeader.SizeOfImage;
        return true;
    } __except (EXCEPTION_EXECUTE_HANDLER) { return false; }
}

static bool core_fingerprint(HMODULE core) {
    uint32_t timestamp = 0, image_size = 0;
    if (!core_image_identity(core, &timestamp, &image_size)) return false;
    wchar_t path[32768]{};
    if (!GetModuleFileNameW(core, path, static_cast<DWORD>(std::size(path)))) return false;
    HANDLE file = CreateFileW(path, GENERIC_READ, FILE_SHARE_READ | FILE_SHARE_DELETE,
                              nullptr, OPEN_EXISTING, FILE_FLAG_SEQUENTIAL_SCAN, nullptr);
    if (file == INVALID_HANDLE_VALUE) return false;
    LARGE_INTEGER size{};
    bool valid = GetFileSizeEx(file, &size) && core_size_supported(static_cast<uint64_t>(size.QuadPart));
    BCRYPT_ALG_HANDLE algorithm = nullptr;
    BCRYPT_HASH_HANDLE hash = nullptr;
    if (valid && BCryptOpenAlgorithmProvider(&algorithm, BCRYPT_SHA256_ALGORITHM, nullptr, 0) >= 0) {
        // Windows allocates the hash object when pbHashObject is NULL on supported Windows.
        if (BCryptCreateHash(algorithm, &hash, nullptr, 0, nullptr, 0, 0) >= 0) {
            unsigned char buffer[65536], digest[32];
            DWORD count = 0;
            while (valid) {
                valid = ReadFile(file, buffer, sizeof(buffer), &count, nullptr) != FALSE;
                if (!valid || !count) break;
                valid = BCryptHashData(hash, buffer, count, 0) >= 0;
            }
            valid = valid && BCryptFinishHash(hash, digest, sizeof(digest), 0) >= 0 &&
                core_select_build(static_cast<uint64_t>(size.QuadPart), digest, timestamp, image_size);
            BCryptDestroyHash(hash);
        } else valid = false;
        BCryptCloseAlgorithmProvider(algorithm, 0);
    } else valid = false;
    CloseHandle(file);
    return valid;
}

static void release_shared(SharedMessage& message) {
    if (!message.control) return;
    auto control = static_cast<unsigned char*>(message.control);
    if (_InterlockedDecrement(reinterpret_cast<volatile LONG*>(control + 8)) == 0) {
        using VirtualFunction = void(__fastcall*)(void*);
        auto table = *reinterpret_cast<VirtualFunction**>(control);
        table[0](control);
        if (_InterlockedDecrement(reinterpret_cast<volatile LONG*>(control + 12)) == 0) {
            table = *reinterpret_cast<VirtualFunction**>(control);
            table[1](control);
        }
    }
    message = {};
}

static void guarded_release_shared(SharedMessage* message, TestResult* report) {
    __try {
        release_shared(*message);
    } __except (record_exception(GetExceptionInformation(), report)) {
    }
}

static void write_json_string(std::ostream& log, const char* text) {
    log << '"';
    for (const unsigned char* current = reinterpret_cast<const unsigned char*>(text); *current; ++current) {
        if (*current == '"' || *current == '\\') { log << '\\' << *current; }
        else if (*current < 32) { char escaped[7]; sprintf_s(escaped, "\\u%04x", *current); log << escaped; }
        else log << *current;
    }
    log << '"';
}

static void publish_report(const std::string& text) {
    if (text.empty() || text.size() >= sizeof(WxFileReport)) {
        InterlockedExchange64(&WxFileDiagnostics[7], ERROR_INSUFFICIENT_BUFFER);
        return;
    }
    memcpy(WxFileReport, text.c_str(), text.size()+1);
    // Publish once after the complete payload. The host saves the durable receipt.
    InterlockedExchange64(&WxFileDiagnostics[9], static_cast<LONG64>(text.size()));
}

static void write_report(const TestConfig& config, const TestResult& result,
                         const char* marker = "WXNATIVE_TEST_2") {
    (void)config;
    std::ostringstream log;
    log << "{\"stage\":" << result.stage << ",\"exception\":" << result.exception
        << ",\"native_status\":" << result.native_status << ",\"exception_rva\":"
        << (result.exception_pc ? result.exception_pc-core_base : 0)
        << ",\"fault_address\":" << result.fault_address << ",\"target\":\"filehelper\",\"text\":";
    write_json_string(log,marker); log << '}'; publish_report(log.str());
}

static bool set_inline(SmallString* string, const char* text) {
    const size_t length = std::strlen(text);
    if (length > 15 || string->capacity != 15 || string->length != 0) return false;
    std::memcpy(string->data, text, length + 1);
    string->length = length;
    return true;
}

static bool set_native_string(SmallString* string, const char* text) {
    const size_t length = std::strlen(text);
    if (length < 16) return set_inline(string, text);
    if (length > 1023 || string->capacity != 15 || string->length != 0) return false;
    using Allocate = void* (__fastcall*)(size_t);
    char* buffer = static_cast<char*>(reinterpret_cast<Allocate>(core_address(core_base, 0x74ab89c))(length + 1));
    if (!buffer) return false;
    std::memcpy(buffer, text, length + 1);
    std::memcpy(string->data, &buffer, sizeof(buffer));
    string->length = string->capacity = length;
    return true;
}

static DWORD dispatch_native_task(const TestConfig& config, std::function<void()>* callable) {
    static_assert(sizeof(std::function<void()>) == 64, "Unexpected function ABI");
    struct Location { const char* function; const char* file; uint32_t line; uint32_t pad; void* caller; };
    static_assert(sizeof(Location) == 32, "Unexpected source location ABI");
    Location location{"wxbot.selftest", "selftest_bridge.cpp", 1, 0, nullptr};
    SharedMessage scheduler{}, future{};
    TestResult error{};
    auto* execution = begin_native_execution();
    __try {
        __try {
            // 0x45d10 reads the process-wide application pointer; 0x47310 copies
            // its owned scheduler. These helpers do not require a task-local TLS.
            using App = void* (__fastcall*)();
            using Scheduler = SharedMessage* (__fastcall*)(void*, SharedMessage*);
            void* app = reinterpret_cast<App>(core_address(core_base, 0x45d10))();
            if (!app) return ERROR_NOT_READY;
            reinterpret_cast<Scheduler>(core_address(core_base, 0x47310))(app, &scheduler);
            if (!scheduler.object || !scheduler.control) return ERROR_NOT_READY;
            using Schedule = SharedMessage* (__fastcall*)(void*, SharedMessage*, Location*, std::function<void()>*, uint32_t);
            reinterpret_cast<Schedule>(core_address(core_base, 0x2fb010))(scheduler.object, &future, &location, callable, 1);
            InterlockedExchange64(&WxFileDiagnostics[1], future.object ? 1 : 0);
            InterlockedExchange64(&WxFileDiagnostics[2], future.control ? *reinterpret_cast<LONG*>(static_cast<unsigned char*>(future.control)+8) : -1);
        } __finally {
            __try {
                guarded_release_shared(&future, &error);
                guarded_release_shared(&scheduler, &error);
            } __finally { end_native_execution(execution); }
        }
    } __except (record_exception(GetExceptionInformation(), &error)) {
    }
    if (error.exception) {
        write_report(config, error, "WXNATIVE_TEST_3");
        return 5;
    }
    return 0;
}

static DWORD schedule_task(const TestConfig& config, std::function<void()>* callable) {
    try {
        auto task = tracked_native_task(std::move(*callable));
        return dispatch_native_task(config, &task);
    } catch (const std::bad_alloc&) {
        return ERROR_NOT_ENOUGH_MEMORY;
    }
}

struct QtStaticUtf16 { int32_t references, length; uint32_t allocation, padding; int64_t offset; wchar_t characters[1024]; };
static bool image_file_argument(const TextConfig& config, QtStaticUtf16* utf16) {
    size_t length = strnlen_s(config.base.text, sizeof(config.base.text));
    if (!length || length >= sizeof(config.base.text)) return false;
    int count = MultiByteToWideChar(CP_UTF8, MB_ERR_INVALID_CHARS, config.base.text,
                                  static_cast<int>(length), utf16->characters, 1023);
    if (count <= 0) return false;
    utf16->characters[count] = 0;
    utf16->references = -1; // Qt's immutable static-array reference marker.
    utf16->length = count;
    utf16->allocation = utf16->padding = 0;
    utf16->offset = offsetof(QtStaticUtf16, characters);
    DWORD attributes = GetFileAttributesW(utf16->characters);
    return attributes != INVALID_FILE_ATTRIBUTES && !(attributes & FILE_ATTRIBUTE_DIRECTORY);
}

static void image_free_string(SmallString* text, TestResult* report) {
    __try {
        if (text->capacity > 15 && text->capacity < 1024 * 1024) {
            void* allocation = *reinterpret_cast<void**>(text->data);
            size_t size = static_cast<size_t>(text->capacity + 1);
            if (size >= 4096) {
                allocation = *(reinterpret_cast<void**>(allocation) - 1);
                size += 39;
            }
            using Free = void (__fastcall*)(void*, size_t);
            reinterpret_cast<Free>(core_address(core_base, 0x74ab8e0))(allocation, size);
        }
    } __except (record_exception(GetExceptionInformation(), report)) {
    }
}

static bool emoticon_account_matches(const SharedMessage& context, const char* account) {
    const auto root = *reinterpret_cast<const uintptr_t*>(core_address(core_base, 0xb912690));
    if (!root || *reinterpret_cast<const uintptr_t*>(root) != core_address(core_base, 0x8d804e8) ||
        !context.object || !context.control ||
        *reinterpret_cast<void* const*>(root + 0x68) != context.object ||
        *static_cast<const uintptr_t*>(context.object) != core_address(core_base, 0x8dfe2f8))
        return false;
    const auto identity = reinterpret_cast<const SmallString*>(
        static_cast<const unsigned char*>(context.object) + 0x48);
    const size_t length = strnlen_s(account, 128);
    if (!length || length >= 128 || identity->length != length ||
        identity->capacity < length || identity->capacity > 1024 * 1024)
        return false;
    const char* bytes = identity->capacity > 15 ?
        *reinterpret_cast<const char* const*>(identity->data) : identity->data;
    return bytes && std::memcmp(bytes, account, length) == 0 &&
        *reinterpret_cast<const uintptr_t*>(core_address(core_base, 0xb912690)) == root &&
        *reinterpret_cast<void* const*>(root + 0x68) == context.object;
}

#pragma once
#include <vector>

// Ordinary-file layout derived from the reviewed upstream implementation.
// All addresses resolve through the exact 4.2.0.53 core map; type 49/subtype 6.
struct FileConfig {
    TextConfig base;
    char account[128];
    uint32_t send;
    uint32_t reserved;
};
static_assert(sizeof(FileConfig) == 1824, "Unexpected file config ABI");
static_assert(offsetof(FileConfig, account) == 1688, "Unexpected file account offset");
static_assert(offsetof(FileConfig, send) == 1816, "Unexpected file mode offset");

struct FileWideString {
    wchar_t data[8]{};
    uint64_t length = 0;
    uint64_t capacity = 7;
};
static_assert(sizeof(FileWideString) == 32, "Unexpected native wide string ABI");

struct FileTaskLease {
    FileConfig config;
    HANDLE source = INVALID_HANDLE_VALUE;
    uint64_t size = 0;
    ULONGLONG deadline = GetTickCount64()+120000;
    char name[1024]{};
    explicit FileTaskLease(const FileConfig& value) : config(value) {
        _InterlockedIncrement(&live_tasks);
    }
    ~FileTaskLease() {
        if (source != INVALID_HANDLE_VALUE) CloseHandle(source);
        _InterlockedDecrement(&live_tasks);
    }
};

static volatile LONG file_send_admission = 0;

static DWORD file_read_source(FileTaskLease& lease) {
    QtStaticUtf16 path{};
    if (!image_file_argument(lease.config.base, &path)) return ERROR_FILE_NOT_FOUND;
    if (!((path.characters[0] >= L'A' && path.characters[0] <= L'Z') ||
          (path.characters[0] >= L'a' && path.characters[0] <= L'z')) ||
        path.characters[1] != L':' ||
        (path.characters[2] != L'\\' && path.characters[2] != L'/') ||
        wcschr(path.characters + 2, L':')) return ERROR_BAD_PATHNAME;
    wchar_t drive[] = {path.characters[0], L':', L'\\', 0};
    if (GetDriveTypeW(drive) == DRIVE_REMOTE) return ERROR_BAD_PATHNAME;
    const char* name = lease.config.base.base.text;
    for (const char* cursor = name; *cursor; ++cursor)
        if (*cursor == '\\' || *cursor == '/') name = cursor + 1;
    if (!*name || !std::strcmp(name, ".") || !std::strcmp(name, ".."))
        return ERROR_INVALID_NAME;
    strcpy_s(lease.name, name);
    // Retain a read handle across the asynchronous callback. Sharing deletion
    // allows the Python snapshot to be cleaned up after a timeout; denying
    // write sharing keeps the bytes stable until the copy completes.
    lease.source = CreateFileW(path.characters, GENERIC_READ, FILE_SHARE_READ | FILE_SHARE_DELETE,
        nullptr, OPEN_EXISTING, FILE_FLAG_SEQUENTIAL_SCAN | FILE_FLAG_OPEN_REPARSE_POINT, nullptr);
    if (lease.source == INVALID_HANDLE_VALUE) return GetLastError();
    BY_HANDLE_FILE_INFORMATION information{};
    LARGE_INTEGER size{};
    if (GetFileType(lease.source) != FILE_TYPE_DISK ||
        !GetFileInformationByHandle(lease.source, &information) ||
        !GetFileSizeEx(lease.source, &size)) return ERROR_INVALID_DATA;
    if (information.dwFileAttributes & (FILE_ATTRIBUTE_DIRECTORY | FILE_ATTRIBUTE_REPARSE_POINT) ||
        size.QuadPart <= 0) return ERROR_INVALID_DATA;
    lease.size = static_cast<uint64_t>(size.QuadPart);
    return ERROR_SUCCESS;
}

static const wchar_t* file_wide_data(const FileWideString& value) {
    if (!value.length || value.length >= 1024 || value.capacity < value.length ||
        value.capacity > 1024 * 1024) return nullptr;
    const wchar_t* data = value.capacity > 7 ?
        *reinterpret_cast<const wchar_t* const*>(value.data) : value.data;
    return data && !data[value.length] ? data : nullptr;
}

static void file_release_wide(FileWideString* value, TestResult* report) {
    __try {
        using Destroy = void (__fastcall*)(void*);
        reinterpret_cast<Destroy>(core_address(core_base, 0x7a60))(value);
    } __except (record_exception(GetExceptionInformation(), report)) {}
}

static void file_write_report(const FileTaskLease& lease, const TestResult& report,
                              DWORD status, bool sent, const char* prepared, bool video) {
    std::ostringstream log;
    const auto& config = lease.config;
    InterlockedExchange64(&WxFileDiagnostics[4], report.stage);
    InterlockedExchange64(&WxFileDiagnostics[5], status);
    InterlockedExchange64(&WxFileDiagnostics[6], report.exception);
    const bool success = !status && !report.exception &&
        !report.native_status && !report.native_status_high;
    log << "{\"operation\":\"" << (video ? (config.send ? "video_send" : "video_probe") :
             (config.send ? "file_send" : "file_probe")) << "\",\"message_type\":" << (video?43:49)
        << ",\"app_type\":" << (video?0:6) << ",\"sent\":" << (sent?"true":"false")
        << ",\"stage\":" << report.stage << ",\"exception\":" << report.exception
        << ",\"status\":" << status << ",\"native_status\":" << report.native_status
        << ",\"native_status_high\":" << report.native_status_high << ",\"bytes\":" << lease.size
        << ",\"completion_success\":" << (success?"true":"false") << ",\"target\":";
    write_json_string(log, config.base.target);
    log << ",\"text\":";
    write_json_string(log, config.base.base.text);
    log << ",\"file_path\":";
    write_json_string(log, config.base.base.text);
    log << ",\"file_name\":";
    write_json_string(log, lease.name);
    log << ",\"prepared_path\":";
    write_json_string(log, prepared);
    log << ",\"exception_rva\":" << (report.exception_pc?report.exception_pc-core_base:0)
        << ",\"fault_address\":" << report.fault_address << '}';
    publish_report(log.str());
    InterlockedExchange64(&WxFileDiagnostics[8], 1);
}

static void file_send_on_task(const FileTaskLease& lease, bool video) {
    InterlockedIncrement64(&WxFileDiagnostics[3]);
    const FileConfig& config = lease.config;
    SharedMessage context{}, provider{}, manager{}, message{};
    FileWideString directory{}, prepared{};
    SmallString token{};
    token.capacity = 15;
    alignas(16) unsigned char result[128]{};
    char prepared_utf8[3072]{};
    wchar_t prepared_copy[1024]{};
    HANDLE staged_handle = INVALID_HANDLE_VALUE;
    bool staged_created = false, handed_to_manager = false, sent = false;
    TestResult report{};
    report.native_status = 0xffffffffu;
    DWORD status = ERROR_GEN_FAILURE;
    _InterlockedIncrement(&active_callbacks);
    __try {
        __try {
            report.stage = 70;
            if(GetTickCount64() >= lease.deadline) { status=ERROR_TIMEOUT; __leave; }
            using GetContext = SharedMessage* (__fastcall*)(SharedMessage*);
            using GetService = SharedMessage* (__fastcall*)(void*, SharedMessage*);
            reinterpret_cast<GetContext>(core_address(core_base, 0x47220))(&context);
            if (!emoticon_account_matches(context, config.account)) {
                status = ERROR_NOT_READY; __leave;
            }
            // Allocate a fresh path in this account's Weixin InputTemp directory.
            // This is the same owned staging-path allocator as the image factory.
            using GetDirectory = FileWideString* (__fastcall*)(FileWideString*);
            using EnsureDirectory = uint32_t (__fastcall*)(const FileWideString*);
            using MakeToken = SmallString* (__fastcall*)(SmallString*);
            using Join = FileWideString* (__fastcall*)(const FileWideString*, FileWideString*, const void*);
            reinterpret_cast<GetDirectory>(core_address(core_base, 0x22d8390))(&directory);
            if (!file_wide_data(directory) ||
                !reinterpret_cast<EnsureDirectory>(core_address(core_base, 0x389830))(&directory)) {
                status = ERROR_PATH_NOT_FOUND; __leave;
            }
            reinterpret_cast<MakeToken>(core_address(core_base, 0x57fe90))(&token);
            if (!token.length || token.length >= 128 || token.capacity < token.length) {
                status = ERROR_INVALID_DATA; __leave;
            }
            const char* token_data = token.capacity > 15 ?
                *reinterpret_cast<const char* const*>(token.data) : token.data;
            struct StringView { const char* data; uint64_t length; } token_view{token_data, token.length};
            reinterpret_cast<Join>(core_address(core_base, 0x9f4b0))(&directory, &prepared, &token_view);
            if (video) {
                // Weixin inspects the staged path extension to choose video
                // upload; an extensionless staging path becomes a file card.
                const wchar_t* without_suffix = file_wide_data(prepared);
                wchar_t with_suffix[1024]{};
                if (!without_suffix || prepared.length + 4 >= std::size(with_suffix) ||
                    wcscpy_s(with_suffix, without_suffix) ||
                    wcscat_s(with_suffix, L".mp4")) {
                    status = ERROR_BAD_PATHNAME; __leave;
                }
                FileWideString view{};
                *reinterpret_cast<const wchar_t**>(view.data) = with_suffix;
                view.length = wcslen(with_suffix);
                view.capacity = std::size(with_suffix) - 1;
                using CopyWidePath = void* (__fastcall*)(void*, const FileWideString*);
                reinterpret_cast<CopyWidePath>(core_address(core_base, 0x9b5d0))(&prepared, &view);
            }
            const wchar_t* path = file_wide_data(prepared);
            const wchar_t* root = file_wide_data(directory);
            if (!path || !root || prepared.length <= directory.length ||
                wcsncmp(path, root, static_cast<size_t>(directory.length)) ||
                (path[directory.length] != L'\\' && path[directory.length] != L'/')) {
                status = ERROR_INVALID_DATA; __leave;
            }
            wcscpy_s(prepared_copy, path);
            if (!WideCharToMultiByte(CP_UTF8, WC_ERR_INVALID_CHARS, path, -1,
                prepared_utf8, sizeof(prepared_utf8), nullptr, nullptr)) {
                status = ERROR_INVALID_DATA; __leave;
            }
            report.stage = 71;
            using Factory = SharedMessage* (__fastcall*)(SharedMessage*);
            // The video factory and vtable are verified only for 4.2.0.12.
            const uintptr_t factory = video ? core_video_address(core_base, 0x3078f60) : core_address(core_base, 0x2bab360);
            const uintptr_t vtable = video ? core_video_address(core_base, 0x93bd678) : core_address(core_base, 0x8e53718);
            if (!factory || !vtable) { status = ERROR_NOT_SUPPORTED; __leave; }
            reinterpret_cast<Factory>(factory)(&message);
            if (!message.object || !message.control ||
                *static_cast<const uintptr_t*>(message.object) != vtable) {
                status = ERROR_INVALID_DATA; __leave;
            }
            auto object = static_cast<unsigned char*>(message.object);
            *reinterpret_cast<uint64_t*>(object + 0x118) = video ? 43ull : 0x600000031ull;
            if (video) *reinterpret_cast<uint32_t*>(object + 0x76c) = config.reserved;
            using CopyWide = void* (__fastcall*)(void*, const FileWideString*);
            reinterpret_cast<CopyWide>(core_address(core_base, 0x9b5d0))(object + 0x120, &prepared);
            *reinterpret_cast<uint64_t*>(object + 0x1c8) = lease.size;
            if (!set_native_string(reinterpret_cast<SmallString*>(object + 0x1a8), lease.name) ||
                !set_native_string(reinterpret_cast<SmallString*>(object + 0xb0), config.base.target)) {
                status = ERROR_NOT_ENOUGH_MEMORY; __leave;
            }
            report.stage = 72;
            staged_handle = CreateFileW(prepared_copy, GENERIC_WRITE, FILE_SHARE_READ, nullptr,
                CREATE_NEW, FILE_ATTRIBUTE_NORMAL, nullptr);
            if (staged_handle == INVALID_HANDLE_VALUE) { status = GetLastError(); __leave; }
            staged_created = true;
            unsigned char chunk[65536]{};
            uint64_t copied = 0;
            while (copied < lease.size) {
                const DWORD requested = static_cast<DWORD>(std::min<uint64_t>(sizeof(chunk), lease.size - copied));
                DWORD read = 0, written = 0;
                if (!ReadFile(lease.source, chunk, requested, &read, nullptr) || read != requested ||
                    !WriteFile(staged_handle, chunk, read, &written, nullptr) || written != read) {
                    status = ERROR_WRITE_FAULT; __leave;
                }
                copied += read;
            }
            CloseHandle(staged_handle);
            staged_handle = INVALID_HANDLE_VALUE;
            if (!emoticon_account_matches(context, config.account)) {
                status = ERROR_NOT_READY; __leave;
            }
            if (!config.send) {
                report.stage = 73;
                report.native_status = 0;
                status = ERROR_SUCCESS; __leave;
            }
            report.stage = 74;
            if(GetTickCount64() >= lease.deadline) { status=ERROR_TIMEOUT; __leave; }
            reinterpret_cast<GetService>(core_address(core_base, 0x36c740))(context.object, &provider);
            if (!provider.object || !provider.control) { status = ERROR_NOT_READY; __leave; }
            reinterpret_cast<GetService>(core_address(core_base, 0x6f4d90))(provider.object, &manager);
            if (!manager.object || !manager.control || !emoticon_account_matches(context, config.account)) {
                status = ERROR_NOT_READY; __leave;
            }
            SharedMessage transferred = message;
            _InterlockedIncrement(reinterpret_cast<volatile LONG*>(
                static_cast<unsigned char*>(message.control) + 8));
            handed_to_manager = true; // The uploader may retain InputTemp after this call returns.
            reinterpret_cast<SendFunction>(core_address(core_base, 0x178f100))(manager.object, result, &transferred, 1);
            transferred = {};
            report.native_status = *reinterpret_cast<const uint32_t*>(result);
            report.native_status_high = *reinterpret_cast<const uint32_t*>(result + 4);
            sent = !report.native_status && !report.native_status_high;
            report.stage = 75;
            status = sent ? ERROR_SUCCESS : ERROR_GEN_FAILURE;
        } __except (record_exception(GetExceptionInformation(), &report)) {
            status = ERROR_GEN_FAILURE;
        }
        if (staged_handle != INVALID_HANDLE_VALUE) CloseHandle(staged_handle);
        if (staged_created && !handed_to_manager) DeleteFileW(prepared_copy);
        guarded_release_shared(reinterpret_cast<SharedMessage*>(result + 40), &report);
        image_free_string(reinterpret_cast<SmallString*>(result + 8), &report);
        guarded_release_shared(&message, &report);
        guarded_release_shared(&manager, &report);
        guarded_release_shared(&provider, &report);
        guarded_release_shared(&context, &report);
        image_free_string(&token, &report);
        file_release_wide(&prepared, &report);
        file_release_wide(&directory, &report);
        file_write_report(lease, report, status, sent, prepared_utf8, video);
    } __finally { _InterlockedDecrement(&active_callbacks); }
}

static DWORD file_copy_config(void* parameter, FileConfig* config) {
    if (!parameter) return ERROR_INVALID_PARAMETER;
    __try { *config = *static_cast<const FileConfig*>(parameter); }
    __except (EXCEPTION_EXECUTE_HANDLER) { return ERROR_INVALID_PARAMETER; }
    return ERROR_SUCCESS;
}

static DWORD file_send_dispatch(void* parameter, bool send, bool video) {
    if (live_tasks || text_reply_pending()) return ERROR_BUSY;
    FileConfig config{};
    DWORD status = file_copy_config(parameter, &config);
    if (status) return status;
    const size_t path_length = strnlen_s(config.base.base.text, sizeof(config.base.base.text));
    const size_t target_length = strnlen_s(config.base.target, sizeof(config.base.target));
    const size_t account_length = strnlen_s(config.account, sizeof(config.account));
    const size_t log_length = wcsnlen_s(config.base.base.log_path, std::size(config.base.base.log_path));
    if (config.base.base.size != sizeof(config) || config.base.base.pid != GetCurrentProcessId() ||
        std::strcmp(config.base.target, "filehelper") != 0 || config.send != (send ? 1u : 0u) || (video ? !config.reserved : config.reserved != 0) || !path_length ||
        path_length >= sizeof(config.base.base.text) || !target_length ||
        target_length >= sizeof(config.base.target) || !account_length ||
        account_length >= sizeof(config.account) || !log_length ||
        log_length >= std::size(config.base.base.log_path) || !valid_target(config.base.target) ||
        !valid_target(config.account) || !std::strncmp(config.account, "gh_", 3) ||
        std::strchr(config.account, '@') || !std::strcmp(config.account, "filehelper"))
        return ERROR_INVALID_PARAMETER;
    HMODULE core = GetModuleHandleW(L"Weixin.dll");
    if (!core || !core_fingerprint(core) || (video && core_profile_id != 4)) return ERROR_NOT_SUPPORTED;
    core_base = reinterpret_cast<uintptr_t>(core);
    try {
        auto lease = std::make_shared<FileTaskLease>(config);
        // The queued callback owns the open snapshot handle even after timeout.
        status = file_read_source(*lease);
        if (status) return status;
        std::function<void()> task = [lease, video]() { file_send_on_task(*lease, video); };
        return schedule_task(config.base.base, &task);
    } catch (const std::bad_alloc&) { return ERROR_NOT_ENOUGH_MEMORY; }
    catch (...) { return ERROR_GEN_FAILURE; }
}

static DWORD file_send_export(void* parameter, bool send, bool video = false) {
    _InterlockedIncrement(&active_callbacks);
    bool admitted = false;
    __try {
        if (_InterlockedCompareExchange(&file_send_admission, 1, 0) != 0) return ERROR_BUSY;
        admitted = true;
        return file_send_dispatch(parameter, send, video);
    } __finally {
        if (admitted) _InterlockedExchange(&file_send_admission, 0);
        _InterlockedDecrement(&active_callbacks);
    }
}

extern "C" __declspec(dllexport) DWORD WINAPI WxInspectFilePath(void* parameter) {
    return file_send_export(parameter, false);
}
extern "C" __declspec(dllexport) DWORD WINAPI WxSendFile(void* parameter) {
    return file_send_export(parameter, true);
}

extern "C" __declspec(dllexport) DWORD WINAPI WxRemoveSelfTest(void*) {
    for(int i=0;i<100;++i) {
        bool busy=InterlockedCompareExchange(&active_callbacks,0,0)||InterlockedCompareExchange(&live_tasks,0,0);
        for(auto& slot:WxNativeExecutionSlots) busy=busy||InterlockedCompareExchange64(&slot.id,0,0);
        if(!busy) { Sleep(50); if(!active_callbacks&&!live_tasks) return ERROR_SUCCESS; }
        Sleep(50);
    }
    return ERROR_BUSY;
}
BOOL WINAPI DllMain(HINSTANCE, DWORD, LPVOID) { return TRUE; }
