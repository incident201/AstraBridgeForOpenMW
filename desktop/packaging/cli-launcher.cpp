#ifndef UNICODE
#define UNICODE
#endif
#ifndef _UNICODE
#define _UNICODE
#endif
#include <windows.h>
#include <bcrypt.h>
#include <string>
#include <vector>
#include <algorithm>

static int fail(const wchar_t* message)
{
    std::wstring text=std::wstring(message)+L"\r\n";
    int size=WideCharToMultiByte(CP_UTF8,0,text.data(),static_cast<int>(text.size()),nullptr,0,nullptr,nullptr);
    std::string utf8(size,'\0');WideCharToMultiByte(CP_UTF8,0,text.data(),static_cast<int>(text.size()),utf8.data(),size,nullptr,nullptr);
    DWORD written;WriteFile(GetStdHandle(STD_ERROR_HANDLE),utf8.data(),size,&written,nullptr);return 1;
}
static std::wstring quote(const std::wstring& value)
{
    std::wstring out=L"\"";unsigned slashes=0;
    for(wchar_t c:value){if(c==L'\\'){++slashes;continue;}out.append(slashes*(c==L'\"'?2:1)+(c==L'\"'?1:0),L'\\');slashes=0;out+=c;}
    out.append(slashes*2,L'\\');return out+L"\"";
}
static std::wstring normalized(std::wstring value)
{
    const auto first=value.find_first_not_of(L" \t\"");const auto last=value.find_last_not_of(L" \t\"");
    value=first==std::wstring::npos?L"":value.substr(first,last-first+1);
    DWORD size=ExpandEnvironmentStringsW(value.c_str(),nullptr,0);
    if(size){std::vector<wchar_t> expanded(size);ExpandEnvironmentStringsW(value.c_str(),expanded.data(),size);value=expanded.data();}
    std::replace(value.begin(),value.end(),L'/',L'\\');while(value.size()>3&&value.back()==L'\\')value.pop_back();return value;
}
static bool equivalent(const std::wstring& a,const std::wstring& b)
{
    const auto left=normalized(a),right=normalized(b);return CompareStringOrdinal(left.c_str(),-1,right.c_str(),-1,TRUE)==CSTR_EQUAL;
}
static int userPath(const std::wstring& action,const std::wstring& directory)
{
    if(action!=L"query"&&action!=L"add"&&action!=L"remove")return fail(L"Invalid PATH operation.");
    HKEY key=nullptr;LONG result=RegOpenKeyExW(HKEY_CURRENT_USER,L"Environment",0,KEY_QUERY_VALUE|(action==L"query"?0:KEY_SET_VALUE),&key);
    if(result==ERROR_FILE_NOT_FOUND&&action==L"add")result=RegCreateKeyExW(HKEY_CURRENT_USER,L"Environment",0,nullptr,0,KEY_QUERY_VALUE|KEY_SET_VALUE,nullptr,&key,nullptr);
    if(result!=ERROR_SUCCESS&&result!=ERROR_FILE_NOT_FOUND)return fail(L"Cannot access the user PATH.");
    DWORD type=REG_EXPAND_SZ,size=0;std::wstring path;
    if(key){
        result=RegQueryValueExW(key,L"Path",nullptr,&type,nullptr,&size);
        if(result==ERROR_SUCCESS){
            if(type!=REG_SZ&&type!=REG_EXPAND_SZ){RegCloseKey(key);return fail(L"Unsupported user PATH registry type.");}
            std::vector<wchar_t> data(size/sizeof(wchar_t)+1,0);
            result=RegQueryValueExW(key,L"Path",nullptr,&type,reinterpret_cast<BYTE*>(data.data()),&size);
            if(result!=ERROR_SUCCESS){RegCloseKey(key);return fail(L"Cannot read the user PATH.");}path=data.data();
        }else if(result!=ERROR_FILE_NOT_FOUND){RegCloseKey(key);return fail(L"Cannot read the user PATH.");}
        else type=REG_EXPAND_SZ;
    }
    bool present=false;std::vector<std::wstring> remaining;
    for(size_t start=0;;){const auto end=path.find(L';',start);const auto entry=path.substr(start,end==std::wstring::npos?end:end-start);
        if(!entry.empty()&&equivalent(entry,directory))present=true;else remaining.push_back(entry);
        if(end==std::wstring::npos)break;
        start=end+1;
    }
    bool changed=(action==L"add"&&!present)||(action==L"remove"&&present);
    if(changed){
        std::wstring updated;
        if(action==L"add")updated=directory+(path.empty()?L"":L";"+path);
        else for(size_t i=0;i<remaining.size();++i){if(i)updated+=L';';updated+=remaining[i];}
        if(!key){return fail(L"Cannot write the user PATH.");}
        result=RegSetValueExW(key,L"Path",0,type,reinterpret_cast<const BYTE*>(updated.c_str()),static_cast<DWORD>((updated.size()+1)*sizeof(wchar_t)));
        if(result!=ERROR_SUCCESS){RegCloseKey(key);return fail(L"Cannot write the user PATH.");}
        DWORD_PTR ignored;SendMessageTimeoutW(HWND_BROADCAST,WM_SETTINGCHANGE,0,reinterpret_cast<LPARAM>(L"Environment"),SMTO_ABORTIFHUNG,1000,&ignored);
    }
    if(key)RegCloseKey(key);
    const std::string json=std::string("{\"present\":")+(present?"true":"false")+",\"changed\":"+(changed?"true":"false")+"}\n";
    DWORD written;WriteFile(GetStdHandle(STD_OUTPUT_HANDLE),json.data(),static_cast<DWORD>(json.size()),&written,nullptr);return 0;
}
static bool matchesHash(HANDLE file,const std::wstring& expected)
{
    BCRYPT_ALG_HANDLE algorithm=nullptr;BCRYPT_HASH_HANDLE hash=nullptr;
    if(BCryptOpenAlgorithmProvider(&algorithm,BCRYPT_SHA256_ALGORITHM,nullptr,0)<0)return false;
    bool ok=BCryptCreateHash(algorithm,&hash,nullptr,0,nullptr,0,0)>=0;
    BYTE block[16384],digest[32];DWORD count=0;
    while(ok){if(!ReadFile(file,block,sizeof(block),&count,nullptr)){ok=false;break;}if(!count)break;ok=BCryptHashData(hash,block,count,0)>=0;}
    if(ok)ok=BCryptFinishHash(hash,digest,sizeof(digest),0)>=0;
    if(hash)BCryptDestroyHash(hash);
    BCryptCloseAlgorithmProvider(algorithm,0);
    std::wstring hex;const wchar_t* digits=L"0123456789abcdef";
    if(ok)for(BYTE byte:digest){hex+=digits[byte>>4];hex+=digits[byte&15];}
    return ok&&hex==expected;
}
static int removeLauncher(const std::wstring& executable,const std::wstring& expected)
{
    if(expected.size()!=64)return fail(L"Invalid CLI removal identity.");
    const auto target=executable.substr(0,executable.find_last_of(L"\\/"))+L"\\cli-target.ini";
    for(unsigned attempt=0;attempt<100;++attempt){
        // Lock the exact pending registration against replacement while deleting.
        HANDLE registration=CreateFileW(target.c_str(),GENERIC_READ|DELETE,FILE_SHARE_READ,nullptr,OPEN_EXISTING,0,nullptr);
        if(registration==INVALID_HANDLE_VALUE){if(GetLastError()==ERROR_FILE_NOT_FOUND)return 0;Sleep(100);continue;}
        LARGE_INTEGER size{};DWORD count=0;bool pending=GetFileSizeEx(registration,&size)&&size.QuadPart>0&&size.QuadPart<1024*1024;
        std::vector<wchar_t> text(pending?static_cast<size_t>(size.QuadPart)/sizeof(wchar_t)+1:1,0);
        if(pending)pending=ReadFile(registration,text.data(),static_cast<DWORD>(size.QuadPart),&count,nullptr)&&count==size.QuadPart;
        if(pending){const std::wstring contents=text.data();pending=contents.find(L"\r\nSchema=0\r\n")!=std::wstring::npos&&contents.find(L"\r\nLauncherHash="+expected+L"\r\n")!=std::wstring::npos;}
        if(!pending){CloseHandle(registration);return 0;}
        HANDLE binary=CreateFileW(executable.c_str(),GENERIC_READ|DELETE,FILE_SHARE_READ|FILE_SHARE_DELETE,nullptr,OPEN_EXISTING,0,nullptr);
        bool removed=binary==INVALID_HANDLE_VALUE&&GetLastError()==ERROR_FILE_NOT_FOUND;
        if(binary!=INVALID_HANDLE_VALUE){
            if(!matchesHash(binary,expected)){CloseHandle(binary);CloseHandle(registration);return fail(L"CLI executable changed; it was not removed.");}
            FILE_DISPOSITION_INFO disposition{TRUE};removed=SetFileInformationByHandle(binary,FileDispositionInfo,&disposition,sizeof(disposition))!=FALSE;
            CloseHandle(binary);
        }
        if(removed){FILE_DISPOSITION_INFO disposition{TRUE};bool done=SetFileInformationByHandle(registration,FileDispositionInfo,&disposition,sizeof(disposition))!=FALSE;CloseHandle(registration);return done?0:1;}
        CloseHandle(registration);Sleep(100);
    }
    return fail(L"CLI removal is pending. Retry Remove CLI command in Setup after the command exits.");
}
int wmain(int argc,wchar_t** argv)
{
    if(argc==4&&std::wstring(argv[1])==L"--remove-launcher")return removeLauncher(argv[2],argv[3]);
    if(argc==4&&std::wstring(argv[1])==L"--user-path")return userPath(argv[2],argv[3]);
    std::vector<wchar_t> buffer(32768);
    if(!GetModuleFileNameW(nullptr,buffer.data(),static_cast<DWORD>(buffer.size())))return fail(L"Cannot locate the CLI launcher.");
    const std::wstring self=buffer.data(),target=self.substr(0,self.find_last_of(L"\\/"))+L"\\cli-target.ini";
    if(GetPrivateProfileIntW(L"AstraBridgeCLI",L"Schema",0,target.c_str())!=1)return fail(L"CLI registration is missing. Enable the CLI command in AstraBridge Setup.");
    auto read=[&](const wchar_t* name){DWORD n=GetPrivateProfileStringW(L"AstraBridgeCLI",name,L"",buffer.data(),static_cast<DWORD>(buffer.size()),target.c_str());return n&&n<buffer.size()-1?std::wstring(buffer.data(),n):L"";};
    const auto application=read(L"Executable"),config=read(L"Config");
    if(application.empty()||config.empty()||equivalent(application,self)||GetFileAttributesW(application.c_str())==INVALID_FILE_ATTRIBUTES)
        return fail(L"AstraBridge application is missing. Open the current application and enable the CLI command in Setup.");
    SetEnvironmentVariableW(L"ASTRA_CONFIG",config.c_str());
    std::wstring command=quote(application);for(int i=1;i<argc;++i)command+=L" "+quote(argv[i]);
    STARTUPINFOW startup{};startup.cb=sizeof(startup);startup.dwFlags=STARTF_USESTDHANDLES;
    startup.hStdInput=GetStdHandle(STD_INPUT_HANDLE);startup.hStdOutput=GetStdHandle(STD_OUTPUT_HANDLE);startup.hStdError=GetStdHandle(STD_ERROR_HANDLE);
    PROCESS_INFORMATION process{};
    if(!CreateProcessW(application.c_str(),command.data(),nullptr,nullptr,TRUE,0,nullptr,nullptr,&startup,&process))return fail(L"Cannot launch AstraBridge. Repair the CLI command in Setup.");
    CloseHandle(process.hThread);if(argc==1){CloseHandle(process.hProcess);return 0;}
    WaitForSingleObject(process.hProcess,INFINITE);DWORD code=1;GetExitCodeProcess(process.hProcess,&code);CloseHandle(process.hProcess);return static_cast<int>(code);
}
