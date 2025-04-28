import sys
import os
import random
import re
import time
from PyQt5.QtWidgets import (QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, 
                            QLabel, QPushButton, QComboBox, QLineEdit, 
                            QStatusBar, QMessageBox, QSlider, QStyle,
                            QTableWidget, QTableWidgetItem, QHeaderView, QAbstractItemView)
from PyQt5.QtCore import Qt, QUrl, pyqtSignal, QThread, QTimer
from PyQt5.QtMultimedia import QMediaPlayer, QMediaContent
from PyQt5.QtGui import QFont, QColor, QPalette

# 导入mutagen库用于读取音频文件元数据
try:
    from mutagen import File as MutagenFile
    MUTAGEN_IMPORTED = True
except ImportError:
    MUTAGEN_IMPORTED = False
    print("警告: 未能导入mutagen库，将使用QMediaPlayer的内置时长获取方法")

# 尝试导入搜索和下载模块
try:
    import tools.search_music as search_music
    import tools.auto_download_bilibili as auto_download_bilibili
    TOOLS_IMPORTED = True
except ImportError:
    TOOLS_IMPORTED = False
    print("警告: 未能导入搜索或下载模块，某些功能将不可用")

class DownloadWorker(QThread):
    """下载工作线程，避免UI卡顿"""
    download_complete = pyqtSignal(str)  # 下载完成信号
    download_progress = pyqtSignal(str)  # 下载进度信号
    download_error = pyqtSignal(str)     # 下载错误信号
    
    def __init__(self, song_name, artist_name=""):
        super().__init__()
        self.song_name = song_name
        self.artist_name = artist_name if artist_name else None  # 在搜索时使用None以获取原唱
        
    def rename_file(self, file_path):
        """基于歌曲和歌手信息重命名文件，不使用AI"""
        if not file_path:
            return file_path
            
        import os
        # 获取文件目录和扩展名
        file_dir = os.path.dirname(file_path)
        file_ext = os.path.splitext(file_path)[1]
        
        # 构建新文件名
        if self.artist_name:
            # 使用歌曲--歌手格式
            new_filename = f"{self.song_name}--{self.artist_name}{file_ext}"
        else:
            # 只有歌曲名，无歌手信息
            new_filename = f"{self.song_name}{file_ext}"
            
        # 确保文件名不包含非法字符
        import re
        new_filename = re.sub(r'[\\/:*?"<>|]', '', new_filename)
        
        # 构建新的完整路径
        new_path = os.path.join(file_dir, new_filename)
        
        # 如果文件已存在，添加序号
        counter = 1
        while os.path.exists(new_path):
            if self.artist_name:
                new_filename = f"{self.song_name}--{self.artist_name}_{counter}{file_ext}"
            else:
                new_filename = f"{self.song_name}_{counter}{file_ext}"
            new_path = os.path.join(file_dir, new_filename)
            counter += 1
            
        # 重命名文件
        try:
            os.rename(file_path, new_path)
            return new_path
        except Exception as e:
            print(f"重命名文件时发生错误: {str(e)}")
            return file_path
        
    def run(self):
        if not TOOLS_IMPORTED:
            self.download_error.emit("搜索和下载功能不可用")
            return
            
        try:
            # 更新状态
            self.download_progress.emit(f"正在搜索: {self.song_name}" + 
                                       (f" - {self.artist_name}" if self.artist_name else " 原唱"))
            
            # 搜索BV号
            query = f"{self.song_name} {self.artist_name}" if self.artist_name else f"{self.song_name} 原唱"
            html_content = search_music.search_bilibili(query)
            videos = search_music.extract_videos(html_content)
            
            if not videos:
                self.download_error.emit(f"未找到歌曲: {self.song_name}")
                return
                
            selected_bv = search_music.send_to_llm(videos, self.song_name, self.artist_name)
            
            if not selected_bv:
                self.download_error.emit(f"无法选择合适的视频: {self.song_name}")
                return
                
            # 更新状态
            self.download_progress.emit(f"正在下载: {self.song_name} (BV: {selected_bv})")
            
            # 下载音频
            download_dir = auto_download_bilibili.ensure_download_dir()
            file_path = auto_download_bilibili.download_bilibili_audio(selected_bv, download_dir)
            
            if not file_path:
                self.download_error.emit(f"下载失败: {self.song_name}")
                return
                
            # 更新状态
            self.download_progress.emit(f"正在处理文件名: {self.song_name}")
            
            # 根据是否有歌手信息决定命名方式
            if self.artist_name:
                # 如果有歌曲和歌手信息，使用简单的歌曲--歌手格式命名
                self.download_progress.emit(f"正在重命名: {self.song_name}--{self.artist_name}")
                renamed_path = self.rename_file(file_path)
            else:
                # 如果没有歌手信息，尝试使用AI识别并重命名
                self.download_progress.emit(f"正在使用AI重命名: {self.song_name}")
                renamed_path = auto_download_bilibili.rename_file_with_ai(file_path, "LLM")
            
            # 发送完成信号
            self.download_complete.emit(renamed_path)
            
        except Exception as e:
            self.download_error.emit(f"下载过程中发生错误: {str(e)}")


class MusicPlayer(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("牛马音乐播放器")
        self.setMinimumSize(1000, 600)  # 增加窗口大小以适应更大字体
        self.current_playlist_path = None  # 初始化变量
        
        # 获取系统主题的默认文本颜色
        self.default_text_color = self.palette().color(QPalette.Text)
        
        # 初始化媒体播放器
        self.player = QMediaPlayer()
        self.player.stateChanged.connect(self.media_state_changed)
        self.player.mediaStatusChanged.connect(self.media_status_changed)
        self.player.positionChanged.connect(self.position_changed)
        self.player.durationChanged.connect(self.duration_changed)
        
        # 初始化播放列表变量
        self.current_playlist = []  # 歌曲对象列表 (name, artist, path)
        self.current_index = -1
        self.play_mode = 0  # 0: 列表循环, 1: 单曲循环, 2: 随机播放
        self.play_modes = ["列表循环", "单曲循环", "随机播放"]
        
        # 添加缓存音频时长的字典
        self.audio_durations = {}
        
        # 设置UI
        self.setup_ui()
        
        # 加载播放列表文件
        self.load_playlists()
        
        # 设置定时器用于更新状态
        self.status_timer = QTimer(self)
        self.status_timer.timeout.connect(self.update_status)
        self.status_timer.start(1000)  # 每秒更新一次
        
    def setup_ui(self):
        """设置UI界面"""
        # 创建中央部件和主布局
        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        main_layout = QVBoxLayout(central_widget)
        
        # 增大字体
        app_font = QFont("Microsoft YaHei", 12)
        self.setFont(app_font)
        
        # 顶部控件布局
        top_layout = QHBoxLayout()
        
        # 播放列表选择器
        self.playlist_selector = QComboBox()
        self.playlist_selector.setMinimumWidth(250)
        self.playlist_selector.setFont(app_font)
        self.playlist_selector.currentIndexChanged.connect(self.load_selected_playlist)
        # 添加点击当前列表重新加载功能
        self.playlist_selector.activated.connect(self.reload_current_playlist)
        
        list_label = QLabel("歌曲列表:")
        list_label.setFont(app_font)
        top_layout.addWidget(list_label)
        top_layout.addWidget(self.playlist_selector)
        
        # 搜索框
        search_label = QLabel("搜索:")
        search_label.setFont(app_font)
        top_layout.addWidget(search_label)
        
        self.search_box = QLineEdit()
        self.search_box.setFont(app_font)
        self.search_box.setPlaceholderText("输入歌名或歌名--歌手")
        self.search_box.returnPressed.connect(self.search_song)
        top_layout.addWidget(self.search_box)
        
        # 添加顶部布局到主布局
        main_layout.addLayout(top_layout)
        
        # 歌曲列表部件（使用QTableWidget代替QListWidget来显示两列）
        self.song_list = QTableWidget()
        self.song_list.setFont(QFont("Microsoft YaHei", 12))
        self.song_list.setAlternatingRowColors(True)
        self.song_list.setColumnCount(2)
        self.song_list.setHorizontalHeaderLabels(["歌曲名称", "歌手"])
        self.song_list.horizontalHeader().setSectionResizeMode(0, QHeaderView.Stretch)
        self.song_list.horizontalHeader().setSectionResizeMode(1, QHeaderView.Stretch)
        self.song_list.horizontalHeader().setFont(QFont("Microsoft YaHei", 12, QFont.Bold))
        self.song_list.cellDoubleClicked.connect(self.play_selected_song)
        # 禁用歌曲列表接收上下左右键
        self.song_list.installEventFilter(self)
        
        # 禁止编辑表格内容
        self.song_list.setEditTriggers(QAbstractItemView.NoEditTriggers)
        
        main_layout.addWidget(self.song_list)
        
        # 创建自定义进度条（只能点击，不能拖动）
        class ClickableSlider(QSlider):
            def __init__(self, orientation):
                super().__init__(orientation)
                
            def mousePressEvent(self, event):
                # 只处理鼠标点击事件，将位置转换为值
                if event.button() == Qt.LeftButton:
                    value = QStyle.sliderValueFromPosition(
                        self.minimum(), self.maximum(), 
                        event.x(), self.width())
                    self.setValue(value)
                    self.sliderMoved.emit(value)
                    event.accept()
                else:
                    super().mousePressEvent(event)
                    
            def mouseMoveEvent(self, event):
                # 禁止拖动行为
                event.ignore()
        
        # 使用自定义的只能点击的进度条
        self.position_slider = ClickableSlider(Qt.Horizontal)
        self.position_slider.setRange(0, 0)
        self.position_slider.sliderMoved.connect(self.set_position)
        main_layout.addWidget(self.position_slider)
        
        # 时间标签
        time_layout = QHBoxLayout()
        self.time_label = QLabel("00:00 / 00:00")
        self.time_label.setFont(QFont("Microsoft YaHei", 12))
        time_layout.addStretch()
        time_layout.addWidget(self.time_label)
        main_layout.addLayout(time_layout)
        
        # 播放控制布局
        controls_layout = QHBoxLayout()
        
        # 上一曲按钮
        self.prev_button = QPushButton("上一曲")
        self.prev_button.setFont(app_font)
        self.prev_button.clicked.connect(self.play_previous)
        controls_layout.addWidget(self.prev_button)
        
        # 播放/暂停按钮
        self.play_button = QPushButton("播放")
        self.play_button.setFont(app_font)
        self.play_button.clicked.connect(self.toggle_playback)
        controls_layout.addWidget(self.play_button)
        
        # 下一曲按钮
        self.next_button = QPushButton("下一曲")
        self.next_button.setFont(app_font)
        self.next_button.clicked.connect(self.play_next)
        controls_layout.addWidget(self.next_button)
        
        # 播放模式按钮
        self.mode_button = QPushButton(self.play_modes[self.play_mode])
        self.mode_button.setFont(app_font)
        self.mode_button.clicked.connect(self.toggle_play_mode)
        controls_layout.addWidget(self.mode_button)
        
        # 添加控制布局到主布局
        main_layout.addLayout(controls_layout)
        
        # 状态栏
        self.statusbar = QStatusBar()
        self.setStatusBar(self.statusbar)
        
        # 状态标签
        self.playing_status = QLabel("未播放")
        self.playing_status.setFont(QFont("Microsoft YaHei", 11))
        
        self.mode_status = QLabel(self.play_modes[self.play_mode])
        self.mode_status.setFont(QFont("Microsoft YaHei", 11))
        
        self.download_status = QLabel("准备就绪")
        self.download_status.setFont(QFont("Microsoft YaHei", 11))
        
        self.statusbar.addWidget(self.playing_status)
        self.statusbar.addWidget(self.mode_status)
        self.statusbar.addPermanentWidget(self.download_status)
        
        # 设置键盘焦点策略，确保窗口可以接收键盘事件
        self.setFocusPolicy(Qt.StrongFocus)
    
    def get_audio_duration(self, file_path):
        """
        获取音频文件的准确时长（毫秒）
        使用mutagen库来获取更准确的时长
        如果获取失败，则回退到QMediaPlayer提供的时长
        """
        # 检查缓存中是否已有该文件的时长
        if file_path in self.audio_durations:
            return self.audio_durations[file_path]
            
        # 如果mutagen库可用，则使用它来获取时长
        if MUTAGEN_IMPORTED:
            try:
                audio_file = MutagenFile(file_path)
                if audio_file is not None:
                    # 获取时长（秒）并转换为毫秒
                    duration_ms = int(audio_file.info.length * 1000)
                    # 缓存结果
                    self.audio_durations[file_path] = duration_ms
                    return duration_ms
            except Exception as e:
                print(f"使用mutagen获取音频时长失败: {str(e)}")
        
        # 如果使用mutagen获取失败，等待一段时间后尝试使用QMediaPlayer获取
        temp_player = QMediaPlayer()
        temp_player.setMedia(QMediaContent(QUrl.fromLocalFile(file_path)))
        
        # 等待媒体加载
        for _ in range(50):  # 最多等待5秒
            if temp_player.duration() > 0:
                duration_ms = temp_player.duration()
                self.audio_durations[file_path] = duration_ms
                return duration_ms
            time.sleep(0.1)
            
        # 如果仍然获取不到，返回0
        return 0
    
    def load_playlists(self):
        """扫描脚本目录中的MUSICLIST_*.txt文件"""
        self.playlist_selector.clear()
        
        script_dir = os.path.dirname(os.path.abspath(__file__))
        playlist_files = []
        
        for file in os.listdir(script_dir):
            if file.startswith("MUSICLIST_") and file.endswith(".txt"):
                playlist_name = file[len("MUSICLIST_"):-4]  # 移除前缀和扩展名
                playlist_files.append((playlist_name, os.path.join(script_dir, file)))
        
        if playlist_files:
            for playlist_name, file_path in sorted(playlist_files):
                self.playlist_selector.addItem(playlist_name, file_path)
        else:
            self.statusbar.showMessage("未找到歌曲列表文件，请创建MUSICLIST_名字.txt文件", 5000)
    
    def load_selected_playlist(self):
        """加载选定的播放列表文件"""
        if self.playlist_selector.count() == 0:
            return
            
        # 停止当前播放
        self.player.stop()
        self.current_index = -1
        self.update_playing_status()
        
        playlist_path = self.playlist_selector.currentData()
        self.current_playlist_path = playlist_path  # 保存当前播放列表路径，便于后续写入新歌曲
        
        try:
            with open(playlist_path, 'r', encoding='utf-8') as f:
                songs = [line.strip() for line in f.readlines() if line.strip()]
            
            self.current_playlist = []
            self.song_list.setRowCount(0)  # 清空表格
            
            for song_line in songs:
                if "--" in song_line:
                    song_name, artist_name = song_line.split("--", 1)
                    song_name = song_name.strip()
                    artist_name = artist_name.strip()
                else:
                    song_name = song_line.strip()
                    artist_name = ""  # 使用空字符串代替"未知"
                
                # 创建歌曲对象
                song = {
                    "name": song_name,
                    "artist": artist_name,
                    "path": None,  # 稍后在找到或下载文件时设置
                    "duration": 0  # 添加时长字段，初始为0
                }
                
                self.current_playlist.append(song)
                
                # 添加到表格中
                row_position = self.song_list.rowCount()
                self.song_list.insertRow(row_position)
                self.song_list.setItem(row_position, 0, QTableWidgetItem(song_name))
                self.song_list.setItem(row_position, 1, QTableWidgetItem(artist_name))
                
                # 设置文本颜色为默认文本颜色
                self.song_list.item(row_position, 0).setForeground(self.default_text_color)
                self.song_list.item(row_position, 1).setForeground(self.default_text_color)
            
            # 查找歌曲文件
            self.find_song_files()
            
            playlist_name = self.playlist_selector.currentText()
            self.statusbar.showMessage(f"已载入歌曲列表: {playlist_name} ({len(self.current_playlist)}首歌曲)", 5000)
            
        except Exception as e:
            QMessageBox.warning(self, "错误", f"载入歌曲列表失败: {str(e)}")
    
    def find_song_files(self):
        """查找播放列表中歌曲的本地文件，并从文件名中提取歌名和歌手信息"""
        script_dir = os.path.dirname(os.path.abspath(__file__))
        music_dir = os.path.join(script_dir, "music_download")
        
        if not os.path.exists(music_dir):
            os.makedirs(music_dir)
            return
        
        # 获取所有音乐文件
        audio_extensions = ['.mp3', '.wav', '.ogg', '.flac', '.m4a']
        music_files = []
        
        for file in os.listdir(music_dir):
            file_path = os.path.join(music_dir, file)
            if os.path.isfile(file_path) and any(file.lower().endswith(ext) for ext in audio_extensions):
                music_files.append(file_path)
        
        # 从文件名中提取歌名和歌手，并与播放列表中的歌曲匹配
        for i, song in enumerate(self.current_playlist):
            song_name = song["name"].lower()
            song_artist = song["artist"].lower() if song["artist"] else None
            
            found = False
            for file_path in music_files:
                filename = os.path.basename(file_path)
                filename_lower = filename.lower()
                
                # 检查歌名和歌手是否都在文件名中
                if song_name in filename_lower:
                    if song_artist is None or song_artist in filename_lower:
                        self.current_playlist[i]["path"] = file_path
                        
                        # 获取并缓存文件时长
                        self.current_playlist[i]["duration"] = self.get_audio_duration(file_path)
                        
                        # 尝试从文件名中更新歌曲信息
                        if "--" in filename:
                            # 从文件名提取信息
                            name_part, artist_part = filename.rsplit("--", 1)
                            # 移除扩展名
                            for ext in audio_extensions:
                                if artist_part.lower().endswith(ext):
                                    artist_part = artist_part[:-len(ext)]
                                    break
                            
                            # 更新歌曲信息
                            self.current_playlist[i]["name"] = name_part
                            self.current_playlist[i]["artist"] = artist_part
                            
                            # 更新表格中的显示
                            self.song_list.setItem(i, 0, QTableWidgetItem(name_part))
                            self.song_list.setItem(i, 1, QTableWidgetItem(artist_part))
                            
                            # 设置文本颜色为默认文本颜色
                            self.song_list.item(i, 0).setForeground(self.default_text_color)
                            self.song_list.item(i, 1).setForeground(self.default_text_color)
                        
                        found = True
                        break
            
            # 如果未找到，更新UI项目以指示需要下载
            if not found:
                # 在表格中获取并更新项目
                name_item = self.song_list.item(i, 0)
                if name_item:
                    current_text = name_item.text()
                    if "[需要下载]" not in current_text:
                        name_item.setText(f"{current_text} [需要下载]")
                        name_item.setForeground(QColor("#777777"))
    
    def search_song(self):
        """基于文本输入搜索歌曲，并将新歌曲添加到当前播放列表文件"""
        search_text = self.search_box.text().strip()
        if not search_text:
            return
            
        # 解析搜索文本
        if "--" in search_text:
            song_name, artist_name = search_text.split("--", 1)
            song_name = song_name.strip()
            artist_name = artist_name.strip()
        else:
            song_name = search_text.strip()
            artist_name = ""  # 使用空字符串代替"未知"
        
        # 首先尝试在当前播放列表中查找
        found_in_playlist = False
        for i, song in enumerate(self.current_playlist):
            if song["name"].lower() == song_name.lower():
                if artist_name == "" or (song["artist"] and song["artist"].lower() == artist_name.lower()):
                    # 完美匹配，如果可用则播放
                    if song["path"]:
                        self.play_song(i)
                        found_in_playlist = True
                        break
                    else:
                        # 需要先下载
                        self.download_and_play(song["name"], artist_name, playlist_index=i)
                        found_in_playlist = True
                        break
        
        if found_in_playlist:
            return
            
        # 如果不在播放列表中，尝试在本地文件中查找
        script_dir = os.path.dirname(os.path.abspath(__file__))
        music_dir = os.path.join(script_dir, "music_download")
        
        if not os.path.exists(music_dir):
            os.makedirs(music_dir)
            self.download_and_play(song_name, artist_name)
            return
        
        # 查找匹配文件
        audio_extensions = ['.mp3', '.wav', '.ogg', '.flac', '.m4a']
        found_file = None
        found_artist = artist_name
        
        for file in os.listdir(music_dir):
            file_path = os.path.join(music_dir, file)
            if os.path.isfile(file_path) and any(file.lower().endswith(ext) for ext in audio_extensions):
                filename = os.path.basename(file_path).lower()
                
                if song_name.lower() in filename:
                    if artist_name == "" or artist_name.lower() in filename:
                        found_file = file_path
                        
                        # 尝试从文件名提取歌手信息
                        if "--" in file:
                            base_name = os.path.basename(file_path)
                            name_part, artist_part = base_name.rsplit("--", 1)
                            # 移除扩展名
                            for ext in audio_extensions:
                                if artist_part.lower().endswith(ext):
                                    artist_part = artist_part[:-len(ext)]
                                    break
                            song_name = name_part
                            found_artist = artist_part
                        
                        break
        
        if found_file:
            # 获取文件时长
            duration = self.get_audio_duration(found_file)
            
            # 创建临时歌曲条目并播放
            temp_song = {
                "name": song_name,
                "artist": found_artist,
                "path": found_file,
                "duration": duration
            }
            
            # 添加到播放列表
            self.current_playlist.append(temp_song)
            
            # 添加到表格
            row_position = self.song_list.rowCount()
            self.song_list.insertRow(row_position)
            self.song_list.setItem(row_position, 0, QTableWidgetItem(song_name))
            self.song_list.setItem(row_position, 1, QTableWidgetItem(found_artist))
            
            # 设置文本颜色为默认文本颜色
            self.song_list.item(row_position, 0).setForeground(self.default_text_color)
            self.song_list.item(row_position, 1).setForeground(self.default_text_color)
            
            # 将新歌曲添加到播放列表文件中
            if hasattr(self, 'current_playlist_path') and self.current_playlist_path:
                try:
                    # 根据是否有歌手决定如何写入
                    if found_artist:
                        song_entry = f"{song_name}--{found_artist}\n"
                    else:
                        song_entry = f"{song_name}\n"
                    
                    # 检查文件是否以换行符结束
                    self.ensure_newline_in_playlist(self.current_playlist_path, song_entry)
                    
                    print(f"已将找到的歌曲 {song_name}" + (f"--{found_artist}" if found_artist else "") + " 添加到播放列表文件")
                except Exception as e:
                    print(f"将歌曲添加到播放列表文件时出错: {e}")
            
            # 仅当当前没有播放的歌曲时才播放此曲
            if self.current_index == -1:
                self.play_song(len(self.current_playlist) - 1)
        else:
            # 需要下载
            self.download_and_play(song_name, artist_name)
    
    def download_and_play(self, song_name, artist_name=None, playlist_index=None):
        """下载歌曲并在准备好时播放"""
        if not TOOLS_IMPORTED:
            QMessageBox.warning(self, "功能不可用", 
                           "搜索和下载功能不可用。请确保 search_music.py 和 auto_download_bilibili.py 在同一目录中。")
            self.download_status.setText("下载功能不可用")
            return
            
        # 记录当前是否有歌曲在播放
        was_playing = (self.current_index != -1)
            
        self.download_status.setText(f"正在下载: {song_name}")
        
        # 创建并启动下载工作线程
        self.download_worker = DownloadWorker(song_name, artist_name)
        self.download_worker.download_complete.connect(
            lambda path: self.handle_download_complete(path, song_name, artist_name, playlist_index, was_playing)
        )
        self.download_worker.download_progress.connect(self.download_status.setText)
        self.download_worker.download_error.connect(self.handle_download_error)
        
        self.download_worker.start()
    
    def handle_download_complete(self, file_path, song_name, artist_name, playlist_index=None, was_playing=False):
        """处理完成的下载，并将新歌曲添加到当前播放列表文件中"""
        self.download_status.setText("下载完成")
        
        # 获取音频文件时长
        duration = self.get_audio_duration(file_path)
        
        if playlist_index is not None:
            # 更新现有播放列表条目
            self.current_playlist[playlist_index]["path"] = file_path
            self.current_playlist[playlist_index]["duration"] = duration
            
            # 更新表格项
            self.song_list.setItem(playlist_index, 0, QTableWidgetItem(song_name))
            self.song_list.setItem(playlist_index, 1, QTableWidgetItem(artist_name if artist_name else ""))
            
            # 设置文本颜色为默认文本颜色
            for j in range(self.song_list.columnCount()):
                item = self.song_list.item(playlist_index, j)
                if item:
                    item.setForeground(self.default_text_color)
            
            # 仅当之前没有歌曲在播放时才播放下载的歌曲
            if not was_playing:
                self.play_song(playlist_index)
        else:
            # 创建新的播放列表条目
            temp_song = {
                "name": song_name,
                "artist": artist_name if artist_name else "",
                "path": file_path,
                "duration": duration
            }
            
            # 添加到播放列表
            self.current_playlist.append(temp_song)
            
            # 添加到表格中
            row_position = self.song_list.rowCount()
            self.song_list.insertRow(row_position)
            self.song_list.setItem(row_position, 0, QTableWidgetItem(song_name))
            self.song_list.setItem(row_position, 1, QTableWidgetItem(artist_name if artist_name else ""))
            
            # 设置文本颜色为默认文本颜色
            self.song_list.item(row_position, 0).setForeground(self.default_text_color)
            self.song_list.item(row_position, 1).setForeground(self.default_text_color)
            
            # 将新歌曲添加到播放列表文件中
            if hasattr(self, 'current_playlist_path') and self.current_playlist_path:
                try:
                    # 根据是否有歌手决定如何写入
                    if artist_name:
                        song_entry = f"{song_name}--{artist_name}\n"
                    else:
                        song_entry = f"{song_name}\n"
                    
                    # 确保文件以换行符结束
                    self.ensure_newline_in_playlist(self.current_playlist_path, song_entry)
                    
                    print(f"已将新歌曲 {song_name}" + (f"--{artist_name}" if artist_name else "") + " 添加到播放列表文件")
                except Exception as e:
                    print(f"将歌曲添加到播放列表文件时出错: {e}")
            
            # 仅当之前没有歌曲在播放时才播放下载的歌曲
            if not was_playing:
                self.play_song(len(self.current_playlist) - 1)
    
    def ensure_newline_in_playlist(self, playlist_path, song_entry):
        """确保播放列表文件以换行符结束后再添加新条目"""
        try:
            # 检查文件是否存在
            if not os.path.exists(playlist_path):
                with open(playlist_path, 'w', encoding='utf-8') as f:
                    f.write(song_entry)
                return

            # 检查文件是否为空
            if os.path.getsize(playlist_path) == 0:
                with open(playlist_path, 'w', encoding='utf-8') as f:
                    f.write(song_entry)
                return

            # 检查文件末尾是否有换行符
            with open(playlist_path, 'rb+') as f:
                f.seek(-1, os.SEEK_END)
                last_char = f.read(1)
                
                # 如果最后一个字符不是换行符，添加一个
                if last_char != b'\n':
                    f.seek(0, os.SEEK_END)
                    f.write(b'\n')
            
            # 追加新条目
            with open(playlist_path, 'a', encoding='utf-8') as f:
                f.write(song_entry)
                
        except Exception as e:
            print(f"确保文件换行时出错: {str(e)}")
            # 如果出错，尝试直接追加
            with open(playlist_path, 'a', encoding='utf-8') as f:
                f.write(song_entry)
    
    def handle_download_error(self, error_message):
        """处理下载错误"""
        self.download_status.setText("下载失败")
        QMessageBox.warning(self, "下载错误", error_message)
    
    def play_selected_song(self, row, column):
        """双击列表行时播放歌曲"""
        # 在表格中我们直接使用行号作为索引
        self.play_song(row)
    
    def play_song(self, index):
        """播放给定索引的歌曲"""
        if not self.current_playlist or index < 0 or index >= len(self.current_playlist):
            return
            
        song = self.current_playlist[index]
        
        if not song["path"]:
            # 需要先下载
            self.download_and_play(song["name"], song["artist"], index)
            return
            
        # 更新当前索引
        self.current_index = index
        
        # 更新表格选择和高亮
        self.song_list.selectRow(index)
        self.song_list.scrollToItem(self.song_list.item(index, 0))
        
        # 设置所有行的文本颜色为默认颜色，背景为默认
        for i in range(self.song_list.rowCount()):
            for j in range(self.song_list.columnCount()):
                item = self.song_list.item(i, j)
                if item:
                    item.setBackground(QColor("transparent"))
                    item.setForeground(self.default_text_color)
        
        # 设置当前行的背景颜色为高亮，文本为黑色以增强对比
        for j in range(self.song_list.columnCount()):
            item = self.song_list.item(index, j)
            if item:
                item.setBackground(QColor("#E6F3FF"))
                item.setForeground(QColor("black"))  # 正在播放的歌曲文字颜色为黑色
        
        # 播放歌曲
        self.player.setMedia(QMediaContent(QUrl.fromLocalFile(song["path"])))
        self.player.play()
        
        # 如果有缓存的时长，立即更新进度条和时间标签
        if song["duration"] > 0:
            self.position_slider.setRange(0, song["duration"])
            self.time_label.setText(f"00:00 / {self.format_time(song['duration'])}")
        
        # 更新UI
        self.play_button.setText("暂停")
        self.update_playing_status()
    
    def toggle_playback(self):
        """在播放和暂停之间切换"""
        if self.player.state() == QMediaPlayer.PlayingState:
            self.player.pause()
            self.play_button.setText("播放")
        else:
            if self.current_index >= 0:
                self.player.play()
                self.play_button.setText("暂停")
            elif self.current_playlist:
                # 开始播放第一首歌
                self.play_song(0)
    
    def play_previous(self):
        """播放上一首歌"""
        if not self.current_playlist:
            return
            
        if self.play_mode == 2:  # 随机模式
            self.play_random_song()
            return
            
        if self.current_index > 0:
            self.play_song(self.current_index - 1)
        else:
            # 循环到播放列表末尾
            self.play_song(len(self.current_playlist) - 1)
    
    def play_next(self):
        """播放下一首歌"""
        if not self.current_playlist:
            return
            
        if self.play_mode == 2:  # 随机模式
            self.play_random_song()
            return
            
        if self.current_index < len(self.current_playlist) - 1:
            self.play_song(self.current_index + 1)
        else:
            # 循环到播放列表开头
            self.play_song(0)
    
    def play_random_song(self):
        """从播放列表播放随机歌曲"""
        if not self.current_playlist:
            return
            
        # 避免再次播放相同的歌曲
        if len(self.current_playlist) > 1:
            while True:
                new_index = random.randint(0, len(self.current_playlist) - 1)
                if new_index != self.current_index:
                    break
        else:
            new_index = 0
            
        self.play_song(new_index)
    
    def toggle_play_mode(self):
        """在播放模式之间切换"""
        self.play_mode = (self.play_mode + 1) % len(self.play_modes)
        mode_text = self.play_modes[self.play_mode]
        self.mode_button.setText(mode_text)
        self.mode_status.setText(mode_text)
    
    def media_state_changed(self, state):
        """处理媒体状态变化"""
        if state == QMediaPlayer.PlayingState:
            self.play_button.setText("暂停")
        else:
            self.play_button.setText("播放")
    
    def media_status_changed(self, status):
        """处理媒体状态变化"""
        if status == QMediaPlayer.EndOfMedia:
            # 根据播放模式处理轨道结束
            if self.play_mode == 0:  # 列表循环
                self.play_next()
            elif self.play_mode == 1:  # 单曲循环
                # 重新播放当前歌曲
                self.player.setPosition(0)
                self.player.play()
            elif self.play_mode == 2:  # 随机
                self.play_random_song()
    
    def position_changed(self, position):
        """处理播放位置变化"""
        # 更新进度条（仅显示，不可拖动）
        if self.position_slider.maximum() > 0:
            self.position_slider.setValue(position)
            
        # 更新时间标签
        current_time = self.format_time(position)
        
        # 使用缓存的时长而不是player.duration()
        if self.current_index >= 0 and self.current_index < len(self.current_playlist):
            song = self.current_playlist[self.current_index]
            if song["duration"] > 0:
                total_time = self.format_time(song["duration"])
            else:
                # 如果没有缓存的时长，尝试获取并缓存
                duration = self.player.duration()
                if duration > 0:
                    song["duration"] = duration
                    self.audio_durations[song["path"]] = duration
                total_time = self.format_time(duration)
        else:
            total_time = self.format_time(self.player.duration())
            
        self.time_label.setText(f"{current_time} / {total_time}")
    
    def duration_changed(self, duration):
        """处理持续时间变化"""
        # 更新进度条范围
        self.position_slider.setRange(0, duration)
        
        # 更新当前歌曲的缓存时长
        if self.current_index >= 0 and self.current_index < len(self.current_playlist):
            song = self.current_playlist[self.current_index]
            
            # 如果时长有变化，更新缓存
            if duration > 0 and song["duration"] != duration:
                song["duration"] = duration
                if song["path"]:
                    self.audio_durations[song["path"]] = duration
    
    def set_position(self, position):
        """设置播放位置"""
        self.player.setPosition(position)
    
    def skip_seconds(self, seconds):
        """前进或后退指定的秒数"""
        if self.player.state() == QMediaPlayer.PlayingState or self.player.state() == QMediaPlayer.PausedState:
            current_position = self.player.position()
            new_position = max(0, current_position + seconds * 1000)  # 转换为毫秒
            self.player.setPosition(new_position)
            
    def keyPressEvent(self, event):
        """处理键盘按键事件"""
        if event.key() == Qt.Key_Left:
            # 左箭头: 后退5秒
            self.skip_seconds(-5)
        elif event.key() == Qt.Key_Right:
            # 右箭头: 前进5秒
            self.skip_seconds(5)
        elif event.key() == Qt.Key_Up:
            # 上箭头: 上一曲
            self.play_previous()
        elif event.key() == Qt.Key_Down:
            # 下箭头: 下一曲
            self.play_next()
        elif event.key() == Qt.Key_Space:
            # 空格键: 播放/暂停
            self.toggle_playback()
        else:
            # 其他按键交给父类处理
            super().keyPressEvent(event)
            
    def eventFilter(self, obj, event):
        """事件过滤器，用于拦截表格的方向键事件和Tab键事件"""
        if obj is self.song_list and event.type() == event.KeyPress:
            if event.key() in [Qt.Key_Left, Qt.Key_Right, Qt.Key_Up, Qt.Key_Down]:
                # 将方向键事件传递给主窗口
                self.keyPressEvent(event)
                return True
            elif event.key() == Qt.Key_Tab:
                # 拦截Tab键事件，防止焦点在表格内移动
                return True
        return super().eventFilter(obj, event)
        
    def reload_current_playlist(self):
        """重新加载当前选中的播放列表"""
        if self.playlist_selector.count() > 0:
            # 先保存当前播放的歌曲索引
            current_index = self.current_index
            was_playing = (self.player.state() == QMediaPlayer.PlayingState)
            
            # 重新加载播放列表
            self.load_selected_playlist()
            
            # 如果之前正在播放，则尝试恢复到相同位置
            if was_playing and current_index >= 0 and current_index < len(self.current_playlist):
                self.play_song(current_index)
            
            self.statusbar.showMessage("已重新加载播放列表", 3000)

    def format_time(self, ms):
        """格式化时间毫秒为分:秒格式"""
        secs = ms // 1000
        mins = secs // 60
        secs = secs % 60
        return f"{mins:02d}:{secs:02d}"
    
    def update_playing_status(self):
        """更新播放状态标签"""
        if self.current_index >= 0 and self.current_index < len(self.current_playlist):
            song = self.current_playlist[self.current_index]
            status_text = f"正在播放: {song['name']}"
            if song["artist"]:
                status_text += f" - {song['artist']}"
            self.playing_status.setText(status_text)
        else:
            self.playing_status.setText("未播放")
            
    def update_status(self):
        """定期更新状态信息"""
        # 这个方法只是为了更新状态信息，目前没有特别需要的操作
        pass
            
    def closeEvent(self, event):
        """窗口关闭事件"""
        # 停止播放
        self.player.stop()
        event.accept()


def main():
    app = QApplication(sys.argv)
    
    # 设置应用程序样式
    app.setStyle("Fusion")
    
    # 创建并显示播放器
    player = MusicPlayer()
    player.show()
    
    sys.exit(app.exec_())


if __name__ == "__main__":
    main()