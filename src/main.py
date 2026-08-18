"""主入口文件 - 抓取与解析引擎

本 skill 只负责「抓取页面 → 提取内容 → 保存原始素材」。
翻译、推文串整合、完整文章 HTML、一页纸解读、Banner 等 LLM 任务
全部由宿主 agent 参照 prompts/ 目录下的模板直接完成，
skill 内部不直连任何大模型（不硬编码/提交任何模型配置与密钥）。
"""
from src.fetchers.x_fetcher import XFetcher
from src.fetchers.x_fetcher_backup import XFetcherBackup
from src.fetchers.generic_fetcher import GenericFetcher
from src.extractors.x_extractor import XExtractor
from src.extractors.generic_extractor import GenericExtractor
from src.config import Config
from pathlib import Path
from typing import Dict
import re
from datetime import datetime
import json
import hashlib


class ArticleExtractor:
    """抓取 + 提取引擎（不含 LLM）"""

    def __init__(self):
        self.x_fetcher = XFetcher()
        self.x_fetcher_backup = XFetcherBackup()
        self.x_extractor = XExtractor()
        self.generic_fetcher = GenericFetcher()
        self.generic_extractor = GenericExtractor()

    def process_url(self, url: str, save_to_file: bool = True) -> dict:
        """
        抓取并提取 URL，保存原始素材供宿主 agent 进一步生成内容

        Args:
            url: 文章链接
            save_to_file: 是否把提取结果保存到 output/

        Returns:
            dict: 提取结果（正文、元数据、媒体、语言等）
        """
        print(f"\n{'='*60}")
        print(f"开始处理 URL: {url}")
        print(f"{'='*60}\n")

        # 1. 识别平台
        platform = self._identify_platform(url)
        print(f"识别平台: {platform}")

        if platform == "x.com":
            return self._process_x_url(url, save_to_file)
        elif platform == "generic":
            return self._process_generic_url(url, save_to_file)
        else:
            raise ValueError(f"暂不支持的平台: {platform}")

    def _identify_platform(self, url: str) -> str:
        """识别 URL 平台"""
        if "x.com" in url or "twitter.com" in url:
            return "x.com"
        return "generic"

    def _process_x_url(self, url: str, save_to_file: bool) -> dict:
        """处理 X 平台 URL"""

        # 1. 抓取页面 - 先尝试直接抓取，失败则使用备用方案
        print("\n[步骤 1/3] 抓取页面内容...")
        extracted = None
        use_backup = False

        try:
            html = self.x_fetcher.fetch(url)
            print(f"✓ 页面抓取完成，HTML 大小: {len(html)} 字符")

            # 2. 提取内容
            print("\n[步骤 2/3] 提取推文内容...")
            extracted = self.x_extractor.extract(html, url)

            if not extracted['tweets'] or not extracted['full_text']:
                print("⚠ 未提取到推文内容，可能遇到登录墙，切换到备用方案...")
                use_backup = True
        except Exception as e:
            print(f"✗ 直接抓取失败: {e}，切换到备用方案...")
            use_backup = True

        # 备用方案
        if use_backup:
            print("\n[使用备用抓取方案]")
            backup_result = self.x_fetcher_backup.fetch(url)

            extracted = {
                'tweets': [{
                    'order': 1,
                    'text': backup_result['text'],
                    'images': backup_result['images'],
                    'videos': backup_result['videos']
                }],
                'full_text': backup_result['text'],
                'metadata': {
                    'url': url,
                    'author': backup_result.get('author', ''),
                    'author_handle': re.search(r'x\.com/([^/]+)/', url).group(1) if re.search(r'x\.com/([^/]+)/', url) else '',
                    'created_at': backup_result.get('created_at', ''),
                    'title': backup_result.get('title') or (
                        backup_result['text'][:100] + '...'
                        if len(backup_result['text']) > 100
                        else backup_result['text']
                    )
                },
                'media': {
                    'images': backup_result['images'],
                    'videos': backup_result['videos']
                },
                'language': 'unknown',
                'is_thread': False
            }

            # 检测语言（优先使用 API 返回的 lang 字段）
            if backup_result.get('lang'):
                extracted['language'] = backup_result['lang']
            else:
                try:
                    import langdetect
                    extracted['language'] = langdetect.detect(extracted['full_text'])
                except Exception:
                    extracted['language'] = 'en'  # 默认英文

            print(f"  正文长度: {len(extracted['full_text'])} 字符")

        print(f"✓ 提取完成:")
        print(f"  - 推文数量: {len(extracted['tweets'])}")
        print(f"  - 是否为推文串: {extracted['is_thread']}")
        print(f"  - 检测语言: {extracted['language']}")
        print(f"  - 图片数量: {len(extracted['media']['images'])}")
        print(f"  - 视频数量: {len(extracted['media']['videos'])}")

        # 3. 保存原始素材
        saved_files = {}
        if save_to_file:
            print("\n[步骤 3/3] 保存提取结果...")
            saved_files = self._save_x_extraction(url, extracted)
            print(f"✓ 素材已保存到: {Config.OUTPUT_DIR}")

        return {
            "success": True,
            "platform": "x.com",
            "metadata": extracted['metadata'],
            "language": extracted['language'],
            "is_thread": extracted['is_thread'],
            "tweet_count": len(extracted['tweets']),
            "tweets": extracted['tweets'],
            "full_text": extracted['full_text'],
            "media": extracted['media'],
            "saved_files": saved_files,
            "hint": "LLM 任务（推文串整合/翻译/HTML/Banner）请由宿主 agent 参照 prompts/ 模板完成"
        }

    def _process_generic_url(self, url: str, save_to_file: bool) -> dict:
        """处理普通网页 URL"""

        # 1. 抓取页面
        print("\n[步骤 1/3] 抓取页面内容...")
        try:
            html = self.generic_fetcher.fetch(url)
            print(f"✓ 页面抓取完成，HTML 大小: {len(html)} 字符")
        except Exception as e:
            print(f"✗ 页面抓取失败: {e}")
            return {"success": False, "error": str(e)}

        # 2. 提取内容
        print("\n[步骤 2/3] 提取文章内容...")
        try:
            extracted = self.generic_extractor.extract(html, url)
            print(f"✓ 提取完成:")
            print(f"  - 标题: {extracted['title'][:50]}...")
            print(f"  - 正文长度: {len(extracted['text'])} 字符")
            print(f"  - 图片数量: {len(extracted['images'])}")
        except Exception as e:
            print(f"✗ 内容提取失败: {e}")
            return {"success": False, "error": str(e)}

        # 3. 检测语言（解析逻辑，非 LLM）
        try:
            import langdetect
            language = langdetect.detect(extracted['text'])
            print(f"  检测语言: {language}")
        except Exception as e:
            print(f"⚠ 语言检测失败: {e}，默认为英文")
            language = 'en'

        # 构造素材结构
        metadata = {
            'title': extracted['title'],
            'url': url,
            'author': extracted['metadata'].get('author', ''),
            'created_at': extracted['metadata'].get('published_time', ''),
        }
        media = {
            'images': [img['url'] for img in extracted['images']],
            'videos': []
        }

        # 保存原始素材
        saved_files = {}
        if save_to_file:
            print("\n[步骤 3/3] 保存提取结果...")
            saved_files = self._save_generic_extraction(
                url, extracted, metadata, media, language
            )
            print(f"✓ 素材已保存到: {Config.OUTPUT_DIR}")

        return {
            "success": True,
            "platform": "generic",
            "metadata": metadata,
            "language": language,
            "full_text": extracted['text'],
            "media": media,
            "saved_files": saved_files,
            "hint": "LLM 任务（翻译/HTML/Banner）请由宿主 agent 参照 prompts/ 模板完成"
        }

    # ------------------------------------------------------------------
    # 保存原始素材
    # ------------------------------------------------------------------
    def _save_x_extraction(self, url: str, extracted: dict) -> dict:
        """保存 X 提取结果（JSON + 易读的 Markdown 素材）"""
        match = re.search(r'/status/(\d+)', url)
        file_id = match.group(1) if match else datetime.now().strftime("%Y%m%d%H%M%S")
        return self._write_extraction(
            f"extract_{file_id}",
            {
                "url": url,
                "platform": "x.com",
                "metadata": extracted['metadata'],
                "language": extracted['language'],
                "is_thread": extracted['is_thread'],
                "tweet_count": len(extracted['tweets']),
                "tweets": extracted['tweets'],
                "full_text": extracted['full_text'],
                "media": extracted['media'],
            },
            title=extracted['metadata'].get('title'),
            full_text=extracted['full_text'],
            media=extracted['media'],
            extra={
                "tweets": extracted['tweets'],
                "is_thread": extracted['is_thread'],
            },
        )

    def _save_generic_extraction(self, url: str, extracted: dict, metadata: dict, media: dict, language: str) -> dict:
        """保存通用网页提取结果（JSON + 易读的 Markdown 素材）"""
        url_hash = hashlib.md5(url.encode()).hexdigest()[:8]
        return self._write_extraction(
            f"extract_{url_hash}",
            {
                "url": url,
                "platform": "generic",
                "metadata": metadata,
                "language": language,
                "title": extracted['title'],
                "full_text": extracted['text'],
                "media": media,
            },
            title=metadata.get('title'),
            full_text=extracted['text'],
            media=media,
            extra={},
        )

    def _write_extraction(self, name: str, data: dict, title: str, full_text: str, media: dict, extra: dict) -> dict:
        """写入 JSON 与 Markdown 两份原始素材，返回路径"""
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        base = f"{name}_{timestamp}"

        json_path = Config.OUTPUT_DIR / f"{base}.json"
        with open(json_path, 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False, indent=2)

        md_path = Config.OUTPUT_DIR / f"{base}.md"
        md = self._build_markdown(title, data.get('metadata', {}), data.get('language', ''),
                                  media, full_text, extra)
        with open(md_path, 'w', encoding='utf-8') as f:
            f.write(md)

        return {"json": str(json_path), "markdown": str(md_path)}

    def _build_markdown(self, title: str, metadata: dict, language: str,
                        media: dict, full_text: str, extra: dict) -> str:
        """把提取结果整理成宿主 agent 易读的 Markdown 素材源"""
        lines = []

        def add(k, v):
            if v:
                lines.append(f"- **{k}**: {v}")

        lines.append("# 提取素材（原始内容，供宿主 agent 生成最终成品）")
        lines.append("")
        lines.append("> 以下为 skill 抓取解析得到的原始素材。翻译、HTML 生成等 LLM 步骤")
        lines.append("> 由宿主 agent 参照 `prompts/` 目录模板完成，请勿改动此素材原文。")
        lines.append("")
        lines.append("## 元数据")
        add("标题", title or metadata.get('title'))
        add("作者", metadata.get('author'))
        add("作者ID", metadata.get('author_handle'))
        add("发布时间", metadata.get('created_at') or metadata.get('published_time'))
        add("原文链接", metadata.get('url'))
        add("语言", language)

        # 推文串 / 普通正文
        if extra.get('is_thread') and extra.get('tweets'):
            lines.append("")
            lines.append("## 推文串（按顺序）")
            for t in extra.get('tweets') or []:
                lines.append("")
                lines.append(f"### 推文 {t.get('order')}")
                lines.append(t.get('text', ''))
        else:
            lines.append("")
            lines.append("## 正文")
            lines.append("")
            lines.append(full_text)

        # 媒体
        images = (media or {}).get('images') or []
        videos = (media or {}).get('videos') or []
        if images or videos:
            lines.append("")
            lines.append("## 媒体资源")
            for img in images:
                lines.append(f"- 图片: {img}")
            for v in videos:
                lines.append(f"- 视频: {v}")

        lines.append("")
        lines.append("---")
        lines.append("_生成说明：以上素材由 url-to-article skill 提取。请宿主 agent 参照")
        lines.append("`prompts/x_thread.md`（推文串整合）、`prompts/translate.md`（翻译）、")
        lines.append("`prompts/full_article_html.md`、`prompts/summary_html.md`、")
        lines.append("`prompts/banner_svg.md` 完成最终输出。_")
        lines.append("")

        return "\n".join(lines)


def main():
    """主函数"""
    import sys

    if len(sys.argv) < 2:
        print("用法: python -m src.main <URL>")
        sys.exit(1)

    url = sys.argv[1]

    extractor = ArticleExtractor()
    result = extractor.process_url(url)

    if result['success']:
        print("\n提取结果摘要:")
        print(f"  - 平台: {result['platform']}")
        print(f"  - 语言: {result['language']}")
        if result['platform'] == 'x.com':
            print(f"  - 推文数: {result['tweet_count']}")
        print(f"  - 保存素材:")
        for key, path in result['saved_files'].items():
            print(f"    * {key}: {path}")
        print(f"\n提示: {result['hint']}")


if __name__ == "__main__":
    main()
