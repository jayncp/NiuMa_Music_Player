## 下载

### Windows用户：

- 访问 https://www.gyan.dev/ffmpeg/builds/ 下载最新的静态编译版本（ffmpeg-release-essentials.zip）
- 解压后，你需要的是bin文件夹中的ffmpeg.exe、ffprobe.exe和ffplay.exe


### macOS用户：

- 访问 https://evermeet.cx/ffmpeg/ 下载最新的静态编译版本
- 或使用Homebrew：brew install ffmpeg（如果选择此方法则不需要将二进制文件放入项目文件夹）


### Linux用户：

- 根据你的发行版和架构下载对应的静态编译版本
- 例如：apt install ffmpeg（如果选择此方法则不需要将二进制文件放入项目文件夹）

## 载入

- 将下载的二进制文件放入`tools`目录下的`bin`文件夹中
- 在bin文件夹中创建对应操作系统的子文件夹：`windows`、`macos`和`linux`
- 将下载的二进制文件放入对应操作系统的子文件夹中，结构如下
```
niuma-music-player/
└── tool/
    ├── auto_download_bilibili.py
    ├── bin/
    │   ├── windows/
    │   │   ├── ffmpeg.exe
    │   │   ├── ffprobe.exe
    │   │   └── ffplay.exe
    │   ├── macos/
    │   │   ├── ffmpeg
    │   │   ├── ffprobe
    │   │   └── ffplay
    │   └── linux/
    │       ├── ffmpeg
    │       ├── ffprobe
    │       └── ffplay
    └── other files...
```
