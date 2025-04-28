import os
import argparse
import subprocess
import sys
import json
import requests
import time

# AI模型配置
AI_MODELS = {
    "LLM": {
        "api_url": "https://tbnx.plus7.plus/v1/chat/completions",
        "api_key": "sk-kMrK6zQMDPfwLP3xgrPrkIzLK7evhJgaWxm7t4SlpsaQ12SN",  # 替换为您的API密钥
        "model_name": "deepseek-chat",
        "headers": lambda key: {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {key}"
        },
        "payload": lambda prompt: {
            "model": "deepseek-chat",
            "messages": [{"role": "user", "content": prompt}],
            "temperature": 0.7,
            "max_tokens": 150
        },
        "extract_result": lambda response: response.json()["choices"][0]["message"]["content"]
    }
    # 可以添加更多AI模型配置
}

def check_yt_dlp_installed():
    """检查是否安装了yt-dlp，如果没有则尝试安装"""
    try:
        subprocess.run(['yt-dlp', '--version'], stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        return True
    except FileNotFoundError:
        print("yt-dlp未安装，正在尝试安装...")
        try:
            subprocess.run([sys.executable, '-m', 'pip', 'install', 'yt-dlp'], check=True)
            return True
        except subprocess.CalledProcessError:
            print("安装yt-dlp失败。请手动安装：pip install yt-dlp")
            return False

def get_script_dir():
    """获取脚本所在目录"""
    return os.path.dirname(os.path.abspath(__file__))

def ensure_download_dir():
    """确保下载目录存在"""
    script_dir = get_script_dir()
    download_dir = os.path.join(script_dir, "../music_download")
    
    if not os.path.exists(download_dir):
        os.makedirs(download_dir)
        print(f"创建下载目录: {download_dir}")
    
    return download_dir

def get_ffmpeg_path():
    """获取本地FFmpeg路径，无论脚本是直接运行还是被导入"""
    # 使用__file__获取当前模块的绝对路径，无论是直接运行还是被导入
    current_file = os.path.abspath(__file__)
    current_dir = os.path.dirname(current_file)
    
    # 尝试不同的可能路径
    possible_paths = [
        # 1. 当前脚本所在目录中的bin目录
        os.path.join(current_dir, "bin"),
        # 2. 项目根目录中的bin目录（假设当前脚本在项目的某个子目录中）
        os.path.join(current_dir, "..", "bin"),
        # 3. 环境变量中指定的路径
        os.environ.get("FFMPEG_PATH", "")
    ]
    
    # 根据操作系统确定可执行文件名
    if sys.platform.startswith('win'):
        ffmpeg_exe = "ffmpeg.exe"
        platform_dir = "windows"
    elif sys.platform.startswith('darwin'):  # macOS
        ffmpeg_exe = "ffmpeg"
        platform_dir = "macos"
    else:  # Linux和其他
        ffmpeg_exe = "ffmpeg"
        platform_dir = "linux"
    
    # 检查所有可能的路径
    for base_path in possible_paths:
        if not base_path:
            continue
            
        # 检查特定平台目录下的ffmpeg
        platform_path = os.path.join(base_path, platform_dir, ffmpeg_exe)
        if os.path.exists(platform_path):
            return os.path.dirname(platform_path)
            
        # 也检查直接在bin目录下的ffmpeg
        direct_path = os.path.join(base_path, ffmpeg_exe)
        if os.path.exists(direct_path):
            return os.path.dirname(direct_path)
    
    # 如果找不到本地版本，返回None
    return None

def check_system_ffmpeg():
    """检查系统是否安装了ffmpeg"""
    try:
        result = subprocess.run(['ffmpeg', '-version'], stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        return result.returncode == 0
    except FileNotFoundError:
        return False

def download_bilibili_audio(bv_number, download_dir):
    """使用yt-dlp从Bilibili视频下载音频，按照优先级尝试不同的下载策略"""
    if not check_yt_dlp_installed():
        return None
    
    url = f"https://www.bilibili.com/video/{bv_number}"
    print(f"正在从以下地址下载音频: {url}")
    
    # 基本的yt-dlp命令参数
    base_cmd = [
        'yt-dlp', 
        '-x',  # 提取音频
        '--print', 'after_move:filepath',  # 打印处理后的文件路径
        '-o', f'{download_dir}/%(title)s-%(id)s.%(ext)s',  # 设置输出路径和文件名格式
    ]
    
    # 环境变量
    env = os.environ.copy()
    
    # 1. 首先尝试使用系统的ffmpeg
    if check_system_ffmpeg():
        print("尝试使用系统安装的FFmpeg...")
        try:
            cmd = base_cmd + ['--audio-format', 'mp3', '--audio-quality', '0', url]
            result = subprocess.run(cmd, check=True, text=True, capture_output=True, env=env)
            file_path = result.stdout.strip()
            print(f"成功使用系统FFmpeg下载 {bv_number} 到 {file_path}")
            return file_path
        except subprocess.CalledProcessError as e:
            print(f"使用系统FFmpeg下载失败: {e}")
    else:
        print("系统未安装FFmpeg")
    
    # 2. 如果系统的ffmpeg失败，尝试使用本地ffmpeg
    local_ffmpeg_path = get_ffmpeg_path()
    if local_ffmpeg_path:
        print(f"尝试使用本地FFmpeg: {local_ffmpeg_path}...")
        
        # 设置本地ffmpeg的执行权限
        if not sys.platform.startswith('win'):
            for exe in ["ffmpeg", "ffprobe"]:
                exe_path = os.path.join(local_ffmpeg_path, exe)
                if os.path.exists(exe_path):
                    try:
                        os.chmod(exe_path, 0o755)
                    except Exception as e:
                        print(f"警告：无法设置{exe}的执行权限: {e}")
        
        # 使用本地ffmpeg路径
        try:
            cmd = base_cmd + [
                '--ffmpeg-location', local_ffmpeg_path,
                '--audio-format', 'mp3', 
                '--audio-quality', '0', 
                url
            ]
            result = subprocess.run(cmd, check=True, text=True, capture_output=True, env=env)
            file_path = result.stdout.strip()
            print(f"成功使用本地FFmpeg下载 {bv_number} 到 {file_path}")
            return file_path
        except subprocess.CalledProcessError as e:
            print(f"使用本地FFmpeg下载失败: {e}")
    else:
        print("未找到本地FFmpeg")
    
    # 3. 如果前两种方法都失败，尝试不指定音频格式的下载
    print("尝试不转换格式直接下载...")
    try:
        cmd = base_cmd + ['--audio-quality', '0', url]
        result = subprocess.run(cmd, check=True, text=True, capture_output=True, env=env)
        file_path = result.stdout.strip()
        print(f"成功下载 {bv_number} 到 {file_path} (未转换格式)")
        return file_path
    except subprocess.CalledProcessError as e:
        print(f"所有下载方法均失败: {e}")
        return None

def read_bv_list(list_file):
    """从文本文件中读取BV号列表"""
    bv_list = []
    try:
        with open(list_file, 'r', encoding='utf-8') as file:
            for line in file:
                # 去除空白并跳过空行
                bv = line.strip()
                if bv:
                    bv_list.append(bv)
        return bv_list
    except Exception as e:
        print(f"读取BV列表文件时出错: {e}")
        return []

def call_ai_for_rename(file_path, ai_name):
    """调用AI模型来获取歌曲名称和歌手信息"""
    if ai_name not in AI_MODELS:
        print(f"错误: 未配置的AI模型 '{ai_name}'")
        return None
    
    ai_config = AI_MODELS[ai_name]
    api_key = ai_config["api_key"]
    
    if api_key == "YOUR_OPENAI_API_KEY" or api_key == "YOUR_ANTHROPIC_API_KEY":
        print(f"错误: 请在脚本中设置您的{ai_name} API密钥")
        return None
    
    # 从文件名中提取现有信息
    file_name = os.path.basename(file_path)
    prompt = f"""
我有一个从哔哩哔哩(Bilibili)下载的音频文件，文件名为：{file_name}
请分析这个文件名，并提取出歌曲名称和歌手名称，然后去除歌曲名中的修饰词和描述性词语。
如果歌曲名称或歌手名称中有多个部分需要隔断，请使用下划线(_)。
请以JSON格式返回，格式为：{{"song": "歌曲名称", "artist": "歌手名称"}}
如果无法确定歌手，请将artist设为"Unknown"。
    """
    
    try:
        headers = ai_config["headers"](api_key)
        payload = ai_config["payload"](prompt)
        
        response = requests.post(
            ai_config["api_url"],
            headers=headers,
            data=json.dumps(payload)
        )
        
        if response.status_code == 200:
            result_text = ai_config["extract_result"](response)
            
            # 尝试从结果中提取JSON
            try:
                # 找到JSON部分
                json_start = result_text.find('{')
                json_end = result_text.rfind('}') + 1
                if json_start >= 0 and json_end > json_start:
                    json_str = result_text[json_start:json_end]
                    result = json.loads(json_str)
                    return result
                else:
                    print(f"无法从AI响应中提取JSON: {result_text}")
                    return None
            except json.JSONDecodeError as e:
                print(f"解析AI响应JSON时出错: {e}")
                print(f"AI响应: {result_text}")
                return None
        else:
            print(f"调用AI API时出错: {response.status_code}")
            print(f"响应: {response.text}")
            return None
    except Exception as e:
        print(f"调用AI服务时发生错误: {e}")
        return None

def rename_file_with_ai(file_path, ai_name):
    """使用AI获取信息后重命名文件"""
    if not os.path.exists(file_path):
        print(f"错误: 文件不存在 {file_path}")
        return file_path
    
    # 调用AI获取歌曲信息
    print(f"正在使用{ai_name}分析文件...")
    song_info = call_ai_for_rename(file_path, ai_name)
    
    if not song_info:
        print("无法获取歌曲信息，保留原文件名")
        return file_path
    
    # 获取文件目录和扩展名
    dir_name = os.path.dirname(file_path)
    _, ext = os.path.splitext(file_path)
    
    # 创建新文件名
    song_name = song_info.get("song", "Unknown").replace(" ", "_")
    artist_name = song_info.get("artist", "Unknown").replace(" ", "_")
    new_name = f"{song_name}--{artist_name}{ext}"
    new_path = os.path.join(dir_name, new_name)
    
    # 重命名文件
    try:
        os.rename(file_path, new_path)
        print(f"文件已重命名: {new_name}")
        return new_path
    except Exception as e:
        print(f"重命名文件时发生错误: {e}")
        return file_path

def batch_download(bv_list, download_dir, ai_name=None):
    """批量下载多个BV号对应的音频"""
    total = len(bv_list)
    print(f"共有 {total} 个视频等待下载")
    
    for i, bv in enumerate(bv_list, 1):
        print(f"[{i}/{total}] 开始下载 {bv}")
        file_path = download_bilibili_audio(bv, download_dir)
        
        # 如果成功下载并指定了AI模型，则进行重命名
        if file_path and ai_name:
            rename_file_with_ai(file_path, ai_name)
            # 下载之间添加延迟，避免API限制
            if i < total:
                time.sleep(2)  

def main():
    parser = argparse.ArgumentParser(description='从Bilibili视频下载音频')
    parser.add_argument('bv', help='视频的BV号 (例如: BV1es41127Fd) 或 BVLIST (从BVLIST.txt读取)')
    parser.add_argument('-AINAME', help='用于重命名文件的AI模型名称', choices=AI_MODELS.keys())
    parser.epilog = "使用示例: python auto_download_bilibili.py BV1es41127Fd -AINAME LLM"

    # 捕获参数解析错误，显示帮助信息而不是错误
    try:
        args = parser.parse_args()
    except SystemExit:
        # 当发生参数错误时，显示帮助信息并退出
        parser.print_help()
        sys.exit(1)
    
    # 确保下载目录存在
    download_dir = ensure_download_dir()
    
    if args.bv == "BVLIST":
        # 从文件中读取BV号列表
        list_file = os.path.join(get_script_dir(), "BVLIST.txt")
        if not os.path.exists(list_file):
            print(f"错误: 找不到文件 {list_file}")
            return
        
        bv_list = read_bv_list(list_file)
        if bv_list:
            batch_download(bv_list, download_dir, args.AINAME)
        else:
            print("BV列表为空或读取失败")
    else:
        # 下载单个BV号
        file_path = download_bilibili_audio(args.bv, download_dir)
        # 如果成功下载并指定了AI模型，则进行重命名
        if file_path and args.AINAME:
            rename_file_with_ai(file_path, args.AINAME)

if __name__ == "__main__":
    main()