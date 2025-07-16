#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
多平台学术论文检索脚本
通过HTTP接口调用MCP服务来检索多个平台的学术论文，按时间排序，去重，输出JSON格式

使用方法:
1. 先启动MCP HTTP服务: python http_mcp_server.py
2. 运行此脚本: python final_paper_search.py "搜索关键词" [论文数量]

示例:
python final_paper_search.py "quantum computing" 50
python final_paper_search.py "machine learning" 30
"""

import requests
import json
import sys
import time
import hashlib
from datetime import datetime
from typing import List, Dict, Set

# 设置输出编码
if sys.platform == "win32":
    import codecs
    sys.stdout = codecs.getwriter("utf-8")(sys.stdout.detach())


class PaperSearchClient:
    """多平台学术论文检索客户端"""
    
    def __init__(self, base_url: str = "http://localhost:8011"):
        self.base_url = base_url
        self.session = requests.Session()
        self.platforms = ['arxiv', 'pubmed', 'biorxiv', 'medrxiv', 'google_scholar', 'iacr', 'semantic']
        self.seen_papers: Set[str] = set()  # 用于去重
    
    def check_server_status(self) -> bool:
        """检查MCP服务器状态"""
        try:
            response = self.session.get(f"{self.base_url}/", timeout=5)
            return response.status_code == 200
        except:
            return False
    
    def generate_paper_hash(self, title: str, authors: List[str]) -> str:
        """生成论文的唯一标识符用于去重"""
        # 标准化标题（去除空格、标点，转小写）
        normalized_title = ''.join(c.lower() for c in title if c.isalnum())
        # 标准化作者列表
        normalized_authors = ''.join(sorted([
            ''.join(c.lower() for c in author if c.isalnum()) 
            for author in authors[:2]  # 只使用前两个作者
        ]))
        # 生成哈希
        content = f"{normalized_title}_{normalized_authors}"
        return hashlib.md5(content.encode()).hexdigest()
    
    def search_platform(self, platform: str, query: str, max_results: int = 10) -> List[Dict]:
        """在单个平台搜索论文"""
        try:
            payload = {
                "query": query,
                "max_results": max_results
            }
            
            print(f"正在搜索 {platform}...")
            response = self.session.post(
                f"{self.base_url}/search/{platform}",
                json=payload,
                timeout=60
            )
            
            if response.status_code == 200:
                data = response.json()
                papers = data.get('papers', [])
                print(f"{platform} 找到 {len(papers)} 篇论文")
                return papers
            else:
                print(f"搜索 {platform} 失败: {response.status_code}")
                return []
        
        except Exception as e:
            print(f"搜索 {platform} 时出错: {e}")
            return []
    
    def search_all_platforms(self, query: str, total_papers: int = 50) -> List[Dict]:
        """搜索所有平台并合并结果"""
        all_papers = []
        
        # 计算每个平台应该搜索的论文数量
        papers_per_platform = max(10, total_papers // len(self.platforms))
        
        for platform in self.platforms:
            papers = self.search_platform(platform, query, papers_per_platform)
            
            for paper in papers:
                try:
                    # 标准化论文格式
                    standardized = self.standardize_paper(paper, platform)
                    
                    # 检查是否重复
                    paper_hash = self.generate_paper_hash(
                        standardized['title'], 
                        standardized['authors']
                    )
                    
                    if paper_hash not in self.seen_papers and standardized['title']:
                        self.seen_papers.add(paper_hash)
                        all_papers.append(standardized)
                    else:
                        print(f"跳过重复论文: {standardized['title'][:50]}...")
                
                except Exception as e:
                    print(f"处理论文时出错: {e}")
                    continue
        
        # 按年份排序（最新的在前）
        all_papers.sort(key=lambda x: x.get('year', '0'), reverse=True)
        
        return all_papers[:total_papers]
    
    def standardize_paper(self, paper: Dict, source: str) -> Dict:
        """标准化论文格式，确保符合要求的JSON格式"""
        # 处理作者
        authors_raw = paper.get('authors', '')
        if isinstance(authors_raw, str):
            if ';' in authors_raw:
                authors = [a.strip() for a in authors_raw.split(';') if a.strip()]
            elif ',' in authors_raw and len(authors_raw.split(',')) > 2:
                authors = [a.strip() for a in authors_raw.split(',') if a.strip()]
            else:
                authors = [authors_raw] if authors_raw else []
        elif isinstance(authors_raw, list):
            authors = authors_raw
        else:
            authors = []
        
        # 提取年份
        published_date = paper.get('published_date', '')
        year = ''
        if published_date:
            try:
                if 'T' in published_date:
                    year = published_date.split('T')[0].split('-')[0]
                elif '-' in published_date:
                    year = published_date.split('-')[0]
                else:
                    year = published_date[:4] if len(published_date) >= 4 else ''
                
                # 验证年份
                if year and (not year.isdigit() or int(year) < 1900 or int(year) > 2030):
                    year = ''
            except:
                year = ''
        
        # 确保所有必需字段都存在
        title = paper.get('title') or ''
        abstract = paper.get('abstract') or ''
        url = paper.get('url') or paper.get('pdf_url') or ''
        venue = paper.get('source') or source
        paper_id = paper.get('paper_id') or ''

        return {
            "title": title.strip() if title else '',
            "authors": authors,
            "abstract": abstract.strip() if abstract else '',
            "year": year,
            "url": url,
            "venue": venue,
            "citedby": paper.get('citations', 0),
            "paper_id": paper_id
        }


def main():
    """主函数"""
    if len(sys.argv) < 2:
        print("用法: python final_paper_search.py <搜索关键词> [论文数量]")
        print("示例: python final_paper_search.py 'quantum computing' 50")
        print("示例: python final_paper_search.py 'machine learning' 30")
        print()
        print("注意: 请先启动MCP HTTP服务: python http_mcp_server.py")
        sys.exit(1)
    
    query = sys.argv[1]
    total_papers = int(sys.argv[2]) if len(sys.argv) > 2 else 50
    
    print("=" * 60)
    print("多平台学术论文检索系统")
    print("=" * 60)
    print(f"搜索主题: {query}")
    print(f"目标论文数量: {total_papers}")
    print(f"支持平台: arXiv, PubMed, bioRxiv, medRxiv, Google Scholar, IACR, Semantic Scholar")
    print("-" * 60)
    
    # 创建客户端
    client = PaperSearchClient()
    
    # 检查服务器状态
    print("检查MCP服务器状态...")
    if not client.check_server_status():
        print("❌ 错误: 无法连接到MCP服务器")
        print("请先启动HTTP MCP服务器: python http_mcp_server.py")
        sys.exit(1)
    
    print("✅ MCP服务器连接正常")
    print("-" * 60)
    
    # 执行搜索
    start_time = time.time()
    papers = client.search_all_platforms(query, total_papers)
    end_time = time.time()
    
    print("-" * 60)
    print(f"🎉 搜索完成! 找到 {len(papers)} 篇不重复的论文")
    print(f"⏱️  用时: {end_time - start_time:.2f} 秒")
    
    if not papers:
        print("❌ 没有找到相关论文，请尝试其他关键词")
        sys.exit(1)
    
    # 保存结果到JSON文件
    timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
    output_file = f"papers_{query.replace(' ', '_')}_{timestamp}.json"
    
    with open(output_file, 'w', encoding='utf-8') as f:
        json.dump(papers, f, ensure_ascii=False, indent=2)
    
    print(f"💾 结果已保存到: {output_file}")
    
    # 显示统计信息
    years = [p['year'] for p in papers if p['year']]
    if years:
        print(f"📊 年份分布: {min(years)} - {max(years)}")
    
    venues = {}
    for paper in papers:
        venue = paper.get('venue', 'Unknown')
        venues[venue] = venues.get(venue, 0) + 1
    
    print("📈 来源分布:")
    for venue, count in sorted(venues.items(), key=lambda x: x[1], reverse=True):
        print(f"   {venue}: {count} 篇")
    
    # 显示前几篇论文的预览
    print("\n📄 前5篇论文预览:")
    print("=" * 60)
    for i, paper in enumerate(papers[:5], 1):
        print(f"\n{i}. {paper['title']}")
        authors_str = ', '.join(paper['authors'][:3]) if paper['authors'] else 'Unknown'
        if len(paper['authors']) > 3:
            authors_str += f' 等 {len(paper["authors"])} 位作者'
        print(f"   👥 作者: {authors_str}")
        print(f"   📅 年份: {paper['year'] or 'Unknown'}")
        print(f"   🏛️  来源: {paper['venue']}")
        print(f"   📊 引用: {paper['citedby']}")
        abstract_preview = paper['abstract'][:200] + "..." if len(paper['abstract']) > 200 else paper['abstract']
        print(f"   📝 摘要: {abstract_preview}")
    
    print(f"\n📁 完整结果请查看文件: {output_file}")
    print("=" * 60)


if __name__ == "__main__":
    main()
