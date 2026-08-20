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
        # og:description 会被 X 截断，只作为最后兜底。
        # 第三方镜像站偶发不稳定，多留几个通道 + 单个服务内部重试。
        services = [
            self._fetch_fxtwitter_api,
            self._fetch_vxtwitter_api,
            self._fetch_vxtwitter,
            self._fetch_fxtwitter,
            self._fetch_oembed,
        ]

        errors = []
        for service in services:
            try:
                result = service(url)
                if result and result.get('text'):
                    print(f"  ✓ 备用方案成功（{result.get('source')}）")
                    return result
            except Exception as e:
                errors.append(f"{getattr(service, '__name__', 'service')}: {e}")
                print(f"  ✗ 服务失败: {e}")
                continue

        # 所有备用通道都失败：给出汇总信息，便于区分「网络不通」与「代码问题」
        summary = "；".join(errors[:6]) if errors else "无可用通道"
        raise Exception(f"所有备用服务均失败（可能是网络受限，无法访问 x.com 及其镜像服务）: {summary}")
    
    def _fetch_fxtwitter_api(self, url: str) -> dict:
        """
        使用 fxtwitter JSON API 抓取推文

        相比 og:description，JSON API 能拿到：
        - 完整推文正文（含 note tweet 长推文）
        - X Article 长文的全部段落（article.content.blocks）
        - 全部媒体资源
        """
        handle, status_id = self._get_url_parts(url)
        if not handle:
            return None
        api_url = f"https://api.fxtwitter.com/{handle}/status/{status_id}"
        print(f"  尝试 fxtwitter API: {api_url}")

        headers = {'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36'}
        response = self._get_with_retry(api_url, headers=headers)
        result = self._parse_meta_json(response.json())
        if result:
            result['source'] = 'fxtwitter-api'
            print(f"  ✓ fxtwitter API 成功，正文 {len(result['text'])} 字符")
            return result
        return None

    def _parse_meta_json(self, data: dict) -> dict:
        """通用解析 fxtwitter / vxtwitter 风格的 JSON 推文结构"""
        tweet = data.get('tweet') or {}
        if not tweet:
            return None

        parts = []
        title = ''
        tweet_text = (tweet.get('text') or '').strip()
        tweet_text = re.sub(r'\s*https://t\.co/\w+\s*$', '', tweet_text).strip()
        if tweet_text:
            parts.append(tweet_text)

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
        if not text:
            return None

        images, videos = [], []
        cover = ((article.get('cover_media') or {}).get('media_info') or {}).get('original_img_url')
        if cover and cover not in images:
            images.append(cover)
        for entity in (article.get('media_entities') or []):
            img = (entity.get('media_info') or {}).get('original_img_url')
            if img and img not in images:
                images.append(img)
        for item in (tweet.get('media') or {}).get('all') or []:
            item_url = item.get('url')
            if not item_url:
                continue
            if item.get('type') == 'photo' and item_url not in images:
                images.append(item_url)
            elif item.get('type') in ('video', 'gif') and item_url not in videos:
                videos.append(item_url)

        return {
            'text': text,
            'title': title,
            'author': (tweet.get('author') or {}).get('name', ''),
            'created_at': tweet.get('created_at', ''),
            'lang': tweet.get('lang', ''),
            'images': images,
            'videos': videos,
        }

    def _get_url_parts(self, url: str):
        """从 x/twitter 链接解析出 handle 与 status_id"""
        m = re.search(r'(?:x\.com|twitter\.com)/([^/]+)/status/(\d+)', url)
        return (m.group(1), m.group(2)) if m else (None, None)

    def _fetch_vxtwitter_api(self, url: str) -> dict:
        """使用 api.vxtwitter.com JSON 接口（结构同 fxtwitter）"""
        handle, status_id = self._get_url_parts(url)
        if not handle:
            return None
        api_url = f"https://api.vxtwitter.com/{handle}/status/{status_id}"
        print(f"  尝试 vxtwitter API: {api_url}")

        headers = {'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36'}
        response = self._get_with_retry(api_url, headers=headers)
        result = self._parse_meta_json(response.json())
        if result:
            result['source'] = 'vxtwitter-api'
            print(f"  ✓ vxtwitter API 成功，正文 {len(result['text'])} 字符")
            return result
        return None

    def _fetch_oembed(self, url: str) -> dict:
        """使用 Twitter 官方 oEmbed 接口兜底（能拿到推文简介与作者）"""
        oembed_url = f"https://publish.twitter.com/oembed?url={url}"
        print(f"  尝试官方 oEmbed: publish.twitter.com/oembed")
        headers = {'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36'}
        try:
            response = requests.get(oembed_url, headers=headers, timeout=20)
            response.raise_for_status()
            data = response.json()
        except Exception:
            return None

        # oEmbed 返回 html / title / author_name，抽出纯文本作为最后兜底
        html = data.get('html') or ''
        author = data.get('author_name') or ''
        soup = BeautifulSoup(html, 'lxml')
        text = soup.get_text('\n', strip=True)
        # oEmbed 会带「在 X 上查看/查看动态」等尾注，尽量只保留推文正文
        for marker in ('在 X 上查看', 'View on X', '查看动态', '分享', 'Follow'):
            if marker in text:
                text = text.split(marker)[0].strip()
        if not text:
            return None
        text = re.sub(r'\n{3,}', '\n\n', text).strip()
        if len(text) < 20:  # 太短说明只有按钮文字，不可用
            return None
        print(f"  ✓ 官方 oEmbed 兜底成功，正文 {len(text)} 字符")
        return {
            'text': text,
            'title': data.get('title') or '',
            'author': author,
            'created_at': '',
            'lang': '',
            'images': [],
            'videos': [],
            'source': 'oembed',
        }

    def _get_with_retry(self, url: str, headers: dict, tries: int = 3, timeout: int = 30):
        """带重试的 GET：镜像站偶发 SSL/连接被断，多试几次更稳"""
        import time as _time
        last_exc = None
        for i in range(tries):
            try:
                return requests.get(url, headers=headers, timeout=timeout)
            except Exception as e:  # noqa: BLE001
                last_exc = e
                if i < tries - 1:
                    print(f"  （第 {i + 1} 次失败: {e}，重试…）")
                    _time.sleep(1.5)
        raise last_exc

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
