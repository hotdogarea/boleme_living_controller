# 播了么直播中控助手（独立 MVP）

独立的 Python/PyQt6 工具，参考 [oba-live-tool](https://github.com/qiutongxue/oba-live-tool) 的各平台中控入口、选择器和弹幕采集方式。没有打包 Electron、React、OBA 项目目录，也不修改系统代理。本项目按 MIT 协议开源；上游版权和许可见 [THIRD_PARTY_LICENSE.txt](THIRD_PARTY_LICENSE.txt)。

## 启动

在此仓库根目录创建助手自己的 Python 环境，随后启动源码：

```powershell
.\setup.ps1
.\.venv\Scripts\python.exe -m boleme_live_control
```

运行依赖只安装到本目录的 `.venv`，不使用语音引擎的虚拟环境。首次使用 Playwright 自带 Chromium 时需在本环境执行 `.\.venv\Scripts\python.exe -m playwright install chromium`；本机已有 Edge/Chrome 时优先使用系统浏览器。源码联调完成后，先用 `.\.venv\Scripts\python.exe -m pip install -r .\requirements-build.txt` 安装构建依赖，再运行 `.\build.ps1`。打包输出在 `dist/BolemeLiveControl`；发布时把其中的 EXE 和 `_internal` 一起放到主程序 EXE 旁边的 `BolemeLiveControl` 目录，不要只复制 EXE。

打包诊断：`BolemeLiveControl.exe --smoke-browser` 只打开并关闭无网络的空白页，以退出码 0 表示浏览器驱动可用。运行本项目的独立测试：`.\.venv\Scripts\python.exe -m unittest discover -s tests`。

选择平台和账号后连接，在浏览器里完成登录、开播并进入中控台。选择另一个账号会先关闭当前浏览器，再打开该账号的独立浏览器资料目录；同一时刻只运行一个账号。账号管理可以添加、改名和删除账号。登录未过期时重连会复用浏览器资料；过期时应在浏览器里重新扫码，具体有效期由平台决定。快捷语和商品讲解都由用户明确勾选后才自动运行，按表格顺序执行；可在“直播互动”里选中评论后点击“回复”，或直接公开发言。运行记录始终固定在窗口底部，可拖动分隔线调整高度。

所有浏览器登录资料保存在当前 Windows 用户的 `%LOCALAPPDATA%\Boleme\LiveControl\profiles`，设置和通信令牌保存在同级 `settings.json`。旧版单账号资料继续作为每个平台的“默认账号”，不会复制 Cookie；新增账号资料位于 `profiles\accounts\<platform>\<account_id>`。删除新增账号时会一并删除对应的本机浏览器资料；默认账号不能删除。**打包和分发时不要复制整个 `%LOCALAPPDATA%\Boleme\LiveControl` 目录。**

弹幕表格显示时间、昵称、内容、类型和文字发送状态；**没有用户等级列**，因为 OBA 的抖店评论/罗盘事件没有可靠的通用等级字段。选中弹幕后点击“查看字段”，可查看标准化事件和该条平台原始 JSON，仅保留在助手内存，不写入日志。请勿公开分享可能包含个人信息的原始数据。表格中的手动“发文字”和主程序同步的 AI 文案都发送到平台公共评论框，不会艾特或定向回复；手动发文字的 `msg_id` 仅关联本地状态。

每个平台可保存多个账号的独立登录资料。同一时间只连接一个平台/账号；关闭浏览器后连接状态会恢复为未连接。

## 平台范围

抖音小店、巨量百应、抖音团购、小红书方舟、小红书蒲公英、微信视频号、快手小店、淘宝直播均有独立的中控入口和发送/商品操作配置。抖店/百应尝试连接罗盘以接收评论、进房、点赞等事件；小红书、视频号、快手、淘宝基于各自页面采集评论；OBA 的抖音团购入口没有弹幕监听实现，本工具同样不宣称捕获该平台弹幕。各网站的登录、DOM 和接口可能变化，尚未通过真实商家账号对所有平台逐一验收。网站失败会显示在运行记录里。

## 本机通信协议

WebSocket 只监听 `127.0.0.1:21341`。首次连接发送 `{"token":"<settings.json 中的 bridge_token>","subscribe_barrage":false}`，成功收到 `{"type":"ready","version":1}`。`platform_status` 包含当前平台、账号、浏览器会话和 `ready` 状态。`subscribe_barrage:false` 的客户端只接收状态，不接收助手采集的弹幕；省略该字段的旧客户端仍可订阅事件。公开发文字使用 `{"type":"send_public_text","text":"...","platform":"...","session_id":"..."}`，不带 `msg_id`。助手拒绝跨平台、过期会话或未就绪状态下的发送请求。桥接令牌不要放进日志或安装包。

语音引擎继续使用各平台原有采集器作为唯一回复输入；助手独立运行商品讲解、快捷语和手动发言。主程序的“同步评论回复到中控助手”每次启动都默认关闭，不保存开启状态。用户确认两个程序处于同一直播间后可开启：主程序只把原采集器评论的最终文案经本机桥接发送到公共评论框，不传进房/点赞等事件，也不再次调用模型。两边无法自动核对直播间 ID，切换直播间前应关闭同步；切换平台、账号或浏览器会话时，旧会话文案会被拒绝。源码协议与本机模拟测试已通过；真实商家账号的直播弹幕和跨程序操作仍需联调验收。

## 源码与许可

参考基线：`qiutongxue/oba-live-tool` commit `db22b63ee9bcca3e96b6631b6a0c88061ed0777d`，MIT 条款见 `THIRD_PARTY_LICENSE.txt`。本工具移植了思路和选择器，不包含 OBA 的 UI 或 Electron 运行时。
