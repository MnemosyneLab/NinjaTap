# NinjaTap

在一台已有 KernelSU 的 HONOR DNY-NX9 上试验本机控制。电脑上的 Agent 可以通过 CLI 或 MCP 操作手机。手机上的 App 开启后台的截图和触控服务。

当前只针对这一台机器。

## 文档

- [Agent 操作指南](host/ninjatap/guide.md) · CLI 和 MCP 的常见操作、推荐默认值和错误恢复
- [架构设计](docs/design/NinjaTap.md)
- [DNY-NX9 实测](docs/devices/DNY-NX9.md)：屏幕、触摸轴，以及真实点击、拖动、缩放时应用读到的压力和接触面积
- [操作这台手机](docs/operating.md)：通过 MCP 操作时已经踩过的坑

## 手机

`android/` 是控制 App，包名 `com.ninjatap.player`。在 KernelSU 里允许它的 root。打开后设置端口、令牌和绑定地址，点开启。通知栏会留下监听地址。点停止就结束服务。重启后需要再点一次开启。

App 拉起的是 `phone/` 里的播放程序。它提供 `GET /screencap` 和 `POST /inject`，把像素乘 8 后写入 `/dev/input/event6`。

`touchtest/` 是测量页，用来记录 `MotionEvent`。它不需要 root。

### 远程锁屏与解锁

在手机 App 的「设置」→「远程锁屏与解锁」里保存当前 6 位锁屏 PIN，再到「控制」页开启服务。电脑上的 CLI 和 MCP 都可以用 `lock` 和 `unlock`。两条命令通过 Wi-Fi 上的配对 HTTPS 连接和手机端 KernelSU 执行，解锁适配 HONOR DNY-NX9 的系统锁屏。

PIN 由 Android Keystore 加密，电脑只发锁屏或解锁指令。手机点亮后向系统 PIN 界面发送数字键，确认已解锁才返回成功。一次输入未能确认成功时，先手动解锁，在手机上核对 PIN 设置后重启 NinjaTap 服务。手机重启后，先手动解锁并开启 NinjaTap 服务。

## 电脑

`host/` 提供 CLI 和 stdio MCP 服务。两者都使用手机 App 界面上显示的 HTTPS 地址、令牌和 SHA-256 证书指纹。

```bash
cd host
python3 -m venv .venv
.venv/bin/pip install -e .
```

### 首次配对

用新版 App 启动服务。手机会生成证书并保存在 App 私有目录，重启服务后继续使用同一张。在底栏「配对」页可以分别复制地址和指纹，也可以一键复制完整配置。把这三个值写入项目根目录的 `.env`：

```dotenv
NINJATAP_URL=https://192.0.2.10:8787
NINJATAP_TLS_FINGERPRINT=<手机屏幕上显示的 64 位十六进制指纹>
NINJATAP_SECRET=<手机 App 的访问令牌>
```

CLI 和 MCP 在发送令牌前确认本次 TLS 连接的证书指纹。手机更换 Wi-Fi 地址时只需更新 URL。App 数据被清除或证书被更换后，请在手机屏幕上核对新指纹再更新配置。

### CLI

CLI 和 MCP 默认从项目根目录的 `.env` 读取配对配置，从其他目录调用也能读取。命令环境可以分别覆盖这些值。`.env` 已被 Git 忽略。安装后可以直接调用 `.venv/bin/ninjatap`。如果把 `.venv/bin` 加入 `PATH`，可以使用下面的命令：

```bash
ninjatap guide
ninjatap --help
ninjatap screenshot ./screen.png
ninjatap screenshot --ocr ./screen.png
ninjatap back
ninjatap home
ninjatap lock
ninjatap unlock
ninjatap tap 410 980
ninjatap tap_exact 410 980
ninjatap taps 410 980 520 980
ninjatap long_press 410 980 700
ninjatap hold_drag 410 980 820 1120
ninjatap drag 410 980 820 1120
ninjatap slow_drag 410 980 820 1120
ninjatap flick 410 980 820 1120
ninjatap pinch 630 1300 300 600
ninjatap read_clipboard
ninjatap write_clipboard '要粘贴的文字'
printf '%s' '也可以从标准输入读取' | ninjatap write_clipboard --stdin
```

`screenshot` 默认只把全帧 PNG 写到指定路径，并在标准输出打印保存位置。加上 `--ocr` 才会识别文字并打印中心坐标。OCR 失败时仍会保存 PNG，并打印识别失败提示。旧参数 `--no-ocr` 仍可用，但不能与 `--ocr` 同时使用。坐标以当前截图左上角为原点，竖屏为 1264×2736，横屏为 2736×1264。改变方向后重新截图再点按。命令成功时退出码为 0，运行错误写到标准错误并返回 1，参数或连接配置缺失时返回 2。`read_clipboard` 原样输出纯文本，空剪贴板的输出为空。

`long_press` 和 `hold_drag` 的按住时长最多 10000 毫秒。双指缩放的完整轨迹要能放进屏幕。截图、触控和剪贴板可以并行，每类同时最多执行一个请求。同类请求重叠时返回 `device busy`。

### 文件互传

手机播放程序直接读写共享存储。使用 `/sdcard/…`、`/storage/emulated/0/…` 或相对于共享存储的文件路径。传输走同一条 Wi‑Fi HTTPS 连接。两端的目标父目录须已存在，目标文件已存在时会报错。

上传完成后会通知 Android 更新媒体索引。要让相册能发现图片，上传到 `/sdcard/Pictures/` 或 `/sdcard/DCIM/`。目标 App 的照片访问权限仍由 Android 管理。

```bash
ninjatap pull '/sdcard/Pictures/保存的图片.jpg' ./saved.jpg
ninjatap push ./photo.jpg '/sdcard/Download/photo.jpg'
```

### MCP

在 Cursor 里登记这个服务。如果已有旧配置里的 `env`，把三个值都更新为配对后的配置，或移除整个 `env` 让服务读取项目的 `.env`。

```json
{
  "mcpServers": {
    "ninjatap": {
      "command": "/path/to/NinjaTap/host/.venv/bin/python",
      "args": ["-m", "ninjatap"],
      "cwd": "/path/to/NinjaTap/host"
    }
  }
}
```

MCP 提供同名的触控、导航、剪贴板和文件工具。`screenshot` 默认只返回全帧 PNG，也可以把这一帧写到绝对路径。传入 `ocr: true` 才会同时识别文字并返回其中心点。OCR 失败时仍返回 PNG 和错误提示。旧参数 `no_ocr: true`（关闭）和 `no_ocr: false`（开启）仍可用，但不能与 `ocr` 同时传入。整段文字用剪贴板再粘贴。选中一段可见文字用 `hold_drag`。连续几点用 `taps`，见 [操作这台手机](docs/operating.md)。

Agent 可以离线运行 `ninjatap guide`，或通过 MCP 读取资源 `ninjatap://guide`。

## 改了 MCP 之后

Cursor 在进程连上时记下工具列表，之后一直用那份。改了 `host/` 里的工具、说明或识别程序，正在跑的进程不会自己换成新的。

配置在用户目录的 `~/.cursor/mcp.json`，不进仓库。上面的 `command` 必须是 `host/.venv` 里的 Python。Cursor 经常不用 `cwd` 找包，所以这个 venv 里要先做过 `pip install -e .`。没有的话，进程报 `No module named ninjatap` 然后退出。

只杀掉进程，Cursor 不一定会再启动。改 `ninjatap` 这一段配置，它会停掉旧进程，再起一个，并重新读取工具。做法：

1. 在 `ninjatap.env` 里临时加一个无用的环境变量。
2. 等 MCP 设置里这个服务显示已连接，工具列表里能看到新工具。
3. 删掉这个变量。删的时候会再连一次，连上的仍是当前源码。

这次对话如果在重连之前就开始了，它手里的工具列表还是旧的。新开一个对话才能调用新工具。
