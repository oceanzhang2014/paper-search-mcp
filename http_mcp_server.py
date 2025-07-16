#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
HTTP包装器服务，将MCP服务暴露为HTTP API
"""

import asyncio
import json
import sys
from datetime import datetime
from typing import List, Dict, Optional
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
import uvicorn

# 导入MCP服务的搜索函数
from paper_search_mcp.server import (
    search_arxiv,
    search_pubmed, 
    search_biorxiv,
    search_medrxiv,
    search_google_scholar,
    search_iacr,
    search_semantic
)

# 创建FastAPI应用
app = FastAPI(title="Paper Search MCP HTTP API", version="1.0.0")

# 添加CORS中间件
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# 请求模型
class SearchRequest(BaseModel):
    query: str
    max_results: int = 10
    platforms: Optional[List[str]] = None
    year: Optional[str] = None

class MultiSearchRequest(BaseModel):
    query: str
    total_papers: int = 50
    platforms: Optional[List[str]] = None

# 平台映射
PLATFORM_FUNCTIONS = {
    'arxiv': search_arxiv,
    'pubmed': search_pubmed,
    'biorxiv': search_biorxiv,
    'medrxiv': search_medrxiv,
    'google_scholar': search_google_scholar,
    'iacr': search_iacr,
    'semantic': search_semantic
}

@app.get("/")
async def root():
    """根路径"""
    return {
        "message": "Paper Search MCP HTTP API",
        "version": "1.0.0",
        "available_platforms": list(PLATFORM_FUNCTIONS.keys()),
        "endpoints": {
            "search_single": "/search/{platform}",
            "search_multi": "/search/multi",
            "platforms": "/platforms",
            "health": "/health"
        }
    }

@app.get("/health")
async def health_check():
    """健康检查端点"""
    return {
        "status": "healthy",
        "timestamp": datetime.now().isoformat(),
        "platforms": list(PLATFORM_FUNCTIONS.keys()),
        "platform_count": len(PLATFORM_FUNCTIONS)
    }

@app.get("/platforms")
async def get_platforms():
    """获取可用的搜索平台"""
    return {
        "platforms": list(PLATFORM_FUNCTIONS.keys()),
        "total": len(PLATFORM_FUNCTIONS)
    }

@app.post("/search/multi")
async def search_multiple_platforms(request: MultiSearchRequest):
    """在多个平台搜索论文并合并结果"""
    platforms = request.platforms or list(PLATFORM_FUNCTIONS.keys())

    # 验证平台
    invalid_platforms = [p for p in platforms if p not in PLATFORM_FUNCTIONS]
    if invalid_platforms:
        raise HTTPException(status_code=400, detail=f"Unsupported platforms: {invalid_platforms}")

    try:
        all_papers = []
        seen_papers = set()  # 用于去重

        # 计算每个平台应该搜索的论文数量
        papers_per_platform = max(10, request.total_papers // len(platforms))

        # 并发搜索所有平台
        tasks = []
        for platform in platforms:
            search_func = PLATFORM_FUNCTIONS[platform]

            if platform == 'semantic':
                # Semantic Scholar支持年份过滤，搜索最近几年的论文
                current_year = datetime.now().year
                year_filter = f"{current_year-5}-{current_year}"
                task = search_func(request.query, year=year_filter, max_results=papers_per_platform)
            elif platform == 'iacr':
                task = search_func(request.query, max_results=papers_per_platform, fetch_details=True)
            else:
                task = search_func(request.query, max_results=papers_per_platform)

            tasks.append((platform, task))

        # 等待所有搜索完成
        results = await asyncio.gather(*[task for _, task in tasks], return_exceptions=True)

        # 处理结果并去重
        for i, result in enumerate(results):
            platform = tasks[i][0]

            if isinstance(result, Exception):
                print(f"Platform {platform} search failed: {result}")
                continue

            if not isinstance(result, list):
                continue

            # 去重逻辑：基于标题和第一作者
            for paper in result:
                if not isinstance(paper, dict):
                    continue

                title = paper.get('title', '').strip().lower()
                authors = paper.get('authors', '')
                if isinstance(authors, str):
                    first_author = authors.split(';')[0].split(',')[0].strip().lower() if authors else ''
                elif isinstance(authors, list):
                    first_author = authors[0].strip().lower() if authors else ''
                else:
                    first_author = ''

                # 创建去重键
                dedup_key = f"{title}_{first_author}"

                if dedup_key not in seen_papers and title:
                    seen_papers.add(dedup_key)

                    # 标准化论文格式
                    standardized_paper = standardize_paper_format(paper, platform)
                    all_papers.append(standardized_paper)

        # 按年份排序（最新的在前）
        all_papers.sort(key=lambda x: x.get('year', '0'), reverse=True)

        # 限制结果数量
        all_papers = all_papers[:request.total_papers]

        return {
            "query": request.query,
            "platforms_searched": platforms,
            "total_results": len(all_papers),
            "papers": all_papers
        }

    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Multi-platform search failed: {str(e)}")

@app.post("/search/{platform}")
async def search_single_platform(platform: str, request: SearchRequest):
    """在单个平台搜索论文"""
    if platform not in PLATFORM_FUNCTIONS:
        raise HTTPException(status_code=400, detail=f"Unsupported platform: {platform}")

    try:
        search_func = PLATFORM_FUNCTIONS[platform]

        # 根据平台调用相应的搜索函数
        if platform == 'semantic' and request.year:
            papers = await search_func(request.query, year=request.year, max_results=request.max_results)
        elif platform == 'iacr':
            papers = await search_func(request.query, max_results=request.max_results, fetch_details=True)
        else:
            papers = await search_func(request.query, max_results=request.max_results)

        return {
            "platform": platform,
            "query": request.query,
            "total_results": len(papers),
            "papers": papers
        }

    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Search failed: {str(e)}")

def standardize_paper_format(paper: Dict, source: str) -> Dict:
    """标准化论文格式"""
    # 处理作者
    authors_raw = paper.get('authors', '')
    if isinstance(authors_raw, str):
        if ';' in authors_raw:
            authors = [a.strip() for a in authors_raw.split(';') if a.strip()]
        elif ',' in authors_raw:
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
        except:
            year = ''
    
    # 安全处理可能为None的字段
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
        "venue": venue,
        "url": url,
        "citedby": paper.get('citations', 0),
        "paper_id": paper_id
    }

if __name__ == "__main__":
    print("Starting Paper Search MCP HTTP Server...")
    print("Available platforms:", list(PLATFORM_FUNCTIONS.keys()))
    print("Server will be available at: http://localhost:8011")
    print("API documentation at: http://localhost:8011/docs")

    # 配置更长的超时时间来处理慢速搜索请求
    uvicorn.run(
        app,
        host="0.0.0.0",
        port=8011,
        log_level="info",
        timeout_keep_alive=120,  # 保持连接120秒
        timeout_graceful_shutdown=30  # 优雅关闭超时30秒
    )
