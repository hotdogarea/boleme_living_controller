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

弹幕表格显示时间、昵称、内容、类型和文字发送状态；**没有用户等级列**，因为 OBA 的抖店评论/罗盘事件没有可靠的通用等级字段。选中弹幕后点击“查看字段”，可查看标准化事件和该条平台原始 JSON，仅保留在助手内存，不写入日志，也不转发原始 JSON。请勿公开分享可能包含个人信息的原始数据。表格中的“发文字”及主程序同步的 AI 文案目前都发送到平台公共评论框；`msg_id` 只用来关联原问题并更新本地发送状态，尚不构成平台的艾特或定向回复。

每个平台可保存多个账号的独立登录资料。同一时间只连接一个平台/账号；关闭浏览器后连接状态会恢复为未连接。

## 平台范围

抖音小店、巨量百应、抖音团购、小红书方舟、小红书蒲公英、微信视频号、快手小店、淘宝直播均有独立的中控入口和发送/商品操作配置。抖店/百应尝试连接罗盘以接收评论、进房、点赞等事件；小红书、视频号、快手、淘宝基于各自页面采集评论；OBA 的抖音团购入口没有弹幕监听实现，本工具同样不宣称捕获该平台弹幕。各网站的登录、DOM 和接口可能变化，尚未通过真实商家账号对所有平台逐一验收。网站失败会显示在运行记录里。

## 本机通信协议

WebSocket 只监听 `127.0.0.1:21341`。首次连接发送 `{"token":"<settings.json 中的 bridge_token>"}`，成功收到 `{"type":"ready","version":1}`。助手还会发送 `platform_status`，区分本机通信已连接与平台网页已登录。工具采集的事件会推送为 `{"type":"barrage","event":{...}}`。事件遵循语音引擎现有的 `platform`、`type`、`nickname`、`content`、`display_text`、`user_id`、`full_inner_data` 字段，并带 `schema_version=1`、`source_platform`、`account_id`、`session_id` 和 `msg_id`；平台原始 JSON 不经桥接发送。发送文字使用 `{"type":"send_text","text":"...","platform":"...","session_id":"...","msg_id":"..."}`。`msg_id` 用于将发送结果标回原评论。平台或会话不匹配的过期回复会被丢弃。主程序只回传已经通过现有错误检查的评论最终文案，不再调用第二次模型。桥接令牌不要放进日志或安装包。

主程序右侧弹幕系统的“中控助手”页有显式连接和“语音回复同步发文字”开关。未连接时独立工具仍可单独工作；连接后由助手采到的弹幕进入现有知识库/语音流程。主程序完成该条评论的知识库回复后，可用原事件的 `platform`、`session_id`、`msg_id` 将最终文案送回助手；来自旧采集器的弹幕没有这组助手会话标识，不会自动回传。请勿同时开启同平台旧采集器。已用本机测试页面验证抖店评论框发送、商品讲解按钮和 WebSocket 往返；真实商家账号的登录、直播弹幕及各平台 DOM 操作仍需逐一联调验收。

助手在抖音小店或巨量百应平台检测到本机运行的 `WssBarrageServer.exe` 时，会提示先关闭旧抖音弹幕插件；不会结束该进程。旧插件本身及其原有采集协议保持不变，用户仍可选择单独使用它。

## 源码与许可

参考基线：`qiutongxue/oba-live-tool` commit `db22b63ee9bcca3e96b6631b6a0c88061ed0777d`，MIT 条款见 `THIRD_PARTY_LICENSE.txt`。本工具移植了思路和选择器，不包含 OBA 的 UI 或 Electron 运行时。
