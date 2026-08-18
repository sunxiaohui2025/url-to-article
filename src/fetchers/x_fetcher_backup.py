"""X 平台备用抓取器 - 使用第三方服务"""
import requests
from bs4 import BeautifulSoup
import re


class XFetcherBackup:
    """使用 vxtwitter 等服务作为备用方案"""
    
    def fetch(self, url: str) -> dict:
        """
        使用备用服务抓取推文
        
        Args:
            url: X 推文链接
            
        Returns:
            dict: 包含推文信息
        """
        print(f"使用备用方案抓取: {url}")
        
        # 尝试多个备用服务：优先 JSON API（可拿到长文全文），
        # og:description 会被 X 截断，只作为最后兜底
        services = [
            self._fetch_fxtwitter_api,
            self._fetch_vxtwitter,
            self._fetch_fxtwitter,
        ]

        for service in services:
            try:
                result = service(url)
                if result and result.get('text'):
                    return result
            except Exception as e:
                print(f"  ✗ 服务失败: {e}")
                continue
        
        raise Exception("所有备用服务均失败")
    
    def _fetch_fxtwitter_api(self, url: str) -> dict:
        """
        使用 fxtwitter JSON API 抓取推文

        相比 og:description，JSON API 能拿到：
        - 完整推文正文（含 note tweet 长推文）
        - X Article 长文的全部段落（article.content.blocks）
        - 全部媒体资源
        """
        match = re.search(
            r'(?:x\.com|twitter\.com)/([^/]+)/status/(\d+)', url
        )
        if not match:
            return None

        handle, status_id = match.group(1), match.group(2)
        api_url = f"https://api.fxtwitter.com/{handle}/status/{status_id}"

        print(f"  尝试 fxtwitter API: {api_url}")

        headers = {
            'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36'
        }

        response = requests.get(api_url, headers=headers, timeout=30)
        response.raise_for_status()

        data = response.json()
        tweet = data.get('tweet') or {}
        if not tweet:
            return None

        parts = []
        title = ''

        # 1. 推文正文（去掉尾部的 t.co 短链）
        tweet_text = (tweet.get('text') or '').strip()
        tweet_text = re.sub(r'\s*https://t\.co/\w+\s*$', '', tweet_text).strip()
        if tweet_text:
            parts.append(tweet_text)

        # 2. X Article 长文全文
        article = tweet.get('article') or {}
        if article:
            title = (article.get('title') or '').strip()
            if title:
                parts.append(title)

            blocks = ((article.get('content') or {}).get('blocks')) or []
            block_texts = [
                (b.get('text') or '').strip()
                for b in blocks
                if (b.get('text') or '').strip()
            ]
            if block_texts:
                parts.extend(block_texts)
                print(f"  ✓ 提取到长文正文 {len(block_texts)} 个段落")
            elif article.get('preview_text'):
                parts.append(article['preview_text'].strip())

        text = "\n\n".join(parts).strip()

        # 3. 媒体资源
        images = []
        videos = []

        cover = (article.get('cover_media') or {}) if article else {}
        cover_url = ((cover.get('media_info') or {}).get('original_img_url'))
        if cover_url:
            images.append(cover_url)

        for entity in (article.get('media_entities') or []) if article else []:
            media_info = entity.get('media_info') or {}
            img = media_info.get('original_img_url')
            if img and img not in images:
                images.append(img)

        media = tweet.get('media') or {}
        for item in (media.get('all') or []):
            item_type = item.get('type')
            item_url = item.get('url')
            if not item_url:
                continue
            if item_type == 'photo' and item_url not in images:
                images.append(item_url)
            elif item_type in ('video', 'gif') and item_url not in videos:
                videos.append(item_url)

        if text:
            print(f"  ✓ fxtwitter API 成功，正文 {len(text)} 字符")
            return {
                'text': text,
                'title': title,
                'author': (tweet.get('author') or {}).get('name', ''),
                'created_at': tweet.get('created_at', ''),
                'lang': tweet.get('lang', ''),
                'images': images,
                'videos': videos,
                'source': 'fxtwitter-api'
            }

        return None

    def _fetch_vxtwitter(self, url: str) -> dict:
        """使用 vxtwitter.com"""
        # 将 x.com 替换为 vxtwitter.com
        vx_url = re.sub(r'(https?://)(?:x\.com|twitter\.com)', r'\1vxtwitter.com', url)
        
        print(f"  尝试 vxtwitter: {vx_url}")
        
        headers = {
            'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36'
        }
        
        response = requests.get(vx_url, headers=headers, timeout=30)
        response.raise_for_status()
        
        soup = BeautifulSoup(response.text, 'lxml')
        
        # 提取 Open Graph 元数据
        og_description = soup.find('meta', property='og:description')
        og_image = soup.find('meta', property='og:image')
        
        text = og_description['content'] if og_description else ""
        image = og_image['content'] if og_image else ""
        
        if text:
            print(f"  ✓ vxtwitter 成功")
            return {
                'text': text,
                'images': [image] if image else [],
                'videos': [],
                'source': 'vxtwitter'
            }
        
        return None
    
    def _fetch_fxtwitter(self, url: str) -> dict:
        """使用 fxtwitter.com"""
        fx_url = re.sub(r'(https?://)(?:x\.com|twitter\.com)', r'\1fxtwitter.com', url)
        
        print(f"  尝试 fxtwitter: {fx_url}")
        
        headers = {
            'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36'
        }
        
        response = requests.get(fx_url, headers=headers, timeout=30)
        response.raise_for_status()
        
        soup = BeautifulSoup(response.text, 'lxml')
        
        # 提取内容
        og_description = soup.find('meta', property='og:description')
        og_image = soup.find('meta', property='og:image')
        
        text = og_description['content'] if og_description else ""
        image = og_image['content'] if og_image else ""
        
        if text:
            print(f"  ✓ fxtwitter 成功")
            return {
                'text': text,
                'images': [image] if image else [],
                'videos': [],
                'source': 'fxtwitter'
            }
        
        return None
