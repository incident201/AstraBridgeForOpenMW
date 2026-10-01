#define UNICODE
#define _UNICODE
#include <windows.h>
#include <shellapi.h>
#include <string>
#include <vector>

static std::wstring quote(const std::wstring& value)
{
    std::wstring out=L"\"";
    unsigned slashes=0;
    for(wchar_t c:value)
    {
        if(c==L'\\'){++slashes;continue;}
        if(c==L'\"')out.append(slashes*2+1,L'\\');else out.append(slashes,L'\\');
        slashes=0;out+=c;
    }
    out.append(slashes*2,L'\\');out+=L'\"';return out;
}

int wmain(int argc,wchar_t** argv)
{
    std::vector<wchar_t> path(32768);
    if(!GetModuleFileNameW(nullptr,path.data(),static_cast<DWORD>(path.size())))return 1;
    const std::wstring self=path.data();const auto dir=self.substr(0,self.find_last_of(L"\\/"));
    const auto binary=dir+L"\\astrabridge-desktop.exe";
    std::wstring command=quote(binary);
    if(argc>1)
    {
        SetEnvironmentVariableW(L"ELECTRON_RUN_AS_NODE",L"1");
        SetEnvironmentVariableW(L"ASTRA_RESOURCES",(dir+L"\\resources\\astra").c_str());
        SetEnvironmentVariableW(L"ASTRA_EXECUTABLE",self.c_str());
        command+=L" "+quote(dir+L"\\resources\\app.asar\\out\\cli.cjs");
        for(int i=1;i<argc;++i)command+=L" "+quote(argv[i]);
    }
    else SetEnvironmentVariableW(L"ELECTRON_RUN_AS_NODE",nullptr);
    STARTUPINFOW startup{};startup.cb=sizeof(startup);
    startup.dwFlags=STARTF_USESTDHANDLES;
    startup.hStdInput=GetStdHandle(STD_INPUT_HANDLE);
    startup.hStdOutput=GetStdHandle(STD_OUTPUT_HANDLE);
    startup.hStdError=GetStdHandle(STD_ERROR_HANDLE);
    PROCESS_INFORMATION process{};
    if(!CreateProcessW(binary.c_str(),command.data(),nullptr,nullptr,TRUE,0,nullptr,dir.c_str(),&startup,&process))return 1;
    CloseHandle(process.hThread);
    if(argc==1){CloseHandle(process.hProcess);return 0;}
    WaitForSingleObject(process.hProcess,INFINITE);DWORD code=1;GetExitCodeProcess(process.hProcess,&code);
    CloseHandle(process.hProcess);return static_cast<int>(code);
}
