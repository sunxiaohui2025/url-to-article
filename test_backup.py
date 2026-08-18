"""测试备用抓取器"""
from src.fetchers.x_fetcher_backup import XFetcherBackup

url = "https://x.com/hwchase17/status/2085780032031760694"

fetcher = XFetcherBackup()
result = fetcher.fetch(url)

print("\n" + "="*60)
print("抓取结果:")
print("="*60)
print(f"来源: {result['source']}")
print(f"\n文本内容:\n{result['text']}")
print(f"\n图片数量: {len(result['images'])}")
if result['images']:
    print(f"图片: {result['images'][0][:100]}...")
