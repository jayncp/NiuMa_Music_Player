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
        
    def rename_file(self, file_path, artist_name=None):
        """基于歌曲和歌手信息重命名文件"""
        if not file_path:
            return file_path
                
        import os, re
        
        # 获取文件目录和扩展名
        file_dir = os.path.dirname(file_path)
        file_ext = os.path.splitext(file_path)[1]
        
        # 确定要使用的歌手名
        artist = artist_name if artist_name is not None else self.artist_name or "Unknown"
        
        # 构建新文件名并去除非法字符
        new_filename = f"{self.song_name}--{artist}{file_ext}"
        new_filename = re.sub(r'[\\/:*?"<>|]', '', new_filename)
        
        # 构建新路径并处理文件名冲突
        new_path = os.path.join(file_dir, new_filename)
        counter = 1
        while os.path.exists(new_path):
            new_filename = f"{self.song_name}--{artist}_{counter}{file_ext}"
            new_filename = re.sub(r'[\\/:*?"<>|]', '', new_filename)
            new_path = os.path.join(file_dir, new_filename)
            counter += 1
                
        # 重命名文件
        try:
            os.rename(file_path, new_path)
            return new_path
        except Exception as e:
            print(f"重命名文件时发生错误: {str(e)}")
            return file_path

    def handle_file_renaming(self, file_path):
        """处理文件重命名逻辑"""
        self.download_progress.emit(f"正在处理文件名: {self.song_name}")
        
        # 如果提供了歌手名，直接使用
        if self.artist_name:
            self.download_progress.emit(f"正在重命名: {self.song_name}--{self.artist_name}")
            return self.rename_file(file_path)
        
        # 否则尝试使用AI分析
        self.download_progress.emit(f"正在使用AI分析获取歌手信息: {self.song_name}")
        song_info = auto_download_bilibili.call_ai_for_rename(file_path)
        
        # 根据AI结果决定使用的歌手名
        ai_artist = None
        if song_info and "artist" in song_info:
            ai_artist = song_info["artist"].replace(" ", "_")
            self.download_progress.emit(f"正在重命名: {self.song_name}--{ai_artist}")
        else:
            self.download_progress.emit(f"无法获取歌手信息，仅使用歌名: {self.song_name}--Unknown")
        
        return self.rename_file(file_path, ai_artist)

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
            
            # 处理文件重命名
            renamed_path = self.handle_file_renaming(file_path)
            
            # 发送完成信号
            self.download_complete.emit(renamed_path)
            
        except Exception as e:
            self.download_error.emit(f"下载过程中发生错误: {str(e)}")


class MusicPlayer(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("牛马音乐播放器")
        
        # 获取当前屏幕尺寸
        screen = QApplication.primaryScreen().availableGeometry()
        screen_width = screen.width()
        screen_height = screen.height()
        
        # 设置窗口尺寸为屏幕的一半
        self.setMinimumSize(screen_width // 2, screen_height // 2)
        
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
        
        # 添加搜索延迟计时器
        self.search_timer = QTimer(self)
        self.search_timer.setSingleShot(True)
        self.search_timer.setInterval(1000)  # 1秒延迟
        self.search_timer.timeout.connect(self.execute_search)
        
        # 添加下载队列
        self.download_queue = []
        self.is_downloading = False
        
        # 设置UI
        self.setup_ui()
        
        # 加载播放列表文件
        self.load_playlists()
        
        # 设置定时器用于更新状态
        self.status_timer = QTimer(self)
        self.status_timer.timeout.connect(self.update_status)
        self.status_timer.start(1000)  # 每秒更新一次

        # 添加一个锁定标志，防止循环更新
        self.position_update_lock = False
    
        # 记录时长比例关系
        self.duration_ratio = 1.0
        
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
        self.search_box.setPlaceholderText("输入:“歌名”或“歌名--歌手”")
        self.search_box.returnPressed.connect(self.queue_search)
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
        self.playing_status.setFont(QFont("Microsoft YaHei", 13))
        
        self.mode_status = QLabel(self.play_modes[self.play_mode])
        self.mode_status.setFont(QFont("Microsoft YaHei", 13))
        
        self.download_status = QLabel("准备就绪")
        self.download_status.setFont(QFont("Microsoft YaHei", 13))
        
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

    def extract_song_info(self, filename):
        """从文件名中提取歌曲名和歌手信息"""
        # 移除扩展名
        file_base = os.path.splitext(filename)[0]
        
        # 检查是否有歌手信息
        if "--" in file_base:
            song_name, artist_name = file_base.split("--", 1)
            return song_name.strip(), artist_name.strip()
        else:
            return file_base.strip(), None

    def is_song_match(self, search_name, search_artist, target_name, target_artist):
        """根据新规则检查两个歌曲是否匹配"""
        # 歌曲名需要完全匹配（不区分大小写）
        if search_name.lower() != target_name.lower():
            return False
        
        # 如果搜索没有指定歌手，则认为匹配
        if not search_artist:
            return True
        
        # 如果目标没有歌手信息，但搜索指定了歌手，则不匹配
        if not target_artist:
            return False
        
        # 对于歌手，检查是否有一方是另一方的子串（不区分大小写）
        search_artist_lower = search_artist.lower()
        target_artist_lower = target_artist.lower()
        return search_artist_lower in target_artist_lower or target_artist_lower in search_artist_lower

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
            song_name = song["name"]
            song_artist = song["artist"] if song["artist"] else None
            
            found = False
            for file_path in music_files:
                filename = os.path.basename(file_path)
                file_song_name, file_artist_name = self.extract_song_info(filename)
                
                # 使用新的匹配逻辑
                if self.is_song_match(song_name, song_artist, file_song_name, file_artist_name):
                    self.current_playlist[i]["path"] = file_path
                    
                    # 获取并缓存文件时长
                    self.current_playlist[i]["duration"] = self.get_audio_duration(file_path)
                    
                    # 可能的话更新歌曲信息
                    if file_artist_name and not song_artist:
                        self.current_playlist[i]["artist"] = file_artist_name
                        self.song_list.setItem(i, 1, QTableWidgetItem(file_artist_name))
                    
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
        """基于文本输入搜索歌曲，使用新的匹配逻辑"""
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
        
        # 检查播放列表中是否已有该歌曲
        found_in_playlist = False
        for i, song in enumerate(self.current_playlist):
            # 使用新的匹配逻辑
            if self.is_song_match(song_name, artist_name, song["name"], song["artist"]):
                # 完美匹配，如果可用则播放
                if song["path"]:
                    self.play_song(i)
                    found_in_playlist = True
                    break
                else:
                    # 需要先下载
                    self.add_to_download_queue(song["name"], artist_name, playlist_index=i)
                    found_in_playlist = True
                    break
        
        if found_in_playlist:
            self.search_box.clear()
            return
            
        # 如果不在播放列表中，尝试在本地文件中查找
        script_dir = os.path.dirname(os.path.abspath(__file__))
        music_dir = os.path.join(script_dir, "music_download")
        
        if not os.path.exists(music_dir):
            os.makedirs(music_dir)
            self.add_to_download_queue(song_name, artist_name)
            self.search_box.clear()
            return
        
        # 查找匹配文件
        audio_extensions = ['.mp3', '.wav', '.ogg', '.flac', '.m4a']
        found_file = None
        found_artist = artist_name
        
        for file in os.listdir(music_dir):
            file_path = os.path.join(music_dir, file)
            if os.path.isfile(file_path) and any(file.lower().endswith(ext) for ext in audio_extensions):
                filename = os.path.basename(file_path)
                file_song_name, file_artist_name = self.extract_song_info(filename)
                
                # 使用新的匹配逻辑
                if self.is_song_match(song_name, artist_name, file_song_name, file_artist_name):
                    found_file = file_path
                    
                    # 使用文件名中的歌手信息（如果有）
                    if file_artist_name:
                        found_artist = file_artist_name
                    
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
            self.add_to_download_queue(song_name, artist_name)
            self.search_box.clear()
    
    def queue_search(self):
        """将搜索请求加入延迟队列"""
        if self.search_timer.isActive():
            self.search_timer.stop()  # 重置计时器
        self.search_timer.start()

    def execute_search(self):
        """实际执行搜索操作"""
        # 调用search_song方法来先检查本地文件和播放列表
        self.search_song()

    def add_to_download_queue(self, song_name, artist_name="", playlist_index=None):
        """将歌曲添加到下载队列"""
        # 首先检查是否已在队列中
        for item in self.download_queue:
            if item['song_name'].lower() == song_name.lower() and item['artist_name'].lower() == artist_name.lower():
                self.download_status.setText(f"已在队列中: {song_name}")
                return
        
        # 添加到队列
        self.download_queue.append({
            'song_name': song_name,
            'artist_name': artist_name,
            'playlist_index': playlist_index
        })
        
        # 更新状态
        queue_length = len(self.download_queue)
        self.download_status.setText(f"队列: {queue_length}首歌曲待下载")
        
        # 如果当前没有下载任务，启动下载
        if not self.is_downloading:
            self.process_download_queue()

    def process_download_queue(self):
        """处理下载队列中的下一个项目"""
        if not self.download_queue:
            self.is_downloading = False
            self.download_status.setText("所有下载完成")
            return
        
        # 获取队列中的下一个项目
        item = self.download_queue[0]
        self.is_downloading = True
        
        # 开始下载
        self.download_and_play(
            item['song_name'], 
            item['artist_name'], 
            item['playlist_index'],
            process_queue=True
        )

    def download_and_play(self, song_name, artist_name=None, playlist_index=None, process_queue=False):
        """下载歌曲并在准备好时播放"""
        if not TOOLS_IMPORTED:
            QMessageBox.warning(self, "功能不可用", 
                        "搜索和下载功能不可用。请确保 search_music.py 和 auto_download_bilibili.py 在同一目录中。")
            self.download_status.setText("下载功能不可用")
            
            # 移除当前任务并处理下一个
            if process_queue and self.download_queue:
                self.download_queue.pop(0)
                self.process_download_queue()
            return
            
        # 记录当前是否有歌曲在播放
        was_playing = (self.current_index != -1)
        
        # 更新状态显示
        queue_text = f"[队列:{len(self.download_queue)}]" if self.download_queue else ""
        self.download_status.setText(f"{queue_text} 正在下载: {song_name}")
        
        # 创建并启动下载工作线程
        self.download_worker = DownloadWorker(song_name, artist_name)
        
        # 修改信号连接以考虑队列处理
        if process_queue:
            self.download_worker.download_complete.connect(
                lambda path: self.handle_download_complete_queue(path, song_name, artist_name, playlist_index, was_playing)
            )
        else:
            self.download_worker.download_complete.connect(
                lambda path: self.handle_download_complete(path, song_name, artist_name, playlist_index, was_playing)
            )
        
        # 连接进度信号，显示更多细节
        self.download_worker.download_progress.connect(
            lambda msg: self.update_download_status(msg, len(self.download_queue))
        )
        
        # 修改错误处理以支持队列
        if process_queue:
            self.download_worker.download_error.connect(self.handle_download_error_queue)
        else:
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

    def update_download_status(self, message, queue_length=0):
        """更新下载状态，包括队列信息"""
        queue_text = f"[队列:{queue_length}]" if queue_length > 0 else ""
        self.download_status.setText(f"{queue_text} {message}")

    def handle_download_complete_queue(self, file_path, song_name, artist_name, playlist_index, was_playing):
        """处理队列中的下载完成"""
        # 处理当前下载项
        self.handle_download_complete(file_path, song_name, artist_name, playlist_index, was_playing)
        
        # 从队列中移除当前项
        if self.download_queue:
            self.download_queue.pop(0)
        
        # 处理队列中的下一个项目
        QTimer.singleShot(500, self.process_download_queue)

    def handle_download_error_queue(self, error_message):
        """处理队列中的下载错误"""
        # 显示错误消息
        self.download_status.setText(f"下载失败: {error_message}")
        QMessageBox.warning(self, "下载错误", error_message)
        
        # 从队列中移除当前项
        if self.download_queue:
            failed_item = self.download_queue.pop(0)
            print(f"从队列中移除失败的下载: {failed_item['song_name']}")
        
        # 如果队列为空，确保重置下载状态
        if not self.download_queue:
            self.is_downloading = False
    
        # 处理队列中的下一个项目
        QTimer.singleShot(1000, self.process_download_queue)
    
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
            # 只将歌曲添加到下载队列，而不是调用download_and_play
            self.add_to_download_queue(song["name"], song["artist"], index)
            self.statusbar.showMessage(f"'{song['name']}'已加入下载队列，下载完成后可以播放", 3000)
            return
            
        # 更新当前索引
        self.current_index = index

        # 重置时长比例关系
        self.duration_ratio = 1.0
        
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
        
        # 如果有缓存的准确时长，立即设置进度条范围
        if song["duration"] > 0:
            self.position_slider.setRange(0, song["duration"])
            self.time_label.setText(f"00:00 / {self.format_time(song['duration'])}")
            
            # 确保后续QMediaPlayer的duration变化不会覆盖已有的准确时长
            try:
                # 尝试断开所有信号处理程序
                self.player.durationChanged.disconnect()
            except TypeError:
                pass  # 如果没有连接，忽略错误
            
            # 连接自定义处理程序
            self.player.durationChanged.connect(lambda d: self.custom_duration_handler(d, song["duration"]))
        
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
                # 使用QTimer创建小延迟，避免可能的播放问题
                QTimer.singleShot(10, lambda: self.player.setPosition(0))
                QTimer.singleShot(20, lambda: self.player.play())
            elif self.play_mode == 2:  # 随机
                self.play_random_song()
    
    def custom_duration_handler(self, player_duration, cached_duration):
        """当我们已有准确时长时的自定义处理器"""
        # 只有当缓存的时长明显不同于player报告的时长时，才记录差异用于后续计算
        if abs(player_duration - cached_duration) > 1000:  # 差异超过1秒
            self.duration_ratio = player_duration / cached_duration if cached_duration > 0 else 1.0
            print(f"时长比例更新: {self.duration_ratio:.2f} (播放器/缓存)")
        
        # 保持进度条使用缓存的准确时长
        self.position_slider.setRange(0, cached_duration)
    
    def position_changed(self, position):
        """处理播放位置变化，确保进度条显示正确"""
        if self.current_index < 0 or self.current_index >= len(self.current_playlist):
            return
        
        # 如果锁定状态，跳过此次更新
        if self.position_update_lock:
            return
            
        song = self.current_playlist[self.current_index]
        cached_duration = song["duration"]
        player_duration = self.player.duration()
        
        # 确保进度条范围正确设置为缓存时长
        if cached_duration > 0 and self.position_slider.maximum() != cached_duration:
            self.position_slider.setRange(0, cached_duration)
        
        # 从播放器位置转换回进度条位置
        slider_position = position
        if player_duration > 0 and cached_duration > 0:
            # 计算播放器当前位置的百分比
            player_percentage = position / player_duration
            
            # 应用同样百分比到进度条时间线
            slider_position = int(player_percentage * cached_duration)
            
            # 更新进度条，但不触发额外信号
            self.position_slider.blockSignals(True)
            self.position_slider.setValue(slider_position)
            self.position_slider.blockSignals(False)
        else:
            # 无效时长情况的处理
            self.position_slider.setValue(position)
        
        # 更新时间标签 - 这里使用转换后的slider_position来显示当前时间
        current_time = self.format_time(slider_position)  # 使用进度条时间线的位置
        total_time = self.format_time(cached_duration if cached_duration > 0 else player_duration)
        self.time_label.setText(f"{current_time} / {total_time}")
    
    def duration_changed(self, duration):
        """处理持续时间变化，优先使用缓存的准确时长"""
        # 检查是否有正在播放的歌曲
        if self.current_index < 0 or self.current_index >= len(self.current_playlist):
            return
            
        song = self.current_playlist[self.current_index]
        cached_duration = song["duration"]
        
        # 如果缓存中有准确时长，优先使用缓存时长
        if cached_duration > 0:
            actual_duration = cached_duration
        else:
            # 否则使用QMediaPlayer提供的时长并更新缓存
            actual_duration = duration
            if duration > 0:
                song["duration"] = duration
                if song["path"]:
                    self.audio_durations[song["path"]] = duration
        
        # 更新进度条范围
        if actual_duration > 0:
            self.position_slider.setRange(0, actual_duration)
            
        # 更新时间标签
        current_position = self.player.position()
        current_time = self.format_time(current_position)
        total_time = self.format_time(actual_duration)
        self.time_label.setText(f"{current_time} / {total_time}")
    
    def set_position(self, position):
        """设置播放位置，修复时长不一致问题"""
        if self.current_index < 0 or self.current_index >= len(self.current_playlist):
            return
                
        # 激活锁定，防止反馈循环
        self.position_update_lock = True
        
        song = self.current_playlist[self.current_index]
        cached_duration = song["duration"]
        player_duration = self.player.duration()
        
        # 打印调试信息
        print(f"点击进度条位置: {position}ms / {cached_duration}ms ({position/cached_duration:.2%})")
        
        # 计算时长比例关系（仅在需要时更新）
        if cached_duration > 0 and player_duration > 0 and abs(player_duration - cached_duration) > 1000:
            self.duration_ratio = player_duration / cached_duration
            print(f"时长比例: {self.duration_ratio:.2f} (播放器/缓存)")
        
        # 根据时长比例计算实际播放位置
        if cached_duration > 0:
            # 计算点击位置在进度条上的百分比
            percentage = position / cached_duration
            # 转换为播放器时间线上的位置
            player_position = int(percentage * player_duration)
            
            print(f"设置播放位置: {player_position}ms / {player_duration}ms ({percentage:.2%})")
            self.player.setPosition(player_position)
        else:
            # 无缓存时长时的后备方案
            self.player.setPosition(position)
        
        # 设置定时器在短暂延迟后释放锁
        QTimer.singleShot(200, self.release_position_lock)

    def release_position_lock(self):
        """释放位置更新锁"""
        self.position_update_lock = False
        
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
            self.skip_seconds(-int(5*self.duration_ratio))
        elif event.key() == Qt.Key_Right:
            # 右箭头: 前进5秒
            self.skip_seconds(int(5*self.duration_ratio))
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
            if event.key() in [Qt.Key_Left, Qt.Key_Right]:
                # 直接在这里处理左右键，而不是传给keyPressEvent
                if event.key() == Qt.Key_Left:
                    self.skip_seconds(-5)
                elif event.key() == Qt.Key_Right:
                    self.skip_seconds(5)
                return True
            elif event.key() in [Qt.Key_Up, Qt.Key_Down]:
                # 将上下键事件传递给主窗口
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