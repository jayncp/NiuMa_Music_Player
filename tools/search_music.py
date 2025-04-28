import argparse
import requests
import urllib.parse
import json
import sys
import re
import os  # 添加os模块以获取脚本目录
from bs4 import BeautifulSoup

# 大模型API配置常量
LLM_API_URL = "https://tbnx.plus7.plus/v1/chat/completions"  # 替换为实际的大模型API地址
LLM_API_KEY = "sk-kMrK6zQMDPfwLP3xgrPrkIzLK7evhJgaWxm7t4SlpsaQ12SN"  # 替换为你的API密钥
LLM_MODEL_NAME = "deepseek-chat"  # 替换为你想使用的模型名称

def search_bilibili(query):
    """
    在Bilibili上搜索指定的查询内容，获取视频结果。
    """
    encoded_query = urllib.parse.quote(query)
    url = f"https://search.bilibili.com/all?keyword={encoded_query}"
    
    headers = {
        "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8,application/signed-exchange;v=b3;q=0.7",
        "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
        "Connection": "keep-alive",
        "Referer": "https://www.bilibili.com/"
    }
    
    print(f"正在向Bilibili发送搜索请求: {url}")
    
    try:
        response = requests.get(url, headers=headers)
        response.raise_for_status()
        print(f"搜索请求成功，HTTP状态码: {response.status_code}")
        return response.text
    except Exception as e:
        print(f"搜索出错: {e}")
        sys.exit(1)

def extract_videos(html_content):
    """
    从HTML内容中提取视频信息。
    """
    print("\n开始提取视频信息...")
    videos = []
    soup = BeautifulSoup(html_content, 'html.parser')
    
    # 首先检查是否有正常的HTML内容
    body_content = soup.find('body')
    if not body_content or len(str(body_content)) < 1000:
        print(f"警告: 返回的HTML内容异常简短，可能遇到了反爬机制")
        print(f"HTML长度: {len(html_content)} 字节")
        print(f"HTML片段: {html_content[:200]}...")
    
    # 保存原始页面内容以便调试
    try:
        with open("bilibili_search_result.html", "w", encoding="utf-8") as f:
            f.write(html_content)
        print("原始HTML已保存到bilibili_search_result.html文件")
    except:
        print("无法保存HTML文件")
    
    # 首先尝试从页面的JSON数据中提取视频信息
    # B站搜索页面通常在页面中嵌入了初始数据
    print("尝试从嵌入的JSON数据中提取视频信息...")
    json_data_pattern = r'window\.__INITIAL_STATE__\s*=\s*({.+?});\s*\(function'
    json_match = re.search(json_data_pattern, html_content)
    
    if json_match:
        try:
            json_data = json.loads(json_match.group(1))
            print("成功提取页面嵌入的JSON数据")
            
            # 视频数据可能在不同的位置
            video_list = None
            
            # 尝试各种可能的数据结构
            possible_paths = [
                ('flow', 'items'),  # 常见路径
                ('searchPage', 'items'),
                ('searchResult', 'result'),
                ('videoInfo', 'videoList')
            ]
            
            for parent, child in possible_paths:
                if parent in json_data and child in json_data[parent]:
                    video_list = json_data[parent][child]
                    print(f"在JSON路径 {parent}.{child} 中找到视频列表")
                    break
            
            # 搜索整个JSON查找包含视频数据的部分
            if not video_list:
                for key, value in json_data.items():
                    if isinstance(value, dict) and 'items' in value and isinstance(value['items'], list):
                        video_list = value['items']
                        print(f"在JSON路径 {key}.items 中找到视频列表")
                        break
            
            if video_list and isinstance(video_list, list):
                print(f"从JSON中找到 {len(video_list)} 个视频项目")
                for i, item in enumerate(video_list[:10]):  # 只处理前10个
                    # B站JSON结构可能有所不同，尝试所有可能的字段
                    title = item.get('title', '')
                    if not title and 'data' in item and isinstance(item['data'], dict):
                        title = item['data'].get('title', '')
                    
                    # 处理可能的HTML编码
                    if title and '<' in title:
                        title = BeautifulSoup(title, 'html.parser').get_text()
                    
                    bvid = item.get('bvid', '')
                    if not bvid:
                        bvid = item.get('bv_id', '')
                    if not bvid and 'data' in item and isinstance(item['data'], dict):
                        bvid = item['data'].get('bvid', '')
                    
                    duration = item.get('duration', '')
                    if not duration and 'data' in item and isinstance(item['data'], dict):
                        duration = item['data'].get('duration', '')
                    
                    # 格式化时长
                    if isinstance(duration, (int, float)):
                        minutes = int(duration) // 60
                        seconds = int(duration) % 60
                        duration = f"{minutes:02d}:{seconds:02d}"
                    
                    if title and bvid:
                        videos.append({
                            "title": title,
                            "duration": duration or "未知时长",
                            "bv_number": bvid
                        })
                        print(f"- 从JSON提取视频 {i+1}: {title} ({duration or '未知时长'}) - {bvid}")
                
                if videos:
                    return videos
        except json.JSONDecodeError as e:
            print(f"JSON解析失败: {e}")
        except Exception as e:
            print(f"从JSON提取数据时出错: {e}")
    
    # 如果JSON提取失败，尝试使用选择器提取
    # 尝试找到视频卡片 - 使用多种可能的选择器
    selectors = [
        'div.bili-video-card',                 # 新版可能的选择器
        'div.video-item',                      # 原始选择器
        'li.video-item',                       # 原始选择器
        'div.search-card',                     # 搜索结果卡片
        'div.bili-card',                       # 通用卡片
        'div.video-list-item',                 # 视频列表项
        'div.search-page-video-item',          # 搜索页视频项
        'div.result-item',                     # 结果项
        'div.ajax-render > div',               # AJAX渲染内容
        'div.video-card',                      # 通用视频卡片
        'div[data-v]',                         # Vue组件
    ]
    
    video_cards = []
    for selector in selectors:
        cards = soup.select(selector)
        if cards:
            print(f"使用选择器 '{selector}' 找到 {len(cards)} 个视频卡片")
            video_cards.extend(cards)
    
    print(f"总共找到 {len(video_cards)} 个视频卡片，将提取前10个")
    
    # 打印一些示例卡片HTML，帮助调试
    if video_cards and len(video_cards) > 0:
        sample_card = video_cards[0]
        print(f"\n示例卡片HTML片段:")
        print(str(sample_card)[:300] + "...\n")  # 只打印前300个字符
    
    for i, card in enumerate(video_cards):
        if i >= 10:  # 只获取前10个结果
            break
        
        try:
            # 试图定位标题 - 使用多种策略
            title = None
            
            # 尝试直接在卡片中找包含title属性的元素
            title_attrs = card.find_all(attrs={"title": True})
            for title_attr in title_attrs:
                if title_attr.get('title').strip():
                    title = title_attr.get('title').strip()
                    print(f"从title属性找到标题: {title}")
                    break
            
            # 尝试新版B站卡片中的标题选择器
            if not title:
                title_selectors = [
                    'a.bili-video-card__info--tit',  # 新版B站视频卡片标题
                    '.bili-video-card__info--tit',   # 类似选择器
                    'a.title',                       # 通用标题链接
                    'a.video-title',                 # 视频标题链接
                    'span.title',                    # 标题文本
                    'p.title',                       # 标题段落
                    'div.title',                     # 标题容器
                    'a[title]',                      # 带title属性的链接
                    'h3.bili-video-card__info--tit', # 标题标签
                    'h4.bili-video-card__info--tit', # 标题标签
                ]
                
                for selector in title_selectors:
                    title_elem = card.select_one(selector)
                    if title_elem:
                        # 尝试从title属性获取
                        if title_elem.has_attr('title'):
                            title = title_elem['title'].strip()
                        # 否则从文本内容获取
                        else:
                            title = title_elem.get_text().strip()
                        
                        if title:
                            print(f"使用选择器 '{selector}' 找到标题: {title}")
                            break
            
            # 尝试查找所有可能的链接并提取其文本内容或title属性
            if not title:
                all_links = card.find_all('a')
                for link in all_links:
                    # 检查链接是否指向视频
                    href = link.get('href', '')
                    if 'video' in href or 'BV' in href:
                        # 尝试从title属性获取
                        if link.has_attr('title'):
                            title = link['title'].strip()
                        # 否则从文本内容获取
                        else:
                            title = link.get_text().strip()
                        
                        if title:
                            print(f"从视频链接中提取标题: {title}")
                            break
            
            # 如果仍未找到标题，尝试使用更宽松的方法
            if not title:
                text_containers = card.find_all(['div', 'span', 'p', 'h3', 'h4', 'a'])
                for container in text_containers:
                    text = container.get_text().strip()
                    if len(text) > 10 and len(text) < 100:  # 合理的标题长度
                        title = text
                        print(f"从文本容器中提取可能的标题: {title[:30]}...")
                        break
            
            if not title:
                # 最后尝试使用URL中的信息
                url_elems = card.find_all('a', href=True)
                for url_elem in url_elems:
                    href = url_elem.get('href', '')
                    if 'video' in href and 'BV' in href:
                        match = re.search(r'BV\w+', href)
                        if match:
                            print(f"无法找到标题，使用BV号作为替代: {match.group(0)}")
                            title = f"视频 {match.group(0)}"
                            break
            
            if not title:
                title = "未知标题"
            
            # 尝试从URL中找到BV号
            bv_number = ""
            url_elems = card.find_all('a', href=True)
            for url_elem in url_elems:
                href = url_elem.get('href', '')
                match = re.search(r'BV\w+', href)
                if match:
                    bv_number = match.group(0)
                    break
            
            # 如果没找到BV号，尝试从卡片上的其他属性找
            if not bv_number:
                for attr in ['data-aid', 'data-id', 'data-video-id']:
                    if card.has_attr(attr):
                        print(f"找到视频ID属性: {attr}={card[attr]}")
            
            # 尝试找到视频时长
            duration = "未知时长"
            duration_selectors = [
                'span.length', 'span.duration', 'span.video-duration',
                'span.time', 'span.bili-video-card__stats__duration',
                '.bili-video-card__stats__duration',
                'div.duration', 'span.bili-video-card__stats--duration'
            ]
            
            for selector in duration_selectors:
                duration_elem = card.select_one(selector)
                if duration_elem:
                    duration = duration_elem.get_text().strip()
                    break
            
            if bv_number:  # 只添加有BV号的视频
                videos.append({
                    "title": title,
                    "duration": duration,
                    "bv_number": bv_number
                })
                
                print(f"- 提取视频 {i+1}: {title} ({duration}) - {bv_number}")
        except Exception as e:
            print(f"提取视频 {i+1} 信息出错: {e}")
            import traceback
            traceback.print_exc()
    
    # 如果还是没找到任何视频，尝试使用纯正则表达式
    if not videos:
        print("无法使用DOM解析提取视频，尝试使用纯正则表达式...")
        
        # 尝试匹配包含BV号、标题和时长的模式
        video_patterns = [
            # 匹配a标签中的标题和href中的BV号
            r'<a[^>]*href="[^"]*?(BV\w+)"[^>]*title="([^"]+)"[^>]*>',
            # 匹配包含BV号和标题的更宽松模式
            r'href="//www\.bilibili\.com/video/(BV\w+)[^"]*"[^>]*>([^<]+)</a>',
            # 匹配视频卡片结构
            r'data-text="([^"]*)"[^>]*data-id="(BV\w+)"',
        ]
        
        for pattern in video_patterns:
            matches = re.findall(pattern, html_content)
            
            if matches:
                print(f"使用正则表达式 '{pattern}' 找到 {len(matches)} 个匹配")
                
                for i, match in enumerate(matches[:10]):
                    if len(match) >= 2:
                        if "BV" in match[0]:  # 如果BV号在第一个位置
                            bv, title = match[0], match[1]
                        else:  # 否则假设标题在第一个位置，BV号在第二个位置
                            title, bv = match[0], match[1]
                        
                        # 移除标题中的HTML标签
                        title = re.sub(r'<[^>]+>', '', title).strip()
                        
                        videos.append({
                            "title": title,
                            "duration": "未知时长",
                            "bv_number": bv
                        })
                        print(f"- 通过正则表达式提取视频 {i+1}: {title} - {bv}")
                
                if videos:
                    break
        
        # 最后的特别尝试：从JSON字符串中提取
        if not videos:
            # 尝试查找页面中的JSON数据块
            all_script_tags = re.findall(r'<script[^>]*>(.*?)</script>', html_content, re.DOTALL)
            for script in all_script_tags:
                # 寻找包含视频数据的JSON对象
                json_objects = re.findall(r'\{.*?"title":\s*"([^"]+)".*?"bvid":\s*"(BV\w+)".*?\}', script)
                if json_objects:
                    print(f"在脚本标签中找到 {len(json_objects)} 个视频数据")
                    for i, (title, bv) in enumerate(json_objects[:10]):
                        videos.append({
                            "title": title,
                            "duration": "未知时长",
                            "bv_number": bv
                        })
                        print(f"- 从脚本标签提取视频 {i+1}: {title} - {bv}")
                    if videos:
                        break
    
    return videos

def send_to_llm(videos, song_name, artist_name):
    """
    将视频信息发送给大模型，让其选择最合适的视频。
    """
    if not videos:
        print("没有视频信息可发送给大模型")
        return None
    
    print(f"\n正在将视频信息发送至大模型 ({LLM_MODEL_NAME})")
    print(f"使用API: {LLM_API_URL}")
    
    # 构建发送给大模型的提示词
    prompt = f"""
我正在寻找歌曲名为"{song_name}"{' 演唱者为"' + artist_name + '"' if artist_name else ' 原唱版本'}的完整视频。
以下是从Bilibili搜索到的前10个结果，请选择最可能是完整歌曲视频的一个，并只返回其BV号。

视频列表:
"""

    # 添加视频信息到提示词
    for i, video in enumerate(videos):
        prompt += f"{i+1}. 标题: {video['title']}, 时长: {video['duration']}, BV号: {video['bv_number']}\n"
    
    prompt += """
请分析这些视频标题和时长，选择最可能是上述歌手的完整歌曲视频（而非片段、翻唱、现场版等）。
如果有多个满足条件的，则再根据标题判断可能音质最好的一个（例如：无损，录音棚等关键字）。
只需返回最适合的视频对应的BV号，无需其他解释。
"""
    
    print("发送的提示词:")
    print("-" * 40)
    print(prompt)
    print("-" * 40)
    
    try:
        # 实际调用大模型API
        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {LLM_API_KEY}"
        }
        
        data = {
            "model": LLM_MODEL_NAME,
            "messages": [
                {"role": "system", "content": "你是一个专业的音乐视频选择助手，擅长从标题和时长分析哪个视频最可能是指定歌手的完整歌曲。"},
                {"role": "user", "content": prompt}
            ],
            "temperature": 0.3
        }
        
        print("正在发送API请求...")
        
        response = requests.post(LLM_API_URL, headers=headers, json=data)
        response.raise_for_status()
        response_json = response.json()
        llm_response = response_json.get("choices", [{}])[0].get("message", {}).get("content", "")
        
        print(f"大模型响应: {llm_response}")
        
        # 提取BV号
        bv_pattern = re.compile(r'BV\w+')
        bv_matches = bv_pattern.findall(llm_response)
        
        if bv_matches:
            return bv_matches[0]
        else:
            print("无法从大模型响应中提取BV号")
            return None
    except Exception as e:
        print(f"调用大模型API出错: {e}")

def main():
    # 获取脚本所在目录
    script_dir = os.path.dirname(os.path.abspath(__file__))
    
    parser = argparse.ArgumentParser(description="在Bilibili上搜索歌曲")
    parser.add_argument("input", help="歌曲名称或NAMELIST以批量处理")
    parser.add_argument("--artist", help="歌手名称（可选，当input不为NAMELIST时使用）")
    parser.epilog = "使用示例:  python search_music.py 烟雨行舟 --artist 司南 或者  python search_music.py NAMELIST"
    
    # 捕获参数解析错误，显示帮助信息而不是错误
    try:
        args = parser.parse_args()
    except SystemExit:
        # 当发生参数错误时，显示帮助信息并退出
        parser.print_help()
        sys.exit(1)

    if args.input.upper() == "NAMELIST":
        # 从NAMELIST.txt读取批量处理
        namelist_path = os.path.join(script_dir, "NAMELIST.txt")
        bvlist_path = os.path.join(script_dir, "BVLIST.txt")
        
        print("\n" + "="*60)
        print("Bilibili歌曲批量搜索工具")
        print("="*60)
        print(f"配置信息:")
        print(f"- 大模型API: {LLM_API_URL}")
        print(f"- 大模型: {LLM_MODEL_NAME}")
        print(f"- 输入文件: {namelist_path}")
        print(f"- 输出文件: {bvlist_path}")
        print("="*60 + "\n")
        
        try:
            with open(namelist_path, "r", encoding="utf-8") as f:
                song_list = f.readlines()
            
            print(f"共读取 {len(song_list)} 首歌曲")
            
            bv_results = []
            
            for i, line in enumerate(song_list):
                line = line.strip()
                if not line:
                    continue
                    
                parts = line.split(",")
                song_name = parts[0].strip()
                artist_name = parts[1].strip() if len(parts) > 1 and parts[1].strip() else None
                
                print(f"\n处理第 {i+1}/{len(song_list)} 首歌曲: {song_name} - {artist_name if artist_name else '原唱'}")
                
                # 使用现有函数搜索和选择视频
                query = f"{song_name} {artist_name}" if artist_name else f"{song_name} 原唱"
                print(f"构建搜索查询: {query}")
                
                html_content = search_bilibili(query)
                videos = extract_videos(html_content)
                
                if not videos:
                    print(f"未找到歌曲 '{song_name}' 的视频，跳过")
                    bv_results.append(f"NOT_FOUND_{song_name}")
                    continue
                    
                selected_bv = send_to_llm(videos, song_name, artist_name)
                
                if selected_bv:
                    print(f"已找到歌曲 '{song_name}' 的BV号: {selected_bv}")
                    bv_results.append(selected_bv)
                else:
                    print(f"无法为歌曲 '{song_name}' 选择合适的视频，跳过")
                    bv_results.append(f"NO_SELECTION_{song_name}")
            
            # 将结果写入BVLIST.txt
            with open(bvlist_path, "w", encoding="utf-8") as f:
                for bv in bv_results:
                    f.write(f"{bv}\n")
                    
            print(f"\n处理完成! {len(bv_results)} 个BV号已写入 {bvlist_path}")
            
        except Exception as e:
            print(f"批量处理过程中出错: {e}")
            import traceback
            traceback.print_exc()
            sys.exit(1)
    else:
        # 原来的单首歌曲搜索逻辑
        song_name = args.input
        artist_name = args.artist
        
        print("\n" + "="*60)
        print("Bilibili歌曲搜索工具")
        print("="*60)
        print(f"配置信息:")
        print(f"- 大模型API: {LLM_API_URL}")
        print(f"- 大模型: {LLM_MODEL_NAME}")
        print(f"- 搜索歌曲: {song_name}")
        print(f"- 指定歌手: {artist_name if artist_name else '未指定（将搜索原唱）'}")
        print("="*60 + "\n")
        
        # 构建搜索查询
        if artist_name:
            query = f"{song_name} {artist_name}"
        else:
            query = f"{song_name} 原唱"
        
        print(f"构建搜索查询: {query}")
        
        # 在Bilibili上搜索
        html_content = search_bilibili(query)
        
        # 提取视频信息
        videos = extract_videos(html_content)
        
        if not videos:
            print("未找到视频。")
            sys.exit(1)
        
        print(f"\n成功提取 {len(videos)} 个视频信息")
        
        # 显示找到的视频
        print("\n提取到的视频列表:")
        print("-" * 80)
        for i, video in enumerate(videos):
            print(f"{i+1}. {video['title']} ({video['duration']}) - {video['bv_number']}")
        print("-" * 80)
        
        # 发送给大模型选择最佳视频
        selected_bv = send_to_llm(videos, song_name, artist_name)
        
        if selected_bv:
            print(f"\n分析完成！")
            print(f"大模型选择的BV号: {selected_bv}")
            # 只输出BV号，方便程序获取
            print(f"\n最终结果：{selected_bv}")
        else:
            print("无法选择合适的视频。")
            sys.exit(1)

if __name__ == "__main__":
    main()