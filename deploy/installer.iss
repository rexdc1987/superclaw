; SuperClaw 服务端 — Windows 安装包脚本
;
; 由 deploy/build_installer.py 调用，不直接手工编译：
;     iscc /DMyAppVersion=1.0.3 /DPayloadDir=..\dist\server\SuperClaw installer.iss
;
; 几个刻意的选择：
;   * PrivilegesRequired=lowest —— 不弹 UAC。安装目录归当前用户所有，程序才能
;     在运行时改写 data/，内置自动更新也才能替换 app/。只有放行防火墙那一步
;     需要管理员，交给 allow_firewall.ps1 自己提权。
;   * AppMutex=SuperClaw.Launcher —— 装/卸载前能发现服务还开着，避免覆盖正在
;     使用的文件。
;   * data\instance.json 用 onlyifdoesntexist —— 重复运行安装包（覆盖升级）时
;     不会把用户改过的端口重置掉。

#ifndef MyAppVersion
  #define MyAppVersion "0.0.0"
#endif
#ifndef PayloadDir
  #define PayloadDir "..\dist\server\SuperClaw"
#endif
#ifndef OutputDir
  #define OutputDir "..\dist\release"
#endif

#define MyAppName "SuperClaw"
#define MyAppPublisher "美思科技"
#define MyAppExeName "start_superclaw.bat"

[Setup]
AppId={{A7C41E5B-9D2F-4B83-8E16-5C0D7A3F9E24}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppVerName={#MyAppName} {#MyAppVersion}
AppPublisher={#MyAppPublisher}
VersionInfoVersion={#MyAppVersion}
VersionInfoCompany={#MyAppPublisher}
VersionInfoDescription={#MyAppName} 服务端安装程序

; 装到 C:\ 根下而不是 Program Files：程序运行时需要写 data\ 并替换 app\，
; Program Files 的默认 ACL 会挡住这两件事（除非每次都提权）。
DefaultDirName=C:\SuperClaw
DisableDirPage=no
DefaultGroupName={#MyAppName}
DisableProgramGroupPage=yes
AllowNoIcons=yes

PrivilegesRequired=lowest
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
MinVersion=10.0

AppMutex=SuperClaw.Launcher
CloseApplications=yes
RestartApplications=no

OutputDir={#OutputDir}
OutputBaseFilename=SuperClaw-Setup-{#MyAppVersion}
Compression=lzma2/max
SolidCompression=yes
WizardStyle=modern
UninstallDisplayName={#MyAppName} {#MyAppVersion}
UninstallDisplayIcon={app}\assets\superclaw.ico
SetupIconFile=assets\superclaw.ico
ShowLanguageDialog=no
DisableWelcomePage=no

[Languages]
Name: "chinese"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "创建桌面快捷方式"; GroupDescription: "附加图标："; Flags: checkedonce
Name: "autostart"; Description: "开机自动启动 SuperClaw（随登录启动，最小化运行）"; GroupDescription: "附加图标："
Name: "firewall"; Description: "放行 Windows 防火墙，允许局域网内其他电脑访问（需要管理员授权一次）"; GroupDescription: "网络："; Flags: checkedonce

[Files]
; 主程序树。两项要排除：
;   data\instance.json  —— 用户改过的端口，覆盖升级时必须保留
;   app\config\local.yaml —— 首次启动由 launcher 从 preset 生成，装包不携带
Source: "{#PayloadDir}\*"; DestDir: "{app}"; \
    Excludes: "data\instance.json,app\config\local.yaml"; \
    Flags: ignoreversion recursesubdirs createallsubdirs
Source: "{#PayloadDir}\data\instance.json"; DestDir: "{app}\data"; \
    Flags: onlyifdoesntexist uninsneveruninstall
Source: "assets\superclaw.ico"; DestDir: "{app}\assets"; Flags: ignoreversion
Source: "allow_firewall.ps1"; DestDir: "{app}"; Flags: ignoreversion

[Dirs]
Name: "{app}\data"; Flags: uninsneveruninstall
Name: "{app}\data\logs"
Name: "{app}\data\screenshots"
Name: "{app}\data\updates"

[Icons]
Name: "{autoprograms}\SuperClaw"; Filename: "{app}\{#MyAppExeName}"; \
    IconFilename: "{app}\assets\superclaw.ico"; Comment: "启动 SuperClaw 控制台"
Name: "{autoprograms}\SuperClaw 使用说明"; Filename: "{app}\README.txt"
Name: "{autodesktop}\SuperClaw"; Filename: "{app}\{#MyAppExeName}"; \
    IconFilename: "{app}\assets\superclaw.ico"; Tasks: desktopicon
Name: "{userstartup}\SuperClaw"; Filename: "{app}\{#MyAppExeName}"; \
    IconFilename: "{app}\assets\superclaw.ico"; Tasks: autostart; Flags: runminimized

[Run]
Filename: "powershell.exe"; \
    Parameters: "-NoProfile -ExecutionPolicy Bypass -File ""{app}\allow_firewall.ps1"""; \
    StatusMsg: "正在放行防火墙端口…"; \
    Flags: runhidden waituntilterminated; Tasks: firewall
Filename: "{app}\{#MyAppExeName}"; Description: "立即启动 SuperClaw"; \
    Flags: shellexec nowait postinstall skipifsilent unchecked
Filename: "{app}\README.txt"; Description: "打开使用说明"; \
    Flags: shellexec postinstall skipifsilent unchecked

[UninstallDelete]
; 运行时产生的文件（日志、更新缓存、__pycache__）不在安装清单里，
; 卸载时按目录整体清掉，避免留一堆垃圾。
Type: filesandordirs; Name: "{app}\app"
Type: filesandordirs; Name: "{app}\runtime"
Type: filesandordirs; Name: "{app}\data\logs"
Type: filesandordirs; Name: "{app}\data\updates"
Type: filesandordirs; Name: "{app}\data\screenshots"
Type: files; Name: "{app}\data\instance.json"
Type: dirifempty; Name: "{app}\data"
Type: dirifempty; Name: "{app}"
