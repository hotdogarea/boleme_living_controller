# 播了么任务栏图标

- 基线：main `dea552ac4202cb9af7bfb488364a65f0bcca23de`；本轮仅修改中控助手。
- 深绿色底、白色“播了么”上下两行字标，替换原播放符号。SVG 保存字形轮廓，不依赖用户电脑的字体。
- PNG 用于程序页头；ICO 内含 16、32、48、64、128、256 像素，供窗口、任务栏和后续 EXE 打包使用。打包同时携带运行时 ICO。
- 创建 QApplication 前设置独立 Windows AppUserModelID，避免源码运行被分组到默认 Python 图标。
- 不改登录资料、采集、语音回复或版本号。现有进程需要正常退出并重新启动后加载新图标；不自动重启用户程序。
- 本轮仅更新源码和图标资源，未生成 EXE。旧的已固定任务栏快捷方式可能缓存旧图标，使用新程序重新固定即可。
- 验证：助手完整 54 项测试、主程序接入相关 22 项测试通过；检查真实 Windows 进程 AppUserModelID、图标六种尺寸和打包资源路径，并人工检查生成图案。未替换或重启用户当前窗口，未实测其已固定快捷方式的缓存显示。

重新渲染 PNG／ICO：`python scripts/render_icon.py`。重新制作轮廓字标：`python scripts/render_icon.py --refresh-wordmark`，后者仅在制图电脑需要 Noto Sans SC 字体，运行软件不需要。
